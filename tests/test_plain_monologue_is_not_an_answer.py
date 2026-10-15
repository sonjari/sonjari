"""반말 혼잣말로 끝난 답은 답이 아니다 (2026-10-01 운영 MCP 판 d60f38d3).

Steam 설문을 세 장 읽고 최종 답이 「…browser_extract로 본문만 추출해 본다.」였는데 complete 로 바깥 AI 에게 갔다.
넣기 전에 재 봤다: 운영 기록의 서로 다른 답 2,378개 중 새 판정에 걸린 것은 이 답 하나뿐(멀쩡한 답 0개).
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import _only_a_promise

SEEN = "VRAM 상세 비율이 페이지 본문에 안 보인다. Steam은 동적 테이블을 쓰는데, browser_extract로 본문만 추출해 본다."


@pytest.mark.parametrize("text", [
    SEEN,
    "목록이 짧다. 다음 페이지를 열어 보자.",
    "본문이 잘렸다. browser_scroll 로 아래를 본다.",
])
def test_plain_monologue_is_caught(text: str) -> None:
    assert _only_a_promise(text)


@pytest.mark.parametrize("text", [
    "전문가들은 내년 시장을 성장세로 본다.",
    "Steam 설문 기준 8GB 가 가장 많다.",
    "찾은 세 곳의 가격을 표로 정리했습니다.",
])
def test_real_short_answers_are_not_caught(text: str) -> None:
    assert not _only_a_promise(text)
