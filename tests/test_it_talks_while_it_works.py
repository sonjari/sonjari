"""일하면서 말한다 — 그리고 **그 말은 증거가 아니다** (2026-09-21 사장님 요청).

> 사용자 입장에서도 문제가 되는 거는 바로잡을 수 있고 …
> 지금은 지시하면 결과를 다 만들고 한 번에 답변을 하는데

## 실측이 가른 것

| | 말함 | 도구 부름 |
|---|---|---|
| 안내 없음 | 0/3 | 3/3 |
| 말하라고 시킴 | 3/3 | 3/3 |

기계적으로는 된다. **그런데 같은 실측에서 이런 말이 나왔다:**

    "'weekly_fee' 같은 유사한 이름의 함수를 찾아봤습니다."   ← 찾아본 적 없다

그래서 이 시험의 절반은 **말이 증거로 새지 않는가**를 본다.
「한 척말고 본 척도 잡기」와 같은 자리다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.narration import (
    MAX_CHARS,
    NARRATION_INSTRUCTION,
    clean,
    enabled_for,
)


# ── ① 말을 화면에 낼 수 있는 모양으로 ──────────────────────────────────────
def test_a_plain_sentence_passes_through() -> None:
    said = "저장소에서 `agent_grade` 가 정의된 파일을 찾기 위해 검색하겠습니다."
    assert clean(said) == said


def test_nothing_to_say_is_empty_not_none() -> None:
    for blank in (None, "", "   ", "\n\n"):
        assert clean(blank) == ""


def test_thought_tags_never_reach_the_screen() -> None:
    """속생각 조각이 화면에 그대로 나가면 사람이 놀란다 — 이 저장소가 겪은 사고."""
    assert clean("<thought>속으로 생각</thought>파일을 읽겠습니다") == "속으로 생각파일을 읽겠습니다"
    assert "<" not in clean("<tool_call>읽기</tool_call> 읽겠습니다")


@pytest.mark.parametrize("filler", ["네", "알겠습니다.", "OK", "잠시만요", "sure"])
def test_a_bare_acknowledgement_is_not_worth_showing(filler: str) -> None:
    """「네」만 흘리면 화면이 시끄럽고 진전처럼 보인다 — 예고는 진척이 아니다."""
    assert clean(filler) == ""


def test_a_long_speech_is_cut_and_says_so() -> None:
    """조용히 자르면 사람은 그게 전부인 줄 안다."""
    cut = clean("가" * (MAX_CHARS * 2))
    assert len(cut) <= MAX_CHARS
    assert cut.endswith("…")


def test_a_sentence_that_starts_with_a_filler_word_still_shows() -> None:
    """「네, 그럼 파일을 읽겠습니다」는 버리면 안 된다 — 뒤에 내용이 있다."""
    assert clean("네, 그럼 fees.py 를 읽겠습니다") != ""


# ── ② 모델별로 끌 수 있어야 한다 ────────────────────────────────────────────
def test_it_can_be_turned_off_per_model(tmp_path: Path) -> None:
    """★ 「먼저 알리고」 한 줄이 젬마의 도구 호출을 통째로 막은 적이 있다."""
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    config.agent_narration_blocked_models = ("plopfit-gemma4", "gemma4")

    assert enabled_for(config, "qwen3.6:35b-a3b") is True
    assert enabled_for(config, "gemma4:26b-a4b-it-qat") is False
    assert enabled_for(config, "plopfit-gemma4-qat:latest") is False


def test_it_can_be_turned_off_entirely(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    config.agent_narration_enabled = False
    assert enabled_for(config, "qwen3.6:35b-a3b") is False


def test_it_is_on_by_default_for_a_new_model(tmp_path: Path) -> None:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o")
    assert enabled_for(config, "some-new-model:8b") is True


# ── ③ 안내문이 도구를 막지 않는 모양인가 ────────────────────────────────────
def test_the_instruction_insists_on_tools_too() -> None:
    """★ 이 문장이 빠지면 모델이 말로 때우고 도구를 안 부른다 — 실측으로 확인한 모양."""
    assert "tool_calls" in NARRATION_INSTRUCTION
    assert "말만 하고" in NARRATION_INSTRUCTION


def test_the_instruction_forbids_claiming_undone_work() -> None:
    """실측에서 「찾아봤습니다」(안 했음)가 나왔다 — 안내문이 그걸 먼저 막는다."""
    assert "안 한 일을 했다고" in NARRATION_INSTRUCTION
