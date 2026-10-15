"""분야 버튼이 스킬 **닿는 비율**을 어떻게 바꾸는가 — 실제 사람 발화로 결정론 재생 (W4 측정).

    python scripts/measure_skill_reach.py --db <jarvis.db> [--out result.json]

재생이다 — 모델을 부르지 않고 `match_skills` 만 돌린다. 그래서 「붙은 판이 더 좋은 답을 냈나」가 아니라
「무엇이 붙을 수 있었나」를 잰다(라이브 A/B 는 따로). 결과에는 **개수만** 싣는다 — 발화 원문은 안 싣는다.

분모를 먼저 적는다: 사람 발화 수 · 일을 시키는 동사가 있는 수 · 아무 분야 없이 붙는 수.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alture_jarvis.config import JarvisConfig  # noqa: E402
from alture_jarvis.skill_domains import DOMAINS, allowed_skills  # noqa: E402
from alture_jarvis.skills import _SKILL_TASK_VERBS, SkillLibrary, match_skills  # noqa: E402


def prompts(db: Path, limit: int) -> list[str]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT content FROM conversation_messages WHERE role = 'user' ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()
    seen: set[str] = set()
    out = []
    for (content,) in rows:
        text = " ".join(str(content or "").split())
        if 4 <= len(text) <= 2000 and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    library = SkillLibrary(JarvisConfig(runtime_root=root, skills_dir=root / "skills"))
    served = {name for name, doc in library.skills.items() if doc.served}
    texts = prompts(Path(args.db), args.limit)
    with_verb = [t for t in texts if any(v in t.lower() for v in _SKILL_TASK_VERBS)]
    base = {t: match_skills(t, available=served, limit=3) for t in texts}
    base_hit = [t for t, m in base.items() if m]
    report: dict = {
        "denominator": {"unique_user_prompts": len(texts), "with_task_verb": len(with_verb),
                        "matched_without_domain": len(base_hit)},
        "top_skills_without_domain": Counter(m[0][0] for m in base.values() if m).most_common(12),
        "domains": {},
    }
    for domain in DOMAINS:
        allowed = allowed_skills((domain.id,), served) or set()
        hits = {t: match_skills(t, available=allowed, limit=3) for t in texts}
        hit = [t for t, m in hits.items() if m]
        # 분야 밖 스킬이 1순위였던 판 — 이 분야를 고르면 **안 붙게 되는** 판.
        dropped = [t for t in base_hit if not hits[t]]
        # 1순위가 바뀐 판 — 분야 안의 다른 스킬로 옮겨 붙은 판.
        moved = [t for t in base_hit if hits[t] and hits[t][0][0] != base[t][0][0]]
        report["domains"][domain.id] = {
            "label": domain.label, "skills": len(allowed), "matched": len(hit),
            "reach_pct": round(100 * len(hit) / max(1, len(texts)), 2),
            "dropped_vs_all": len(dropped), "top_changed": len(moved),
            "top_skills": Counter(m[0][0] for m in hits.values() if m).most_common(6),
        }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    sys.stdout.buffer.write(text.encode("utf-8") + b"\n")


if __name__ == "__main__":
    main()
