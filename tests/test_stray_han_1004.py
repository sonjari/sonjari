"""끼어든 한자 고치기 — 일하면서 하는 말에도, 영어 화면에도 (2026-10-04 사다리 L2 화면 「원격 관測 시작」)."""

from __future__ import annotations

from alture_jarvis.agent import _strip_stray_chinese
from alture_jarvis.narration import clean as clean_narration
from alture_jarvis.stray_han import READINGS, mend


def test_a_han_character_inside_a_korean_word_becomes_its_korean_sound() -> None:
    text, touched = mend("원격 관測 시작 버튼을 눌러 반응을 확인하겠다.")
    assert text == "원격 관측 시작 버튼을 눌러 반응을 확인하겠다."
    assert touched == ["測→측"]
    assert mend("검证 완료")[0] == "검증 완료"
    assert mend("결果를 정리한다")[0] == "결과를 정리한다"


def test_two_or_more_characters_are_removed_never_sounded_out() -> None:
    """중국어 낱말은 한국어 소리로 읽으면 다른 낱말이 된다 — 「设置」(설정)는 소리로 「설치」다."""
    text, touched = mend("이건 정확한 방법입니다设置인데요")
    assert text == "이건 정확한 방법입니다인데요" and touched == ["设置"]
    # ★ 같은 날 오후: 문장 **속**의 아는 낱말은 지우지 않고 뜻으로 바꾼다(소리로는 여전히 안 바꾼다) — 아래 뜻 표 시험.
    assert mend("설정을 确认했습니다")[0] == "설정을 확인했습니다"


def test_a_single_character_that_completes_no_known_word_is_removed() -> None:
    """「좋습니다好」의 好 는 한글 낱말의 음절이 아니다 — 「다호」는 낱말이 아니므로 지운다."""
    assert mend("좋습니다好 다음으로 갑니다") == ("좋습니다 다음으로 갑니다", ["好"])


def test_a_character_with_more_than_one_sound_is_removed_not_guessed() -> None:
    """樂(락·악·요)·行(행·항)·度(도·탁)·不(불·부) 처럼 소리가 갈리는 글자는 표에 없다 — 지운다."""
    for char in "樂行度不便更說率力理料":
        assert char not in READINGS, char
    text, touched = mend("실행行 결과")
    assert text == "실행 결과" and touched == ["行"]


def test_han_in_an_english_sentence_is_removed() -> None:
    text, touched = mend("Clicked the 设置 button and the status changed.")
    assert text == "Clicked the button and the status changed."
    assert touched == ["设置"]


def test_a_long_chinese_passage_is_left_alone() -> None:
    """사용자가 시킨 번역·인용일 수 있다 — 긴 덩어리는 건드리지 않는다."""
    passage = "这是用户要求翻译成中文的一段很长的文字"
    assert mend(f"번역: {passage}") == (f"번역: {passage}", [])


def test_plain_text_is_untouched() -> None:
    assert mend("카드 3개가 그려졌다. 92% · 78% · 54%") == ("카드 3개가 그려졌다. 92% · 78% · 54%", [])
    assert mend("") == ("", [])


def test_the_final_answer_gate_and_the_narration_use_the_same_rule() -> None:
    assert _strip_stray_chinese("원격 관測 시작")[0] == "원격 관측 시작"
    assert clean_narration("j4(원격 관測 시작)를 클릭해 상단 버튼 반응도 확인하겠다.") == (
        "j4(원격 관측 시작)를 클릭해 상단 버튼 반응도 확인하겠다."
    )
    assert clean_narration("Opening the page and clicking 设置 to check the reaction.") == (
        "Opening the page and clicking to check the reaction."
    )


def test_every_reading_is_one_hangul_syllable_and_no_character_has_two() -> None:
    assert all(len(sound) == 1 and "가" <= sound <= "힣" for sound in READINGS.values())
    from alture_jarvis.stray_han import _BY_READING

    seen: dict[str, str] = {}
    for sound, chars in _BY_READING.items():
        for char in chars:
            assert char not in seen, f"{char} 가 {seen.get(char)}·{sound} 두 소리에 들어 있다"
            seen[char] = sound


def test_another_script_wedged_between_hangul_syllables_is_removed() -> None:
    """사다리 L2 답의 「노\u0e23웨이」 — 태국 글자 하나가 한글 음절 사이에 끼었다."""
    text, touched = mend("트롬소 — 노\u0e23웨이 · 북해 연안")
    assert text == "트롬소 — 노웨이 · 북해 연안" and touched == ["\u0e23"]
    # 띄어 쓴 외국어 낱말은 사용자가 인용한 것일 수 있다 — 건드리지 않는다.
    quoted = "러시아어로 \u043f\u0440\u0438\u0432\u0435\u0442 은 안녕이라는 뜻이다"
    assert mend(quoted) == (quoted, [])


# --- 뜻으로 바꾸기 · 질문 카드 (라이브 351858ba) ---------------------------------

def test_a_known_chinese_word_in_a_korean_sentence_becomes_its_meaning() -> None:
    """지우기만 하면 「폴더를합니다 · 정리에서 제외」가 돼 무엇을 고르는지가 사라진다 — 사람이 눌러야 하는 카드에서."""
    from alture_jarvis.stray_han import mend

    fixed, touched = mend("old_assets 폴더를保存합니다. 저장소 정리对象에서 제외.")

    assert fixed == "old_assets 폴더를저장합니다. 저장소 정리대상에서 제외."
    assert touched == ["保存→저장", "对象→대상"]
    # 소리가 아니라 뜻이다(设置: 「설치」가 아니라 「설정」).
    assert mend("화면 设置 을 바꿨습니다")[0] == "화면 설정 을 바꿨습니다"
    # 붙어 나온 두 낱말도 전부 알면 바꾼다.
    assert mend("이제 删除文件 합니다")[0] == "이제 삭제파일 합니다"


def test_unknown_words_and_english_sentences_are_still_only_cleaned() -> None:
    from alture_jarvis.stray_han import mend

    # 표에 없는 낱말 — 모르는 뜻을 채우지 않는다.
    assert mend("이건 麒麟 입니다")[0] == "이건 입니다"
    # 한 조각이라도 모르면 통째로 지운다(반만 바꾸지 않는다).
    assert "저장" not in mend("이건 保存麒 입니다")[0]
    # 영어 문장에는 한국어를 끼우지 않는다.
    assert mend("The folder is 保存 now")[0] == "The folder is now"


def test_the_question_card_shows_mended_text_and_still_matches_the_choice() -> None:
    from alture_jarvis.ask_user import AskUserTool

    arguments = {
        "question": "old_assets 폴더를 删除 할까요?",
        "options": [
            {"label": "강제로 삭제", "description": "폴더를 되돌릴 수 없이 지웁니다."},
            {"label": "그대로 保存", "description": "old_assets 폴더를保存합니다. 저장소 정리对象에서 제외."},
        ],
    }

    card = AskUserTool.describe(arguments)

    assert card["question"] == "old_assets 폴더를 삭제 할까요?"
    assert card["options"][1]["label"] == "그대로 저장"
    assert card["options"][1]["description"] == "old_assets 폴더를저장합니다. 저장소 정리대상에서 제외."
    # 사람은 고친 글을 보고 눌렀다 — 그 선택지로 알아본다(직접 적은 말로 취급하지 않는다).
    assert AskUserTool.answer({**arguments, "__answer": "그대로 저장"})["free_text"] is False
