"""닫을 수 있는 로그인 **팝업**은 사람 문이 아니다 — 단, 닫아도 되는 때에만 (2026-10-04, 진짜 크로미움).

2026-10-03 Online-Mind2Web 재기, WebMD: 결과 화면 위에 X 가 달린 「Log In」 팝업이 뜨자 비밀번호 칸만 보고
「로그인이 필요해요」로 사람에게 넘겼다. 과제는 로그인이 필요 없었다 — 사람이라면 X 를 누르고 계속 간다.

그런데 그냥 닫기만 하면 2026-08-10 크몽을 되살린다: 「의뢰 등록」을 눌러 뜬 로그인 모달은 **진짜 문**이었다.
그래서 조건이 둘이다.

    ① 걸음 뒤 **감지**할 때만 닫는다. 사람을 기다리며 지켜보는 쪽은 손대지 않는다(사람이 연 로그인 창을 닫으면 안 된다).
    ② **같은 주소에서는 한 번만** 닫는다. 닫았는데 또 뜨면 그 일에는 로그인이 필요한 것이다 → 문.

로그인 전용 주소(`/login`)와 닫기 단추가 없는 모달, 팝업이 아닌 로그인 화면은 그대로 문이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from alture_jarvis.browser import BrowserWorker  # noqa: E402
from alture_jarvis.config import JarvisConfig  # noqa: E402
from alture_jarvis.human_gate import wall_code  # noqa: E402

_FORM = '<form><input type="email" name="id"><input type="password" name="pw"><button type="submit">Log In</button></form>'

#: WebMD 꼴 — 결과 화면 위에 X 가 달린 로그인 팝업.
POPUP_PAGE = f"""<!doctype html><html><body>
<main><h1>Results</h1><a href="/item/1">Result one</a><a href="/item/2">Result two</a></main>
<script>
function showLogin() {{
  const o = document.createElement('div'); o.id = 'overlay';
  o.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5)';
  o.innerHTML = '<div role="dialog" aria-modal="true" class="login-modal" style="margin:80px auto;width:360px;background:#fff;padding:24px">'
    + '<button type="button" aria-label="Close" class="modal-close" onclick="document.getElementById(\\'overlay\\').remove()">×</button>'
    + '<h2>Log In</h2>{_FORM}</div>';
  document.body.appendChild(o);
}}
showLogin();
</script></body></html>"""

#: 닫기 단추가 없는 모달 — 지나갈 길이 로그인뿐이다.
NO_CLOSE_PAGE = f"""<!doctype html><html><body><main><h1>Results</h1></main>
<div id="overlay" style="position:fixed;inset:0;background:rgba(0,0,0,.5)">
<div role="dialog" aria-modal="true" style="margin:80px auto;width:360px;background:#fff;padding:24px"><h2>Log In</h2>{_FORM}</div>
</div></body></html>"""

#: 팝업이 아닌 로그인 화면 — 본문이 곧 로그인 폼이다.
PLAIN_LOGIN_PAGE = f"""<!doctype html><html><body><h1>Sign in to continue</h1>{_FORM}</body></html>"""

PAGES = {
    "/results": POPUP_PAGE,
    "/other": POPUP_PAGE,
    "/login": POPUP_PAGE,
    "/noclose": NO_CLOSE_PAGE,
    "/plain": PLAIN_LOGIN_PAGE,
}


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


@pytest.fixture()
def page(browser, worker):
    opened = browser.new_page(viewport={"width": 1200, "height": 800})

    def serve(route) -> None:
        path = route.request.url.split("shop.example", 1)[-1].split("?", 1)[0]
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=PAGES.get(path, "<html><body>ok</body></html>"))

    opened.route("**/*", serve)
    worker._page = opened
    yield opened
    opened.close()


def _popup_open(page) -> bool:
    return page.locator("input[type='password']:visible").count() > 0


def test_a_closable_login_popup_is_closed_and_is_not_a_gate(worker, page) -> None:
    page.goto("https://shop.example/results")
    assert _popup_open(page)
    state = worker._blocking_wall(page, dismiss_popups=True)
    assert wall_code(state) == "", state
    assert not _popup_open(page), "닫기 단추를 눌러 팝업이 사라져 있어야 한다"
    assert page.locator("main a").count() == 2, "뒤의 결과 화면은 그대로다"


def test_the_watcher_never_closes_a_login_popup(worker, page) -> None:
    """사람을 기다리며 지켜보는 쪽(기본값)은 닫지 않는다 — 사람이 로그인하려고 연 창일 수 있다."""
    page.goto("https://shop.example/results")
    state = worker._blocking_wall(page)
    assert wall_code(state) == "login_required", state
    assert _popup_open(page)


def test_a_popup_that_comes_back_at_the_same_address_is_a_gate(worker, page) -> None:
    """크몽 꼴: 닫았는데 같은 자리에서 또 뜨면 그 일에는 로그인이 필요하다 — 두 번째는 사람에게 넘긴다."""
    page.goto("https://shop.example/results")
    assert wall_code(worker._blocking_wall(page, dismiss_popups=True)) == ""
    page.evaluate("showLogin()")
    assert _popup_open(page)
    state = worker._blocking_wall(page, dismiss_popups=True)
    assert wall_code(state) == "login_required", state
    assert _popup_open(page), "두 번째 팝업은 닫지 않고 사람에게 남긴다"


def test_a_query_change_is_still_the_same_address(worker, page) -> None:
    page.goto("https://shop.example/results?page=1")
    assert wall_code(worker._blocking_wall(page, dismiss_popups=True)) == ""
    page.goto("https://shop.example/results?page=2")
    assert wall_code(worker._blocking_wall(page, dismiss_popups=True)) == "login_required"


def test_another_address_gets_its_own_one_try(worker, page) -> None:
    page.goto("https://shop.example/results")
    assert wall_code(worker._blocking_wall(page, dismiss_popups=True)) == ""
    page.goto("https://shop.example/other")
    assert wall_code(worker._blocking_wall(page, dismiss_popups=True)) == ""
    assert not _popup_open(page)


def test_a_login_address_stays_a_gate_even_with_a_close_button(worker, page) -> None:
    page.goto("https://shop.example/login")
    state = worker._blocking_wall(page, dismiss_popups=True)
    assert wall_code(state) == "login_required", state
    assert _popup_open(page)


def test_a_modal_without_a_close_control_stays_a_gate(worker, page) -> None:
    page.goto("https://shop.example/noclose")
    state = worker._blocking_wall(page, dismiss_popups=True)
    assert wall_code(state) == "login_required", state


def test_a_plain_login_screen_stays_a_gate(worker, page) -> None:
    page.goto("https://shop.example/plain")
    state = worker._blocking_wall(page, dismiss_popups=True)
    assert wall_code(state) == "login_required", state


def test_the_public_check_is_the_one_that_dismisses() -> None:
    """배선: 걸음 뒤 감지(`blocking_wall`)만 닫기를 켜고, 감시(`_gate_snapshot`)는 켜지 않는다."""
    import inspect

    public = inspect.getsource(BrowserWorker.blocking_wall)
    watcher = inspect.getsource(BrowserWorker._gate_snapshot)
    assert "dismiss_popups=True" in public
    assert "dismiss_popups" not in watcher
