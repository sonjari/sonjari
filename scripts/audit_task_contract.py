"""작업계약 그림자 계측 — 과거 판의 원문을 다시 컴파일해서 센다.

    분모 먼저. 비율은 그 다음.

`compile_task_contract` 는 실행을 바꾸지 않는다(Phase 1). 그래서 이 스크립트가
계약이 **실제 요청에서 무엇을 읽고 무엇을 못 읽는지**를 재는 유일한 자다.

⚠ 이 자에는 한계가 하나 있다. 라이브는 `planning_prompt(prompt, history)` 로
컴파일하지만 여기서는 잡에 저장된 프롬프트만 쓴다. 그래서 「제안한대로 진행해줘」
같은 이어받는 판은 여기서만 미분류로 보인다. 그 판은 따로 표시한다.
"""

from __future__ import annotations

import collections
import json
import sqlite3
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from alture_jarvis.agent import named_sources  # noqa: E402
from alture_jarvis.plan import extract as extract_plan  # noqa: E402
from alture_jarvis.task_contract import compile_task_contract  # noqa: E402

DB = r"C:\RoboMetaFit\tools\alture-jarvis\data\jarvis.db"
LIMIT = 300
#: 앞 말에 기대는 판. 라이브는 직전 발화를 붙여 컴파일하므로 여기 수치와 다르다.
_CONTINUATION = ("제안한대로", "저 순위대로", "1부터", "그대로 해", "아까 그")

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

jobs: list[dict] = []
for row in conn.execute(
    "select id,payload_json,result_json from jobs order by created_at desc limit ?",
    (LIMIT,),
):
    try:
        result = json.loads(row["result_json"] or "{}")
    except Exception:
        continue
    steps = (result.get("agent_trace") or {}).get("steps") or []
    prompt = (json.loads(row["payload_json"] or "{}") or {}).get("prompt") or ""
    if not steps or not prompt.strip():
        continue
    jobs.append({"id": row["id"], "prompt": prompt, "steps": steps})

print(f"분모 — 도구를 쓴 판 {len(jobs)}개 (최근 {LIMIT}판 중)\n")

clauses = unclassified = single = 0
policy: collections.Counter = collections.Counter()
bound = unbound = narrowed = 0
reasons: collections.Counter = collections.Counter()
rules: collections.Counter = collections.Counter()
units: collections.Counter = collections.Counter()
roles: collections.Counter = collections.Counter()
silent: collections.Counter = collections.Counter()
continuation = 0
self_diag_suspect: list[str] = []

for job in jobs:
    prompt = job["prompt"]
    contract = compile_task_contract(
        prompt,
        legacy_requirements=extract_plan(
            prompt, has_named_source=bool(named_sources(prompt))
        ),
    )
    clauses += len(contract.clauses)
    unclassified += sum(1 for c in contract.clauses if not c.operations)
    single += len(contract.clauses) == 1
    policy[contract.side_effect_policy] += 1
    for binding in contract.legacy_bindings:
        if binding.clause_id:
            bound += 1
        else:
            unbound += 1
            reasons[binding.reason.split(" ")[0]] += 1
            if binding.clause_ids:
                narrowed += 1
            if binding.reason.startswith("ambiguous"):
                rules[binding.reason.split("rules=")[-1]] += 1
    for clause in contract.clauses:
        for quantity in clause.quantities:
            units[quantity.unit] += 1
            roles[quantity.role] += 1
        # 자기 진단은 「자비스/너」 + 「점검/느려」로 잡는다. `너무`·`건너`의 `너`가
        # 걸리면 남의 사이트 이야기가 자기 진단이 된다 — 실제로 걸린다.
        if "self_diagnose" in clause.operations and not any(
            word in clause.quote for word in ("자비스", "JARVIS", "jarvis")
        ):
            self_diag_suspect.append(clause.quote[:60])
    if not any(c.operations for c in contract.clauses):
        if any(word in prompt for word in _CONTINUATION):
            continuation += 1
        else:
            silent[prompt[:60].replace("\n", " ")] += 1

silent_total = sum(silent.values())
print(f"절 총계              {clauses}개 (판당 {clauses/len(jobs):.1f})")
print(f"분류 못 한 절        {unclassified}/{clauses} = {unclassified/clauses:.0%}")
print(f"절이 하나뿐인 판     {single}/{len(jobs)} = {single/len(jobs):.0%}")
print(f"★ 계약이 침묵한 판   {silent_total}/{len(jobs)} = {silent_total/len(jobs):.0%}"
      f"   (이어받는 판 {continuation}개는 뺐다 — 라이브는 앞 말을 붙인다)")
print(f"정책                 {dict(policy)}")
print(f"레거시 바인딩        묶임 {bound} · 못 묶음 {unbound}"
      + (f" = {unbound/(bound+unbound):.0%} 미결" if bound + unbound else ""))
print(f"  그중 3개 이하로 좁힘 {narrowed}건 ← 아주 모르는 것과 구별한다")
print(f"  못 묶은 사유       {dict(reasons)}")
print(f"  좁히다 걸린 규칙   {dict(rules.most_common(5))}")
print(f"수량 단위            {dict(units.most_common(8))}")
print(f"수량 역할            {dict(roles.most_common())}")
print(f"자기진단 오탐 후보   {len(self_diag_suspect)}건")
for quote in self_diag_suspect[:5]:
    print(f"     {quote}")

print("\n── 계약이 아무것도 못 읽은 문장 (많이 나온 순) ──")
for text, count in silent.most_common(12):
    print(f"  {count:3}판  {text}")
