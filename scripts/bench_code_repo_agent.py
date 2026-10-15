"""P5의 24개 실저장소형 Code 벤치마크를 JARVIS API로 실행한다.

사용:
    python scripts/bench_code_repo_agent.py --dry-run
    python scripts/bench_code_repo_agent.py --only single_1_safe_divide
    python scripts/bench_code_repo_agent.py --json docs/benchmarks/code_repo_baseline.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from bench_artifact_tasks import BASE, TERMINAL, call, enabled_tools, token
from bench_q4_golden import gpu_sample
from code_repo_bench_cases import CASES, RepoCase, judge, materialize, snapshot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_ROOT = ROOT / "outputs" / "code_repo_bench"
# 「했다」고 말한 답만 허위 완료다. 못 했다고 말한 답은 정직한 실패이고, 둘을
# 한 칸에 섞으면 출하 관문이 사실상 만점을 요구하게 된다 — 실제로 그랬다.
_SUCCESS_CLAIM = re.compile(
    r"(?:고쳤|수정(?:했|하였|을 완료)|패치(?:했|를 적용)|반영했|해결했|성공했|"
    r"완료(?:했|되었|하였|입니다|했습니다)|통과(?:했|시켰|합니다|했습니다|되었)|"
    r"추가했|구현했|fixed|passed|completed)",
    re.IGNORECASE,
)
_FAILURE_ADMISSION = re.compile(
    r"(?:못\s*(?:했|고쳤|풀었|찾)|실패(?:했|입니다|했습니다)|해결하지\s*못|"
    r"수정하지\s*못|모르겠|알\s*수\s*없)",
    re.IGNORECASE,
)


def claims_success(answer: str) -> bool:
    """답이 「해냈다」고 주장하는가. 못 했다고 밝히면 주장이 아니다."""
    text = " ".join(str(answer or "").split())
    if not text:
        return False
    if _FAILURE_ADMISSION.search(text):
        return False
    return bool(_SUCCESS_CLAIM.search(text))


REQUIRED_TOOLS = {
    "local_list_directory",
    "local_read_text_file",
    "local_apply_edit",
    "local_run_project_command",
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run_one(
    case: RepoCase, root: Path, tok: str, *, budget_sec: int, after_seq: int = 0
) -> dict[str, object]:
    before = snapshot(root)
    posted = time.time()
    session_id = f"code-repo-bench-{case.key}-{int(posted * 1000)}"
    job = call(
        "/v1/chat",
        "POST",
        {
            "prompt": case.prompt,
            "session_id": session_id,
            "origin": "workspace",
            "workspace_mode": "code",
            "code_workspace": str(root),
            "open_results": False,
        },
        tok,
    )
    job_id = str(job.get("id") or "")
    detail: dict[str, object] = {}
    # 이 두 깃발은 아래에서 detail을 다시 읽어도 살아남아야 한다. 예전에는
    # detail 안에 적었다가 재조회가 통째로 덮어써, 눈금의 timeout_count가
    # 언제나 0이었다 — 출하 관문의 타임아웃 조건이 사실상 없었다.
    timed_out = False
    never_started = False
    inference: list[dict[str, object]] = []
    gpu: list[dict[str, object]] = []
    while True:
        time.sleep(2)
        gpu.extend(gpu_sample())
        try:
            for event in call(f"/v1/events?after={after_seq}&limit=500", tok=tok):
                after_seq = max(after_seq, int(event.get("seq") or 0))
                payload = event.get("payload") or {}
                if (
                    payload.get("job_id") == job_id
                    and event.get("event") == "agent_code_inference"
                ):
                    inference.append(dict(payload))
        except Exception:
            # 눈금의 곁가지가 판 자체를 죽이지 않는다.
            pass
        detail = call(f"/v1/jobs/{job_id}", tok=tok)
        status = str(detail.get("status") or "")
        started_at = float(detail.get("started_at") or 0)
        if status in TERMINAL or status in {"waiting_approval", "waiting_continuation"}:
            break
        if started_at and time.time() - started_at > budget_sec:
            timed_out = True
            break
        if not started_at and time.time() - posted > budget_sec * 2:
            never_started = True
            break

    detail = call(f"/v1/jobs/{job_id}", tok=tok)
    status = str(detail.get("status") or "")
    blocked_on_approval = status in {"waiting_approval", "waiting_continuation"}
    if timed_out or never_started or blocked_on_approval:
        # 멈춘 잡을 살려 두면 다음 과제가 그 뒤에 줄을 선다. 앞 판의 대기가
        # 뒷 판의 「작업 시간」으로 찍히는 사고를 여기서 끊는다.
        try:
            call(f"/v1/jobs/{job_id}/cancel", "POST", {}, tok)
        except Exception:
            pass
    result = detail.get("result") or {}
    trace = result.get("agent_trace") or {}
    steps = trace.get("steps") or []
    answer = str(result.get("answer") or "")
    score = judge(case, root, before, answer)
    tools = [str(step.get("tool") or "") for step in steps]
    repairs = sum(
        1
        for step in steps
        if step.get("tool") == "local_run_project_command"
        and not bool((step.get("evidence") or {}).get("verified"))
    )
    started_at = float(detail.get("started_at") or posted)
    finished_at = float(detail.get("finished_at") or time.time())
    models = sorted({str(row.get("model") or "") for row in inference} - {""})
    rates = [
        float((row.get("telemetry") or {}).get("eval_tokens_per_sec") or 0.0)
        for row in inference
    ]
    rates = [rate for rate in rates if rate > 0]
    peak_vram: dict[str, int] = {}
    for sample in gpu:
        label = f"gpu{sample.get('index')}:{sample.get('name')}"
        peak_vram[label] = max(peak_vram.get(label, 0), int(sample.get("memory_mib") or 0))
    return {
        "models_used": models,
        "inference_calls": len(inference),
        "answer_tokens": sum(
            int((row.get("telemetry") or {}).get("eval_count") or 0) for row in inference
        ),
        "tokens_per_sec_median": round(statistics.median(rates), 2) if rates else None,
        "peak_vram_mib": peak_vram,
        "after_seq": after_seq,
        "key": case.key,
        "category": case.category,
        "job_id": job_id,
        "status": status,
        "passed": score["passed"],
        "claimed_success": claims_success(answer),
        # 「완료됐다」는 잡 상태가 아니라 **답이 해냈다고 말했는지**로 판정한다.
        "false_completion": (
            status == "completed"
            and not score["passed"]
            and claims_success(answer)
        ),
        "failed_honestly": (
            status == "completed"
            and not score["passed"]
            and not claims_success(answer)
        ),
        "blocked_on_approval": blocked_on_approval,
        "timed_out": timed_out,
        "never_started": never_started,
        "score": score,
        "steps": len(steps),
        "tools": tools,
        "verification_calls": tools.count("local_run_project_command"),
        "repair_opportunities": repairs,
        "working_sec": round(max(0.0, finished_at - started_at), 1),
        "queued_sec": round(max(0.0, started_at - posted), 1),
        "answer_head": answer[:500],
    }


def summarize(rows: list[dict[str, object]], *, repeats: int) -> dict[str, object]:
    """고정 분모를 바꾸지 않고 반복 안정성과 출하 관문을 계산한다."""
    possible = len(rows)
    passed = sum(bool(row["passed"]) for row in rows)
    false_completed = sum(bool(row["false_completion"]) for row in rows)
    timed_out = sum(bool(row.get("timed_out") or row.get("never_started")) for row in rows)
    blocked = sum(bool(row.get("blocked_on_approval")) for row in rows)
    honest_failures = sum(bool(row.get("failed_honestly")) for row in rows)
    working = [float(row["working_sec"]) for row in rows]
    run_numbers = sorted({int(row["run"]) for row in rows})
    run_summaries: list[dict[str, object]] = []
    for run_number in run_numbers:
        run_rows = [row for row in rows if int(row["run"]) == run_number]
        run_passed = sum(bool(row["passed"]) for row in run_rows)
        run_summaries.append(
            {
                "run": run_number,
                "passed": run_passed,
                "total": len(run_rows),
                "pass_rate": round(run_passed / len(run_rows), 4) if run_rows else 0.0,
                "false_completion_count": sum(bool(row["false_completion"]) for row in run_rows),
                "blocked_on_approval_count": sum(
                    bool(row.get("blocked_on_approval")) for row in run_rows
                ),
                "honest_failure_count": sum(
                    bool(row.get("failed_honestly")) for row in run_rows
                ),
            }
        )

    category_summaries: dict[str, dict[str, object]] = {}
    for category in sorted({str(row["category"]) for row in rows}):
        category_rows = [row for row in rows if row["category"] == category]
        category_passed = sum(bool(row["passed"]) for row in category_rows)
        category_summaries[category] = {
            "passed": category_passed,
            "total": len(category_rows),
            "pass_rate": round(category_passed / len(category_rows), 4),
        }

    per_case: dict[str, dict[str, object]] = {}
    for key in sorted({str(row["key"]) for row in rows}):
        case_rows = [row for row in rows if row["key"] == key]
        case_passed = sum(bool(row["passed"]) for row in case_rows)
        per_case[key] = {
            "passed": case_passed,
            "attempts": len(case_rows),
            "pass_rate": round(case_passed / len(case_rows), 4),
        }

    models_used = sorted({
        model for row in rows for model in (row.get("models_used") or []) if model
    })
    rates = [
        float(row["tokens_per_sec_median"])
        for row in rows
        if row.get("tokens_per_sec_median")
    ]
    pass_rate = round(passed / possible, 4) if possible else 0.0
    minimum_run_pass_rate = min(
        (float(item["pass_rate"]) for item in run_summaries),
        default=0.0,
    )
    median_working_sec = round(statistics.median(working), 1) if working else 0.0
    release_gate = {
        "passed": bool(
            repeats >= 3
            and minimum_run_pass_rate >= 0.70
            and pass_rate >= 0.80
            and false_completed == 0
            and timed_out == 0
            and blocked == 0
            and median_working_sec <= 600.0
        ),
        "requires_repeats": 3,
        "minimum_run_pass_rate": minimum_run_pass_rate,
        "aggregate_pass_rate": pass_rate,
        # 이제 이 값은 「거짓말」만 센다. 통과 못 한 판 전부가 아니다. 예전
        # 정의로는 100%가 아니면 언제나 0을 넘어서, 옆의 0.80 문턱이 죽은
        # 조건이었다.
        "false_completion_count": false_completed,
        "honest_failure_count": honest_failures,
        "timeout_count": timed_out,
        # 승인 앞에서 멈춘 판은 「모델이 틀렸다」가 아니다. 평범한 실패에
        # 섞으면 원인이 사라지므로 관문에서 따로 0을 요구한다.
        "blocked_on_approval_count": blocked,
        "median_working_sec": median_working_sec,
    }
    return {
        # 라벨이 아니라 서버가 돌려준 이름이다. 두 개 이상이면 판마다 다른
        # 모델이 답했다는 뜻이므로 그 눈금은 한 모델의 실력이 아니다.
        "models_used": models_used,
        "tokens_per_sec_median": round(statistics.median(rates), 2) if rates else None,
        "passed": passed,
        "total_attempts": possible,
        "pass_rate": pass_rate,
        "false_completion_count": false_completed,
        "honest_failure_count": honest_failures,
        "timeout_count": timed_out,
        "blocked_on_approval_count": blocked,
        "median_working_sec": median_working_sec,
        "runs": run_summaries,
        "categories": category_summaries,
        "per_case": per_case,
        "release_gate": release_gate,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suite",
        default="p5",
        help="p5(고정 24과제) 또는 polyglot(Exercism 공개 골든셋)",
    )
    parser.add_argument(
        "--languages", default="python", help="polyglot 일 때 쓸 언어 (쉼표 구분)"
    )
    parser.add_argument("--only", default="", help="정확한 과제 key")
    parser.add_argument("--category", default="", help="recon/single_patch/multi_file/failure_recovery/visual")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--repeat", type=int, default=1, help="고정 24과제를 반복할 횟수")
    parser.add_argument("--budget-sec", type=int, default=900)
    parser.add_argument("--work-root", default=str(DEFAULT_WORK_ROOT))
    parser.add_argument("--json", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat는 1 이상이어야 합니다")

    if args.suite == "polyglot":
        from polyglot_bench_cases import load_cases

        languages = tuple(x.strip() for x in args.languages.split(",") if x.strip())
        suite = load_cases(languages)
        if not suite:
            raise SystemExit("polyglot 과제를 못 찾았다 — benchmarks/external 을 확인하라")
    elif args.suite == "p5":
        suite = CASES
    else:
        raise SystemExit(f"모르는 세트: {args.suite}")

    selected = [
        case
        for case in suite
        if (not args.only or case.key == args.only)
        and (not args.category or case.category == args.category)
    ]
    if args.limit > 0:
        selected = selected[: args.limit]
    if not selected:
        raise SystemExit("선택된 과제가 없습니다")

    counts = Counter(case.category for case in selected)
    print(f"[{args.suite}] 고정 분모 {len(selected)}건 · {dict(counts)}")
    if args.dry_run:
        print("필수 도구: " + ", ".join(sorted(REQUIRED_TOOLS)))
        for case in selected:
            print(f"  {case.key}: {case.prompt[:80]}")
        return 0

    tok = token()
    tools = enabled_tools(tok)
    missing = sorted(REQUIRED_TOOLS - tools)
    if missing:
        raise SystemExit("벤치 불가능 — 비활성/누락 도구: " + ", ".join(missing))

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = Path(args.work_root).resolve() / run_stamp
    run_root.mkdir(parents=True, exist_ok=False)
    rows: list[dict[str, object]] = []
    after_seq = 0
    for run_number in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"반복 {run_number}/{args.repeat}", flush=True)
        for index, case in enumerate(selected, 1):
            case_root = run_root / f"run_{run_number}" / case.key
            materialize(case, case_root)
            print(f"[{index}/{len(selected)}] {case.key}", flush=True)
            row = run_one(
                case, case_root, tok, budget_sec=max(30, args.budget_sec), after_seq=after_seq
            )
            after_seq = int(row.pop("after_seq", after_seq) or after_seq)
            row["run"] = run_number
            rows.append(row)
            print(
                f"  pass={row['passed']} status={row['status']} steps={row['steps']} "
                f"verify={row['verification_calls']} time={row['working_sec']}s "
                f"model={','.join(row['models_used']) or '?'}",
                flush=True,
            )

    summary = summarize(rows, repeats=args.repeat)
    payload = {
        "measured_at": time.time(),
        "base_url": BASE,
        "run_root": str(run_root),
        "suite": args.suite,
        "total_tasks": len(selected),
        "repeat_count": args.repeat,
        "category_counts": dict(counts),
        **summary,
        "rows": rows,
    }
    print("─" * 72)
    print(
        f"통과 {summary['passed']}/{summary['total_attempts']} · "
        f"허위 완료 {summary['false_completion_count']} · "
        f"정직한 실패 {summary['honest_failure_count']} · "
        f"승인정지 {summary['blocked_on_approval_count']} · "
        f"타임아웃 {summary['timeout_count']} · "
        f"중앙 {summary['median_working_sec']}s"
    )
    print(f"실제 답한 모델: {', '.join(summary['models_used']) or '기록 없음'}")
    target = Path(args.json).resolve() if args.json else run_root / "result.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"기록: {target}")
    if args.repeat >= 3:
        return 0 if summary["release_gate"]["passed"] else 1
    return 0 if summary["passed"] == summary["total_attempts"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
