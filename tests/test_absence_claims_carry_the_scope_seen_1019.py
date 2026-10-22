"""「없다 · 아직 없다」는 **본 범위 안의 말**이다 — 범위를 안 적은 단정에는 걸음 기록의 범위를 붙인다 (2026-10-19 판 1bc39285).

「Show GN에 AI · 로컬 모델 글이 많던데 알아봐 줘」에 손자리는 `news.hada.io/show` 첫 화면을 읽고 거기서 글 몇 개를 골라 연 뒤
「Show GN에서 "로컬 모델로 일하는 에이전트"는 아직 없었습니다」로 끝맺었다. 범위를 붙이는 옛 자리(`_list_scope_fact`)는
「목록 · 검색 결과」 낱말과 **검색 도구**의 검색어만 봐서 아무것도 안 붙였다.

지키는 약속(`absence_scope.absence_scope_note` ← `agent.BrowserAgent._list_scope_fact`):
- 「아직 없다 · 하나도 없다 · 존재하지 않는다」를 범위 없이 단정했고, 그 판이 목록(검색 · 링크를 모아 글을 고른 화면 · 쪽 넘김)을
  봤으면 「목록 화면 N곳 · 거기서 연 글 M개」를 붙인다.
- 목록을 안 본 판 · 목록 끝까지 본 판 · 검색이 0건만 준 판 · 답이 범위를 스스로 적은 판 · 따옴표 안의 옮긴 말 · 내 PC 만 본 판은
  붙이지 않는다.
- 검색어 범위가 붙던 옛 판(「목록에 … 없었다」 + 검색 도구)은 예전 문구 그대로다.
(운영 답 3,587개 옛 · 새 대조: 옛 68 그대로 · 바뀜 0 · 잃음 0, 새로 붙음 11 — 맞게 붙음 8 · 경계 1 · 헛붙임 2 「종가는 아직 없습니다」 ·
 「극단어 하나도 없습니다」. 헛붙임도 참인 범위 한 줄이다.)
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.absence_scope import absence_scope_note, denied_sentence
from alture_jarvis.agent import BrowserAgent

_SHOW = "https://news.hada.io/show"
_TITLE = "GeekNews Show - 새로운 서비스와 오픈소스 알리기"
ANSWER = (
    "사용자님, Show GN에서 AI·로컬 모델 관련 글 4개를 직접 열어 확인했습니다.\n\n"
    "## 1. memopro\n메모리보다 큰 LLM 을 돌리는 라이브러리\n\n"
    "**결론: 전부 다릅니다.**\n\n"
    "Show GN에서 \"로컬 모델로 일하는 에이전트\"는 아직 없었습니다. 손자리가 그 자리에 있습니다."
)


def _step(tool: str, url: str, title: str = "", **extra: Any) -> dict[str, Any]:
    evidence: dict[str, Any] = {"url": url, **extra}
    if title:
        evidence["title"] = title
    return {"tool": tool, "ok": True, "evidence": evidence}


def _topic(n: int) -> str:
    return f"https://news.hada.io/topic?id={35570 + n}"


def _link(url: str) -> str:
    return str({"url": url, "domain": "news.hada.io", "text": "글 제목"})[:80]


def _geeknews_steps() -> list[dict[str, Any]]:
    """1bc39285 의 걸음 모양 — 목록을 열어 읽고, 글 이름마다 링크를 받아 둘을 열어 읽었다."""
    steps = [_step("browser_open", "https://news.hada.io/", "GeekNews"),
             _step("browser_open", _SHOW, _TITLE), _step("browser_extract", _SHOW, _TITLE, link_ratio=78, char_count=4174)]
    steps += [_step("browser_links", _SHOW, _TITLE, links=[_link(_topic(n))]) for n in (14, 48, 5, 4)]
    for n in (14, 5):
        steps += [_step("browser_open", _topic(n), f"글 {n}"), _step("browser_extract", _topic(n), f"글 {n}", link_ratio=14)]
    return steps


def test_the_geeknews_absence_claim_gets_the_scope_it_was_drawn_from() -> None:
    steps = _geeknews_steps()
    note = BrowserAgent._list_scope_fact(ANSWER, steps)
    assert "아직 없다" in note and "본 범위 안의 말" in note
    assert "목록 화면 1곳(news.hada.io/show)" in note
    assert "거기서 연 글 2개" in note, note        # 목록 화면은 「연 글」로 세지 않는다
    assert denied_sentence(ANSWER).startswith("Show GN에서")


def test_no_note_when_the_answer_states_its_own_scope() -> None:
    steps = _geeknews_steps()
    scoped = "Show GN 첫 화면에서 연 글 2개 중에는 「로컬 모델로 일하는 에이전트」가 아직 없었습니다."
    assert BrowserAgent._list_scope_fact(scoped, steps) == ""
    assert BrowserAgent._list_scope_fact("읽은 범위 안에서는 그런 글이 아직 없었습니다.", steps) == ""


def test_no_note_without_any_list_seen() -> None:
    """글 한 장만 읽고 「무료 요금제는 아직 없습니다」 — 그 글이 범위의 전부다."""
    steps = [_step("browser_open", "https://vendor.example/pricing", "요금"),
             _step("browser_extract", "https://vendor.example/pricing", "요금")]
    assert BrowserAgent._list_scope_fact("무료 요금제는 아직 없습니다.", steps) == ""


def test_no_note_after_the_list_end_or_on_a_zero_result_search() -> None:
    ended = [*_geeknews_steps(), {"tool": "browser_load_more", "ok": True, "evidence": {"grew": False}}]
    assert BrowserAgent._list_scope_fact(ANSWER, ended) == ""
    zero = [{"tool": "browser_site_search", "ok": True, "arguments": {"query": "로컬 에이전트"},
             "evidence": {"query": "로컬 에이전트", "result_count": 0}}]
    assert absence_scope_note("그런 서비스는 아직 없습니다.", zero, []) == ""


def test_no_note_on_a_local_directory_listing() -> None:
    steps = [{"tool": "local_list_dir", "ok": True, "evidence": {"path": "C:/work", "count": 3}}]
    assert BrowserAgent._list_scope_fact("그 폴더에 PDF 파일이 하나도 없습니다.", steps) == ""
    assert BrowserAgent._list_scope_fact("`test_api.py` 는 저장소에 존재하지 않습니다.", steps) == ""


def test_words_quoted_from_the_page_are_not_our_claim() -> None:
    steps = _geeknews_steps()
    assert denied_sentence("세 서비스 모두 '아직 작성된 리뷰가 없어요'로 나타났습니다.") == ""
    assert denied_sentence("스토어 화면에 \"아직 리뷰가 없습니다.\" 라고 떠 있습니다.") == ""
    assert BrowserAgent._list_scope_fact("평점 칸에는 「아직 리뷰가 없습니다」가 떠 있었습니다.", steps) == ""


def test_name_form_headings_are_not_conclusions() -> None:
    assert denied_sentence("### 3) 성능 수치 — 자체 발표 기준, 아직 검증 없음") == ""


def test_a_search_scope_answer_keeps_the_old_wording() -> None:
    """10-02 K-Startup 꼴 — 검색 도구 범위가 있으면 예전 문구 그대로(`test_division_kstartup_fixes`)."""
    steps = [{"tool": "browser_site_search", "ok": True, "arguments": {"query": "AI 창업"},
              "evidence": {"query": "AI 창업", "result_count": 9}}]
    note = BrowserAgent._list_scope_fact("목록에 AI 제목 공고가 없었습니다.", steps)
    assert "손자리가 본 목록 범위는 검색 「AI 창업」 9건" in note


def test_a_category_claim_drawn_from_searches_gets_the_queries() -> None:
    steps = [{"tool": "browser_search", "ok": True, "arguments": {"query": "국내 무료 AI 에이전트"},
              "evidence": {"query": "국내 무료 AI 에이전트", "result_count": 12, "url": "https://search.naver.com/search.naver?query=x"}},
             _step("browser_extract", "https://blog.example/post/1", "글 하나")]
    note = BrowserAgent._list_scope_fact("완전 공짜 + 이 수준은 국내에 아직 없어요.", steps)
    assert "「국내 무료 AI 에이전트」 12건" in note and "거기서 연 글 1개" in note


def test_an_english_claim_gets_an_english_note() -> None:
    steps = _geeknews_steps()
    note = BrowserAgent._list_scope_fact("There is still no agent that works with local models on Show GN.", steps)
    assert note.startswith("\n\nℹ Tool log:") and "1 list screen(s)" in note
    assert BrowserAgent._list_scope_fact("Apple's page doesn't list it; I read 2 pages.", steps) == ""


def test_our_own_scope_lines_do_not_set_it_off_again() -> None:
    """다음 턴에는 우리가 붙인 줄도 답 글에 남는다(`memory.without_our_tail` 은 ⚠ 만 뗀다) — 그 줄이 또 걸리면 안 된다."""
    steps = _geeknews_steps()
    once = ANSWER + BrowserAgent._list_scope_fact(ANSWER, steps)
    tail = once[len(ANSWER):]
    assert tail and denied_sentence(tail) == ""
