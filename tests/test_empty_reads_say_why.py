"""빈손으로 끝났으면 **왜** 빈손인지 말한다.

빈 결과는 전혀 다른 세 사정을 하나로 뭉갠다:

    정말 없음        이 페이지엔 그런 게 없다     -> 다른 데를 봐야 한다
    아직 안 그려짐   스크립트가 그리는 중이다     -> 기다렸다 다시 보면 된다
    차단·오류 화면   봇 검사가 떠 있다            -> 사람이 손대야 한다

구별이 없으면 모델은 늘 첫째로 읽고 엉뚱한 데로 간다. 실제로 두 번 그랬다:

  · 빙 0건(2026-08-08) — 봇 검사 화면이 "이 질의는 결과가 없다"로 둔갑
  · 요소 0개(2026-08-05, 8개 사이트) — `_snapshot` 은 자기 docstring 에
    "요소 0개는 망가진 페이지로 읽힌다"고 적어 놓고도 정작 0을 돌려줄 때
    아무 말을 안 했다

`_search` 는 2026-08-08 에 고쳤고 `_extract` 는 원래 됐다. 나머지 셋을 여기서 잠근다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from test_search_bot_check_late import _CHALLENGE, _Page, _worker


class _Blank(_Page):
    """아직 아무것도 안 그려진 화면 — 뼈대만 내려온 상태."""

    def body_text(self) -> str:
        return ""

    def elements(self) -> list[Any]:
        return []


class _Challenge(_Page):
    """봇 검사 화면. 누를 것은 있지만 우리가 찾는 것은 없다."""

    def body_text(self) -> str:
        return _CHALLENGE


class _Plain(_Page):
    """멀쩡히 그려진 페이지 — 다만 찾는 것이 없을 뿐."""

    def body_text(self) -> str:
        return "평범한 글이 있는 페이지"


def _links_of(page: _Page, tmp_path: Path) -> dict[str, Any]:
    return _worker(tmp_path)._links(page, {})


# ---- browser_snapshot ------------------------------------------------------

def test_snapshot_zero_on_a_blank_page_says_not_drawn(tmp_path: Path) -> None:
    found = _worker(tmp_path)._snapshot(_Blank(challenge_after=99), {})

    assert found["element_count"] == 0
    assert found["empty_reason"] == "not_drawn"
    assert "browser_wait" in found["instruction"], "기다리라고 말해 주지 않으면 '없다'로 읽는다"


def test_snapshot_zero_on_a_challenge_says_blocked(tmp_path: Path) -> None:
    page = _Challenge(challenge_after=0)
    page.goto("https://www.bing.com/search?q=x")
    worker = _worker(tmp_path)
    # 검사 화면은 요소가 있으므로 snapshot 이 0이 되게 만드는 건 링크 쪽이다.
    found = worker._links(page, {})

    assert found["link_count"] == 0
    assert found["empty_reason"] == "blocked"
    assert "막힌" in found["instruction"]


# ---- browser_links ---------------------------------------------------------

def test_links_zero_on_a_blank_page_says_not_drawn(tmp_path: Path) -> None:
    found = _links_of(_Blank(challenge_after=99), tmp_path)

    assert found["link_count"] == 0
    assert found["empty_reason"] == "not_drawn"


def test_links_zero_on_a_drawn_page_says_absent(tmp_path: Path) -> None:
    """그려져 있는데 링크가 없으면 그건 진짜 '없다'다 — 기다리라고 하면 안 된다."""
    page = _Plain(challenge_after=99)
    page.goto("https://search.naver.com/search.naver?query=x")

    found = _links_of(page, tmp_path)

    assert found["link_count"] == 0
    assert found["empty_reason"] == "absent"
    assert found["page_elements"] > 0
    assert "browser_wait" not in found["instruction"], (
        "그려진 화면에서 기다리라고 하면 모델이 헛되이 폴링한다"
    )


# ---- browser_find ----------------------------------------------------------

def test_find_keeps_its_own_advice_when_the_thing_is_truly_absent(tmp_path: Path) -> None:
    """'없는 셀렉터를 지어내지 마라'는 find 만의 조언이라 덮어쓰면 안 된다."""
    page = _Plain(challenge_after=99)
    page.goto("https://search.naver.com/search.naver?query=x")

    found = _worker(tmp_path)._find(page, {"query": "존재하지않는버튼"})

    assert found["match_count"] == 0
    assert found["empty_reason"] == "absent"
    assert "지어내지 마라" in found["instruction"]


def test_find_on_a_blank_page_says_not_drawn_instead(tmp_path: Path) -> None:
    """훑은 것이 0개면 '이 이름으로는 없다'조차 아니다."""
    found = _worker(tmp_path)._find(_Blank(challenge_after=99), {"query": "저장"})

    assert found["scanned"] == 0
    assert found["empty_reason"] == "not_drawn"
    assert "지어내지 마라" not in found["instruction"], (
        "안 그려진 화면에 '다른 낱말로 찾아라'라고 하면 있는 버튼을 못 찾고 포기한다"
    )


def test_a_hit_is_not_given_an_empty_reason(tmp_path: Path) -> None:
    # 찾았는데 왜 비었는지 설명이 붙으면 그게 더 헷갈린다.
    page = _Plain(challenge_after=99)
    page.goto("https://search.naver.com/search.naver?query=x")

    found = _worker(tmp_path)._find(page, {"query": "블로그 글"})

    assert found["match_count"] > 0
    assert "empty_reason" not in found
