"""**그 초는 어디서 갔나.** 판마다 도구와 모델을 갈라 본다.

## 왜 필요한가

2026-09-10 사슬 벤치에서 중앙 시간이 138초 → 252초로 늘었다. 그런데 그때는
`took_ms` 가 걸음에 안 실려서 **10판 2,495초가 전부 「도구 0초」** 였다 —
도구가 느린지 모델이 느린지 가를 수가 없었다.

`took_ms` 를 걸음 기록에 실은 뒤로 이 셈이 가능해졌다:

    벽시계 − 도구합 = 모델·되받기·계획대조에 쓴 시간

## 분모를 조심한다

`took_ms` 가 0인 걸음이 섞이면 「도구가 빨랐다」가 아니라 **「안 쟀다」**일 수 있다.
그래서 0인 걸음 수를 따로 세어 같이 적는다 — 안 세면 못 잰 것이 빠른 것으로
둔갑한다.

큐 대기(`queued_sec`)는 일한 시간이 아니므로 벽시계에서 뺀다. 이 저장소가 그것을
일한 시간으로 세다 「421초·0걸음」이라는 유령을 본 적이 있다.
"""
from __future__ import annotations

import collections
import json
import pathlib
import shutil
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).parent

_SNAPSHOT: sqlite3.Connection | None = None


def _snapshot() -> sqlite3.Connection:
    """살아 있는 DB 를 **한 번만** 뜬다 (부를 때마다 뜨면 사본이 앞뒤가 안 맞는다)."""
    global _SNAPSHOT
    if _SNAPSHOT is not None:
        return _SNAPSHOT
    src = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data")
    tmp = pathlib.Path("C:/Users/user/AppData/Local/Temp/claude/tb.sqlite")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):   # ★ WAL 없이 뜨면 방금 쓴 판이 안 보인다
        one = src / ("jarvis.db" + suffix)
        if one.exists():
            shutil.copy(one, str(tmp) + suffix)
    _SNAPSHOT = sqlite3.connect(tmp)
    return _SNAPSHOT


def steps_of(job_id: str) -> list[dict]:
    if not job_id:
        return []
    try:
        row = _snapshot().execute(
            "SELECT result_json FROM jobs WHERE id LIKE ?", (job_id + "%",)).fetchone()
        return (json.loads(row[0] or "{}").get("agent_trace") or {}).get("steps") or []
    except Exception:
        return []


def main() -> None:
    src = HERE / "results" / (sys.argv[1] if len(sys.argv) > 1 else "multiturn.json")
    rows = json.loads(src.read_text(encoding="utf-8"))
    per_tool: collections.Counter[str] = collections.Counter()
    per_tool_calls: collections.Counter[str] = collections.Counter()
    total_wall = total_tool = 0.0
    unmeasured = measured = 0

    print(f"{'판':22}{'일한초':>8}{'도구':>8}{'모델등':>8}{'걸음':>6}{'못잰걸음':>9}")
    for row in rows:
        steps = steps_of(str(row.get("job") or ""))
        tool_sec = sum(int(s.get("took_ms") or 0) for s in steps) / 1000
        blind = sum(1 for s in steps if not int(s.get("took_ms") or 0))
        unmeasured += blind
        measured += len(steps) - blind
        # 큐 대기는 일한 시간이 아니다
        worked = float(row.get("elapsed_sec") or row.get("wall_sec") or 0)
        total_wall += worked
        total_tool += tool_sec
        for step in steps:
            name = str(step.get("tool") or "?")
            per_tool[name] += int(step.get("took_ms") or 0) / 1000
            per_tool_calls[name] += 1
        print(f"r{row.get('round')} {str(row.get('task')):18}"
              f"{worked:8.1f}{tool_sec:8.1f}{worked - tool_sec:8.1f}"
              f"{len(steps):6}{blind:9}")

    share = (100 * total_tool / total_wall) if total_wall else 0
    print(f"\n{'합계':22}{total_wall:8.1f}{total_tool:8.1f}{total_wall - total_tool:8.1f}"
          f"   도구가 차지한 비율 {share:.0f}%")
    if unmeasured:
        print(f"★ 시간이 안 실린 걸음 {unmeasured}개 / 잰 걸음 {measured}개 — "
              "이만큼은 「빨랐다」가 아니라 「못 쟀다」이다")

    print("\n오래 걸린 도구 (합계초 · 호출수 · 1회 평균)")
    for name, seconds in per_tool.most_common(12):
        calls = per_tool_calls[name]
        print(f"  {name:28}{seconds:8.1f}{calls:6}{seconds / max(calls, 1):9.1f}")


if __name__ == "__main__":
    main()
