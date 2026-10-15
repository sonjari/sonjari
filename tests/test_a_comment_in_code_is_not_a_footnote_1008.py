"""코드 이야기의 「주석」은 각주가 아니다 (2026-10-08).

우리 숙제 하나를 손자리에게 맡긴 판에서 나왔다. 「표에 여섯을 넣어라. 왜 넣는지 다른 항목들처럼 짧은 주석을 달아라」에
「각주 3개 이상 달기 — 워드는 각주가 안 되니 한글(hwpx)로」가 섰다. 손자리는 시킨 것을 다 하고 시험까지 통과시켰는데
판은 「❌ 각주 없음」·덜 끝남으로 찍혔다.

「각주」는 한 뜻이지만 「주석」은 두 뜻이다. 「각주」라는 말이 없고 코드 대상(파일 이름 · 함수 · 코드 …)이 같이 있으면 코드 주석이다.
운영 요청 1,802개에 옛·새 판정을 대 보니 각주 요구가 사라진 것은 그 과제 글 둘뿐이었다.
"""
from __future__ import annotations

import pytest

from alture_jarvis import plan


def _kinds(prompt: str) -> set[str]:
    return {requirement.kind for requirement in plan.extract(prompt)}


@pytest.mark.parametrize("prompt", [
    "settings.py 의 표에 항목 둘을 넣고 시험 파일을 만들어라. 왜 넣는지 다른 항목들처럼 짧은 주석을 달아라.",
    "settings.py 에 항목 둘을 추가하는 코드를 작성해줘. 짧은 주석을 달아서.",
    "이 함수에 주석을 달고 이름을 고쳐줘.",
    "app.py 를 만들어줘. 줄마다 주석을 달아서.",
])
def test_a_comment_asked_for_in_code_is_not_a_footnote(prompt: str) -> None:
    assert "footnote" not in _kinds(prompt)


@pytest.mark.parametrize("prompt", [
    "이 이력서를 한글 문서로 만들어줘. 문단마다 주석을 달아서.",
    "보고서를 문서로 만들어줘. 각주를 달아서.",
    # 「각주」라고 했으면 코드 낱말이 같이 있어도 각주다.
    "report.py 가 만든 수치를 한글 문서로 정리해줘. 각주를 달아서.",
])
def test_a_note_asked_for_in_a_document_is_still_a_footnote(prompt: str) -> None:
    assert "footnote" in _kinds(prompt)
