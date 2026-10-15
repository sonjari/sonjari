"""「게시자」는 게시하라는 말이 아니다 (2026-09-18).

「MS 스토어에서 ChatGPT 앱의 게시자와 별점을 알려줘」가 발행 요구로 읽혀, 한 판은 네이버 블로그에 글을 넣으러 갔고
막고 나니 다음 판은 「발행 날짜」를 답했다. 30일 요청 564개로 재 보고 좁혔다(새로 놓침 = 이 문장 1개).
"""

from __future__ import annotations

import pytest

from alture_jarvis.plan import extract


def _actions(prompt: str) -> list[str]:
    return [r.target for r in extract(prompt) if r.kind == "action"]


@pytest.mark.parametrize("prompt", [
    "마이크로소프트 스토어(apps.microsoft.com)에서 ChatGPT 앱을 찾아서 게시자와 별점을 알려줘",
    "이 책의 발행일과 발행처를 알려줘",
    "커뮤니티 게시판에서 최근 게시글 3개 제목 알려줘",
    "게시물 수가 몇 개인지 세어줘",
])
def test_nouns_are_not_a_publish_request(prompt: str) -> None:
    assert "naver_blog_publish" not in _actions(prompt)


@pytest.mark.parametrize("prompt", [
    "이 글 네이버 블로그에 발행해줘",
    "블로그에 게시해 줘",
    "블로그에 포스팅해줘",
    "이거 블로그에 올려줘",
])
def test_real_publish_requests_still_count(prompt: str) -> None:
    assert "naver_blog_publish" in _actions(prompt)
