"""첫 글자 대기 가름표 — `docs/측정계획_첫글자대기_2026-10-21.ko.md` 1단계의 답을 뽑는다.

    python scripts/first_token_wait_report.py [model_calls.jsonl 경로] [--since "2026-10-22 00:00"] [--over 20]

이름표(`purpose` · `prefix_kept`)가 붙은 줄만 본다(10-21 밤 이전 줄에는 없다). 읽기만 한다.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

DEFAULT = Path("C:/RoboMetaFit/tools/alture-jarvis/data/model_calls.jsonl")


def why(prev: dict | None, row: dict) -> str:
    """이 부르기의 앞부분이 왜 캐시에 없었나 — 이름표로 가른다(짐작 칸은 따로 둔다)."""
    if (row.get("load_sec") or 0) > 5:
        return "모델을 다시 올림"
    if prev is not None and prev.get("model") == row.get("model") and prev.get("think") != row.get("think"):
        return "생각 켬/끔 뒤집기"
    if row.get("step_folded"):
        return "계단식 접기"
    kept, before = row.get("prefix_kept"), row.get("prev_messages")
    if kept is None:
        return "그 판의 첫 부르기 · 판 밖"
    if kept < before:
        return f"앞 대화가 바뀜(메시지 {kept}번째부터)" if kept < 3 else "중간이 바뀜(덜어내기 · 안내 붙이기)"
    return "새 글이 붙음(앞은 그대로)"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=str(DEFAULT))
    parser.add_argument("--since", default="")
    parser.add_argument("--over", type=float, default=20.0)
    args = parser.parse_args()
    rows = [json.loads(line) for line in Path(args.path).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if row.get("at", "") >= args.since]
    tagged = [row for row in rows if "purpose" in row or "prefix_kept" in row or "cut" in row]
    print(f"부르기 {len(rows)}건 · 이름표 붙은 것 {len(tagged)}건 · 범위 {rows[0]['at'] if rows else '-'} ~ {rows[-1]['at'] if rows else '-'}")

    cuts = [row for row in rows if row.get("cut")]
    if cuts:
        print("\n## 우리가 중간에 끊은 부르기(생각하다 버린 시간)")
        by = collections.defaultdict(list)
        for row in cuts:
            by[row["cut"]].append(row.get("elapsed_sec") or 0)
        for name, secs in sorted(by.items(), key=lambda item: -sum(item[1])):
            print(f"- {name}: {len(secs)}건 · {int(sum(secs))}초")

    long = []
    prev = None
    for row in rows:
        if row.get("cut"):
            continue  # 끊긴 줄은 첫 글자 대기가 아니라 생각 시간이다 — 위에서 따로 셌다
        if (row.get("first_token_sec") or 0) > args.over:
            long.append((why(prev, row), row))
        prev = row
    print(f"\n## 첫 글자 {args.over:.0f}초 넘은 부르기 {len(long)}건")
    by_why = collections.defaultdict(list)
    for name, row in long:
        by_why[name].append(row)
    for name, items in sorted(by_why.items(), key=lambda item: -sum(r["first_token_sec"] for r in item[1])):
        purposes = collections.Counter(str(r.get("purpose") or "(이름 없음)") for r in items)
        total = sum(r["first_token_sec"] for r in items)
        print(f"- {name}: {len(items)}건 · {int(total)}초 · 어느 부르기: "
              + ", ".join(f"{p} {n}" for p, n in purposes.most_common()))


if __name__ == "__main__":
    main()
