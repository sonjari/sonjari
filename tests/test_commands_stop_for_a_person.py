"""도는 명령도 「그만」을 듣는다 — 맡긴 판이 긴 명령을 돌리는 중에 사람이 오면 끊고 비켜 준다 (2026-10-10).

2026-10-09 밤의 실제 판: 맡긴 판이 3분짜리 전체 시험을 돌리는 동안 사람의 요청이 206초를 기다렸다. 걸음 사이와 모델이
생각하는 도중에는 비켰지만(2초 안), 명령이 도는 중에는 들을 귀가 없었다.
"""
from __future__ import annotations

import sys
import threading
import time

from alture_jarvis import local_computer
from alture_jarvis.local_computer import STOPPED_EXIT_CODE, run_captured, stop_commands_when

_SLEEPER = [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(120)"]
_QUICK = [sys.executable, "-c", "print('done')"]


def _run(command: list[str], timeout_sec: float = 150.0) -> tuple[int, bytes, bytes, bool, float]:
    started = time.monotonic()
    code, out, err, timed_out = run_captured(command, cwd=None, env=None, timeout_sec=timeout_sec)
    return code, out, err, timed_out, time.monotonic() - started


def test_a_running_command_stops_when_asked(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(local_computer, "_STOP_POLL_SEC", 0.3)
    asked_at = time.monotonic() + 1.0
    with stop_commands_when(lambda: time.monotonic() >= asked_at) as was_stopped:
        code, out, _err, timed_out, took = _run(_SLEEPER)
    assert was_stopped()
    assert code == STOPPED_EXIT_CODE
    assert not timed_out, "끊긴 것은 시간 제한에 걸린 것이 아니다 — 모델에게 「느리다」로 읽히면 안 된다"
    assert b"started" in out, "끊기기 전에 나온 출력은 버리지 않는다"
    assert took < 30, f"120초짜리 명령이 {took:.0f}초 뒤에야 끊겼다"


def test_whether_it_was_stopped_can_be_asked_after_the_block(monkeypatch) -> None:  # noqa: ANN001
    """처음 짠 것은 블록을 나오면 표시가 지워졌다 — 묻는 자리는 늘 블록 밖이다."""
    monkeypatch.setattr(local_computer, "_STOP_POLL_SEC", 0.3)
    with stop_commands_when(lambda: True) as was_stopped:
        _run(_SLEEPER)
    assert was_stopped()
    with stop_commands_when(lambda: False) as was_stopped:
        code, *_ = _run(_QUICK)
    assert code == 0
    assert not was_stopped()


def test_without_anyone_listening_a_command_runs_as_before() -> None:
    code, out, _err, timed_out, _took = _run(_QUICK)
    assert (code, timed_out) == (0, False)
    assert b"done" in out


def test_the_time_limit_still_works_while_listening(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(local_computer, "_STOP_POLL_SEC", 0.3)
    with stop_commands_when(lambda: False) as was_stopped:
        code, _out, _err, timed_out, took = _run(_SLEEPER, timeout_sec=1.5)
    assert (code, timed_out) == (124, True)
    assert not was_stopped()
    assert took < 30


def test_a_broken_question_does_not_stop_the_command(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(local_computer, "_STOP_POLL_SEC", 0.2)

    def broken() -> bool:
        raise RuntimeError("줄을 못 읽었다")

    with stop_commands_when(broken) as was_stopped:
        code, out, _err, timed_out, _took = _run([sys.executable, "-c", "import time; time.sleep(1); print('done')"])
    assert (code, timed_out) == (0, False)
    assert b"done" in out
    assert not was_stopped()


def test_only_the_thread_that_asked_is_listened_to(monkeypatch) -> None:  # noqa: ANN001
    """귀는 판을 도는 스레드에만 달린다 — 그 사이 다른 요청이 돌리는 명령은 끊기지 않는다."""
    monkeypatch.setattr(local_computer, "_STOP_POLL_SEC", 0.2)
    elsewhere: dict[str, object] = {}

    def other_request() -> None:
        elsewhere["result"] = _run([sys.executable, "-c", "import time; time.sleep(1.5); print('done')"])

    with stop_commands_when(lambda: True) as was_stopped:
        worker = threading.Thread(target=other_request)
        worker.start()
        worker.join(timeout=60)
    code, out, _err, timed_out, _took = elsewhere["result"]  # type: ignore[misc]
    assert (code, timed_out) == (0, False)
    assert b"done" in out
    assert not was_stopped()


def test_listening_ends_with_the_block(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(local_computer, "_STOP_POLL_SEC", 0.2)
    with stop_commands_when(lambda: True):
        pass
    code, out, _err, timed_out, _took = _run([sys.executable, "-c", "import time; time.sleep(1); print('done')"])
    assert (code, timed_out) == (0, False)
    assert b"done" in out
