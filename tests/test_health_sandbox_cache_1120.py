"""`/health` 의 상자 칸은 앞 답을 잠깐 쓴다 (2026-11-20).

클로드 연결 서버가 30초마다 `/health` 를 묻고, 그때마다 `sandbox.status()` 가 `wsl.exe` 를 돌려 WSLg 의 보이지 않는
`msrdc.exe` 창이 키보드 초점을 뺏었다. 상자 칸은 잘 붙으면 5분, 못 붙으면 30초 앞 답을 쓴다.
"""
from __future__ import annotations

import types

from alture_jarvis import runtime as rt


class _Box:
    def __init__(self, reachable: bool = True) -> None:
        self.calls = 0
        self.reachable = reachable

    def status(self):
        self.calls += 1
        return {"enabled": True, "reachable": self.reachable, "isolated": True}


def _owner(box: _Box):
    o = types.SimpleNamespace(sandbox=box,
                              SANDBOX_HEALTH_TTL_SEC=rt.JarvisRuntime.SANDBOX_HEALTH_TTL_SEC,
                              SANDBOX_HEALTH_RETRY_SEC=rt.JarvisRuntime.SANDBOX_HEALTH_RETRY_SEC)
    return o


def _call(o):
    return rt.JarvisRuntime._sandbox_health(o)


def test_health_every_30s_does_not_run_wsl_each_time(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(rt.time, "monotonic", lambda: clock[0])
    box = _Box()
    o = _owner(box)
    for _ in range(10):  # 연결 서버처럼 30초마다 5분 가까이
        assert _call(o)["reachable"] is True
        clock[0] += 29.0
    assert box.calls == 1  # 10번 물어도 wsl.exe 는 한 번
    clock[0] += 300.0
    _call(o)
    assert box.calls == 2  # 5분 지나면 다시 읽는다


def test_unreachable_box_is_rechecked_sooner(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(rt.time, "monotonic", lambda: clock[0])
    box = _Box(reachable=False)
    o = _owner(box)
    _call(o)
    clock[0] += 10.0
    _call(o)
    assert box.calls == 1
    clock[0] += 25.0
    _call(o)
    assert box.calls == 2


def test_cached_answer_is_a_copy(monkeypatch):
    monkeypatch.setattr(rt.time, "monotonic", lambda: 5.0)
    o = _owner(_Box())
    first = _call(o)
    first["reachable"] = "망가뜨림"
    assert _call(o)["reachable"] is True


def test_health_uses_the_cached_door():
    import inspect
    src = inspect.getsource(rt.JarvisRuntime.health)
    assert '"sandbox": self._probe("sandbox", self._sandbox_health)' in src
    assert "self.sandbox.status)" not in src
