"""진짜 셸을 준다 — **창은 안 뜨고, 바꾸는 명령은 사람 앞에 선다** (2026-09-20 사장님 지시).

## 왜 (조사 결과)

커서·윈드서프·클로드 코드 **셋 다 진짜 셸을 준다**:

    커서        run_terminal_cmd  + Run Mode(언제 묻고 언제 샌드박스에 넣을지)
    윈드서프    Run Command       + 단계마다 diff 승인
    클로드 코드 Bash (제한 없음)  + 권한 모드

온텔릭만 허용 목록 8개(`python`·`pytest`·`npm`·`cargo`·`git`…)로 묶여 있었다. 실전에서
`flake8` 을 두 번 시도했다가 `project_command_not_allowed` 로 막혔다 — 조사하러 온 판에서
연장을 못 집는다.

★ 그들의 안전 모델은 **허용 목록이 아니라 승인**이다. 우리도 거기로 간다:

    L1  보기만 하는 명령        — 막힘없이 돈다 (조사는 멈추지 않는다)
    L2  바꾸는 명령             — 승인 카드. 설정에서 「자동 실행」을 켜면 작업 폴더 안에서는 L1
    거부 보안 설정·시스템 폴더  — **토글과 무관하게 언제나 거부** (전역 규칙: 보안 설정은 사람이)

그리고 **검은 창이 화면에 뜨지 않는다.** 사장님이 못 박은 조건이다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.models import RiskLevel


def _tools(tmp_path: Path, **over) -> tuple[LocalComputerTools, Path]:
    work = tmp_path / "repo"
    work.mkdir(parents=True)
    (work / "sample.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                          output_dir=tmp_path / "out",
                          local_file_allowed_roots=str(work),
                          local_read_roots=str(tmp_path), **over)
    tools = LocalComputerTools(config)
    tools.authorize_code_workspace("code-job", str(work))
    return tools, work


def _risk(tools: LocalComputerTools, command: str) -> RiskLevel:
    return tools._shell_risk({"__job_id": "code-job", "command": command})


# ── 위험 판정 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("command", [
    "dir",
    "Get-ChildItem -Recurse -Filter *.py",
    "Select-String -Path *.py -Pattern monthly_fee",
    "Get-Content sample.py",
    "git log --oneline -5",
    "python --version",
    "where python",
])
def test_looking_around_needs_no_approval(command: str, tmp_path: Path) -> None:
    """★ 조사는 멈추지 않는다 — 이게 셸을 주는 이유다."""
    tools, _work = _tools(tmp_path)
    assert _risk(tools, command) == RiskLevel.L1, command


@pytest.mark.parametrize("command", [
    "Remove-Item sample.py",
    "New-Item -ItemType File new.txt",
    "pip install requests",
    "Invoke-WebRequest https://example.invalid",
    "Stop-Process -Name notepad",
])
def test_changing_things_asks_first(command: str, tmp_path: Path) -> None:
    tools, _work = _tools(tmp_path)
    assert _risk(tools, command) == RiskLevel.L2, command


def test_the_autorun_switch_lets_the_work_folder_run_free(tmp_path: Path) -> None:
    """사장님 요청: 기본은 승인, **버튼을 켜면** 자동 실행 (커서의 Run Mode 와 같은 자리)."""
    tools, _work = _tools(tmp_path, shell_autorun_enabled=True)
    assert _risk(tools, "Remove-Item sample.py") == RiskLevel.L1
    assert _risk(tools, "New-Item -ItemType File new.txt") == RiskLevel.L1


@pytest.mark.parametrize("command", [
    "Set-MpPreference -DisableRealtimeMonitoring $true",
    "Add-MpPreference -ExclusionPath C:\\",
    "netsh advfirewall set allprofiles state off",
    "certutil -addstore root bad.cer",
    "reg delete HKLM\\SOFTWARE\\Policies /f",
    "Remove-Item C:\\Windows\\System32 -Recurse",
])
def test_security_settings_are_never_opened(command: str, tmp_path: Path) -> None:
    """★ 승인으로도, 자동 실행을 켜도 **안 연다.** 보안 설정은 사람이 직접 한다(전역 규칙)."""
    for over in ({}, {"shell_autorun_enabled": True}):
        tools, _work = _tools(tmp_path / f"case{len(over)}", **over)
        with pytest.raises(PermissionError):
            tools.run_shell({"__job_id": "code-job", "command": command})


# ── 실제로 도는가 ────────────────────────────────────────────────────────────

def test_it_actually_runs_and_reads_korean(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    (work / "메모.txt").write_text("한글 내용\n", encoding="utf-8")

    out = tools.run_shell({"__job_id": "code-job", "command": "Get-Content 메모.txt"})

    assert out["exit_code"] == 0
    assert "한글 내용" in str(out.get("stdout") or "")


def test_it_runs_in_the_work_folder(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    out = tools.run_shell({"__job_id": "code-job", "command": "Get-Location"})
    assert str(work).lower() in str(out.get("stdout") or "").lower()


def test_the_black_window_never_shows(tmp_path: Path) -> None:
    """★ 사장님이 못 박은 조건 — 검은 창이 화면에 뜨면 안 된다."""
    import inspect

    source = inspect.getsource(LocalComputerTools.run_shell)
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert "CREATE_NO_WINDOW" in code, "창을 숨기라고 말하지 않으면 뜬다"


def test_the_tool_is_registered_everywhere() -> None:
    """도구를 만들어도 등록 자리를 빠뜨리면 모델은 못 부른다 — 이 저장소의 단골 함정."""
    import inspect

    from alture_jarvis.code_runtime import CODE_CORE_TOOL_NAMES

    register = inspect.getsource(LocalComputerTools.register)
    assert '"local_run_shell": self.run_shell' in register
    assert '"local_run_shell": RiskLevel.L2' in register      # 바닥은 L2, 동적으로 내려간다
    assert "local_run_shell" in CODE_CORE_TOOL_NAMES
