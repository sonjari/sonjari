"""붙임새 실측 — 바깥 AI 가 **부를 때 부르고, 안 부를 때 안 부르는가** (2026-09-16).

    .venv\\Scripts\\python.exe adoption_probe.py --tools claude codex [--only S1] [--repeat 1]

## 이 눈금이 재는 것 (다른 것과 헷갈리지 말 것)

9월 7일에 **비용·시간·품질**은 이미 쟀다. 여기서 재는 것은 그 앞의 질문이다:

    붙여 놨는데 **부르기는 하는가.** 그리고 안 불러야 할 때 **안 부르는가.**

9월 16일에 Codex 는 연결된 채로 온텔릭을 **0회** 부르고 「온텔릭으로 했다」고 답했다.
전역 지침 네 줄을 넣자 부르기 시작했다. 그 변화를 판(n)으로 세려고 만든다.

- `should`     : 온텔릭이 해야 하는 일(실제 브라우저·웹 조사→파일). 안 부르면 **놓친 것**이다.
- `should_not` : 지식·산수·코드 읽기. 부르면 **헛호출**이다(느려지고 돈만 든다).

## 두 쪽에서 본다 — 한쪽만 보면 속는다

    CLI 기록   : 모델이 **부르려 했는가** (그 자리에서 거절돼도 결정은 남는다)
    온텔릭 장부: `audit_log.tool_executed` 와 `jobs` — **실제로 우리 쪽에서 일이 돌았는가**

둘을 따로 적는 이유는 하나다. 「했다」는 말은 증거가 아니다 — 그 거짓말이 이 눈금을 만든 이유다.

## 알려진 한계 (결과에 그대로 싣는다)

- `codex exec` 는 비대화형이라 MCP 호출이 **승인 정책에 막힌다**(`approval policy is never`).
  우회 플래그(`--dangerously-*`)는 쓰지 않는다. 그래서 Codex 는 **부르려 한 것**까지만 재고,
  실제 수행은 대화형(사람이 승인)에서 확인한 것으로 갈음한다.
- Claude Code CLI 에는 이 PC 에서 온텔릭이 등록돼 있지 않아 `--mcp-config` 로 붙여 준다.
  자기 도구(WebSearch·Write…)는 **그대로 열어 둔다** — 고를 수 있어야 「골랐다」를 잴 수 있다.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "results" / "adoption"
RUNTIME_PY = pathlib.Path(r"C:\RoboMetaFit\tools\alture-jarvis\.venv\Scripts\python.exe")
RUNTIME_SRC = pathlib.Path(r"C:\RoboMetaFit\tools\alture-jarvis\src")
TOKEN_FILE = pathlib.Path(RUNTIME_SRC).parent / "data" / "control.token"
LIVE_DB = pathlib.Path(r"C:\RoboMetaFit\tools\alture-jarvis\data\jarvis.db")
CODEX = pathlib.Path(r"C:\Users\user\AppData\Local\OpenAI\Codex\bin\bffc5354119c8421\codex.exe")
CLAUDE = str(pathlib.Path.home() / "AppData/Roaming/npm/claude.cmd")
# Claude 에게 여는 손: 온텔릭 **과** 자기 것. 고를 수 있어야 「골랐다」가 뜻이 있다.
CLAUDE_ALLOW = "mcp__ontelic,WebSearch,WebFetch,Write,Read,Glob,Grep"

TASKS = [
    # ── 불러야 하는 일 ────────────────────────────────────────────────────────
    {"id": "S1", "kind": "should", "budget": 900,
     "prompt": "사람인에서 여수 지역 회계 채용 공고 2개를 찾아 회사명과 마감일을 엑셀 파일로 정리해 줘."},
    {"id": "S2", "kind": "should", "budget": 900,
     "prompt": "예스24에서 「클린 코드」 책의 정가와 쪽수를 찾아 워드 문서 한 장으로 정리해 줘."},
    {"id": "S3", "kind": "should", "budget": 900,
     "prompt": "내 PC 의 로그인된 크롬으로 네이버 메인에 들어가 오늘 헤드라인 기사 제목 3개를 마크다운 파일로 저장해 줘."},
    # ★ 2026-09-16 밤: S1 은 요즘 거의 다 끝나서(6판 중 5판 complete) `resume` 이 붙는 판이 안 나왔고
    #   `reopened_evidence` 를 잴 수 없었다. 이어받기 e2e 와 같은 과제(3건 + 자격 요건)는 3판 중 2판이
    #   partial 이었다 — 덜 끝나기 쉬운 과제로 「돌려준 근거를 다시 여는가」를 잰다.
    {"id": "S4", "kind": "should", "budget": 1200,
     "prompt": "사람인에서 여수 회계 채용 공고 3개를 찾아서 회사·마감일·자격 요건 비교표를 엑셀로 만들어줘."},
    # ── 부르면 안 되는 일 (헛호출) ───────────────────────────────────────────
    {"id": "N1", "kind": "should_not", "budget": 180,
     "prompt": "파이썬에서 리스트와 튜플의 차이를 세 줄로 설명해 줘."},
    {"id": "N2", "kind": "should_not", "budget": 180,
     "prompt": "88,000원이 부가세 10%가 포함된 금액일 때 공급가액과 부가세를 계산해 줘."},
    {"id": "N3", "kind": "should_not", "budget": 180,
     "prompt": "이 코드의 버그를 한 줄로 지적해 줘: def avg(xs): return sum(xs) / len(xs)"},
]


def mcp_config() -> str:
    """Claude 에게 줄 온텔릭 한 대. 토큰은 파일 경로로만 넘어간다(값을 적지 않는다)."""
    entry = {"command": str(RUNTIME_PY), "args": ["-m", "alture_jarvis.mcp_server"],
             "env": {"PYTHONPATH": str(RUNTIME_SRC), "PYTHONIOENCODING": "utf-8",
                     "JARVIS_BASE_URL": "http://127.0.0.1:8091",
                     # 토큰은 **파일 경로로만** 넘긴다. 값을 적지도 찍지도 않는다.
                     # 없으면 모든 호출이 토큰 불일치로 거부돼 「안 불렀다」처럼 보인다(눈금 역검증에서 잡았다).
                     "JARVIS_TOKEN_FILE": str(TOKEN_FILE)}}
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump({"mcpServers": {"ontelic": entry}}, handle)
    handle.close()
    return handle.name


def resume_evidence(job_ids: list[str]) -> list[str]:
    """이 판에 생긴 잡들의 `resume.evidence` — 호스트가 **이미 받은** 근거 주소."""
    if not job_ids or not LIVE_DB.exists():
        return []
    sys.path.insert(0, str(RUNTIME_SRC))
    from alture_jarvis.delegation import summarize_job  # noqa: E402 — 운영 판과 같은 코드로 만든다

    evidence: list[str] = []
    try:
        conn = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True, timeout=5)
        for job_id in job_ids:
            row = conn.execute("SELECT status, result_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                continue
            summary = summarize_job({"id": job_id, "status": row[0], "result": json.loads(row[1] or "{}")})
            evidence += list((summary.get("resume") or {}).get("evidence") or [])
        conn.close()
    except Exception:  # noqa: BLE001 — 못 읽으면 「안 줬다」로 센다(재사용 판정을 안 한다)
        return []
    return evidence


def ledger_since(started: float) -> dict[str, list[str]]:
    """온텔릭 **자기 장부**. CLI 가 뭐라 적었든 여기 없으면 우리 쪽에서 아무 일도 안 났다."""
    if not LIVE_DB.exists():
        return {"tools": [], "jobs": []}
    try:
        conn = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True, timeout=5)
        tools = [row[0] for row in conn.execute(
            "SELECT json_extract(payload_json,'$.tool') FROM audit_log"
            " WHERE event='tool_executed' AND created_at >= ?", (started - 1,))]
        jobs = [row[0] for row in conn.execute(
            "SELECT id FROM jobs WHERE created_at >= ?", (started - 1,))]
        conn.close()
    except Exception as exc:  # noqa: BLE001 — 장부를 못 읽은 것과 「없다」는 다르다
        return {"tools": [], "jobs": [], "error": f"{type(exc).__name__}: {exc}"}
    return {"tools": [t for t in tools if t], "jobs": jobs}


def run_claude(prompt: str, budget: float, config_path: str, cwd: pathlib.Path) -> dict:
    args = [CLAUDE, "-p", prompt, "--output-format", "stream-json", "--verbose",
            "--mcp-config", config_path, "--allowedTools", CLAUDE_ALLOW]
    started = time.time()
    done = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=budget, stdin=subprocess.DEVNULL)
    # 호출 **순서**만 적는다. 걸린 시각은 못 적는다 — 아래 `grade` 주석 참고.
    calls: list[str] = []
    opened: list[str] = []
    answer = ""
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if event.get("type") == "assistant":
            for part in ((event.get("message") or {}).get("content") or []):
                if isinstance(part, dict) and part.get("type") == "tool_use":
                    calls.append(str(part.get("name") or ""))
                    url = str((part.get("input") or {}).get("url") or "")
                    if url:
                        opened.append(url)
        elif event.get("type") == "result":
            answer = str(event.get("result") or "")
    return {"calls": calls, "opened": opened, "answer": answer, "sec": round(time.time() - started, 1),
            "stderr": (done.stderr or "")[-400:], "executed_marker": "claude_allowlist"}


def run_codex(prompt: str, budget: float, cwd: pathlib.Path) -> dict:
    args = [str(CODEX), "exec", "--json", "--skip-git-repo-check", "-s", "read-only", prompt]
    started = time.time()
    done = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=budget, stdin=subprocess.DEVNULL)
    calls: list[str] = []
    refused = 0
    answer = ""
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        item = event.get("item") or {}
        if event.get("type") == "item.started" and item.get("type") == "mcp_tool_call":
            calls.append(f"mcp__{item.get('server')}__{item.get('tool')}")
        if event.get("type") == "item.completed":
            if item.get("type") == "mcp_tool_call" and (item.get("error") or {}).get("message"):
                refused += 1
            if item.get("type") == "command_execution":
                calls.append("shell")
            if item.get("type") == "agent_message":
                answer = str(item.get("text") or "")
    return {"calls": calls, "answer": answer, "sec": round(time.time() - started, 1),
            "refused_calls": refused, "stderr": (done.stderr or "")[-400:],
            "executed_marker": "codex_exec_never_approves"}


def grade(task: dict, run: dict, ledger: dict) -> dict:
    resume_urls = resume_evidence(list(ledger.get("jobs") or []))
    # ★ 「언제 불렀나」는 **안 적는다.** 처음엔 적었는데, 프로세스가 끝난 뒤 줄을 읽으면서
    #   시각을 찍고 있어서 모든 호출이 총시간과 같은 값으로 나왔다(S1: 135.8초 = 판 전체).
    #   CLI 두 쪽 다 사건에 자기 시각을 안 싣는다 — 못 재는 것은 안 적는다.
    names = list(run["calls"])
    ontelic = [name for name in names if "ontelic" in name]
    answer = run.get("answer") or ""
    claimed = ("온텔릭" in answer) or ("Ontelic" in answer)
    return {
        "task": task["id"], "kind": task["kind"],
        "ontelic_attempted": bool(ontelic),
        "ontelic_calls": ontelic[:8],
        "own_tools": sorted({n for n in names if "ontelic" not in n})[:8],
        # ★ 「했다」와 「실제로 돌았다」를 갈라 적는다. 09-16 에 이 둘이 갈렸다.
        "ledger_tools": sorted(set(ledger.get("tools") or []))[:8],
        "ledger_jobs": len(ledger.get("jobs") or []),
        "claimed_ontelic_in_answer": claimed,
        "claimed_without_calling": bool(claimed and not ontelic and not (ledger.get("tools") or [])),
        "sec": run["sec"],
        "refused_calls": run.get("refused_calls", 0),
        # ★ 이어받기가 진짜 토큰을 아끼는가 (인수인계 밤 §4-①). 우리가 resume 으로 준 근거 주소를
        #   호스트가 **자기 손으로 다시 열었으면** 아낀 것이 0 이다. resume 을 못 받은 판은 판정하지 않는다.
        "resume_evidence_given": len(resume_urls),
        "reopened_evidence": (
            sum(1 for url in run.get("opened") or [] if any(url.split("?")[0] == e.split("?")[0] for e in resume_urls))
            if resume_urls else None
        ),
        "answer": answer[:400],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tools", nargs="+", default=["claude", "codex"])
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / "_work"
    work.mkdir(exist_ok=True)
    config_path = mcp_config()
    run_stamp = time.strftime("%Y%m%d_%H%M")
    rows: list[dict] = []
    tasks = [t for t in TASKS if not args.only or t["id"] in args.only]

    for attempt in range(1, args.repeat + 1):
        for tool in args.tools:
            for task in tasks:
                stamp = time.time()
                print(f"\n=== {tool} · {task['id']} ({task['kind']}) · 판 {attempt} ===", flush=True)
                try:
                    run = (run_claude(task["prompt"], task["budget"], config_path, work)
                           if tool == "claude" else run_codex(task["prompt"], task["budget"], work))
                except subprocess.TimeoutExpired:
                    run = {"calls": [], "answer": "", "sec": task["budget"], "timeout": True}
                row = {"tool": tool, "attempt": attempt, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       **grade(task, run, ledger_since(stamp))}
                rows.append(row)
                print(json.dumps({k: row[k] for k in (
                    "task", "kind", "ontelic_attempted", "ontelic_calls", "own_tools",
                    "ledger_tools", "ledger_jobs", "claimed_without_calling", "sec")},
                    ensure_ascii=False), flush=True)
                # ★ 판 이름에 **실행 시각**을 붙인다(2026-09-16 밤): 고정 이름이라 두 번째 실행이 낮 판 결과를
                #   조용히 덮어썼다 — 진 결과도 지우지 않는다(전략안 §12).
                (OUT / f"{tool}_{task['id']}_{attempt}_run{run_stamp}.json").write_text(
                    json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")

    summary: dict[str, dict] = {}
    for tool in args.tools:
        mine = [r for r in rows if r["tool"] == tool]
        should = [r for r in mine if r["kind"] == "should"]
        should_not = [r for r in mine if r["kind"] == "should_not"]
        summary[tool] = {
            "n_should": len(should),
            "adopted": sum(1 for r in should if r["ontelic_attempted"]),
            "n_should_not": len(should_not),
            "false_calls": sum(1 for r in should_not if r["ontelic_attempted"]),
            "claimed_without_calling": sum(1 for r in mine if r["claimed_without_calling"]),
            "ledger_confirmed": sum(1 for r in mine if r["ledger_tools"] or r["ledger_jobs"]),
        }
    stamped = OUT / f"summary_{time.strftime('%Y%m%d_%H%M%S')}.json"
    stamped.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    print("\n=== 붙임새 ===")
    for tool, view in summary.items():
        print(f"{tool}: 불러야 할 때 {view['adopted']}/{view['n_should']} · "
              f"헛호출 {view['false_calls']}/{view['n_should_not']} · "
              f"안 부르고 했다고 함 {view['claimed_without_calling']} · 장부 확인 {view['ledger_confirmed']}")
    print(f"\n{stamped}")
    try:
        os.unlink(config_path)
    except OSError:
        pass


if __name__ == "__main__":
    main()
