"""이어 붙인 셸 명령은 **조각마다** 본다 (2026-09-23 이어받기 실측).

고친 온텔릭으로 이어받기를 사람 손 없이 돌렸더니 첫 셸 걸음에서 승인 카드가 떴다:

    cd <가지 폴더> && git status

맨 앞 이름(`cd`)만 보고 「모르는 명령」으로 판정해 L2 가 됐다. 폴더 이동은 아무것도 안 바꾸고
`git status` 는 보기만 한다 — 사람을 부를 일이 아니었다. 반대로, 느슨해지면 안 된다:
조각 하나라도 바꾸는 명령이면 지금처럼 승인이다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.models import RiskLevel


def _tools(tmp_path: Path) -> LocalComputerTools:
    work = tmp_path / "repo"
    work.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          local_file_allowed_roots=str(work), local_read_roots=str(tmp_path))
    tools = LocalComputerTools(config)
    tools.authorize_code_workspace("code-job", str(work))
    return tools


def _risk(tools: LocalComputerTools, command: str) -> RiskLevel:
    return tools._shell_risk({"__job_id": "code-job", "command": command})


@pytest.mark.parametrize("command", [
    "cd C:/work/8-1 && git status",
    "cd C:/work/8-1; git diff --stat",
    "Set-Location C:/work; git log --oneline -3",
    "git status && git diff",
    "git log | Select-String fix",
    "cd C:/work",
])
def test_looking_around_does_not_call_a_human(tmp_path: Path, command: str) -> None:
    assert _risk(_tools(tmp_path), command) == RiskLevel.L1, command


@pytest.mark.parametrize("command", [
    "cd C:/work && Remove-Item x.txt",
    "git status; del x.txt",
    "cd C:/work && git reset --hard",
    "git status && npm install left-pad",
    "Get-ChildItem | Remove-Item",
    "cd C:/work && git status > out.txt",
    "cd C:/work && notepad x.txt",
])
def test_one_changing_piece_still_needs_approval(tmp_path: Path, command: str) -> None:
    """★ 조각으로 나눈다고 느슨해지지 않는다 — 하나라도 바꾸거나 모르는 명령이면 L2."""
    assert _risk(_tools(tmp_path), command) == RiskLevel.L2, command
