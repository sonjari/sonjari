"""모델이 **글로** 한 선택지 질문은 질문 카드가 된다 — 코드 판에서 (2026-09-30 촬영 판).

Gemma 4 가 「어떤 방식으로 만들까요? 1. 웹 페이지 2. 파이썬 명령줄 … 골라주세요」를 `ask_user` 없이 글로 세 번 물었고,
코드 게이트는 그걸 「코드 없이 끝내려는 답」으로 되받다 `coding_verification_missing` 으로 닫았다.
도구를 부를 줄 아는 모델만 카드가 떴다. 안내문으로는 못 고친다(사고 R) — 코드가 알아보고 카드로 띄운다.

헛발동이 제일 나쁘다. 운영 답 2,379개에 돌려 처음 42개 → 조건을 좁혀 12개(전부 실제 선택지 질문)로 만들었다.
"""

from __future__ import annotations

import inspect

from alture_jarvis.ask_user import question_from_text

GEMMA = (
    "알겠습니다. 코드를 작성한 후에는 직접 실행하고 검증하겠습니다.\n\n어떤 방식으로 만들까요?\n\n"
    "1. **웹 페이지** (HTML/JS 사용, 브라우저에서 바로 열어서 메모 가능)\n"
    "2. **파이썬 명령줄 프로그램** (터미널에서 명령어로 메모 작성 및 확인)\n\n원하시는 방식을 골라주세요."
)


def test_the_real_gemma_question_becomes_a_card() -> None:
    asked = question_from_text(GEMMA)

    assert asked is not None
    assert asked["question"] == "어떤 방식으로 만들까요?"
    assert [o["label"] for o in asked["options"]] == ["웹 페이지", "파이썬 명령줄 프로그램"]
    assert asked["options"][0]["description"].startswith("HTML/JS")


def test_bracketed_choices_after_a_which_question() -> None:
    text = "분석을 마쳤습니다.\n\n다음 중 어떤 작업을 바로 실행할까요?\n- [시나리오 구체화]\n- [기술적 실체 확인]\n- [판매 전략 수립]"

    asked = question_from_text(text)

    assert asked and [o["label"] for o in asked["options"]] == ["시나리오 구체화", "기술적 실체 확인", "판매 전략 수립"]


def test_a_thought_block_is_not_read_as_the_answer() -> None:
    assert question_from_text("<thought>\n1. A\n2. B\n어느 쪽?\n</thought>이대로 진행하겠습니다.") is None


def test_topic_headings_with_a_yes_no_question_are_not_choices() -> None:
    """헛발동 1위 — 설명용 소제목 목록 뒤의 예/아니오 질문."""
    text = "정리하면 이렇습니다.\n\n1. **정직함:** 못 한 건 못 했다고\n2. **연결성:** MCP 로\n3. **확장성:** 팩으로\n\n더 조사해 드릴까요?"

    assert question_from_text(text) is None


def test_our_own_checker_notes_are_not_choices() -> None:
    text = ("공고 3개를 정리했습니다.\n\n- '정규직' 를 시키셨는데 답에 **인턴** 이 들어 있습니다\n"
            "- '계약직' 를 시키셨는데 답에 **정규직** 이 들어 있습니다\n\n조건에 맞는 것만 다시 찾아드릴까요?")

    assert question_from_text(text) is None


def test_a_research_list_is_not_a_question() -> None:
    text = "교보문고 파이썬 책 3권입니다.\n\n1. 점프 투 파이썬 — 19,800원\n2. 혼자 공부하는 파이썬 — 19,800원\n3. 파이썬 200제 — 18,000원"

    assert question_from_text(text) is None


def test_choices_followed_by_a_long_report_are_not_the_ending_question() -> None:
    text = ("어느 쪽으로 할까요?\n1. A 방식\n2. B 방식\n\n" + "이어서 긴 보고서 본문이 계속됩니다. " * 20)

    assert question_from_text(text) is None


def test_the_agent_turns_it_into_a_card_only_in_code_runs() -> None:
    """배선(소스에서 확인) — 코드 판만, 한 판 두 번까지, ask_user 호출로 바꾼다."""
    from alture_jarvis.agent import BrowserAgent

    source = inspect.getsource(BrowserAgent.run)
    assert "question_from_text(candidate_answer)" in source
    assert '(require_sandbox or model_role == "code")' in source
    assert "agent_question_card_from_text" in source


def test_a_call_we_made_for_the_model_is_recorded_as_called() -> None:
    """대신 만든 호출도 대화에 `tool_calls` 로 남긴다 (2026-09-30 fa50568c).

    빠지면 모델에게는 「글로 물었음 → 부른 적 없는 도구의 결과」로 보인다. 같은 대화를 Gemma 4 에 넣은 재생 실험:
    표시 없음 3/3 이 ask_user 로 되물었고, 표시 있음 0/3 (둘은 파일 쓰기로 진행).
    """
    from alture_jarvis.agent import BrowserAgent

    source = inspect.getsource(BrowserAgent.run)
    assert 'if calls and not message.get("tool_calls"):' in source
    assert '"tool_calls": calls' in source


def test_a_stray_thought_end_and_a_paren_before_the_description() -> None:
    """촬영 판 5f45a7e3 의 실제 모양 — 여는 태그 없는 생각 끝과 「**이름** (괄호): 설명」."""
    text = (
        "사용자가 방식을 고르라고 했다. 선택지를 두 개 보인다.</thought>어떤 방식으로 만드는 게 좋을까요? 원하시는 스타일을 골라 주세요.\n\n"
        "1. **웹 페이지 형태** (HTML/JavaScript): 브라우저에서 바로 열어볼 수 있어 사용이 간편합니다.\n"
        "2. **파이썬 명령줄 프로그램** (Python CLI): 터미널에서 명령어를 입력해 사용하는 방식입니다."
    )

    asked = question_from_text(text)

    assert asked is not None
    assert asked["question"].startswith("어떤 방식으로"), asked["question"]
    assert asked["options"][0]["label"] == "웹 페이지 형태"
    assert asked["options"][0]["description"] == "HTML/JavaScript · 브라우저에서 바로 열어볼 수 있어 사용이 간편합니다."
