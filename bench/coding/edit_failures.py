# -*- coding: utf-8 -*-
"""운영 잡 기록에서 편집 도구(local_apply_edit)가 어떤 이유로 얼마나 실패했나 — 개수만 본다(글은 안 찍는다)."""
import io
import json
import os
import re
import sqlite3
import sys
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
RUNTIME = os.environ.get("JARVIS_RUNTIME_ROOT", r"C:\RoboMetaFit\tools\alture-jarvis")
con = sqlite3.connect("file:" + os.path.join(RUNTIME, "data", "jarvis.db") + "?mode=ro", uri=True)
cols = [r[1] for r in con.execute("pragma table_info(jobs)")]
result_col = "result_json" if "result_json" in cols else ("result" if "result" in cols else None)
print("열:", cols)
rows = con.execute(f"select id, {result_col} from jobs where {result_col} is not null order by rowid desc limit 4000").fetchall()

jobs_with_edit = 0
edits = ok = 0
kinds: Counter[str] = Counter()
healed: Counter[str] = Counter()
after_fail_same_file_retry = 0
syntax_fail_after_edit = 0          # 편집 성공 → 바로 다음 실행이 SyntaxError/IndentationError 로 실패
edit_then_run = 0
not_unique_then = Counter()
for job_id, raw in rows:
    try:
        data = json.loads(raw)
    except Exception:
        continue
    steps = ((data.get("agent_trace") or {}).get("steps")) or []
    if not any(s.get("tool") == "local_apply_edit" for s in steps):
        continue
    jobs_with_edit += 1
    for i, step in enumerate(steps):
        if step.get("tool") != "local_apply_edit":
            continue
        edits += 1
        evidence = step.get("evidence") or {}
        if step.get("ok"):
            ok += 1
            if isinstance(evidence, dict) and evidence.get("healed"):
                healed[str(evidence.get("healed"))] += 1
            # 다음 실행 걸음이 문법 오류로 떨어졌나
            for later in steps[i + 1: i + 4]:
                if later.get("tool") in {"local_run_project_command", "sandbox_run", "local_run_shell"}:
                    edit_then_run += 1
                    blob = json.dumps(later.get("evidence") or {}, ensure_ascii=False)
                    if re.search(r"SyntaxError|IndentationError|TabError", blob):
                        syntax_fail_after_edit += 1
                    break
            continue
        error = str(step.get("error") or "")
        kind = re.split(r"[:\s—-]", error.strip(), maxsplit=1)[0][:40] or "(빈 오류)"
        kinds[kind] += 1
        if kind == "old_text_not_unique":
            nxt = next((s for s in steps[i + 1: i + 3] if s.get("tool")), {})
            not_unique_then[str(nxt.get("tool"))] += 1

print(f"편집이 있는 판 {jobs_with_edit} · 편집 호출 {edits} · 성공 {ok} ({ok / edits:.0%})" if edits else "편집 없음")
print("실패 종류:", kinds.most_common(12))
print("구제해서 성공한 것:", healed.most_common(8))
print(f"편집 성공 뒤 3걸음 안에 실행이 있던 것 {edit_then_run} · 그 실행이 문법 오류로 떨어진 것 {syntax_fail_after_edit}")
print("여러 군데 일치 뒤 다음 걸음:", not_unique_then.most_common(6))
