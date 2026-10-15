"""P4 조사: 같은 모델을 검증 프롬프트로 한 번 더 부를 때의 실측 비용.

새 추론을 돌리지 않는다. 최근 완료 잡의 Ollama telemetry에서 첫 호출 이후 같은
모델 호출을 모아, 이미 모델이 적재된 상태의 추가 호출 비용을 계산한다.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = Path(r"C:\RoboMetaFit\tools\alture-jarvis\data\jarvis.db")
LIMIT = 300


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = conn.execute(
    "select id,result_json from jobs where result_json is not null "
    "order by created_at desc limit ?",
    (LIMIT,),
).fetchall()

jobs: list[list[dict[str, object]]] = []
for _job_id, raw in rows:
    try:
        result = json.loads(raw or "{}")
    except Exception:
        continue
    trace = result.get("agent_trace") if isinstance(result, dict) else {}
    trace = trace if isinstance(trace, dict) else {}
    verification = trace.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    observations = verification.get("inference_observations")
    if isinstance(observations, list) and observations:
        jobs.append([item for item in observations if isinstance(item, dict)])

all_calls = [call for job in jobs for call in job]
same_model_later: list[dict[str, object]] = []
for job in jobs:
    if not job:
        continue
    first_model = str(job[0].get("model") or "")
    same_model_later.extend(
        call for call in job[1:] if str(call.get("model") or "") == first_model
    )


def metric(call: dict[str, object], key: str) -> float:
    telemetry = call.get("telemetry")
    telemetry = telemetry if isinstance(telemetry, dict) else {}
    return float(telemetry.get(key) or 0)


later_total_sec = [metric(call, "total_duration") / 1e9 for call in same_model_later]
later_load_sec = [metric(call, "load_duration") / 1e9 for call in same_model_later]
later_prompt_tokens = [metric(call, "prompt_eval_count") for call in same_model_later]
later_eval_tokens = [metric(call, "eval_count") for call in same_model_later]

print(f"최근 {LIMIT}잡 중 추론 telemetry가 있는 판: {len(jobs)}")
print(f"기록된 모델 호출: {len(all_calls)}")
print(f"첫 호출 뒤 같은 모델 추가 호출: {len(same_model_later)}")
print(
    "판당 호출 수: "
    f"중앙 {percentile([float(len(job)) for job in jobs], .5):.0f} · "
    f"90% {percentile([float(len(job)) for job in jobs], .9):.0f}"
)
print(
    "같은 모델 추가 호출 총비용: "
    f"중앙 {percentile(later_total_sec, .5):.1f}초 · "
    f"90% {percentile(later_total_sec, .9):.1f}초"
)
print(
    "그중 모델 적재비: "
    f"중앙 {percentile(later_load_sec, .5):.3f}초 · "
    f"90% {percentile(later_load_sec, .9):.3f}초"
)
print(
    "추가 호출 문맥/생성 토큰: "
    f"prompt 중앙 {percentile(later_prompt_tokens, .5):.0f} · "
    f"eval 중앙 {percentile(later_eval_tokens, .5):.0f}"
)
