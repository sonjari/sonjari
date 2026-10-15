"""읽을 본문이 있는 페이지의 로그인 상자는 사람 문이 아니다 (2026-10-06 국내 조사 판, 진짜 크로미움).

한국클라우드신문 기사는 로그인 없이 열리고 본문이 다 읽힌다. 그런데 머리말에 아이디·비밀번호 상자가 있어
`login_required` 로 사람에게 넘겼고, 판은 12분을 기다렸다. 머리말 로그인 상자와 로그인 화면은 폼만 보면 같은
모양이다 — 가르는 것은 폼 **바깥의 글**이다. 로그인 화면에는 읽을 글이 없고, 기사에는 긴 문단이 있다.

거꾸로도 지킨다: 메뉴·바닥글만 잔뜩 있는 로그인 화면, 로그인 주소(`/login`)의 글 많은 화면, 글이 숨겨져 있는
화면은 그대로 문이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

from alture_jarvis.browser import BrowserWorker  # noqa: E402
from alture_jarvis.config import JarvisConfig  # noqa: E402
from alture_jarvis.human_gate import wall_code  # noqa: E402

_LOGIN = ('<form action="/member/auth"><input type="text" name="id" placeholder="아이디">'
          '<input type="password" name="pw" placeholder="비밀번호"><button type="submit">로그인</button></form>')
_PARAGRAPH = ("클라우드 사업자들이 에이전트가 직접 일하는 가상 PC 를 잇달아 내놓고 있다. 사용자가 맡긴 일을 에이전트가 "
              "따로 마련된 컴퓨터에서 이어 가고, 사람은 결과만 확인하는 방식이다. 업계는 이 방식이 사무 자동화의 "
              "다음 단계가 될 것으로 보고 있지만, 비용과 보안을 둘러싼 물음은 아직 남아 있다. ")
_MENU = "".join(f'<a href="/s{i}">섹션 {i} 바로가기</a> ' for i in range(120))

#: 기사 — 머리말에 로그인 상자, 본문에 긴 문단 넷.
ARTICLE = f"""<!doctype html><html><body>
<header><a href="/">신문</a>{_LOGIN}</header>
<nav>{_MENU}</nav>
<article><h1>에이전트용 가상 PC 가 온다</h1>{''.join(f'<p>{_PARAGRAPH}</p>' for _ in range(4))}</article>
<footer>회사 소개 · 이용약관 · 개인정보처리방침</footer></body></html>"""

#: 로그인 화면 — 메뉴와 바닥글은 길지만(짧은 조각들) 읽을 문단은 없다.
WALL_WITH_CHROME = f"""<!doctype html><html><body>
<nav>{_MENU}</nav><main><h1>로그인 후 이용할 수 있습니다</h1>{_LOGIN}</main>
<footer>{_MENU}</footer></body></html>"""

#: 본문이 있긴 한데 숨겨져 있다(로그인해야 보이는 글).
HIDDEN_ARTICLE = f"""<!doctype html><html><body>
<main><h1>회원 전용 글입니다</h1>{_LOGIN}</main>
<article style="display:none">{''.join(f'<p>{_PARAGRAPH}</p>' for _ in range(4))}</article></body></html>"""

#: 글이 폼 **안**에 있다(약관을 읽고 로그인하라는 화면) — 폼 바깥에는 읽을 것이 없다.
PROSE_INSIDE_THE_FORM = f"""<!doctype html><html><body><main><h1>로그인</h1>
<form action="/member/auth"><p>{_PARAGRAPH * 4}</p><input type="text" name="id">
<input type="password" name="pw"><button type="submit">로그인</button></form></main></body></html>"""

PAGES = {"/news/article": ARTICLE, "/login": ARTICLE, "/wall": WALL_WITH_CHROME, "/hidden": HIDDEN_ARTICLE,
         "/terms": PROSE_INSIDE_THE_FORM}


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
        path = route.request.url.split("news.example", 1)[-1].split("?", 1)[0]
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=PAGES.get(path, "<html><body>ok</body></html>"))

    opened.route("**/*", serve)
    worker._page = opened
    yield opened
    opened.close()


def test_an_article_with_a_login_box_in_its_header_is_not_a_gate(worker, page) -> None:
    page.goto("https://news.example/news/article")
    assert page.locator("input[type='password']:visible").count() == 1

    for dismiss in (True, False):  # 걸음 뒤의 감지와, 사람을 기다리며 지켜보는 쪽 — 둘 다 같은 답
        state = worker._blocking_wall(page, dismiss_popups=dismiss)
        assert wall_code(state) == "", state


def test_a_login_screen_with_long_menus_is_still_a_gate(worker, page) -> None:
    """메뉴·바닥글 링크는 합치면 길어도 한 조각이 짧다 — 읽을 글로 세지 않는다."""
    page.goto("https://news.example/wall")
    assert wall_code(worker._blocking_wall(page, dismiss_popups=True)) == "login_required"


def test_a_login_address_stays_a_gate_even_when_the_page_has_prose(worker, page) -> None:
    page.goto("https://news.example/login")
    assert wall_code(worker._blocking_wall(page, dismiss_popups=True)) == "login_required"


def test_prose_that_is_hidden_does_not_open_the_gate(worker, page) -> None:
    page.goto("https://news.example/hidden")
    assert wall_code(worker._blocking_wall(page, dismiss_popups=True)) == "login_required"


def test_prose_inside_the_login_form_does_not_open_the_gate(worker, page) -> None:
    page.goto("https://news.example/terms")
    assert wall_code(worker._blocking_wall(page, dismiss_popups=True)) == "login_required"
