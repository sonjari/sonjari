"""조사할 때 영상 결과는 뺀다 — 네이버 클립·숏츠까지 (2026-09-26 노트북 실측·사용자 요청)."""

from __future__ import annotations

import pytest

from alture_jarvis.browser import _is_video_url, _without_videos


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=x", "https://youtu.be/x", "https://m.youtube.com/shorts/x",
    "https://clip.naver.com/@kbsmedia_news?tab=all", "https://m.naver.com/shorts/?mediaType=VOD",
    "https://tv.naver.com/v/1", "https://www.instagram.com/reel/abc/", "https://www.facebook.com/watch/?v=1",
    "https://chzzk.naver.com/live/x", "https://www.tiktok.com/@a/video/1",
])
def test_video_results_are_recognised(url: str) -> None:
    assert _is_video_url(url), url


@pytest.mark.parametrize("url", [
    "https://blog.naver.com/abc/1", "https://m.naver.com/", "https://weather.naver.com/today/1",
    "https://www.instagram.com/p/abc/", "https://news.naver.com/article/1", "https://search.naver.com/search.naver?query=%EC%87%BC%EC%B8%A0",
])
def test_text_pages_are_kept(url: str) -> None:
    assert not _is_video_url(url), url


def test_ranks_are_renumbered_after_dropping_videos() -> None:
    rows = [{"rank": 1, "url": "https://clip.naver.com/@kbs"}, {"rank": 2, "url": "https://m.naver.com/shorts/?id=1"},
            {"rank": 3, "url": "https://weather.naver.com/today/1"}]
    kept = _without_videos(rows, "오늘 부산 날씨")
    assert [(row["rank"], row["url"]) for row in kept] == [(1, "https://weather.naver.com/today/1")]


def test_when_the_person_asks_for_video_they_stay() -> None:
    rows = [{"rank": 1, "url": "https://clip.naver.com/@kbs"}]
    assert _without_videos(rows, "부산 날씨 클립 영상 찾아줘") == rows
