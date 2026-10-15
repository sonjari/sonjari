"""상태 알약이 사이트 오른쪽 위를 덮지 않는다 (2026-10-01 네이버 서치어드바이저).

손자리가 페이지 오른쪽 위에 띄우는 「Sonjari · 작업 단계 완료」 알약이 **네이버 로그인 버튼을
그대로 덮었다.** 사용자님 화면 캡처로 드러났다. 오른쪽 위는 사이트 대부분이 로그인·계정 버튼을 두는
자리라, 사람이 그 버튼을 보려면 알약이 비켜야 한다.

모델 쪽은 원래 문제가 없었다 — 스크린샷 때는 오버레이를 숨기고, 알약은 `pointer-events:none`
이라 클릭이 통과한다. 이 시험은 **사람 쪽**을 잰다:

  1. 마우스가 알약 근처로 오면 알약이 사라진다(불투명도 0).
  2. 마우스가 멀어지면 돌아온다.
  3. 알약 밑의 버튼을 누르면 그 버튼이 받는다(알약이 클릭을 먹지 않는다).

실제 크로미움에서 잰다. pytest 안의 sync playwright 는 앞 시험의 이벤트 루프에 오염되므로
(tests/result_list_bench.py 머리말) 자식 프로세스에서 돌리고 JSON 만 받는다.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import textwrap

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"

_CHILD = textwrap.dedent(
    r"""
    import json, sys, types
    sys.path.insert(0, sys.argv[1])
    from playwright.sync_api import sync_playwright
    from alture_jarvis.browser import BrowserWorker

    stub = types.SimpleNamespace(config=types.SimpleNamespace(browser_visual_overlay=True))
    html = '''<html><body style="margin:0;height:900px">
      <button id="login" style="position:fixed;top:12px;right:14px;width:120px;height:34px"
              onclick="window.__clicked=(window.__clicked||0)+1">로그인</button>
    </body></html>'''
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1000, "height": 700})
        page.set_content(html)
        BrowserWorker._show_visual(stub, page, "작업 단계 완료", completed=True)
        badge = page.locator("#__alture_jarvis_visual [data-jarvis-part=badge]")
        box = badge.bounding_box()
        login = page.locator("#login").bounding_box()
        out["overlaps"] = not (box["x"] + box["width"] < login["x"] or login["x"] + login["width"] < box["x"]
                               or box["y"] + box["height"] < login["y"] or login["y"] + login["height"] < box["y"])
        page.mouse.move(100, 600)
        page.wait_for_timeout(50)
        out["far"] = badge.evaluate("el => el.style.opacity")
        page.mouse.move(login["x"] + login["width"] / 2, login["y"] + login["height"] / 2)
        page.wait_for_timeout(50)
        out["near"] = badge.evaluate("el => el.style.opacity")
        page.mouse.down(); page.mouse.up()
        out["clicked"] = page.evaluate("window.__clicked || 0")
        page.mouse.move(100, 600)
        page.wait_for_timeout(50)
        out["back"] = badge.evaluate("el => el.style.opacity")
        # 같은 페이지에서 다시 그려도 리스너가 겹쳐 쌓이지 않는다(알약은 하나).
        BrowserWorker._show_visual(stub, page, "다음 단계")
        out["badges"] = page.locator("[data-jarvis-part=badge]").count()
        b.close()
    print(json.dumps(out))
    """
)


@pytest.fixture(scope="module")
def measured() -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, str(_SRC)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if proc.returncode != 0:
        if "Executable doesn't exist" in proc.stderr or "playwright install" in proc.stderr:
            pytest.skip("크로미움이 설치돼 있지 않다: " + proc.stderr.strip().splitlines()[-1])
        raise AssertionError(proc.stderr[-2000:])
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_fixture_really_puts_the_badge_over_a_login_button(measured: dict) -> None:
    # 시험이 재는 상황이 실제로 재현됐는지 먼저 본다 — 겹치지 않으면 아래 시험들은 아무것도 안 잰다.
    assert measured["overlaps"] is True


def test_the_badge_steps_aside_when_the_mouse_comes_near(measured: dict) -> None:
    assert measured["far"] == ""
    assert measured["near"] == "0"
    assert measured["back"] == ""


def test_the_button_under_the_badge_still_gets_the_click(measured: dict) -> None:
    assert measured["clicked"] == 1


def test_redrawing_keeps_one_badge(measured: dict) -> None:
    assert measured["badges"] == 1
