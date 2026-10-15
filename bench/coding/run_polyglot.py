"""바깥 과제로 모델을 견준다 — Aider 폴리글랏 벤치의 파이썬 과제 34개 (2026-10-08, 대표: 「외부 과제 한번 들고오자」).

우리 사다리는 우리 하네스에 맞춰 만든 과제라 큰 모델 둘이 다 통과한다(못 가린다). 이 과제들은 Exercism 의 어려운 문제를
모아 둔 것이고 과제 하나가 폴더 하나다 — 설명 · 빈 함수 · 시험 파일.

- 과제 원본은 이 PC 의 `Documents\\bench_external\\polyglot-benchmark` 에만 둔다(저장소에 넣지 않는다 — 라이선스 표기가 없다).
- 모델에게 주는 폴더에는 설명(`INSTRUCTIONS.md`) · 빈 함수 · 시험 파일만 복사한다. **모범 답안(`.meta/example.py`)은 안 준다.**
- 채점: 판이 끝난 뒤 시험 파일을 원본으로 되돌려 놓고 pytest 를 돌린다(모델이 시험을 고쳐도 소용없다).
- 과제마다 새 폴더 · 새 세션 · MCP 출처(소리 없음) · 코드 모드. 판 전체 JSON 을 남긴다.
- Aider 가 공개하는 순위 점수와는 견줄 수 없다 — 그쪽은 여섯 언어 225개를 Aider 로, 두 번 시도로 잰다.

사용: python run_polyglot.py <결과.json> <창 크기> [과제=a,b,…] [판당 상한 초=600]
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

# 출력을 파일로 돌리면 윈도우가 cp949 로 써서 줄표 하나에 죽는다(다섯 모델 모두 마지막 요약 줄에서 종료 값 1 — 결과는 저장된 뒤였다).
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8091"
TOKEN = Path(r"C:\RoboMetaFit\tools\alture-jarvis\data\control.token").read_text(encoding="utf-8").strip()
H = {"X-JARVIS-TOKEN": TOKEN}
PYTHON = r"C:\RoboMetaFit\tools\alture-jarvis\.venv\Scripts\python.exe"
SOURCE = Path.home() / "Documents" / "bench_external" / "polyglot-benchmark" / "python" / "exercises" / "practice"
OUT = Path(sys.argv[1])
CTX = int(sys.argv[2])
ONLY = [name for name in (sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[3] else []) if name]
CAP = int(sys.argv[4]) if len(sys.argv) > 4 else 600
ROOT = Path.home() / "Documents" / "bench_polyglot" / OUT.stem
PROMPT = ("{folder} 폴더의 INSTRUCTIONS.md 를 읽고 {solution} 를 구현해서 {tests} 의 테스트를 전부 통과시켜. "
          "테스트 파일은 고치지 마. pytest 로 통과를 확인해.")
DONE = {"completed", "failed", "cancelled", "waiting_continuation", "waiting_approval"}


def loaded() -> str:
    models = httpx.get("http://127.0.0.1:11434/api/ps", timeout=10).json().get("models") or []
    return " | ".join(f"{m.get('name')} ctx={m.get('context_length')} vram={round((m.get('size_vram') or 0) / 2**30, 1)}GB" for m in models)


def seed(name: str, folder: Path) -> tuple[list[str], list[str]]:
    source = SOURCE / name
    files = json.loads((source / ".meta" / "config.json").read_text(encoding="utf-8")).get("files") or {}
    solution, tests = list(files.get("solution") or []), list(files.get("test") or [])
    folder.mkdir(parents=True)
    for relative in solution + tests:
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    docs = [source / ".docs" / part for part in ("introduction.md", "instructions.md", "instructions.append.md")]
    (folder / "INSTRUCTIONS.md").write_text("\n\n".join(doc.read_text(encoding="utf-8") for doc in docs if doc.exists()), encoding="utf-8")
    return solution, tests


def grade(name: str, folder: Path, tests: list[str]) -> dict:
    for relative in tests:  # 원본 시험으로 되돌린다
        shutil.copyfile(SOURCE / name / relative, folder / relative)
    try:
        done = subprocess.run([PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests], cwd=folder,
                              capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"passed": False, "why": "채점 pytest 가 180초 안에 안 끝남"}
    tail = (done.stdout or "").strip().splitlines()[-1:] or [""]
    return {"passed": done.returncode == 0, "why": tail[0][:200]}


def main() -> None:
    names = ONLY or sorted(path.name for path in SOURCE.iterdir() if path.is_dir())
    results: list[dict] = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    finished = {row["task"] for row in results}
    for name in names:
        if name in finished:
            continue
        folder = ROOT / name
        if folder.exists():
            shutil.rmtree(folder)
        solution, tests = seed(name, folder)
        record = {"task": name, "folder": str(folder), "runner_before": loaded(), "ctx": CTX}
        body = {"prompt": PROMPT.format(folder=folder, solution=" · ".join(solution), tests=" · ".join(tests)),
                "origin": "mcp", "display_prompt": f"바깥 과제 {name}", "open_results": False,
                "session_id": f"bench-polyglot-{name}-{time.strftime('%H%M%S')}",
                "workspace_mode": "code", "code_workspace": str(folder)}
        started = time.time()
        job_id = str(httpx.post(f"{BASE}/v1/chat", json=body, headers=H, timeout=60).json().get("id") or "")
        state: dict = {}
        began = 0.0  # 판이 **실제로 돌기 시작한** 때 — 상한은 여기서부터 잰다
        while job_id:
            time.sleep(5)
            state = httpx.get(f"{BASE}/v1/jobs/{job_id}", headers=H, timeout=30).json()
            if state.get("status") in DONE:
                # ★ 2026-10-12: 「계속할까요」로 선 판을 끝으로만 세고 닫지 않았더니, 그 판이 다시 이어 돌며 일꾼을 잡아
                #   다음 과제가 5분 동안 시작을 못 했다(dominoes → forth). 물어 보며 선 판은 여기서 닫는다.
                if str(state.get("status") or "").startswith("waiting_"):
                    httpx.post(f"{BASE}/v1/jobs/{job_id}/cancel", headers=H, timeout=30)
                break
            if not began and state.get("started_at"):
                began = time.time()
            # ★ 2026-10-08: 앞 판을 끊어도 일꾼이 안 풀려 다음 판이 10분 동안 시작도 못 한 적이 있다(시간 제한에 걸린 명령의
            #   손자 프로세스 — 고침 35d61e9d). 그 판이 「0걸음 실패」로 섞였다. 줄 선 시간은 상한에 넣지 않고 따로 적으며,
            #   5분 넘게 시작을 못 하면 이 측정 자체를 멈춘다(일꾼이 막힌 것이다).
            if not began and time.time() - started > 300:
                record["never_started"] = True
                httpx.post(f"{BASE}/v1/jobs/{job_id}/cancel", headers=H, timeout=30)
                break
            if began and time.time() - began > CAP:
                record["timeout"] = True
                httpx.post(f"{BASE}/v1/jobs/{job_id}/cancel", headers=H, timeout=30)
                time.sleep(8)
                state = httpx.get(f"{BASE}/v1/jobs/{job_id}", headers=H, timeout=30).json()
                break
        if record.get("never_started"):
            record.update({"job_id": job_id, "status": "never_started"})
            results.append(record)
            OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{name}: 5분 동안 시작을 못 했다 — 일꾼이 막힌 것으로 보고 측정을 멈춘다", flush=True)
            return
        try:
            record["wait_sec"] = round(float(state.get("started_at")) - float(state.get("created_at")), 1)
        except (TypeError, ValueError):
            record["wait_sec"] = None
        OUT.with_name(f"{OUT.stem}_{name}_job.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        result = state.get("result") or {}
        steps = (result.get("agent_trace") or {}).get("steps") or result.get("steps") or []
        try:
            work = round(float(state.get("finished_at") or time.time()) - float(state.get("started_at") or started), 1)
        except (TypeError, ValueError):
            work = round(time.time() - started, 1)
        verdict = grade(name, folder, tests)
        record.update({"job_id": job_id, "status": state.get("status"), "error": str(state.get("error") or "")[:120],
                       "work_sec": work, "steps": len(steps), "failed_steps": sum(1 for step in steps if not step.get("ok")),
                       "grade": verdict, "runner_after": loaded()})
        results.append(record)
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{name}: {'통과' if verdict['passed'] else '실패'} · {work}초 · {len(steps)}걸음 · 상태 {record['status']} · {verdict['why'][:70]}", flush=True)
        time.sleep(5)
    passed = sum(1 for row in results if (row.get("grade") or {}).get("passed"))
    print(f"끝 — {passed}/{len(results)} 통과", flush=True)


if __name__ == "__main__":
    main()
