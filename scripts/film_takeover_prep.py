"""레딧 영상 「클로드 한도 → 손자리 이어받기」 준비 (2026-10-23 대표).

대표 결정: 「한도 걸린 그 대화 기록만 데모로 만들고, 제품은 진짜 손자리가 하는 것」.
- 클로드 코드는 **진짜로** 돌린다(촬영용 홈 · 몇 걸음만 · 웹 읽기 도구만 허락). 하던 일 · 읽은 페이지는 실제 기록이다.
- 그 기록 끝에 **한도 줄 한 줄만** 붙인다 — 실제 한도 줄과 같은 모양(`isApiErrorMessage` · `error: rate_limit` · 429).
  이 한 줄이 데모다. 영상에는 「클로드 기록은 영상용으로 준비함 · 그 뒤 손자리는 편집 없는 실제 실행」이라고 밝힌다.
- 사용자님 실제 대화 기록(`~/.claude`)은 쓰지 않는다 — 촬영용 홈(`e2e_oneshot/home/.claude`)에만.

    C:\\RoboMetaFit\\tools\\alture-jarvis\\.venv\\Scripts\\python.exe scripts/film_takeover_prep.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOME = Path(r"C:\RoboMetaFit\tools\e2e_oneshot\home")
CLAUDE_DIR = HOME / ".claude"
LOGIN_FROM = Path(r"D:\bench_tmp\film_cc\config")   # 10-20 촬영 때 로그인해 둔 촬영 전용 설정
WORK = HOME / "Documents" / "trending-report"
TASK = (
    "Find today's top 3 trending Python repositories on GitHub (https://github.com/trending/python). "
    "For each one, open its repository page and note the license and the latest release. "
    "Then put name, stars, description, license and latest release into trending_python.xlsx in my Documents folder."
)


def main() -> int:
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    for name in (".credentials.json", ".claude.json"):
        shutil.copy2(LOGIN_FROM / name, CLAUDE_DIR / name)
    guide = CLAUDE_DIR / "CLAUDE.md"
    if guide.exists():   # 「손자리에게 넘겨라」 지침 — 이 장면의 클로드는 스스로 조사하다 멈춰야 한다
        guide.rename(CLAUDE_DIR / "CLAUDE.md.film_off")
    WORK.mkdir(parents=True, exist_ok=True)
    empty_mcp = CLAUDE_DIR.parent / "film_empty_mcp.json"
    empty_mcp.write_text('{"mcpServers": {}}', encoding="utf-8")
    projects = CLAUDE_DIR / "projects"
    before = set(projects.glob("*/*.jsonl")) if projects.exists() else set()

    env = dict(__import__("os").environ)
    env.update({"CLAUDE_CONFIG_DIR": str(CLAUDE_DIR), "PYTHONIOENCODING": "utf-8"})
    cmd = ["claude", "-p", TASK, "--max-turns", "7", "--allowedTools", "WebFetch", "ToolSearch",
           "--mcp-config", str(empty_mcp), "--strict-mcp-config", "--output-format", "text"]
    print("running real Claude Code (max 7 turns) ...", flush=True)
    done = subprocess.run(cmd, cwd=str(WORK), env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=600, shell=True)
    print("claude exit", done.returncode, "| out:", (done.stdout or "")[-600:], "| err:", (done.stderr or "")[-400:])

    fresh = sorted(set(projects.glob("*/*.jsonl")) - before, key=lambda p: p.stat().st_mtime)
    if not fresh:
        raise SystemExit("no new Claude transcript found")
    log = fresh[-1]
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    last = next(x for x in reversed(lines) if x.get("uuid"))
    stamp = datetime.now(timezone.utc)
    resets = int((stamp + timedelta(hours=3)).timestamp())
    limit_line = {
        "parentUuid": last["uuid"], "isSidechain": False, "type": "assistant", "uuid": str(uuid.uuid4()),
        "timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z",
        "message": {"id": str(uuid.uuid4()), "model": "<synthetic>", "role": "assistant", "stop_reason": "stop_sequence",
                    "stop_sequence": "", "type": "message",
                    "usage": {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                    "content": [{"type": "text", "text": "You've hit your session limit · resets 6:00pm (Asia/Seoul)"}]},
        "quotaLimits": {"status": "rejected", "resetsAt": resets, "rateLimitType": "five_hour", "isUsingOverage": False},
        "error": "rate_limit", "isApiErrorMessage": True, "apiErrorStatus": 429,
        "userType": "external", "entrypoint": last.get("entrypoint", "cli"), "cwd": last.get("cwd", str(WORK)),
        "sessionId": last.get("sessionId", log.stem), "version": last.get("version", ""), "gitBranch": last.get("gitBranch", ""),
        "_film_demo": "limit line added for the video (2026-10-23) - everything above it is a real Claude Code run",
    }
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(limit_line, ensure_ascii=False) + "\n")
    tools = [c.get("name") for x in lines if x.get("type") == "assistant"
             for c in (x.get("message", {}).get("content") or []) if isinstance(c, dict) and c.get("type") == "tool_use"]
    print("transcript:", log)
    print("real lines:", len(lines), "| tool calls:", tools)
    print("demo limit line appended")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
