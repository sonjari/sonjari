"""W1-7 합격 시험 — 진짜 앱(Tauri exe + 동봉 파이썬 + 백엔드)을 MSIX 느슨한 등록으로.

    build_app_package.ps1 → 이 스크립트(E: venv 파이썬, 패키지 밖 프로세스로 돈다)

순서: 등록 → 앱 켜기(explorer 로, 패키지 밖에서) → 동봉 백엔드 응답 → 토큰이 **전용 칸**에 생겼나 →
첫 실행 판정(마법사) → 대화 1회 → 이어받기 캡슐 준비 → MCP 잇기(시험용 설정 파일에만, 실행 별칭으로 실제로 띄워
도구 목록) → 기억 복제본 → 제거 → 전용 칸이 지워지고 복제 폴더는 남나.

지키는 것: 실제 Claude·Cursor·Codex 설정 파일에는 쓰지 않는다. 운영 자비스(8091)는 건드리지 않는다(8094 사용).
이어받기는 실제 `~/.claude` 기록을 **읽기만** 하고(패키지 앱이 실제 홈을 보는지가 시험 대상), 대화 본문은 결과에 싣지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

# ★ 창 제목·경로에 한글이 섞이면 cp949 stdout 이 여기서 죽는다 — 오늘 검사가
#   웹 판에 닿기도 전에 `windows` 줄에서 끝났다(2026-09-16 실측).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - 어떤 셸이든 찍는 것이 멈추면 안 된다
        pass

IDENTITY = "RoboMetaFit.OntelicMsixTest"


def ps(command: str, timeout: float = 180) -> str:
    # PowerShell 5.1 은 출력을 콘솔 코드페이지(여기선 cp949)로 쓴다. utf-8 로 읽으면
    # 한글이 통째로 `�` 가 된다 — 창 제목 검사가 그동안 글자 아닌 것을 보고 있었다.
    # 쓰는 쪽을 UTF-8 로 돌려놓고 읽는다.
    prelude = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
    done = subprocess.run(["powershell", "-NoProfile", "-Command", prelude + command], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    return (done.stdout or "").strip() + (("\nERR: " + done.stderr.strip()) if done.stderr.strip() else "")


def call(base: str, method: str, path: str, token: str = "", body: dict[str, Any] | None = None, timeout: float = 60) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(f"{base}{path}", data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("X-JARVIS-TOKEN", token)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


async def mcp_tool_count(entry: dict[str, Any], timeout: float = 90) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=entry["command"], args=entry["args"], env={**os.environ, **entry["env"]})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout)
            return len((await asyncio.wait_for(session.list_tools(), timeout)).tools)


#: 합격 조건. 하나라도 어기면 **올리지 않는다**(publish_update_channel.ps1 의 관문, 2026-09-18).
#: 오늘 채널에 네 번 올렸는데 앞의 두 번은 고장난 채로 나갔다 — 이 시험은 있었지만 사람이 기억해야 돌았고,
#: 무엇이 실패해도 종료 코드가 0 이라 관문이 될 수 없었다.
def _kill_engine(root: Path) -> int:
    """시험용 자리에서 도는 ollama.exe 만 끈다 — 운영 Ollama(다른 자리)는 건드리지 않는다."""
    listing = ps("Get-CimInstance Win32_Process -Filter \"Name='ollama.exe' or Name='llama-server.exe'\" | "
                 "ForEach-Object { \"$($_.ProcessId)|$($_.ExecutablePath)\" }")
    prefix = str(root).lower()
    killed = 0
    for line in listing.splitlines():
        pid, _, path = line.partition("|")
        if pid.strip().isdigit() and path.lower().startswith(prefix):
            ps(f"Stop-Process -Id {pid.strip()} -Force -ErrorAction SilentlyContinue")
            killed += 1
    return killed


def verdict(out: dict[str, Any], *, web: bool) -> list[str]:
    failed: list[str] = []

    def need(name: str, ok: bool) -> None:
        if not ok:
            failed.append(name)

    need("health", bool((out.get("health") or {}).get("ok")))
    need("token_in_private_cache", out.get("token_in_private_cache") is True)
    need("ollama_install_root_outside_app_private_store",
         bool((out.get("ollama_install_root_outside_app_private_store") or {}).get("ok")))
    need("chat", (out.get("chat") or {}).get("status") == "completed")
    tools = out.get("mcp_tools_via_alias")
    need("mcp_tools_via_alias", isinstance(tools, int) and tools > 0)
    if web:
        need("web_research_passed", out.get("web_research_passed") is True)
    if "engine_install" in out:
        engine = out.get("engine_install") or {}
        need("engine_install", engine.get("phase") == "ready" and engine.get("runner_missing") is False
             and bool(engine.get("running")))
        need("engine_apply", (out.get("engine_apply") or {}).get("ok") is True)
        need("engine_self_check", "engine" not in ((out.get("engine_self_check") or {}).get("down") or ["?"]))
    if "private_cache_after_remove" in out:
        need("private_cache_after_remove", out.get("private_cache_after_remove") is False)
        need("backend_after_remove", out.get("backend_after_remove") == "gone")
    return failed


def _resident_model() -> tuple[str, int]:
    """지금 Ollama 에 올라가 있는 모델과 창 크기. 없으면 받아 둔 목록의 첫 대화 모델(임베딩 모델 제외)."""
    import urllib.request

    def get(path: str) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:11434{path}", timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — 못 물어보면 아래에서 멈춘다
            return {}

    for row in get("/api/ps").get("models") or []:
        name = str(row.get("name") or row.get("model") or "")
        if name:
            return name, int(row.get("context_length") or 0)
    for row in get("/api/tags").get("models") or []:
        name = str(row.get("name") or "")
        if name and "bge" not in name and "embed" not in name:
            return name, 0
    raise SystemExit("gate: Ollama 에 쓸 모델이 없다 — --model 로 지정하라")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default=r"C:\RoboMetaFit\tools\JarvisAppStage")
    ap.add_argument("--port", type=int, default=8094)
    # ★ 기본값은 **지금 이 PC 에 올라가 있는 모델과 그 창 크기**다 (2026-10-05). 예전 기본값 `plopfit-gemma4-qat` 는 09-30 에
    #   로보메타핏 작업을 끄며 지워졌고, 그 뒤 첫 게시에서 관문이 「model not found」로 떨어졌다 — 제품이 아니라 시험 설정이 낡은 것.
    #   이름을 박아 두면 모델을 바꿀 때마다 또 낡는다. 창 크기도 맞춘다: 다른 크기로 부르면 운영 모델의 러너가 밀려난다.
    ap.add_argument("--model", default="", help="비우면 지금 올라가 있는 모델(없으면 목록의 첫 대화 모델)")
    ap.add_argument("--num-ctx", type=int, default=0, help="비우면 올라가 있는 모델의 창 크기(없으면 32768)")
    ap.add_argument("--keep", action="store_true", help="do not unregister at the end")
    ap.add_argument("--update", action="store_true", help="G5: re-register a higher version over it and check user data survives")
    # ★ 「모듈 있음」 ≠ 「진짜 됨」 (2026-09-16). playwright 가 빠진 판도, 레시피·스킬이 빠진 판도
    #   여기까지의 검사는 **전부 통과했다.** 그래서 포장본으로 실제 웹 조사를 한 판 돌린다.
    ap.add_argument("--no-web", dest="web", action="store_false", help="웹 조사 한 판을 건너뛴다(빠른 확인용)")
    ap.add_argument("--web-task", default="사람인에서 여수 회계 채용 공고 2개를 찾아 회사와 마감일을 엑셀로 정리해줘")
    ap.add_argument("--web-budget", type=float, default=900.0, help="웹 조사 판을 기다리는 초")
    # ★ 새 사용자의 길 (2026-09-18). 이 PC 에는 Ollama 가 이미 떠 있어서 「온텔릭이 Ollama 를 받아서 깔아 준다」는 길을
    #   한 번도 안 탔다 — 노트북 고장이 정확히 그 길에 있었다. 떠 있는 Ollama 를 못 보게 다른 포트를 가리키고,
    #   설치 자리를 비운 채로 시작해 받기 → 러너 확인 → 켜기 → 모델 적용 → 자가 점검까지 끝까지 탄다.
    ap.add_argument("--fresh-engine", action="store_true", help="빈 자리에서 Ollama 를 받아 깔고 모델까지 적용(웹 판은 건너뜀)")
    ap.add_argument("--fresh-port", type=int, default=11500)
    ap.add_argument("--fresh-model", default="qwen3.5-9b")
    ap.add_argument("--fresh-ctx", type=int, default=32768)
    args = ap.parse_args()
    if args.fresh_engine:
        args.web = False  # 새 엔진 판은 받기·적용이 주인공이다 — 웹 판까지 얹으면 실패 자리가 흐려진다
    if not args.model:
        args.model, resident_ctx = _resident_model()
        if not args.num_ctx:
            args.num_ctx = resident_ctx
    if not args.num_ctx:
        args.num_ctx = 32768
    print(f"[gate_model] {args.model} ctx={args.num_ctx}", flush=True)
    stage = Path(args.stage)
    base = f"http://127.0.0.1:{args.port}"
    home = Path(os.environ["USERPROFILE"])
    local = Path(os.environ["LOCALAPPDATA"])
    backup_dir = home / "RoboMetaFit-msix-test" / "backup"
    fresh_engine_dir = home / "RoboMetaFit-msix-test" / "engine"
    if args.fresh_engine:
        import shutil

        _kill_engine(fresh_engine_dir)
        shutil.rmtree(fresh_engine_dir, ignore_errors=True)  # 비운 채로 시작해야 「받기」를 탄다
    out: dict[str, Any] = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    def step(name: str, value: Any) -> None:
        out[name] = value
        print(f"[{name}] {json.dumps(value, ensure_ascii=False)[:400]}", flush=True)

    manifest = stage / "app" / "AppxManifest.xml"
    step("register", ps(f"Add-AppxPackage -Register '{manifest}'; (Get-AppxPackage -Name {IDENTITY}).PackageFamilyName"))
    family = ps(f"(Get-AppxPackage -Name {IDENTITY}).PackageFamilyName").splitlines()[0].strip()
    step("family", family)
    # 새 설치는 앱 데이터 이름이 Ontelic(2026-09-15). 전용 칸에 옛 이름이 이미 있으면 그쪽(brand.runtime_dir 와 같은 규칙).
    cache_local = local / "Packages" / family / "LocalCache" / "Local"
    private = next((cache_local / n for n in ("AltureJarvis", "Ontelic") if (cache_local / n).is_dir()), cache_local / "Sonjari")

    # 시험판 백엔드 설정은 **전용 칸의 .env** 로 넣는다 — 패키지 앱에는 환경변수를 줄 수 없다.
    private.mkdir(parents=True, exist_ok=True)
    (private / ".env").write_text("\n".join([
        f"JARVIS_BACKUP_DIR={backup_dir}",
        "JARVIS_HOTKEY_ENABLED=0", "JARVIS_VOICE_ENABLED=0", "JARVIS_TTS_ENABLED=0", "JARVIS_TTS_WARMUP_ENABLED=0",
        "JARVIS_VISION_ENABLED=0", "JARVIS_CAMERA_ENABLED=0", "JARVIS_SCHEDULER_ENABLED=0", "JARVIS_WATCHES_ENABLED=0",
        "JARVIS_STARTUP_WARMUP_ENABLED=0",
        # 웹 조사 판을 돌 때만 브라우저를 켠다. 끄고 재면 「포장본이 웹을 도는가」를 아예 못 묻는다.
        f"JARVIS_BROWSER_ENABLED={1 if args.web else 0}",
        f"JARVIS_OLLAMA_CHAT_MODEL={args.model}", f"JARVIS_OLLAMA_VISION_MODEL={args.model}", f"JARVIS_OLLAMA_NUM_CTX={args.num_ctx}",
        *([f"JARVIS_OLLAMA_BASE_URL=http://127.0.0.1:{args.fresh_port}", f"JARVIS_OLLAMA_INSTALL_DIR={fresh_engine_dir}"]
          if args.fresh_engine else []),
    ]) + "\n", encoding="utf-8")

    launched = time.time()
    ps(f"Start-Process explorer.exe 'shell:AppsFolder\\{family}!App'")
    health: dict[str, Any] = {}
    while time.time() - launched < 180:
        try:
            health = call(base, "GET", "/health", timeout=5)
            break
        except Exception:
            time.sleep(1.5)
    step("backend_up_sec", round(time.time() - launched, 1) if health else None)
    if not health:
        step("hud_processes", ps("Get-Process Ontelic,python -ErrorAction SilentlyContinue | Select-Object Id,Path | Format-List | Out-String"))
        raise SystemExit("bundled backend did not answer")
    step("health", {"ok": health.get("ok"), "build": health.get("build"), "roles": (health.get("ollama") or {}).get("roles")})

    token_private = private / "data" / "control.token"
    token_real = local / private.name / "data" / "control.token"
    step("token_in_private_cache", token_private.exists())
    # ★ 이 스크립트를 띄운 셸이 Claude 데스크톱(MSIX) 안이면 AppData 가 **Claude 의 보기**다(인수인계서 4절).
    #   실제 경로는 explorer 로 띄운 cmd(어느 패키지에도 안 속함)가 봐야 한다.
    probe_out = stage / "real_view.txt"
    probe_out.unlink(missing_ok=True)
    probe_cmd = stage / "real_view.cmd"
    probe_cmd.write_text(f'@if exist "{token_real}" (echo yes> "{probe_out}") else (echo no> "{probe_out}")\r\n',
                         encoding="mbcs")
    ps(f"Start-Process explorer.exe '{probe_cmd}'")
    for _ in range(40):
        if probe_out.exists():
            break
        time.sleep(0.5)
    step("token_at_real_appdata_path_outside_any_package",
         probe_out.read_text(encoding="mbcs").strip() if probe_out.exists() else "probe did not run")
    token = token_private.read_text(encoding="utf-8-sig").strip()

    step("setup_state", call(base, "GET", "/v1/setup/state", token))
    if args.fresh_engine:
        before = call(base, "GET", "/v1/setup/ollama", token)
        step("engine_before", {k: before.get(k) for k in ("running", "can_install", "install_root", "runner_missing")})
        began = time.time()
        step("engine_install_started", call(base, "POST", "/v1/setup/ollama/install", token, {}))
        engine: dict[str, Any] = {}
        while time.time() - began < 1200:
            engine = call(base, "GET", "/v1/setup/ollama", token)
            if str((engine.get("install") or {}).get("phase") or "") in {"ready", "error"}:
                break
            time.sleep(3)
        step("engine_install", {"phase": (engine.get("install") or {}).get("phase"),
                                "error": (engine.get("install") or {}).get("error"),
                                "sec": round(time.time() - began, 1), "running": engine.get("running"),
                                "version": engine.get("version"), "runner_missing": engine.get("runner_missing"),
                                "install_root": engine.get("install_root")})
        applied = call(base, "POST", "/v1/setup/models/apply", token,
                       {"model_key": args.fresh_model, "num_ctx": args.fresh_ctx}, timeout=600)
        step("engine_apply", {"ok": applied.get("ok"), "error": applied.get("error"),
                              "tokens_per_sec": (applied.get("bench") or {}).get("tokens_per_sec"),
                              "bench_error": (applied.get("bench") or {}).get("error")})
        checked = call(base, "GET", "/v1/self-check?run=1", token, timeout=300)
        step("engine_self_check", {"down": checked.get("down"), "healable": checked.get("healable")})
    step("windows", ps("Get-Process Ontelic -ErrorAction SilentlyContinue | ForEach-Object { $_.MainWindowTitle }"))
    ollama_view = call(base, "GET", "/v1/setup/ollama", token)
    step("ollama_status", {k: v for k, v in ollama_view.items()
                           if k in ("running", "version", "can_install", "runner_missing", "install_root")})
    # ★ 2026-09-18 노트북: 앱 데이터 안에 Ollama 를 깔았더니 스토어판에서 그 파일이 앱 전용 칸으로 가고,
    #   패키지 밖 실행 파일인 Ollama 는 자기 러너를 못 봤다(파일 43개가 멀쩡히 있는데 「binary not found」).
    #   이 PC 의 pytest 는 패키지 밖에서 돌아 이 병을 **원리적으로** 못 잡는다 — 그래서 여기, 진짜 패키지 안에서 본다.
    install_root = str(ollama_view.get("install_root") or "")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    step("ollama_install_root_outside_app_private_store", {
        "install_root": install_root,
        "ok": bool(install_root) and bool(local_app_data)
              and not install_root.lower().startswith(local_app_data.lower().rstrip("\\") + "\\"),
    })

    started = time.time()
    job = call(base, "POST", "/v1/chat", token, {"prompt": "한 줄로만 자기소개해 줘.", "session_id": "msix-test",
                                                  "delivery": "screen", "origin": "workspace", "open_results": False})
    final: dict[str, Any] = {}
    while time.time() - started < 300:
        final = call(base, "GET", f"/v1/jobs/{job['id']}", token)
        if final.get("status") in {"completed", "failed", "cancelled"}:
            break
        time.sleep(2)
    step("chat", {"status": final.get("status"), "sec": round(time.time() - started, 1),
                  "answer": str((final.get("result") or {}).get("answer") or final.get("error") or "")[:160]})

    sessions = call(base, "GET", "/v1/takeover/sessions?hours=168", token).get("sessions") or []
    capsule: dict[str, Any] = {"sessions_seen": len(sessions)}
    if sessions:
        picked = call(base, "POST", "/v1/takeover/pick", token, {"session_path": sessions[0]["session_path"]})
        prepared = call(base, "POST", f"/v1/takeover/{picked.get('takeover_id')}/cowork", token, {"direction": "tasks"})
        capsule.update({"picked": bool(picked.get("ok")), "prepared": bool(prepared.get("ok")),
                        "direction": prepared.get("direction"), "prompt_chars": len(prepared.get("prompt") or "")})
    step("takeover_capsule", capsule)

    scan = call(base, "GET", "/v1/setup/connect/scan", token)
    entry = scan["entry"]
    step("mcp_entry", {"command": entry["command"], "token_file": entry["env"].get("JARVIS_TOKEN_FILE"),
                       "token_file_exists": Path(entry["env"].get("JARVIS_TOKEN_FILE", "")).exists(),
                       "pythonpath_in_entry": "PYTHONPATH" in entry["env"]})
    test_config = stage / "mcp_test_config.json"
    test_config.write_text(json.dumps({"mcpServers": {"ontelic": entry}}, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        step("mcp_tools_via_alias", asyncio.run(mcp_tool_count(entry)))
    except Exception as exc:  # noqa: BLE001
        step("mcp_tools_via_alias", f"error: {type(exc).__name__}: {str(exc)[:300]}")

    # ★ 코드가 아니라 **자료**가 빠지는 사고 (2026-09-16). recipes/·skills/ 가 통째로 안 들어갔는데
    #   앱은 멀쩡히 떴다 — 없다고 죽지 않고 **검토된 절차 대신 모델이 더듬는다.** 그날 이어받기 판이
    #   사람인 검색칸을 못 찾아 손으로 채우다 끝났고, 원인은 그 레시피가 거기 없던 것이었다.
    abilities = call(base, "GET", "/v1/capabilities")
    recipe_sites = [str(r.get("site") or r.get("name") or "") for r in (abilities.get("recipes") or [])]
    skills_view = call(base, "GET", "/v1/skills/domains", token)
    step("data_shipped", {"recipes": len(recipe_sites), "sites": recipe_sites[:6],
                          "skills_served": skills_view.get("total_served"),
                          "skill_domains": len(skills_view.get("domains") or [])})

    made = call(base, "POST", "/v1/backup/now", token, {})
    step("backup_now", {"ok": made.get("ok"), "path": made.get("path"), "tables": made.get("tables")})

    # 8차 M1~M3 — 포장본 안에서도 카드 감지·등급 추천·받아 둔 모델 판정이 도는가.
    rec = call(base, "GET", "/v1/setup/recommendation", token)
    step("recommendation", {"mode": rec.get("mode"), "tier_gb": rec.get("tier_gb"),
                            "picks": [(p.get("kind"), p.get("model_key")) for p in rec.get("picks") or []]})
    installed = call(base, "GET", "/v1/setup/models/installed", token).get("models") or []
    step("installed_models", {"count": len(installed), "with_tools": sum(1 for m in installed if m.get("tools"))})

    if args.web:
        # 한 판을 **끝까지** 돌린다. 보는 것은 세 가지다:
        #   ① 브라우저 도구가 실제로 성공한 걸음이 있는가 (playwright 가 빠지면 여기서 죽는다)
        #   ② 산출물 파일이 진짜 생겼는가 (「만들었다」는 말이 아니라 디스크의 파일)
        #   ③ 답에 도구가 준 적 없는 숫자가 있는가 (창작이면 통과시키면 안 된다)
        web_started = time.time()
        web_job = call(base, "POST", "/v1/chat", token, {
            "prompt": args.web_task, "session_id": "msix-web", "delivery": "screen",
            "origin": "workspace", "open_results": False,
        }, timeout=90)
        web_final: dict[str, Any] = {}
        while time.time() - web_started < args.web_budget:
            web_final = call(base, "GET", f"/v1/jobs/{web_job['id']}", token)
            if web_final.get("status") in {"completed", "failed", "cancelled", "needs_review"}:
                break
            time.sleep(4)
        detail = call(base, "GET", f"/v1/jobs/{web_job['id']}/steps", token)
        steps = detail.get("steps") or detail.get("items") or []
        browsed = [s for s in steps if str(s.get("tool") or "").startswith("browser_") and s.get("ok")]
        result = web_final.get("result") or {}
        # ★ 잡 결과에는 `files` 칸이 **없다**(실측으로 확인). 산출물 장부는 `/v1/outputs` 다 —
        #   없는 칸을 보면 좋은 판도 「파일 0개」로 찍혀 검사가 조용히 거짓말한다(분모 구멍).
        outputs = call(base, "GET", f"/v1/outputs?job_id={web_job['id']}", token).get("items") or []
        on_disk = [str(item.get("path")) for item in outputs if item.get("exists")]
        verification = ((result.get("agent_trace") or {}).get("verification") or {})
        step("web_research", {
            "status": web_final.get("status"),
            "sec": round(time.time() - web_started, 1),
            "steps": len(steps),
            "browser_steps_ok": len(browsed),
            "browser_tools": sorted({str(s.get("tool")) for s in browsed})[:8],
            "files_on_disk": on_disk[:4],
            # 창작 숫자는 여기서 안 센다 — 잡 결과에 그 칸이 없어서 무조건 빈 목록이 나온다.
            # 「검사가 있다」와 「그 검사가 이 종류를 잡는다」는 다른 말이다(전략안 §41).
            "verified_steps": verification.get("successful_steps"),
            "error": str(web_final.get("error") or "")[:200],
        })
        # 한 줄 판정. 이 셋이 다 서야 「포장본이 웹 조사를 한다」고 말할 수 있다.
        step("web_research_passed", bool(browsed) and bool(on_disk)
             and web_final.get("status") == "completed")

    if args.update:
        # G5 — 스토어 갱신 흉내: 같은 칸에 **더 높은 버전**을 덮어 올린 뒤 다시 켜서 사용자 값이 남는지.
        marker = f"갱신시험{int(time.time()) % 10000}"
        call(base, "PATCH", "/v1/settings", token, {"values": {"user_label": marker}})
        ps("Get-Process Ontelic -ErrorAction SilentlyContinue | Stop-Process -Force")
        ps(f"Get-CimInstance Win32_Process | Where-Object {{ $_.ExecutablePath -like '{stage}\\app\\*' }} | "
           "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
        text = manifest.read_text(encoding="utf-8")
        import re as _re
        current = _re.search(r'Version="(\d+)\.(\d+)\.(\d+)\.(\d+)"', text)
        bumped = f'Version="{current.group(1)}.{current.group(2)}.{current.group(3)}.{int(current.group(4)) + 1}"'
        manifest.write_text(text.replace(current.group(0), bumped, 1), encoding="utf-8")
        step("update_register", ps(f"Add-AppxPackage -Register '{manifest}'; (Get-AppxPackage -Name {IDENTITY}).Version"))
        relaunched = time.time()
        ps(f"Start-Process explorer.exe 'shell:AppsFolder\\{family}!App'")
        again: dict[str, Any] = {}
        while time.time() - relaunched < 180:
            try:
                again = call(base, "GET", "/health", timeout=5)
                break
            except Exception:
                time.sleep(1.5)
        rows = {r["key"]: r for r in call(base, "GET", "/v1/settings", token).get("settings") or []} if again else {}
        step("after_update", {"backend_up_sec": round(time.time() - relaunched, 1) if again else None,
                              "user_label_kept": (rows.get("user_label") or {}).get("value") == marker,
                              "token_same": token_private.exists() and token_private.read_text(encoding="utf-8-sig").strip() == token,
                              "setup_state": call(base, "GET", "/v1/setup/state", token).get("completed") if again else None})

    if not args.keep:
        step("unregister", ps(f"Get-AppxPackage -Name {IDENTITY} | Remove-AppxPackage; 'removed'"))
        time.sleep(3)
        step("private_cache_after_remove", (local / "Packages" / family).exists())
        step("backup_after_remove", sorted(p.name for p in backup_dir.iterdir()) if backup_dir.exists() else [])
        try:
            call(base, "GET", "/health", timeout=3)
            step("backend_after_remove", "still answering")
        except Exception:
            step("backend_after_remove", "gone")
    if args.fresh_engine:
        step("engine_cleanup", _kill_engine(fresh_engine_dir))
    failed = verdict(out, web=args.web)
    step("gate", {"passed": not failed, "failed": failed})
    (stage / "package_test_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
