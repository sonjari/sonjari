"""믿는 태그는 글이 가장 많은 것을 · 그림으로 된 본문은 읽어서 붙인다 (2026-10-05).

1. 본문 고르기는 문서에서 **처음 나오는** `<article>`·`<main>` 을 그대로 믿었다. 연합뉴스 기사는 요약 상자
   `<article class=story-summary>`(154자)가 본문보다 먼저 와서 기사를 요약 한 줄만 읽고 있었고(페이지 글의 3%),
   사람인 템플릿 공고는 회사가 쓴 영역 안의 `<main>`(4%)만 읽었다. 멀쩡한 여덟 곳은 85~100% 였다.
2. 통이미지 공고는 「그림이라 확인 못 함」이라고 말하는 데까지였다. 정답을 아는 공고 그림으로 재 보니(운영 모델, 3판)
   값 18개 중 17·17·18개가 글자 그대로 맞았다 — 읽어서 붙이되 「틀릴 수 있다」고 적는다.
"""
from __future__ import annotations

import io
from typing import Any

import pytest

from alture_jarvis.browser import _EXTRACT_MAIN_JS, BrowserWorker, _clean_lines

BODY = "금융당국은 4일 긴급 점검 회의를 열고 기업 2만8천곳에 보안 점검을 권고했다. " * 12
SIDE = "".join(f"<p>많이 본 뉴스 {i} — 다른 기사의 요약 문장이 여기에 길게 이어집니다. 관련 소식을 더 전합니다.</p>" for i in range(18))

# 연합뉴스처럼: 요약 상자 article 이 본문 article 보다 먼저 온다.
SUMMARY_FIRST = f"""
<html><body><div class="wrapper">
<article class="story-summary"><p>{"금융권 해킹에 정부가 비상 대응에 나섰다는 요약입니다. " * 5}</p></article>
<article id="articleWrap"><h1>금융권 해킹에 정부 비상대응</h1><p>{BODY}</p></article>
<div class="side">{SIDE}</div>
</div></body></html>
"""

# 사람인 템플릿처럼: 회사가 쓴 작은 main 하나 · 사이트가 채운 칸은 그 밖 · 페이지 글은 훨씬 많다.
SMALL_MAIN = f"""
<html><body><div id="content">
<div class="summary"><dl><dt>근무형태</dt><dd>계약직 12개월</dd><dt>급여</dt><dd>면접 후 결정</dd></dl></div>
<div class="user_content"><main class="job-posting"><p>{"국책과제 운영 관리와 연구비 정산을 맡습니다. " * 6}</p></main></div>
<div class="howto"><dl><dt>마감일</dt><dd>2026.10.21 23:59</dd></dl></div>
<div class="company">{"".join(f"<p>회사 소개 {i} — 연혁과 사업 분야, 복리후생과 근무 환경에 대한 설명이 길게 이어집니다. 지원 전 참고하세요.</p>" for i in range(40))}</div>
</div></body></html>
"""


def _evaluate(html: str) -> dict[str, Any]:
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_page()
            page.set_content(html)
            found = page.evaluate(_EXTRACT_MAIN_JS)
            found["text"] = _clean_lines(found["text"], 20_000)
            return found
        finally:
            browser.close()


# --- 1. 믿는 태그 ---------------------------------------------------------------

def test_the_trusted_tag_with_the_most_text_wins_not_the_first_one() -> None:
    found = _evaluate(SUMMARY_FIRST)

    assert found["selector"].startswith("article#articleWrap")
    assert "긴급 점검 회의" in found["text"]
    assert "많이 본 뉴스" not in found["text"], "본문 태그를 믿었으니 옆의 잡음은 싣지 않는다"


def test_a_trusted_tag_holding_a_sliver_of_the_page_is_not_trusted() -> None:
    found = _evaluate(SMALL_MAIN)

    assert not found["selector"].startswith("main"), found["selector"]
    text = found["text"]
    assert "국책과제 운영 관리" in text
    assert "계약직 12개월" in text and "2026.10.21 23:59" in text, "태그 밖의 사이트 칸이 빠지지 않는다"


