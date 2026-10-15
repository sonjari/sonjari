"""클립보드만 반복해서 올리면 앞 글이 사라진다 — 2026-09-22 실측.

면접 예상 질문에 답변을 만들어 달라는 대화체 요청은 계획 층이 `kind=="artifact"`
로 잡지 않는다("문서로"·"파일로" 같은 낱말이 없다). 그런데 모델이 clipboard_write
로만 답을 올리면, 자리가 하나뿐이라 다음 답을 올리는 순간 앞 답이 지워진다.

산출물 안전망(`_forced_artifact_decision`)이 계획 층 판정과 무관하게, "클립보드에
두 번 이상 올렸는데 파일을 한 번도 안 만들었다"는 패턴만으로도 걸려야 한다. 이 글은
표나 제목이 없는 프로즈(면접 답변)이므로 표·제목 관문은 면제한다.
"""

from __future__ import annotations

from alture_jarvis.agent import (
    _clipboard_overwrote_without_a_file,
    _clipboard_texts,
    _forced_artifact_decision,
)
from alture_jarvis.plan import check as check_plan, extract as extract_plan

INTERVIEW_PROMPT = "면접 예상 질문 3개에 대한 답변을 만들어줘."

# 실제 클립보드에 올라갔을 법한 마지막 답 — 표도 제목도 없는 줄글이다.
INTERVIEW_ANSWER = (
    "세 번째 질문 '팀 프로젝트에서 갈등을 겪은 경험은?' 에 대한 답변입니다. "
    "저는 학교 팀 프로젝트에서 역할 분담을 두고 팀원과 의견이 갈린 적이 있습니다. "
    "저는 먼저 상대의 입장을 정리해 듣고, 제 우려를 근거와 함께 전달해 절충안을 "
    "만들었습니다. 그 결과 마감을 지키면서도 팀원 모두가 만족하는 결과물을 냈고, "
    "이후에도 비슷한 상황에서 먼저 대화를 제안하는 습관이 생겼습니다."
)

# 세 질문에 실제로 클립보드로 올라갔을 법한 글 — 앞 두 개는 답에 안 남고 사라진다.
CLIPBOARD_ANSWERS = [
    "첫 번째 질문 '자기소개를 해 주세요' 에 대한 답변입니다. 저는 대학에서 컴퓨터공학을 "
    "전공하며 팀 프로젝트 중심으로 실력을 쌓았고, 특히 데이터 처리 자동화에 강점이 있습니다.",
    "두 번째 질문 '지원 동기가 무엇인가요' 에 대한 답변입니다. 귀사의 현장 중심 개발 문화가 "
    "제가 학교에서 쌓아 온 실무형 프로젝트 경험과 잘 맞는다고 판단해 지원했습니다.",
    INTERVIEW_ANSWER,
]


def _clipboard_steps(
    count: int, *, ok: bool = True, texts: list[str] | None = None
) -> list[dict[str, object]]:
    return [
        {
            "tool": "clipboard_write",
            "ok": ok,
            "evidence": {"char_count": 120 + index},
            "arguments": {"text": texts[index]} if texts and index < len(texts) else {},
        }
        for index in range(count)
    ]


def _plan_results(steps: list[dict[str, object]]):
    plan = extract_plan(INTERVIEW_PROMPT, has_named_source=False)
    return check_plan(plan, sources=[], steps=steps)


def test_the_prompt_is_not_classified_as_an_artifact_request() -> None:
    """전제 확인: 이 프롬프트는 계획 층이 산출물로 안 잡는다."""
    plan = extract_plan(INTERVIEW_PROMPT, has_named_source=False)
    assert not any(item.kind == "artifact" for item in plan)


def test_one_clipboard_write_is_not_enough_to_trigger() -> None:
    """한 번은 정상적인 붙여넣기일 수 있다 — 덮어쓴 증거가 아니다."""
    steps = _clipboard_steps(1)
    assert not _clipboard_overwrote_without_a_file(steps)
    call, reason = _forced_artifact_decision(
        _plan_results(steps), steps, INTERVIEW_ANSWER, INTERVIEW_PROMPT
    )
    assert call is None
    assert reason == ""


def test_two_clipboard_writes_with_no_file_gets_one_written_for_us() -> None:
    """앞 답이 지워졌을 두 번째부터는 대신 파일로 저장한다 — 표·제목 없이도."""
    steps = _clipboard_steps(2)
    assert _clipboard_overwrote_without_a_file(steps)
    call, reason = _forced_artifact_decision(
        _plan_results(steps), steps, INTERVIEW_ANSWER, INTERVIEW_PROMPT
    )
    assert reason == ""
    assert call is not None
    tool, args = call
    assert tool == "local_write_document"
    blocks = args["blocks"]
    # 내용을 짓지 않는다 — 클립보드에 올랐던 그 글이 그대로 들어간다.
    assert any("갈등을 겪은 경험" in str(block.get("text") or "") for block in blocks)


