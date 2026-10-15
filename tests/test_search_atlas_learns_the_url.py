"""검색이 통한 주소를 배워 두고 다음엔 그리로 바로 간다.

## 왜 (2026-09-06 실측)

    검색칸을 못 찾음         31 건 · 5 종   (위시켓 22 건 — 걸음 2 위 사이트)
    모델이 손으로 주소 조립   57 건 · 11 종
    ────────────────────────────────────
    합계                     88 건 · 12 종

손 조립은 오타가 난다. 실측 사례: 다나와에서 퍼센트 인코딩을 한 글자 틀려
「무섧마우스」로 검색했고 **404 가 아니라 빈 목록**으로 조용히 왔다.

## 왜 「API 학습」이 아닌가

klura 같은 방식은 네트워크를 캡처해 토큰까지 재생한다. 우리는 안 한다:

    ① 상위 사이트가 서버 렌더다. 크몽 검색은 요청 58 건이 전부 JS 청크,
       데이터 API 호출 **0 건** — 때릴 API가 없다.
    ② 토큰을 저장하면 사용자님 실계정 세션이 디스크에 남는다.
    ③ 브라우저 없이 쏘면 봇 검사에 더 걸린다(여기어때 Cloudflare 실측).

배우는 것은 **진짜 크롬이 열어서 결과가 나온 주소** 하나뿐이다.
"""

from __future__ import annotations

import json

import pytest

from alture_jarvis.search_atlas import (
    CONFIRM_AT,
    MIN_ROWS,
    SearchAtlas,
    fill,
    is_search_engine,
    template_from,
)

# 실측한 주소들.
KMONG = "https://kmong.com/search?type=gigs&keyword=AI%20%EC%9E%90%EB%8F%99%ED%99%94"
KMONG_PLAIN = "https://kmong.com/search?type=gigs&keyword=AI 자동화"
YEOGI = (
    "https://www.yeogi.com/domestic-accommodations"
    "?keyword=경주&checkIn=2026-10-10&checkOut=2026-10-11&personal=2"
)


# ─────────────────────────────────────────────────────────────────────────────
# 틀 만들기 — 검색어가 주소에 있을 때만
# ─────────────────────────────────────────────────────────────────────────────


def test_검색어가_주소에_있으면_틀이_된다():
    template = template_from(KMONG_PLAIN, "AI 자동화")
    assert "{query}" in template
    assert "type=gigs" in template, "다른 인자는 그대로 살려야 한다"
    assert "kmong.com/search" in template


def test_이름이_뭐든_값이_검색어면_그_자리다():
    """`keyword`·`q`·`stext`… 이름은 사이트마다 다르다. **값**으로 찾는다."""
    for name in ("q", "stext", "searchword", "이상한이름"):
        template = template_from(f"https://x.example/find?{name}=경주&page=1", "경주")
        assert "{query}" in template, name


def test_검색어가_없으면_안_배운다():
    """그 주소는 검색을 안 담고 있다 — 다음 검색어로 바꿔 쓸 수가 없다."""
    assert template_from("https://kmong.com/gig/12345", "AI 자동화") == ""
    assert template_from("https://x.example/list?page=2", "경주") == ""


def test_검색엔진은_안_배운다():
    """거기 주소는 그 사이트의 검색이 아니다."""
    assert is_search_engine("https://search.naver.com/search.naver?query=경주")
    assert template_from("https://search.naver.com/search.naver?query=경주", "경주") == ""
    assert template_from("https://www.google.com/search?q=경주", "경주") == ""


@pytest.mark.parametrize(
    "junk", ["utm_source=x", "gclid=abc", "token=SECRET", "sessionId=9", "_rsc=1nh4w"]
)
def test_추적_인증_인자는_버린다(junk):
    """★ 토큰이 배운 표에 남으면 그게 곧 자격증명 저장이다."""
    template = template_from(f"https://x.example/find?q=경주&{junk}", "경주")
    assert "{query}" in template
    assert junk.split("=")[0] not in template, f"{junk} 가 남았다"


