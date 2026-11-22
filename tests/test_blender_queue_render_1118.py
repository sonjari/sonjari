"""블렌더 공통 층 2단계 — 한 줄 대기열 · 렌더 `gen_3d_render` (2026-11-18 · 설계 `설계_블렌더공통층_워크플로우` §14).

한 줄 대기열(`pack_ram.heavy_slot`):
- 해야 할 것: 맥은 배타 · 윈도우는 비배타(카드 둘 — 같이 굽는 것이 빠름) · `JARVIS_HEAVY_ONE_LINE` 이 둘을 뒤집음 /
  안 기다리는 일은 바로 HeavyBusy(누가 쥐었나 이름) / 기다린 초를 따로 / 예외가 나도 놓는다
- 교착 없음: 영상이 쥔 동안 3D 마무리 · 렌더 · 애니 블렌더는 즉시 busy, 3D 굽기는 기다렸다가 끝까지 돈다
렌더(`gen3d/render.py` · `runner.render`):
- 숫자는 블렌더 말이 아니라 파일에서(그림 크기 · 장 수 · 모델 몫) / 이음새 비율 / mp4 못 만들면 not_done / render_v 새 칸 ·
  원본 그대로 / base last · original / 블렌더가 없으면 까닭 · 빈 칸 안 남김 / 인자 범위
- 진짜 블렌더가 있으면 still · turntable 한 판(없으면 건너뜀)
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from test_gen3d_1114 import _cube, _no_real_slicer, _runner, _wait, _write_glb  # noqa: F401
from test_gen3d_finish_1116 import _done_runner, _found

from alture_jarvis import config, pack_ram
from alture_jarvis.gen3d import render as rd
from alture_jarvis.gen3d.runner import Gen3DError


@pytest.fixture
def one_line(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    values: dict[str, str] = {"JARVIS_HEAVY_ONE_LINE": "1"}
    real = config.setting
    monkeypatch.setattr(config, "setting", lambda name, default="": values.get(name, real(name, default)))
    return values


def _hold_slot(who: str = "영상 굽기") -> tuple[threading.Event, threading.Event, threading.Thread]:
    """다른 실행기가 한 줄 잠금을 쥔 것처럼 — release 를 set 할 때까지 쥔다."""
    got, release = threading.Event(), threading.Event()

    def hold() -> None:
        with pack_ram.heavy_slot(who, wait=True):
            got.set()
            release.wait(10)

    th = threading.Thread(target=hold, daemon=True)
    th.start()
    assert got.wait(5)
    return got, release, th


# ── 한 줄 대기열 ──────────────────────────────────────────────────────────
def test_the_default_is_one_line_on_mac_and_single_card_pcs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "setting", lambda name, default="": default)
    monkeypatch.setattr(pack_ram, "gpu_count", lambda: 2)
    monkeypatch.setattr(pack_ram.sys, "platform", "darwin")
    assert pack_ram.one_line()
    monkeypatch.setattr(pack_ram.sys, "platform", "win32")
    assert not pack_ram.one_line()  # 카드 둘(이 PC 3090 · 3060) — 같이 굽는다
    monkeypatch.setattr(pack_ram, "gpu_count", lambda: 1)
    assert pack_ram.one_line()  # 손님 대부분(카드 한 장) — 영상과 3D 가 한 카드에서 겹치지 않게


def test_the_setting_flips_both_ways(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {"JARVIS_HEAVY_ONE_LINE": "1"}
    monkeypatch.setattr(config, "setting", lambda name, default="": values.get(name, default))
    monkeypatch.setattr(pack_ram, "gpu_count", lambda: 2)
    monkeypatch.setattr(pack_ram.sys, "platform", "win32")
    assert pack_ram.one_line()
    values["JARVIS_HEAVY_ONE_LINE"] = "0"
    monkeypatch.setattr(pack_ram.sys, "platform", "darwin")
    assert not pack_ram.one_line()


def test_a_non_waiting_job_is_refused_with_the_holder_name(one_line: dict[str, str]) -> None:
    _, release, th = _hold_slot("영상 굽기")
    try:
        with pytest.raises(pack_ram.HeavyBusy) as err:
            with pack_ram.heavy_slot("3D 렌더", wait=False):
                pass
        assert "영상 굽기" in str(err.value) and str(err.value).startswith("busy:")
    finally:
        release.set()
        th.join(5)


def test_a_waiting_job_counts_its_wait_apart(one_line: dict[str, str]) -> None:
    _, release, th = _hold_slot()
    threading.Timer(0.4, release.set).start()
    with pack_ram.heavy_slot("3D 굽기", wait=True) as info:
        assert info["one_line"] and info["busy_wait_sec"] >= 0.3
    th.join(5)


def test_not_exclusive_lets_both_run_but_still_counts_holders(one_line: dict[str, str]) -> None:
    one_line["JARVIS_HEAVY_ONE_LINE"] = "0"
    with pack_ram.heavy_slot("영상 굽기", wait=True):
        with pack_ram.heavy_slot("3D 렌더", wait=False) as info:
            assert info == {"busy_wait_sec": 0.0, "one_line": False}
            assert pack_ram.heavy_holders() == ["영상 굽기", "3D 렌더"]
    assert pack_ram.heavy_holders() == []


def test_the_slot_is_released_when_the_job_raises(one_line: dict[str, str]) -> None:
    with pytest.raises(ZeroDivisionError):
        with pack_ram.heavy_slot("3D 렌더", wait=False):
            raise ZeroDivisionError
    with pack_ram.heavy_slot("다음", wait=False):
        assert pack_ram.heavy_holders() == ["다음"]


def test_finish_and_render_refuse_at_once_while_video_holds_the_slot(tmp_path: Path, one_line: dict[str, str]) -> None:
    runner, job_id = _done_runner(tmp_path)
    runner._run_render = lambda *a, **k: pytest.fail("잠금을 못 잡았는데 블렌더를 불렀다")
    _, release, th = _hold_slot("영상 굽기")
    try:
        started = time.monotonic()
        with pytest.raises(Gen3DError, match="영상 굽기"):
            runner.finish(job_id, [{"op": "smooth_surface"}])
        with pytest.raises(Gen3DError, match="영상 굽기"):
            runner.render(job_id)
        assert time.monotonic() - started < 2.0  # 기다리지 않는다(교착 막기)
        assert not list((tmp_path / "out" / job_id).glob("render_v*"))  # 시작도 못 한 칸을 남기지 않는다
    finally:
        release.set()
        th.join(5)


def test_a_bake_waits_for_the_slot_then_finishes(tmp_path: Path, one_line: dict[str, str]) -> None:
    runner = _runner(tmp_path)
    image = tmp_path / "a.png"
    image.write_bytes(b"png")
    _, release, th = _hold_slot("영상 굽기")
    job_id = runner.submit(image)
    time.sleep(0.5)
    assert runner.get(job_id)["state"] != "done"  # 영상이 쥔 동안은 굽지 않는다
    release.set()
    th.join(5)
    found = _wait(runner, job_id)
    assert found["state"] == "done"
    assert found["receipt"]["measured"]["busy_wait_sec"] >= 0.3


def test_anim_blender_is_refused_while_a_bake_holds_the_slot(tmp_path: Path, one_line: dict[str, str],
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis.animator import blender_bridge as bb

    monkeypatch.setattr(bb, "find_blender", lambda **_: "blender.exe")
    from alture_jarvis.gen3d import blender as g3b

    monkeypatch.setattr(g3b.subprocess, "Popen", lambda *a, **k: pytest.fail("잠금을 못 잡았는데 블렌더를 불렀다"))
    _, release, th = _hold_slot("3D 굽기")
    try:
        with pytest.raises(pack_ram.HeavyBusy, match="3D 굽기"):
            bb.run(tmp_path / "a.blend", "print(1)", {}, tmp_path / "work")
    finally:
        release.set()
        th.join(5)


# ── 렌더 (가짜 블렌더) ──────────────────────────────────────────────────────
def _frame(path: Path, turn: float, size: tuple[int, int] = (64, 64)) -> None:
    """turn(0~1 바퀴)만큼 원을 따라 돈 네모 — 진짜 한 바퀴처럼 끝 다음이 첫으로 이어진다."""
    import math

    w, h = size
    img = np.full((h, w, 3), 236, np.uint8)
    cx, cy = w // 2 + int(w * 0.2 * math.cos(2 * math.pi * turn)), h // 2 + int(h * 0.2 * math.sin(2 * math.pi * turn))
    img[max(0, cy - h // 8):cy + h // 8, max(0, cx - w // 10):cx + w // 10] = (20, 40, 160)
    Image.fromarray(img).save(path)


class _FakeRender:
    """run_script 꼴: 블렌더가 말한 숫자(일부러 틀리게)와 실제 그림 파일을 따로 둔다."""

    def __init__(self, frames: int = 8, size: tuple[int, int] = (64, 64), break_seam: bool = False) -> None:
        self.frames, self.size, self.break_seam = frames, size, break_seam
        self.jobs: list[dict[str, Any]] = []

    def __call__(self, script: str, job: dict[str, Any], *, exe: str | None = None, timeout: int = 0) -> dict[str, Any]:
        assert script == "render.py"
        self.jobs.append(dict(job, timeout=timeout))
        out = Path(job["out_dir"])
        if job["mode"] == "turntable":
            for i in range(self.frames):
                turn = i / self.frames if not (self.break_seam and i == self.frames - 1) else 0.0  # 0° 를 끝에 또 — 멈칫
                _frame(out / f"frame_{i + 1:04d}.png", turn, self.size)
        else:
            _frame(out / "still.png", 0, self.size)
        # 블렌더가 하는 말 — 일부러 틀린 장 수 · 크기를 섞는다(영수증이 이걸 옮기면 안 된다)
        return {"ok": True, "engine": "CYCLES", "samples": 24, "view_transform": "Khronos PBR Neutral", "render_sec": 8.0,
                "look": job["look"], "files": ["거짓"] * 99, "width": 9999, "height": 9999}


def test_receipt_numbers_come_from_the_files_not_from_blender(tmp_path: Path) -> None:
    fake = _FakeRender(frames=8, size=(64, 48))
    out = rd.render_glb(tmp_path / "a.glb", tmp_path / "r", mode="turntable", frames=8, width=256, height=256,
                        find=_found, run=fake, mp4=False)
    m = out["measured"]
    assert m["frames"] == 8 and m["size"] == [64, 48]  # 블렌더가 말한 99장 · 9999 가 아니라 파일
    assert any("크기가 요청" in n for n in out["not_done"])
    assert m["color_graded"] is False and m["view_transform"] == "Khronos PBR Neutral"
    assert 0.02 < m["cover"]["첫"] < 0.2


def test_seam_is_smooth_for_a_loop_and_flagged_when_it_jumps(tmp_path: Path) -> None:
    ok = rd.render_glb(tmp_path / "a.glb", tmp_path / "r1", mode="turntable", frames=8, width=256, height=256,
                       find=_found, run=_FakeRender(frames=8, size=(256, 256)), mp4=False)
    assert ok["measured"]["seam"]["verdict"] == "ok" and not ok["not_done"]
    bad = rd.render_glb(tmp_path / "a.glb", tmp_path / "r2", mode="turntable", frames=8, width=256, height=256,
                        find=_found, run=_FakeRender(frames=8, size=(256, 256), break_seam=True), mp4=False)
    assert bad["measured"]["seam"]["verdict"] == "stall" and any("멈칫" in n for n in bad["not_done"])


def test_missing_ffmpeg_is_said_not_hidden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rd.shutil, "which", lambda _: None)
    out = rd.render_glb(tmp_path / "a.glb", tmp_path / "r", mode="turntable", frames=8, width=256, height=256,
                        find=_found, run=_FakeRender(size=(256, 256)))
    assert out["ok"] and "mp4" not in out["files"] and any("ffmpeg" in n for n in out["not_done"])


def test_no_blender_says_why(tmp_path: Path) -> None:
    out = rd.render_glb(tmp_path / "a.glb", tmp_path / "r", find=lambda: {"found": False, "why": "블렌더 4.5 미만(3.6)"})
    assert not out["ok"] and "3.6" in out["not_done"][0] and not (tmp_path / "r").exists()


@pytest.mark.parametrize("kw", [{"mode": "loop"}, {"look": "toon"}, {"engine": "octane"}, {"mode": "turntable", "frames": 2},
                                {"width": 100}, {"lens": 5.0}, {"background": "red"}])
def test_bad_arguments_are_refused(tmp_path: Path, kw: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        rd.render_glb(tmp_path / "a.glb", tmp_path / "r", find=_found, run=_FakeRender(), **kw)


def test_defaults_per_mode_reach_blender(tmp_path: Path) -> None:
    fake = _FakeRender(size=(1024, 1024))
    rd.render_glb(tmp_path / "a.glb", tmp_path / "s", find=_found, run=fake, background="#000000")
    still = fake.jobs[-1]
    assert still["lens"] == 85.0 and still["samples"] == 48 and still["bg"] == [0.0, 0.0, 0.0]
    rd.render_glb(tmp_path / "a.glb", tmp_path / "t", mode="turntable", find=_found, run=_FakeRender(frames=48, size=(1024, 1024)), mp4=False)


def test_runner_writes_a_new_render_folder_from_the_last_finish(tmp_path: Path) -> None:
    runner, job_id = _done_runner(tmp_path)
    home = tmp_path / "out" / job_id
    original = next(home.glob("*.glb"))
    before = original.read_bytes()
    runner.finish(job_id, [{"op": "smooth_surface"}])
    fake = _FakeRender(size=(1024, 1024))
    runner._run_render = fake
    first = runner.render(job_id)
    second = runner.render(job_id, base="original", look="clay")
    assert Path(first["folder"]).name == "render_v1" and Path(second["folder"]).name == "render_v2"
    assert Path(fake.jobs[0]["input"]).parent.name == "finish_v1"  # 기본은 마지막 마무리 판
    assert Path(fake.jobs[1]["input"]) == original and fake.jobs[1]["look"] == "clay"
    assert original.read_bytes() == before and (Path(first["folder"]) / "render.json").is_file()


def test_the_tool_is_listed_registered_and_returns_errors_as_text(tmp_path: Path) -> None:
    from test_gen3d_1114 import _Config, _Packs

    from alture_jarvis.gen3d_tools import Gen3DTools

    tools = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    assert "gen_3d_render" in [t["function"]["name"] for t in tools.active_ollama_tools]
    assert tools.gen_3d_render({})["ok"] is False  # job_id · glb_path 둘 다 없음 → 글로


# ── 진짜 블렌더(있을 때만) ─────────────────────────────────────────────────
@pytest.mark.skipif(not __import__("alture_jarvis.gen3d.blender", fromlist=["x"]).find_blender()["found"], reason="블렌더 없음")
def test_real_blender_still_and_turntable(tmp_path: Path) -> None:
    mesh = _cube()
    glb = tmp_path / "box.glb"
    _write_glb(glb, mesh)
    still = rd.render_glb(glb, tmp_path / "s", width=320, height=256, samples=8)
    assert still["ok"], still["not_done"]
    assert still["measured"]["size"] == [320, 256] and still["measured"]["cover"]["첫"] > 0.02
    turn = rd.render_glb(glb, tmp_path / "t", mode="turntable", frames=8, width=256, height=256, samples=4, look="clay")
    assert turn["ok"], turn["not_done"]
    assert turn["measured"]["frames"] == 8 and turn["measured"]["seam"]["verdict"] == "ok"


def test_the_tool_checks_the_glb_path_and_reads_false_as_false(tmp_path: Path) -> None:
    from test_gen3d_1114 import _Config, _Packs

    from alture_jarvis.gen3d_tools import Gen3DTools

    seen: list[str] = []

    def resolve(raw: str) -> Path:
        seen.append(raw)
        raise PermissionError("허용 밖 자리")

    tools = Gen3DTools(_Config(tmp_path), resolve=resolve, packs=_Packs(True))
    out = tools.gen_3d_render({"glb_path": "C:/Windows/secret.glb"})
    assert out == {"ok": False, "error": "허용 밖 자리"} and seen == ["C:/Windows/secret.glb"]  # 파일 도구와 같은 검사를 거친다

    got: dict[str, Any] = {}
    tools2 = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    tools2._runner = type("R", (), {"render": lambda self, job_id, **kw: got.update(kw) or {"ok": True}})()
    tools2.gen_3d_render({"job_id": "g3_x", "transparent": "false", "elevation": 0})
    assert got["transparent"] is False and got["elevation"] == 0.0  # 글자 false · 0 도가 살아서 간다


def test_blender_is_lifted_to_normal_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """본체가 BelowNormal 로 떠 블렌더가 물려받으면 렌더가 두 배 느렸다(11-18 · 2.6 → 5.8초/장) — 띄운 직후 올린다."""
    import subprocess
    import sys

    from alture_jarvis.gen3d import blender as g3b

    lifted: list[int] = []
    monkeypatch.setattr(pack_ram, "lift_to_normal", lambda proc: lifted.append(proc.pid))
    done = g3b._run_normal([sys.executable, "-c", "print('ok')"], 30)
    assert isinstance(done, subprocess.CompletedProcess) and done.returncode == 0 and b"ok" in done.stdout
    assert len(lifted) == 1


def test_turntable_answer_does_not_list_every_frame(tmp_path: Path) -> None:
    out = rd.render_glb(tmp_path / "a.glb", tmp_path / "r", mode="turntable", frames=48, width=256, height=256,
                        find=_found, run=_FakeRender(frames=48, size=(256, 256)), mp4=False)
    frames = out["files"]["frames"]
    assert frames["count"] == 48 and frames["first"].endswith("frame_0001.png") and frames["last"].endswith("frame_0048.png")
    assert len(str(out)) < 3000  # 경로 48줄을 클로드 창에 붓지 않는다


@pytest.mark.skipif(__import__("os").name != "nt", reason="윈도우 전용")
def test_lift_also_turns_off_power_throttling(monkeypatch: pytest.MonkeyPatch) -> None:
    """본체(작업 스케줄러 · 창 없음 · 낮은 순위)의 자식은 윈도우가 효율 모드로 느리게 돌렸다 — 11-18 렌더 8장 41.7초 → 끈 뒤 18.7 · 17.8초."""
    import subprocess
    import sys

    from alture_jarvis import winapi

    calls: list[int] = []
    real = winapi.kernel32.SetProcessInformation

    def spy(handle: Any, klass: int, buf: Any, size: int) -> Any:
        calls.append(int(klass))
        return real(handle, klass, buf, size)

    monkeypatch.setattr(winapi.kernel32, "SetProcessInformation", spy)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
    try:
        pack_ram.lift_to_normal(proc)
    finally:
        proc.wait(10)
    assert 4 in calls  # ProcessPowerThrottling
