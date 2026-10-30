"""천천히 닫히는 제안 목록을 「안 골라짐」으로 읽지 않는다 (2026-10-30 · 판 eba156fb 에어비앤비 행선지).

0.5초에 한 번만 봤더니 실제로 골라졌는데 verified=false 가 나왔고, 모델은 3걸음 만에 「화면을 직접 확인해 달라」며 사람에게 넘겼다.
진짜 크로미움으로: 고르면 1.2초 뒤 닫히는 목록은 확인됨 · 눌러도 아무 일 없는 목록은 여전히 확인 안 됨.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PAGE = """<html><head><meta charset="utf-8"></head><body>
<input id="where" placeholder="Search destinations" autocomplete="off">
<ul id="list" style="display:none"><li role="option" id="opt">Shibuya Station, Tokyo</li></ul>
<script>
  const box = document.getElementById('where'), list = document.getElementById('list'), opt = document.getElementById('opt');
  box.addEventListener('input', () => { list.style.display = box.value ? 'block' : 'none'; });
  opt.addEventListener('click', () => {
    if (window.BROKEN) return;                       // 역방향: 눌러도 안 골라진다
    box.value = 'Shibuya Station, Tokyo Prefecture, Japan';
    setTimeout(() => { list.style.display = 'none'; }, 1200);   // 천천히 닫힌다
  });
</script></body></html>"""


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
            page.set_default_timeout(5000)
            page.set_content(PAGE)
            worker._page = page
            yield worker, page
        finally:
            browser.close()


def _pick(worker, page) -> dict:
    snap = worker._snapshot(page, {})
    box = next(item for item in snap["elements"] if "Search destinations" in str(item.get("name") or item.get("placeholder") or ""))
    return worker._pick_suggestion(page, {"ref": box["ref"], "text": "Shibuya", "choose": "Shibuya Station"})


def test_a_list_that_closes_slowly_is_still_a_pick(worker_page) -> None:
    worker, page = worker_page
    result = _pick(worker, page)
    assert result["action"] == "suggestion_picked" and result["verified"] is True


def test_a_click_that_did_nothing_is_still_unverified(worker_page) -> None:
    worker, page = worker_page
    page.evaluate("window.BROKEN = true")
    result = _pick(worker, page)
    assert result["action"] == "suggestion_picked" and result["verified"] is False
