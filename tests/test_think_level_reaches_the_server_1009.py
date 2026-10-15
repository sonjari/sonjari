"""코드 판의 「보통」 생각 세기를 서버가 알아듣는 자리에 싣는다 · 셸의 `format` 오탐 · 시간 제한은 멈춘 것이 아니다 (2026-10-09 새벽).

숙제 3 판: 생각 예산 16,000자에 네 번 걸렸다(한 번에 130~200초). 입력 토큰으로 재 보니 우리가 `reasoning_effort` 칸에 실어 온
「보통」은 서버에 닿지 않았고, 운영 모델은 내내 틀의 기본값(가장 센 것)으로 생각하고 있었다. `think` 자리에 글자로 넣어야 닿는다.
숙제 5 판: 전체 시험이 300초 제한에 걸린 것을 「멈춘다」로 읽어 15분을 썼고, `Format-Table` 이 든 명령은 보안 설정 변경으로 막혔다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alture_jarvis import local_computer
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.tool_gateway import ToolGateway
from test_thinking_budget import _ANSWERED, _Client, _Response, _client, _thinking_lines


# ── 세기를 재서 정한다 ──────────────────────────────────────────────────────────


def _measuring(monkeypatch: Any, *, window: int, tokens: dict[Any, int]) -> tuple[Any, list[Any]]:
    client = _client(monkeypatch, [])
    asked: list[Any] = []
    monkeypatch.setattr(type(client), "_resident_window", lambda self, _model: window)

    def count(self, _model: str, think: Any, _context: int) -> int:  # type: ignore[no-untyped-def]
        asked.append(think)
        return tokens[think]

    monkeypatch.setattr(type(client), "_prompt_tokens_for", count)
    return client, asked


def test_a_level_that_leaves_the_front_alone_is_used(monkeypatch: Any) -> None:
    client, asked = _measuring(monkeypatch, window=131072, tokens={False: 29, "medium": 27})
    assert client.steady_think_level("m") == "medium"
    assert client.steady_think_level("m") == "medium"
    assert asked == [False, "medium"], "모델마다 한 번만 잰다"


def test_a_level_that_adds_a_sentence_at_the_front_is_not(monkeypatch: Any) -> None:
    client, _ = _measuring(monkeypatch, window=131072, tokens={False: 29, "medium": 65})
    assert client.steady_think_level("m") == ""


def test_a_model_that_refuses_the_level_keeps_the_old_way(monkeypatch: Any) -> None:
    client, _ = _measuring(monkeypatch, window=131072, tokens={False: 29, "medium": 0})
    assert client.steady_think_level("m") == ""


def test_a_model_that_is_not_loaded_is_not_measured_and_is_asked_again(monkeypatch: Any) -> None:
    client, asked = _measuring(monkeypatch, window=0, tokens={False: 29, "medium": 27})
    assert client.steady_think_level("m") == ""
    assert asked == [], "이 호출로 모델을 올리지 않는다"
    monkeypatch.setattr(type(client), "_resident_window", lambda self, _model: 65536)
    assert client.steady_think_level("m") == "medium", "올라온 뒤에는 잰다"


def test_only_a_code_job_at_medium_effort_sends_the_level(monkeypatch: Any) -> None:
    """조사·대화 판에는 싣지 않는다 — 운영에 올려 아홉 판을 재 보고 정했다(완료 7/9 → 6/9 · 얻는 것이 분명하지 않았다.
    숫자는 `OllamaClient._think_value` 의 설명에)."""
    client = _client(monkeypatch, [])
    monkeypatch.setattr(type(client), "steady_think_level", lambda self, _model: "medium")
    value = client._think_value
    assert value("m", role="code", profile="medium", think=True) == "medium"
    assert value("m", role="code", profile="balanced", think=True) == "medium"
    assert value("m", role="code", profile="deep", think=True) is True       # 「깊게」는 틀의 기본(가장 센 것) 그대로
    assert value("m", role="chat", profile="default", think=True) is True    # 조사·대화 판은 건드리지 않는다
    assert value("m", role="agent", profile="default", think=True) is True
    assert value("m", role="code", profile="medium", think=False) is False


def test_a_model_without_a_steady_level_still_gets_plain_true(monkeypatch: Any) -> None:
    client = _client(monkeypatch, [])
    monkeypatch.setattr(type(client), "steady_think_level", lambda self, _model: "")
    assert client._think_value("m", role="code", profile="medium", think=True) is True


def test_the_request_carries_the_level(monkeypatch: Any) -> None:
    client = _client(monkeypatch, [_Response([_ANSWERED])])
    monkeypatch.setattr(type(client), "steady_think_level", lambda self, _model: "medium")
    client.chat_messages_stream([{"role": "user", "content": "고쳐줘"}], think=True, role="code", inference_profile="medium")
    assert _Client.bodies[0]["think"] == "medium"


def test_with_a_steady_front_the_second_call_just_stops_thinking(monkeypatch: Any) -> None:
    """앞머리가 안 움직이는 세기로 생각하는 판은 예전 방식이 싸고 확실하다 — 생각을 켠 채 부른 두 번째 호출은 실제 판에서 네 번 모두 또 넘겼다."""
    client = _client(monkeypatch, [_Response(_thinking_lines(30_000)), _Response([_ANSWERED])])
    monkeypatch.setattr(type(client), "steady_think_level", lambda self, _model: "medium")
    monkeypatch.setattr(type(client), "think_moves_the_front", lambda self, _model: True)
    message = client.chat_messages_stream([{"role": "user", "content": "고쳐줘"}], think=True, role="code", inference_profile="medium")

    assert [body["think"] for body in _Client.bodies] == ["medium", False]
    assert message["_thinking_budget"]["second_pass"]["kept_thinking"] is False


# ── 셸: 디스크 포맷은 드라이브를 지목한 명령으로만 ───────────────────────────────


@pytest.mark.parametrize("command", [
    "Get-ChildItem -Recurse *.py | Sort-Object LastWriteTime -Descending | Select-Object -First 15 | Format-Table -AutoSize",
    "Get-Process | Format-List Name, Id",
    "Get-Date -Format yyyy-MM-dd",
    "python -c \"print('{:>8}'.format(3))\"",
])
def test_ordinary_formatting_is_not_a_security_change(command: str) -> None:
    assert local_computer._SHELL_NEVER.search(command) is None


@pytest.mark.parametrize("command", ["format C: /q", "FORMAT.COM d:", "diskpart", "certutil -hashfile a.txt", "Set-ExecutionPolicy Bypass", "net user someone /add"])
def test_the_dangerous_ones_are_still_refused(command: str) -> None:
    assert local_computer._SHELL_NEVER.search(command) is not None


# ── 시간 제한에 걸린 것은 멈춘 것이 아니다 ────────────────────────────────────────


def test_a_command_we_cut_off_says_that_we_cut_it_off(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(project), local_computer_enabled=True,
    )
    local = LocalComputerTools(config)
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    local.register(gateway)

    result = gateway.execute(
        "local_run_project_command",
        {"path": str(project), "command": ["python", "-c", "import time; print('started', flush=True); time.sleep(60)"], "timeout_sec": 5},
        job_id="code-1",
    )

    body = result.result
    assert body["timed_out"] is True and body["failure_kind"] == "timeout"
    note = body["timeout_note"]
    assert "5초" in note and "우리가 끊었다" in note and "멈췄다는 뜻이 아니다" in note


def test_a_command_that_finishes_carries_no_such_note(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(project), local_computer_enabled=True,
    )
    local = LocalComputerTools(config)
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    local.register(gateway)
    result = gateway.execute(
        "local_run_project_command", {"path": str(project), "command": ["python", "-c", "print(1)"], "timeout_sec": 30}, job_id="code-1",
    )
    assert "timeout_note" not in result.result


# ── 심볼 찾기에 파일을 주면 그 파일이 든 폴더에서 찾는다 (판 hw3 — 두 번 튕겼다) ──────────────


def test_find_symbol_given_a_file_looks_in_its_folder(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "pkg").mkdir(parents=True)
    (project / "pkg" / "mod.py").write_text("def lonely_helper():\n    return 1\n", encoding="utf-8")
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(project), local_computer_enabled=True,
    )
    local = LocalComputerTools(config)
    gateway = ToolGateway(JobStore(tmp_path / "data" / "jarvis.db"), EventBus())
    local.register(gateway)

    result = gateway.execute(
        "local_find_symbol", {"path": str(project / "pkg" / "mod.py"), "symbol": "lonely_helper"}, job_id="code-1",
    )

    assert result.ok is True, result.result
    assert "directory_required" not in str(result.result)
    assert "mod.py" in str(result.result.get("note") or "")
    assert "lonely_helper" in str(result.result)