def test_an_ordinary_main_is_trusted_as_before() -> None:
    html = f"<html><body><nav><a href='/'>홈</a></nav><main><h1>글</h1><p>{BODY}</p></main><footer>회사 정보</footer></body></html>"

    assert _evaluate(html)["selector"].startswith("main")


# --- 2. 그림 본문 ---------------------------------------------------------------

def _png(width: int, height: int) -> bytes:
    image_module = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    image_module.new("RGB", (width, height), (250, 250, 250)).save(buffer, format="PNG")
    return buffer.getvalue()


class _Response:
    def __init__(self, raw: bytes, ok: bool = True) -> None:
        self._raw, self.ok = raw, ok

    def body(self) -> bytes:
        return self._raw


class _Request:
    def __init__(self, raw: bytes) -> None:
        self.raw, self.asked = raw, []

    def get(self, url: str, timeout: int = 0) -> _Response:
        self.asked.append(url)
        return _Response(self.raw, ok=bool(self.raw))


class _Context:
    def __init__(self, raw: bytes) -> None:
        self.request = _Request(raw)


class _Page:
    url = "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=1"

    def __init__(self, raw: bytes) -> None:
        self.context = _Context(raw)


def _worker(reader: Any = None) -> BrowserWorker:
    worker = object.__new__(BrowserWorker)
    if reader is not None:
        worker.image_text_reader = reader
    return worker


def test_a_tall_image_is_read_in_tiles_and_joined() -> None:
    calls: list[int] = []

    def reader(png: bytes) -> str:
        calls.append(len(png))
        return "모집부문\n연구행정 담당 (1명)\n(빈 이미지이므로 옮겨 적을 글자가 없습니다.)" if len(calls) == 1 else "연구행정 담당 (1명)\n급여 : 연봉 3,480만원"

    text, images, tiles = _worker(reader)._read_body_images(_Page(_png(765, 3000)), ["https://img.example/poster.png"])

    assert images == 1 and tiles == 2 and len(calls) == 2
    assert text.splitlines() == ["모집부문", "연구행정 담당 (1명)", "급여 : 연봉 3,480만원"], "겹친 줄과 모델의 군말은 싣지 않는다"


def test_a_very_long_image_stops_at_the_cap_and_says_so() -> None:
    worker = _worker(lambda png: "한 줄")
    counter = {"n": 0}

    def reader(png: bytes) -> str:
        counter["n"] += 1
        return f"줄 {counter['n']}"

    worker.image_text_reader = reader
    text, _images, tiles = worker._read_body_images(_Page(_png(765, 30_000)), ["https://img.example/long.png"])

    assert tiles == BrowserWorker._IMAGE_READ_MAX_TILES
    assert text.splitlines()[-1].startswith("…(그림이 길어")


def test_without_a_reader_or_without_the_image_nothing_is_invented() -> None:
    assert _worker()._read_body_images(_Page(_png(765, 2000)), ["https://img.example/a.png"]) == ("", 0, 0)
    assert _worker(lambda png: "글")._read_body_images(_Page(b""), ["https://img.example/a.png"]) == ("", 0, 0)
    assert _worker(lambda png: "글")._read_body_images(_Page(_png(10, 10)), []) == ("", 0, 0)


def test_a_reader_that_fails_or_says_nothing_leaves_it_unread() -> None:
    def broken(png: bytes) -> str:
        raise RuntimeError("model does not see images")

    assert _worker(broken)._read_body_images(_Page(_png(765, 2000)), ["https://img.example/a.png"])[0] == ""
    assert _worker(lambda png: "")._read_body_images(_Page(_png(765, 2000)), ["https://img.example/a.png"])[:2] == ("", 0)
