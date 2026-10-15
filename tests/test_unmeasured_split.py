"""「대조할 요구를 못 뽑음」이 두 가지를 뜻하고 있었다.

## 무엇이 문제였나

`extract` 가 빈 목록을 주면 `completion_state` 가 `answered` 가 된다. 그런데 그
한 칸에 완전히 다른 둘이 들어 있었다:

    "지금 몇 시야"             → 대조할 요구가 **원래 없다.** 정상이다
    "그래서 공고를 좀 찾아줘"   → 일을 시켰는데 **못 뽑았다.** 눈금의 구멍이다

빈 값 하나가 두 사실을 뜻하면 조용히 고장난다. 그리고 이 경우는 더 나빴다 —
`measure_autonomy._goal_reached` 가 `answered` 를 **성공으로** 셌다. 못 잰 판이
L4 분자에 들어가 있었다는 뜻이다(2026-08-21 실측: 위임 54판 중 17판 = 31.5%).

같은 파일이 바로 위에서 "모르는 것을 성공으로도 실패로도 세지 않고 분모에서
뺀다"고 적고 있었다. **그 원칙이 이 칸에만 안 지켜지고 있었다.**
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from alture_jarvis.agent import _completion_state
from alture_jarvis.plan import asked_for_work


def _measure():
    spec = importlib.util.spec_from_file_location(
        "_ma_split", Path(__file__).resolve().parents[1] / "scripts" / "measure_autonomy.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "prompt",
    [
        "그래서 공고를 좀 찾아줘. 이제 시작하자.",
        "아니면 사업비관리 이런걸로 직무를 키워드로 검색해줘",
        "이 내용 정리해줘",
        "경쟁사 좀 비교해줘",
        "요약해줘",
    ],
)
def test_a_task_with_no_requirements_is_unmeasured(prompt: str) -> None:
    """일을 시켰는데 요구가 0개면 **못 쟀다**고 적는다."""
    assert asked_for_work(prompt) is True
    assert _completion_state("model_answered", [], prompt) == "unmeasured"


@pytest.mark.parametrize(
    "prompt",
    [
        "지금 몇 시야",
        "우리 수강료가 얼마였지",
        "전환율이 뭐야",
        "고마워",
        "그렇구나",
    ],
)
def test_plain_talk_stays_answered(prompt: str) -> None:
    """묻기만 한 것은 원래 대조할 게 없다 — 이건 고장이 아니다."""
    assert asked_for_work(prompt) is False
    assert _completion_state("model_answered", [], prompt) == "answered"


def test_unmeasured_is_neither_success_nor_failure() -> None:
    """★ 이 파일에서 가장 중요한 검사.

    못 잰 것을 성공으로 세면 성적표가 실제보다 좋아지고, 실패로 세면 실제보다
    나빠진다. **분모에서 뺀다.**
    """
    ma = _measure()

    assert ma._goal_reached({"completion_state": "unmeasured"}) is None
    assert ma._goal_reached({"completion_state": "answered"}) is True
    assert ma._goal_reached({"completion_state": "complete"}) is True
    assert ma._goal_reached({"completion_state": "partial"}) is False


def test_the_two_have_different_names_in_the_table() -> None:
    """표에서도 갈려야 어디가 새는지 보인다."""
    ma = _measure()

    assert "model_answered" in ma._OUTCOME_LABELS
    assert "model_answered:unmeasured" in ma._OUTCOME_LABELS
    assert ma._OUTCOME_LABELS["model_answered"] != ma._OUTCOME_LABELS["model_answered:unmeasured"]


def test_requirements_still_win_over_the_prompt() -> None:
    """요구를 뽑았으면 그것으로 판정한다 — 문장은 그때 안 본다."""
    done = [(object(), True, "3개 읽음")]
    short = [(object(), False, "2개 읽음")]

    assert _completion_state("model_answered", done, "찾아줘") == "complete"
    assert _completion_state("model_answered", short, "찾아줘") == "partial"


def test_old_rows_without_a_prompt_do_not_crash() -> None:
    """프롬프트를 안 넘기던 옛 호출도 그대로 돈다(기본값 빈 문자열)."""
    assert _completion_state("model_answered", []) == "answered"
