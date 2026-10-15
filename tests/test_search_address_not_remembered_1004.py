"""검색·목록 화면의 주소는 「같은 종류 페이지의 모양」으로 기억하지도 알려 주지도 않는다 (2026-10-04 실전 판 574826ac).

사람인에 `…/zf_user/search?searchType=search&loc_mcd={n}&…` 가 「본문이 제대로 읽혔던 주소 모양」으로 쌓여 있었다. `{n}` 은 지역 번호다 —
모델은 그 자리에 번호를 짐작해 넣어(41,42,44 · 85,86,51 · 47,55,46) 세 번 열고, 돌아온 엉뚱한 목록을 「0건」의 근거로 삼았다.
상세 주소의 번호는 목록에서 받을 수 있지만 검색 주소의 번호는 받을 곳이 없다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.site_traits import SiteTraits, is_search_address

SEARCH = "/zf_user/search?searchType=search&loc_mcd={n}&company_cd=0%2C1&keydownAccess="
ITEM = "/zf_user/jobs/view?rec_idx={n}"


@pytest.mark.parametrize("pattern", [
    SEARCH,
    "/search",
    "/search/cats-for-adoption/us/tx/{n}/?distance=35",
    "/results?q=Audiologist&sids={n}&d=40",
    "/serp?q=digital%20trends&searchId=01a0feb1-{n}",
])
def test_search_and_list_addresses_are_recognised(pattern: str) -> None:
    assert is_search_address(pattern) is True


@pytest.mark.parametrize("pattern", [
    ITEM,
    "/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn={n}",
    "/experiences/{n}",
    "/hub/pricing",
    "/research/papers/{n}",
])
def test_item_addresses_are_not_mistaken_for_search(pattern: str) -> None:
    assert is_search_address(pattern) is False


def test_a_search_address_is_not_recorded(tmp_path: Path) -> None:
    traits = SiteTraits(tmp_path / "site_traits.json")
    traits.record("https://www.saramin.co.kr/zf_user/search", "readable_url", SEARCH)
    traits.record("https://www.saramin.co.kr/zf_user/jobs/view", "readable_url", ITEM)

    note = traits.note_for("https://www.saramin.co.kr/")

    assert ITEM in note and "loc_mcd" not in note


def test_one_already_stored_is_not_shown(tmp_path: Path) -> None:
    """이미 쌓인 것은 지우지 않고(사람이 볼 수 있게) 알려 주지만 않는다 — 글 하나의 주소와 같은 규칙."""
    path = tmp_path / "site_traits.json"
    path.write_text(
        '{"saramin.co.kr": {"readable_url": {"count": 3, "details": ["' + SEARCH + '", "' + ITEM + '"], "last": 9999999999}}}',
        encoding="utf-8",
    )

    note = SiteTraits(path).note_for("https://www.saramin.co.kr/")

    assert ITEM in note and "loc_mcd" not in note
    assert "loc_mcd" in path.read_text(encoding="utf-8")
