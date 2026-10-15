"""합격 시험 — agent.py 를 동작 그대로 줄인다. 맡기기 전에 썼다(2026-10-09).

`agent.py` 는 13,795줄이다. 소스를 열어 본 사람이 한 번에 읽을 수 없는 크기다(공개 뒤 기여자가 들어올 문을 막는다).
모듈 맨 바깥의 순수 함수·상수 묶음 하나를 새 모듈로 옮겨 300줄 이상 줄인다. 무엇을 옮길지는 맡은 쪽이 정한다.

이 파일이 보는 것은 셋뿐이다 — 줄었는가 · 옮긴 이름이 예전 자리에서도 불러와지는가 · 새 모듈이 실제로 생겼는가.
**동작이 그대로인지는 전체 회귀가 본다**(확인 명령에 같이 들어 있다). tests/ 밖에 있어 평소 회귀에는 안 잡힌다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import alture_jarvis
from alture_jarvis import agent

_PACKAGE = Path(alture_jarvis.__file__).parent
#: 맡기기 전에 agent 가 이미 함수를 가져다 쓰던 모듈(2026-10-09 에 뽑음). 여기 없는 모듈이 새로 생긴 것이다.
_HOMES_BEFORE = frozenset({
    "answer_audit", "ask_user", "claude_code", "clock", "code_runtime", "code_scout", "evidence", "grounding_scout",
    "human_gate", "mission", "narration", "number_checks", "ollama", "plan", "presentation", "search_typo",
    "site_atlas", "stray_han", "task_contract", "transcript",
})


def _outer_names(path: Path) -> set[str]:
    """모듈 맨 바깥에 **정의된** 함수·클래스·상수 이름(불러온 이름은 빼고)."""
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


# 줄 수 상한(13,795 − 300)은 **맡긴 판의 끝을 가르는 데만** 썼다. 여기(tests/)에 남기면 agent.py 를 고칠 때마다 떨어진다 —
# 가져온 지 세 시간 만에 다른 고침 둘이 얹히자 실제로 떨어졌다. 옮긴 것이 새 모듈에 있고 혼자 불러와지는지만 계속 본다.


def _new_homes() -> dict[str, list[str]]:
    """새로 생긴 모듈 → 그 모듈에 정의돼 있으면서 agent 에서도 불러와지는 함수 이름들."""
    found: dict[str, list[str]] = {}
    for name in dir(agent):
        value = getattr(agent, name)
        if value.__class__.__name__ != "function":
            continue
        home = str(getattr(value, "__module__", ""))
        if not home.startswith("alture_jarvis.") or home == "alture_jarvis.agent":
            continue
        stem = home.split(".", 1)[1]
        if stem not in _HOMES_BEFORE:
            found.setdefault(stem, []).append(name)
    return found


def test_the_lines_went_into_a_new_module_not_into_the_bin() -> None:
    """줄을 지워서 줄인 것이 아니다 — 새 모듈이 생겼고, 거기로 간 함수가 agent 에서도 여전히 불러와진다."""
    homes = _new_homes()
    assert homes, "새 모듈이 없다 — agent 에서 불러와지는 함수가 전부 예전부터 있던 모듈의 것이다"
    moved = sum(len(names) for names in homes.values())
    assert moved >= 5, f"새 모듈로 간 함수가 {moved}개뿐이다: {homes}"
    still_defined = _outer_names(_PACKAGE / "agent.py")
    for stem, names in homes.items():
        assert (_PACKAGE / f"{stem}.py").is_file()
        twice = sorted(set(names) & still_defined)
        assert not twice, f"{stem}.py 로 옮긴 것이 agent.py 에도 그대로 남아 있다(두 벌): {twice[:8]}"


def test_a_new_module_can_be_imported_on_its_own() -> None:
    """새 모듈을 **혼자** 불러와도 된다 — agent 를 먼저 불러와야만 되는 모듈이면 순환이다."""
    import subprocess
    import sys

    for stem in sorted(_new_homes()):
        done = subprocess.run(
            [sys.executable, "-c", f"import alture_jarvis.{stem}"],
            capture_output=True, text=True, cwd=str(_PACKAGE.parent),
        )
        assert done.returncode == 0, f"alture_jarvis.{stem} 를 혼자 불러오지 못한다: {done.stderr[-300:]}"
