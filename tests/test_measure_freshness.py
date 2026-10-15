"""재는 자가 **자기 규칙을 판(build)에도 쓰는가.**

## 왜 (2026-08-20)

`measure_autonomy.py` 는 맨 위에 이렇게 적어 두고 있다:

    표본이 적으면 비율을 내지 않고 **표본 수를 그대로 보여준다.**
    2 건 중 2 건 성공을 100% 라고 적는 순간 그 표가 거짓말을 시작한다.

그런데 그 규칙이 **날짜에만** 걸려 있었다. 판(build)에는 안 걸려서, 30일 평균이
`지금` 이라는 이름의 칸에 찍혔다. 실제로 그날 두 번 오독했다:

    "L4 52.8% · 요구가 남았는데 멈춤 105건"  → 105건 중 98건이 계측 전 옛 줄
    "site 요구 미달 5건 = 로그인 벽"          → 전부 그날 아침에 고쳐진 것

머리에 경고 한 줄은 있었다("이 표는 지금 코드를 말하지 않는다"). **안 먹었다** —
큰 숫자가 `지금` 칸에 있으면 사람은 큰 숫자를 읽는다. 그래서 둘 다 찍는다.

★ 이 저장소에서 재는 자에 검사가 붙은 것은 이번이 처음이다. 눈금이 틀리면
   그 위에서 내린 판단이 전부 틀린다 — 오늘 그것이 두 번 일어났다.
"""

from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_autonomy.py"
_spec = importlib.util.spec_from_file_location("measure_autonomy", _SCRIPT)
assert _spec and _spec.loader
ma = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ma)


def _result(*, current: dict | None = None, **over) -> dict:
    base = {
        "read": (96, 100),
        "write": (85, 100),
        "delegation": (52, 100),
        "prepare": (9, 10),
        "agent_runs": 100,
        "gate_waits": 0,
        "still_waiting": 0,
        "outcomes": Counter(),
        # 실제 자료 모양 그대로 — `tried`/`passed` 는 도구별 카운터다.
        "tried": Counter(),
        "passed": Counter(),
        "read_tools": Counter(),
        "pushbacks": (0, 0),
        "approvals": Counter(),
        "unknown_outcome": 0,
        "undo_offers": {},
        "build_filter": "",
        "builds": Counter({"oldbuild": 100}),
        "now_build": "newbuild",
        "toolless": 0,
        "toolless_sourced": 0,
    }
    base.update(over)
    if current is not None:
        base["current"] = current
    return base


# ── 규칙이 판에도 걸리는가 ───────────────────────────────────────────────────


def test_a_tiny_current_sample_never_becomes_a_percentage() -> None:
    """★ 2 건 중 2 건을 100% 로 적는 것을 이 파일이 금지한다."""
    text = ma.report(
        _result(current={"read": (2, 2), "write": (2, 2), "delegation": (2, 2)})
    )
    assert "100.0%" not in text, "표본 2건을 100% 라고 적었다"
    assert "표본 부족" in text


def test_the_current_build_row_is_always_shown_when_not_filtered() -> None:
    """없으면 사람은 전체 평균을 지금 성적으로 읽는다 — 실제로 그랬다."""
    text = ma.report(
        _result(current={"read": (0, 0), "write": (0, 0), "delegation": (0, 0)})
    )
    assert text.count("지금 판만") == 3, "세 단계 모두에 지금 판 줄이 있어야 한다"


def test_the_column_is_not_called_now_when_it_is_not_now() -> None:
    """★ `지금` 이라는 칸 이름이 거짓말의 몸통이었다."""
    stale = ma.report(
        _result(current={"read": (0, 0), "write": (0, 0), "delegation": (0, 0)})
    )
    header = next(line for line in stale.splitlines() if "단계" in line)
    assert "전체" in header and "지금" not in header


def test_a_build_filtered_run_keeps_calling_it_now() -> None:
    """`--build` 로 판을 지목했으면 그 표는 정말 그 판의 것이다."""
    text = ma.report(_result(build_filter="newbuild"))
    header = next(line for line in text.splitlines() if "단계" in line)
    assert "지금" in header
    assert "지금 판만" not in text


def test_zero_current_samples_says_zero_not_a_dash_alone() -> None:
    """0건이라는 사실 자체가 정보다 — 「아직 한 판도 안 돌았다」."""
    text = ma.report(
        _result(current={"read": (0, 0), "write": (0, 0), "delegation": (0, 0)})
    )
    assert "표본 부족 (0건)" in text


# ── 원래 있던 규칙이 안 깨졌는가 ─────────────────────────────────────────────


def test_the_small_sample_rule_still_holds_for_the_whole_table() -> None:
    assert "표본 부족" in ma._verdict(2, 2, 95)
    assert ma.MIN_SAMPLE >= 10


def test_a_healthy_sample_still_gets_a_verdict() -> None:
    assert "도달" in ma._verdict(96, 100, 95)
    assert "미달" in ma._verdict(52, 100, 70)


def test_the_stale_build_warning_line_survives() -> None:
    """표 밖의 경고도 그대로 둔다. 둘 다 있어야 한다 — 한쪽만으로는 안 먹혔다."""
    text = ma.report(
        _result(current={"read": (0, 0), "write": (0, 0), "delegation": (0, 0)})
    )
    assert "이 표는 지금 코드를 말하지 않는다" in text


def test_rows_line_up_across_levels() -> None:
    """★ 단계마다 한 칸씩 어긋나면 표로 읽히지 않는다. 한글 폭 보정이 상위
    라벨마다 달라서 실제로 어긋났었다."""
    text = ma.report(
        _result(current={"read": (9, 10), "write": (9, 10), "delegation": (9, 10)})
    )
    subs = [line for line in text.splitlines() if "지금 판만" in line]
    assert len(subs) == 3
    assert len({line.index("%") for line in subs}) == 1, "지금 판 줄이 서로 안 맞는다"
