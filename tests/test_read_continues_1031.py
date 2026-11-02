"""browser_read 이어 읽기 (2026-10-31 · Kimi 강연 자막 판: 2만 자에서 잘리고 스크롤해도 같은 2만 자 → 자막 16분에서 멈춤)."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def worker_page(tmp_path: Path):
    playwright_api = pytest.importorskip("playwright.sync_api")
    from alture_jarvis.browser import BrowserWorker
    from alture_jarvis.config import JarvisConfig

    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_context().new_page()
            lines = "".join(f"<p>{i:05d}분 자막 줄입니다 가나다라마바사 아자차카타파하</p>" for i in range(1, 1601))
            page.set_content(f"<html><body>{lines}</body></html>")
            worker._page = page
            yield worker, page
        finally:
            browser.close()


def test_a_long_page_can_be_read_to_the_end_in_parts(worker_page) -> None:
    worker, page = worker_page
    first = worker._read(page, {"max_chars": 20000})
    assert first["char_count"] == 20000 and first["has_more"] is True and first["next_offset"] == 20000
    assert "offset=20000" in first["note"]
    seen = first["text"]
    offset = first["next_offset"]
    for _ in range(5):
        part = worker._read(page, {"max_chars": 20000, "offset": offset})
        seen += part["text"]
        if not part.get("has_more"):
            break
        offset = part["next_offset"]
    assert "01600분" in seen and "00001분" in seen, "처음부터 끝까지 다 읽혀야 한다"
    assert "has_more" not in part


def test_a_short_page_says_nothing_about_more(worker_page) -> None:
    worker, page = worker_page
    page.set_content("<html><body><p>짧은 글</p></body></html>")
    out = worker._read(page, {"max_chars": 20000})
    assert "has_more" not in out and "offset" not in out


# ── 유튜브 영상 페이지는 「읽기」가 자막을 읽는다(같은 판 · 페이지 전체에 메뉴 · 추천이 섞여 16분에서 끊김) ──

YT = """<html><head><title>강연 - YouTube</title></head><body>
<div id="menu">홈 Shorts 구독 추천 영상 추천 영상 추천 영상</div>
<button id="open" aria-label="스크립트 표시">스크립트 표시</button>
<div id="panel"></div>
<script>
document.getElementById('open').addEventListener('click', () => {
  const panel = document.getElementById('panel');
  for (let i = 0; i < 1200; i++) {
    const row = document.createElement('transcript-segment-view-model');
    const m = Math.floor(i / 30), s = (i % 30) * 2;
    row.innerHTML = '<div class="ytwTranscriptSegmentViewModelTimestamp">' + m + ':' + String(s).padStart(2, '0') + '</div>'
      + '<div class="ytwTranscriptSegmentViewModelTimestampA11yLabel">' + m + '분</div>'
      + '<span class="ytAttributedStringHost">말 ' + i + ' 번째 문장 가나다라마바사</span>';
    panel.appendChild(row);
  }
});
</script></body></html>"""


def test_on_a_youtube_watch_page_read_returns_the_whole_transcript_in_parts(worker_page) -> None:
    worker, page = worker_page
    page.route("https://www.youtube.com/watch*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=YT))
    page.goto("https://www.youtube.com/watch?v=test")
    first = worker._read(page, {"max_chars": 20000})
    assert first["source"] == "youtube_transcript" and first["transcript_lines"] == 1200
    assert first["text"].startswith("[유튜브 자막 · 1200줄 · 0:00~39:58]") and "[0:00] 말 0 번째" in first["text"]
    assert "추천 영상" not in first["text"], "메뉴 · 추천이 섞이지 않는다"
    seen, offset = first["text"], first.get("next_offset")
    while offset:
        part = worker._read(page, {"max_chars": 20000, "offset": offset})
        seen += part["text"]
        offset = part.get("next_offset")
    assert "[39:58] 말 1199 번째" in seen


LAZY = """<html><head><title>느린 강연 - YouTube</title></head><body>
<video src="" autoplay></video>
<button aria-label="스크립트 표시">스크립트 표시</button>
<div id="box" style="height:300px; overflow-y:auto"><div id="list"></div></div>
<script>
let made = 0;
const more = () => {
  const list = document.getElementById('list');
  for (let k = 0; k < 40 && made < 600; k++, made++) {
    const row = document.createElement('transcript-segment-view-model');
    const m = Math.floor(made / 15), s = (made % 15) * 4;
    row.style.display = 'block'; row.style.height = '30px';
    row.innerHTML = '<div class="ytwTranscriptSegmentViewModelTimestamp">' + m + ':' + String(s).padStart(2, '0') + '</div>'
      + '<span class="ytAttributedStringHost">줄 ' + made + ' swarm 이야기</span>';
    list.appendChild(row);
  }
};
document.querySelector('button').addEventListener('click', more);
document.getElementById('box').addEventListener('scroll', (e) => {
  const b = e.target; if (b.scrollTop + b.clientHeight >= b.scrollHeight - 50) more();
});
</script></body></html>"""


def test_a_lazily_drawn_transcript_is_scrolled_and_gathered_to_the_end(worker_page) -> None:
    worker, page = worker_page
    page.route("https://www.youtube.com/watch*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=LAZY))
    page.goto("https://www.youtube.com/watch?v=lazy")
    out = worker._read(page, {"max_chars": 20000, "selector": "ytd-transcript-renderer"})   # 판 7aebb25a 처럼 칸 이름을 붙여 와도
    assert out["transcript_lines"] == 600, out.get("transcript_lines")
    assert out["text"].startswith("[유튜브 자막 · 600줄 · 0:00~39:56]")


def test_extract_on_a_youtube_page_gives_the_matching_transcript_lines(worker_page) -> None:
    worker, page = worker_page
    page.route("https://www.youtube.com/watch*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=YT))
    page.goto("https://www.youtube.com/watch?v=test")
    out = worker._extract(page, {"find": ["말 777 번째"]})
    assert out["source"] == "youtube_transcript"
    assert "말 777 번째" in out["text"] and "말 775 번째" in out["text"] and "말 10 번째" not in out["text"]
