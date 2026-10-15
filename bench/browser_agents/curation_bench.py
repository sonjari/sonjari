"""8차 실측 묶음 — 모델 큐레이션 M4 + 분야 버튼 A2 (2026-09-15, 사용자님 승인 「3번까지만」).

    .venv\\Scripts\\python.exe bench/browser_agents/curation_bench.py            # 전부
    .venv\\Scripts\\python.exe bench/browser_agents/curation_bench.py --only a2  # 분야 A/B 만

★ 운영 온텔릭(8091)을 쓴다 — 벤치가 실제 크롬·실제 사이트로 돌기 때문. 그래서:
  1. 시작 전에 되돌릴 것을 **파일로** 떠 둔다(data/settings.json · 분야 선택). 모델은 swap_chat_model.ps1 이 떠 둔다.
  2. `model_selection.json` 이 있거나 settings.json 에 model_chat 이 있으면 **멈춘다** — 그 값이 교체를 이겨
     엉뚱한 모델로 재게 된다(swap 스크립트가 라이브 모델 이름을 읽어 한 번 더 확인한다).
  3. 끝나면(실패해도) 모델·설정·분야를 되돌리고, 시험 모델을 GPU 에서 내리고, 운영 모델을 다시 올린다.

과제·채점은 multiturn_bench.py 그대로(조사→파일 사슬 5과제, 기계 채점). 모델 칸은 과제당 3판.
결과: results/multiturn_<이름표>.json 과 요약 results/curation_2026-09-15.json.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = Path(r"C:\RoboMetaFit\tools\alture-jarvis")
BASE = "http://127.0.0.1:8091"
OLLAMA = "http://127.0.0.1:11434"
TOKEN = (RUNTIME / "data" / "control.token").read_text(encoding="utf-8").strip()
RESULTS = HERE / "results"
SAVE = RESULTS / ".curation_restore"

MODELS = [  # (이름표, 태그, 컨텍스트) — 큐레이션 6절 1~3번. 31B 는 안 한다(사용자님).
    ("qwen35_9b_32k", "qwen3.5:9b", 32768),
    ("qwen35_4b_32k", "qwen3.5:4b", 32768),
    ("gemma4_12b_qat_32k", "gemma4:12b-it-qat", 32768),
]
SKILL_TASKS = ("resume_skill", "competitor_skill")
A2_DOMAINS = ["career", "research"]

sys.stdout.reconfigure(encoding="utf-8")


def api(method: str, path: str, body: dict | None = None, *, base: str = BASE, timeout: float = 60, token: bool = True):
    request = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("X-JARVIS-TOKEN", TOKEN)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def log(message: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


def swap(model: str | None) -> str:
    args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HERE / "swap_chat_model.ps1")]
    args += ["-Restore"] if model is None else ["-Model", model]
    done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    log(f"swap {model or 'restore'} -> exit {done.returncode}: {(done.stdout or '').strip()[-200:]}")
    if done.returncode != 0:
        raise RuntimeError(f"swap failed: {done.stderr[-300:]}")
    return done.stdout


def wait_backend(limit: float = 240) -> None:
    deadline = time.time() + limit
    while time.time() < deadline:
        try:
            if api("GET", "/health", token=False, timeout=10).get("ok"):
                return
        except Exception:
            time.sleep(3)
    raise RuntimeError("backend did not come back")


def ensure_pulled(tag: str) -> None:
    names = {m.get("name") for m in api("GET", "/api/tags", base=OLLAMA, token=False).get("models") or []}
    if tag in names or f"{tag}:latest" in names:
        log(f"{tag} already present")
        return
    log(f"pulling {tag} …")
    started = time.time()
    api("POST", "/api/pull", {"model": tag, "stream": False}, base=OLLAMA, token=False, timeout=7200)
    log(f"pulled {tag} in {time.time() - started:.0f}s")


def unload(tag: str) -> None:
    try:
        api("POST", "/api/generate", {"model": tag, "keep_alive": 0, "prompt": ""}, base=OLLAMA, token=False, timeout=120)
    except Exception:
        pass


def run_bench(tag: str, rounds: int, only: str = "") -> Path:
    env = {**os.environ, "MT_TAG": tag, "PYTHONIOENCODING": "utf-8"}
    args = [str(HERE / ".venv" / "Scripts" / "python.exe"), str(HERE / "multiturn_bench.py"), str(rounds)]
    if only:
        args.append(only)
    log(f"bench {tag} rounds={rounds} {only}")
    with (RESULTS / f"curation_{tag}.log").open("a", encoding="utf-8") as handle:
        subprocess.run(args, env=env, stdout=handle, stderr=subprocess.STDOUT, timeout=6 * 3600)
    return RESULTS / f"multiturn_{tag}.json"


def summarize(path: Path) -> dict:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    walls = [r.get("wall_sec") for r in rows if isinstance(r.get("wall_sec"), (int, float))]
    return {
        "n": len(rows),
        "chain_ok": sum(1 for r in rows if r.get("chain_ok")),
        "format_ok": sum(1 for r in rows if r.get("format_ok")),
        "unsupported_numbers": sum(len(r.get("unsupported") or []) for r in rows),
        "with_skills": sum(1 for r in rows if r.get("skills")),
        "skills": sorted({s for r in rows for s in r.get("skills") or []}),
        "median_wall_sec": round(statistics.median(walls), 1) if walls else None,
        "by_task": {t: {"chain_ok": sum(1 for r in rows if r.get("task") == t and r.get("chain_ok")),
                        "n": sum(1 for r in rows if r.get("task") == t)}
                    for t in sorted({r.get("task") for r in rows})},
    }


def save_state() -> dict:
    SAVE.mkdir(parents=True, exist_ok=True)
    data = RUNTIME / "data"
    if (data / "model_selection.json").exists():
        raise SystemExit("data/model_selection.json 이 있다 — 모델 교체를 이겨 엉뚱한 모델로 잰다. 멈춘다.")
    settings = data / "settings.json"
    state = {"settings_existed": settings.exists(), "domains": api("GET", "/v1/skills/domains").get("selected") or []}
    if settings.exists():
        values = json.loads(settings.read_text(encoding="utf-8") or "{}")
        if any(k in values for k in ("model_chat", "model_vision", "model_code")):
            raise SystemExit("settings.json 에 모델 값이 있다 — 교체를 이긴다. 멈춘다.")
        shutil.copy2(settings, SAVE / "settings.json")
    (SAVE / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return state


def restore_state(state: dict) -> None:
    settings = RUNTIME / "data" / "settings.json"
    if state.get("settings_existed"):
        shutil.copy2(SAVE / "settings.json", settings)
    elif settings.exists():
        settings.unlink()
    log(f"settings restored (existed={state.get('settings_existed')})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["a2", "m4", ""], default="")
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()
    state = save_state()
    summary: dict = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "rounds": args.rounds, "runs": {}}
    out = RESULTS / "curation_2026-09-15.json"
    swapped = False
    try:
        if args.only in ("", "a2"):
            # A2 — 운영 모델(26B) 그대로, 스킬 과제 둘만. 끔 = 분야 비움(전부 후보) / 켬 = 취업·조사만 후보.
            api("PATCH", "/v1/settings", {"values": {"skills_domains": [], "skills_route_enabled": True}})
            for task in SKILL_TASKS:
                run_bench("a2_domains_off", args.rounds, task)
            summary["runs"]["a2_domains_off"] = summarize(RESULTS / "multiturn_a2_domains_off.json")
            api("POST", "/v1/skills/domains", {"domains": A2_DOMAINS})
            for task in SKILL_TASKS:
                run_bench("a2_domains_on", args.rounds, task)
            summary["runs"]["a2_domains_on"] = summarize(RESULTS / "multiturn_a2_domains_on.json")
            out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
            api("POST", "/v1/skills/domains", {"domains": state["domains"]})

        if args.only in ("", "m4"):
            for tag, model, ctx in MODELS:
                ensure_pulled(model)
                api("PATCH", "/v1/settings", {"values": {"ollama_num_ctx": str(ctx)}})
                swap(model)  # 재기동 — 컨텍스트 설정도 이때 먹는다
                swapped = True
                wait_backend()
                health = api("GET", "/health", token=False)
                summary["runs"][tag] = {"live_model": (health.get("ollama") or {}).get("model"), "num_ctx": ctx}
                run_bench(tag, args.rounds)
                summary["runs"][tag].update(summarize(RESULTS / f"multiturn_{tag}.json"))
                out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
                unload(model)
    finally:
        if not swapped:
            try:  # 재기동이 없으니 메모리 값도 되돌린다 — 파일은 그 뒤에 원본으로 덮는다
                api("POST", "/v1/skills/domains", {"domains": state["domains"]})
            except Exception:
                pass
        restore_state(state)
        if swapped:
            try:
                swap(None)  # 재기동 — 되돌린 settings.json 을 이때 읽는다
            except Exception as exc:  # noqa: BLE001
                log(f"★ restore swap failed: {exc} — run swap_chat_model.ps1 -Restore by hand")
        summary["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"done -> {out}")


if __name__ == "__main__":
    main()
