"""Code 모드에 **일할 자리**를 준다 (2026-09-20 사장님 지시: "깡성능을 최대치로").

## 왜 (재 보고 정한 값)

어려운 코딩 한 바퀴의 **최소 걸음**을 세어 보면 이렇다:

    색인 1 · grep 1~2 · 읽기 2~3 · 고치기 1~2 · 돌리기 1 · 실패 읽고 다시 고치기 2~3
    = 8~12 걸음

그런데 기본 예산이 **12** 였다. 한 바퀴를 겨우 돌고 끝나서, 시험이 빨간불인 채로
「승인하시겠습니까?」로 끝나는 판이 나왔다(2026-09-02 라이브에서 같은 모양을 이미 봤다).
**끈기가 모자란 게 아니라 자리가 없었다** — 이 저장소가 여러 번 밟은 그 함정이다.

## 무엇을 열었나

    걸음        Code 모드만 24 (일반 대화는 12 그대로)
    상한        Code 모드만 80 (일반 대화는 48 그대로)
    스크립트    `python foo.py` 를 **작업 폴더 안에서만** 허용 — 재현 스크립트를 짜 놓고
                못 돌리는 것이 제일 큰 막힘이었다. 밖의 스크립트는 그대로 막힌다.
    문서 읽기   `local_read_document` 를 Code 도구에 넣는다(저장소의 PDF·docx 설계문서).

상자(`sandbox_enabled`)는 **켜지 않는다.** 이 PC 의 WSL 은 진짜 상자가 아니고, 저장소 안에서
`pytest` 가 이미 임의 코드를 돌린다 — 위험은 그대로인데 판만 복잡해진다.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.code_runtime import CODE_CORE_TOOL_NAMES
from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def test_code_mode_gets_more_steps_than_a_chat_turn() -> None:
    config = JarvisConfig()
    assert config.ollama_max_tool_steps == 12, "일반 대화는 그대로 둔다"
    assert config.code_max_tool_steps >= 24, "한 바퀴(8~12걸음)에 실패 여유 두 바퀴"
    assert config.code_autonomous_max_steps >= 80


def test_the_budget_actually_reads_the_code_knob() -> None:
    """값만 만들고 안 쓰면 아무 일도 안 일어난다 — 이 저장소가 여러 번 겪은 자리."""
    source = inspect.getsource(BrowserAgent._step_budget)
    assert "code_max_tool_steps" in source
    assert "code_autonomous_max_steps" in source
    run = inspect.getsource(BrowserAgent.run)
    assert "_step_budget(plan, code=" in run, "판이 Code 인지 예산에 알려 줘야 한다"


def test_a_repro_script_inside_the_workspace_runs(tmp_path: Path) -> None:
    """★ 제일 큰 막힘이었다. 재현 스크립트를 짜 놓고 돌릴 수가 없었다."""
    work = tmp_path / "repo"
    work.mkdir()
    (work / "repro.py").write_text("print('재현됨')\n", encoding="utf-8")
    tools = LocalComputerTools(JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data",
        local_file_allowed_roots=str(work), local_read_roots=str(tmp_path),
    ))
    tools.authorize_code_workspace("code-job", str(work))
    out = tools.run_project_command(
        {"__job_id": "code-job", "path": str(work), "command": ["python", "repro.py"]}
    )
    assert "재현됨" in str(out.get("stdout") or "")


def test_a_script_outside_the_workspace_is_still_refused(tmp_path: Path) -> None:
    """★ 원래 막은 이유는 **바깥 스크립트를 부를 통로**였다. 그건 그대로 막혀야 한다."""
    work = tmp_path / "repo"
    work.mkdir()
    outside = tmp_path / "남의것.py"
    outside.write_text("print('열리면 안 된다')\n", encoding="utf-8")
    tools = LocalComputerTools(JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data",
        local_file_allowed_roots=str(work), local_read_roots=str(tmp_path),
    ))
    tools.authorize_code_workspace("code-job", str(work))
    for bad in (str(outside), "../남의것.py", "..\\남의것.py"):
        with pytest.raises(PermissionError):
            tools.run_project_command(
                {"__job_id": "code-job", "path": str(work), "command": ["python", bad]}
            )


def test_code_mode_can_read_design_documents() -> None:
    """저장소 안의 PDF·docx 설계문서를 못 읽으면 어려운 과제의 절반을 못 본다."""
    assert "local_read_document" in CODE_CORE_TOOL_NAMES


def test_the_sandbox_stays_off() -> None:
    """켜 두면 「막았다」는 착각만 생긴다 — 이 PC 의 WSL 은 상자가 아니다."""
    assert JarvisConfig().sandbox_enabled is False
