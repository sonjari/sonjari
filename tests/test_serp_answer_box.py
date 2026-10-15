"""검색 결과 맨 위 답 상자(날씨 위젯)를 모델에게 보여 준다 (2026-09-26 고친 판 벤치 · 날씨 1/3)."""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.browser import _SERP_ANSWER_BOX_JS, _clean_answer_box


def test_a_real_weather_box_is_kept_and_squashed() -> None:
    text = "부산광역시 중구 남포동 기준\n오늘 내일\n현재 온도 20.1°  어제보다 3.5° 낮아요  흐림 체감 22.1° 습도 81%"
    kept = _clean_answer_box(text)
    assert "현재 온도 20.1°" in kept and "\n" not in kept


def test_a_box_with_only_tab_names_is_dropped() -> None:
    assert _clean_answer_box("전체 이미지 뉴스") == ""


def test_the_probe_looks_at_the_first_naver_section_not_scripts() -> None:
    """네이버 `#main_pack` 앞에는 스크립트·검색 옵션 칸이 먼저 온다(실측) — 첫 **section** 을 본다."""
    assert "el.tagName === 'SECTION'" in _SERP_ANSWER_BOX_JS


def test_the_search_evidence_carries_it() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "browser.py").read_text(encoding="utf-8")
    assert '"answer_box": answer_box' in source


def _run_probe(html: str) -> str:
    import pytest

    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium not installed: {exc}")
        try:
            page = browser.new_page()
            page.set_content(html)
            return _clean_answer_box(page.evaluate(_SERP_ANSWER_BOX_JS))
        finally:
            browser.close()


def test_an_ordinary_google_result_is_not_an_answer_box() -> None:
    """★ 2026-09-26 노트북: 구글 첫 덩어리가 보통 결과(Rome2Rio)였는데 답 상자로 집혀 길찾기 답이 「3시간 3분」이 됐다."""
    html = ("<div id='rso'><div><div>Web results</div><a href='https://www.rome2rio.com/'><h3>Busan to Yeosu Trains | 7-Day Timetable</h3>"
            "<cite>https://www.rome2rio.com › Train › Busan › Yeosu</cite></a><span>The train between Busan and Yeosu takes 3h 3m. "
            "The train runs, on average, 3 times per week.</span></div></div>")
    assert _run_probe(html) == ""


def test_a_google_weather_widget_is_still_an_answer_box() -> None:
    html = ("<div id='rso'><div><div id='wob_wc'>부산광역시 현재 온도 20°C 강수확률 10% 습도 81% 풍속 3m/s "
            "오늘 최고 23° 최저 20° 흐림</div></div></div>")
    assert "최고 23°" in _run_probe(html)


def test_naver_skips_ad_and_web_sections_and_keeps_the_widget() -> None:
    html = ("<div id='main_pack'><section class='sc_new sp_power'>파워링크 광고 부산 여수 렌터카 최저가 예약 지금 바로 확인하세요</section>"
            "<section class='sc_new cs_weather_new'>부산광역시 중구 남포동 기준 현재 온도 20.1° 어제보다 3.5° 낮아요 흐림 체감 22.1°</section></div>")
    assert "현재 온도 20.1°" in _run_probe(html)


def test_ads_spell_hints_and_video_rows_are_not_answer_boxes() -> None:
    """2026-10-02 운영 기록: 통합 검색 「답 상자」 17개 중 진짜는 6개(코스피·날씨). 나머지는 광고·맞춤법 제안·동영상이었다."""
    for text in (
        "K-Startup전남무료사무실창업공간지원 관련 광고 이 광고가 표시된 이유 등록 안내 g1company.co.kr/ 카페창업은 지원컴퍼니",
        "제안도움말 새 창 열림 어쌔신 AI 에이전트플랫폼 2026(으)로 검색하시겠습니까? 검색 결과를 더 보려면",
        "MoE CPU Offload N CPU MoE Override Tensor 동영상 7:59 Running Kimi-K2.7-Code 1.02T on a single GPU with MoE offload — full walkthrough and numbers",
        "사람들이 묻는 질문 Is Muse a personal AI agent? How do I get a free personal AI agent? What can it do",
    ):
        assert _clean_answer_box(text) == "", text
    kept = "주가지수 코스피 KOSPI 문서 저장하기 지수 6,849.57 전일대비 하락21.24(0.31%) 기간별 정보 일봉 주봉 월봉"
    assert _clean_answer_box(kept) == kept
