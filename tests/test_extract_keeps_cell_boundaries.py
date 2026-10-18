"""본문 추출은 칸 경계를 지킨다 (2026-10-02 사람인 여수 회계 판).

추출 스크립트는 고른 덩어리를 **복제해서** 메뉴·스크립트를 지운 뒤 글을 읽는다. 복제본은 화면에 없어 `innerText` 가
줄바꿈을 못 넣는다 — 원본 「근무형태 / 정규직 수습기간 3개월 / 우대사항 / 3건」이 「근무형태정규직 수습기간 3개월우대사항3건」으로
붙었고, 모델은 고용형태 칸에 「정규직(수습 3개월 우대)」를 적었다. 줄바꿈 없이 짠 페이지 전부가 같은 병이었다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.browser import _EXTRACT_MAIN_JS, _clean_lines

SARAMIN_LIKE = (
    "<html><body><main><h2>모집요강</h2>"
    "<dl><dt>근무형태</dt><dd>정규직 수습기간 3개월</dd></dl><dl><dt>우대사항</dt><dd>3건</dd></dl>"
    "<table><tr><th>급여</th><td>회사내규에 따름</td></tr><tr><th>마감일</th><td>2026.10.15</td></tr></table>"
    "<p>" + "회계 담당자를 모집합니다. " * 12 + "</p>"
    "<nav>메뉴 홈 채용정보 기업정보</nav></main></body></html>"
)


#: 진짜 크롬을 띄우는 데 기다릴 최대 시간(초). 넘으면 이 시험은 건너뛴다 — 시험 장치가 멈춘 것이지 코드가 틀린 게 아니다.
# ★ 2026-10-18: 열두 갈래로 동시에 돌린 전체 회귀가 이 시험에서 두 번 멈췄다(한 번은 한 시간). 헤드리스 크롬 띄우기가
#   가끔 돌아오지 않는데, Playwright 의 시작 단계(`sync_playwright()`)에는 시간 제한이 없다. 그래서 따로 된 실에서 돌리고 기다림에 끝을 둔다.
_BROWSER_WAIT_SEC = 90


def _extract(html: str) -> str:
    import threading

    playwright_api = pytest.importorskip("playwright.sync_api")
    box: dict[str, object] = {}

    def run() -> None:
        try:
            with playwright_api.sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True, timeout=60_000)
                except Exception as exc:  # noqa: BLE001
                    box["skip"] = f"chromium not installed: {exc}"
                    return
                try:
                    page = browser.new_page()
                    page.set_content(html)
                    found = page.evaluate(_EXTRACT_MAIN_JS)
                    box["text"] = _clean_lines(found["text"], 10_000)
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(_BROWSER_WAIT_SEC)
    if worker.is_alive():
        pytest.skip(f"헤드리스 크롬이 {_BROWSER_WAIT_SEC}초 안에 돌아오지 않음(시험 장치가 멈춤)")
    if "skip" in box:
        pytest.skip(str(box["skip"]))
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return str(box["text"])


def test_definition_cells_do_not_run_together() -> None:
    text = _extract(SARAMIN_LIKE)
    lines = text.splitlines()
    assert "정규직 수습기간 3개월" in lines
    assert "3개월우대" not in text and "3개월 우대" not in text
    assert "급여 회사내규에 따름" in lines, "표 한 행은 한 줄, 칸 사이는 빈칸"
    assert "메뉴 홈" not in text, "지우던 메뉴는 여전히 지운다"


def test_clean_lines_keeps_lines_and_squeezes_spaces() -> None:
    assert _clean_lines("  근무형태 \n\n  정규직   수습기간 \n") == "근무형태\n정규직 수습기간"


def test_the_extract_path_keeps_lines() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "browser.py").read_text(encoding="utf-8")
    assert 'full = _clean_lines(best.get("text"), 10_000_000)' in source
