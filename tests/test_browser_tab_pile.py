"""탭이 쌓이는 것 — 상한은 있었는데 **세는 목록이 비어 있었다** (2026-09-16, 사용자 두 번째 지적).

`browser_max_tabs` 를 6 으로 두고 동작이 끝날 때마다 정리를 불렀는데도 탭이 18장이 됐다.
정리가 `_our_pages` 에 적힌 탭만 닫기 때문이다 — 사이트가 스스로 띄운 탭(`target="_blank"`
링크, 상세 팝업)은 아무도 안 적었다. 상한이 아니라 **분모**가 문제였다(사고 S 와 같은 가족).
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.config import JarvisConfig


class _FakePage:
    def __init__(self, url: str) -> None:
        self.url = url
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class _FakeContext:
    def __init__(self, pages: list[_FakePage]) -> None:
        self._pages = pages

    @property
    def pages(self) -> list[_FakePage]:
        return [page for page in self._pages if not page.closed]


def _worker(tmp_path: Path, **values) -> BrowserWorker:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", **values)
    return BrowserWorker(config)


def test_tabs_the_site_opened_during_our_action_are_ours(tmp_path: Path) -> None:
    """★ 이게 고친 것이다 — 우리 동작 중에 생긴 탭은 우리가 띄운 것으로 센다."""
    worker = _worker(tmp_path)
    opened = _FakePage("https://example.com/popup")

    worker._action_depth = 0
    worker._claim_if_we_caused_it(opened)
    assert worker._our_pages == [], "우리가 쉬는 동안 생긴 탭은 사람의 것이다"

    worker._action_depth = 1
    worker._claim_if_we_caused_it(opened)
    assert worker._our_pages == [id(opened)]


def test_the_cap_actually_closes_site_opened_tabs(tmp_path: Path) -> None:
    """상한 6, 탭 10장(전부 우리 동작 중에 생긴 것) → 6장으로 줄어든다."""
    worker = _worker(tmp_path, browser_max_tabs=6)
    pages = [_FakePage(f"https://example.com/{index}") for index in range(10)]
    worker._context = _FakeContext(pages)  # type: ignore[assignment]
    worker._page = pages[-1]
    worker._action_depth = 1
    for page in pages:
        worker._claim_if_we_caused_it(page)

    closed = worker._prune_tabs()

    assert closed == 4
    assert len(worker._context.pages) == 6
    assert not pages[-1].closed, "지금 보는 탭은 남긴다"
    assert [page.url for page in worker._context.pages][0] == "https://example.com/4", "오래된 것부터 닫는다"


def test_a_tab_the_person_opened_is_left_alone(tmp_path: Path) -> None:
    """**붙어 쓰는 크롬**에서는 사람의 탭을 상한을 넘겨서라도 남긴다."""
    worker = _worker(tmp_path, browser_max_tabs=2)
    worker._connect_mode = "attached"
    mine = [_FakePage(f"https://example.com/{index}") for index in range(4)]
    theirs = _FakePage("https://nid.naver.com/login")
    worker._context = _FakeContext([theirs, *mine])  # type: ignore[assignment]
    worker._page = mine[-1]
    worker._action_depth = 1
    for page in mine:
        worker._claim_if_we_caused_it(page)

    worker._prune_tabs()

    assert not theirs.closed
    assert theirs in worker._context.pages


def test_the_cap_of_zero_turns_tidying_off(tmp_path: Path) -> None:
    worker = _worker(tmp_path, browser_max_tabs=0)
    pages = [_FakePage(f"https://example.com/{index}") for index in range(9)]
    worker._context = _FakeContext(pages)  # type: ignore[assignment]
    worker._page = pages[0]
    worker._action_depth = 1
    for page in pages:
        worker._claim_if_we_caused_it(page)

    assert worker._prune_tabs() == 0
    assert len(worker._context.pages) == 9


def test_an_unclaimed_tab_is_immune_in_attached_mode(tmp_path: Path) -> None:
    """★ 이것이 고장의 모양이었다 — 목록에 없는 탭은 상한이 몇이든 안 닫혔다.

    **우리가 띄운 크롬에서는 이제 사실이 아니다**(아래 시험이 그것을 잡는다). 사람의 크롬에
    붙어 쓸 때만 남는 규칙이고, 거기서는 그것이 맞다 — 남의 창을 세어서 닫을 수는 없다.
    """
    worker = _worker(tmp_path, browser_max_tabs=1)
    worker._connect_mode = "attached"
    pages = [_FakePage(f"https://example.com/{index}") for index in range(12)]
    worker._context = _FakeContext(pages)  # type: ignore[assignment]
    worker._page = pages[0]
    # 아무것도 적지 않는다 — 사이트가 스스로 띄운 탭이 예전에 이 상태였다.
    assert worker._our_pages == []

    assert worker._prune_tabs() == 0
    assert len(worker._context.pages) == 12


def test_tabs_that_appeared_during_the_action_are_pruned(tmp_path: Path) -> None:
    """★ 실측이 고른 규칙 — `context.on("page")` 는 늦게 펌프돼 24장 중 2장만 잡았다.

    그래서 이벤트가 아니라 **동작 시작 때 찍은 목록**과의 차이로 가른다.
    """
    worker = _worker(tmp_path, browser_max_tabs=6)
    worker._connect_mode = "spawned"
    start = [_FakePage("https://saramin.co.kr/list")]
    worker._context = _FakeContext(start)  # type: ignore[assignment]
    worker._pages_before_action = worker._page_ids()
    # 사이트가 상세 팝업을 아홉 장 띄웠다 — 아무도 `_claim_page` 를 안 불렀다.
    popups = [_FakePage(f"https://saramin.co.kr/detail/{index}") for index in range(9)]
    worker._context._pages.extend(popups)  # type: ignore[attr-defined]
    worker._page = popups[-1]

    closed = worker._prune_tabs()

    assert closed == 4
    assert len(worker._context.pages) == 6
    assert not popups[-1].closed


def test_the_pile_does_not_grow_across_steps(tmp_path: Path) -> None:
    """걸음마다 한 장씩만 닫히던 것 — 앞 걸음이 띄운 탭을 다음 걸음에 다시 남의 것으로 읽었다."""
    worker = _worker(tmp_path, browser_max_tabs=6)
    worker._connect_mode = "spawned"
    pages = [_FakePage("https://saramin.co.kr/list")]
    worker._context = _FakeContext(pages)  # type: ignore[assignment]
    worker._page = pages[0]

    for step in range(10):  # 열 걸음, 걸음마다 탭 두 장을 띄운다
        worker._pages_before_action = worker._page_ids()
        fresh = [_FakePage(f"https://saramin.co.kr/{step}-{n}") for n in range(2)]
        worker._context._pages.extend(fresh)  # type: ignore[attr-defined]
        worker._page = fresh[-1]
        worker._prune_tabs()

    assert len(worker._context.pages) <= 6, "쌓이면 안 된다"


def test_attached_chrome_is_not_widened(tmp_path: Path) -> None:
    """사람의 크롬에 붙어 쓸 때는 넓히지 않는다 — 그동안 사람이 연 탭까지 우리 것이 된다."""
    worker = _worker(tmp_path, browser_max_tabs=2)
    worker._connect_mode = "attached"
    pages = [_FakePage(f"https://example.com/{index}") for index in range(8)]
    worker._context = _FakeContext(pages)  # type: ignore[assignment]
    worker._page = pages[0]
    worker._pages_before_action = {id(pages[0])}

    assert worker._prune_tabs() == 0
    assert len(worker._context.pages) == 8


def test_leftovers_from_the_last_run_are_ours(tmp_path: Path) -> None:
    """★ 26장이 한 장도 안 닫힌 진짜 이유 — 세션 복원으로 되살아난 탭은 아무도 안 적었다.

    우리가 띄운 크롬이 방금 떴다면 그 안의 탭은 우리 지난 판의 것이다. 적어야 닫힌다.
    """
    worker = _worker(tmp_path, browser_max_tabs=6)
    worker._connect_mode = "spawned"
    restored = [_FakePage(f"https://saramin.co.kr/old/{index}") for index in range(26)]
    worker._context = _FakeContext(restored)  # type: ignore[assignment]
    # 기동 때 하는 일: 있는 탭을 전부 우리 것으로 적는다
    for page in restored:
        worker._claim_page(page)
    worker._page = restored[-1]
    worker._pages_before_action = worker._page_ids()

    closed = worker._prune_tabs()

    assert closed == 20
    assert len(worker._context.pages) == 6


def test_in_our_own_chrome_every_tab_is_prunable(tmp_path: Path) -> None:
    """★ 실측이 고른 규칙 — 우리가 띄운 크롬의 탭은 아무도 안 적었어도 우리 것이다.

    세 번 틀린 끝에 남은 규칙이다(만진 것만 / 동작 중 이벤트 / 기동 때 목록 — 전부 구멍).
    적어 두는 것으로 가르려는 시도 자체가 틀렸다: 그 창은 우리가 띄웠고 우리 프로필이다.
    """
    worker = _worker(tmp_path, browser_max_tabs=6)
    worker._connect_mode = "spawned"
    restored = [_FakePage(f"https://saramin.co.kr/old/{index}") for index in range(26)]
    worker._context = _FakeContext(restored)  # type: ignore[assignment]
    worker._page = restored[-1]
    assert worker._our_pages == [], "아무것도 적지 않는다 — 세션 복원으로 되살아난 무더기다"

    closed = worker._prune_tabs()

    assert closed == 20
    assert len(worker._context.pages) == 6
    assert not restored[-1].closed, "지금 보는 탭은 남긴다"
    assert restored[0].closed and restored[19].closed, "오래된 것부터 닫는다"


def test_the_gauge_tells_the_truth_about_what_it_could_not_close(tmp_path: Path) -> None:
    """「닫을 것이 없었다」와 「닫으려 했는데 못 했다」를 가른다 — 이게 없어서 세 판을 헛봤다."""

    class _Stubborn(_FakePage):
        def close(self) -> None:
            raise RuntimeError("target closed")

    worker = _worker(tmp_path, browser_max_tabs=2)
    worker._connect_mode = "spawned"
    pages = [_Stubborn(f"https://example.com/{index}") for index in range(6)]
    worker._context = _FakeContext(pages)  # type: ignore[assignment]
    worker._page = pages[-1]

    assert worker._prune_tabs() == 0
    assert worker._tab_census["wanted_to_close"] == 4
    assert worker._tab_census["refused_to_close"] == 4


def test_a_chrome_we_attached_to_on_our_own_profile_is_ours(tmp_path: Path) -> None:
    """★ 「우리가 안 띄웠다」 ≠ 「우리 것이 아니다」 (2026-09-16 실측).

    앞 판의 백엔드가 띄운 크롬은 포트를 쥔 채 남고, 다음 판은 거기에 **붙는다**.
    그것을 남의 창으로 읽어서 창도 안 내리고(3.4초 뺏김) 탭도 안 닫았다(26장 그대로).
    """
    worker = _worker(tmp_path, browser_max_tabs=6)
    worker._connect_mode = "attached"

    worker._attached_is_ours = False  # 사람이 자기 프로필로 포트를 열어 둔 크롬
    assert worker._browser_is_ours() is False
    pages = [_FakePage(f"https://example.com/{index}") for index in range(20)]
    worker._context = _FakeContext(pages)  # type: ignore[assignment]
    worker._page = pages[0]
    assert worker._prune_tabs() == 0, "남의 창은 손대지 않는다"

    worker._attached_is_ours = True  # 우리 프로필로 떠 있던 우리 크롬
    assert worker._browser_is_ours() is True
    assert worker._prune_tabs() == 14
    assert len(worker._context.pages) == 6
