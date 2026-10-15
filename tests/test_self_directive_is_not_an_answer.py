"""「~하기 위해 ~한다」는 자기에게 거는 지시다 — 답이 아니다.

★ 2026-09-28 MCP 위임 판 78671832. 여덟 곳을 읽고 최종 답이 같은 속말 두 줄이었다. 예고 그물(`_only_a_promise`)은
「하겠습니다」 꼴만 봐서 통과시켰고, 사람(과 맡긴 클로드)에게는 할 일 메모가 답으로 갔다.
"""

from __future__ import annotations

from alture_jarvis.agent import _only_a_promise

LIVE = (
    "llama.cpp 저장소에서 --override-tensor 옵션을 찾기 위해 GitHub 코드 검색을 올바르게 사용한다.\n\n"
    "llama.cpp 저장소 내에서 --override-tensor 옵션을 찾기 위해 GitHub 코드 검색을 올바르게 사용한다."
)


def test_the_live_self_directive_is_caught() -> None:
    assert _only_a_promise(LIVE)


def test_a_single_self_directive_line_is_caught() -> None:
    assert _only_a_promise("가격을 확인하기 위해 상세 페이지를 연다.")


def test_a_plain_answer_about_the_topic_is_not_caught() -> None:
    """답 내용이 반말 평서형이어도 **일하는 과정**을 목적으로 대지 않으면 답이다."""
    assert not _only_a_promise("--override-tensor 로 전문가 층을 CPU 에 두면 VRAM 이 모자란 PC 에서도 모델이 돈다.")


def test_a_polite_explanation_with_purpose_is_not_caught() -> None:
    assert not _only_a_promise("정확한 값을 확인하기 위해 공식 문서를 읽었습니다. 기본값은 32K 입니다.")


def test_mixed_answer_is_not_caught() -> None:
    """한 문장이라도 사람에게 하는 존댓말이 섞이면 속말만 있는 답이 아니다."""
    assert not _only_a_promise("옵션을 찾기 위해 README 를 읽는다. 결과는 아래 표와 같습니다.")
