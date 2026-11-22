"""작은 창에서 팩 도구는 그 일을 말했을 때만 싣는다 (2026-11-17 맥 4B · 32K · 팩 켠 맥 · 워드 판에 도구 109개)."""
from __future__ import annotations

import pytest

from alture_jarvis.tool_roster import _platform_scoped_tool_definitions


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": "d", "parameters": {}}}


TOOLS = [_tool(n) for n in ("local_write_document", "browser_navigate", "gen_3d", "gen_3d_status", "unity_editor_look",
                            "video_read", "anim_fit_check")]


def _names(request: str, compact: bool = True) -> set[str]:
    return {t["function"]["name"] for t in _platform_scoped_tool_definitions(TOOLS, request, compact=compact)}


def test_a_word_job_on_a_small_window_carries_no_pack_tools() -> None:
    assert _names("오늘 할 일 워드 문서를 만들어 줘") == {"local_write_document", "browser_navigate"}


@pytest.mark.parametrize(("request_text", "kept"), [
    ("이 사진으로 3D 피규어 만들어 줘", {"gen_3d", "gen_3d_status"}),
    ("유니티 씬 화면 좀 봐 줘", {"unity_editor_look"}),
    ("이 영상 내용 정리해 줘", {"video_read"}),
    ("바이페드 모션 맞는지 봐 줘", {"anim_fit_check"}),
])
def test_saying_the_pack_brings_its_tools_back(request_text: str, kept: set[str]) -> None:
    assert kept <= _names(request_text)


def test_a_big_window_keeps_everything() -> None:
    assert _names("오늘 할 일 워드 문서를 만들어 줘", compact=False) == {t["function"]["name"] for t in TOOLS}


def test_a_middle_window_drops_only_pack_tools() -> None:
    """11-18 맥 9B 64K: 작은 창 압축은 안 걸려도 말 안 나온 팩 도구는 뺀다. 다른 무리(한글 · 입시 …)는 그대로."""
    tools = TOOLS + [_tool("hwp_read"), _tool("admission_lookup")]
    names = {t["function"]["name"] for t in _platform_scoped_tool_definitions(tools, "워드 문서 만들어 줘", pack_lean=True)}
    assert names == {"local_write_document", "browser_navigate", "hwp_read", "admission_lookup"}
    assert "gen_3d" in {t["function"]["name"] for t in _platform_scoped_tool_definitions(tools, "3D 피규어", pack_lean=True)}
