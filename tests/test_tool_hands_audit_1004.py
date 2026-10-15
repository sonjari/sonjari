"""도구 목록 「빠진 손」 전수조사(`docs/도구목록_빠진손_전수조사_1004.ko.md`)에서 고친 것들 (2026-10-04)."""

from __future__ import annotations

import inspect

from alture_jarvis import plan
from alture_jarvis.agent import BrowserAgent, _platform_scoped_tool_definitions, _platform_write_unrequested


def _planned(prompt: str) -> frozenset[str]:
    return frozenset(str(req.target) for req in plan.extract(prompt) if req.kind == "action")


def _tools(*names: str) -> list[dict]:
    return [{"type": "function", "function": {"name": name}} for name in names]


# ── 3. 영어로 시킨 메일·일정 ──────────────────────────────────────────────────
def test_an_english_request_to_send_mail_opens_the_mail_hands() -> None:
    prompt = "Send an email to bo@example.com with the summary of the three job postings."
    planned = _planned(prompt)
    assert "google_gmail_send" in planned, "영어 계획이 「메일 발송」을 요구로 세운다"
    # 병의 모양: 낱말만 보면 닫혀 있다 — `email` 은 `gmail` 을 품지 않는다.
    assert _platform_write_unrequested("google_gmail_send", prompt) == "메일 보내기"
    # 계획이 세운 요구로 연다 — 사슬의 앞 걸음(준비)도 같이.
    assert _platform_write_unrequested("google_gmail_send", prompt, planned) == ""
    assert _platform_write_unrequested("google_gmail_prepare_send", prompt, planned) == ""
    kept = {t["function"]["name"] for t in _platform_scoped_tool_definitions(
        _tools("google_gmail_prepare_send", "google_gmail_send", "browser_open"), prompt, planned=planned)}
    assert kept == {"google_gmail_prepare_send", "google_gmail_send", "browser_open"}


def test_an_english_request_to_schedule_a_meeting_opens_the_calendar_hands() -> None:
    prompt = "Schedule a meeting with the design team next Tuesday at 3pm."
    planned = _planned(prompt)
    assert any(tool.startswith("google_calendar_") for tool in planned)
    assert _platform_write_unrequested("google_calendar_prepare_create", prompt, planned) == ""
    assert _platform_write_unrequested("google_calendar_create", prompt, planned) == ""
    # 다른 가족은 그대로 닫혀 있다 — 일정을 시켰다고 메일 손이 열리지 않는다.
    assert _platform_write_unrequested("google_gmail_send", prompt, planned) == "메일 보내기"


def test_a_request_that_asked_for_neither_keeps_both_closed() -> None:
    """문을 만든 이유는 그대로다 — 말하지 않은 서비스에는 안 올린다(2026-09-18 「게시자」 사고)."""
    prompt = "Find the publisher and rating of the ChatGPT app in the Microsoft Store."
    planned = _planned(prompt)
    assert _platform_write_unrequested("google_gmail_send", prompt, planned) == "메일 보내기"
    assert _platform_write_unrequested("google_calendar_create", prompt, planned) == "캘린더 일정"
    assert _platform_write_unrequested("naver_blog_publish", prompt, planned) == "네이버 블로그"


def test_the_blog_is_opened_by_words_only_never_by_the_plan() -> None:
    """블로그는 계획이 「발행」을 세워도 낱말이 없으면 안 연다 — 발행은 되돌릴 수 없고, 낱말 오독 전례가 있다."""
    assert _platform_write_unrequested("naver_blog_publish", "Publish it when you are done.", frozenset({"naver_blog_publish"})) == "네이버 블로그"
    assert _platform_write_unrequested("naver_blog_publish", "블로그에 올려 줘", frozenset()) == ""


def test_the_loop_passes_the_planned_actions_to_both_gates() -> None:
    source = inspect.getsource(BrowserAgent)
    assert "planned=planned_action_tools" in source, "모델에게 보일 목록"
    assert "_platform_write_unrequested(name, platform_request_text, planned_action_tools)" in source, "부를 때의 문"


