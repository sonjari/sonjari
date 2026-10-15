# -*- coding: utf-8 -*-
"""`old_text_not_found` 는 어떤 경우에 나나 — 운영 잡 기록에서 개수만 센다(파일 글은 안 찍는다)."""
import io
import json
import os
import sqlite3
import statistics
import sys
import time
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
RUNTIME = os.environ.get("JARVIS_RUNTIME_ROOT", r"C:\RoboMetaFit\tools\alture-jarvis")
con = sqlite3.connect("file:" + os.path.join(RUNTIME, "data", "jarvis.db") + "?mode=ro", uri=True)
rows = con.execute("select id, result_json, created_at, build from jobs where result_json is not null order by rowid desc limit 4000").fetchall()

READS = {"local_read_text_file", "local_read_document"}


def norm_path(args: dict) -> str:
    return str(args.get("path") or args.get("file") or args.get("file_path") or "").replace("/", "\\").lower().rsplit("\\", 1)[-1]


def arguments_of(step: dict) -> dict:
    args = step.get("arguments")
    if isinstance(args, dict):
        return args
    raw = step.get("call_fingerprint")
    if isinstance(raw, str):
        try:
            return (json.loads(raw).get("arguments")) or {}
        except Exception:
            return {}
    return {}


kinds: Counter[str] = Counter()
recovery: Counter[str] = Counter()
by_period: dict[str, list[int]] = {}
old_lines_fail: list[int] = []
old_lines_ok: list[int] = []
steps_to_recover: list[int] = []
total_fail = 0
for job_id, raw, created, build in rows:
    try:
        data = json.loads(raw)
    except Exception:
        continue
    steps = ((data.get("agent_trace") or {}).get("steps")) or []
    period = "10-04 이후" if float(created or 0) >= time.mktime((2026, 10, 4, 6, 0, 0, 0, 0, -1)) else "그 전"
    for i, step in enumerate(steps):
        if step.get("tool") != "local_apply_edit":
            continue
        args = arguments_of(step)
        old = str(args.get("old") or args.get("old_string") or args.get("old_text") or "")
        new = str(args.get("new") or args.get("new_string") or args.get("new_text") or "")
        target = norm_path(args)
        bucket = by_period.setdefault(period, [0, 0])
        bucket[0] += 1
        if step.get("ok"):
            old_lines_ok.append(old.count("\n") + 1 if old else 0)
            continue
        if not str(step.get("error") or "").startswith("old_text_not_found"):
            continue
        bucket[1] += 1
        total_fail += 1
        old_lines_fail.append(old.count("\n") + 1 if old else 0)
        before = steps[:i]
        same_new_done = any(
            s.get("tool") == "local_apply_edit" and s.get("ok") and norm_path(arguments_of(s)) == target
            and new and str(arguments_of(s).get("new") or "") == new
            for s in before
        )
        last_read = max((j for j, s in enumerate(before) if s.get("tool") in READS and norm_path(arguments_of(s)) == target), default=-1)
        edited_since = any(
            s.get("tool") in {"local_apply_edit", "local_write_file"} and s.get("ok") and norm_path(arguments_of(s)) == target
            for s in before[last_read + 1:]
        )
        wrote_it = any(s.get("tool") == "local_write_file" and s.get("ok") and norm_path(arguments_of(s)) == target for s in before)
        if not old and not args:
            kind = "인자 기록 없음"
        elif same_new_done:
            kind = "A 같은 new 를 이미 넣었다(이미 반영)"
        elif last_read < 0 and not wrote_it:
            kind = "D 이 판에서 그 파일을 읽은 적 없다"
        elif edited_since:
            kind = "B 마지막으로 읽은 뒤 그 파일이 바뀌었다(낡은 눈)"
        elif last_read < 0 and wrote_it:
            kind = "E 자기가 쓴 파일(읽지는 않음)"
        else:
            kind = "C 읽은 뒤 안 바뀌었는데 못 맞췄다"
        kinds[kind] += 1
        # 그 뒤 어떻게 됐나
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        recovered_at = next(
            (j for j, s in enumerate(steps[i + 1:], 1)
             if s.get("tool") in {"local_apply_edit", "local_write_file"} and s.get("ok") and norm_path(arguments_of(s)) == target),
            None,
        )
        if recovered_at is None:
            recovery["끝내 그 파일을 못 고침"] += 1
        else:
            steps_to_recover.append(recovered_at)
            recovery[f"다음 걸음 = {nxt.get('tool') if nxt else '없음'}"] += 1

print(f"old_text_not_found {total_fail}건")
for period, (count, failed) in by_period.items():
    print(f"  {period}: 편집 {count} · 못 찾음 {failed} ({failed / count:.0%})")
print("경우:")
for kind, count in kinds.most_common():
    print(f"  {count:>4}  {kind}")
print("그 뒤:", recovery.most_common(8))
if steps_to_recover:
    print(f"다시 고치기까지 걸음: 가운데 {statistics.median(steps_to_recover)} · 평균 {statistics.mean(steps_to_recover):.1f} (n={len(steps_to_recover)})")
if old_lines_fail and old_lines_ok:
    print(f"old 의 줄 수 — 실패 가운데 {statistics.median(old_lines_fail)} (최대 {max(old_lines_fail)}) · 성공 가운데 {statistics.median(old_lines_ok)} (최대 {max(old_lines_ok)})")
    for limit in (1, 3, 8, 20):
        f = sum(1 for n in old_lines_fail if n > limit)
        o = sum(1 for n in old_lines_ok if n > limit)
        if f + o:
            print(f"  old 가 {limit}줄 넘는 편집: {f + o}건 중 못 찾음 {f} ({f / (f + o):.0%})")
