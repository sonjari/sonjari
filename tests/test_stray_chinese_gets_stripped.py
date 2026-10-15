"""간체가 한 단어씩 섞여 나오는 버그 — 2026-09-23 사장님 실사용 보고.

Qwen 계열은 중국어·영어 위주 학습이라, 드물게 한글 문장 한가운데 한자 토막이
섞여 나온다. 샘플링 쪽(`min_p`)만으로는 완전히 안 막혀서, 화면에 칠하기
직전 마지막 관문으로 `_strip_stray_chinese` 를 건다.
"""

from __future__ import annotations

from alture_jarvis.agent import _strip_stray_chinese


def test_a_short_stray_han_word_is_removed() -> None:
    text = "이건 정확한 방법입니다设置인데요, 확인해 보세요."
    cleaned, removed = _strip_stray_chinese(text)
    assert removed == ["设置"]
    assert "设置" not in cleaned
    assert "이건 정확한 방법입니다인데요, 확인해 보세요." == cleaned


def test_text_with_no_chinese_is_returned_unchanged() -> None:
    text = "이건 정상적인 한국어 문장입니다."
    cleaned, removed = _strip_stray_chinese(text)
    assert cleaned == text
    assert removed == []


def test_a_long_deliberate_chinese_block_is_left_alone() -> None:
    """사용자가 진짜로 중국어 번역을 시켰으면 그 답은 길다 — 지우면 안 된다."""
    text = "번역해 드립니다: 这是一段用来测试的中文句子，长度超过了短暂误入的门槛。"
    cleaned, removed = _strip_stray_chinese(text)
    assert cleaned == text
    assert removed == []


def test_multiple_short_runs_are_all_removed_and_reported() -> None:
    text = "첫번째报告 그리고 두번째说明 도 섞였습니다."
    cleaned, removed = _strip_stray_chinese(text)
    assert removed == ["报告", "说明"]
    assert "报告" not in cleaned and "说明" not in cleaned


def test_hangul_is_never_touched() -> None:
    text = "완전히 정상적인 한글 문장이고 한자는 전혀 없습니다."
    cleaned, removed = _strip_stray_chinese(text)
    assert cleaned == text
    assert removed == []


def test_removing_a_run_does_not_leave_double_spaces() -> None:
    text = "이 값은 你好 확인된 값입니다."
    cleaned, removed = _strip_stray_chinese(text)
    assert removed == ["你好"]
    assert "  " not in cleaned


def test_empty_text_is_safe() -> None:
    assert _strip_stray_chinese("") == ("", [])
