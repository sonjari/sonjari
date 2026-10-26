"""앱 안의 Claude Agent — 「앱 안」 지침 · 작업 폴더 · 키 모양 (2026-10-26).

진짜 클로드 호출은 없다. 지침은 바깥 판(`mcp_server.INSTRUCTIONS`)에서 줄 몇 개만 바꿔 만들므로, 바깥 판이 바뀌어
고칠 자리를 못 찾으면 이 시험이 먼저 깨진다(두 판이 조용히 갈라지지 않게).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from alture_jarvis import api_escalation as esc
from alture_jarvis import claude_agent, mcp_server


@pytest.mark.parametrize("lang", ["ko", "en"])
@pytest.mark.parametrize("mode", ["cowork", "code"])
def test_every_anchor_is_found(mode: str, lang: str) -> None:
    text = claude_agent.in_app_instructions(mode, lang)
    assert text.startswith("당신은" if lang == "ko" else "You are")
    # 바깥 클로드 이야기는 빠진다.
    assert "빈 브라우저라 로그인이 없습니다" not in text
    assert "empty browser without their logins" not in text
    # 승인은 「이 창」에서.
    assert ("이 창의 승인 카드" in text) if lang == "ko" else ("approval card in this window" in text)
    assert "Sonjari 창에서 직접" not in text and "in the Sonjari window" not in text


def test_cowork_drops_localhost_line_code_keeps_it() -> None:
    cowork = claude_agent.in_app_instructions("cowork", "ko")
    code = claude_agent.in_app_instructions("code", "ko")
    assert "방금 띄워 둔 앱(localhost)" not in cowork
    assert "방금 띄워 둔 앱(localhost)" in code


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_code_mode_adds_hand_off_line_inside_when_to_call(lang: str) -> None:
    text = claude_agent.in_app_instructions("code", lang)
    lines = text.split("\n")
    delegate = claude_agent._EN["code_delegate"] if lang == "en" else claude_agent._KO["code_delegate"]
    when_not = "When not to call it" if lang == "en" else "부르지 말 것"
    assert lines.index(delegate) < lines.index(when_not)
    # 「큰 설계 통째로」 줄은 「사용자가 따로 말하지 않았는데」로 맞춰져 맡기기 줄과 부딪히지 않는다.
    dont = claude_agent._EN["code_dont"] if lang == "en" else claude_agent._KO["code_dont"]
    assert dont in lines
    assert lines.index(dont) > lines.index(when_not)


def test_cowork_has_no_code_hand_off_line() -> None:
    assert claude_agent._KO["code_delegate"] not in claude_agent.in_app_instructions("cowork", "ko")


def test_other_lines_stay_identical_to_outside_version() -> None:
    """바꾸기로 한 줄 말고는 바깥 판과 한 글자도 다르지 않다."""
    outside = mcp_server.instructions_ko().strip().split("\n")
    inside = claude_agent.in_app_instructions("cowork", "ko").split("\n")
    changed_heads = ("- 코딩 중에도", "- 당신이 방금 띄워 둔 앱", "- 되돌릴 수 없는 동작")
    for line in outside:
        if line.startswith(changed_heads):
            continue
        assert line in inside, line


def test_missing_anchor_is_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "instructions_ko", lambda: "다른 글\n부르지 말 것\n")
    with pytest.raises(claude_agent.AnchorMissing):
        claude_agent.in_app_instructions("cowork", "ko")


def test_tools_are_the_three_delegation_doors() -> None:
    assert claude_agent.TOOLS == [
        "mcp__sonjari__sonjari_task", "mcp__sonjari__sonjari_task_status", "mcp__sonjari__sonjari_guide",
    ]


def test_prepare_writes_files_without_secrets(tmp_path: Path) -> None:
    config = SimpleNamespace(data_dir=tmp_path, host="127.0.0.1", port=8091)
    result = claude_agent.prepare(config, lang="ko")
    base = tmp_path / "claude_agent"
    mcp = json.loads((base / "mcp.json").read_text(encoding="utf-8"))
    entry = mcp["mcpServers"]["sonjari"]
    assert entry["args"] == ["-m", "alture_jarvis.mcp_server"]
    assert entry["env"]["JARVIS_TOKEN_FILE"].endswith("control.token")
    # 비밀은 없다 — 토큰 값도 키도 아니고 토큰 **파일 자리**만.
    text = (base / "mcp.json").read_text(encoding="utf-8")
    assert "sk-ant-" not in text
    assert (base / "instructions_cowork.ko.md").read_text(encoding="utf-8") == claude_agent.in_app_instructions("cowork", "ko")
    assert (base / "instructions_code.ko.md").is_file()
    assert (base / "workspace").is_dir()
    assert result["has_key"] is False
    assert result["mcp_config"] == str(base / "mcp.json")


def test_prepare_does_not_rewrite_same_text(tmp_path: Path) -> None:
    config = SimpleNamespace(data_dir=tmp_path, host="127.0.0.1", port=8091)
    claude_agent.prepare(config, lang="en")
    path = tmp_path / "claude_agent" / "instructions_cowork.en.md"
    before = path.stat().st_mtime_ns
    claude_agent.prepare(config, lang="en")
    assert path.stat().st_mtime_ns == before


@pytest.mark.parametrize("key,shape", [
    ("sk-ant-api03-" + "x" * 40, "api_key"),
    ("sk-ant-oat01-" + "x" * 40, "subscription_token"),
    ("sk-ant-admin01-" + "x" * 40, "admin_key"),
    ("hunter2", "not_a_key"),
    ("sk-ant-api03- spaced", "not_a_key"),
])
def test_key_shape(key: str, shape: str) -> None:
    assert esc.key_shape(key) == shape


class _Clip:
    def __init__(self, text: str) -> None:
        self.text = text

    def read(self) -> str:
        return self.text

    def clear(self) -> None:
        self.text = ""


def test_clipboard_refuses_subscription_token(tmp_path: Path) -> None:
    config = SimpleNamespace(data_dir=tmp_path)
    out = esc.key_from_clipboard(config, _Clip("sk-ant-oat01-" + "y" * 60))
    assert out == {"ok": False, "error": "subscription_token"}
    assert not esc.has_key(config)
    out = esc.key_from_clipboard(config, _Clip("sk-ant-admin01-" + "y" * 60))
    assert out == {"ok": False, "error": "not_an_api_key"}
