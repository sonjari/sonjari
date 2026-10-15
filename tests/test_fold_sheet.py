"""접기 전 정리 한 장 — 접는 순간 모델이 쓴 정리를 요청 메시지 앞에 싣는다 (2026-10-10 · 재기 전 · 설정으로 끄고 켠다)."""
from __future__ import annotations

from alture_jarvis.transcript import (
    FOLD_SHEET_CLOSE,
    FOLD_SHEET_MAX_CHARS,
    FOLD_SHEET_OPEN,
    FOLD_SHEET_REQUEST,
    JOB_CONTEXT_CLOSE,
    JOB_CONTEXT_OPEN,
    set_fold_sheet,
    with_job_context,
)

REQUEST = "agent.py 를 300줄 줄여줘"


def _conversation(first_user: str) -> list[dict]:
    return [
        {"role": "system", "content": "규칙"},
        {"role": "user", "content": first_user},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "local_grep", "arguments": {}}}]},
        {"role": "tool", "content": "결과"},
        {"role": "user", "content": "[시스템] 안내"},
    ]


def test_the_sheet_goes_in_front_of_the_request_not_into_the_middle() -> None:
    messages = _conversation(REQUEST)
    before = [dict(item) for item in messages]
    assert set_fold_sheet(messages, "## 목표\n300줄 줄이기")
    assert [item["role"] for item in messages] == [item["role"] for item in before], "메시지를 새로 끼우지 않는다"
    assert messages[2:] == before[2:], "요청 메시지 뒤는 한 글자도 안 바뀐다"
    content = messages[1]["content"]
    assert content.startswith(JOB_CONTEXT_OPEN)
    assert content.endswith(REQUEST), "요청 글은 끝에 그대로 남는다"
    assert content.index(FOLD_SHEET_OPEN) < content.index(JOB_CONTEXT_CLOSE)


def test_it_joins_the_context_that_is_already_there() -> None:
    messages = _conversation(with_job_context("지금 시각: 밤", REQUEST))
    assert set_fold_sheet(messages, "## 목표\n줄이기")
    content = messages[1]["content"]
    assert content.count(JOB_CONTEXT_OPEN) == 1 and content.count(JOB_CONTEXT_CLOSE) == 1
    assert "지금 시각: 밤" in content
    assert content.index("지금 시각: 밤") < content.index(FOLD_SHEET_OPEN) < content.index(JOB_CONTEXT_CLOSE)
    assert content.endswith(REQUEST)


def test_the_next_fold_replaces_the_old_sheet() -> None:
    messages = _conversation(with_job_context("지금 시각: 밤", REQUEST))
    set_fold_sheet(messages, "첫 정리")
    set_fold_sheet(messages, "둘째 정리")
    content = messages[1]["content"]
    assert content.count(FOLD_SHEET_OPEN) == 1 and content.count(FOLD_SHEET_CLOSE) == 1
    assert "둘째 정리" in content and "첫 정리" not in content
    assert "지금 시각: 밤" in content and content.endswith(REQUEST)


def test_an_empty_sheet_changes_nothing() -> None:
    messages = _conversation(REQUEST)
    before = [dict(item) for item in messages]
    assert not set_fold_sheet(messages, "   ")
    assert messages == before


def test_a_long_sheet_is_cut() -> None:
    messages = _conversation(REQUEST)
    set_fold_sheet(messages, "가" * (FOLD_SHEET_MAX_CHARS * 3))
    assert len(messages[1]["content"]) < FOLD_SHEET_MAX_CHARS + 500
    assert messages[1]["content"].endswith(REQUEST)


def test_a_system_note_is_not_mistaken_for_the_request() -> None:
    messages = [{"role": "system", "content": "규칙"}, {"role": "user", "content": "[시스템] 안내"}, {"role": "user", "content": REQUEST}]
    assert set_fold_sheet(messages, "정리")
    assert messages[1]["content"] == "[시스템] 안내"
    assert FOLD_SHEET_OPEN in messages[2]["content"]


def test_no_request_message_means_nowhere_to_put_it() -> None:
    assert not set_fold_sheet([{"role": "system", "content": "규칙"}], "정리")


def test_a_request_that_quotes_the_marker_is_not_cut_up() -> None:
    """요청 글이 표시 글자를 인용해도 그 자리를 정리로 알지 않는다 — 정리는 맥락 칸 안의 것만이다."""
    quoted = f"문서에 {FOLD_SHEET_OPEN} 가 뭔지 설명해줘 {FOLD_SHEET_CLOSE} 이것도"
    messages = _conversation(quoted)
    assert set_fold_sheet(messages, "정리")
    assert messages[1]["content"].endswith(quoted)


def test_the_request_tells_the_model_not_to_call_tools_and_names_every_heading() -> None:
    assert "도구를 부르지 마라" in FOLD_SHEET_REQUEST
    for heading in ("목표", "지킬 것", "끝난 것", "하는 중", "막힌 것", "정한 것", "다음 걸음", "다시 읽지 않아도 되게"):
        assert f"## {heading}" in FOLD_SHEET_REQUEST
