"""2026-11-02 대표: 「사람이 필요한 작업 · 로그인이 필요하다는데 막상 보면 없다 — 정말 필요할 때만 넘겨라」.

① 읽을 본문이 다 보이는 페이지의 캡차는 문이 아니다 — 로그인 상자에 쓰던 규칙(10-06)을 캡차에도 쓴다.
   최근 30일 봇 검사로 넘긴 5판에 hcaptcha 소개 글 · KDI 보도자료처럼 본문이 다 읽히는 페이지가 섞였다.
   거꾸로도 지킨다: 읽을 글이 없는 검사 화면 · 로그인 주소는 그대로 문이다.
② 답이 「로그인이 필요하다」고 말하는데 이 판이 로그인 문을 본 적이 없으면 표시한다(상태는 안 바꾼다).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.delegation import login_claim_without_gate, summarize_job

playwright_api = pytest.importorskip("playwright.sync_api")

from alture_jarvis.browser import BrowserWorker  # noqa: E402
from alture_jarvis.config import JarvisConfig  # noqa: E402
from alture_jarvis.human_gate import wall_code  # noqa: E402

_CAPTCHA = '<div class="captcha-widget" style="width:300px;height:78px;border:1px solid #ccc">I am human</div>'
_PARAGRAPH = ("한국개발연구원은 인공지능 도입이 일자리에 미치는 영향을 분석한 보고서를 내놓았다. 보고서는 사무직 가운데 "
              "반복 업무 비중이 높은 직무부터 변화가 빠를 것으로 보면서도, 새 업무가 함께 생겨 전체 고용의 순감소는 "
              "크지 않을 수 있다고 내다봤다. 연구진은 재교육 지원과 직무 전환 경로를 함께 설계해야 한다고 권했다. ")

#: 보도자료 — 본문이 다 보이고, 아래 댓글 · 문의 칸에 캡차 상자가 있다.
ARTICLE = f"""<!doctype html><html><body><article><h1>AI와 일자리</h1>
{''.join(f'<p>{_PARAGRAPH}</p>' for _ in range(4))}</article><section><h2>문의하기</h2>{_CAPTCHA}</section></body></html>"""

#: 진짜 검사 화면 — 읽을 글이 없다.
CHALLENGE = f"""<!doctype html><html><body><main><h1>잠시만 기다려 주세요</h1><p>사람인지 확인합니다.</p>
{_CAPTCHA}</main></body></html>"""

PAGES = {"/press/1": ARTICLE, "/check": CHALLENGE, "/login": ARTICLE}


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
        path = route.request.url.split("kdi.example", 1)[-1].split("?", 1)[0]
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=PAGES.get(path, "<html><body>ok</body></html>"))

    opened.route("**/*", serve)
    worker._page = opened
    yield opened
    opened.close()


def test_a_captcha_box_under_a_readable_article_is_not_a_gate(worker, page) -> None:
    page.goto("https://kdi.example/press/1")
    for dismiss in (True, False):
        state = worker._blocking_wall(page, dismiss_popups=dismiss)
        assert wall_code(state) == "", state


def test_a_challenge_screen_with_nothing_to_read_is_still_a_gate(worker, page) -> None:
    page.goto("https://kdi.example/check")
    assert wall_code(worker._blocking_wall(page, dismiss_popups=True)) == "bot_check"


def test_a_login_address_with_a_captcha_stays_a_gate(worker, page) -> None:
    page.goto("https://kdi.example/login")
    assert wall_code(worker._blocking_wall(page, dismiss_popups=True)) == "bot_check"


# ── ② 근거 없는 「로그인이 필요하다」 ──

_BROWSED = [{"tool": "browser_open", "arguments": {"url": "https://www.wishket.com/project/150552/"}, "ok": True}]


def test_a_login_claim_without_any_gate_is_flagged() -> None:
    answer = "위시켓 공고 중 일부는 상세 내용을 확인하기 위해 로그인이 필요하여, 공개된 개요만 정리했습니다."
    assert "로그인이 필요하여" in login_claim_without_gate(answer, _BROWSED, "위시켓 공고 찾아 줘")


def test_a_claim_backed_by_a_gate_or_a_login_page_is_not_flagged() -> None:
    answer = "이 페이지는 로그인이 필요합니다."
    gated = [*_BROWSED, {"tool": "browser_click", "human_gate": {"code": "login_required", "url": "https://x/"}}]
    assert login_claim_without_gate(answer, gated) == ""
    login_page = [{"tool": "browser_open", "arguments": {"url": "https://github.com/login?return_to=x"}}]
    assert login_claim_without_gate(answer, login_page) == ""
    blog = [{"tool": "naver_blog_write", "ok": False, "error": "naver_blog_login_required: 네이버 로그인이 필요합니다"}]
    assert login_claim_without_gate(answer, blog) == ""


def test_general_talk_and_negations_are_not_flagged() -> None:
    assert login_claim_without_gate("로그인이 필요한 곳도 다닐 수 있다.", _BROWSED) == ""
    assert login_claim_without_gate("봇 검사 · 로그인 벽에 부딪히면 알려요.", _BROWSED) == ""
    assert login_claim_without_gate("로그인 없이 로그인이 필요합니다 없이 볼 수 있다", []) == ""  # 브라우저를 안 본 판
    assert login_claim_without_gate("로그인이 필요합니다.", _BROWSED, "그냥 로그인창으로 가 줘") == ""  # 사람이 먼저 꺼냄


def test_the_summary_carries_the_flag_without_changing_status() -> None:
    job = {"id": "t", "status": "completed", "payload": {"prompt": "위시켓 공고 찾아 줘"},
           "result": {"answer": "상세 내용은 로그인이 필요합니다.", "agent_trace": {"steps": _BROWSED}}}
    summary = summarize_job(job)
    assert summary["unsupported_login_claim"]
    assert summary["status"] == "done"
    assert any("로그인 화면 · 비밀번호 칸을 본 적이 없습니다" in note for note in summary.get("review_notes") or [])


def test_odd_step_shapes_do_not_break_the_check() -> None:
    steps = [{"tool": "browser_open", "arguments": "https://x/", "evidence": None}, "이상한 줄"]
    assert "로그인이 필요합니다" in login_claim_without_gate("이 페이지는 로그인이 필요합니다.", steps)  # 터지지 않고 판정한다
