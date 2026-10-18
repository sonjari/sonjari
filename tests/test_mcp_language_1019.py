"""바깥 AI 연결(MCP)이 사용자의 언어로 말하는가 (2026-10-19).

사고: 영어로 시킨 클로드 코드가 손자리에게 과제를 **한국어로** 넘겼다(사진 찍던 판 `029fae29`). 과제 칸 설명이
「한국어 권장」이었고, 안내문 · 도구 설명 · 결과 안내가 전부 한국어였다. 영어 사용자가 클로드 코드에 손자리를 붙이면
똑같이 된다. 연결이 사용자가 고른 화면 언어를 따르고, 과제는 **사용자의 말로** 적게 한다.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import pytest

from alture_jarvis import mcp_language
from alture_jarvis.delegation import DELEGATION_TOOLS, GUIDE_TOOL, TASK_TOOL, localized_tool
from alture_jarvis.mcp_server import INSTRUCTIONS, INSTRUCTIONS_EN, JarvisMcpBridge

HANGUL = re.compile("[가-힣]")


class _Resp:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload


class _LangClient:
    def __init__(self, lang: str | None) -> None:
        self.lang = lang
        self.calls: list[str] = []

    def get(self, url: str, headers: dict[str, str], timeout: float) -> _Resp:
        self.calls.append(url)
        if self.lang is None:
            raise OSError("backend is not up")
        return _Resp({"lang": self.lang})


# ---- 언어 고르기 ---------------------------------------------------------------------


def test_the_connection_follows_the_language_the_user_picked_in_the_app() -> None:
    client = _LangClient("en")
    assert mcp_language.pick_language("http://127.0.0.1:8091", "t", env={}, client=client) == "en"
    assert client.calls == ["http://127.0.0.1:8091/v1/ui-language"]
    assert mcp_language.pick_language("http://x", "t", env={}, client=_LangClient("ko")) == "ko"


def test_without_the_app_running_it_falls_back_to_the_windows_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_language, "os_language", lambda: "en")
    assert mcp_language.pick_language("http://x", "t", env={}, client=_LangClient(None)) == "en"
    monkeypatch.setattr(mcp_language, "os_language", lambda: "ko")
    assert mcp_language.pick_language("http://x", "t", env={}, client=_LangClient(None)) == "ko"


def test_an_explicit_setting_wins_for_measurements() -> None:
    client = _LangClient("ko")
    assert mcp_language.pick_language("http://x", "t", env={"JARVIS_MCP_LANG": "en"}, client=client) == "en"
    assert client.calls == []  # 정해 줬으면 묻지도 않는다


# ---- 안내문 · 도구 설명 ---------------------------------------------------------------


def test_the_task_field_no_longer_asks_for_korean() -> None:
    """뿌리: 「(한국어 권장)」. 두 언어 모두 「사용자의 말로」."""
    ko = TASK_TOOL["parameters"]["properties"]["task"]["description"]
    en = localized_tool(TASK_TOOL, "en")["parameters"]["properties"]["task"]["description"]
    assert "한국어 권장" not in ko and "사용자가 당신과 쓰는 언어" in ko
    assert "language the user is using with you" in en
    assert "사용자가 당신과 쓰는 언어로" in INSTRUCTIONS
    assert "language the user is using with you" in INSTRUCTIONS_EN


def test_english_instructions_and_tool_descriptions_carry_no_korean() -> None:
    assert not HANGUL.search(INSTRUCTIONS_EN)
    for tool in (*DELEGATION_TOOLS, GUIDE_TOOL):
        assert not HANGUL.search(json.dumps(localized_tool(tool, "en"), ensure_ascii=False)), tool["name"]


def test_english_tools_keep_the_same_names_and_fields() -> None:
    """설명 글만 바꾼다 — 이름 · 칸 · 스키마가 갈리면 호스트가 부르다 막힌다."""
    for tool in (*DELEGATION_TOOLS, GUIDE_TOOL):
        en = localized_tool(tool, "en")
        assert en["name"] == tool["name"]
        assert set((en.get("parameters") or {}).get("properties", {})) == set((tool.get("parameters") or {}).get("properties", {}))
        for key, spec in (tool.get("parameters") or {}).get("properties", {}).items():
            assert {k: v for k, v in en["parameters"]["properties"][key].items() if k != "description"} == \
                   {k: v for k, v in spec.items() if k != "description"}
    assert localized_tool(TASK_TOOL, "ko") == dict(TASK_TOOL)  # 한국어 연결은 그대로


def test_the_bridge_lists_english_tools_on_an_english_connection() -> None:
    class _Down:
        async def get(self, *args: Any, **kwargs: Any) -> Any:
            raise OSError("down")

    bridge = JarvisMcpBridge(client=_Down(), lang="en")
    tools = asyncio.run(bridge.list_tools())
    assert {tool["name"] for tool in tools} >= {"sonjari_task", "sonjari_task_status", "sonjari_guide"}
    assert not HANGUL.search(json.dumps(tools, ensure_ascii=False))


# ---- 결과 안내 ------------------------------------------------------------------------


def test_the_result_summary_goes_out_in_english_but_paths_and_commands_stay() -> None:
    """운영 맡기기 판 1,481개를 영어로 요약해 보니 남은 한국어의 대부분이 이어 붙인 한 줄이었다(「○○ 에게 보냄 · 정제 N」)."""
    bridge = JarvisMcpBridge(lang="en")
    summary = {
        "status": "done",
        "message": "일하는 중입니다. 잠시 뒤 sonjari_task_status 를 다시 부르세요.",
        "receipt": {"line": "Claude Code 에게 보냄 · 필요한 것 2/3 · 정제 0"},
        "review_notes": [
            "가지에 바뀐 파일이 없습니다.",
            "돌려받아야 할 것 중 비어 있는 항목: source URL — 이 항목 없이 끝낼 수 있는지, 다시 맡길지 정하세요.",
        ],
        "branch": {"repo": r"C:\work\monorepo", "take_home": {"take": r'git -C "C:\work\monorepo" cherry-pick -n abc..def'}},
        "answer": "모델의 답은 사용자가 쓴 말 그대로 둔다",
    }
    out = bridge.say(summary)
    assert not HANGUL.search(out["message"]) and not HANGUL.search(out["receipt"]["line"])
    assert out["receipt"]["line"] == "Sent to Claude Code · needs 2/3 · masked 0"
    assert all(not HANGUL.search(note) for note in out["review_notes"])
    # 명령 · 경로 안의 한국어 폴더 이름을 바꾸면 명령이 깨진다.
    assert out["branch"]["repo"] == summary["branch"]["repo"]
    assert out["branch"]["take_home"]["take"] == summary["branch"]["take_home"]["take"]
    assert out["answer"] == summary["answer"]


def test_a_korean_connection_is_left_exactly_as_before() -> None:
    bridge = JarvisMcpBridge(lang="ko")
    summary = {"message": "일하는 중입니다.", "review_notes": ["가지에 바뀐 파일이 없습니다."]}
    assert bridge.say(summary) == summary


def test_failure_text_goes_out_in_english_on_an_english_connection() -> None:
    class _Refuse:
        async def get(self, *args: Any, **kwargs: Any) -> Any:
            return _Resp([])

        async def post(self, *args: Any, **kwargs: Any) -> Any:
            r = _Resp({}, 401)
            r.text = ""  # type: ignore[attr-defined]
            return r

    bridge = JarvisMcpBridge(client=_Refuse(), lang="en")
    text, failed = asyncio.run(bridge.call("sonjari_task", {"task": "x"}))
    assert failed
    assert not HANGUL.search(text), text
