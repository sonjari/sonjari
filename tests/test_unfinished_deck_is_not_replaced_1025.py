"""만들다 만 장표는 답의 표 문서로 대신하지 않는다 (2026-10-25 밤 daisy-days 판 ac529631 — 3/6 장에서 멈춘 판이 표 PPTX 로 「완료」)."""

from types import SimpleNamespace

from alture_jarvis.agent import _forced_artifact_decision

ANSWER = "## 무지개손 겨울방학 특강\n\n| 장 | 내용 |\n|---|---|\n| 1 · 표지 | 무지개손 겨울방학 특강 |\n| 2 · 한눈에 | 기간 1.6~1.31 · 화·목 · 7~10세 |\n" * 3
PLAN = [(SimpleNamespace(kind="artifact", target=(".pptx",), destination=""), False, "열 수 있는 산출물 없음")]


def test_a_deck_in_progress_is_left_unfinished() -> None:
    steps = [{"tool": "local_make_slide", "ok": True, "evidence": {"theme": "daisy-days"}},
             {"tool": "local_make_slide", "ok": True, "evidence": {"title": "무지개손", "index": 1, "total": 6, "saved": True}}]
    call, why = _forced_artifact_decision(PLAN, steps, ANSWER, "무지개손 특강 안내 PPT를 6장으로 만들어 줘")
    assert call is None and why == "deck_in_progress"


def test_choosing_a_theme_alone_does_not_block_the_safety_net() -> None:
    """결만 고르고 장을 하나도 안 넣은 판은 예전 규칙 그대로 판정한다(이 규칙에 걸리지 않는다)."""
    steps = [{"tool": "local_make_slide", "ok": True, "evidence": {"theme": "daisy-days"}}]
    _, why = _forced_artifact_decision(PLAN, steps, ANSWER, "무지개손 특강 안내 PPT를 6장으로 만들어 줘")
    assert why != "deck_in_progress"
