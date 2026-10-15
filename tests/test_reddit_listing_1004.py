"""레딧 글 목록을 읽으면 글마다 제목·댓글 수·추천 수·지난 시간·**진짜 글 주소**가 같이 온다 (2026-10-04).

같은 과제(「글 25개의 제목·댓글 수·추천 수를 엑셀로」)가 세 번 중 한 번만 깔끔히 됐다. 숫자가 화면 추출에 안 잡혀
모델이 판마다 다른 길을 찾았고, 목록을 글자로만 읽은 모델은 주소를 몰라 글 번호를 지어냈다.
글 한 편에는 이미 해 주던 일을 목록에도 한다.
"""
from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis.browser import BrowserWorker, reddit_listing_items, reddit_listing_json_url


def _payload(count: int = 3) -> dict[str, Any]:
    return {"kind": "Listing", "data": {"children": [
        {"kind": "t3", "data": {
            "title": f"글 제목 {index}", "num_comments": 10 + index, "score": 30 + index, "upvote_ratio": 0.9,
            "created_utc": 1_000_000 - 3600 * (index + 1), "subreddit_name_prefixed": "r/LocalLLM",
            "permalink": f"/r/LocalLLM/comments/1abc{index}z/post_title_{index}/", "stickied": index == 0,
        }} for index in range(count)
    ] + [{"kind": "t5", "data": {"title": "게시판 소개"}}]}}


# --- 어떤 주소가 목록인가 -------------------------------------------------------

@pytest.mark.parametrize("url, expected", [
    ("https://www.reddit.com/r/LocalLLM/", "https://www.reddit.com/r/LocalLLM.json"),
    ("https://www.reddit.com/r/LocalLLM/hot/", "https://www.reddit.com/r/LocalLLM/hot.json"),
    ("https://old.reddit.com/r/LocalLLM/new/.json?limit=25", "https://www.reddit.com/r/LocalLLM/new.json?limit=25"),
    ("https://www.reddit.com/r/LocalLLaMA/search/?q=parallel+slots&restrict_sr=1",
     "https://www.reddit.com/r/LocalLLaMA/search.json?q=parallel+slots&restrict_sr=1"),
    ("https://www.reddit.com/search/?q=local+agent", "https://www.reddit.com/search.json?q=local+agent"),
])
def test_boards_sorts_and_searches_are_listings(url: str, expected: str) -> None:
    assert reddit_listing_json_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://www.reddit.com/r/LocalLLaMA/comments/1abcd9z/a_post_title/",  # 글 한 편 — 다른 장치의 일
    "https://www.reddit.com/",                                             # 사람마다 다른 첫 화면
    "https://www.reddit.com/r/LocalLLM/wiki/index",
    "https://www.reddit.com/user/someone/",
    "https://www.reddit.com/search/",                                      # 검색어 없는 검색
    "https://example.com/r/LocalLLM/",
    "",
])
def test_everything_else_is_left_alone(url: str) -> None:
    assert reddit_listing_json_url(url) == ""


# --- 해석 ---------------------------------------------------------------------

def test_each_post_carries_its_counts_age_and_real_address() -> None:
    items = reddit_listing_items(_payload(), now=1_000_000)

    assert len(items) == 3  # 글이 아닌 줄(t5)은 뺀다
    first = items[0]
    assert first["title"] == "글 제목 0" and first["num_comments"] == 10 and first["score"] == 30
    assert first["url"] == "https://www.reddit.com/r/LocalLLM/comments/1abc0z/post_title_0/"
    assert first["age"] == "1시간 전" and first["pinned"] is True
    assert items[2]["age"] == "3시간 전" and "pinned" not in items[2]


def test_a_strange_shape_gives_nothing_rather_than_guesses() -> None:
    for payload in (None, {}, {"data": {}}, [1, 2], {"data": {"children": [{"kind": "t3", "data": {"title": "주소 없는 글"}}]}}):
        assert reddit_listing_items(payload) == []


# --- 읽기 결과에 붙이기 ---------------------------------------------------------

class _Response:
    def __init__(self, payload: Any, ok: bool = True) -> None:
        self._payload, self.ok = payload, ok

    def json(self) -> Any:
        return self._payload


class _Page:
    def __init__(self, url: str, payload: Any, ok: bool = True) -> None:
        self.url = url
        self.asked: list[str] = []
        outer = self

        class _Request:
            @staticmethod
            def get(address: str, **_kwargs: Any) -> _Response:
                outer.asked.append(address)
                return _Response(payload, ok)

        class _Context:
            request = _Request()

        self.context = _Context()


def test_reading_a_board_puts_the_listing_on_top() -> None:
    page = _Page("https://www.reddit.com/r/LocalLLM/hot/", _payload())
    result = {"url": page.url, "text": "화면에서 읽힌 글자"}

    out = BrowserWorker._attach_listing(object(), page, result)  # type: ignore[arg-type]

    assert page.asked == ["https://www.reddit.com/r/LocalLLM/hot.json"]
    assert out["text"].startswith("[레딧 글 목록 3개]")
    assert "「글 제목 1」 · 댓글 11 · 추천 31" in out["text"]
    assert "https://www.reddit.com/r/LocalLLM/comments/1abc1z/post_title_1/" in out["text"]
    assert "글 번호를 짐작해 주소를 만들지 마라" in out["text"]
    assert out["text"].endswith("화면에서 읽힌 글자")
    assert len(out["listing"]) == 3
    assert result["text"] == "화면에서 읽힌 글자"  # 받은 결과는 건드리지 않는다


def test_nothing_is_attached_when_it_is_not_a_listing_or_the_fetch_fails() -> None:
    post = _Page("https://www.reddit.com/r/LocalLLM/comments/1abc0z/post_title_0/", _payload())
    plain = {"url": post.url, "text": "본문"}
    assert BrowserWorker._attach_listing(object(), post, plain) is plain and post.asked == []  # type: ignore[arg-type]

    blocked = _Page("https://www.reddit.com/r/LocalLLM/", _payload(), ok=False)
    untouched = {"url": blocked.url, "text": "본문"}
    assert BrowserWorker._attach_listing(object(), blocked, untouched) is untouched  # type: ignore[arg-type]


def test_both_read_paths_attach_it() -> None:
    import inspect

    assert "self._attach_listing(page, self._attach_post_stats(" in inspect.getsource(BrowserWorker._extract_with_data)
    assert "self._attach_listing(page, self._attach_post_stats(" in inspect.getsource(BrowserWorker._read_with_data)


# --- 막힌 통로 -----------------------------------------------------------------

def test_a_blocked_outside_function_fails_loudly_and_names_a_way_that_works() -> None:
    from alture_jarvis.plopfit import _raise_if_blocked

    blocked = {"text": '{\n  "ok": false,\n  "error": "reddit_blocked",\n  "message": "Reddit 접근 차단(403)."\n}', "language": "json"}
    with pytest.raises(RuntimeError) as caught:
        _raise_if_blocked("reddit_hot", {"subreddit": "LocalLLM"}, blocked)
    assert "reddit_blocked" in str(caught.value)
    assert "https://www.reddit.com/r/LocalLLM/hot/" in str(caught.value) and "browser_extract" in str(caught.value)
    assert "tavily" not in str(caught.value)  # 이 PC 에 없는 도구를 권하지 않는다

    fine = {"text": '{"ok": true, "posts": []}', "language": "json"}
    assert _raise_if_blocked("reddit_hot", {}, fine) is fine
    assert _raise_if_blocked("github_search", {}, {"text": "그냥 글"}) == {"text": "그냥 글"}
