"""명령을 **문자열로 줘도 받는다** (2026-09-20, 내가 만든 회귀에서 드러남).

## 어떻게 찾았나

Code 모드에 연장(ruff·mypy·bandit…)을 쥐어 주면서 도구 설명을 이렇게 바꿨다:

    tests    python -m pytest -q
    lint     python -m ruff check .

그랬더니 모델이 `command` 를 **그 글자 그대로** 문자열로 넘기기 시작했고, 벽에 부딪쳤다:

    command_array_required × 7 · path_required × 3   (17걸음 중 10걸음을 버렸다)

**설명이 보여 준 모양과 도구가 받는 모양이 달랐다.** 설명을 고쳐 「배열로 주라」고 적을 수도
있지만, 이 저장소가 여러 번 배운 것은 **안내문은 안 먹는다**는 것이다(사고 R). 받아 주면 된다.

★ 받아 준다고 느슨해지지 않는다. 쪼갠 뒤 **똑같은 관문**을 지난다 — 프로그램 허용 목록,
  인자 검사, 셸 메타문자 차단. 달라지는 것은 「쪼개는 일을 누가 하느냐」뿐이다.

`path` 도 같다. 작업 폴더는 이미 잡에 묶여 있으니 안 주면 거기서 돈다 — 같은 날 아침
`local_glob`·`local_grep` 에 넣은 것과 같은 손질이다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _tools(tmp_path: Path) -> tuple[LocalComputerTools, Path]:
    work = tmp_path / "repo"
    work.mkdir()
    (work / "sample.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                          output_dir=tmp_path / "out",
                          local_file_allowed_roots=str(work), local_read_roots=str(tmp_path))
    tools = LocalComputerTools(config)
    tools.authorize_code_workspace("code-job", str(work))
    return tools, work


def test_a_plain_string_command_runs(tmp_path: Path) -> None:
    """★ 이것이 한 판에서 걸음 일곱을 버린 자리다."""
    tools, work = _tools(tmp_path)

    out = tools.run_project_command(
        {"__job_id": "code-job", "path": str(work), "command": "python -c \"print(40+2)\""}
    )

    assert out["exit_code"] == 0 and "42" in str(out)


def test_the_work_folder_is_the_default(tmp_path: Path) -> None:
    """`path` 를 안 줘도 잡에 묶인 작업 폴더에서 돈다."""
    tools, _work = _tools(tmp_path)

    out = tools.run_project_command({"__job_id": "code-job", "command": "python -m ruff --version"})

    assert out["exit_code"] == 0


def test_a_string_command_goes_through_the_same_gate(tmp_path: Path) -> None:
    """★ 받아 준다고 느슨해지지 않는다 — 쪼갠 뒤 **똑같은 관문**을 지난다."""
    tools, work = _tools(tmp_path)

    for blocked in (
        "powershell Get-ChildItem",          # 허용 목록 밖 프로그램
        "git reset --hard",                  # 허용 목록 밖 git
        "python -m pip uninstall requests",  # 허용 목록 밖 pip 하위명령
        "git status && git clean -fd",       # 셸 메타문자
    ):
        with pytest.raises((PermissionError, ValueError)):
            tools.run_project_command(
                {"__job_id": "code-job", "path": str(work), "command": blocked}
            )


def test_quoted_arguments_survive_the_split(tmp_path: Path) -> None:
    """따옴표 안의 공백을 쪼개면 인자가 통째로 달라진다 — 그러면 받아 준 의미가 없다."""
    tools, work = _tools(tmp_path)

    out = tools.run_project_command(
        {"__job_id": "code-job", "path": str(work),
         "command": "python -c \"print('한 칸 띄운 말')\""}
    )

    assert "한 칸 띄운 말" in str(out.get("stdout") or "")


def test_a_bracketed_string_is_unwrapped_into_the_same_command() -> None:
    """2026-10-01 밤 Ornith 1.5 35B: 배열을 `"[python -m pytest -q]"` 글자로 보내 첫 낱말이 `[python` 이 되어 세 번 거절됐다.
    코드는 이미 맞게 고친 판이 「확인 안 함」으로 실패했다. 풀어서 받고, 아래 관문은 그대로 지난다."""
    from alture_jarvis.local_computer import LocalComputerTools

    for raw in ("[python -m pytest -q]", "[python, -m, pytest, -q]", '["python", "-m", "pytest", "-q"]'):
        assert LocalComputerTools._validated_project_command(raw)[0] == ["python", "-m", "pytest", "-q"], raw
    import pytest as _pytest

    with _pytest.raises(PermissionError):
        LocalComputerTools._validated_project_command("[browser_search, x]")
