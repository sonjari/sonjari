"""「일정」이 든 조사 요청을 일정 등록으로 읽지 않는다 (2026-10-02 대표 운영 판 · 공개 전 필수 ①).

「…베타 시작일과 본 서비스 일정·지금 할 수 있는 기능(…)을 정리한 문서(.md)로 만들어줘」에서 계획 층이 `일정.*만들` 로
「일정 등록」 요구를 만들었고, 손자리가 시키지 않은 예약 작업 만들기를 준비했다. 진짜 일정 요청은 그대로 잡아야 한다.
"""

from __future__ import annotations

import pytest

from alture_jarvis.plan import extract

MISREAD = (
    "정부의 '모두의 AI'(카카오·SK텔레콤·KT가 만드는 전 국민 무료 AI 서비스) 베타를 지금 일반인이 써 볼 수 있는지 찾아서, "
    "서비스 이름·운영사별 앱/웹 주소·이용 대상·신청 또는 설치 방법·베타 시작일과 본 서비스 일정·지금 할 수 있는 기능"
    "(특히 웹을 대신 찾아보거나 예약 같은 일을 해 주는 에이전트 기능)을 정리한 문서(.md)로 만들어줘."
)


def _labels(prompt: str) -> list[str]:
    return [r.label for r in extract(prompt)]


def test_a_document_about_a_schedule_is_not_a_calendar_event() -> None:
    labels = _labels(MISREAD)
    assert "일정 등록" not in labels
    assert "실제 산출물 파일 만들기" in labels


@pytest.mark.parametrize("prompt", [
    "일정을 30분짜리로 만들어줘", "내일 3시에 치과 일정 등록해줘", "다음 주 회의 일정 잡아줘", "캘린더에 일정 추가해줘",
])
def test_real_calendar_asks_still_count(prompt: str) -> None:
    assert "일정 등록" in _labels(prompt)
