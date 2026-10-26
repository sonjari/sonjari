"""「막히면 내 클로드에게 넘기기」(2026-10-19) — 손자리가 막히면 사용자의 Claude Code 에 넘기는 기능을 사용자 설정으로.

지키는 것:
- 기본 꺼짐(코드 · .env 기본값 모두). 켜는 것은 사람이 설정 › 연결에서 한다 — 화면 값이 .env 의 0 을 이긴다.
- 측정 판은 켜 둬도 넘기지 않는다(2026-08-27: 24판 중 6판이 클로드에게 빠져 로컬 실력이 부풀었다).
- 클로드 명령 · 로그인이 없거나 관리자가 잠갔으면 켤 수 없고, 화면이 그 까닭을 말한다.
- 넘겼으면 답 · 진행 줄이 그렇게 말한다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from alture_jarvis import claude_code as cc
from alture_jarvis.api_escalation import hold_reason as esc_hold_reason
from alture_jarvis.claude_code import (
    CLAUDE_CODE_TOOL,
    ClaudeCodeError,
    ClaudeCodeTools,
    completion_answer,
    handoff_receipt,
    hold_reason,
    measurement_reason,
    with_handoff_receipt,
)
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.settings import BY_KEY, GROUPS, SettingsService

REPO = Path(__file__).resolve().parents[1]
READY = {"ok": True, "code": "", "reason": "", "short": ""}


def _config(tmp_path: Path, **overrides) -> JarvisConfig:
    values = dict(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                  local_file_allowed_roots=str(tmp_path))
    values.update(overrides)
    return JarvisConfig(**values)


def _row(view: dict, key: str = "claude_code_enabled") -> dict:
    return next(row for row in view["settings"] if row["key"] == key)


# ── 기본값 · 자리 ─────────────────────────────────────────────────────────


def test_default_is_off_in_code_and_in_env_loader(tmp_path: Path) -> None:
    assert JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data").claude_code_enabled is False
    # 새 파이썬으로 — 환경에 JARVIS_* 가 하나도 없을 때 로더의 기본값.
    env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    env.update({"JARVIS_RUNTIME_ROOT": str(tmp_path / "rt"), "PYTHONPATH": str(REPO / "src"),
                "USERPROFILE": str(tmp_path / "home"), "HOME": str(tmp_path / "home"), "PYTHONIOENCODING": "utf-8"})
    script = ("from alture_jarvis.config import JarvisConfig\n"
              "c = JarvisConfig.from_env()\n"
              "print(c.claude_code_enabled, c.claude_code_locked)\n")
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8",
                          env=env, timeout=120)
    assert done.returncode == 0, done.stderr[-800:]
    assert done.stdout.strip().splitlines()[-1] == "False False"


def test_the_switch_lives_in_connect_not_labs_and_applies_live(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cc, "cli_status", lambda _config: READY)
    setting = BY_KEY["claude_code_enabled"]
    assert setting.group == "connect" and setting.live and not setting.lab
    assert setting.label == "막히면 내 클로드에게 넘기기"
    assert "구독" in setting.help and "막혔을 때만" in setting.help
    # 왼쪽 목록에 「연결」 묶음을 하나 더 만들지 않는다 — 화면의 「사용자 지정 › 연결」이 그린다.
    assert "connect" not in {gid for gid, _ in GROUPS}
    row = _row(SettingsService(_config(tmp_path)).view())
    assert row["value"] is False and row["source"] == "default" and row["unavailable"] == ""


def test_screen_value_beats_env_zero(tmp_path: Path, monkeypatch) -> None:
    """운영 .env 의 JARVIS_CLAUDE_CODE_ENABLED=0 은 기본값일 뿐이다 — 사람이 켜면 켜진다."""
    monkeypatch.setattr(cc, "cli_status", lambda _config: READY)
    config = _config(tmp_path, claude_code_enabled=False)  # .env=0 과 같은 출발점
    result = SettingsService(config).patch({"claude_code_enabled": True})
    assert result["ok"] is True and result["applied"] == ["claude_code_enabled"]
    assert config.claude_code_enabled is True  # 바로 적용
    again = _config(tmp_path, claude_code_enabled=False)  # 다음 기동에도 화면 값이 이긴다
    assert again.claude_code_enabled is True


# ── 켰을 때만 넘긴다 ───────────────────────────────────────────────────────


class _OfflineClient:
    def __init__(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def get(self, url, **kwargs):
        return httpx.Response(200, json={"models": []}, request=httpx.Request("GET", url))
    def post(self, url, **kwargs):
        return httpx.Response(200, json={"message": {"content": "시험"}}, request=httpx.Request("POST", url))


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch):
    from alture_jarvis.runtime import JarvisRuntime

    monkeypatch.setattr(httpx, "Client", _OfflineClient)
    monkeypatch.setattr("alture_jarvis.config._default_backup_root", lambda: tmp_path / "backups")
    # 진짜 claude 를 찾지 않는다 — 있고 로그인된 척만(실행은 하지 않는다).
    monkeypatch.setattr(cc, "cli_status", lambda _config: READY)
    config = _config(tmp_path, documents_dir=tmp_path / "documents", claude_code_enabled=False,
                     voice_enabled=False, tts_enabled=False, hotkey_enabled=False, scheduler_enabled=False,
                     browser_enabled=False, memory_backup_dir=None,
                     sandbox_enabled=True)  # 코드 일 판정(`_requires_coding`)이 상자를 본다 — 상자를 돌리지는 않는다
    return JarvisRuntime(config)


#: `test_claude_code` 가 코드 일 · 다중 파일로 확인한 실제 문장.
MULTI_FILE = (
    "E:\\work\\repo 안의 여러 파일을 함께 수정해줘. "
    "alpha.py에 multiply를 추가하고 test_alpha.py에 그 테스트를 추가해서 "
    "pytest를 실제로 통과시켜줘."
)


def _tool_enabled(runtime, name: str) -> bool:
    return next(tool["enabled"] for tool in runtime.gateway.list_tools() if tool["name"] == name)


def test_off_by_default_then_on_offers_the_delegate_hand(runtime) -> None:
    assert _tool_enabled(runtime, CLAUDE_CODE_TOOL) is False
    assert runtime.claude_code.available("job-a") is False
    assert runtime._requires_claude_delegation(MULTI_FILE, job_id="job-a") is False

    assert runtime.settings.patch({"claude_code_enabled": True})["ok"] is True

    assert _tool_enabled(runtime, CLAUDE_CODE_TOOL) is True  # 다시 켜지 않아도 손이 열린다
    assert runtime.claude_code.available("job-a") is True
    assert runtime._requires_claude_delegation(MULTI_FILE, job_id="job-a") is True

    runtime.settings.patch({"claude_code_enabled": False})
    assert _tool_enabled(runtime, CLAUDE_CODE_TOOL) is False
    assert runtime._requires_claude_delegation(MULTI_FILE, job_id="job-a") is False


# ── 측정 판은 늘 꺼짐 ──────────────────────────────────────────────────────


@pytest.mark.parametrize("payload, session, expected", [
    ({"measurement": True}, "mcp-0123456789ab", "measurement_flag"),
    ({"caller": "bench-om2w"}, "mcp-0123456789ab", "measurement_caller"),
    ({"caller": "honesty-bench"}, "", "measurement_caller"),
    ({}, "code-repo-bench-multi_file-1756280000000", "measurement_session"),  # 2026-08-27 의 6/24 가 나온 스크립트
    ({}, "measure-chain-1a2b3c4d", "measurement_session"),
    ({}, "q4-golden-case-1", "measurement_session"),
    ({}, "ladder-t3-r1-1756280000", "measurement_session"),
    ({}, "route-probe-x-1-1756280000", "measurement_session"),
    ({"origin": "workspace"}, "c0ffee12-3456-7890-abcd-ef0123456789", ""),
    ({"origin": "mcp", "caller": "Claude Desktop"}, "mcp-0123456789ab", ""),
])
def test_measurement_runs_are_recognized(payload, session, expected) -> None:
    assert measurement_reason(payload, session) == expected


def test_a_job_handed_to_us_by_claude_code_is_not_handed_back() -> None:
    assert hold_reason({"origin": "mcp", "caller": "claude-code"}, "mcp-0123456789ab") == "delegated_by_claude_code"
    assert hold_reason({"origin": "mcp", "caller": "Discord"}, "discord-1") == ""  # 사람이 폰으로 시킨 판
    assert hold_reason({"origin": "workspace"}, "s-1") == ""


@pytest.mark.parametrize("caller", ["", "claude-ai", "Claude Desktop", "codex-mcp-client", "cursor-vscode", "remote-laptop"])
def test_any_outside_ai_job_stays_on_the_local_model(caller) -> None:
    # 2026-10-26 대표: 클로드 앱이 MCP 로 시킨 일은 무조건 로컬 — 부른 쪽 이름이 비어도(최근 14일 426판) 막는다.
    assert hold_reason({"origin": "mcp", "caller": caller}, "mcp-0123456789ab") == "delegated_by_outside_ai"
    assert esc_hold_reason({"origin": "mcp", "caller": caller}) == "delegated_by_outside_ai"
    assert esc_hold_reason({"origin": "mcp", "caller": caller, "api_escalation_measure": True}) == "delegated_by_outside_ai"


def test_measurement_job_is_forced_off_even_when_the_user_turned_it_on(runtime) -> None:
    runtime.settings.patch({"claude_code_enabled": True})
    runtime.claude_code.hold_for_job("bench-job", measurement_reason({}, "code-repo-bench-x-1"))

    assert runtime.claude_code.available("bench-job") is False
    assert runtime.claude_code.available("person-job") is True  # 다른 판은 그대로
    assert runtime._requires_claude_delegation(MULTI_FILE, job_id="bench-job") is False
    # 갈래 · 강제 호출이 놓쳐도 손 자체가 멈춘다.
    with pytest.raises(ClaudeCodeError, match="claude_code_off_for_measurement"):
        runtime.claude_code.delegate({"prompt": "x", "folder": str(runtime.config.runtime_root),
                                      "reason": "multi_file_request", "__job_id": "bench-job"})


def test_the_runner_holds_the_job_before_routing(runtime) -> None:
    """`_chat_job` 이 판 맨 앞에서 측정 판을 잡아 두는가 — 소스에서 갈래보다 앞인지 본다."""
    source = (REPO / "src" / "alture_jarvis" / "runtime.py").read_text(encoding="utf-8")
    hold = source.index("self.claude_code.hold_for_job(str(job[\"id\"]), hold_reason(payload, session_id))")
    route = source.index("route, routed_answer, routed_observation = self._general_route(")
    run = source.index("agent_result = self.agent.run(")
    assert hold < route < run


def test_measure_kit_marks_its_runs() -> None:
    source = (REPO / "src" / "alture_jarvis" / "measure_kit.py").read_text(encoding="utf-8")
    assert '"measurement": True' in source


# ── 켤 수 없을 때 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("code, short", [("not_installed", "Claude Code 없음"), ("not_signed_in", "로그인 필요"),
                                         ("locked", "관리자가 꺼 둠")])
def test_cannot_turn_on_without_cli_login_or_when_locked(tmp_path: Path, monkeypatch, code, short) -> None:
    reason, expected_short = cc.CLI_BLOCKS[code]
    assert expected_short == short
    monkeypatch.setattr(cc, "cli_status", lambda _config: {"ok": False, "code": code, "reason": reason, "short": short})
    config = _config(tmp_path)
    service = SettingsService(config)

    result = service.patch({"claude_code_enabled": True})

    assert result == {"ok": False, "error": "unavailable:claude_code_enabled"}
    assert config.claude_code_enabled is False
    assert not (tmp_path / "data" / "settings.json").exists()
    row = _row(service.view())
    assert row["unavailable"] == reason and row["unavailable_short"] == short
    # 끄는 것은 언제나 된다.
    assert service.patch({"claude_code_enabled": False})["ok"] is True


def test_lock_beats_a_saved_on_value(tmp_path: Path) -> None:
    config = _config(tmp_path, claude_code_enabled=True, claude_code_locked=True)
    tools = ClaudeCodeTools(config, EventBus(), LocalComputerTools(config))
    assert tools.switched_on() is False and tools.available() is False
    assert cc.cli_status(config)["code"] == "locked"


def test_cli_status_reads_files_only(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    config = _config(tmp_path, claude_code_command=str(tmp_path / "no-such-claude.exe"))
    assert cc.cli_status(config)["code"] == "not_installed"

    fake = tmp_path / "claude.exe"
    fake.write_text("", encoding="utf-8")
    config = _config(tmp_path, claude_code_command=str(fake))
    assert cc.cli_status(config)["code"] == "not_signed_in"

    (home / ".claude").mkdir()
    (home / ".claude" / ".credentials.json").write_text("{}", encoding="utf-8")
    assert cc.cli_status(config) == {"ok": True, "code": "", "reason": "", "short": ""}


# ── 넘겼으면 그렇게 말한다 ─────────────────────────────────────────────────


def _claude_step(*, ok: bool, status: str, reason: str = "tests_still_failing") -> dict:
    return {"tool": CLAUDE_CODE_TOOL, "ok": ok, "arguments": {"reason": reason},
            "evidence": {"status": status, "reason": reason} if ok else {}}


def test_completed_handoff_answer_says_so_with_the_reason() -> None:
    answer = completion_answer({"result": "두 파일을 고쳤고 pytest 3개 통과", "reason": "multi_file_request",
                                "total_cost_usd": 0.01})
    assert answer.endswith("이 일은 클로드(내 구독)에게 넘겨 처리했습니다 · 이유: 여러 파일을 함께 고치는 일이라서")
    # 영수증 줄을 두 번 붙이지 않는다.
    assert with_handoff_receipt(answer, [_claude_step(ok=True, status="completed")]) == answer


def test_failed_or_unfinished_handoff_is_still_reported() -> None:
    line = handoff_receipt([_claude_step(ok=False, status="")])
    assert line == "이 일을 클로드(내 구독)에게 넘겨 봤지만 끝내지 못했습니다 · 이유: 고친 뒤에도 테스트가 계속 실패해서"
    assert with_handoff_receipt("손자리가 직접 고쳤습니다.", [_claude_step(ok=False, status="")]).endswith(line)
    assert handoff_receipt([_claude_step(ok=True, status="waiting_continuation")]).startswith("이 일을 클로드(내 구독)에게 넘겨 봤지만")
    assert with_handoff_receipt("답", []) == "답"
    # 모르는 까닭 코드도 숨기지 않는다.
    assert handoff_receipt([_claude_step(ok=True, status="completed", reason="new_rule")]).endswith("이유: new_rule")


def test_live_progress_says_it_is_using_my_subscription(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "work"
    folder.mkdir()
    fake = tmp_path / "fake_claude.py"
    fake.write_text(
        "import json\n"
        "print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's',"
        " 'result': '끝', 'total_cost_usd': 0.0}), flush=True)\n",
        encoding="utf-8",
    )
    config = _config(tmp_path, claude_code_enabled=True)
    bus = EventBus()
    seen: list[str] = []
    original = bus.publish

    def capture(name, payload=None, *args, **kwargs):
        if name == "agent_progress":
            seen.append(str((payload or {}).get("message") or ""))
        return original(name, payload, *args, **kwargs)

    monkeypatch.setattr(bus, "publish", capture)
    tools = ClaudeCodeTools(config, bus, LocalComputerTools(config))
    monkeypatch.setattr(tools, "_command_prefix", lambda: [sys.executable, str(fake)])
    tools.delegate({"prompt": "고쳐", "folder": str(folder), "reason": "sandbox_same_file_failed_twice",
                    "__job_id": "job-1"})
    assert seen[0] == "막혀서 클로드(내 구독)에게 넘깁니다 · 이유: 같은 파일에서 두 번 막혀서"


def test_handoff_lines_have_english() -> None:
    from alture_jarvis import ui_i18n

    previous = ui_i18n.lang()
    ui_i18n._lang = "en"
    try:
        ui_i18n.reload()
        text = ui_i18n.translate_text(
            "끝\n\nClaude Code 완료 · 예상비용 $0.0100\n이 일은 클로드(내 구독)에게 넘겨 처리했습니다 · 이유: 같은 파일에서 두 번 막혀서")
        assert "Claude (your subscription)" in text and "it got stuck twice on the same file" in text
        assert "Claude Code done · estimated cost $0.0100" in text
        for short in ("관리자가 꺼 둠", "로그인 필요", "Claude Code 없음", "막히면 내 클로드에게 넘기기"):
            assert ui_i18n.translate_text(short) != short
    finally:
        ui_i18n._lang = previous
        ui_i18n.reload()
