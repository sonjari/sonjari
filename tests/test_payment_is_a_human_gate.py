"""결제 정보를 넣는 화면은 **사람만 지날 수 있는 문**이다 (2026-09-23 제품 요청).

「결제 수단이 없는데 결제하려고 헤맨다 — 시간만 쓰고 UX 최악. 클로드는 될 때까지 하다가 안 되면 『이래서 못 했다,
이것만 해 주시면 이어가겠다』고 한다.」 온텔릭은 카드 번호를 **넣지 않는다**(비밀번호와 같은 결정). 그러니 카드 칸이
뜬 화면에서 모델이 두드릴수록 시간만 간다 — 비밀번호 칸처럼 **구조로** 알아보고 멈추고, 할 일을 말하고, 넘긴다.
열림도 같은 신호로 본다(칸이 사라지면 이어 간다). 기존 로그인·캡차 흐름(넘기기 → 지켜보기 → 이어받기)을 그대로 탄다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.human_gate import describe, is_cleared, is_human_gate, wall_code

# ── 판정 규칙 ────────────────────────────────────────────────────────────────


def test_a_payment_wall_is_a_human_gate() -> None:
    code = wall_code({"known": True, "password_fields": 0, "captcha": False, "payment": True})
    assert code == "payment_required" and is_human_gate(code)


def test_a_page_without_payment_fields_is_not_a_gate() -> None:
    """★ 좋은 표본."""
    assert wall_code({"known": True, "password_fields": 0, "captcha": False, "payment": False}) == ""


def test_the_person_is_told_what_to_do_and_that_we_continue() -> None:
    text = describe("payment_required", "https://shop.example/checkout", 4, 4)
    assert "카드 번호" in text and "넣지 않아요" in text
    assert "결제 수단이 없으면 등록" in text
    assert "이어서" in text, "하고 나면 어떻게 되는지가 있어야 한다"
    assert "먼저 여쭤" in text, "마지막 결제는 여전히 승인을 거친다고 말해야 한다"


def test_the_gate_opens_when_the_payment_fields_are_gone() -> None:
    from alture_jarvis.site_atlas import registrable

    gate = {"code": "payment_required", "url": "https://shop.example/checkout", "hosts": [registrable("shop.example")]}
    still = {"known": True, "url": "https://shop.example/checkout", "password_fields": 0, "captcha": False, "payment": True}
    done = {"known": True, "url": "https://shop.example/checkout", "password_fields": 0, "captcha": False, "payment": False}
    assert not is_cleared(gate, still)
    assert is_cleared(gate, done)


# ── 진짜 크롬에서 ────────────────────────────────────────────────────────────

CHECKOUT = """<html><body><h1>Checkout</h1><form>
<input name="email"><input autocomplete="cc-number" name="x1" placeholder="Card">
<input autocomplete="cc-exp" name="x2"><input autocomplete="cc-csc" name="x3"><button>Pay</button></form></body></html>"""
PRODUCT_WITH_PAY_BUTTON = """<html><body><h1>무선 마우스</h1><p>25,900원</p>
<iframe src="https://pay.naver.com/o/button" style="width:120px;height:40px"></iframe>
<button>장바구니</button></body></html>"""
SIGNUP_FORM = """<html><body><form><input name="name"><input name="address"><input name="phone">
<input name="zip"><textarea name="memo"></textarea><button>저장</button></form></body></html>"""


@pytest.fixture(scope="module")
def chrome():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True, channel="chrome")
        except Exception as exc:  # pragma: no cover - 크롬이 없는 PC
            pytest.skip(f"chrome unavailable: {exc}")
        yield browser
        browser.close()


def _wall(tmp_path: Path, chrome, html: str) -> dict:
    from alture_jarvis.browser import BrowserWorker
    from alture_jarvis.config import JarvisConfig

    context = chrome.new_context()
    page = context.new_page()
    page.set_content(html)
    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d"))
    worker._context, worker._page = context, page
    try:
        return worker._blocking_wall()
    finally:
        context.close()


def test_a_real_checkout_page_is_seen_as_a_payment_wall(tmp_path: Path, chrome) -> None:
    wall = _wall(tmp_path, chrome, CHECKOUT)
    assert wall["payment"] is True and wall_code(wall) == "payment_required"


def test_a_product_page_with_a_small_pay_button_is_not_a_wall(tmp_path: Path, chrome) -> None:
    """★ 좋은 표본 — 상품 페이지의 작은 간편결제 단추 iframe 은 문이 아니다(그걸 막으면 쇼핑 조사가 전부 멈춘다)."""
    wall = _wall(tmp_path, chrome, PRODUCT_WITH_PAY_BUTTON)
    assert wall["payment"] is False and wall_code(wall) == ""


def test_an_ordinary_form_is_not_a_payment_wall(tmp_path: Path, chrome) -> None:
    """★ 좋은 표본 — 주소·전화 칸만 있는 폼은 사람 문이 아니다."""
    wall = _wall(tmp_path, chrome, SIGNUP_FORM)
    assert wall["payment"] is False and wall_code(wall) == ""
