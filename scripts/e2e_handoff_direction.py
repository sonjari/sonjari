"""W0 라이브 재현 — 이어오기 방향 계약 (2026-09-15).

이름 바꾼 앱 E2E 와 같은 격리: 빈 런타임 루트 · 포트 8093 · 가짜 홈 · `JARVIS_*` 제거.
운영 자비스(8091)·실제 `~/.claude` 는 건드리지 않는다. Ollama(11434)만 같이 쓴다.

가짜 홈에 **합성** Claude Code 한도 로그를 쓰고, 백엔드 API 로 캡슐과 같은 순서를 밟는다:
  /v1/takeover/sessions → /pick → /{id}/cowork(direction) → /v1/chat(prompt·display_prompt·handoff_direction)
그리고 잡이 끝날 때까지 기다려 걸음 수·쓰기 도구·새 파일·시간을 적는다.

    python scripts/e2e_handoff_direction.py --root C:\\RoboMetaFit\\tools\\e2e_w0 --directions tasks review continue

`--legacy` 를 주면 같은 인계문을 `handoff_direction` 없이 보낸다(고치기 전 요청 모양 — 반대쪽 표본).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PORT = 8093
MODEL_TAG = ""
BASE = f"http://127.0.0.1:{PORT}"
WRITE_TOOLS = {
    "local_write_document", "local_write_file", "local_apply_edit", "sandbox_run",
    "artifact_from_observations", "local_run_project_command", "local_write_spreadsheet",
}


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(epoch))


def write_synthetic_log(home: Path, work: Path) -> Path:
    """E2E 와 같은 모양의 합성 한도 로그. 할 일에 계산·검증·엑셀이 들어 있다(버그를 부르던 낱말)."""
    work.mkdir(parents=True, exist_ok=True)
    (work / "vat_2026Q3.csv").write_text("월,매출,매입\n7,12000000,4000000\n8,9000000,3000000\n9,15000000,6000000\n",
                                         encoding="utf-8")
    (work / "README.md").write_text("# 3분기 부가세 신고 준비\n\n- 매출·매입 합계 확인\n- 신고서 초안\n", encoding="utf-8")
    at = time.time() - 240
    cwd = str(work)
    base = {"sessionId": "e2e-w0", "cwd": cwd}
    rows = [
        {**base, "type": "custom-title", "customTitle": "3분기 부가세 신고 준비"},
        {**base, "type": "user", "timestamp": _iso(at - 900),
         "message": {"role": "user", "content": "3분기 부가세 신고 자료 정리해줘"}},
        {**base, "type": "assistant", "timestamp": _iso(at - 800), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "TaskCreate", "input": {"subject": "부가세 계산 확인", "description": "", "activeForm": ""}},
            {"type": "tool_use", "name": "TaskCreate", "input": {"subject": "검증", "description": "", "activeForm": ""}},
            {"type": "tool_use", "name": "TaskCreate", "input": {"subject": "신고서 엑셀 정리", "description": "", "activeForm": ""}},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": f"{cwd}/README.md", "old_string": "a", "new_string": "b"}},
        ]}},
        {**base, "type": "assistant", "timestamp": _iso(at - 500), "message": {"role": "assistant", "content": [
            {"type": "text", "text": "매출·매입 합계를 계산해 검증하고 엑셀 표로 만들겠습니다."}]}},
        {**base, "type": "user", "timestamp": _iso(at - 400),
         "message": {"role": "user", "content": "부가세 계산 확인하고 엑셀로 정리해줘"}},
        {**base, "type": "assistant", "timestamp": _iso(at), "isApiErrorMessage": True, "error": "rate_limit",
         "apiErrorStatus": 429, "message": {"role": "assistant", "content": [
             {"type": "text", "text": "You've hit your limit · resets 6am"}]}},
    ]
    path = home / ".claude" / "projects" / "e2e-w0" / "hit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8") + b"\n")
    return path


def _call(method: str, path: str, token: str, body: dict[str, Any] | None = None, timeout: float = 60) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-JARVIS-TOKEN", token)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def start_backend(root: Path, home: Path, log: Path) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    env.update({
        "JARVIS_RUNTIME_ROOT": str(root / "runtime"),
        "JARVIS_PORT": str(PORT),
        "USERPROFILE": str(home), "HOME": str(home),
        "PYTHONPATH": str(REPO / "src"),
        "PYTHONIOENCODING": "utf-8",
        # 운영과 부딪히는 장치는 끈다(F9 단축키·마이크·스피커·카메라·예약).
        "JARVIS_HOTKEY_ENABLED": "0", "JARVIS_VOICE_ENABLED": "0", "JARVIS_TTS_ENABLED": "0",
        "JARVIS_VISION_ENABLED": "0", "JARVIS_CAMERA_ENABLED": "0", "JARVIS_SCHEDULER_ENABLED": "0",
        "JARVIS_WATCHES_ENABLED": "0", "JARVIS_STARTUP_WARMUP_ENABLED": "0", "JARVIS_TTS_WARMUP_ENABLED": "0",
        # 운영 러너와 같은 창 — 갈리면 Ollama 가 러너를 새로 띄워 운영 모델을 쫓아낸다.
        "JARVIS_OLLAMA_NUM_CTX": "131072",
    })
    if MODEL_TAG:
        # 이 PC 운영 자비스가 쓰는 태그와 맞추면 러너 하나를 같이 쓴다. 태그가 다르면 digest 가 같아도
        # Ollama 가 러너를 갈아 끼워 서로 축출하고, 그 재적재 시간이 판 시간에 섞인다(W0 1·2회차 실측).
        env["JARVIS_OLLAMA_CHAT_MODEL"] = MODEL_TAG
        env["JARVIS_OLLAMA_VISION_MODEL"] = MODEL_TAG
    handle = log.open("wb")
    return subprocess.Popen([str(REPO / ".venv" / "Scripts" / "python.exe"), "-m", "alture_jarvis"],
                            cwd=str(root), env=env, stdout=handle, stderr=subprocess.STDOUT)


def wait_health(timeout: float = 180) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return _call("GET", "/health", "", timeout=5)
        except Exception:
            time.sleep(2)
    raise RuntimeError("backend did not become healthy")


def files_under(paths: list[Path]) -> set[str]:
    out: set[str] = set()
    for base in paths:
        if base.exists():
            out |= {str(p) for p in base.rglob("*") if p.is_file()}
    return out


def run_one(direction: str, token: str, session_path: str, watch: list[Path], *, legacy: bool) -> dict[str, Any]:
    picked = _call("POST", "/v1/takeover/pick", token, {"session_path": session_path})
    tid = int(picked["takeover_id"])
    prepared = _call("POST", f"/v1/takeover/{tid}/cowork", token, {"direction": direction, "custom": ""})
    assert prepared.get("ok"), prepared
    title = picked["card"].get("title") or "작업"
    phrase = {"review": "먼저 검토해줘", "tasks": "남은 일로 정리해줘"}.get(direction, "멈춘 자리부터 이어서 해줘")
    visible = f"{prepared.get('tool_name') or 'Claude Code'}에서 멈춘 「{title}」을 {phrase}"
    body = {
        "prompt": prepared["prompt"], "display_prompt": visible, "session_id": f"e2e-w0-{direction}-{int(time.time())}",
        "delivery": "screen", "origin": "workspace", "agent_mode": "auto", "workspace_mode": "cowork",
        "open_results": False,
    }
    if not legacy:
        body["handoff_direction"] = prepared.get("direction") or direction
    before = files_under(watch)
    started = time.time()
    job = _call("POST", "/v1/chat", token, body)
    job_id = job["id"]
    final: dict[str, Any] = {}
    while time.time() - started < 900:
        final = _call("GET", f"/v1/jobs/{job_id}", token, timeout=30)
        if final.get("status") in {"completed", "failed", "cancelled", "waiting_approval", "waiting_continuation"}:
            break
        time.sleep(3)
    elapsed = round(time.time() - started, 1)
    result = final.get("result") or {}
    trace = result.get("agent_trace") or {}
    steps = trace.get("steps") or []
    tools = [str(s.get("tool") or "") for s in steps]
    # outputs/thinking 은 판마다 남는 자비스 자신의 생각 기록이다 — 산출물이 아니다.
    new_files = sorted(p for p in files_under(watch) - before if "\\outputs\\thinking\\" not in p)
    return {
        "direction": direction, "legacy": legacy, "job_id": job_id, "status": final.get("status"),
        "elapsed_sec": elapsed, "steps": len(steps), "tools": tools,
        "write_tools": [t for t in tools if t in WRITE_TOOLS],
        "new_files": new_files,
        "plan": trace.get("plan") or {},
        "answer_head": str(result.get("answer") or "")[:400],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--directions", nargs="+", default=["tasks", "review", "continue"])
    ap.add_argument("--legacy", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--model", default="", help="chat/vision tag override (match the resident runner)")
    args = ap.parse_args()
    global MODEL_TAG
    MODEL_TAG = args.model
    root = Path(args.root)
    home = root / "home"
    work = home / "Documents" / "tax_q3"
    root.mkdir(parents=True, exist_ok=True)
    session_path = str(write_synthetic_log(home, work))
    proc = start_backend(root, home, root / "backend.log")
    rows: list[dict[str, Any]] = []
    try:
        health = wait_health()
        token = (root / "runtime" / "data" / "control.token").read_text(encoding="utf-8-sig").strip()
        print("health", health.get("build"), health.get("ollama", {}).get("roles"), flush=True)
        watch = [work, root / "runtime" / "outputs", home / "Documents", home / "Desktop", home / "Downloads"]
        for direction in args.directions:
            row = run_one(direction, token, session_path, watch, legacy=args.legacy)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            rows.append(row)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
