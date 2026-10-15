"""말하지 않은 서비스에는 올리지 않는다 (2026-09-18).

섀도 DOM 벤치 ms_detail: 「MS 스토어에서 ChatGPT 앱의 **게시자**와 별점을 알려줘」 → 모델이 답을 다 만들고
`naver_blog_prepare_post` → `naver_blog_fill_editor` 를 불렀다(로그인이 없어 막혔을 뿐). 요청에 블로그가 없었다.
"""

from __future__ import annotations

from alture_jarvis import agent as agent_module
from alture_jarvis.agent import _platform_scoped_tool_definitions, _platform_write_unrequested


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}


def test_the_ms_store_question_cannot_reach_the_blog() -> None:
    asked = "마이크로소프트 스토어(apps.microsoft.com)에서 ChatGPT 앱을 찾아서 게시자와 별점을 알려줘"
    for name in ("naver_blog_prepare_post", "naver_blog_fill_editor", "naver_blog_publish"):
        assert _platform_write_unrequested(name, asked) == "네이버 블로그"
    kept = [t["function"]["name"] for t in _platform_scoped_tool_definitions(
        [_tool("browser_extract"), _tool("naver_blog_prepare_post"), _tool("google_gmail_send"), _tool("google_calendar_list")], asked)]
    assert kept == ["browser_extract", "google_calendar_list"], "읽기 도구·조회는 그대로, 올리는 손만 빠진다"


def test_asking_for_the_blog_still_opens_it_including_a_follow_up_turn() -> None:
    assert _platform_write_unrequested("naver_blog_prepare_post", "이 내용 네이버 블로그에 임시저장해줘") == ""
    # 이번 말엔 서비스가 없어도 직전 사용자 발화에 있으면 연다(판정 글에 최근 발화를 붙인다).
    assert _platform_write_unrequested("naver_blog_fill_editor", "그거 올려줘 아까 블로그 글 초안 써줘") == ""


def test_mail_and_calendar_writes_follow_the_same_rule() -> None:
    assert _platform_write_unrequested("google_gmail_send", "공고 3개 찾아서 표로 정리해줘") == "메일 보내기"
    assert _platform_write_unrequested("google_gmail_send", "정리해서 김 팀장한테 메일로 보내줘") == ""
    assert _platform_write_unrequested("google_calendar_create", "마감일 알려줘") == "캘린더 일정"
    assert _platform_write_unrequested("google_calendar_create", "마감일을 내 캘린더에 넣어줘") == ""
    assert _platform_write_unrequested("browser_click", "아무 말") == ""


def test_the_agent_filters_the_menu_and_refuses_the_call() -> None:
    source = open(agent_module.__file__, encoding="utf-8").read()
    assert "_platform_scoped_tool_definitions(\n                    available_model_tools, platform_request_text" in source.replace("\r\n", "\n")
    assert '"error": "platform_write_not_requested"' in source
