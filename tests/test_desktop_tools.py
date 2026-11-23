"""`desktop_tools.py` 역할 표 — 판정 자리를 옮긴 뒤에도 **윈도우 집합이 글자까지 그대로**인지(설계 §8-1).

옛 집합은 `fixtures/desktop_tool_sets_6927f47e.json` — 옮기기 직전(6927f47e) 모듈에서 그대로 뜬 것이다. 손으로 고치지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis import (
    agent,
    answer_claims,
    answer_hygiene,
    code_look_gate,
    desktop_tools,
    permissions,
    plan,
    promise_gate,
    transcript,
)

_OLD = json.loads((Path(__file__).parent / "fixtures" / "desktop_tool_sets_6927f47e.json").read_text(encoding="utf-8"))["sets"]

_NOW = {
    "agent._PREVIEW_TOOLS": agent._PREVIEW_TOOLS,
    "answer_hygiene._ARTIFACT_STAGE_SUPPORT": answer_hygiene._ARTIFACT_STAGE_SUPPORT,
    "answer_claims._DESKTOP_READ_TOOLS": answer_claims._DESKTOP_READ_TOOLS,
    "promise_gate._LOOK_ONLY_TOOLS": promise_gate._LOOK_ONLY_TOOLS,
    "code_look_gate._READ_ONLY_FORBIDDEN_TOOLS": code_look_gate._READ_ONLY_FORBIDDEN_TOOLS,
    "plan._GUI_ACTION_TOOLS": plan._GUI_ACTION_TOOLS,
    "plan._ACTION_TOOLS": plan._ACTION_TOOLS,
    "plan._WINDOW_READ_TOOLS": plan._WINDOW_READ_TOOLS,
    "transcript.NAVIGATION_TOOLS": transcript.NAVIGATION_TOOLS,
    "permissions.ALWAYS_ASK": permissions.ALWAYS_ASK,
    "permissions.WRITE_TOOL_NAMES": permissions.WRITE_TOOL_NAMES,
}

#: 자리마다 맥에서 **더해져야 하는** 이름 — 윈도우 이름의 역할 짝(비전 미리보기는 맥 짝 없음).
_MAC_ADDED = {
    "agent._PREVIEW_TOOLS": {"mac_ax_preview"},
    "answer_hygiene._ARTIFACT_STAGE_SUPPORT": {"mac_list_open_windows", "mac_focus_window", "mac_open_path", "mac_ax_snapshot",
                                               "mac_ax_preview", "mac_execute_preview", "mac_copy_from_window"},
    "answer_claims._DESKTOP_READ_TOOLS": {"mac_ax_snapshot", "mac_copy_from_window", "mac_list_open_windows"},
    "promise_gate._LOOK_ONLY_TOOLS": {"mac_ax_preview", "mac_ax_snapshot"},
    "code_look_gate._READ_ONLY_FORBIDDEN_TOOLS": {"mac_execute_preview"},
    "plan._GUI_ACTION_TOOLS": {"mac_execute_preview"},
    "plan._ACTION_TOOLS": {"mac_execute_preview"},
    "plan._WINDOW_READ_TOOLS": {"mac_ax_snapshot", "mac_copy_from_window"},
    "transcript.NAVIGATION_TOOLS": {"mac_ax_snapshot", "mac_focus_window", "mac_list_open_windows"},
    "permissions.ALWAYS_ASK": {"mac_execute_preview"},
    "permissions.WRITE_TOOL_NAMES": {"mac_execute_preview", "mac_open_path"},
}


#: 고정(6927f47e) **뒤에** 새 도구로 더한 이름 — 고정 파일은 손으로 고치지 않으니 여기에 적고 빼고 견준다.
#:   2026-11-23 한글 양식 채우기(hwp_preview_fill → hwp_apply_fill): 서식 도구가 있는 자리에 같이 들어간다.
_ADDED_AFTER_FREEZE = {
    "answer_hygiene._ARTIFACT_STAGE_SUPPORT": {"hwp_preview_fill"},
    "code_look_gate._READ_ONLY_FORBIDDEN_TOOLS": {"hwp_preview_fill", "hwp_apply_fill"},
    "permissions.WRITE_TOOL_NAMES": {"hwp_apply_fill"},
    "plan._ACTION_TOOLS": {"hwp_apply_fill"},
}


@pytest.mark.parametrize("key", sorted(_OLD))
def test_windows_side_unchanged(key: str) -> None:
    """맥 이름을 빼면 옛 집합과 **글자까지** 같다 — 윈도우 동작은 하나도 안 바뀐다."""
    now = set(_NOW[key]) - _ADDED_AFTER_FREEZE.get(key, set())
    assert {name for name in now if not name.startswith("mac_")} == set(_OLD[key])


@pytest.mark.parametrize("key", sorted(_OLD))
def test_only_mac_names_added_and_all_pairs_present(key: str) -> None:
    added = _ADDED_AFTER_FREEZE.get(key, set())
    assert added <= set(_NOW[key])  # 적어 둔 이름이 정말 들어가 있다(빠지면 이 목록도 같이 고친다)
    now = set(_NOW[key]) - added
    assert now - set(_OLD[key]) == _MAC_ADDED[key]


def test_every_site_frozen() -> None:
    assert set(_OLD) == set(_NOW) == set(_MAC_ADDED)


def test_agent_inline_execute_set() -> None:
    """`agent.py` 안쪽 진척 셈 둘은 `_DESKTOP_EXECUTE_TOOLS` 를 본다 — 옛 글자는 「windows_execute_preview」 하나였다."""
    assert agent._DESKTOP_EXECUTE_TOOLS == frozenset({"windows_execute_preview", "mac_execute_preview"})
    source = Path(agent.__file__).read_text(encoding="utf-8")
    assert source.count("tool in _DESKTOP_EXECUTE_TOOLS") == 2


def test_role_table_windows_names_match_registered_tools(tmp_path) -> None:
    """표의 윈도우 이름이 실제로 등록되는 이름과 같다(오타 0)."""
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.local_computer import LocalComputerTools
    from alture_jarvis.windows_automation import WindowsAutomationTools

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    registered = WindowsAutomationTools(config).names | {
        str(item["function"]["name"]) for item in LocalComputerTools(config).ollama_tools
    }
    assert desktop_tools.WINDOWS_NAMES <= registered


def test_role_table_mac_names_match_mac_tools(tmp_path) -> None:
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.mac_automation import MacAutomationTools

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    assert MacAutomationTools(config).names == desktop_tools.MAC_NAMES


def test_execute_always_asks_on_both_oses() -> None:
    """보안 경계: 창 동작 실행은 어느 OS 에서도 모드와 상관없이 사람이 본다."""
    assert desktop_tools.names(desktop_tools.EXECUTE) <= permissions.ALWAYS_ASK
    assert desktop_tools.names(desktop_tools.EXECUTE, desktop_tools.OPEN) <= permissions.WRITE_TOOL_NAMES


def test_mac_progress_labels_cover_all_mac_tools() -> None:
    assert set(desktop_tools.MAC_PROGRESS_LABELS) == desktop_tools.MAC_NAMES


def test_role_of() -> None:
    assert desktop_tools.role_of("mac_ax_preview") == desktop_tools.role_of("windows_uia_preview") == desktop_tools.PREVIEW
    assert desktop_tools.role_of("browser_click") == ""


def test_measure_script_classifies_mac_like_windows() -> None:
    """측정 스크립트(`scripts/measure_autonomy.py`)는 패키지를 늦게 불러와 이름을 글자로 적는다 — 역할마다 맥 짝이 윈도우 이름과
    **같은 칸**(쓰기 · 확정 · 준비 · 중립)에 있는지 본다. 한쪽만 더하면 맥 실적이 성공률 분모에서 조용히 빠진다."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "measure_autonomy.py"
    spec = importlib.util.spec_from_file_location("_measure_autonomy_desktop", path)
    assert spec and spec.loader
    ma = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ma)
    buckets = {"write": ma.WRITE_TOOLS, "commit": ma.COMMIT_TOOLS, "prepare": ma.PREPARE_TOOLS, "neutral": ma.NEUTRAL_TOOLS}
    for role, (windows_name, mac_name) in desktop_tools.ROLE_NAMES.items():
        if not mac_name:
            continue
        where_windows = {key for key, names in buckets.items() if windows_name in names}
        where_mac = {key for key, names in buckets.items() if mac_name in names}
        assert where_windows and where_windows == where_mac, (role, where_windows, where_mac)
