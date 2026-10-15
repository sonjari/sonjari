"""판 하나를 통째로 펼친다 — **「이 판 이상해」 한 마디로 끝나게.**

    python scripts/inspect_job.py 9941dd71
    python scripts/inspect_job.py            ← 마지막 판

트레이스를 손으로 붙여넣지 않아도 되게 만든 자리다. 한 판을 진단할 때 봐야 하는
것이 여섯 군데에 흩어져 있다 — 걸음 장부 · 계획 대조 · 증거 원장 · 스킬 라우팅 ·
근거 경고 · 사고 원문. 하나라도 빠뜨리면 엉뚱한 데를 판다(오늘만 세 번 그랬다).

읽기 전용이다. 아무것도 안 고친다.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUNTIME = Path(r"C:\RoboMetaFit\tools\alture-jarvis")
DB = RUNTIME / "data" / "jarvis.db"
THINKING = RUNTIME / "outputs" / "thinking"

WARNING_MARK = "읽지 않고 적은 것이 있습니다"


def _line(title: str) -> None:
    print()
    print(f"── {title} " + "─" * max(0, 66 - len(title)))


def main() -> int:
    wanted = sys.argv[1] if len(sys.argv) > 1 else ""
    if not DB.exists():
        print(f"잡 DB 가 없다: {DB}")
        return 1
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    if wanted:
        row = conn.execute(
            "select * from jobs where id like ? order by created_at desc limit 1",
            (wanted + "%",),
        ).fetchone()
    else:
        row = conn.execute(
            "select * from jobs where result_json is not null "
            "order by created_at desc limit 1"
        ).fetchone()
    if row is None:
        print(f"그런 판이 없다: {wanted!r}")
        return 1

    payload = json.loads(row["payload_json"] or "{}")
    result = json.loads(row["result_json"] or "{}")
    trace = result.get("agent_trace") or {}
    verify = trace.get("verification") or {}
    steps = trace.get("steps") or []
    answer = result.get("answer") or ""

    print(f"판 {row['id']}")
    print(f"  상태 {row['status']} · 걸음 {len(steps)} · {verify.get('elapsed_sec', 0):.0f}초"
          f" · 완료 {verify.get('completion_state') or '?'}"
          f" · 멈춘 이유 {verify.get('stop_reason') or '?'}")
    print(f"  예산 {verify.get('step_limit', '?')} · 사고 {verify.get('thinking_chars', 0):,}자"
          f" · 되받기 {verify.get('plan_pushbacks', 0)}"
          f" · 대신읽기 {verify.get('forced_reads', 0)}"
          f" · 대신커밋 {verify.get('forced_commits', 0)}")

    _line("시킨 말")
    print(str(payload.get("prompt") or "")[:1400])

    _line("시킨 것 대조")
    plan = trace.get("plan") or {}
    items = plan.get("items") or []
    if not items:
        print("  요구 0개 — 미달 판정도 되먹임도 대조표도 없다")
    for item in items:
        print(f"  {'O' if item.get('met') else 'X'} {item.get('label')}"
              f"   ({item.get('saw') or ''})")

    _line("증거 원장 — 무엇을 실제로 했나")
    shadow = verify.get("evidence_shadow") or {}
    if not shadow:
        print("  (없음 — 이 기능이 배포되기 전 판이다)")
    else:
        print(f"  증거 {shadow.get('records', 0)} · 목록 {shadow.get('sources_listed', 0)}"
              f" · 열림 {shadow.get('sources_opened', 0)} · 읽음 {shadow.get('sources_read', 0)}")
        if shadow.get("opened_never_read"):
            print(f"  ★ 열고 안 읽음: {shadow['opened_never_read']}")
        if shadow.get("reread_sources"):
            print(f"  ★ 두 번 읽음: {shadow['reread_sources']}")
        if shadow.get("answered_from_listing_only"):
            print("  ★ 목록만 보고 답했다")
        if shadow.get("read_only_violations"):
            print(f"  ★ 읽기 전용인데 쓰기 {shadow['read_only_violations']}건")
    for record in trace.get("evidence") or []:
        print(f"    {str(record.get('type')):11} {str(record.get('tool')):24}"
              f" {str(record.get('source_id'))[-56:]}")

    _line("걸음")
    for step in steps:
        evidence = step.get("evidence") or {}
        note = str(step.get("error") or evidence.get("error") or "")
        fused = " (붙여 읽음)" if step.get("tool") == "browser_extract" else ""
        print(f"  {step.get('step'):3} {str(step.get('tool')):26}"
              f" {'ok' if step.get('ok') else '★실패'}{fused}  {note[:44]}")
        interesting = {
            key: value for key, value in evidence.items()
            if key in {"url", "path", "output_path", "char_count", "rank", "result_count",
                       "query", "footnotes", "verified", "count"}
        }
        if interesting:
            print(f"      {json.dumps(interesting, ensure_ascii=False)[:150]}")

    _line("스킬")
    rows = list(conn.execute(
        "select payload_json from audit_log where event='skill_route_selected' and subject_id=?",
        (row["id"],),
    ))
    if not rows:
        print("  (안 붙음) — 트리거가 안 맞았거나 과업 동사가 없었다")
    for entry in rows:
        got = json.loads(entry[0] or "{}")
        print(f"  {got.get('skill')} (적중 {got.get('trigger_hits')})"
              f" · 같이 {got.get('also') or []} · 접힌 절 {got.get('folded_sections')}")

    _line("답")
    if WARNING_MARK in answer:
        head, _, tail = answer.partition(WARNING_MARK)
        print(head[:900])
        print(f"\n  ★ 근거 경고: {WARNING_MARK}{tail[:220]}")
    else:
        print(answer[:1200])

    kept = THINKING / f"{row['id']}.md"
    _line("사고 원문")
    print(f"  {kept}" if kept.exists() else "  (안 남았다)")

    print()
    print("더 보려면:  scripts/audit_evidence.py · audit_task_contract.py · audit_pipeline.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
