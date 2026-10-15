"""섀도 DOM 안까지 본다 — 실제 크로미움으로 (2026-09-17).

MS 스토어(apps.microsoft.com)는 누를 것·글자가 전부 웹 컴포넌트의 섀도 DOM 안이라, 우리 페이지 안 코드
(`document.querySelectorAll`)가 **아무것도 못 봤다** — 스냅샷 0개, 본문 0자, 검색칸 없음. 16걸음을 헤매고 「못 찾았다」.
여기서는 같은 구조의 페이지를 직접 만들어 수집기마다 섀도 안이 보이는지, 그리고 **보통 페이지 결과는 한 글자도
안 바뀌었는지**를 잰다. 가짜 evaluate 로는 이 병을 못 잡는다(병이 브라우저의 DOM 규칙에 있다) — 진짜 브라우저를 쓴다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from alture_jarvis import browser as browser_module  # noqa: E402
from alture_jarvis.browser import BrowserWorker  # noqa: E402
from alture_jarvis.config import JarvisConfig  # noqa: E402

SHADOW_PAGE = """
<!doctype html><html><body>
<store-header></store-header>
<store-grid></store-grid>
<script>
customElements.define('store-search', class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML =
    '<form role="search"><input type="text" placeholder="앱, 게임 등 검색" aria-label="검색"></form>'; }
});
customElements.define('store-header', class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML =
    '<nav><a href="https://store.example/home">홈</a><a href="https://store.example/apps">앱</a></nav><store-search></store-search>'; }
});
customElements.define('app-card', class extends HTMLElement {
  constructor() { super(); const n = this.getAttribute('n');
    this.attachShadow({mode: 'open'}).innerHTML =
      '<div class="card"><a class="title" href="https://store.example/detail/app' + n + '">앱 이름 ' + n + ' 번째 스토어 앱입니다</a>' +
      '<span class="rating">4.' + n + '</span><slot></slot></div>'; }
});
customElements.define('store-grid', class extends HTMLElement {
  constructor() { super(); let html = '<section class="grid">';
    for (let i = 1; i <= 7; i++) html += '<app-card n="' + i + '">게시자 ' + i + '</app-card>';
    this.attachShadow({mode: 'open'}).innerHTML = html + '</section>'; }
});
</script>
</body></html>
"""

LIGHT_PAGE = """
<!doctype html><html><body>
<header><nav><a href="/home">홈</a><a href="/apps">앱</a></nav>
<form role="search"><input type="search" name="q" placeholder="검색"></form></header>
<main><ul class="results">
""" + "".join(
    f'<li class="item"><a href="/detail/{i}">결과 제목 번호 {i} 입니다</a><button>담기</button></li>' for i in range(1, 8)
) + """
</ul><article><p>""" + ("본문 문장입니다. " * 30) + """</p></article></main>
</body></html>
"""

CLOSED_PAGE = """
<!doctype html><html><body>
<script>
customElements.define('locked-widget', class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'closed'}).innerHTML = '<button style="width:120px;height:40px">누르기</button>'; }
});
for (let i = 0; i < 6; i++) document.body.appendChild(document.createElement('locked-widget'));
</script>
</body></html>
"""


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
    return BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out"))


def _page(browser, html: str):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.set_content(html)
    page.wait_for_timeout(100)
    return page


def _elements(worker: BrowserWorker, page) -> list[dict]:
    return worker._frame_elements_fast(page.main_frame, frame_label="main", frame_index=0, budget=200,
                                       start=0, include_box=False) or []


def test_the_snapshot_lists_the_search_box_inside_shadow_dom_and_its_ref_types(worker, browser) -> None:
    page = _page(browser, SHADOW_PAGE)
    rows = _elements(worker, page)
    box = next((r for r in rows if r["tag"] == "input"), None)
    assert box is not None, f"섀도 안 검색칸이 목록에 없다: {rows[:5]}"
    assert sum(1 for r in rows if (r.get("href") or "").endswith(tuple(f"app{i}" for i in range(1, 8)))) == 7
    # ref 로 다시 찾아 실제로 친다 — 목록에만 있고 못 누르면 소용없다.
    page.locator(f'[data-jarvis-ref="{box["ref"]}"]').fill("AI")
    typed = page.evaluate("() => document.querySelector('store-header').shadowRoot"
                          ".querySelector('store-search').shadowRoot.querySelector('input').value")
    assert typed == "AI"
    page.close()


def test_the_site_search_finder_reaches_a_box_inside_shadow_dom(worker, browser) -> None:
    page = _page(browser, SHADOW_PAGE)
    found = page.evaluate(BrowserWorker._SITE_SEARCH_JS)
    assert found and "검색" in found["name"], found
    assert page.locator("[data-jarvis-sitesearch]").count() == 1
    page.close()


def test_the_text_inside_shadow_dom_is_read_in_rendered_order(worker, browser) -> None:
    page = _page(browser, SHADOW_PAGE)
    text = worker._deep_text(page, 20000)
    assert "앱 이름 1 번째 스토어 앱입니다" in text and "4.1" in text and "게시자 1" in text, text[:300]
    assert text.index("앱 이름 1 번째 스토어 앱입니다") < text.index("4.1") < text.index("게시자 1") < text.index("앱 이름 2 번째 스토어 앱입니다"), \
        "slot 에 꽂힌 게시자는 카드 안 자리에서 읽혀야 한다"
    assert page.evaluate("() => document.body.innerText.length") < 5, "시험 페이지가 정말 섀도 DOM 이어야 이 시험이 뜻이 있다"
    page.close()


def test_read_and_extract_fall_back_to_shadow_text(worker, browser, monkeypatch) -> None:
    page = _page(browser, SHADOW_PAGE)
    monkeypatch.setattr(worker, "_sweep_for_lazy_content", lambda _page: None)
    read = worker._read(page, {})
    assert read.get("shadow_dom") is True and "앱 이름 7 번째 스토어 앱입니다" in read["text"]
    extracted = worker._extract(page, {})
    assert extracted.get("shadow_dom") is True and "게시자 3" in extracted["text"]
    page.close()


def test_the_result_list_is_found_across_shadow_boundaries(worker, browser) -> None:
    page = _page(browser, SHADOW_PAGE)
    rows = page.evaluate(BrowserWorker._RESULT_LIST_JS) or []
    hrefs = [row.get("href", "") for row in rows]
    assert sum(1 for h in hrefs if "/detail/app" in h) == 7, rows[:3]
    page.close()


def test_a_closed_shadow_page_says_unreadable_instead_of_absent_or_not_drawn(worker, browser, monkeypatch) -> None:
    page = _page(browser, CLOSED_PAGE)
    monkeypatch.setattr(worker, "_search_blocked", lambda _page: False)
    why = worker._why_empty(page, scanned=0, listed_nothing=True)
    assert why["empty_reason"] == "unreadable_structure", why
    assert "browser_click_at" in why["instruction"]
    page.close()


def test_an_ordinary_page_gives_exactly_the_same_results_as_before(worker, browser) -> None:
    """섀도 루트가 없는 페이지에서는 새 도우미가 **원래 질의 그대로**여야 한다 — 순서·개수·글자까지."""
    page = _page(browser, LIGHT_PAGE)
    raw_links = browser_module._COLLECT_LINKS_JS  # 감싼 것
    assert page.evaluate(raw_links) == page.evaluate(
        "() => Array.from(document.querySelectorAll('a[href]')).map(a => ({href: a.href, text: (a.innerText || a.title || a.getAttribute('aria-label') || '').trim()}))"
    )
    rows = _elements(worker, page)
    assert [r["name"] for r in rows][:3] == ["홈", "앱", "검색"]
    assert worker._deep_text(page, 20000) == "", "섀도 루트가 없으면 섀도 글자 읽기는 아무것도 안 해야 한다(비용·중복)"
    found = page.evaluate(BrowserWorker._SITE_SEARCH_JS)
    assert found and found["tag"] == "input"
    page.close()


CLOSED_FORM_PAGE = """
<!doctype html><html><body>
<script>
window.clicks = [];
customElements.define('locked-search', class extends HTMLElement {
  constructor() { super(); const root = this.attachShadow({mode: 'closed'});
    root.innerHTML = '<input type="text" aria-label="앱 검색" style="width:300px;height:30px">' +
      '<button style="width:100px;height:30px">검색 열기</button>' +
      '<button style="width:100px;height:30px">구매하기</button>' +
      '<input type="password" aria-label="비밀번호" style="width:200px;height:30px">';
    for (const b of root.querySelectorAll('button')) b.addEventListener('click', () => window.clicks.push(b.textContent));
    window.lockedInput = root.querySelector('input'); }
});
document.body.appendChild(document.createElement('locked-search'));
</script>
</body></html>
"""


def _target(targets: list[dict], name: str) -> dict:
    return next(t for t in targets if t["name"] == name)


def test_closed_shadow_targets_come_from_the_accessibility_tree_and_click_at_presses_them(worker, browser, monkeypatch) -> None:
    page = _page(browser, CLOSED_FORM_PAGE)
    monkeypatch.setattr(worker, "_search_blocked", lambda _page: False)
    why = worker._why_empty(page, scanned=0, listed_nothing=True)
    names = [t["name"] for t in why.get("targets", [])]
    assert "검색 열기" in names and "앱 검색" in names, why
    button = _target(why["targets"], "검색 열기")
    result = worker._click_at(page, {"x": button["x"], "y": button["y"]})
    assert result["target"]["name"] == "검색 열기"
    assert page.evaluate("() => window.clicks") == ["검색 열기"]
    page.close()


def test_click_at_runs_the_same_safety_check_as_click(worker, browser, monkeypatch) -> None:
    """좌표 누르기가 안전 검사를 **우회하는 문**이 되면 안 된다 — 이름은 닫힌 섀도 DOM 안에서도 읽는다."""
    page = _page(browser, CLOSED_FORM_PAGE)
    buy = _target(worker._ax_targets(page), "구매하기")
    # 읽기 전용이면 그 앞 검사에서 막히고, 읽기 전용을 꺼도 되돌릴 수 없는 동작 검사에서 막힌다 — 둘 다 본다.
    with pytest.raises(RuntimeError, match="read_only_action_blocked"):
        worker._click_at(page, {"x": buy["x"], "y": buy["y"]})
    monkeypatch.setattr(worker.config, "browser_read_only", False, raising=False)
    with pytest.raises(RuntimeError, match="irreversible_click_needs_approval"):
        worker._click_at(page, {"x": buy["x"], "y": buy["y"]})
    assert page.evaluate("() => window.clicks") == [], "막혔으면 실제로 안 눌려야 한다"
    with pytest.raises(ValueError, match="point_outside_window"):
        worker._click_at(page, {"x": 99999, "y": 5})
    page.close()


def test_type_at_types_into_a_closed_shadow_input_but_never_a_password(worker, browser, monkeypatch) -> None:
    page = _page(browser, CLOSED_FORM_PAGE)
    monkeypatch.setattr(worker.config, "browser_read_only", False, raising=False)
    targets = worker._ax_targets(page)
    box = _target(targets, "앱 검색")
    worker._type_at(page, {"x": box["x"], "y": box["y"], "text": "AI"})
    assert page.evaluate("() => window.lockedInput.value") == "AI"
    secret = _target(targets, "비밀번호")
    with pytest.raises(RuntimeError, match="password_field_refused"):
        worker._type_at(page, {"x": secret["x"], "y": secret["y"], "text": "hunter2"})
    page.close()


# ★ 2026-09-29 MS 스토어 M4: 머리말이 **섀도 안의 섀도**에 있었다 — app-header(섀도) > header > nav > nav-bar(섀도) > a.
#   `zone.querySelectorAll` 은 nav-bar 안으로 못 들어가 머리 링크 「유니버설 Microsoft 웹 사이트」가 검색 결과 1위가 됐다.
NESTED_HEADER_PAGE = """
<!doctype html><html><body>
<app-header></app-header>
<main><a href="https://apps.example/detail/app1">앱 1</a><a href="https://apps.example/detail/app2">앱 2</a></main>
<script>
customElements.define('nav-bar', class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML =
    '<div><a href="https://example.com/">유니버설 웹 사이트</a></div>'; }
});
customElements.define('app-header', class extends HTMLElement {
  constructor() { super(); this.attachShadow({mode: 'open'}).innerHTML = '<header><nav><nav-bar></nav-bar></nav></header>'; }
});
</script>
</body></html>
"""


def test_a_home_link_inside_a_nested_shadow_header_is_chrome_not_a_result(browser) -> None:
    page = _page(browser, NESTED_HEADER_PAGE)
    chrome = page.evaluate(browser_module._CHROME_LINKS_JS)
    assert "https://example.com/" in chrome, chrome
    assert not any("/detail/" in href for href in chrome), "본문 결과가 머리말로 잘못 빠지면 안 된다"
    page.close()
