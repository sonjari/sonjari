"""허용한 도구는 **실제로 깔려 있어야 한다** (2026-09-20 사장님 지적으로 드러남).

> "그. 패키지도 쥐어줬나"

## 재 보니 문만 열려 있었다

`_PYTHON_MODULES` 에 `ruff` 와 `mypy` 가 **이미 있었다.** 그런데 운영 venv 에는:

    ruff 없음 · mypy 없음 · black 없음 · pylint 없음 · bandit 없음

**갈래는 있는데 도구가 없었다.** 모델이 `python -m ruff check .` 를 부르면
`No module named ruff` 로 죽는다. 한두 번 죽으면 다시 안 부른다 — 오늘 코딩 과제에서
정적 분석을 한 번도 안 쓴 이유가 이것일 수 있다.

이 저장소가 아는 「도구를 만들어도 갈래가 없으면 안 쓰인다」의 **한 단계 더 나쁜 판**이다:
갈래는 있는데 그 끝에 아무것도 없다. 그리고 그건 **아무 시험도 안 보고 있었다.**

★ 그래서 이 파일은 「목록에 적힌 것 = 실제로 도는 것」을 붙든다. 둘이 갈리면 여기서 빨개진다.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from alture_jarvis.local_computer import _PYTHON_MODULES

#: 파이썬 표준에 이미 있는 것 — 따로 설치할 필요가 없다.
_STDLIB = {"unittest", "compileall", "py_compile"}


@pytest.mark.parametrize("module", sorted(_PYTHON_MODULES - _STDLIB))
def test_every_allowed_module_can_actually_run(module: str) -> None:
    """허용 목록의 모든 도구가 **지금 이 파이썬에서** 실제로 불린다.

    없으면 모델은 「허용된 도구」를 부르고 `No module named …` 를 받는다. 그건 막는 것보다
    나쁘다 — 막히면 다른 길을 찾지만, 있다고 했다가 없으면 자기가 틀린 줄 안다.
    """
    assert importlib.util.find_spec(module) is not None, (
        f"`python -m {module}` 을 허용해 놓고 설치는 안 했다. "
        f"requirements.txt 에 넣고 운영 venv 에도 깔아라."
    )


def test_the_linter_and_type_checker_are_in_the_toolchain() -> None:
    """코드 에이전트의 기본 연장 — 고친 뒤 스스로 확인할 수단이 있어야 한다."""
    for tool in ("ruff", "mypy"):
        assert tool in _PYTHON_MODULES, f"{tool} 를 Code 모드에서 못 부른다"


def test_ruff_really_finds_a_problem(tmp_path) -> None:
    """설치만 확인하지 않는다 — **실제로 일하는지** 본다(설치됐는데 못 도는 경우가 있다)."""
    bad = tmp_path / "bad.py"
    bad.write_text("import os\nx = 1\n", encoding="utf-8")   # os 를 안 쓴다 → F401

    done = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--select", "F401", str(bad)],
        capture_output=True, text=True, timeout=120,
    )

    assert done.returncode != 0, "안 쓰는 import 를 못 잡았다"
    assert "F401" in (done.stdout + done.stderr)


def test_the_model_is_told_these_exist() -> None:
    """★ 깔아 두기만 하면 안 쓴다. 도구 설명에 **있다고 적혀 있어야** 부른다."""
    from alture_jarvis.code_runtime import _QWEN_DESCRIPTIONS

    description = _QWEN_DESCRIPTIONS["local_run_project_command"]
    assert "ruff" in description and "mypy" in description, (
        "설명에 안 적으면 모델은 이 연장이 있는 줄 모른다 — "
        "「스킬 85개가 일에 닿지 않았다」와 같은 자리다."
    )


#: `python -m …` 명령이 아니라 **라이브러리**로 쓰는 연장 (2026-09-20 2단).
#:
#: 문법 검사만으로는 코드 에이전트가 안 된다. 이것들은 `python -c` 나 작업 폴더에 쓴
#: 스크립트에서 import 해서 쓴다 — 그래서 `_PYTHON_MODULES` 가 아니라 **설치**가 전부다.
CODE_LIBRARIES = {
    "jedi": "심볼 정의·참조 찾기",
    "libcst": "주석 보존 코드 변환",
    "hypothesis": "속성 기반 시험",
    "pandas": "표 데이터 분석",
    "numpy": "수치 계산",
    "yaml": "YAML 설정",
    "tomlkit": "TOML 주석 보존 편집",
    "bs4": "HTML 검증",
    "lxml": "빠른 HTML·XML 파서",
    "xdist": "시험 병렬 실행",
    "freezegun": "시간 고정 시험",
    "respx": "httpx 모킹",
    "line_profiler": "줄 단위 성능",
}


@pytest.mark.parametrize("module", sorted(CODE_LIBRARIES))
def test_every_declared_library_imports(module: str) -> None:
    """선언해 놓고 안 깔린 것이 없어야 한다 — 오늘 ruff·mypy 가 딱 그 상태였다."""
    assert importlib.util.find_spec(module) is not None, (
        f"{module}({CODE_LIBRARIES[module]}) 를 선언했는데 안 깔렸다. "
        "requirements.txt 와 pyproject.toml **둘 다** 확인하라 — "
        "pyproject 를 빠뜨리면 갱신(`pip install -e .`)으로는 영영 안 깔린다."
    )


def test_the_model_knows_the_libraries_exist() -> None:
    """★ 깔아 두기만 하면 안 쓴다. 시스템 안내에 **있다고 적혀 있어야** 집어 든다."""
    from alture_jarvis.code_runtime import CODE_LIBRARY_NOTE

    for key in ("jedi", "pandas", "hypothesis", "libcst"):
        assert key in CODE_LIBRARY_NOTE, f"{key} 가 안내에 없다 — 모델은 모른다"
