"""셸 명령을 뒤에서 띄우고 번호로 본다 (2026-11-08 게임 시험 2-2).

맥 손자리가 Unity Hub 명령줄 설치를 띄웠는데 셸 도구의 시간 제한(최대 600초)이 받기만 끝난 설치를 통째로 끊었다.
설치 · 빌드는 10분을 넘는 게 정상이고 윈도우도 같다 — 같은 도구에 「뒤에서 돌리기」 칸을 둔다.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import _SHELL_FORBIDDEN_PATHS, LocalComputerTools
from alture_jarvis.models import RiskLevel
from alture_jarvis.stuck_hands import _repeat_notice


def _tools(tmp_path: Path) -> LocalComputerTools:
    work = tmp_path / "work"
    work.mkdir()
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          local_file_allowed_roots=str(work), local_read_roots=str(tmp_path))
    tools = LocalComputerTools(config)
    tools.authorize_code_workspace("code-job", str(work))
    return tools


def _cmd(seconds: float, text: str) -> str:
    py = sys.executable.replace("\\", "/")
    # ★ 2026-11-12 공개 CI: 깃허브 윈도우 기계의 파이썬은 `C:/hostedtoolcache/windows/Python/…` 라 경로의 「/windows/」가
    #   셸 도구의 시스템 폴더 막기(`_SHELL_FORBIDDEN_PATHS`)에 걸렸다. 시험이 보는 것은 막기가 아니라 뒤에서 돌리기다 —
    #   그런 경로면 PATH 의 `python` 으로 부른다.
    if _SHELL_FORBIDDEN_PATHS.search(py):
        py = "python"
    code = f"import time,sys; print('{text}-시작', flush=True); time.sleep({seconds}); print('{text}-끝'); sys.exit(3)"
    return f'& "{py}" -c "{code}"' if sys.platform == "win32" else f'"{py}" -c "{code}"'


def test_background_runs_past_the_call_and_reports_by_id(tmp_path: Path, monkeypatch) -> None:
    tools = _tools(tmp_path)
    started = time.monotonic()
    out = tools.run_shell({"__job_id": "code-job", "command": _cmd(3, "설치"), "background": True})
    assert time.monotonic() - started < 2.5, "뒤에서 띄우면 바로 돌아와야 한다"
    assert out["background_id"].startswith("bg") and Path(out["log"]).name.endswith(".log")
    assert out["verified"] is False and "background_id" in out["instruction"]

    first = tools.run_shell({"background_id": out["background_id"]})
    assert first["state"] == "running" and first["exit_code"] is None and first["verified"] is False

    done = tools.run_shell({"background_id": out["background_id"], "wait_sec": 30})
    assert done["state"] == "finished"
    # 윈도우 PowerShell -Command 는 실패한 종료 값을 1 로 돌려준다(앞에서 띄우는 셸과 같다) — 0 이 아니면 확인된 게 아니다.
    assert done["exit_code"] not in (None, 0) and done["verified"] is False
    assert "설치-끝" in done["log_tail"]


def test_status_is_read_only_risk_and_unknown_id_is_refused(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    assert tools._shell_risk({"background_id": "bg0123abcd"}) == RiskLevel.L1
    assert tools._shell_risk({"command": "rm -rf build", "background": True}) == RiskLevel.L2, "띄우는 것은 그대로 승인"
    with pytest.raises(ValueError, match="background_id_unknown"):
        tools.run_shell({"background_id": "bg0123abcd"})
    with pytest.raises(ValueError, match="background_id_unknown"):
        tools.run_shell({"background_id": "../../etc/passwd"})
    with pytest.raises(ValueError, match="command_required"):
        tools.run_shell({})


def test_background_still_refuses_security_commands(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    command = "Set-MpPreference -DisableRealtimeMonitoring $true" if sys.platform == "win32" else "sudo spctl --master-disable"
    with pytest.raises(PermissionError):
        tools.run_shell({"__job_id": "code-job", "command": command, "background": True})


def test_repeat_notice_spares_a_running_background_check() -> None:
    running = {"ok": True, "result": {"background_id": "bg0123abcd", "state": "running"}}
    assert _repeat_notice(running, tool="local_run_shell", repeat_count=5, same_failure_count=0) is running
    finished = {"ok": True, "result": {"background_id": "bg0123abcd", "state": "finished"}}
    assert _repeat_notice(finished, tool="local_run_shell", repeat_count=5, same_failure_count=0)["result"]["repeat_notice"]


def test_unity_hub_without_headless_is_sent_back_before_it_hangs(tmp_path: Path) -> None:
    """11-08 2-2: `"…/Unity Hub" --version` 을 --headless 없이 불러 허브 창이 떴고 명령이 시간 제한까지 매달렸다."""
    from alture_jarvis.local_computer import _gui_app_refusal

    hub = '"/Applications/Unity Hub.app/Contents/MacOS/Unity Hub"'
    assert _gui_app_refusal(f"{hub} --version").startswith("gui_app_would_hang")
    assert _gui_app_refusal(f"{hub} -- --headless editors -i") == ""
    assert _gui_app_refusal('"C:/Program Files/Unity Hub/Unity Hub.exe" editors').startswith("gui_app_would_hang")
    assert _gui_app_refusal("ls /Applications") == ""
    tools = _tools(tmp_path)
    with pytest.raises(ValueError, match="gui_app_would_hang"):
        tools.run_shell({"__job_id": "code-job", "command": f"{hub} --version"})
