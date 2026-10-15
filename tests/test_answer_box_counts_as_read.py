"""검색 답 상자의 본문을 받아 왔으면 **읽은 것**이다 (2026-09-30 대구 날씨 판).

네이버 「대구 날씨」 첫 검색이 답 상자(현재 29.2°·맑음·체감 27.6°…)를 이미 받아 왔는데 「근거 읽기 0개」로 세어, 모델이
날씨 사이트 검색칸과 15걸음·161초를 씨름했다. 낱말이 아니라 증거(받아 온 본문)로 가른다 — 목록 요약만 온 검색은 여전히 안 센다.
"""

from __future__ import annotations

from alture_jarvis import plan
from alture_jarvis.agent import BrowserAgent

URL = "https://search.naver.com/search.naver?query=%EB%8C%80%EA%B5%AC+%EB%82%A0%EC%94%A8"
ANSWER_BOX = ("대구광역시 중구 동인동1가 기준 오늘의 날씨 맑음 현재 온도 29.2° 어제보다 4.6° 높아요 "
              "체감 27.6° 습도 38% 남동풍 1.4m/s 미세먼지 좋음")


def _search(answer_box: str) -> dict:
    return {"ok": True, "tool": "browser_search",
            "evidence": {"url": URL, "engine": "naver", "query": "대구 날씨", "answer_box": answer_box, "result_count": 8}}


def test_a_search_that_brought_back_the_answer_box_is_a_read() -> None:
    assert BrowserAgent._sources_actually_read([_search(ANSWER_BOX)]) == [URL]


def test_the_observe_requirement_is_met_by_it() -> None:
    req = plan.Requirement("observe", "근거가 되는 대상 실제로 읽기", "browser")
    steps = [_search(ANSWER_BOX)]
    ((_, ok, _saw),) = plan.check([req], sources=BrowserAgent._sources_actually_read(steps), steps=steps)
    assert ok


def test_a_search_with_only_a_result_list_is_still_not_a_read() -> None:
    """역방향 — 교보 사건(검색 목록을 연 것을 읽은 것으로 세서 2권 읽고 3권 충족)은 그대로 막는다."""
    assert BrowserAgent._sources_actually_read([_search("")]) == []
    assert BrowserAgent._sources_actually_read([_search("대구 날씨")]) == []


NEWS_LIST = ("언론사 선정 언론사가 선정한 주요기사 혹은 심층기획 기사입니다. 네이버 메인에서 보고 싶은 언론사를 구독하세요. "
             "새 창 열림 연합뉴스 새 창 열림 19시간 전 네이버뉴스 SKT·카카오·KT, 10월 중 '모두의 AI' 첫선…전국민 무료")


def test_a_news_tab_list_is_not_an_answer_box_read() -> None:
    """2026-10-02 「모두의 AI」 판: 뉴스·블로그 탭 검색 두 번이 「근거 2개 실제로 읽음」이 돼 파일 단계로 넘어갔고,
    기사를 열려던 `browser_open_result` 두 번이 `not_this_stage` 로 막혀 본문 0개로 문서를 썼다."""
    for tab in ("news", "blog"):
        step = _search(NEWS_LIST)
        step["evidence"]["tab"] = tab
        assert BrowserAgent._sources_actually_read([step]) == [], tab
    main = _search(ANSWER_BOX)
    main["evidence"]["tab"] = "all"
    assert BrowserAgent._sources_actually_read([main]) == [URL]


def test_the_browser_only_takes_an_answer_box_on_the_main_tab() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "browser.py").read_text(encoding="utf-8")
    assert '_clean_answer_box(page.evaluate(_SERP_ANSWER_BOX_JS)) if tab == "all" else ""' in source