def test_a_document_already_made_means_nothing_to_rescue() -> None:
    """local_write_document 를 한 번이라도 불렀으면(성공이든 실패든) 더는 걸 일이 없다.

    이 프롬프트는 계획 층도 산출물을 안 시켰으니, 클립보드 증거마저 사라지면
    (문서가 이미 있으니) 애초에 "빚진 것"이 없다 — 그래서 이유도 `""` 다.
    """
    steps = _clipboard_steps(3) + [
        {"tool": "local_write_document", "ok": True, "evidence": {"path": "면접_답변.docx"}}
    ]
    assert not _clipboard_overwrote_without_a_file(steps)
    call, reason = _forced_artifact_decision(
        _plan_results(steps), steps, INTERVIEW_ANSWER, INTERVIEW_PROMPT
    )
    assert call is None
    assert reason == ""


def test_already_attempted_still_reported_when_the_plan_also_wants_an_artifact() -> None:
    """계획이 산출물을 시킨 자리에서는 원래 규율대로 `already_attempted` 가 남는다."""
    prompt = "이 내용을 워드 문서로 정리해줘."
    steps = _clipboard_steps(2) + [
        {"tool": "local_write_document", "ok": False, "evidence": {}}
    ]
    plan = extract_plan(prompt, has_named_source=False)
    results = check_plan(plan, sources=[], steps=steps)
    call, reason = _forced_artifact_decision(results, steps, INTERVIEW_ANSWER, prompt)
    assert call is None
    assert reason == "already_attempted"


def test_short_answer_still_backs_off_even_with_repeated_clipboard_writes() -> None:
    """빈 문서를 만드는 것이 제일 나쁘다 — 이 규율은 클립보드 트리거에도 그대로다."""
    steps = _clipboard_steps(2)
    call, reason = _forced_artifact_decision(
        _plan_results(steps), steps, "알겠습니다.", INTERVIEW_PROMPT
    )
    assert call is None
    assert reason.startswith("answer_too_short:")


def test_failed_clipboard_writes_do_not_count_as_overwriting() -> None:
    """실패한 clipboard_write 는 아무것도 지우지 않았다 — 세지 않는다."""
    steps = _clipboard_steps(3, ok=False)
    assert not _clipboard_overwrote_without_a_file(steps)


def test_a_terse_reply_still_recovers_the_actual_clipboard_text() -> None:
    """★ 이 안전망 자체의 구멍 (2026-09-22, 같은 날 추가 점검에서 발견).

    모델이 "클립보드에 올렸습니다." 처럼 짧게만 답하고 실제 글을 답에 안 옮겨 적으면,
    답만 보던 예전 로직은 `answer_too_short` 로 물러나 아무것도 못 구한다 — 정작 세
    번의 clipboard_write 인자에는 실제 답변 세 개가 고스란히 남아 있는데도. 답이 아니라
    **실제로 도구에 넘어간 글**에서 되살려야 한다.
    """
    steps = _clipboard_steps(3, texts=CLIPBOARD_ANSWERS)
    recovered = _clipboard_texts(steps)
    assert recovered == CLIPBOARD_ANSWERS

    terse = "세 답변 모두 클립보드에 올렸습니다."
    call, reason = _forced_artifact_decision(
        _plan_results(steps), steps, terse, INTERVIEW_PROMPT
    )
    assert reason == ""
    assert call is not None
    tool, args = call
    assert tool == "local_write_document"
    text_in_file = "\n".join(str(b.get("text") or "") for b in args["blocks"])
    # 세 개 다 — 첫 번째·두 번째는 클립보드가 지웠지만 파일에는 살아 있어야 한다.
    assert "자기소개를 해 주세요" in text_in_file
    assert "지원 동기가 무엇인가요" in text_in_file
    assert "갈등을 겪은 경험" in text_in_file


def test_recovery_does_not_kick_in_when_the_answer_already_has_enough() -> None:
    """답이 이미 충분하면 복구 경로를 안 타는지 — 있는 그대로 답을 우선한다."""
    steps = _clipboard_steps(2, texts=["짧은 글", "또 짧은 글"])
    call, reason = _forced_artifact_decision(
        _plan_results(steps), steps, INTERVIEW_ANSWER, INTERVIEW_PROMPT
    )
    assert reason == ""
    tool, args = call
    text_in_file = "\n".join(str(b.get("text") or "") for b in args["blocks"])
    assert "갈등을 겪은 경험" in text_in_file
    assert "짧은 글" not in text_in_file


def test_recovery_still_backs_off_when_even_the_clipboard_texts_are_too_short() -> None:
    """되살려도 짧으면 여전히 빈 문서를 안 만든다."""
    steps = _clipboard_steps(2, texts=["짧다", "이것도 짧다"])
    call, reason = _forced_artifact_decision(
        _plan_results(steps), steps, "올렸습니다.", INTERVIEW_PROMPT
    )
    assert call is None
    assert reason.startswith("answer_too_short:")


def test_explicit_document_request_without_a_table_still_backs_off() -> None:
    """기존 규율 회귀 확인: 계획이 산출물을 시켰는데 줄글뿐이면(클립보드 증거 없이)
    여전히 물러난다 — 이번 변경이 원래 관문을 느슨하게 만들지 않았는지 확인."""
    prompt = "이 내용을 워드 문서로 정리해줘."
    plan = extract_plan(prompt, has_named_source=False)
    assert any(item.kind == "artifact" for item in plan)
    steps: list[dict[str, object]] = []
    results = check_plan(plan, sources=[], steps=steps)
    prose = "그냥 줄글로만 답했습니다. " * 20
    call, reason = _forced_artifact_decision(results, steps, prose, prompt)
    assert call is None
    assert reason.startswith("no_table_or_heading:")