def test_틀에_검색어를_넣을_때_인코딩은_한_번만():
    """손으로 퍼센트 인코딩하다 「무섧마우스」가 나왔다. 코드가 한다."""
    url = fill("https://kmong.com/search?type=gigs&keyword={query}", "무선 마우스")
    assert "%EB%AC%B4%EC%84%A0" in url
    assert "{query}" not in url
    assert "%25" not in url, "이중 인코딩"


def test_틀이_아니면_아무것도_안_준다():
    assert fill("https://x.example/find?q=고정값", "경주") == ""
    assert fill("", "경주") == ""


# ─────────────────────────────────────────────────────────────────────────────
# 표 — 배우고, 확인되면 쓰고, 안 먹으면 버린다
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def atlas(tmp_path):
    return SearchAtlas(tmp_path / "search_atlas.json")


def test_한_번_본_것은_아직_안_쓴다(atlas):
    """한 번은 우연일 수 있다. 우연으로 길을 바꾸면 안 된다."""
    atlas.learn(KMONG_PLAIN, "AI 자동화", rows=12)
    assert atlas.url_for("https://kmong.com/", "블로그 자동화") == ""


def test_두_번_보면_쓴다(atlas):
    for _ in range(CONFIRM_AT):
        atlas.learn(KMONG_PLAIN, "AI 자동화", rows=12)
    url = atlas.url_for("https://kmong.com/", "블로그 자동화")
    assert url.startswith("https://kmong.com/search?")
    assert "type=gigs" in url
    assert "%EB%B8%94%EB%A1%9C%EA%B7%B8" in url, "새 검색어가 들어가야 한다"


def test_결과가_적으면_안_배운다(atlas):
    """한두 줄은 목록이 아니다 — 상세 화면일 수 있다."""
    atlas.learn(KMONG_PLAIN, "AI 자동화", rows=MIN_ROWS - 1)
    assert atlas.known() == {}


def test_사이트가_주소를_바꾸면_새것으로_갈아탄다(atlas):
    for _ in range(CONFIRM_AT):
        atlas.learn("https://x.example/old?q=경주", "경주", rows=9)
    assert "old" in atlas.url_for("https://x.example/", "부산")
    atlas.learn("https://x.example/new?query=경주", "경주", rows=9)
    row = atlas.known()["x.example"]
    assert "new" in row["template"] and row["seen"] == 1, "새 틀은 다시 확인받아야 한다"


def test_안_먹으면_버린다(atlas):
    """재생해서 결과가 없으면 그 틀은 죽은 것이다."""
    for _ in range(CONFIRM_AT):
        atlas.learn(KMONG_PLAIN, "AI 자동화", rows=12)
    assert atlas.forget("https://kmong.com/") is True
    assert atlas.url_for("https://kmong.com/", "무엇이든") == ""


def test_파일로_살아남는다(tmp_path):
    """판이 끝나도 배운 것이 남아야 다음 판이 덕을 본다."""
    path = tmp_path / "search_atlas.json"
    first = SearchAtlas(path)
    for _ in range(CONFIRM_AT):
        first.learn(KMONG_PLAIN, "AI 자동화", rows=12)
    assert SearchAtlas(path).url_for("https://kmong.com/", "부업").startswith("https://kmong.com/")
    # 사람이 열어 볼 수 있는 모양이어야 한다.
    assert "kmong.com" in json.loads(path.read_text(encoding="utf-8"))["hosts"]


def test_깨진_파일이어도_죽지_않는다(tmp_path):
    path = tmp_path / "search_atlas.json"
    path.write_text("{ 깨진 json", encoding="utf-8")
    assert SearchAtlas(path).known() == {}


def test_모르는_사이트에는_아무_말도_안_한다(atlas):
    assert atlas.url_for("https://처음보는곳.example/", "경주") == ""


# ─────────────────────────────────────────────────────────────────────────────
# 브라우저 배선 — 검색칸을 찾기 **전에** 배운 주소로 간다
# ─────────────────────────────────────────────────────────────────────────────


class _Page:
    def __init__(self, url: str) -> None:
        self.url = url

    def wait_for_timeout(self, ms: int) -> None:
        return None


