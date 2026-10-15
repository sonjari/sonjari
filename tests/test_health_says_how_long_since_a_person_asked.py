"""`/health` 가 **마지막으로 사람이 시킨 지 얼마나 됐는지** 말한다 (2026-09-21).

## 왜 필요한가

밖에서 3090 을 건드리려는 쪽(문제은행 야간배치)이 「비켜야 하나」를 판단하려면
`state` 만으로는 모자란다. `state` 는 「지금 답하는 중인가」이고, 사람이 답을 읽고
다음 질문을 치는 30초 동안은 `idle` 이다. 배치가 정확히 그 틈으로 들어가 모델을
갈아 끼웠고, 다음 턴이 23GB 를 다시 올렸다 — 「생각하다 1분 멈춤」의 정체다.

★ **모르는 것과 0초를 섞지 않는다.** 한 번도 안 시켰으면 `None` 이다. 옛 판을 보는
  쪽이 「방금 썼다」로 오해하면 밤 생산이 통째로 죽는다.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from alture_jarvis.runtime import JarvisRuntime


class _Jobs:
    def __init__(self, rows: list[dict[str, Any]] | Exception) -> None:
        self._rows = rows

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:  # noqa: ARG002
        if isinstance(self._rows, Exception):
            raise self._rows
        return self._rows


def _ask(rows: list[dict[str, Any]] | Exception) -> float | None:
    runtime = JarvisRuntime.__new__(JarvisRuntime)
    runtime.store = _Jobs(rows)  # type: ignore[attr-defined]
    return runtime._seconds_since_user_activity()


def test_it_reads_the_attribute_the_runtime_actually_has() -> None:
    """★ 이 시험이 없어서 한 번 놓쳤다 (2026-09-21).

    처음 쓸 때 `self.jobs` 라고 썼는데 런타임의 진짜 이름은 `self.store` 다.
    `except` 가 그 AttributeError 를 삼켜 **조용히 `None`** 이 됐고, 시험은 가짜를
    같은 틀린 이름으로 붙여 놓아 같이 속았다. 라이브 `/health` 를 보고서야 잡았다.

    가짜를 쓰는 시험은 **가짜의 이름이 진짜와 같은지** 한 번은 확인해야 한다.
    """
    import inspect

    source = inspect.getsource(JarvisRuntime._seconds_since_user_activity)
    assert "self.store" in source, "런타임에 없는 이름을 읽고 있다"
    assert "self.jobs" not in source
    # 그리고 그 이름이 런타임 생성자에 실제로 있는지도 본다.
    assert "self.store = JobStore(" in inspect.getsource(JarvisRuntime.__init__)


def test_no_jobs_at_all_means_we_do_not_know() -> None:
    assert _ask([]) is None


def test_an_unreadable_store_means_we_do_not_know() -> None:
    """못 읽은 것을 0초로 내놓으면 밖에서 「방금 썼다」로 읽는다."""
    assert _ask(RuntimeError("DB 잠김")) is None


def test_a_recent_question_is_a_small_number() -> None:
    seconds = _ask([{"kind": "chat", "created_at": time.time() - 30, "updated_at": 0}])
    assert seconds is not None and 25 <= seconds <= 40


def test_an_old_question_is_a_big_number() -> None:
    seconds = _ask([{"kind": "chat", "created_at": time.time() - 7200, "updated_at": 0}])
    assert seconds is not None and seconds > 3600


def test_the_newest_job_wins_even_if_it_is_not_first() -> None:
    now = time.time()
    seconds = _ask([
        {"kind": "chat", "created_at": now - 9000, "updated_at": 0},
        {"kind": "chat", "created_at": now - 12, "updated_at": 0},
    ])
    assert seconds is not None and seconds < 30


def test_a_machine_job_does_not_count_as_a_person() -> None:
    """★ 밤새 스스로 도는 것을 사람으로 세면 비켜 주기가 영영 안 끝난다."""
    now = time.time()
    seconds = _ask([
        {"kind": "scheduled", "created_at": now - 5, "updated_at": 0},
        {"kind": "chat", "created_at": now - 7200, "updated_at": 0},
    ])
    assert seconds is not None and seconds > 3600, "예약 잡을 사람 활동으로 셌다"


def test_finishing_a_job_counts_as_activity_too() -> None:
    """답이 길게 이어지는 판은 만든 시각이 오래돼도 **아직 쓰는 중**이다."""
    now = time.time()
    seconds = _ask([{"kind": "chat", "created_at": now - 900, "updated_at": now - 10}])
    assert seconds is not None and seconds < 30


@pytest.mark.parametrize("kind", ["chat", "transcribe_command", "research", "vision"])
def test_the_kinds_people_actually_use_all_count(kind: str) -> None:
    seconds = _ask([{"kind": kind, "created_at": time.time() - 20, "updated_at": 0}])
    assert seconds is not None and seconds < 40, kind
