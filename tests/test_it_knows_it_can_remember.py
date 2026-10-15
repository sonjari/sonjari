"""「앞으로 기억해」에 「저장 기능이 없다」고 답했다 — 실제로는 저장했다 (2026-09-20 노트북 실측).

노트북 qwen3.5:4b 화면(원격 스크린샷): 「나는 이 온텔릭을 만든 박가람의 아버지 박정우이야 앞으로 기억해」 →
「온텔릭 시스템은 사용자 데이터를 장기적으로 저장하는 기능이 없어, 이 대화 내용은 세션 종료 후 사라집니다」 +
`clipboard_write`·`local_write_file` 같은 **내부 도구 이름**을 사용자에게 권했다.

같은 노트북의 사실 서랍(`/v1/memory/facts`)에는 그 말이 **이미 저장돼 있었다**(person · 박정우 · 인용까지).
모델이 자기에게 기억이 있다는 것을 몰랐을 뿐이다 — 할 수 있는 것을 모르면 할 수 없다고 지어낸다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig


def _runtime(tmp_path: Path, **overrides):
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        control_token="test-token", camera_enabled=False, vision_enabled=False, voice_enabled=False,
        tts_enabled=False, camera_control_enabled=False, google_enabled=False, naver_blog_enabled=False,
        **overrides,
    )
    return create_app(config, start_services=False).state.jarvis


def test_the_model_is_told_it_remembers_when_fact_learning_is_on(tmp_path: Path) -> None:
    prompt = _runtime(tmp_path)._system_prompt()
    assert "기억" in prompt and "저장하는 기능이 없다고 말하지" in prompt


def test_it_is_not_told_so_when_fact_learning_is_off(tmp_path: Path) -> None:
    """꺼 둔 PC 에서 「기억한다」고 하면 그게 거짓말이다."""
    prompt = _runtime(tmp_path, fact_learning_enabled=False)._system_prompt()
    assert "저장하는 기능이 없다고 말하지" not in prompt


def test_internal_tool_names_are_not_offered_to_people(tmp_path: Path) -> None:
    assert "내부 도구 이름" in _runtime(tmp_path)._system_prompt()


def test_an_answer_without_tools_does_not_claim_it_checked_tool_results() -> None:
    """같은 노트북 화면: 「고마워」에 도구를 0번 썼는데 「사용한 도구의 결과와 근거를 확인했습니다」가 찍혔다."""
    import inspect

    from alture_jarvis.agent import BrowserAgent

    source = inspect.getsource(BrowserAgent)
    assert 'else "사용한 도구의 결과와 근거를 확인했습니다" if steps' in source
    assert "도구 없이 바로 답했습니다" in source


# ── 지시문만으로는 4B 가 안 따랐다 (2026-09-20 노트북 241판) ──────────────────────────────────
#
# 시스템 프롬프트에 「기억한다 · 저장 기능이 없다고 말하지 않는다」를 넣은 판에서도 「너 내가 한 말 다음에도
# 기억할 수 있어?」 → 「기억해 드립니다 … 다만 온텔릭 시스템은 대화 기록을 장기적으로 저장하는 기능이 없어
# 세션이 종료되면 이 내용이 사라집니다」. 그래서 **내보내기 전에 코드가 본다** — 화면 칭찬의 카메라 답과 같은 자리.

DENIAL = ("기억해 드립니다. 다만, 온텔릭 시스템은 대화 기록을 장기적으로 저장하는 기능이 없어 "
          "세션이 종료되면 이 내용이 사라집니다.")


def _route_with(tmp_path: Path, prompt: str, answers: list[str], **overrides):
    runtime = _runtime(tmp_path, **overrides)
    calls: list[dict] = []

    def chat(text, **kwargs):
        calls.append(dict(kwargs))
        return {"content": answers[len(calls) - 1]}

    message, _ = runtime._routing_chat(chat, prompt, {"system": "S", "history": [], "tools": []})
    return message, calls


def test_a_denial_of_its_own_memory_is_asked_again(tmp_path: Path) -> None:
    message, calls = _route_with(tmp_path, "너 내가 한 말 다음에도 기억할 수 있어?", [DENIAL, "네, 기억해 두겠습니다."])
    assert len(calls) == 2 and message["content"] == "네, 기억해 두겠습니다."
    assert "기억" in calls[1]["system"] and "사실 서랍" in calls[1]["system"]


def test_an_honest_answer_is_left_alone(tmp_path: Path) -> None:
    message, calls = _route_with(tmp_path, "너 내가 한 말 다음에도 기억할 수 있어?", ["네, 다음 대화에서도 기억합니다."])
    assert len(calls) == 1


def test_with_fact_learning_off_the_denial_is_the_truth(tmp_path: Path) -> None:
    """꺼 둔 PC 에서는 「저장 안 한다」가 사실이다 — 고치면 그게 거짓말이다."""
    _message, calls = _route_with(tmp_path, "너 기억할 수 있어?", [DENIAL], fact_learning_enabled=False)
    assert len(calls) == 1


def test_a_design_compliment_is_not_met_with_an_excuse(tmp_path: Path) -> None:
    """241판: 「온텔릭 화면이 왜이얼게 이뻐보이지」 → 「직접 확인해 본 적은 없으므로 정확한 이유는 알 수 없습니다」."""
    excuse = "온텔릭의 화면을 직접 확인해 본 적은 없으므로 정확한 이유는 알 수 없습니다."
    message, calls = _route_with(tmp_path, "온텔릭 화면이 왜이얼게 이뻐보이지", [excuse, "그렇게 봐 주셔서 기뻐요!"])
    assert len(calls) == 2 and message["content"] == "그렇게 봐 주셔서 기뻐요!"


@pytest.mark.parametrize("excuse", [
    # 323판 노트북 실측 — 첫 패턴이 「못했으므로」「보지 않았」을 놓쳤다.
    "온텔릭의 디자인에 대한 감상은 직접 확인하지 못했으므로, 현재는 그 느낌을 공유하는 데 집중합니다.",
    "다만, 저는 실제 화면을 직접 보지 않았기 때문에 구체적인 디자인 요소를 설명하기는 어렵습니다.",
    "온텔릭의 디자인에 대한 직접적인 시각적 확인은 불가능하므로, 이는 모델의 추측일 뿐입니다.",
])
def test_every_excuse_seen_on_the_laptop_is_caught(excuse: str) -> None:
    from alture_jarvis.runtime import _DESIGN_EXCUSE

    assert _DESIGN_EXCUSE.search(excuse)


def test_a_plain_happy_answer_is_not_an_excuse() -> None:
    from alture_jarvis.runtime import _DESIGN_EXCUSE

    assert not _DESIGN_EXCUSE.search("그렇게 봐 주셔서 기뻐요! 어두운 바탕에 차분하게 맞추려고 신경 썼답니다.")


def test_two_excuses_in_a_row_still_answer_rather_than_fail(tmp_path: Path) -> None:
    """변명이 두 번 나와도 **작업을 오류로 끝내지 않는다** — 사람에게 빨간 오류가 변명보다 나쁘다."""
    excuse = "다만, 저는 실제 화면을 직접 보지 않았기 때문에 구체적으로 설명하기는 어렵습니다."
    message, calls = _route_with(tmp_path, "온텔릭 화면이 왜이얼게 이뻐보이지", [excuse, excuse])
    assert len(calls) == 2 and message["content"] == excuse