class _Worker:
    """`_learned_search` 만 진짜에서 빌려 온다. 실제 크롬은 안 띄운다."""

    def __init__(self, atlas, rows: int, blow_up: bool = False) -> None:
        from alture_jarvis.browser import BrowserWorker

        self._search_atlas = atlas
        self._rows = rows
        self._blow_up = blow_up
        self.visited: list[str] = []
        self._last_results: list = []
        self._results_origin_host = ""
        self._reads_since_search = 9
        self._searched_before = False
        self._requested_stay = None
        self._learned_search = BrowserWorker._learned_search.__get__(self)
        # 결과는 **그려진 뒤에** 센다(2026-10-13) — 그 기다림도 진짜에서 빌려 온다.
        self._results_once_drawn = BrowserWorker._results_once_drawn.__get__(self)
        self._DRAWN_ROWS, self._DRAWN_POLL_MS = BrowserWorker._DRAWN_ROWS, BrowserWorker._DRAWN_POLL_MS
        self._page_says_no_results = lambda page: False
        self._date_rewrite_evidence = staticmethod(BrowserWorker._date_rewrite_evidence)

    # 항해 흉내
    def _goto_checked(self, page, url):
        if self._blow_up:
            raise RuntimeError("site_blocked:x")
        self.visited.append(url)
        page.url = url

    _wait_until_operable = staticmethod(lambda page: {"count": 5, "ms": 1, "polls": 1})
    _apply_requested_dates_here = staticmethod(lambda page: None)
    _remember_results_origin = staticmethod(lambda page: None)
    _mark_visited = staticmethod(lambda url: None)
    _stay_note_for_list = staticmethod(lambda page, applied=None: "")
    _evidence = staticmethod(lambda action, **kw: {"action": action, **kw})

    def _collect_results(self, page, *, limit=12):
        return [{"rank": i, "url": f"https://x/{i}", "title": f"t{i}"} for i in range(1, self._rows + 1)]


def _confirmed(atlas):
    for _ in range(CONFIRM_AT):
        atlas.learn(KMONG_PLAIN, "AI 자동화", rows=12)
    return atlas


def test_배운_주소가_있으면_검색칸을_안_찾는다(atlas):
    """★ 이 층의 존재 이유. 위시켓에서 검색칸을 22 번 못 찾았다."""
    worker = _Worker(_confirmed(atlas), rows=8)
    out = worker._learned_search(_Page("https://kmong.com/"), "블로그 자동화")
    assert out is not None
    assert out["strategy"] == "learned_url"
    assert out["result_count"] == 8
    assert worker.visited and "kmong.com/search" in worker.visited[0]
    assert "%EB%B8%94%EB%A1%9C%EA%B7%B8" in worker.visited[0], "새 검색어로 갔어야 한다"


def test_결과가_모자라면_틀을_버리고_물러난다(atlas):
    """배운 것이 낡으면 **스스로 물러난다.** 안 그러면 어제 주소가 오늘 판을 죽인다."""
    worker = _Worker(_confirmed(atlas), rows=MIN_ROWS - 1)
    assert worker._learned_search(_Page("https://kmong.com/"), "무엇이든") is None
    assert atlas.url_for("https://kmong.com/", "무엇이든") == "", "낡은 틀이 남아 있다"


def test_모르는_사이트면_조용히_비켜준다(atlas):
    worker = _Worker(atlas, rows=9)
    assert worker._learned_search(_Page("https://처음보는곳.example/"), "경주") is None
    assert worker.visited == []


def test_이동이_터져도_판을_안_죽인다(atlas):
    """이 층은 거들 뿐이지 검색의 조건이 아니다."""
    worker = _Worker(_confirmed(atlas), rows=9, blow_up=True)
    assert worker._learned_search(_Page("https://kmong.com/"), "경주") is None


def test_성공하면_순위가_다음_걸음에_남는다(atlas):
    """`browser_open_result` 가 바로 이어져야 한다 — 안 그러면 반쪽이다."""
    worker = _Worker(_confirmed(atlas), rows=6)
    worker._learned_search(_Page("https://kmong.com/"), "부업")
    assert len(worker._last_results) == 6
    assert worker._reads_since_search == 0


