"""증거 원장 계측 — 도구가 실제로 무엇을 했나.

    분모 먼저. 비율은 그 다음.

⚠ **과거 판에는 증거가 없다.** 증거는 실행 중에만 만들어진다(도구 결과가 길목을
지날 때). 그래서 이 자는 「원장을 가진 판」을 따로 세고 그것만 분모로 쓴다.
원장 없는 판을 분모에 넣으면 무엇을 고쳐도 비율이 안 움직인다 — 이 저장소가
눈금 분모에서 여러 번 겪은 자리다.

세는 네 가지:

    page_open 만 있고 body_read 가 없는 출처   ← 「3개 읽었다」의 거짓이 여기 산다
    같은 출처를 두 번 이상 읽은 판
    read_only 판에서 생긴 쓰기                  ← 0 이어야 한다
    어느 절도 뒷받침하지 못한 증거의 비율
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

DB = r"C:\RoboMetaFit\tools\alture-jarvis\data\jarvis.db"
LIMIT = 300

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

with_tools = 0
with_ledger: list[dict] = []
for row in conn.execute(
    "select id,created_at,payload_json,result_json from jobs "
    "order by created_at desc limit ?",
    (LIMIT,),
):
    try:
        result = json.loads(row["result_json"] or "{}")
    except Exception:
        continue
    trace = result.get("agent_trace") or {}
    if not (trace.get("steps") or []):
        continue
    with_tools += 1
    ledger = trace.get("evidence") or []
    shadow = (trace.get("verification") or {}).get("evidence_shadow")
    # ★ **분모 구멍이었다.** 처음에는 `if not ledger: continue` 였다 — 증거가 0 인
    #   판을 걸러 냈는데, 그게 **제일 봐야 할 판**이다(도구는 썼는데 원장이 빈 판).
    #   실제로 `local_read_document` 구멍이 그렇게 숨었다. 판을 가르는 기준은
    #   「증거가 있나」가 아니라 「원장을 만들 수 있는 판이었나」다.
    if shadow is None:
        continue  # 이 기능이 배포되기 전 판 — 애초에 만들 수가 없었다
    with_ledger.append(
        {
            "id": row["id"],
            "prompt": (json.loads(row["payload_json"] or "{}") or {}).get("prompt") or "",
            "ledger": ledger,
            "steps": trace.get("steps") or [],
            "shadow": shadow or {},
            "policy": ((trace.get("contract") or {}).get("side_effect_policy")) or "",
        }
    )

print(f"분모 — 도구를 쓴 판 {with_tools}개 (최근 {LIMIT}판 중)")
print(f"       그중 증거 원장이 있는 판 {len(with_ledger)}개"
      f"{'  ← 이것만 분모로 쓴다' if with_ledger else ''}")
if not with_ledger:
    print("\n원장을 가진 판이 아직 없다. 증거는 **실행 중에만** 생긴다 —")
    print("과거 판을 재생해서는 못 만든다. 새 판을 돌린 뒤 다시 재라.")
    raise SystemExit(0)

kinds: collections.Counter = collections.Counter()
tools: collections.Counter = collections.Counter()
opened_never_read = 0
opened_never_read_sources: list[tuple[str, str]] = []
reread_jobs = 0
violations = 0
unsupported = 0
records = 0

for job in with_ledger:
    for record in job["ledger"]:
        records += 1
        kinds[str(record.get("type") or "?")] += 1
        tools[str(record.get("tool") or "?")] += 1
        # 연 것이 아무 요구도 못 채우는 것은 **설계대로**다. 그것까지 「못 뒷받침」
        # 으로 세면 비율이 늘 나빠 보여 아무도 안 읽는 줄이 된다.
        if (
            not record.get("supports_clause_ids")
            and str(record.get("type") or "") != "page_open"
        ):
            unsupported += 1
    seen = job["shadow"]
    missed = list(seen.get("opened_never_read") or [])
    if missed:
        opened_never_read += len(missed)
        for source in missed[:2]:
            opened_never_read_sources.append((job["id"][:8], source))
    if seen.get("reread_sources"):
        reread_jobs += 1
    violations += int(seen.get("read_only_violations") or 0)

empty = [job for job in with_ledger if not job["ledger"]]
print(
    f"\n★ 도구를 썼는데 원장이 빈 판  {len(empty)}/{len(with_ledger)}"
    + ("   ← 표에 없는 문으로 일했다는 뜻" if empty else "")
)
for job in empty[:5]:
    used = sorted({str(step.get("tool") or "") for step in job["steps"]})
    print(f"     [{job['id'][:8]}] {', '.join(used)[:74]}")

print(f"\n증거 {records}건")
print(f"  종류        {dict(kinds.most_common())}")
print(f"  도구        {dict(tools.most_common())}")
print(f"\n★ 열고서 본문을 안 읽은 출처   {opened_never_read}곳"
      f"  ({sum(1 for j in with_ledger if (j['shadow'].get('opened_never_read') or []))}"
      f"/{len(with_ledger)}판)")
for job_id, source in opened_never_read_sources[:8]:
    print(f"     [{job_id}] {source[:78]}")
listing_only = [job for job in with_ledger if job["shadow"].get("answered_from_listing_only")]
print(
    f"★ 목록만 보고 답한 판           {len(listing_only)}/{len(with_ledger)}"
    "   ← 고장이 아니라 신호다(목록이 곧 답인 요청도 있다)"
)
for job in listing_only[:6]:
    print(f"     [{job['id'][:8]}] {job['prompt'][:66].replace(chr(10), ' ')}")
print(f"같은 출처를 두 번 이상 읽은 판  {reread_jobs}/{len(with_ledger)}")
print(f"읽기 전용 판에서 생긴 쓰기      {violations}건  ← 0 이어야 한다")
print(f"어느 절도 못 뒷받침한 증거      {unsupported}/{records}"
      f" = {unsupported/records:.0%}" if records else "")

# ★ 이 줄이 첫 라이브 판에서 `local_read_document` 구멍을 잡았다.
# 걸음에는 있는데 증거를 한 번도 안 남긴 도구 — 표에 빠졌거나 출처가 없다는 뜻이다.
# **읽고 쓰는 일을 하는데 표에 없으면 이 원장 전체가 조용히 는다.**
from alture_jarvis import evidence as evidence_module  # noqa: E402

silent_tools: collections.Counter = collections.Counter()
for job in with_ledger:
    minted = {
        str((step.get("evidence_record") or {}).get("tool") or "")
        for step in job["steps"]
        if isinstance(step.get("evidence_record"), dict)
    }
    for step in job["steps"]:
        tool = str(step.get("tool") or "")
        if tool and tool not in minted and tool in evidence_module.MANIFEST:
            silent_tools[tool] += 1
print(f"\n표에 있는데 증거를 못 남긴 호출  {sum(silent_tools.values())}건 {dict(silent_tools) or ''}")
outside = collections.Counter(
    str(step.get("tool") or "")
    for job in with_ledger
    for step in job["steps"]
    if str(step.get("tool") or "") not in evidence_module.MANIFEST
)
print("표 밖 도구 상위 (읽기·쓰기가 섞여 있으면 표에 넣을 것):")
for tool, count in outside.most_common(8):
    print(f"     {count:3}  {tool}")

print("\n── 판별 ──")
for job in with_ledger[:12]:
    seen = job["shadow"]
    print(
        f"  [{job['id'][:8]}] 정책={job['policy'] or '없음':11}"
        f" 증거{seen.get('records', 0):3}"
        f" 열림{seen.get('sources_opened', 0):3}"
        f" 읽음{seen.get('sources_read', 0):3}"
        f" 안읽음{len(seen.get('opened_never_read') or []):3}"
        f"  {job['prompt'][:44].replace(chr(10), ' ')}"
    )
