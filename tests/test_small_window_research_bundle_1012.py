"""작은 창의 조사 판에는 「찾아서 읽고 파일로」 묶음만 싣는다 — 스위치(10-13 부터 기본 켜짐) (2026-10-12).

창 32K 의 조사 판은 첫 프롬프트가 19,800토큰(창의 60%)이었고, 답 쓸 자리 8,192 를 떼면 읽은 페이지를 담을 자리가
4,800토큰쯤이었다(그날 밤 9B · 4B 의 가격 조사가 9줄 중 1~3줄). 그 판이 받는 도구는 81개인데 최근 열흘 브라우저를 쓴
649판에서 불린 호출의 83% 가 아래 스무 개였다. 재 보고 켠다 — 그래서 기본은 꺼 둔다.

지키는 것: 큰 창 · 조사 아닌 판 · 꺼 둔 PC 는 한 글자도 안 바뀐다 · 계획이 세운 행동의 손은 남긴다 · 빈 목록을 보내지 않는다.
"""

from __future__ import annotations

from alture_jarvis.config import JarvisConfig
from alture_jarvis.tool_roster import (
    _ALWAYS_ON_TOOLS,
    _SMALL_WINDOW_RESEARCH_BUNDLE,
    _small_window_research_tools,
)


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {}}}}


WEB_LIST = [_tool(name) for name in (
    "browser_open", "browser_extract", "browser_fill", "browser_screenshot", "browser_site_search", "browser_tabs",
    "local_write_document", "local_write_file", "sandbox_run", "site_list", "github_search", "ask_user", "self_check",
    "google_drive_search", "ui_find_target",
)]


def _names(tools: list[dict]) -> list[str]:
    return [tool["function"]["name"] for tool in tools]


def test_it_is_on_by_default_and_can_be_turned_off(monkeypatch) -> None:  # noqa: ANN001
    """10-12 에는 꺼 두었다(재 보고 켠다). 10-13 에 켰다 — 작은 창의 고침과 측정이 전부 켠 상태에서 이뤄졌고, 꺼 둔 채 내보내면
    작은 카드를 쓰는 사람이 한 번도 재 보지 않은 조합으로 돈다."""
    assert JarvisConfig().small_window_research_bundle is True
    monkeypatch.setenv("JARVIS_SMALL_WINDOW_RESEARCH_BUNDLE", "0")
    assert JarvisConfig.from_env().small_window_research_bundle is False
    monkeypatch.delenv("JARVIS_SMALL_WINDOW_RESEARCH_BUNDLE")
    assert JarvisConfig.from_env().small_window_research_bundle is True


def test_only_a_small_window_research_job_with_the_switch_on_is_narrowed() -> None:
    on = dict(enabled=True, compact=True, web_research=True)
    assert _small_window_research_tools(WEB_LIST, **on) is not WEB_LIST
    for change in ({"enabled": False}, {"compact": False}, {"web_research": False}):
        assert _small_window_research_tools(WEB_LIST, **{**on, **change}) is WEB_LIST, change


def test_the_bundle_keeps_find_read_write_and_the_always_on_hands() -> None:
    kept = _names(_small_window_research_tools(WEB_LIST, enabled=True, compact=True, web_research=True))
    assert kept == ["browser_open", "browser_extract", "browser_site_search", "local_write_document", "site_list",
                    "ask_user", "self_check"], "순서는 원래 목록 그대로 — 앞머리 캐시가 판마다 같아야 한다"
    assert {"ask_user", "self_check"} <= _ALWAYS_ON_TOOLS


def test_a_hand_the_plan_asked_for_is_never_dropped() -> None:
    kept = _names(_small_window_research_tools(WEB_LIST, enabled=True, compact=True, web_research=True,
                                               planned=frozenset({"browser_fill"})))
    assert "browser_fill" in kept and "browser_screenshot" not in kept


def test_an_empty_result_falls_back_to_the_whole_list() -> None:
    odd = [_tool("camera_look"), _tool("hwp_open")]
    assert _small_window_research_tools(odd, enabled=True, compact=True, web_research=True) is odd


def test_the_bundle_is_the_twenty_that_were_actually_called() -> None:
    assert len(_SMALL_WINDOW_RESEARCH_BUNDLE) == 20
    assert {"browser_open", "browser_open_result", "browser_extract", "browser_site_search", "local_write_document",
            "local_edit_spreadsheet"} <= _SMALL_WINDOW_RESEARCH_BUNDLE
    # 다른 묶음의 손 — 화면 조작(채우기 · 고르기) · 코드 · 사진은 이 묶음에 없다.
    assert not {"browser_fill", "browser_select_option", "browser_screenshot", "local_write_file", "sandbox_run"} & _SMALL_WINDOW_RESEARCH_BUNDLE
