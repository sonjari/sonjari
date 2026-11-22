"""무거운 팩 일(3D · 영상 굽기) 전에 램 비우기 (2026-11-17 · `pack_ram` · 설계 `docs/설계_무거운팩_램비우기_2026-11-17.ko.md`).

11-17 새벽: 27B 프롬프트 캐시가 램 24GB 를 쥔 채 영상 시안을 구우니 글 읽기 15~22초가 218초로 늘었다(디스크 넘기기).
카드가 둘인 이 PC 는 「카드 하나일 때만 내린다」에 걸리지 않아 내리지 않았다 — 램을 보고 내리게 고쳤다.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis import pack_ram
from alture_jarvis.genvideo.storyboard import parse
from test_gen3d_1114 import _TextModels as _Text3D
from test_gen3d_1114 import _platform_runner
from test_gen3d_1114 import _wait as _wait3d
from test_genvideo_1116 import _board, _runner, _TextModels, _wait

PLENTY = {"free_mib": 40_000, "commit_mib": 50_000, "commit_limit_mib": 128_000, "commit_share": 0.39}
#: 11-17 새벽 실측 그대로 — 남은 램 13.9GB · 약속 113/127.7GB.
SHORT = {"free_mib": 13_900, "commit_mib": 113_000, "commit_limit_mib": 127_700, "commit_share": 0.885}


@pytest.fixture(autouse=True)
def _clean_flags(monkeypatch):
    monkeypatch.delenv("JARVIS_PACK_RAM_UNLOAD", raising=False)
    pack_ram._busy = 0
    pack_ram._reprime = False
    yield
    pack_ram._busy = 0
    pack_ram._reprime = False


# ── 판정 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("status", "unload", "why_has"), [
    (PLENTY, False, ""),
    (SHORT, True, "남은 램 13.6GB"),
    ({"free_mib": 40_000, "commit_share": 0.90}, True, "약속 메모리가 한도의 90%"),  # 램은 넉넉해도 약속이 차면 넘기기가 시작된다
    ({"free_mib": 15_000, "commit_share": 0.5}, True, "남은 램"),                  # 12.5GB × 1.25 = 15.6GB 보다 적다
    ({"free_mib": 16_000, "commit_share": 0.85}, False, ""),                       # 경계: 같으면 안 내린다
    ({"free_mib": None, "commit_share": None}, False, "못 재서"),                   # 못 재면 내리지 않는다
    ({}, False, "못 재서"),
])
def test_should_unload_table(status: dict, unload: bool, why_has: str) -> None:
    got, why = pack_ram.should_unload(pack_ram.VIDEO_NEED_MIB, status)
    assert got is unload
    assert (why_has in why) if why_has else why == ""


def test_person_can_turn_unloading_off_and_gets_a_warning_instead() -> None:
    got, why = pack_ram.should_unload(pack_ram.VIDEO_NEED_MIB, SHORT, disabled=True)
    assert got is False and "꺼 둬서" in why and "느릴 수" in why


def test_memory_status_reads_this_machine() -> None:
    got = pack_ram.memory_status()
    assert set(got) >= {"free_mib", "commit_share"}
    if got["free_mib"] is not None:
        assert got["free_mib"] > 0


# ── 영상: 카드 둘이어도 램이 모자라면 내린다 ───────────────────────────────

def test_video_unloads_on_a_two_card_pc_when_ram_is_short(tmp_path: Path) -> None:
    text = _TextModels()
    runner = _runner(tmp_path, text_models=text, memory_probe=lambda: dict(SHORT))  # 기본 카드 둘(3090 · 3060)
    found = _wait(runner, runner.submit_batch(parse(_board())))
    assert text.unloaded == ["swift-27b"]
    notes = found["receipt"]["not_done"]
    assert any("램이 모자라" in x and "swift-27b" in x and "다시 올라온다" in x for x in notes)
    assert not any("카드가 하나라" in x for x in notes)
    measured = found["receipt"]["measured"]
    assert measured["ram"]["unload"] is True and measured["text_models_unloaded"] == ["swift-27b"]  # 영수증에 근거
    assert pack_ram.take_reprime() is True and pack_ram.take_reprime() is False  # 끝난 뒤 한 번 데울 차례


def test_video_keeps_the_model_on_a_two_card_pc_when_ram_is_plenty(tmp_path: Path) -> None:
    text = _TextModels()
    runner = _runner(tmp_path, text_models=text, memory_probe=lambda: dict(PLENTY))
    found = _wait(runner, runner.submit_batch(parse(_board())))
    assert text.unloaded == [] and not any("내렸다" in x for x in found["receipt"]["not_done"])
    assert pack_ram.take_reprime() is False


def test_video_turned_off_warns_but_keeps_the_model(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_PACK_RAM_UNLOAD", "0")
    text = _TextModels()
    runner = _runner(tmp_path, text_models=text, memory_probe=lambda: dict(SHORT))
    found = _wait(runner, runner.submit_batch(parse(_board())))
    assert text.unloaded == []
    assert any("꺼 둬서" in x for x in found["receipt"]["not_done"])


def test_video_check_tells_claude_it_will_unload(tmp_path: Path) -> None:
    runner = _runner(tmp_path, text_models=_TextModels(), memory_probe=lambda: dict(SHORT))
    ram = runner.check()["ram"]
    assert ram["will_unload_text_model"] is True and ram["need_mib"] == pack_ram.VIDEO_NEED_MIB and ram["why"]
    runner = _runner(tmp_path / "b", text_models=_TextModels(), memory_probe=lambda: dict(PLENTY))
    assert runner.check()["ram"]["will_unload_text_model"] is False


def test_video_raises_the_heavy_flag_while_baking(tmp_path: Path) -> None:
    seen: list[bool] = []
    calls: list = []
    runner = _runner(tmp_path, calls=calls, memory_probe=lambda: dict(PLENTY))
    real_popen = runner._popen

    def popen(cmd, **kw):
        seen.append(pack_ram.heavy_busy())
        return real_popen(cmd, **kw)

    runner._popen = popen
    _wait(runner, runner.submit_batch(parse(_board())))
    time.sleep(0.05)
    assert seen and all(seen)                # 굽는 동안 깃발이 서 있다
    assert pack_ram.heavy_busy() is False    # 끝나면 내려간다


# ── 3D(윈도우): 램이 모자라면 내린다 · 맥은 그대로 ─────────────────────────

def test_gen3d_windows_unloads_when_ram_is_short(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    text = _Text3D([{"name": "swift-27b", "mib": 20000}])
    runner = _platform_runner(tmp_path, "win32", text_models=text)
    runner._memory_probe = lambda: dict(SHORT)
    found = _wait3d(runner, runner.submit(image, gpu=1))
    assert found["state"] == "done" and text.unloaded_calls == [["swift-27b"]]
    assert any("램이 모자라" in x for x in found["receipt"]["not_done"])
    assert found["receipt"]["measured"]["ram"]["unload"] is True
    assert pack_ram.take_reprime() is True


def test_gen3d_windows_keeps_the_model_when_ram_is_plenty(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    text = _Text3D([{"name": "swift-27b", "mib": 20000}])
    runner = _platform_runner(tmp_path, "win32", text_models=text)
    runner._memory_probe = lambda: dict(PLENTY)
    found = _wait3d(runner, runner.submit(image, gpu=1))
    assert found["state"] == "done" and text.unloaded_calls == []
    assert pack_ram.take_reprime() is False


def test_gen3d_mac_still_always_unloads_and_ignores_the_ram_rule(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    text = _Text3D([{"name": "gemma3:12b", "mib": 9000}])
    runner = _platform_runner(tmp_path, "darwin", text_models=text)
    runner._memory_probe = lambda: dict(PLENTY)
    found = _wait3d(runner, runner.submit(image))
    assert found["state"] == "done" and text.unloaded_calls == [["gemma3:12b"]]
    assert pack_ram.take_reprime() is False  # 맥은 예전 길(다음 질문 때 저절로) 그대로


# ── 데우기 반복: 굽는 동안 쉬고, 내렸으면 끝난 뒤 한 번 데운다 ──────────────────

def _loop_once(self_like: Any, rounds: int = 1) -> None:
    from alture_jarvis.runtime import JarvisRuntime

    waits = iter([False] * rounds + [True])
    self_like._warmup_stop = SimpleNamespace(wait=lambda sec: next(waits))
    JarvisRuntime._front_prime_loop(self_like)


def _fake_runtime() -> SimpleNamespace:
    from alture_jarvis.runtime import JarvisState

    calls: list[str] = []
    ollama = SimpleNamespace(
        refresh_front=lambda *a: calls.append("refresh") or "same",
        watch_front_engine=lambda: "present",
        front_prime_due=lambda: True,
        prime_front=lambda reason: calls.append("prime"),
        front_engine_unloaded=lambda: calls.append("unloaded"),
    )
    return SimpleNamespace(
        config=SimpleNamespace(front_prime_enabled=True),
        state=SimpleNamespace(snapshot=lambda: SimpleNamespace(state=JarvisState.IDLE)),
        ollama=ollama, events=SimpleNamespace(publish=lambda *a: None), _front_now=lambda: [], calls=calls,
    )


def test_prime_loop_rests_while_a_heavy_job_runs() -> None:
    rt = _fake_runtime()
    with pack_ram.heavy_work():
        _loop_once(rt)
    assert rt.calls == []                      # 굽는 동안: 데우지도(=모델 올리지도) 않는다
    _loop_once(rt)
    assert "prime" in rt.calls                 # 끝나면 다시 데운다


def test_prime_loop_marks_a_reprime_after_we_unloaded() -> None:
    rt = _fake_runtime()
    pack_ram.note_unloaded()
    with pack_ram.heavy_work():
        _loop_once(rt)
        assert pack_ram._reprime is True       # 굽는 동안에는 가져가지 않는다
    _loop_once(rt)
    assert rt.calls.count("unloaded") == 1 and "prime" in rt.calls
    _loop_once(rt)
    assert rt.calls.count("unloaded") == 1     # 한 번만


def test_front_engine_unloaded_makes_the_front_due_again() -> None:
    from alture_jarvis.ollama import OllamaClient

    client = OllamaClient.__new__(OllamaClient)
    client.__dict__.update({"_front_warm_keys": {"a", "b"}, "_front_retry_at": 9e18, "_front_engine_seen": True})
    client.front_engine_unloaded()
    assert client.__dict__["_front_warm_keys"] == set() and client.__dict__["_front_retry_at"] == 0.0
    assert client.__dict__["_front_engine_seen"] is None


def test_heavy_work_nests_and_survives_errors() -> None:
    with pack_ram.heavy_work():
        with pack_ram.heavy_work():
            assert pack_ram.heavy_busy()
        assert pack_ram.heavy_busy()
    assert not pack_ram.heavy_busy()
    with pytest.raises(RuntimeError):
        with pack_ram.heavy_work():
            raise RuntimeError("굽기 실패")
    assert not pack_ram.heavy_busy()


def test_turn_off_is_read_from_the_private_store_like_in_production(monkeypatch) -> None:
    """켤 때 `JARVIS_*` 는 환경에서 보관소로 옮겨진다 — 환경을 바로 읽으면 운영에서 끄기가 안 먹는다(11-17 회귀가 잡음)."""
    from alture_jarvis import config

    monkeypatch.delenv("JARVIS_PACK_RAM_UNLOAD", raising=False)
    monkeypatch.setitem(config._PRIVATE, "JARVIS_PACK_RAM_UNLOAD", "0")
    assert pack_ram.unload_disabled() is True
    monkeypatch.setitem(config._PRIVATE, "JARVIS_PACK_RAM_UNLOAD", "1")
    assert pack_ram.unload_disabled() is False


# ── 실행기 순위(11-17 새벽 뿌리: 본체 메모리 2 · 디스크 1 을 물려받아 시안 400초) ─────────────────

@pytest.mark.skipif(__import__("os").name != "nt", reason="윈도우 순위")
def test_lift_to_normal_raises_a_low_child_to_normal_on_all_three() -> None:
    import ctypes
    import subprocess
    import sys

    from alture_jarvis import winapi

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        handle = winapi.kernel32.OpenProcess(0x0200 | 0x0400, False, child.pid)
        winapi.kernel32.SetPriorityClass(handle, 0x4000)  # 보통 아래 — 스케줄러로 뜬 본체를 흉내
        low = ctypes.c_ulong(2)
        winapi.kernel32.SetProcessInformation(handle, 0, ctypes.byref(low), 4)
        io = ctypes.c_ulong(1)
        winapi.ntdll.NtSetInformationProcess(handle, 33, ctypes.byref(io), 4)
        winapi.kernel32.CloseHandle(handle)
        assert pack_ram.priority_of(child.pid) == {"cpu_class": 0x4000, "memory": 2, "io": 1}   # 낮춘 것이 정말 낮다
        assert pack_ram.lift_to_normal(child) == {"cpu_class": 0x20, "memory": 5, "io": 2}
    finally:
        child.kill()


def test_lift_to_normal_leaves_fake_processes_alone() -> None:
    assert pack_ram.lift_to_normal(SimpleNamespace(pid=4)) is None   # 시험의 가짜 과정 · 남의 pid 를 건드리지 않는다
