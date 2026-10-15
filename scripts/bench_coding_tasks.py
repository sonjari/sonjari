"""코딩 요청을 **생성된 파일을 다시 실행한 출력**으로 채점한다.

정답이 하나뿐인 과제만 둔다. 답변의 코드 블록이나 "실행했다"는 문장은 점수가
아니다. 호스트에 실제로 남은 ``.py`` 파일을 별도 프로세스로 다시 실행해 종료코드와
표준출력을 대조한다.

분모는 실행 전에 `/v1/tools`로 적는다. 현재 실행 도구가 없으면 0점이 아니라
``not_possible`` 이다.

사용:
    python scripts/bench_coding_tasks.py --dry-run
    python scripts/bench_coding_tasks.py --json docs/benchmarks/coding_baseline.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# API·큐 대기·산출물 귀속 규칙을 두 벌로 만들지 않는다. 이 파일을 단독 실행할 때도
# scripts 폴더가 sys.path[0] 이므로 같은 폴더의 모듈을 그대로 가져올 수 있다.
from bench_artifact_tasks import (
    BASE,
    TERMINAL,
    _CREATION_CLAIM,
    call,
    enabled_tools,
    output_candidates,
    snapshot_outputs,
    token,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class CodingTask:
    key: str
    prompt: str
    expected_stdout: str
    required_any: tuple[str, ...] = ("sandbox_run",)


TASKS = (
    CodingTask(
        "prime_count",
        "1부터 1000까지 소수의 개수를 계산해 숫자 168만 출력하는 prime_count.py를 "
        "파일로 만들어 저장하고, 그 파일을 실제로 실행해서 검증해줘.",
        "168",
    ),
    CodingTask(
        "multiples_sum",
        "1000 미만 자연수 중 3 또는 5의 배수 합을 계산해 숫자 233168만 출력하는 "
        "multiples_sum.py를 파일로 만들어 저장하고, 그 파일을 실제로 실행해서 검증해줘.",
        "233168",
    ),
    CodingTask(
        "even_fibonacci",
        "4,000,000 이하 피보나치 수 중 짝수 합을 계산해 숫자 4613732만 출력하는 "
        "even_fibonacci.py를 파일로 만들어 저장하고, 그 파일을 실제로 실행해서 검증해줘.",
        "4613732",
    ),
)


def normalize_stdout(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.strip().splitlines())


def execute_file(path: Path, expected: str) -> dict:
    try:
        completed = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(path.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except Exception as exc:
        return {
            "executed": False, "exit_code": None, "stdout": "", "stderr": "",
            "output_matches": False, "error": f"{type(exc).__name__}: {exc}",
        }
    stdout = normalize_stdout(completed.stdout)
    return {
        "executed": True,
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": completed.stderr[-1000:],
        "output_matches": completed.returncode == 0 and stdout == expected,
    }


def run_one(task: CodingTask, tok: str, *, budget_sec: int) -> dict:
    before = snapshot_outputs()
    posted = time.time()
    job = call(
        "/v1/chat", "POST",
        {"prompt": task.prompt, "session_id": f"coding-bench-{task.key}-{int(posted * 1000)}", "open_results": False},
        tok,
    )
    job_id = str(job.get("id") or "")
    detail = {}
    continued = 0
    while True:
        time.sleep(3)
        detail = call(f"/v1/jobs/{job_id}", tok=tok)
        status = str(detail.get("status") or "")
        started_at = float(detail.get("started_at") or 0)
        working = time.time() - started_at if started_at else 0
        if status == "waiting_continuation":
            call(f"/v1/agents/{job_id}/continue", "POST", {"action": "continue_task"}, tok)
            continued += 1
            continue
        if status in TERMINAL or status == "waiting_approval":
            break
        if started_at and working > budget_sec:
            detail["timed_out"] = True
            break
        if not started_at and time.time() - posted > budget_sec * 3:
            detail["never_started"] = True
            break

    detail = call(f"/v1/jobs/{job_id}", tok=tok)
    result = detail.get("result") or {}
    trace = result.get("agent_trace") or {}
    steps = trace.get("steps") or []
    answer = str(result.get("answer") or "")
    files = output_candidates(job_id, tok, before, (".py",))
    executions = []
    winning_path = ""
    for item in files:
        if not item["exists"] or item["bytes"] <= 0:
            continue
        execution = execute_file(Path(item["path"]), task.expected_stdout)
        execution["path"] = item["path"]
        executions.append(execution)
        if execution["output_matches"]:
            winning_path = item["path"]
            break
    started_at = float(detail.get("started_at") or posted)
    finished_at = float(detail.get("finished_at") or time.time())
    return {
        "key": task.key,
        "prompt": task.prompt,
        "possible": True,
        "possible_reason": "코드를 파일로 남기고 실행할 수 있는 도구가 켜져 있다.",
        "job_id": job_id,
        "status": detail.get("status"),
        "claimed_created": bool(_CREATION_CLAIM.search(answer)),
        "file_exists": any(item["exists"] and item["bytes"] > 0 for item in files),
        "executed": any(item.get("executed") for item in executions),
        "execution_succeeded": any(item.get("exit_code") == 0 for item in executions),
        "output_matches": any(item.get("output_matches") for item in executions),
        "expected_stdout": task.expected_stdout,
        "steps": len(steps),
        "tools": [str(step.get("tool") or "") for step in steps],
        "files": files,
        "executions": executions,
        "verified_path": winning_path,
        "queued_sec": round(max(0.0, started_at - posted), 1),
        "working_sec": round(max(0.0, finished_at - started_at), 1),
        "continued": continued,
        "answer_head": answer[:300],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="과제 키")
    parser.add_argument("--budget-sec", type=int, default=420)
    parser.add_argument("--json", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tok = token()
    tools = enabled_tools(tok)
    tasks = [task for task in TASKS if not args.only or task.key == args.only]
    rows: list[dict] = []
    print("분모 — 지금 코드로 가능한가")
    for task in tasks:
        possible = any(name in tools for name in task.required_any)
        print(f"  [{task.key}] {'가능' if possible else '불가능'} · {'/'.join(task.required_any)}")
        if not possible:
            rows.append({
                "key": task.key, "prompt": task.prompt, "possible": False,
                "possible_reason": "코드를 파일로 남기고 실행할 도구가 없다.",
                "required_any": list(task.required_any),
            })
    if args.dry_run:
        return 0

    for index, task in enumerate(tasks, 1):
        if not any(name in tools for name in task.required_any):
            continue
        print(f"[{index}/{len(tasks)}] ({task.key}) {task.prompt[:58]}", flush=True)
        row = run_one(task, tok, budget_sec=args.budget_sec)
        rows.append(row)
        print(f"    파일 {row['file_exists']} · 실행 {row['execution_succeeded']} · "
              f"출력 {row['output_matches']} · {row['steps']}걸음 · "
              f"일한 {row['working_sec']}초 (큐 {row['queued_sec']}초)", flush=True)

    judged = [row for row in rows if row.get("possible")]
    print("\n" + "─" * 68)
    print(f"  가능한 분모          {len(judged)}/{len(rows)}")
    print(f"  파일 실재            {sum(1 for row in judged if row.get('file_exists'))}/{len(judged)}")
    print(f"  실행 성공(rc==0)     {sum(1 for row in judged if row.get('execution_succeeded'))}/{len(judged)}")
    print(f"  출력 일치            {sum(1 for row in judged if row.get('output_matches'))}/{len(judged)}")
    if len(judged) < 10:
        print("  ⚠ 표본이 적다 — 비율 말고 개수로 본다")
    print("─" * 68)

    payload = {
        "measured_at": time.time(),
        "base_url": BASE,
        "tool_count": len(tools),
        "possible_denominator": len(judged),
        "total_tasks": len(rows),
        "rows": rows,
    }
    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  기록: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
