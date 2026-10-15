"""시스템 프롬프트는 **안 바뀌는 것부터, 바뀌는 것은 맨 뒤로.**

프리필 캐시는 접두사로만 걸린다. 그래서 매 호출 달라지는 한 줄이 앞에 있으면
**그 뒤는 전부 딸려서 무효**가 된다. 현재 시각 줄이 두 번째에 있었고, 뒤따르는
프로필·라우팅 지침 2,100자를 매번 다시 씹고 있었다(2026-08-10 실측).

    시각 앞   중앙값 0.630초   [0.63, 0.38, 0.39, 0.63, 0.64, 0.64]
    시각 뒤   중앙값 0.396초   [0.39, 0.40, 0.39, 0.39, 0.40, 0.40]

빨라지는 것(0.23초)보다 흔들림이 없어지는 것이 더 값지다.

★ 이 시험이 지키는 것은 속도가 아니라 **순서**다. 속도는 여기서 못 잰다(모델이
필요하다). 순서가 지켜지면 속도는 따라오고, 순서가 깨지면 아무도 모르게 느려진다 —
그때 로그에 남는 것은 "요즘 좀 느리네"뿐이다.

시간을 제대로 읽는지는 따로 확인했다: 같은 질문 다섯 개를 옮기기 전/후로 던져
답을 대조했고 다섯 개 다 같았다(20:28 기준 시각·요일·오전오후·3시간 뒤·며칠째).
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import SYSTEM_PROMPT


def _runtime(tmp_path: Path):
    config = JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        control_token="test-token",
        camera_enabled=False,
        vision_enabled=False,
        voice_enabled=False,
        tts_enabled=False,
        camera_control_enabled=False,
        google_enabled=False,
        naver_blog_enabled=False,
    )
    return create_app(config, start_services=False).state.jarvis


def _time_line_index(prompt: str) -> int:
    index = prompt.find("현재 한국 시각")
    assert index >= 0, "시각 줄이 통째로 사라졌다 — 옮기려다 빠뜨린 것이다"
    return index


def test_the_clock_goes_last(tmp_path: Path) -> None:
    prompt = _runtime(tmp_path)._system_prompt("라우팅 지침입니다")

    assert prompt.startswith(SYSTEM_PROMPT), "안 바뀌는 것이 맨 앞이어야 캐시가 걸린다"
    assert _time_line_index(prompt) > prompt.find("라우팅 지침입니다"), (
        "시각이 지침보다 앞에 있으면 지침이 매 호출 다시 씹힌다"
    )


def test_the_clock_is_still_there_and_says_the_time(tmp_path: Path) -> None:
    """빠르게 만들려다 시계를 떼면 그건 고장이다."""
    prompt = _runtime(tmp_path)._system_prompt("지침")

    tail = prompt[_time_line_index(prompt) :]
    for field in ("날짜", "요일", "시각"):
        assert field in tail, f"시각 줄에 {field} 가 없다"


def test_instructions_keep_their_order(tmp_path: Path) -> None:
    """여러 지침을 넘길 때 순서가 뒤집히면 라우팅이 달라진다."""
    prompt = _runtime(tmp_path)._system_prompt("첫째 지침", "둘째 지침")

    assert prompt.find("첫째 지침") < prompt.find("둘째 지침") < _time_line_index(prompt)
