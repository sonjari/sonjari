"""스킬 실측 (인수인계 H1 잴 것, 2026-09-16) — Claude 가 온텔릭을 **직접 부리기** vs **가이드 스킬 보고 맡기기**.

    E:\\...\\bench\\browser_agents\\.venv\\Scripts\\python.exe skill_headtohead.py [--tasks yes24_md saramin_doc resume_skill]

같은 과제 · 같은 Claude Code CLI(이 PC 로그인). 조건만 다르다:
- raw      : **온텔릭 없이** Claude 혼자 — 자기 WebSearch·WebFetch 로 찾고 자기 Write 로 파일을 만든다(기준선)
- playwright: Claude + **일반 브라우저 도구**(Playwright MCP). 브레인은 같고 **손만 다르다** — 온텔릭 도구가
             쌓아 온 것(사이트 레시피·결과 목록·본문 추출·문서 만들기)이 값어치를 하는지 여기서 갈린다
- direct   : Claude 가 브레인, 온텔릭은 손 — MCP 의 browser_*·local_* 를 Claude 가 직접 부른다(위임 문은 끔)
- delegate : 온텔릭이 브레인 — 과제를 통째로 맡기고(`ontelic_task`) 결과만 받는다. 판단은 이 PC 로컬 모델이 한다
raw 를 뺀 두 조건은 Claude 자체 웹·파일 도구를 막는다 — 손은 온텔릭 것만 쓴다.
`--dangerously-skip-permissions` 는 쓰지 않는다. 허용 목록(`--allowedTools`)만.

토큰은 설정 파일에 안 쓰고 CLI 프로세스 환경변수로만 넘긴다(자식인 MCP 서버가 물려받는다). 출력하지 않는다.

잰다: 성공(파일이 요청 형식으로 생겼나) · 비용(USD) · 토큰 · 시간 · 턴 · 도구 호출 수 ·
      Claude 최종 답의 숫자 중 **어느 도구 결과에도 없던 것**(창작) · 온텔릭 쪽 근거 없는 숫자.
★ 맡기기는 시간을 둘로 쪼갠다: `ontelic_sec`(온텔릭이 실제로 일한 시간) 과 나머지(Claude 가 묻고 기다린 몫).
  뭉뚱그리면 「로컬 모델이 느리다」와 「기다림이 길다」가 섞여 무엇을 고쳐야 하는지 안 보인다.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bench_research_tasks as B  # noqa: E402
from alture_jarvis.evidence import numbers_claimed_in  # noqa: E402

from multiturn_bench import DOCS, TASKS, read_any  # noqa: E402

RUNTIME_PY = pathlib.Path(r"C:\RoboMetaFit\tools\alture-jarvis\.venv\Scripts\python.exe")
RUNTIME_SRC = pathlib.Path(r"C:\RoboMetaFit\tools\alture-jarvis\src")
DENY = "WebSearch,WebFetch,Bash,Write,Edit,NotebookEdit,Task"
# raw 기준선은 Claude 손만 쓴다 — 웹 검색·문서 쓰기를 열고 온텔릭은 붙이지 않는다.
RAW_DENY = "Bash,Task"
RAW_ALLOW = "WebSearch,WebFetch,Write,Read,Glob,Grep"
# 일반 브라우저 도구 기준선 — 공식 Playwright MCP. 파일은 Claude 자기 Write 로 만든다(그 MCP 에 쓰기가 없다).
PW_ALLOW = "mcp__playwright,Write,Read"
PW_DENY = "WebSearch,WebFetch,Bash,Task"


def mcp_config(delegation: bool) -> str:
    config = {"mcpServers": {"ontelic": {
        "command": str(RUNTIME_PY),
        "args": ["-m", "alture_jarvis.mcp_server"],
        "env": {"PYTHONPATH": str(RUNTIME_SRC), "PYTHONIOENCODING": "utf-8",
                "JARVIS_BASE_URL": "http://127.0.0.1:8091", "JARVIS_MCP_DELEGATION": "1" if delegation else "0"},
    }}}
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(config, handle)
    handle.close()
    return handle.name


def _empty_mcp_config() -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump({"mcpServers": {}}, handle)
    handle.close()
    return handle.name


def _playwright_mcp_config() -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump({"mcpServers": {"playwright": {
        "command": "npx.cmd" if os.name == "nt" else "npx",
        "args": ["-y", "@playwright/mcp@latest", "--isolated"],
    }}}, handle)
    handle.close()
    return handle.name


def _ontelic_seconds(started: float) -> tuple[float, int]:
    """이번 판에 온텔릭이 실제로 돈 시간과 잡 수 — 맡기기 조건의 시간을 쪼개려고."""
    try:
        jobs = json.loads(urlopen("http://127.0.0.1:8091/v1/jobs?limit=20&view=summary", timeout=10).read())
    except Exception:  # noqa: BLE001
        return 0.0, 0
    total, count = 0.0, 0
    for job in jobs:
        created = float(job.get("created_at") or 0)
        finished = float(job.get("finished_at") or 0) or time.time()
        if created >= started - 2:
            total += max(0.0, finished - float(job.get("started_at") or created))
            count += 1
    return round(total, 1), count


def run(task: str, prompt: str, want: list[str], condition: str, budget: float) -> dict:
    raw = condition == "raw"
    generic = condition == "playwright"
    cfg = _empty_mcp_config() if raw else _playwright_mcp_config() if generic else mcp_config(condition == "delegate")
    env = {**os.environ, "JARVIS_CONTROL_TOKEN": B._token()}
    # ★ 「문서 폴더에」라고 적지 않는다 — 작업 폴더 밖 쓰기는 사람 승인 카드를 띄우고(정상 동작), 자동 실측은 거기서 멈춘다.
    #   온텔릭이 알아서 자기 문서 폴더에 만든다.
    full = prompt + (" 파일은 이 폴더에 만들어 줘." if raw or generic else " 파일은 온텔릭 도구로 만들어 줘.")
    before = {p: p.stat().st_mtime for p in DOCS.rglob("*") if p.is_file()} if DOCS.exists() else {}
    started = time.time()
    cmd = ["claude", "-p", full, "--mcp-config", cfg, "--strict-mcp-config", "--output-format", "stream-json",
           "--verbose",
           "--allowedTools", RAW_ALLOW if raw else PW_ALLOW if generic else "mcp__ontelic,Skill",
           "--disallowedTools", RAW_DENY if raw else PW_DENY if generic else DENY]
    workdir = tempfile.mkdtemp(prefix=f"h2h_{condition}_")
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              env=env, cwd=workdir, timeout=budget, shell=(os.name == "nt"))
        stdout, timed_out = done.stdout, False
    except subprocess.TimeoutExpired as exc:
        stdout, timed_out = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""), True
    finally:
        os.unlink(cfg)
    wall = round(time.time() - started, 1)

    tool_calls: list[str] = []
    tool_text: list[str] = []
    final = {}
    skill_used = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use":
                    tool_calls.append(str(block.get("name")))
                    if block.get("name") == "Skill":
                        skill_used = True
        elif event.get("type") == "user":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    content = block.get("content")
                    tool_text.append(json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content)
        elif event.get("type") == "result":
            final = event

    made = [p for p in DOCS.rglob("*") if p.is_file() and p.stat().st_mtime >= started - 2
            and before.get(p) != p.stat().st_mtime] if DOCS.exists() else []
    if raw or generic:
        # Claude 가 자기 손으로 만든 파일은 작업 폴더에 남는다.
        made += [p for p in pathlib.Path(workdir).rglob("*") if p.is_file()]
    blob = "\n".join(read_any(p) for p in made)
    answer = str(final.get("result") or "")
    seen_text = "\n".join(tool_text)
    seen = numbers_claimed_in(seen_text)
    claude_unsupported = sorted(numbers_claimed_in(answer) - seen)
    ontelic_unsupported: list[str] = []
    for match in re.finditer(r'"unsupported_numbers":\s*\[([^\]]*)\]', seen_text.replace('\\"', '"')):
        ontelic_unsupported += re.findall(r'"([^"]+)"', match.group(1))
    usage = final.get("usage") or {}
    ontelic_sec, ontelic_jobs = (0.0, 0) if raw or generic else _ontelic_seconds(started)
    return {
        "task": task, "condition": condition, "timed_out": timed_out, "wall_sec": wall,
        "ontelic_sec": ontelic_sec, "ontelic_jobs": ontelic_jobs,
        "waiting_sec": round(max(0.0, wall - ontelic_sec), 1) if ontelic_sec else None,
        "cost_usd": final.get("total_cost_usd"), "num_turns": final.get("num_turns"),
        "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"), "cache_write_tokens": usage.get("cache_creation_input_tokens"),
        "tool_calls": len(tool_calls), "tools": sorted(set(tool_calls)), "skill_loaded": skill_used,
        "files": [p.name for p in made], "format_ok": any(p.suffix.lower() in want for p in made), "chars": len(blob),
        "claude_unsupported": claude_unsupported[:15], "ontelic_unsupported": sorted(set(ontelic_unsupported))[:15],
        "is_error": final.get("is_error"), "answer_head": answer[:300],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", default=["yes24_md", "saramin_doc", "resume_skill"])
    ap.add_argument("--conditions", nargs="+", default=["raw", "playwright", "direct", "delegate"])
    ap.add_argument("--budget", type=float, default=1500)
    args = ap.parse_args()
    out = HERE / "results" / "skill_headtohead_2026-09-16.json"
    rows = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    table = {name: (want, prompt) for name, _host, want, prompt in TASKS}
    for task in args.tasks:
        want, prompt = table[task]
        for condition in args.conditions:
            row = run(task, prompt, want, condition, args.budget)
            rows.append(row)
            out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{task:13} {condition:8} {row['wall_sec']:>7}s (온텔릭 {row['ontelic_sec']}s) ${row['cost_usd']} turns={row['num_turns']} "
                  f"tools={row['tool_calls']} skill={row['skill_loaded']} files={row['files']} fmt={row['format_ok']} "
                  f"claude_unsup={len(row['claude_unsupported'])} ontelic_unsup={len(row['ontelic_unsupported'])}", flush=True)


if __name__ == "__main__":
    main()
