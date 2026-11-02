"""걸음마다 생각을 켰다 껐다 하지 않게 고르는 측정 스위치 (2026-10-31 대표 「한 번 막히면 쭉 깊게」)."""
from pathlib import Path
from types import SimpleNamespace

from alture_jarvis.agent import _KEEP_THINK_FOR_CACHE_CHARS, BrowserAgent


def _agent(tmp_path: Path, mode: str) -> SimpleNamespace:
    if mode:
        (tmp_path / "bench_overrides.json").write_text('{"think_stick": "%s"}' % mode, encoding="utf-8")
    return SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path), _last_think={})


def _call(agent, think, steps=1, chars=10):
    return BrowserAgent._steady_think(agent, "job", [{"content": "가" * chars}], [{}] * steps, think)


def test_default_leaves_the_policy_alone(tmp_path: Path) -> None:
    agent = _agent(tmp_path, "")
    assert [_call(agent, t) for t in (True, False, True, False)] == [True, False, True, False]


def test_sticky_keeps_thinking_once_it_started_after_the_first_step(tmp_path: Path) -> None:
    agent = _agent(tmp_path, "sticky")
    assert _call(agent, False) is False
    assert _call(agent, True) is True
    assert [_call(agent, False) for _ in range(3)] == [True, True, True]


def test_long_steady_keeps_the_last_setting_only_when_history_is_long(tmp_path: Path) -> None:
    agent = _agent(tmp_path, "long_steady")
    agent._last_think = {"job": False}
    assert _call(agent, True, chars=100) is True
    assert _call(agent, True, chars=_KEEP_THINK_FOR_CACHE_CHARS + 1) is False


def test_stuck_once_thinks_to_the_end_after_a_real_failure(tmp_path: Path) -> None:
    agent = _agent(tmp_path, "stuck_once")
    assert BrowserAgent._steady_think(agent, "job", [], [{"ok": True}], False) is False
    assert BrowserAgent._steady_think(agent, "job", [], [{"ok": True}, {"ok": False}], True) is True
    assert BrowserAgent._steady_think(agent, "job", [], [{"ok": True}, {"ok": False}, {"ok": True}], False) is True


def test_stuck_once_skips_one_step_flips_in_a_long_history(tmp_path: Path) -> None:
    agent = _agent(tmp_path, "stuck_once")
    agent._last_think = {"job": False}
    long = [{"content": "가" * (_KEEP_THINK_FOR_CACHE_CHARS + 1)}]
    assert BrowserAgent._steady_think(agent, "job", long, [{"ok": True}, {"ok": True}], True) is False
