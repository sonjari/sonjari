"""개입 장부 — 하네스가 판마다 끼어든 일을 판 기록에서 다시 세어 표로 낸다 (2026-10-26 최소 개입 설계 ④).

새 칸을 더하지 않고 이미 있는 기록(jobs.result_json 의 agent_trace.steps · verification)에서 계산한다.
사다리 이름은 Guardrails AI 의 OnFailAction 을 빌린다:

    fix      0~1단  코드가 고쳐 받음          steps[].evidence.fixed · verification.answer_corrected · forced_commits
    reask    2단    모델에게 다시 시킴        실패한 걸음의 오류 이름(「slide_sparse: …」) · plan_pushbacks · final_sent_back
    noop     3단    표시만                    steps[].evidence.typo_check · reported_shortfall
    (exception 4단 — 막음 — 은 지금 기록에서 따로 가르지 않는다)

돌려보내기 효과: 같은 손의 다음 부름(장표는 같은 장 번호)이 **바꿔 냈나 · 똑같이 냈나 · 다시 안 냈나**.
장표 「비었다」는 `--remeasure` 를 주면 최종본을 다시 재서 40% 아래로 내려갔는지 본다(느리다 — 장마다 브라우저).

    python scripts/intervention_report.py                 # 지난 20일
    python scripts/intervention_report.py --days 3 --remeasure
    python scripts/intervention_report.py --jobs fa828a92,8c9de860   # 판 id 앞부분으로만
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

RUNTIME = Path(r"C:\RoboMetaFit\tools\alture-jarvis")
OUT = Path(__file__).resolve().parents[3] / "generated_reports" / "intervention"
_CODE = re.compile(r"^([a-z][a-z0-9_]{2,}):")


def job_kind(steps: list[dict], payload: dict) -> str:
    tools = {str(s.get("tool") or "") for s in steps}
    if "local_make_slide" in tools:
        return "장표"
    if str(payload.get("agent_mode") or "") == "code" or str(payload.get("delegated_repo") or ""):
        return "코드"
    if tools & {"local_write_document", "local_edit_document", "local_edit_spreadsheet", "hwp_apply_edit", "artifact_from_observations"}:
        return "문서" if not any(t.startswith("browser_") for t in tools) else "웹 조사 + 문서"
    if any(t.startswith("browser_") for t in tools):
        return "웹 조사"
    return "대화 · 기타" if tools else "도구 없음"


def _sig(arguments: dict) -> str:
    return hashlib.md5(json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _error(step: dict) -> str:
    evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
    return str(step.get("error") or evidence.get("error") or "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=float, default=20)
    parser.add_argument("--jobs", default="", help="쉼표로 가른 판 id 앞부분 — 주면 그 판만")
    parser.add_argument("--remeasure", action="store_true", help="장표 「비었다」 최종본을 다시 잰다")
    parser.add_argument("--db", default=str(RUNTIME / "data" / "jarvis.db"))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    prefixes = [p.strip() for p in args.jobs.split(",") if p.strip()]
    since = dt.datetime.now().timestamp() - args.days * 86400
    rows = db.execute("select id, payload_json, result_json, created_at from jobs where result_json like '%agent_trace%'").fetchall()

    kinds = collections.defaultdict(lambda: {"jobs": 0, "steps": 0, "reask_steps": 0, "partial": 0, "complete": 0})
    reask = collections.defaultdict(lambda: collections.Counter())   # (kind, code) → changed/same/never
    fixes = collections.Counter()
    noops = collections.Counter()
    loop = collections.defaultdict(lambda: collections.Counter())    # verification 칸
    sparse_targets: list[tuple[str, int, int]] = []

    for job_id, payload_json, result_json, created in rows:
        if prefixes and not any(job_id.startswith(p) for p in prefixes):
            continue
        if not prefixes and float(created or 0) < since:
            continue
        try:
            result = json.loads(result_json or "{}")
            payload = json.loads(payload_json or "{}")
        except ValueError:
            continue
        trace = result.get("agent_trace") or {}
        steps = trace.get("steps") or []
        verification = trace.get("verification") or {}
        kind = job_kind(steps, payload)
        k = kinds[kind]
        k["jobs"] += 1
        k["steps"] += len(steps)
        state = str(result.get("completion_state") or verification.get("completion_state") or "")
        k["partial"] += state == "partial"
        k["complete"] += state == "complete"
        for i, step in enumerate(steps):
            evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
            for note in evidence.get("fixed") or []:
                fixes[(kind, re.sub(r"[「『].*?[」』]|\d+", "…", str(note))[:48])] += 1
            for note in evidence.get("typo_check") or []:
                noops[(kind, "typo_check")] += 1
            if evidence.get("sparse_check"):  # 10-26 부터 「비었다」는 돌려보내지 않고 표시만(3단)
                noops[(kind, "sparse_check")] += 1
            if step.get("ok"):
                continue
            match = _CODE.match(_error(step))
            if not match:
                continue
            code = match.group(1)
            k["reask_steps"] += 1
            tool = str(step.get("tool") or "")
            arguments = step.get("arguments") or {}
            same_slot = (lambda other: (other.get("arguments") or {}).get("index") == arguments.get("index")) if tool == "local_make_slide" else (lambda other: True)
            later = next((t for t in steps[i + 1:] if str(t.get("tool") or "") == tool and same_slot(t)), None)
            if later is None:
                reask[(kind, f"{tool}:{code}")]["never"] += 1
            elif _sig(later.get("arguments") or {}) == _sig(arguments):
                reask[(kind, f"{tool}:{code}")]["same"] += 1
            else:
                reask[(kind, f"{tool}:{code}")]["changed"] += 1
            reask[(kind, f"{tool}:{code}")]["count"] += 1
            if code == "slide_sparse":
                m = re.match(r"slide_sparse: (\d+)번 장의 부품 칸이 (\d+)%", _error(step))
                if m:
                    sparse_targets.append((job_id, int(m.group(1)), int(m.group(2))))
        for key in ("plan_pushbacks", "forced_reads", "forced_commits"):
            value = verification.get(key)
            if isinstance(value, (int, float)) and value:
                loop[kind][key] += int(value)
        if verification.get("plan_pushback_worked") is True:
            loop[kind]["plan_pushback_worked"] += 1
        for key in ("answer_corrected", "final_sent_back", "deliver_turn_before_wrap_up", "empty_answer_synthesis", "reported_shortfall"):
            if verification.get(key):
                loop[kind][key] += 1
        fallback = str(verification.get("artifact_fallback") or "")
        if fallback.startswith("fired"):
            loop[kind]["artifact_fallback:fired"] += 1

    lines = [f"# 개입 장부 — {dt.date.today().isoformat()}", "",
             f"범위: {'판 ' + args.jobs if prefixes else f'지난 {args.days:g}일'} · `scripts/intervention_report.py` 가 판 기록에서 다시 셈.", "",
             "## 판 종류별", "", "| 종류 | 판 | 걸음 | 돌려보내기(reask) 걸음 | 비율 | 일부만 됨 | 완료 |", "|---|---|---|---|---|---|---|"]
    for kind, k in sorted(kinds.items(), key=lambda x: -x[1]["jobs"]):
        ratio = k["reask_steps"] / k["steps"] if k["steps"] else 0
        lines.append(f"| {kind} | {k['jobs']} | {k['steps']} | {k['reask_steps']} | {ratio:.0%} | {k['partial']} | {k['complete']} |")
    lines += ["", "## 돌려보내기(reask) — 오류 이름별", "", "| 종류 | 손:오류 | 횟수 | 바꿔 냄 | 똑같이 냄 | 다시 안 냄 |", "|---|---|---|---|---|---|"]
    for (kind, code), c in sorted(reask.items(), key=lambda x: -x[1]["count"]):
        lines.append(f"| {kind} | `{code}` | {c['count']} | {c['changed']} | {c['same']} | {c['never']} |")
    lines += ["", "## 고쳐 받음(fix) · 표시만(noop)", "", "| 종류 | 무엇 | 횟수 |", "|---|---|---|"]
    for (kind, note), n in sorted({**fixes, **noops}.items(), key=lambda x: -x[1]):
        lines.append(f"| {kind} | {note} | {n} |")
    lines += ["", "## 루프 안 개입(판 기록 verification 칸)", "", "| 종류 | 칸 | 값(숫자 칸은 합 · 참/거짓 칸은 판 수) |", "|---|---|---|"]
    for kind, counter in loop.items():
        for key, value in counter.most_common():
            lines.append(f"| {kind} | `{key}` | {value} |")
    if args.remeasure and sparse_targets:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from alture_jarvis import slides  # noqa: E402

        lines += ["", "## 「비었다」 돌려보낸 장 — 최종본 다시 재기", "", "| 판 | 장 | 그때 | 최종본 |", "|---|---|---|---|"]
        work = Path(tempfile.mkdtemp())
        better = 0
        for job_id, index, before in sparse_targets:
            found = list((RUNTIME / "outputs" / "slides" / job_id).glob(f"*/slide_{index:02d}.html"))
            if not found:
                lines.append(f"| {job_id[:8]} | {index} | {before}% | 파일 없음(판이 접힘) |")
                continue
            copy = work / f"{job_id[:8]}_{index}.html"
            shutil.copy(found[0], copy)
            copy.write_text(re.sub(r'(<[^>]+?) style="font-size:[^"]*"', r"\1", copy.read_text(encoding="utf-8")), encoding="utf-8")
            after = round(float(slides.fit_slide(copy).get("empty") or 0) * 100)
            better += after < 40
            lines.append(f"| {job_id[:8]} | {index} | {before}% | {after}% |")
        lines.append(f"\n40% 아래로 내려간 장: {better} / {len(sparse_targets)}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"개입장부_{dt.date.today().isoformat()}{'_' + args.jobs[:20].replace(',', '_') if prefixes else ''}.md"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(target)
    print("\n".join(lines[:40]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
