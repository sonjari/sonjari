"""숫자 굴림 띠는 화면에 보이는 숫자로 읽는다 (2026-10-02 가격표 판 6cc1590c).

Manus 가격이 굴림 애니메이션이라 글로 읽으면 「$ 0 1 2 … 9 0 1 2 … 9 / 월」이었다. 모델은 「스크린샷으로 확인」을 네 번 말하고
못 했고, 결국 「난독화되어 읽을 수 없다」로 냈다. 실제 페이지(manus.im/pricing)를 재 보니 칸마다 0~9 가 세로로 쌓였고 바깥 칸이
`overflow: hidden` · 높이 33px — 보이는 숫자는 바깥과 겹치는 자식 하나다. 그림이 아니라 위치로 정확히 읽힌다
(그 페이지에서 $20 / $40 / $200 확인).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.browser import BrowserWorker, _fold_rollers
from alture_jarvis.config import JarvisConfig


def _column(shown: int) -> str:
    # Manus 와 같은 모양: 바깥 칸이 잘라 내고, 안쪽 열 개가 세로로 늘어서 있고, 보이는 숫자만 바깥 칸 자리에 온다.
    kids = "".join(
        f"<div style='position:absolute;top:{((d - shown) % 10) * 33}px;height:33px'>{d}</div>" for d in range(10)
    )
    return ("<span style='display:inline-block;height:33px;overflow:hidden;vertical-align:top'>"
            f"<div style='height:33px;position:relative;width:1ch'>{kids}</div></span>")


def _price(amount: str) -> str:
    return "<div class='plan'><span>$</span>" + "".join(_column(int(d)) for d in amount) + "<span>/ 월</span></div>"


PAGE = ("<html><head><title>Manus 요금제 및 가격</title></head><body><main><h1>Manus 가격 요금제</h1>"
        + _price("20") + "<p>매일 300 리프레시 크레딧 · 월 4,000 크레딧 · 일상 작업을 위한 심층 연구</p>"
        + _price("40") + "<p>월 8,000 크레딧 · 동시 작업 · 전문 웹사이트 · 정기 작업 예약</p>"
        + _price("200") + "<p>월 40,000 크레딧 · 최대 동시 작업 · 우선 지원</p></main></body></html>")


def test_fold_joins_adjacent_columns_and_marks_unknown() -> None:
    text = "$ 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 / 월 그리고 $ 0123456789 / 월"
    assert _fold_rollers(text, ["2", "0", "4"]) == "$ 20 / 월 그리고 $ 4 / 월"
    assert _fold_rollers(text, ["2"]) == "$ 2? / 월 그리고 $ ? / 월"


def test_read_and_extract_show_the_visible_prices(tmp_path: Path) -> None:
    playwright_api = pytest.importorskip("playwright.sync_api")
    worker = BrowserWorker(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o"))
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        # ★ 2026-10-22: 전체 회귀 아홉 번 중 세 번(모두 평소의 두 배인 6분짜리 판) 이 시험이 떨어졌는데, 결과 끝 몇 줄만 봐서 까닭을
        #   잃었다. CPU · 그래픽카드를 꽉 채워도 · 회귀 두 벌을 동시에 돌려도 재현이 안 됐다. 다음에 떨어지면 까닭이 남게 진단을 붙인다 —
        #   화면 프로세스가 죽었나 · 숫자 칸을 몇 개 · 무엇으로 읽었나.
        crashed: list[str] = []
        try:
            page = browser.new_page()
            page.on("crash", lambda *_: crashed.append("renderer_crashed"))
            page.set_content(PAGE)
            read = " ".join(worker._read(page, {"max_chars": 4000})["text"].split())
            extracted = " ".join(worker._extract(page, {"max_chars": 4000})["text"].split())
            try:
                from alture_jarvis.browser import _ROLLER_DIGITS_JS

                digits = page.evaluate(_ROLLER_DIGITS_JS)
            except Exception as exc:  # noqa: BLE001 — 진단용
                digits = f"evaluate 실패: {type(exc).__name__}: {exc}"[:200]
        finally:
            browser.close()
    for label, text in (("read", read), ("extract", extracted)):
        tight = text.replace(" ", "")
        why = f"{label}={text[:300]!r} · digits={digits!r} · crashed={crashed}"
        assert "$20/월" in tight and "$40/월" in tight and "$200/월" in tight, why
        assert "0123" not in tight, why


def test_a_failed_roller_read_shows_unknown_not_ten_digits() -> None:
    """칸 읽기가 예외로 실패해도 「0 1 2 … 9」 를 값처럼 넘기지 않는다 — 「?」로(2026-10-22)."""
    class _Broken:
        def evaluate(self, *_args, **_kwargs):
            raise RuntimeError("Target crashed")

    worker = BrowserWorker.__new__(BrowserWorker)
    text = "$ 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 / 월"
    assert worker._visible_rollers(_Broken(), text) == "$ ?? / 월"
