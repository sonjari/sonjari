"""판 하나를 통째로 펼치는 자리 — **「이 판 이상해」 한 마디로 끝나게.**

한 판을 진단할 때 봐야 하는 것이 여섯 군데에 흩어져 있다.

    걸음 장부 · 계획 대조 · 증거 원장 · 스킬 라우팅 · 근거 경고 · 사고 원문

하나라도 빠뜨리면 엉뚱한 데를 판다 — 2026-09-03 하루에만 세 번 그랬다
(증거 0인 판을 걸러냄 · 이동을 후보로 셈 · 웹/로컬 혼용).

그래서 **한 자리에서 다 꺼낸다.** 읽기 전용이다.
"""

from __future__ import annotations

from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[1] / "scripts" / "inspect_job.py"
).read_text(encoding="utf-8")


def test_it_pulls_every_place_a_diagnosis_needs() -> None:
    """하나라도 빠지면 그 판은 반쪽만 보인다."""
    for needed in (
        "시킨 것 대조",      # plan
        "증거 원장",         # evidence ledger
        "걸음",              # steps
        "스킬",              # skill_route_selected
        "근거 경고",         # grounding warning in the answer
        "사고 원문",         # outputs/thinking
    ):
        assert needed in SOURCE, needed


def test_it_names_the_silent_failures_it_should_shout_about() -> None:
    """★ 조용한 고장은 **이름을 불러 줘야** 보인다."""
    for mark in (
        "열고 안 읽음",
        "두 번 읽음",
        "목록만 보고 답했다",
        "읽기 전용인데 쓰기",
        "요구 0개",
    ):
        assert mark in SOURCE, mark


def test_it_only_reads() -> None:
    """진단기가 판을 고치면 안 된다 — 보려던 상태가 사라진다."""
    assert "mode=ro" in SOURCE
    for forbidden in ("execute(\"insert", "execute(\"update", "execute(\"delete", "write_text("):
        assert forbidden not in SOURCE.lower(), forbidden


def test_it_works_with_a_prefix_or_nothing_at_all() -> None:
    """잡 ID 앞자리만 줘도, 아무것도 안 줘도 돌아야 한다 — 그래야 싸다."""
    assert 'wanted + "%"' in SOURCE
    assert "order by created_at desc limit 1" in SOURCE
