# -*- coding: utf-8 -*-
"""사다리 한 판의 시각표 — 판 시작부터 걸음마다 몇 초에 무엇이 있었나, 모델 호출마다 서버가 쓴 시간 (2026-10-07).

판의 시간을 「모델 서버 · 도구 · 그 밖」으로 가른다. 호출마다 벽시계와 끝난 시각이 있으면(`wall_sec`·`ended_at`)
호출 안 덧시간 · 호출 사이 · 마지막 호출 뒤까지 가른다. 실행기가 찍는 시간은 10초마다 물어 10초 단위로 뭉치므로 쓰지 않는다.

쓰기: python ladder_timeline.py <결과.json> [판 번호…]
"""
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def find(node, key, path=""):
    """키가 어디에 있든 찾아 (경로, 값) 을 낸다."""
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{path}.{k}" if path else k
            if k == key:
                yield here, v
            yield from find(v, key, here)
    elif isinstance(node, list):
        for i, v in enumerate(node[:400]):
            yield from find(v, key, f"{path}[{i}]")


def sec(ns):
    return round(float(ns or 0) / 1e9, 2)


def one(job_path: Path) -> dict:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    started = float(job.get("started_at") or 0)
    finished = float(job.get("finished_at") or 0)
    trace = ((job.get("result") or {}).get("agent_trace") or {})
    steps = trace.get("steps") or []
    print(f"\n=== {job_path.name}  상태 {job.get('status')}  총 {finished - started:.1f}초  빌드 {str(job.get('build'))[:60]}")
    last = 0.0
    first_pass = None
    for step in steps:
        record = step.get("evidence_record") or {}
        at = float(record.get("created_at") or 0) - started if isinstance(record, dict) else 0.0
        took = float(step.get("took_ms") or 0) / 1000
        name = str(step.get("tool"))
        ok = "ok" if step.get("ok") else f"실패 {str(step.get('error'))[:40]}"
        print(f"  걸음 {step.get('step'):>2}  +{at:6.1f}초 (앞 걸음 뒤 {at - last:5.1f}초 · 도구 {took:5.2f}초)  {name:<28} {step.get('code_phase', ''):<7} {ok}")
        if first_pass is None and name == "local_run_project_command" and step.get("ok"):
            evidence = step.get("evidence") or {}
            if isinstance(evidence, dict) and int(evidence.get("returncode", 1) or 0) == 0:
                first_pass = at
        last = at
    print(f"  마지막 걸음 뒤 끝까지 {finished - started - last:.1f}초")
    observations = []
    for where, value in find(job, "inference_observations"):
        if isinstance(value, list) and value:
            observations = value
            print(f"  모델 호출 기록: {where} ({len(value)}건)")
            break
    server = 0.0
    harness = 0.0
    between = 0.0
    previous_end = started
    for i, item in enumerate(observations, 1):
        t = item.get("telemetry") or {}
        total = sec(t.get("total_duration"))
        server += total
        wall = item.get("wall_sec")
        ended = item.get("ended_at")
        extra = ""
        if wall is not None and ended is not None:
            begun = float(ended) - float(wall)
            harness += float(wall) - total
            between += begun - previous_end
            extra = f"  벽시계 {float(wall):5.2f}(덧 {float(wall) - total:4.2f}) · 앞 호출 뒤 {begun - previous_end:5.2f}초"
            previous_end = float(ended)
        print(
            f"    호출 {i}: 서버 {total:5.2f}초 = 읽기 {sec(t.get('prompt_eval_duration')):5.2f}"
            f"({t.get('prompt_eval_count')}토큰) + 쓰기 {sec(t.get('eval_duration')):5.2f}({t.get('eval_count')}토큰)"
            f" · 생각 {item.get('thinking_chars_received')}자{extra}"
        )
    if harness or between:
        print(f"  호출 안 덧시간 합 {harness:.1f}초 · 호출 사이(도구·검사) 합 {between:.1f}초 · 마지막 호출 뒤 {finished - previous_end:.1f}초")
    for where, value in find(job, "model_time"):
        print(f"  model_time @ {where}: {value}")
        break
    for where, value in find(job, "turn_overhead"):
        print(f"  turn_overhead @ {where}: {value}")
        break
    tools = sum(float(s.get("took_ms") or 0) for s in steps) / 1000
    total = finished - started
    print(f"  합계: 총 {total:.1f} = 모델 서버 {server:.1f} + 도구 {tools:.1f} + 그 밖 {total - server - tools:.1f}초   첫 걸음까지 {float((steps[0].get('evidence_record') or {}).get('created_at') or started) - started if steps else 0:.1f}초")
    return {"total": total, "server": server, "tools": tools, "other": total - server - tools, "turns": len(observations), "first_pass": first_pass}


def main() -> None:
    out = Path(sys.argv[1])
    picks = set(sys.argv[2:])
    rows = []
    for job_path in sorted(out.parent.glob(out.stem + "_*_job.json")):
        if picks and not any(p in job_path.name for p in picks):
            continue
        rows.append(one(job_path))
    if rows:
        print("\n=== 판별 요약")
        for key in ("total", "server", "tools", "other", "turns"):
            print(f"  {key:<7}", " · ".join(f"{row[key]:.1f}" if isinstance(row[key], float) else str(row[key]) for row in rows))


if __name__ == "__main__":
    main()
