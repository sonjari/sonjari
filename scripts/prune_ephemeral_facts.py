"""임시 판에서 들어온 사실을 **덮는다**(지우지 않는다).

## 왜 필요했나 (2026-08-27)

서랍 202건 중 149건(74%)이 벤치·프로브 세션에서 왔다. 그중 「사용자 선호」
17건은 벤치 프롬프트 문구가 사용자님의 영구 취향으로 박힌 것이었다 —
"테스트 파일은 수정하지 마"가 열일곱 번. 벤치의 과제 지시는 그 판에서만
참인 제약이지 사람의 취향이 아니다.

앞으로 들어오는 것은 `fact_extract.ephemeral_session` 이 입구에서 막는다.
이 스크립트는 **이미 들어간 것**만 정리한다.

지우지 않고 `superseded_by` 로 덮는 이유는 되돌릴 수 있어야 하기 때문이다.
행은 남고 회상에서만 빠진다.

    python scripts/prune_ephemeral_facts.py              # 무엇을 덮을지만 보여준다
    python scripts/prune_ephemeral_facts.py --apply      # 실제로 덮는다
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from alture_jarvis.fact_extract import ephemeral_session  # noqa: E402
from alture_jarvis.memory import ConversationMemory  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUNTIME_DB = Path("C:/RoboMetaFit/tools/alture-jarvis/data/jarvis.db")

#: 사실 본문 안에 임시 작업 폴더가 통째로 적힌 것. 다음 실행이면 사라지는 경로다.
_THROWAWAY_MARKERS = (
    "code_repo_bench",
    "code_search_bench",
    "q4_golden",
    "outputs\workspace",
    "outputs/workspace",
)


def throwaway(row: dict) -> str:
    reason = ephemeral_session(str(row.get("session_id") or ""))
    if reason:
        return reason
    blob = f"{row.get('subject') or ''} {row.get('fact') or ''}".lower()
    for marker in _THROWAWAY_MARKERS:
        if marker in blob:
            return f"throwaway_path:{marker}"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(RUNTIME_DB))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    memory = ConversationMemory(Path(args.db))
    live = memory.live_facts(limit=5000)
    doomed = [(row, throwaway(row)) for row in live]
    doomed = [(row, why) for row, why in doomed if why]

    print(f"살아 있는 사실 {len(live)}건 · 덮을 것 {len(doomed)}건")
    print("이유별:", dict(Counter(why.split(":")[0] for _, why in doomed)))
    print("갈래별:", dict(Counter(str(row.get("kind")) for row, _ in doomed)))
    print()
    for row, why in doomed[:12]:
        print(f"  [{row['kind']:10s}] {str(row['subject'])[:28]:28s} | {str(row['fact'])[:52]}")
    if len(doomed) > 12:
        print(f"  … 그리고 {len(doomed) - 12}건 더")

    if not args.apply:
        print()
        print("보기만 했다. 실제로 덮으려면 --apply")
        return 0

    for row, _ in doomed:
        memory.supersede_fact(int(row["id"]))
    remaining = memory.live_facts(limit=5000)
    print()
    print(f"덮었다 {len(doomed)}건 · 남은 사실 {len(remaining)}건")
    print("갈래별 남은 것:", dict(Counter(str(r.get('kind')) for r in remaining)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