# ── 1. 산출물 차례: 행동 사슬의 앞 걸음 ───────────────────────────────────────
def test_an_owed_action_brings_its_whole_chain_except_the_blog() -> None:
    from alture_jarvis.agent import _unmet_action_tools

    drive = plan.Requirement("action", "드라이브에 올리기", "google_drive_write")
    mail = plan.Requirement("action", "메일 발송", "google_gmail_send")
    blog = plan.Requirement("action", "발행", "naver_blog_publish")
    owed = _unmet_action_tools([(drive, False, ""), (mail, False, ""), (blog, False, "")])
    assert {"google_drive_prepare_write", "google_drive_write", "google_gmail_prepare_send", "google_gmail_send"} <= owed
    # 블로그 사슬은 브라우저를 움직인다 — 산출물 차례에는 끝 도구만(예전 그대로).
    assert "naver_blog_publish" in owed and "naver_blog_prepare_post" not in owed
    assert _unmet_action_tools([(drive, True, "완료")]) == frozenset()


# ── 2-E. 산출물 차례에 같이 남는 손 ───────────────────────────────────────────
def test_the_artifact_stage_keeps_the_hands_that_are_part_of_making_the_file() -> None:
    from alture_jarvis.agent import _focused_tool_definitions

    names = (
        "browser_open", "browser_search", "browser_read", "browser_site_search",
        "local_write_document", "local_edit_spreadsheet", "local_read_document",
        "local_list_directory", "local_search_files", "ask_user", "local_request_path_access",
        "skill_read", "sandbox_run", "local_apply_edit", "hwp_list_open", "hwp_read", "hwp_preview_edit", "hwp_apply_edit",
    )
    kept = {t["function"]["name"] for t in _focused_tool_definitions(_tools(*names), "artifact")}
    assert {"ask_user", "local_request_path_access", "local_search_files", "local_list_directory", "sandbox_run",
            "skill_read", "hwp_preview_edit", "local_apply_edit"} <= kept
    # 차례를 좁힌 이유는 그대로 — 브라우저로 더 찾으러 가는 손은 없다(2026-10-02 밤: 페이지를 세 번 더 열어 엑셀을 못 씀).
    assert not {"browser_open", "browser_search", "browser_read", "browser_site_search"} & kept


def test_the_artifact_stage_is_released_once_the_file_exists() -> None:
    from alture_jarvis.agent import _artifact_requirements_met

    made = plan.Requirement("artifact", "실제 산출물 파일 만들기", (".xlsx",))
    read = plan.Requirement("count", "5개 이상 직접 열어 읽기", 5)
    assert _artifact_requirements_met([(made, True, ""), (read, False, "")]) is True
    assert _artifact_requirements_met([(made, False, ""), (read, True, "")]) is False
    assert _artifact_requirements_met([(read, True, "")]) is False, "산출물 요구가 없는 판은 예전 그대로"
    source = inspect.getsource(BrowserAgent)
    assert "if artifact_focus and _artifact_requirements_met(current_plan_results):" in source


# ── 2-D. 최종 답만 남은 때에도 자기가 만든 파일은 지운다 ──────────────────────
def test_a_file_this_job_wrote_may_be_deleted_even_when_only_the_answer_is_left() -> None:
    from alture_jarvis.agent import _deletes_own_file

    steps = [
        {"ok": True, "tool": "local_write_file", "arguments": {"path": "index.html"}},
        {"ok": True, "tool": "local_write_file", "arguments": {"path": "_verify.tmp.py"},
         "evidence": {"output_path": r"C:\work\L2\_verify.tmp.py"}},
        {"ok": False, "tool": "local_write_file", "arguments": {"path": "never.py"}},
    ]
    assert _deletes_own_file("local_delete_file", {"path": "_verify.tmp.py"}, steps) is True
    assert _deletes_own_file("local_delete_file", {"path": r"C:\work\L2\_verify.tmp.py"}, steps) is True
    # 이 판이 만들지 않은 파일 · 실패한 쓰기 · 다른 도구는 해당 없다.
    assert _deletes_own_file("local_delete_file", {"path": "test_pager.py"}, steps) is False
    assert _deletes_own_file("local_delete_file", {"path": "never.py"}, steps) is False
    assert _deletes_own_file("local_write_file", {"path": "_verify.tmp.py"}, steps) is False
    assert ") and not _deletes_own_file(name, arguments, steps):" in inspect.getsource(BrowserAgent)


