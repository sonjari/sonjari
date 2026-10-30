"""손자리가 뒤에서 부르는 명령줄 도구는 **콘솔 창을 띄우지 않는다** (2026-10-30 · 10-29 촬영 중 일하는 도중 콘솔 창이 앞으로 튐).

백엔드는 창 없는 파이썬으로 돈다. 그런 프로세스가 `nvidia-smi` · `taskkill` · `git` 같은 명령줄 도구를 부르면 윈도우가
**새 콘솔 창**을 만든다 — 사람이 쓰는 화면 앞으로 튀어나온다. 그날 원문 기록: 「일하는 도중에 새 콘솔 창이 앞으로 튀어나온 것은 손자리 버그 후보」.
세어 보니 `subprocess` 호출 39곳 중 16곳에 창 숨김(`CREATE_NO_WINDOW`)이 없었다. 한 곳만 고치면 다음에 또 빠진다 —
그래서 **새로 생기는 호출도** 이 시험이 막는다. 사람에게 보여야 하는 창(탐색기 · 사람이 고른 앱 열기)만 이름을 박아 둔다.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis"
CALLS = {"run", "Popen", "check_output", "check_call", "call"}

#: 일부러 창을 보이는 호출 — (파일, 그 줄에 들어 있는 글자). 둘 다 GUI 프로그램이라 콘솔 창과 상관없다.
VISIBLE_ON_PURPOSE = {
    ("runtime.py", '"explorer.exe"'),          # 만든 파일을 탐색기에서 짚어 보이기
    ("local_computer.py", "subprocess.Popen([exe"),  # 사람이 고른 앱으로 파일 열기(허용 목록의 실행 파일)
}


def _calls_without_flag() -> list[str]:
    missing: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in CALLS):
                continue
            owner = node.func.value
            if not (isinstance(owner, ast.Name) and owner.id in {"subprocess", "_sp", "sp", "_subprocess"}):
                continue
            keywords = {keyword.arg for keyword in node.keywords}
            if "creationflags" in keywords or None in keywords:   # **kwargs 로 넘기면 그쪽이 책임진다
                continue
            text = "\n".join(lines[node.lineno - 1: node.end_lineno])
            if any(path.name == name and needle in text for name, needle in VISIBLE_ON_PURPOSE):
                continue
            missing.append(f"{path.relative_to(SRC)}:{node.lineno}")
    return missing


def test_every_background_command_hides_its_console_window() -> None:
    missing = _calls_without_flag()
    assert not missing, "창 숨김 없이 부르는 자리: " + ", ".join(missing) + \
        ' — creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) 를 붙이거나, 정말 보여야 하면 VISIBLE_ON_PURPOSE 에 까닭과 함께'


def test_the_guard_really_looks() -> None:
    """역방향 — 이 검사가 빈손으로 통과하지 않는다: 창 숨김을 단 호출이 실제로 여럿 있고, 예외 둘도 실제로 있다."""
    flagged = 0
    found_visible = set()
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        flagged += source.count('creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)')
        for name, needle in VISIBLE_ON_PURPOSE:
            if path.name == name and needle in source:
                found_visible.add((name, needle))
    assert flagged >= 14
    assert found_visible == VISIBLE_ON_PURPOSE, "예외로 박은 자리가 사라졌으면 목록에서도 뺀다"