def test_site_search_가_배운_길을_먼저_본다():
    """배선이 실제로 앞에 있는지 — 값을 만들어 놓고 안 보면 소용이 없다."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "browser.py"
    ).read_text(encoding="utf-8")
    # 2026-10-07: 본문은 `_site_search_here` 로 옮겼다(`_site_search` 는 입력 폼에서 불렸을 때 새 탭으로 돌리는 겉이다).
    body = source.split("def _site_search_here(")[1].split("\n    def ")[0]
    assert "self._learned_search(page, query)" in body
    # 검색칸 훑기보다 **앞**이어야 한다.
    assert body.index("_learned_search") < body.index("_SITE_SEARCH_JS")
    # 그리고 통한 주소를 배워야 한다.
    assert "self._learn_search_url(page" in body


# ─────────────────────────────────────────────────────────────────────────────
# ★ 문에 걸지 말고, 결과가 나온 자리에 건다 (2026-09-06 라이브가 가르친 것)
# ─────────────────────────────────────────────────────────────────────────────


class _TypingWorker:
    """`browser_site_search` 가 죽고 손으로 검색한 판을 흉내 낸다."""

    def __init__(self, atlas) -> None:
        from alture_jarvis.browser import BrowserWorker

        self._search_atlas = atlas
        self._typed_recently = ("", 0.0)
        self._remember_typed = BrowserWorker._remember_typed.__get__(self)
        self._learn_search_url = BrowserWorker._learn_search_url.__get__(self)
        self._TYPED_TTL_SEC = BrowserWorker._TYPED_TTL_SEC


def test_손으로_친_검색도_배운다(atlas):
    """★ 위시켓 라이브(잡 `b60d7d6c`)가 잡은 구멍.

    `browser_site_search` 가 2 걸음에 `site_search_box_not_found` 로 죽고, 모델이
    `browser_fill` + `browser_press` 로 손수 검색해 결과까지 갔다. 학습기를
    site_search 성공 경로에만 걸어 뒀던 탓에 **한 번도 안 지났다.**
    """
    worker = _TypingWorker(atlas)
    worker._remember_typed("AI 챗봇")          # browser_fill 이 한 일
    page = _Page("https://x.example/search?q=AI 챗봇&page=1")
    for _ in range(CONFIRM_AT):
        worker._learn_search_url(page, rows=9)   # 목록이 뜬 자리
    assert atlas.url_for("https://x.example/", "블록체인").startswith("https://x.example/search?")


def test_친_값이_주소에_없으면_안_배운다(atlas):
    """위시켓 결과 주소는 `?d=JYZw+gxgFghgdg…` — 조건을 통째로 인코딩한 덩어리다.

    틀로 만들어 봐야 다음 검색어에 못 쓴다. 그래서 **일부러 안 배운다.**
    """
    worker = _TypingWorker(atlas)
    worker._remember_typed("AI 챗봇")
    worker._learn_search_url(_Page("https://wishket.com/project/?d=JYZw%2BgxgFghgdg"), rows=9)
    assert atlas.known() == {}


def test_오래된_입력은_검색어로_안_본다(atlas):
    """3 분 전에 친 것은 딴 칸에 친 값이다."""
    import time as _t

    worker = _TypingWorker(atlas)
    worker._typed_recently = ("옛날값", _t.time() - 600)
    worker._learn_search_url(_Page("https://x.example/search?q=옛날값"), rows=9)
    assert atlas.known() == {}


@pytest.mark.parametrize("value", ["", "x", "본문" * 200])
def test_검색어로_보기_어려운_값은_안_들고_있는다(atlas, value):
    """한 글자는 오타고, 아주 긴 것은 본문 붙여넣기다."""
    worker = _TypingWorker(atlas)
    worker._remember_typed(value)
    assert worker._typed_recently[0] == ""


def test_세_자리_모두에_배선돼_있다():
    """★ 오늘만 세 번 물린 규칙 — 문 하나에만 걸면 다른 문으로 들어온다."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "browser.py"
    ).read_text(encoding="utf-8")
    assert source.count("_learn_search_url(page") >= 3, "결과가 나오는 자리마다 걸려야 한다"
    for door in ("_site_search_here(", "_load_more_tool(", "_recover_results_for_open("):
        body = source.split(f"def {door}")[1].split("\n    def ")[0]
        assert "_learn_search_url(page" in body, f"{door} 에 학습기가 없다"
