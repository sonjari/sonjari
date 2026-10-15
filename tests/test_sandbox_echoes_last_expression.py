"""계산 상자는 마지막 식의 값을 **돌려준다** (2026-09-24 라이브).

「12, 15, 20 의 평균」에 모델이 `(12 + 15 + 20) / 3` 한 줄만 보냈다(세 판 모두). print 가 없어 stdout 이 비었고, 모델은
빈 결과를 받고 암산했다 — 근거 대조가 그 숫자를 「도구가 준 적 없는 숫자」로 **옳게** 찍었다. 고칠 곳은 상자였다.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from alture_jarvis.evidence import numbers_claimed_in, numbers_in_body
from alture_jarvis.sandbox import echo_last_expression


def _stdout(code: str) -> str:
    done = subprocess.run([sys.executable, "-c", echo_last_expression(code)], capture_output=True, text=True, timeout=30)
    return done.stdout.strip()


def test_a_bare_expression_prints_its_value_and_grounds_the_answer() -> None:
    out = _stdout("(12 + 15 + 20) / 3")
    assert out == "15.666666666666666"
    assert numbers_claimed_in("15.666666666666666") <= numbers_in_body({"stdout": out})


@pytest.mark.parametrize("code, expected", [
    ("x = 3\nx * 2", "6"),
    ("def f():\n    return 1\nf()", "1"),
    ("xs = [1,\n  2]\nsum(xs)", "3"),
])
def test_the_last_expression_is_echoed_like_a_repl(code: str, expected: str) -> None:
    assert _stdout(code) == expected


@pytest.mark.parametrize("code", ["a = 1", "(", "for i in range(2):\n    i"])
def test_code_that_is_not_a_trailing_value_is_left_alone(code: str) -> None:
    """★ 좋은 표본 — 대입·문법 오류·블록 끝은 손대지 않는다."""
    assert echo_last_expression(code) == code


def test_print_is_not_doubled_and_none_prints_nothing() -> None:
    assert _stdout("print(1)") == "1"
    assert _stdout("None") == ""


def test_a_rounded_tool_value_is_supported_but_a_rounded_integer_is_not() -> None:
    from alture_jarvis.evidence import unsupported_numbers

    seen = {"15.666666666666666"}
    assert unsupported_numbers({"15.67"}, seen) == set()
    assert unsupported_numbers({"15.7"}, seen) == set()
    # ★ 좋은 표본 — 반올림이 안 맞는 소수와 정수 반올림은 그대로 「근거 없음」.
    assert unsupported_numbers({"15.68"}, seen) == {"15.68"}
    assert unsupported_numbers({"16"}, seen) == {"16"}
