"""권한 무시는 **한 축**이어야 한다 — 승인 카드만 풀리고 하네스 문이 따로 막으면 모순이다 (2026-09-28, 전략안 §53).

코드 모드 316판을 세어 보니 사람이 「묻지 말고 해라」를 고른 판에서도 도구 프로필(낱말표)·검증 명령 문·「먼저 읽어라」
문이 각자 막았다. 사람은 「다 허락했는데 왜 막지」, 모델은 그 거절을 정책으로 읽고 포기했다.
"""

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.code_runtime import (
    CODE_PREVIEW_TOOL_NAMES,
    CODE_RESEARCH_TOOL_NAMES,
    CODE_SANDBOX_TOOL_NAMES,
    select_code_tool_profile,
)


def test_bypass_opens_every_code_hand_even_for_a_plain_request():
    plain = select_code_tool_profile("이 함수 이름 바꿔 줘")
    opened = select_code_tool_profile("이 함수 이름 바꿔 줘", open_all=True)
    assert not (CODE_RESEARCH_TOOL_NAMES <= plain.tool_names)          # 평소엔 낱말로 고른다
    for bundle in (CODE_RESEARCH_TOOL_NAMES, CODE_SANDBOX_TOOL_NAMES, CODE_PREVIEW_TOOL_NAMES):
        assert bundle <= opened.tool_names


def test_bypass_does_not_offer_pack_tools_that_are_not_installed():
    # 게임 팩이 꺼진 PC 에서 유니티 도구를 목록에 올리면 그것도 벽이다 — 제품은 사용자 PC 에 기대지 않는다.
    opened = select_code_tool_profile("아무 일", open_all=True, available={"local_read_text_file"})
    assert not any(name.startswith("unity_") for name in opened.tool_names)


def test_a_blocked_write_is_named_in_the_next_pushback():
    steps = [
        {"tool": "local_index_codebase", "ok": True},
        {"tool": "local_write_file", "ok": False, "error": "code_recon_required"},
    ]
    note = BrowserAgent._last_blocked_write_note(steps)
    assert "code_recon_required" in note and "막혔다" in note


def test_no_blocked_note_when_the_last_write_went_through():
    steps = [
        {"tool": "local_write_file", "ok": False, "error": "code_recon_required"},
        {"tool": "local_read_text_file", "ok": True},
        {"tool": "local_write_file", "ok": True},
    ]
    assert BrowserAgent._last_blocked_write_note(steps) == ""


def test_the_list_end_the_tool_saw_is_put_next_to_a_shortfall():
    steps = [{"tool": "browser_load_more", "ok": True, "evidence": {"grew": False}}]
    answer = "Reddit 의 댓글 로드 제한으로 인해 총 4개 중 2개만 확인했습니다."
    fact = BrowserAgent._list_end_fact(answer, steps)
    assert "목록의 끝" in fact and "확인되지 않았습니다" in fact


def test_no_list_end_fact_when_the_list_grew_or_nothing_is_missing():
    grew = [{"tool": "browser_load_more", "ok": True, "evidence": {"grew": True}}]
    assert BrowserAgent._list_end_fact("2개만 확인했습니다", grew) == ""
    ended = [{"tool": "browser_load_more", "ok": True, "evidence": {"grew": False}}]
    assert BrowserAgent._list_end_fact("댓글 두 개를 정리했습니다.", ended) == ""


def test_a_refused_project_command_names_the_door_that_runs_it():
    import pytest

    from alture_jarvis.local_computer import LocalComputerTools

    with pytest.raises(PermissionError) as refused:
        LocalComputerTools._validated_project_command(["someunknowntool", "."])
    assert str(refused.value).startswith("project_command_not_allowed") and "local_run_shell" in str(refused.value)
    with pytest.raises(PermissionError) as refused_module:
        LocalComputerTools._validated_project_command(["python", "-m", "http.server"])
    assert str(refused_module.value).startswith("python_module_not_allowed") and "local_run_shell" in str(refused_module.value)
