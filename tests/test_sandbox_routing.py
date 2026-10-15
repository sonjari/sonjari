""""만들어줘"가 상자에 닿는가.

## 왜 이 파일이 생겼는가

2026-08-21, 상자를 켜고 처음 시킨 일이 이것이었다:

    "학생 5명 이름이랑 점수로 엑셀 성적표 파일 하나 만들어줘"

자비스는 **"[파일 생성 완료]"** 라고 답했다. 표까지 예쁘게 그려서.
그런데 `sandbox_run` 호출은 **0 건**이었고 `outputs/sandbox` 폴더는 아예 없었다.

라우터의 갈래가 다섯(browser·google·local·scheduler·camera)뿐이라 이 말이 갈 곳이
없었고, 평범한 답변 경로가 받아서 지어낸 것이다.

**도구를 만드는 것과 그 도구에 닿는 길을 내는 것은 다른 일이다**(사고 Q).
상자는 완성돼 있었고 검사도 통과했는데, 아무도 그리로 갈 수 없었다.

## 그리고 도구가 없으면 갈래도 안 연다

갈래만 만들고 물건을 안 주면 에이전트가 빈손으로 받아 똑같이 지어낸다.
`_requires_inhouse_data` 가 "도구가 실제로 있을 때만 연다"고 한 그 규칙이다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import JarvisRuntime


class _Runtime:
    """판정만 떼어 쓴다. 전체 런타임은 하드웨어가 있어야 뜬다."""

    _requires_sandbox = JarvisRuntime._requires_sandbox
    _requires_artifact = JarvisRuntime._requires_artifact
    _requires_coding = JarvisRuntime._requires_coding

    def __init__(self, *, enabled: bool = True, has_box: bool = True) -> None:
        self.config = JarvisConfig()
        self.config.sandbox_enabled = enabled
        self.sandbox = object() if has_box else None
        self.local_computer = type(
            "LocalWriter", (), {"names": {"local_write_file", "local_apply_edit"}}
        )()


@pytest.mark.parametrize(
    "prompt",
    [
        "학생 5명 이름이랑 점수로 엑셀 성적표 파일 하나 만들어줘",
        "이 점수들로 xlsx 만들어줘",
        "반별 평균 계산해줘 표로 정리해줘",
        "성적 분포 그래프 만들어줘",
        "이 내용으로 워드 파일 만들어줘",
        "csv 로 뽑아줘",
    ],
)
def test_build_requests_reach_the_box(prompt: str) -> None:
    assert _Runtime()._requires_sandbox(prompt) is True, prompt


@pytest.mark.parametrize(
    "prompt",
    [
        # 만들라는 게 아니다.
        "엑셀 파일 어디 있어",
        "그 표 내용 알려줘",
        # 만들 물건이 상자의 것이 아니다.
        "시간표 만들어줘",
        "다음주 일정 만들어줘",
        "블로그 글 만들어줘",
        # 아예 다른 갈래
        "지금 몇 시야",
        "카메라 정면으로 돌려줘",
    ],
)
def test_other_talk_does_not_reach_the_box(prompt: str) -> None:
    """오탐이 정탐보다 비싸다 — 잡담이 상자로 가면 답이 이상해진다."""
    assert _Runtime()._requires_sandbox(prompt) is False, prompt


def test_closed_box_closes_the_branch() -> None:
    """★ 갈래만 만들고 물건을 안 주면 에이전트가 빈손으로 지어낸다.

    오늘 실제로 그렇게 됐다 — 이 규칙이 그 재발을 막는다.
    """
    prompt = "엑셀 성적표 파일 하나 만들어줘"

    assert _Runtime(enabled=True, has_box=True)._requires_sandbox(prompt) is True
    assert _Runtime(enabled=False, has_box=True)._requires_sandbox(prompt) is False
    assert _Runtime(enabled=True, has_box=False)._requires_sandbox(prompt) is False


@pytest.mark.parametrize(
    "prompt",
    [
        "회의 결과를 보고서 파일로 작성해줘",
        "학생 점수 엑셀로 만들어줘",
        "이 함수 코드를 짜줘",
        "조사한 내용을 표로 정리해서 줘",
        "초안 문서 저장해줘",
    ],
)
def test_artifact_requests_reach_the_file_writer(prompt: str) -> None:
    assert _Runtime()._requires_artifact(prompt) is True, prompt


@pytest.mark.parametrize(
    "prompt",
    [
        "보고서 작성법을 조사해줘",
        "시간표 만들어줘",
        "그래프 코드가 뭐야",
        "문서 어디에 있어",
        "일정 하나 만들어줘",
    ],
)
def test_artifact_words_without_a_target_and_imperative_do_not_open_the_branch(prompt: str) -> None:
    assert _Runtime()._requires_artifact(prompt) is False, prompt


def test_artifact_route_is_before_research_route() -> None:
    import inspect

    source = inspect.getsource(JarvisRuntime._general_route)
    assert source.index("self._requires_artifact(prompt)") < source.index(
        "self._requires_web_research(prompt)"
    )


@pytest.mark.parametrize(
    "prompt",
    [
        "이 함수 코드를 짜줘",
        "파이썬 스크립트를 만들어 실제로 실행해줘",
        "타입스크립트 코드를 고쳐줘",
    ],
)
def test_executable_code_requests_choose_the_coding_role(prompt: str) -> None:
    assert _Runtime()._requires_coding(prompt) is True


def test_code_explanations_do_not_choose_the_coding_role() -> None:
    assert _Runtime()._requires_coding("이 파이썬 코드가 무슨 뜻이야") is False
