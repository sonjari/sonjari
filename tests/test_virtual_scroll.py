"""가상 스크롤 목록을 **내리며 쌓아** 모은다 — 진짜 크로미움 (2026-09-18).

긴 채용·쇼핑 목록은 보이는 줄만 DOM 에 두고 내리면 앞줄을 지운다. 링크 수가 그대로라 「더 없다」로 멈췄고,
끝으로 한 번에 뛰면 중간 줄을 건너뛴다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from alture_jarvis.browser import BrowserWorker  # noqa: E402
from alture_jarvis.config import JarvisConfig  # noqa: E402

VIRTUAL_PAGE = """<!doctype html><html><body style="margin:0">
<header><a href="https://jobs.example/home">홈</a></header>
<div id="box" style="height:600px;overflow-y:auto;position:relative">
  <div id="spacer" style="height:12000px;position:relative"></div>
</div>
<script>
const ROW = 40, TOTAL = 300, box = document.getElementById('box'), spacer = document.getElementById('spacer');
function render() {
  const first = Math.max(0, Math.floor(box.scrollTop / ROW) - 2), last = Math.min(TOTAL, first + 20);
  spacer.innerHTML = '';
  const ul = document.createElement('ul'); ul.className = 'jobs'; ul.style.cssText = 'margin:0;padding:0';
  for (let i = first; i < last; i++) {
    const li = document.createElement('li'); li.className = 'job';
    li.style.cssText = 'position:absolute;top:' + (i * ROW) + 'px;height:' + ROW + 'px;list-style:none';
    li.innerHTML = '<a href="https://jobs.example/view/' + i + '">여수 회계 담당자 채용 공고 번호 ' + i + '</a>';
    ul.appendChild(li);
  }
  spacer.appendChild(ul);
}
box.addEventListener('scroll', render); render();
</script></body></html>"""

ORDINARY_PAGE = """<!doctype html><html><body><ul class="jobs">""" + "".join(
    f'<li class="job" style="height:40px"><a href="https://jobs.example/view/{i}">여수 회계 담당자 채용 공고 번호 {i}</a></li>'
    for i in range(60)
) + "</ul></body></html>"


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            launched = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        yield launched
        launched.close()


@pytest.fixture()
def worker(tmp_path: Path) -> BrowserWorker:
    return BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))


def test_a_virtual_list_is_harvested_row_by_row(worker, browser) -> None:
    page = browser.new_page(viewport={"width": 1200, "height": 800})
    page.set_content(VIRTUAL_PAGE)
    assert len(worker._result_list_rows(page)) < 25, "시험 페이지가 정말 가상 스크롤이어야 한다"
    outcome = worker._load_more(page, rounds=3)
    assert outcome and outcome.get("virtualized") is True, outcome
    hrefs = {row["href"] for row in worker._virtual_rows}
    assert "https://jobs.example/view/0" in hrefs and "https://jobs.example/view/150" in hrefs, "중간 줄을 건너뛰면 안 된다"
    assert len(hrefs) >= 250, len(hrefs)
    results = worker._collect_results(page, limit=30)
    assert "https://jobs.example/view/0" in [r.get("url") or r.get("href") for r in results], results[:2]
    page.close()


def test_an_ordinary_long_list_is_not_mistaken_for_a_virtual_one(worker, browser) -> None:
    page = browser.new_page(viewport={"width": 1200, "height": 800})
    page.set_content(ORDINARY_PAGE)
    assert worker._harvest_virtual_list(page) is None
    page.close()
