"""영어로 물었는데 짧은 한국어로 답하면 다시 쓴다 (2026-10-20 README 영어 영상 촬영).

「Introduce yourself in one line.」 → 「저는 사용자의 로컬 AI 비서 손자리입니다.」(한글 16자)가 「한글 20자 이상」 문턱을 빠져나갔다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis import english

SRC = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis"


def test_short_korean_answer_to_english_prompt_is_caught() -> None:
    assert english.needs_english_rewrite("Introduce yourself in one line.", "저는 사용자의 로컬 AI 비서 손자리입니다.")


def test_long_korean_answer_still_caught() -> None:
    assert english.needs_english_rewrite("How tall is the Eiffel Tower?", "에펠탑의 높이는 330미터이며 1889년에 완공되었습니다. 파리의 상징입니다.")


def test_english_answer_with_a_korean_name_is_left_alone() -> None:
    assert not english.needs_english_rewrite(
        "Find 3 marketing jobs in Seoul on Saramin", "I found 3 jobs. The first is at 이음크리에이티브, posted on Saramin.")


def test_korean_prompt_is_left_alone() -> None:
    assert not english.needs_english_rewrite("한 줄로만 자기소개해 줘.", "저는 손자리입니다.")


def test_tiny_hangul_is_not_a_korean_answer() -> None:
    assert not english.needs_english_rewrite("What is the name of the site?", "사람인 (Saramin)")


def test_empty_answer_is_left_alone() -> None:
    assert not english.needs_english_rewrite("Hello there", "")


def test_both_paths_use_the_one_rule() -> None:
    runtime = (SRC / "runtime.py").read_text(encoding="utf-8")
    agent = (SRC / "agent.py").read_text(encoding="utf-8")
    assert "_english.needs_english_rewrite(prompt, answer)" in runtime
    assert "_english.needs_english_rewrite(prompt, answer)" in agent
    assert ">= 20" not in runtime.split("def _english_if_asked", 1)[1].split("def ", 1)[0]
