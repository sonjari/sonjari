"""클립보드와 키 조합 — 좌표를 쓰지 않는 두 개의 손잡이.

구형 프로그램은 메뉴가 UIA 트리에 안 잡히면서 Ctrl+S 는 먹는 경우가 흔하다. 그리고
표·목록을 읽을 때는 화면을 보는 것보다 복사가 정확하다(비전은 오독하지만 복사는
원문 그대로다).

여기서 지키는 것 셋:
1. 키는 **허용 목록**으로만 해석한다 — 통과시키면 아무 글자나 아무 창에나 치는 통로다
2. 앱을 바꾸는 동작(key·paste)은 기존 미리보기 → 화면 승인 경로를 그대로 탄다
3. 남의 클립보드를 훔치지 않는다 — 쓰고 나면 되돌려 놓는다
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.windows_automation import (
    WindowsAutomationTools,
    _DESTRUCTIVE_KEYS,
    translate_key_combo,
)


def _tools(tmp_path: Path) -> WindowsAutomationTools:
    return WindowsAutomationTools(
        JarvisConfig(
            runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs"
        )
    )


# ── 키 해석 ────────────────────────────────────────────────────────────────
def test_a_plain_shortcut_translates() -> None:
    assert translate_key_combo("ctrl+s") == ("^s", "ctrl+s")


def test_modifiers_stack() -> None:
    keys, combo = translate_key_combo("Ctrl+Shift+N")
    assert keys == "^+n" and combo == "ctrl+shift+n"


def test_named_keys_work() -> None:
    assert translate_key_combo("enter")[0] == "{ENTER}"
    assert translate_key_combo("f5")[0] == "{F5}"
    assert translate_key_combo("alt+f4")[0] == "%{F4}"


def test_free_text_is_refused() -> None:
    """여기가 핵심이다. send_keys 에 문자열을 그대로 넘기면 아무 글자나 칠 수 있다."""
    with pytest.raises(ValueError, match="key_not_allowed"):
        translate_key_combo("계좌번호를 지워라")


def test_an_unknown_modifier_is_refused() -> None:
    with pytest.raises(ValueError, match="key_modifier_not_allowed"):
        translate_key_combo("meta+q")


def test_pywinauto_syntax_cannot_be_smuggled_in() -> None:
    # `{VK_LWIN down}` 같은 원문법이 그대로 들어가면 허용 목록이 무의미해진다.
    for attempt in ("{VK_LWIN down}", "^{F4}", "abc"):
        with pytest.raises(ValueError):
            translate_key_combo(attempt)


def test_destructive_combos_are_named_not_hidden() -> None:
    # 막지는 않는다 — 어차피 사람이 화면에서 승인한다. 다만 알아볼 수 있어야 한다.
    assert "alt+f4" in _DESTRUCTIVE_KEYS
    assert translate_key_combo("alt+f4")[1] in _DESTRUCTIVE_KEYS


# ── 미리보기 경로 ───────────────────────────────────────────────────────────
def test_key_and_paste_are_registered_actions(tmp_path: Path) -> None:
    definition = next(
        item["function"]
        for item in _tools(tmp_path).ollama_tools
        if item["function"]["name"] == "windows_uia_preview"
    )
    allowed = definition["parameters"]["properties"]["action"]["enum"]

    assert "key" in allowed and "paste" in allowed


def test_key_and_paste_do_not_need_a_ref(tmp_path: Path) -> None:
    """구형 앱은 메뉴가 UIA 에 안 잡히면서 Ctrl+S 는 먹는다. ref 를 강제하면
    바로 그 상황에서 못 쓴다."""
    definition = next(
        item["function"]
        for item in _tools(tmp_path).ollama_tools
        if item["function"]["name"] == "windows_uia_preview"
    )

    assert definition["parameters"]["required"] == ["window_id", "action"]


def test_a_bad_key_is_refused_before_any_preview_exists(tmp_path: Path) -> None:
    """거절은 승인 화면 앞이 아니라 그 전에 나야 한다 — 승인 카드에 뜬 것은
    이미 실행 가능한 것이어야 한다."""
    tools = _tools(tmp_path)

    with pytest.raises(ValueError, match="key_not_allowed"):
        tools.uia_preview({"window_id": 1, "action": "key", "value": "아무 말이나"})

    assert tools.status()["active_previews"] == 0


def test_key_without_a_value_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="value_required"):
        _tools(tmp_path).uia_preview({"window_id": 1, "action": "key", "value": ""})


def test_a_missing_ref_says_so_instead_of_blaming_the_snapshot(tmp_path: Path) -> None:
    """ref 를 안 준 것과 준 ref 가 낡은 것은 고치는 방법이 다르다. 한 문구로 뭉치면
    '스냅샷을 다시 뜨라'는 엉뚱한 안내를 받고 그대로 반복한다."""
    with pytest.raises(ValueError, match="ref_required_for_this_action"):
        _tools(tmp_path).uia_preview({"window_id": 1, "action": "click"})


def test_the_new_tools_are_in_the_catalog(tmp_path: Path) -> None:
    # 카탈로그에 없는 도구는 모델이 부를 수 없다 — 지금까지 라우팅 버그 셋이 이 모양이었다.
    names = _tools(tmp_path).names

    assert {"clipboard_read", "windows_copy_from_window"} <= names


def test_reading_the_clipboard_needs_no_approval_but_writing_an_app_does(tmp_path: Path) -> None:
    """읽기는 L1, 앱을 바꾸는 것은 L2. 이 경계가 흐려지면 승인 카드가 의미를 잃는다."""
    from alture_jarvis.jobs import JobStore
    from alture_jarvis.events import EventBus
    from alture_jarvis.tool_gateway import ToolGateway

    gateway = ToolGateway(JobStore(tmp_path / "jobs.db"), EventBus())
    _tools(tmp_path).register(gateway)
    levels = {row["name"]: row["risk_level"] for row in gateway.list_tools()}

    assert levels["clipboard_read"] == "L1"
    assert levels["windows_copy_from_window"] == "L1"
    assert levels["windows_execute_preview"] == "L2"


def test_the_agent_prompt_tells_the_model_these_exist(tmp_path: Path) -> None:
    """도구가 있어도 프롬프트가 모르면 안 부른다(선행 사고 3건이 그 모양이었다)."""
    from alture_jarvis.agent import AGENT_SYSTEM_PROMPT

    assert "windows_copy_from_window" in AGENT_SYSTEM_PROMPT
    assert 'action="key"' in AGENT_SYSTEM_PROMPT
    assert 'action="paste"' in AGENT_SYSTEM_PROMPT