# ── 14. 좁힌 코드 손에도 묻는 손은 남는다 ─────────────────────────────────────
def test_narrowed_code_hands_keep_the_asking_hands() -> None:
    from alture_jarvis.agent import code_tools_after_coding_pushback

    profile = frozenset({"local_read_text_file", "local_write_file", "local_apply_edit", "local_delete_file",
                         "local_run_project_command", "ask_user", "local_request_path_access"})
    hands = code_tools_after_coding_pushback(profile, 1, verified=False)
    assert {"ask_user", "local_request_path_access", "local_run_project_command"} <= hands
    assert "local_read_text_file" not in hands


# ── 4·8·9. 안내가 지금 못 하는 일을 시키지 않는다 ─────────────────────────────
def test_instructions_do_not_name_what_cannot_be_called() -> None:
    source = inspect.getsource(BrowserAgent)
    assert "code_search" not in source.split("code_recon_required")[1][:1500], "없는 도구 이름을 대지 않는다"
    assert "지금은 이 손만 쓸 수 있다: " in source, "예고 되받기가 차례 문과 반대로 말하지 않는다"
    assert "if stage_hands else" in source, "숫자 문은 차례 중에 「다시 열어 읽어라」를 말하지 않는다"


# ── 2-F. 조사 판에서 빠져 있던 손 ─────────────────────────────────────────────
def test_a_research_job_keeps_the_research_apis_and_the_file_finders() -> None:
    from alture_jarvis.agent import _route_scoped_tool_definitions

    names = ("browser_open", "github_search", "reddit_hot", "hackernews_top", "naver_news", "local_list_directory",
             "local_search_files", "local_grep", "local_request_path_access", "google_gmail_search",
             "career_strategy_lookup", "schedule_list", "camera_capture", "google_calendar_create")
    kept = {t["function"]["name"] for t in _route_scoped_tool_definitions(_tools(*names), web_only=True)}
    assert {"github_search", "reddit_hot", "hackernews_top", "naver_news", "local_list_directory", "local_search_files",
            "local_grep", "local_request_path_access", "google_gmail_search"} <= kept
    # 이 갈래를 만든 이유였던 헛손은 그대로 빠진다(2026-09-09: 책 조사 판이 진로DB 를 6번 불렀다).
    assert not {"career_strategy_lookup", "schedule_list", "camera_capture", "google_calendar_create"} & kept


# ── §4. 설명이 실제와 달랐던 도구 ─────────────────────────────────────────────
def test_descriptions_say_what_the_tools_really_do() -> None:
    import json
    from pathlib import Path

    import alture_jarvis
    from alture_jarvis.agent import AGENT_SYSTEM_PROMPT

    package = Path(alture_jarvis.__file__).parent
    local = (package / "local_computer.py").read_text(encoding="utf-8")
    assert "항상 화면 승인이 필요하고" not in local, "지우기는 늘 승인을 묻지 않는다"
    assert "Git 변경 명령은 차단한다" not in local, "add·commit·branch·switch 를 받는다"
    assert "PPTX·HWPX·ODT" in local, "한글(hwpx)도 읽는다"
    assert "여전히 읽기 전용" not in AGENT_SYSTEM_PROMPT and "google_drive_prepare_write" in AGENT_SYSTEM_PROMPT
    assert "어디에도 쓰지 마라" not in AGENT_SYSTEM_PROMPT
    # 바꾼 문장은 영어 사전에도 열쇠가 있어야 한다 — 없으면 영어 화면의 모델이 한국어 설명을 받는다.
    english = json.loads((package / "ui_i18n_en.json").read_text(encoding="utf-8"))
    for needle in ("권한 모드와 자리에 따라 화면 승인을 한 번 물을 수 있다", "**너는 이 그림을 볼 수 없다.**",
                   "그림 파일만 저장됐다", "Git 명령(status·diff·log 와 add·commit·branch·switch)", "PPTX·HWPX·ODT"):
        assert any(needle in key for key in english), needle
    for stale in ("항상 화면 승인이 필요하고", "무엇이 보이는지 확인하거나", "Git 변경 명령은 차단한다", "(code_search 등)"):
        assert not any(stale in key for key in english), stale
