"""Qwen Q4의 자기개선 capstone을 숨은 oracle과 실행 궤적으로 평가한다."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from bench_artifact_tasks import BASE, TERMINAL, call, enabled_tools, token
from q4_golden_cases import CASES, GoldenCase, judge, materialize, snapshot, validate_golden

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_ROOT = ROOT / "outputs" / "q4_golden"
REQUIRED_TOOLS = {"local_list_directory", "local_read_text_file", "local_run_project_command"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def gpu_sample() -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) == 4:
            try:
                rows.append({"index": int(parts[0]), "name": parts[1], "memory_mib": int(parts[2]), "utilization_pct": int(parts[3])})
            except ValueError:
                pass
    return rows


def summarize_inference(observations: list[dict[str, Any]]) -> dict[str, Any]:
    telemetry = [row.get("telemetry") or {} for row in observations]
    return {
        "calls_observed": len(observations),
        "prompt_tokens": sum(int(row.get("prompt_eval_count") or 0) for row in telemetry),
        "answer_tokens": sum(int(row.get("eval_count") or 0) for row in telemetry),
        "generation_sec": round(sum(int(row.get("eval_duration") or 0) for row in telemetry) / 1e9, 3),
        "tokens_per_sec_median": round(statistics.median([
            float(row["eval_tokens_per_sec"]) for row in telemetry if row.get("eval_tokens_per_sec")
        ]), 3) if any(row.get("eval_tokens_per_sec") for row in telemetry) else None,
        "contracts": [row.get("requested") or {} for row in observations],
        "acknowledged": [row.get("response_acknowledged") or {} for row in observations],
    }


def recover_persisted_steps(job_id: str, tok: str) -> list[dict[str, Any]]:
    """실패 job도 관찰 장부에는 걸음이 남는다. trace 유실과 성능을 섞지 않는다."""
    ledger = call(f"/v1/jobs/{job_id}/steps", tok=tok)
    recovered: list[dict[str, Any]] = []
    for summary in ledger.get("items") or []:
        step_number = int(summary.get("step") or 0)
        evidence: dict[str, Any] = {}
        if step_number:
            try:
                detail = call(f"/v1/jobs/{job_id}/steps/{step_number}", tok=tok)
                payload = detail.get("payload") or {}
                raw = payload.get("text") if isinstance(payload, dict) else ""
                parsed = json.loads(raw) if raw else {}
                evidence = parsed if isinstance(parsed, dict) else {}
            except Exception:
                evidence = {}
        recovered.append({
            "step": step_number,
            "tool": str(summary.get("tool") or ""),
            "ok": bool(summary.get("ok")),
            "evidence": evidence,
        })
    return recovered


def run_one(case: GoldenCase, root: Path, tok: str, budget_sec: int) -> dict[str, Any]:
    before = snapshot(root)
    posted = time.time()
    events = call("/v1/events?after=0&limit=500", tok=tok)
    after_seq = max((int(row.get("seq") or 0) for row in events), default=0)
    job = call("/v1/chat", "POST", {
        "prompt": case.prompt,
        "session_id": f"q4-golden-{case.key}-{int(posted * 1000)}",
        "origin": "workspace", "workspace_mode": "code", "code_workspace": str(root), "open_results": False,
    }, tok)
    job_id = str(job.get("id") or "")
    first_agent_at: float | None = None
    gpu: list[dict[str, Any]] = []
    inference_events: list[dict[str, Any]] = []
    detail: dict[str, Any] = {}
    while True:
        time.sleep(2)
        gpu.extend(gpu_sample())
        for event in call(f"/v1/events?after={after_seq}&limit=500", tok=tok):
            after_seq = max(after_seq, int(event.get("seq") or 0))
            payload = event.get("payload") or {}
            if payload.get("job_id") == job_id and str(event.get("event") or "").startswith("agent_"):
                first_agent_at = first_agent_at or float(event.get("timestamp") or time.time())
            if payload.get("job_id") == job_id and event.get("event") == "agent_code_inference":
                inference_events.append(dict(payload))
        detail = call(f"/v1/jobs/{job_id}", tok=tok)
        status = str(detail.get("status") or "")
        started = float(detail.get("started_at") or 0)
        if status in TERMINAL or status in {"waiting_approval", "waiting_continuation"}:
            break
        if started and time.time() - started > budget_sec:
            call(f"/v1/jobs/{job_id}/cancel", "POST", {}, tok)
            detail["timed_out"] = True
            break
    detail = call(f"/v1/jobs/{job_id}", tok=tok)
    result = detail.get("result") or {}
    trace = result.get("agent_trace") or {}
    steps = trace.get("steps") or recover_persisted_steps(job_id, tok)
    status = str(detail.get("status") or "")
    scored = judge(case, root, before, status=status, steps=steps)
    observations = ((trace.get("verification") or {}).get("inference_observations") or inference_events)
    peak_by_gpu: dict[int, dict[str, Any]] = {}
    for row in gpu:
        index = int(row["index"])
        if index not in peak_by_gpu or row["memory_mib"] > peak_by_gpu[index]["memory_mib"]:
            peak_by_gpu[index] = row
    started = float(detail.get("started_at") or posted)
    finished = float(detail.get("finished_at") or time.time())
    return {
        "key": case.key, "version": case.version, "job_id": job_id, "status": status,
        "passed": scored["passed"], "false_completion": status == "completed" and not scored["passed"],
        "score": scored, "steps": len(steps),
        "working_sec": round(max(0.0, finished - started), 2),
        "queued_sec": round(max(0.0, started - posted), 2),
        "time_to_first_agent_event_sec": round(max(0.0, first_agent_at - posted), 3) if first_agent_at else None,
        "inference": summarize_inference(observations),
        "gpu_peak": list(peak_by_gpu.values()),
        "answer_head": str(result.get("answer") or "")[:1000],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--budget-sec", type=int, default=1200)
    parser.add_argument("--work-root", default=str(DEFAULT_WORK_ROOT))
    parser.add_argument("--json", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-golden", action="store_true")
    args = parser.parse_args()
    selected = [case for case in CASES if not args.only or case.key == args.only]
    if not selected:
        raise SystemExit("선택된 골든 과제가 없습니다")
    print(f"{selected[0].version} · {len(selected)} capstone · 숨은 oracle/변조/복구 채점")
    if args.dry_run:
        for case in selected:
            print(f"  {case.key}: {case.prompt}")
        return 0
    if args.validate_golden:
        with tempfile.TemporaryDirectory(prefix="jarvis-q4-golden-check-") as folder:
            checks = [validate_golden(case, Path(folder) / case.key) for case in selected]
        ok = all(all(bool(row[key]) for key in (
            "baseline_public_fails", "baseline_hidden_fails", "reference_public_passes", "reference_hidden_passes"
        )) for row in checks)
        print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    tok = token()
    missing = sorted(REQUIRED_TOOLS - enabled_tools(tok))
    if missing:
        raise SystemExit("벤치 불가능 — 비활성/누락 도구: " + ", ".join(missing))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = Path(args.work_root).resolve() / stamp
    run_root.mkdir(parents=True, exist_ok=False)
    rows = []
    for index, case in enumerate(selected, 1):
        root = run_root / case.key
        materialize(case, root)
        print(f"[{index}/{len(selected)}] {case.key}", flush=True)
        row = run_one(case, root, tok, max(60, args.budget_sec))
        rows.append(row)
        print(f"  score={row['score']['score']}/100 pass={row['passed']} status={row['status']} time={row['working_sec']}s", flush=True)
    payload = {
        "schema": "jarvis-q4-golden-result-v1", "measured_at": time.time(), "base_url": BASE,
        "run_root": str(run_root), "total": len(rows), "passed": sum(bool(row["passed"]) for row in rows),
        "pass_rate": round(sum(bool(row["passed"]) for row in rows) / len(rows), 4),
        "false_completion_count": sum(bool(row["false_completion"]) for row in rows), "rows": rows,
    }
    target = Path(args.json).resolve() if args.json else run_root / "result.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"기록: {target}")
    return 0 if payload["passed"] == payload["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
