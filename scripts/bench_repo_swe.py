"""우리 저장소 SWE 벤치 — **고칠 자리를 스스로 찾는가.**

24과제는 고칠 파일이 사실상 지목된 판이다. 여기서는 안 알려준다. 실패하는
테스트와 그 실패 출력만 주고, 66개 파일 4만 줄에서 원인을 찾아 고치게 한다.

채점은 SWE-bench 와 같다:

    FAIL_TO_PASS   그 테스트가 통과하는가
    PASS_TO_PASS   나머지 회귀가 안 깨졌는가   <- 인수인계를 안전하게 만드는 조건
    변경 경계      테스트를 안 건드리고 소스만 고쳤는가

`PASS_TO_PASS` 를 넣은 이유: 테스트 하나만 통과시키는 것은 쉽다. 통과시키면서
**아무것도 안 깨뜨리는 것**이 사람이 일을 맡길 수 있는 조건이다.

    python scripts/bench_repo_swe.py --limit 3 --json docs/benchmarks/repo_swe.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bench_artifact_tasks import BASE, TERMINAL, call, enabled_tools, token  # noqa: E402
from bench_code_repo_agent import claims_success  # noqa: E402
from repo_swe_bench_cases import (  # noqa: E402
    PREFIX,
    RepoSweSpec,
    load_specs,
    materialize,
    run_tests,
)

DEFAULT_WORK_ROOT = ROOT / "outputs" / "repo_swe_bench"
REQUIRED_TOOLS = {
    "local_list_directory",
    "local_read_text_file",
    "local_apply_edit",
    "local_run_project_command",
    "local_index_codebase",
    "local_search_files",
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


#: 스냅샷에서 뺄 폴더. **저장소 안에서의 상대 경로**로만 본다.
SNAPSHOT_SKIP = frozenset(
    {"__pycache__", ".pytest_cache", "outputs", "data", ".venv", "benchmarks", "node_modules"}
)


def snapshot(root: Path) -> dict[str, str]:
    """이 저장소가 지금 어떤 상태인가 — 파일마다 해시.

    ★ 2026-08-28: 예전에는 `skip & set(path.parts)` 로 걸렀는데 `path.parts` 가
      **절대 경로**였다. 작업 폴더가 `.../alture-jarvis/outputs/repo_swe_bench/...`
      아래라 모든 파일이 `outputs` 에 걸려 통째로 걸러졌고, before/after 가 둘 다
      빈 딕셔너리였다. 그 결과 「테스트를 건드렸나」와 「예상 밖 파일을 고쳤나」가
      **아무것도 안 보고 항상 통과**했다 — 모델이 테스트를 고쳐 통과시켜도 못 잡는
      채점기였다. 상대 경로로 봐야 한다.
    """
    import hashlib

    root = root.resolve()
    found: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if SNAPSHOT_SKIP & set(relative.parts):
            continue
        try:
            found[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return found


def build_prompt(spec: RepoSweSpec) -> str:
    tests = ", ".join(t[len(PREFIX):] for t in spec.test_files)
    lines = [
        "이 저장소에서 다음 테스트가 실패한다:",
        "",
        "    " + tests,
        "",
    ]
    if spec.failure_head:
        lines += ["실패 출력:", "", spec.failure_head.strip()[:900], ""]
    lines += [
        "원인을 찾아 소스를 고쳐서 이 테스트를 통과시켜줘.",
        "테스트 파일은 절대 수정하지 마 — 구현을 고쳐야 한다.",
        "고친 뒤 그 테스트를 실제로 실행해 통과를 확인해줘.",
        "검증용 임시 파일을 만들었으면 끝나기 전에 지워라.",
    ]
    return "\n".join(lines)


def job_steps(job_id: str, result: dict[str, object], tok: str) -> list[dict[str, object]]:
    """완료 전 취소된 잡도 실제 걸음을 잃지 않게 읽는다.

    타임아웃 잡은 ``result`` 가 비어 있는 ``running`` 상태에서 취소된다. 예전에는
    취소 뒤 ``result.agent_trace`` 만 봐서, 실제로 30걸음을 돌고 파일까지 고친 판도
    ``steps=0`` 으로 기록했다. 작업 중에도 유지되는 표준 steps 장부를 폴백으로 쓴다.
    """
    trace = result.get("agent_trace") or {}
    if isinstance(trace, dict):
        steps = trace.get("steps") or []
        if isinstance(steps, list) and steps:
            return [step for step in steps if isinstance(step, dict)]
    try:
        payload = call(f"/v1/jobs/{job_id}/steps", tok=tok)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    items = payload.get("items") or []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def judge(
    spec: RepoSweSpec,
    root: Path,
    before: dict[str, str],
    *,
    run_regression: bool,
    regression_timeout: int,
) -> dict[str, object]:
    after = snapshot(root)
    changed = sorted(
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    )
    expected = {source[len(PREFIX):] for source in spec.source_files}
    touched_tests = [path for path in changed if path.startswith("tests/")]
    unexpected = sorted(set(changed) - expected)

    rel_tests = [t[len(PREFIX):] for t in spec.test_files]
    try:
        target = run_tests(root, rel_tests, timeout=600)
        fail_to_pass = target.returncode == 0
        target_tail = (target.stdout or "")[-1500:]
    except subprocess.TimeoutExpired:
        fail_to_pass = False
        target_tail = "(대상 테스트가 안 끝났다)"

    pass_to_pass: bool | None = None
    regression_tail = ""
    if run_regression and fail_to_pass:
        try:
            whole = run_tests(root, ["tests"], timeout=regression_timeout)
            pass_to_pass = whole.returncode == 0
            regression_tail = (whole.stdout or "")[-1200:]
        except subprocess.TimeoutExpired:
            pass_to_pass = None
            regression_tail = "(회귀가 안 끝났다)"

    passed = bool(
        fail_to_pass
        and not touched_tests
        and not unexpected
        and (pass_to_pass is not False)
    )
    return {
        "passed": passed,
        "fail_to_pass": fail_to_pass,
        "pass_to_pass": pass_to_pass,
        "touched_tests": touched_tests,
        "unexpected_paths": unexpected,
        "changed_paths": changed,
        "expected_paths": sorted(expected),
        "target_tail": target_tail,
        "regression_tail": regression_tail,
    }


def run_one(
    spec: RepoSweSpec,
    root: Path,
    tok: str,
    *,
    budget_sec: int,
    run_regression: bool,
    regression_timeout: int,
) -> dict[str, object]:
    materialize(spec, root)
    before = snapshot(root)
    posted = time.time()
    session_id = "repo-swe-bench-%s-%d" % (spec.commit[:8], int(posted * 1000))
    job = call(
        "/v1/chat",
        "POST",
        {
            "prompt": build_prompt(spec),
            "session_id": session_id,
            "origin": "workspace",
            "workspace_mode": "code",
            "code_workspace": str(root),
            "open_results": False,
        },
        tok,
    )
    job_id = str(job.get("id") or "")
    timed_out = False
    detail: dict[str, object] = {}
    while True:
        time.sleep(3)
        detail = call("/v1/jobs/" + job_id, tok=tok)
        status = str(detail.get("status") or "")
        started_at = float(detail.get("started_at") or 0)
        if status in TERMINAL or status in {"waiting_approval", "waiting_continuation"}:
            break
        if started_at and time.time() - started_at > budget_sec:
            timed_out = True
            break
        if not started_at and time.time() - posted > budget_sec * 2:
            timed_out = True
            break

    detail = call("/v1/jobs/" + job_id, tok=tok)
    status = str(detail.get("status") or "")
    blocked = status in {"waiting_approval", "waiting_continuation"}
    result = detail.get("result") or {}
    if not isinstance(result, dict):
        result = {}
    steps = job_steps(job_id, result, tok)
    stopped_at = time.time()
    if timed_out or blocked:
        try:
            call("/v1/jobs/" + job_id + "/cancel", "POST", {}, tok)
        except Exception:
            pass

    answer = str(result.get("answer") or "")
    score = judge(
        spec,
        root,
        before,
        run_regression=run_regression,
        regression_timeout=regression_timeout,
    )
    tools = [str(step.get("tool") or "") for step in steps]
    started_at = float(detail.get("started_at") or posted)
    finished_at = float(detail.get("finished_at") or stopped_at)
    reported_status = "timed_out" if timed_out else status
    return {
        "commit": spec.commit[:8],
        "subject": spec.subject[:70],
        "status": reported_status,
        "passed": score["passed"],
        "claimed_success": claims_success(answer),
        "false_completion": (
            status == "completed" and not score["passed"] and claims_success(answer)
        ),
        "timed_out": timed_out,
        "blocked_on_approval": blocked,
        "score": score,
        "steps": len(steps),
        "tools": tools,
        "indexed": tools.count("local_index_codebase"),
        "searched": tools.count("local_search_files"),
        "reads": tools.count("local_read_text_file"),
        "verifications": tools.count("local_run_project_command"),
        "working_sec": round(max(0.0, finished_at - started_at), 1),
        "answer_head": answer[:400],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--budget-sec", type=int, default=1200)
    parser.add_argument("--regression-timeout", type=int, default=900)
    parser.add_argument("--no-regression", action="store_true")
    parser.add_argument("--work-root", default=str(DEFAULT_WORK_ROOT))
    parser.add_argument("--json", default="")
    parser.add_argument("--dry-run", action="store_true")
    # ★ 일부만 다시 재는 문 (2026-08-30).
    #
    # 없어서 지금까지는 `repo_swe_cases.json` 을 갈아끼웠다. 그러면 **원복을
    # 잊는 순간 분모가 조용히 바뀐다** — 이 저장소가 눈금에서 제일 여러 번
    # 당한 자리다. 파일은 그대로 두고 메모리에서만 고른다.
    #
    # 짧은 해시로 준다. 없는 해시를 주면 **조용히 0건으로 도는 대신 죽는다** —
    # 오타 하나로 "0/0 통과" 가 나오면 그게 제일 나쁘다.
    parser.add_argument(
        "--commit",
        action="append",
        default=[],
        help="이 커밋만 돈다(짧은 해시 가능). 여러 번 줄 수 있다.",
    )
    args = parser.parse_args()

    specs = [spec for spec in load_specs() if spec.validated]
    if args.commit:
        wanted = [c.strip().lower() for c in args.commit if c.strip()]
        picked = [s for s in specs if any(s.commit.lower().startswith(w) for w in wanted)]
        unknown = [w for w in wanted if not any(s.commit.lower().startswith(w) for s in specs)]
        if unknown:
            raise SystemExit("분모에 없는 커밋: " + ", ".join(unknown))
        specs = picked
    if args.limit:
        specs = specs[: args.limit]
    if not specs:
        raise SystemExit("검증된 과제가 없다 — repo_swe_bench_cases.py --validate 먼저")

    print("[repo-swe] 고정 분모 %d건" % len(specs))
    if args.dry_run:
        for spec in specs:
            print("  %s | %s" % (spec.commit[:8], spec.subject[:60]))
            print("     고쳐야 할 곳(모델에겐 비밀): %s" % (spec.source_files,))
        return 0

    tok = token()
    missing = sorted(REQUIRED_TOOLS - enabled_tools(tok))
    if missing:
        raise SystemExit("벤치 불가능 — 비활성/누락 도구: " + ", ".join(missing))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = Path(args.work_root).resolve() / stamp
    run_root.mkdir(parents=True, exist_ok=False)

    target = Path(args.json).resolve() if args.json else run_root / "result.json"
    target.parent.mkdir(parents=True, exist_ok=True)

    def write_checkpoint(*, complete: bool) -> None:
        """한 판이 끝날 때마다 보존한다.

        장시간 벤치는 터미널이나 호출자가 끊겨도 이미 끝난 판을 잃으면 안 된다.
        ``complete=false`` 는 아직 최종 분모가 채워지지 않았다는 명시적 표시다.
        """
        passed = sum(1 for row in rows if row["passed"])
        f2p = sum(1 for row in rows if row["score"]["fail_to_pass"])
        working = [float(row["working_sec"]) for row in rows]
        payload = {
            "measured_at": time.time(),
            "base_url": BASE,
            "run_root": str(run_root),
            "complete": complete,
            "completed_cases": len(rows),
            "planned_cases": len(specs),
            "passed": passed,
            "total": len(rows),
            "pass_rate": round(passed / len(rows), 4) if rows else 0.0,
            "fail_to_pass_count": f2p,
            "false_completion_count": sum(1 for row in rows if row["false_completion"]),
            "timeout_count": sum(1 for row in rows if row["timed_out"]),
            "blocked_on_approval_count": sum(
                1 for row in rows if row["blocked_on_approval"]
            ),
            "median_working_sec": (
                round(statistics.median(working), 1) if working else 0.0
            ),
            "rows": rows,
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    rows: list[dict[str, object]] = []
    for index, spec in enumerate(specs, 1):
        print("[%d/%d] %s %s" % (index, len(specs), spec.commit[:8], spec.subject[:48]), flush=True)
        row = run_one(
            spec,
            run_root / spec.commit[:8],
            tok,
            budget_sec=args.budget_sec,
            run_regression=not args.no_regression,
            regression_timeout=args.regression_timeout,
        )
        rows.append(row)
        score = row["score"]
        print(
            "  pass=%s F2P=%s P2P=%s steps=%s 색인=%s 검색=%s 읽기=%s 검증=%s %.0fs"
            % (
                row["passed"],
                score["fail_to_pass"],
                score["pass_to_pass"],
                row["steps"],
                row["indexed"],
                row["searched"],
                row["reads"],
                row["verifications"],
                row["working_sec"],
            ),
            flush=True,
        )
        if not row["passed"] and score["unexpected_paths"]:
            print("     예상 밖 변경: %s" % (score["unexpected_paths"][:5],), flush=True)
        write_checkpoint(complete=False)

    passed = sum(1 for row in rows if row["passed"])
    f2p = sum(1 for row in rows if row["score"]["fail_to_pass"])
    working = [float(row["working_sec"]) for row in rows]
    summary = {
        "passed": passed,
        "total": len(rows),
        "pass_rate": round(passed / len(rows), 4) if rows else 0.0,
        "fail_to_pass_count": f2p,
        "false_completion_count": sum(1 for row in rows if row["false_completion"]),
        "timeout_count": sum(1 for row in rows if row["timed_out"]),
        "blocked_on_approval_count": sum(1 for row in rows if row["blocked_on_approval"]),
        "median_working_sec": round(statistics.median(working), 1) if working else 0.0,
    }
    print("-" * 68)
    print(
        "통과 %d/%d · 테스트만 통과 %d · 허위완료 %d · 타임아웃 %d · 중앙 %.0fs"
        % (
            summary["passed"],
            summary["total"],
            summary["fail_to_pass_count"],
            summary["false_completion_count"],
            summary["timeout_count"],
            summary["median_working_sec"],
        )
    )
    write_checkpoint(complete=True)
    print("기록: %s" % target)
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
