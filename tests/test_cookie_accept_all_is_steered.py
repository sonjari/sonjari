"""쿠키·동의 창의 「모두 허용」을 대신 누르지 않는다 (2026-10-02 공개 전 필수 ②).

가격 비교 판에서 모델이 Perplexity 쿠키 창의 「모두 허용」을 browser_click 으로 눌렀다 — 대표의 실제 크롬에서 광고·분석 쿠키까지
동의한 것이다. 같은 창의 거부·필수만을 대신 누르고, 없으면 닫기, 그것도 없으면 아무것도 안 누른다. 사람이 승인한 클릭은 손대지 않는다.
"""

from __future__ import annotations

from typing import Any

from alture_jarvis import browser as browser_mod


class _Locator:
    def __init__(self, page: "_Page", label: str) -> None:
        self.page, self.label = page, label

    def get_attribute(self, name: str) -> str | None:
        return None

    def inner_text(self, timeout: int = 0) -> str:
        return self.label

    def evaluate(self, script: str, arg: Any = None) -> Any:
        if "tagName" in script:
            return "button"
        return self.page.banner

    @property
    def first(self) -> "_Locator":
        return self

    def click(self, timeout: int = 0) -> None:
        self.page.clicked.append(self.label)


class _Page:
    url = "https://www.perplexity.ai/hub/pricing"

    def __init__(self, banner: dict[str, Any]) -> None:
        self.banner = banner
        self.clicked: list[str] = []

    def locator(self, selector: str) -> _Locator:
        return _Locator(self, "steered:" + selector)

    def evaluate(self, script: str, arg: Any = None) -> None:
        return None

    def wait_for_timeout(self, ms: int) -> None:
        return None

    def is_closed(self) -> bool:
        return False

    def title(self) -> str:
        return "Perplexity"


def _worker(page: _Page, label: str) -> Any:
    worker = browser_mod.BrowserWorker.__new__(browser_mod.BrowserWorker)
    worker._page = page
    worker._last_dialog = None
    worker._ref_locator = lambda p, ref: _Locator(page, label)
    worker.config = type("C", (), {"browser_read_only": False})()
    return worker


def test_accept_all_in_a_cookie_banner_presses_reject_instead() -> None:
    page = _Page({"consent": True, "kind": "decline", "label": "필수 쿠키만"})
    result = _worker(page, "모두 허용")._click(page, {"ref": "j3"})
    assert result["consent_steered"] == "decline" and result["pressed"] == "필수 쿠키만"
    assert page.clicked == ['steered:[data-jarvis-consent="1"]']


def test_no_reject_button_means_nothing_is_pressed() -> None:
    page = _Page({"consent": True, "kind": "none", "label": ""})
    result = _worker(page, "Accept all")._click(page, {"ref": "j3"})
    assert result["action"] == "not_clicked" and page.clicked == []


def test_outside_a_consent_box_the_click_is_left_alone(monkeypatch) -> None:
    page = _Page({"consent": False})
    worker = _worker(page, "동의")
    assert worker._steer_consent_click(page, _Locator(page, "동의"), "동의") is None


def test_the_patterns() -> None:
    hit = browser_mod._CONSENT_ACCEPT.search
    for label in ("모두 허용", "전체 동의", "Accept all", "Accept cookies", "동의"):
        assert hit(label), label
    for label in ("모두 거부", "설정", "다음", "로그인", "동의하지 않음"):
        assert not hit(label), label
