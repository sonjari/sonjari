"""검색 걸음도 출처다 (2026-11-20 맥 0.4.49 날씨 판 190f491c).

검색 결과 맨 위 답 상자로 답한 판의 sources 가 0 이었다 — 검색 걸음의 source_id 가 「q:서울 날씨」(검색어)라
http 가 아니어서 버려졌다. 그 걸음이 실제로 본 화면 주소(evidence.url)를 출처로 쓴다.
"""
from __future__ import annotations

from typing import Any

from alture_jarvis.delegation import summarize_job

NAVER = "https://search.naver.com/search.naver?query=%EC%84%9C%EC%9A%B8+%EB%82%A0%EC%94%A8"


def _job(steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": "j1", "status": "completed", "payload": {"origin": "mcp", "prompt": "서울 날씨"},
            "result": {"answer": "최저 -3°", "completion_state": "complete",
                       "agent_trace": {"steps": steps, "tool_numbers": [], "tool_numbers_body": []}}}


def _search(url: str = NAVER) -> dict[str, Any]:
    return {"tool": "browser_search", "ok": True,
            "evidence": {"action": "searched", "engine": "naver", "url": url},
            "evidence_record": {"effect": "read_web", "source_id": "q:서울 날씨", "type": "listing"}}


def test_search_step_source_is_the_results_page() -> None:
    assert summarize_job(_job([_search()]))["sources"] == [NAVER]


def test_search_step_without_a_url_adds_nothing() -> None:
    assert summarize_job(_job([_search(url="")]))["sources"] == []


def test_query_text_never_leaks_as_a_source() -> None:
    assert all(s.startswith("http") for s in summarize_job(_job([_search()]))["sources"])


def test_opened_pages_come_before_search_pages_under_the_cap() -> None:
    """출처는 20개까지 — 검색 화면이 연 페이지를 밀어내면 안 된다(운영 대조: 6,250판 중 12판)."""
    opened = [{"tool": "browser_snapshot", "ok": True, "evidence": {"url": f"https://example.com/p{i}"},
               "evidence_record": {"effect": "read_web", "source_id": f"https://example.com/p{i}"}} for i in range(20)]
    steps = [_search(f"https://www.google.com/search?q=a{i}") for i in range(3)] + opened
    sources = summarize_job(_job(steps))["sources"]
    assert sources == [f"https://example.com/p{i}" for i in range(20)]
