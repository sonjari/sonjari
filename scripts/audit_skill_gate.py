"""스킬 갈래가 어느 문에서 떨어지는가 — 실제 프롬프트로 센다."""

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

from alture_jarvis import skills as S  # noqa: E402

DB = r"C:\RoboMetaFit\tools\alture-jarvis\data\jarvis.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

prompts: list[str] = []
for (payload,) in conn.execute(
    "select payload_json from jobs where payload_json like '%prompt%' "
    "order by created_at desc limit 900"
):
    try:
        text = (json.loads(payload) or {}).get("prompt") or ""
    except Exception:
        continue
    text = " ".join(text.split())
    if 8 < len(text) < 600:
        prompts.append(text)
prompts = list(dict.fromkeys(prompts))

verdict = collections.Counter()
excluded_by = collections.Counter()
no_target_examples: list[str] = []
excluded_examples: list[tuple[str, str]] = []
picked: list[tuple[str, str]] = []

for text in prompts:
    compact = " ".join(text.split()).lower()
    bad = [w for w in S._SKILL_ROUTE_EXCLUSIONS if w in compact]
    if bad:
        verdict["① 제외 낱말에 걸림"] += 1
        excluded_by[bad[0]] += 1
        if len(excluded_examples) < 8:
            excluded_examples.append((bad[0], text[:80]))
        continue
    if not any(v in compact for v in S._SKILL_TASK_VERBS):
        verdict["② 일 시키는 동사 없음"] += 1
        continue
    hits = [
        (name, sum(1 for t in triggers if t in compact))
        for name, triggers in S.SKILL_TRIGGERS_KO.items()
    ]
    best = max(hits, key=lambda x: x[1]) if hits else ("", 0)
    if best[1] == 0:
        verdict["③ 대상 낱말 없음"] += 1
        if len(no_target_examples) < 10:
            no_target_examples.append(text[:80])
        continue
    verdict["④ 스킬 골라짐"] += 1
    if len(picked) < 10:
        picked.append((best[0], text[:70]))

print(f"서로 다른 프롬프트 {len(prompts)}개")
print("=" * 72)
for label, count in sorted(verdict.items()):
    print(f"  {label:22} {count:4}  ({count * 100 // max(1, len(prompts))}%)")

print()
print("① 제외 낱말 — 무엇이 가장 많이 막나")
for word, count in excluded_by.most_common(10):
    print(f"   {word:12} {count}")
print()
for word, text in excluded_examples:
    print(f"   [{word}] {text}")

print()
print("③ 대상 낱말 없음 — 이런 것들이 떨어진다")
for text in no_target_examples:
    print("   ", text)

print()
print("④ 골라진 것")
for name, text in picked:
    print(f"   {name:26} ← {text}")

print()
print(f"등록된 스킬 갈래 {len(S.SKILL_TRIGGERS_KO)}개")
