"""분업 실험 K-Startup 판(클로드 → 손자리 2186746e · 33540444)에서 나온 셋 (2026-10-02 저녁).

1. 보고 범위 — 「AI 창업지원사업」(9건) 등 검색 첫 화면만 보고 「목록에 AI·소프트웨어 제목 공고가 없었다」고 단정했다.
   같은 시각 클로드 혼자 판은 「AI 올라운더 창업가육성과정 8기」를 찾았다. 클로드는 손자리 말을 믿고 기준을 풀었다.
2. 검색어 — 사이트 검색칸이 낱말을 다 맞춰야 나오는 곳이라 「AI 창업지원사업」에 AI 제목 공고가 하나도 안 걸렸다.
3. 대기 비용 — 클로드가 상태를 50초씩 18번 물으며 매번 대화 5~6만 토큰을 다시 읽었다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis import browser as browser_mod
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.delegation import CLAUDE_CODE_MAX_WAIT_SEC, MAX_WAIT_SEC, STATUS_TOOL, is_claude_code

ANSWER = ("## 찾지 못한 것\n1. **AI/소프트웨어 관련성이 명확한 공고 5개**: 목록에 \"AI\" 또는 \"소프트웨어\"가 제목이나 분야로 "
          "명시된 공고가 없었습니다.")


def _search(query: str, count: int) -> dict[str, Any]:
    return {"tool": "browser_site_search", "ok": True, "arguments": {"query": query},
            "evidence": {"query": query, "result_count": count}}


def test_an_absence_claim_gets_the_scope_that_was_actually_seen() -> None:
    steps = [_search("AI 창업지원사업", 9), _search("소프트웨어 창업지원사업", 9), _search("창업", 15)]
    note = BrowserAgent._list_scope_fact(ANSWER, steps)
    assert "「AI 창업지원사업」 9건" in note and "「창업」 15건" in note
    assert "이 범위 안의 말" in note


def test_no_scope_line_without_an_absence_claim_or_after_the_list_end() -> None:
    steps = [_search("AI", 15)]
    assert BrowserAgent._list_scope_fact("AI 올라운더 등 5개를 찾았습니다.", steps) == ""
    ended = [*steps, {"tool": "browser_load_more", "ok": True, "evidence": {"grew": False}}]
    assert BrowserAgent._list_scope_fact(ANSWER, ended) == "", "목록 끝까지 본 판은 범위가 전부다"


#: 다시 찾기는 검색칸의 버릇을 확인한 사이트에서만 켜진다(2026-10-12 · `search_boxes`). 이 실험의 그 사이트.
KSTARTUP = "www.k-startup.go.kr"


def _worker(retry_rows: list[dict[str, Any]]) -> Any:
    worker = browser_mod.BrowserWorker.__new__(browser_mod.BrowserWorker)
    worker.calls = []

    def site_search(_page: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        worker.calls.append(arguments["query"])
        return {"results": retry_rows}

    worker._site_search = site_search
    return worker


def test_a_multi_word_search_that_missed_its_head_word_is_retried_with_it() -> None:
    first = [{"title": "2026 SVC Seoul 멤버십(확장형)"}, {"title": "Startup Korea Special Visa"}]
    again = [{"title": "AI 올라운더(기획,개발,마케팅) 창업가육성과정 8기 모집"}]
    worker = _worker(again)
    out = worker._retry_with_head_word(None, "AI 창업지원사업", first, 20, host=KSTARTUP)
    assert worker.calls == ["AI"]
    assert out == ("AI", again)
    assert "「AI」 하나로 다시 찾았다" in worker._head_retry_note


def test_no_retry_when_the_head_word_is_already_there_or_the_query_is_one_word() -> None:
    worker = _worker([])
    assert worker._retry_with_head_word(None, "AI 창업지원사업", [{"title": "AI 올라운더 8기"}], 20, host=KSTARTUP) is None
    assert worker._retry_with_head_word(None, "AI", [{"title": "SVC Seoul"}], 20, host=KSTARTUP) is None
    assert worker._retry_with_head_word(None, "AI 창업", [], 20, host=KSTARTUP) is None
    assert worker.calls == []


def test_claude_code_waits_longer_per_status_call() -> None:
    assert is_claude_code("Claude Code") and is_claude_code("claude-code")
    assert not is_claude_code("codex-mcp-client") and not is_claude_code("")
    assert STATUS_TOOL["parameters"]["properties"]["wait_sec"]["maximum"] == CLAUDE_CODE_MAX_WAIT_SEC > MAX_WAIT_SEC
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "mcp_server.py").read_text(encoding="utf-8")
    assert "ceiling = CLAUDE_CODE_MAX_WAIT_SEC if is_claude_code(caller) else MAX_WAIT_SEC" in source
