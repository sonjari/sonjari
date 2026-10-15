"""모델이 `old`·`new` 를 **똑같이 평평하게** 보내면서 `new` 에 줄을 더 넣었을 때 — 짐작 없이 되살리거나, 모르면 포기한다.

★ 2026-09-28 헤르메스 대결 T7: O1~O3 세 판 모두 **첫 편집이 실패**했다. O2·O3 은 `new` 앞에 `import math` 와 빈 줄을 더 넣었고,
줄 수가 달라 들여쓰기 구제(`_reindent_like_file`)가 포기 → 도구는 「100% 비슷」이라 말하고도 거절 → 모델 왕복 한 번 더.
헤르메스는 같은 과제를 27~34초에 끝냈고 우리는 82~101초였다(차이는 모델 밖).
"""
from __future__ import annotations

from alture_jarvis.local_computer import _rescue_edit

PAGER = (
    'def page_count(total_items, page_size):\r\n'
    '    """전체 항목 수와 한 페이지 크기로 페이지 수를 구한다."""\r\n'
    '    return total_items // page_size'
)
O2_OLD = 'def page_count(total_items, page_size):\n"""전체 항목 수와 한 페이지 크기로 페이지 수를 구한다."""\nreturn total_items // page_size'
O2_NEW = ('import math\n\ndef page_count(total_items, page_size):\n"""전체 항목 수와 한 페이지 크기로 페이지 수를 구한다."""\n'
          'return math.ceil(total_items / page_size)')


def _apply(text: str, old: str, new: str) -> str | None:
    found, replacement, _how = _rescue_edit(text, old, new)
    return text.replace(found, replacement, 1) if found else None


def test_the_o2_edit_lands_in_one_go() -> None:
    out = _apply(PAGER, O2_OLD, O2_NEW)
    assert out == (
        'import math\r\n\r\ndef page_count(total_items, page_size):\r\n'
        '    """전체 항목 수와 한 페이지 크기로 페이지 수를 구한다."""\r\n'
        '    return math.ceil(total_items / page_size)'
    )
    compile(out, "pager.py", "exec")


def test_a_line_added_right_after_a_block_opener_goes_into_the_body() -> None:
    text = "def f(x):\n    y = x + 1\n    return y\n"
    out = _apply(text, "def f(x):\ny = x + 1\nreturn y", "def f(x):\nassert x >= 0\ny = x + 1\nreturn y")
    assert out == "def f(x):\n    assert x >= 0\n    y = x + 1\n    return y\n"


def test_an_added_block_opener_is_refused() -> None:
    """끼운 줄이 블록을 열면 그 속 깊이를 모른다 — 틀리면 문법은 맞는 **다른 코드**가 된다."""
    text = "def f(x):\n    y = x + 1\n    return y\n"
    assert _apply(text, "def f(x):\ny = x + 1\nreturn y",
                  "def f(x):\nif x < 0:\nraise ValueError\ny = x + 1\nreturn y") is None


def test_a_line_added_between_different_depths_is_refused() -> None:
    """`if` 속 마지막 줄과 밖의 줄 사이에 끼운 줄 — 안인지 밖인지 모른다."""
    text = "def f(a):\n    if a:\n        b()\n    c()\n"
    assert _apply(text, "if a:\nb()\nc()", "if a:\nb()\nd()\nc()") is None


def test_a_line_added_after_the_last_line_is_refused() -> None:
    text = "def f(a):\n    if a:\n        b()\n"
    assert _apply(text, "if a:\nb()", "if a:\nb()\nc()") is None


def test_partial_indentation_from_the_model_is_left_to_the_old_path() -> None:
    """모델이 들여쓰기를 일부라도 줬으면 뜻이 있다 — 이 구제는 안 나선다."""
    text = "def f(x):\n    y = x + 1\n    return y\n"
    found, _new, how = _rescue_edit(text, "def f(x):\ny = x + 1\nreturn y", "import os\ndef f(x):\n    y = x + 2\nreturn y")
    assert how != "indentation_from_file" or found == ""
