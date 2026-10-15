"""`run()` 안의 `:=` 가 판의 변수를 덮지 않는다 (2026-09-30 촬영 판 9f4e17c5).

글 질문을 카드로 바꾸는 조건에 `(asked := question_from_text(...))` 를 썼는데, `asked` 는 **사용자가 시킨 요청 문장**이었다.
질문이 아닌 답이 나올 때마다 요청이 `None` 으로 덮여, 답을 마무리하는 `named_sources(asked)` 에서
`'NoneType' object has no attribute 'split'` 로 판이 죽었다 — 파일을 쓰고 실행까지 마친 판이었다. 운영에도 올라가 있었다.
`:=` 는 조건 안에서 조용히 바깥 변수를 바꾼다. 이름이 겹치는지 구조로 본다.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from alture_jarvis.agent import BrowserAgent


def _names(func) -> tuple[set[str], dict[str, int]]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    assigned: set[str] = set()
    walrus: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.NamedExpr):
            walrus[node.target.id] = node.lineno
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        assigned.add(sub.id)
        elif isinstance(node, (ast.For, ast.comprehension)):
            for sub in ast.walk(node.target):
                if isinstance(sub, ast.Name):
                    assigned.add(sub.id)
        elif isinstance(node, ast.arg):
            assigned.add(node.arg)
    return assigned, walrus


def test_no_walrus_target_shares_a_name_with_a_run_variable() -> None:
    assigned, walrus = _names(BrowserAgent.run)

    clashes = {name: line for name, line in walrus.items() if name in assigned}

    assert not clashes, f"`:=` 가 run() 의 변수를 덮는다: {clashes}"


def test_the_check_would_have_caught_the_real_bug() -> None:
    """눈금 역검증 — 실제로 있던 모양을 넣으면 잡는다."""
    def run(prompt: str) -> str:
        asked = prompt
        if (asked := None) is not None:  # noqa: F841
            pass
        return asked or ""

    assigned, walrus = _names(run)

    assert "asked" in walrus and "asked" in assigned
