"""3D 색 대조 검사 · 다시 굽기 (2026-11-16 밤 · 팩 잇기 시험에서 로봇 색이 검게 나옴).

지키는 것:
1. 검사: 검은 칸 > 10% 또는 밝기 비율 < 0.2 → 이상. 정상 그림은 안 걸린다.
2. 사람이 씨앗을 안 정한 판은 색이 이상하면 새 씨앗으로 최대 두 번 더 굽고, 가장 나은 판을 남긴다(앞 판 파일은 지우지 않음).
3. 사람이 씨앗을 정한 판은 다시 굽지 않는다(영수증에 이상만).
4. 색이 정상이면 한 번만 굽는다.
"""
from __future__ import annotations

import importlib.util
import itertools
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from alture_jarvis.gen3d.color_check import measure
from alture_jarvis.gen3d.runner import COLOR_RETRIES, Gen3DRunner

_spec = importlib.util.spec_from_file_location("_gen3d_1114", Path(__file__).with_name("test_gen3d_1114.py"))
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)  # type: ignore[union-attr]


def _robot(path: Path) -> Path:
    """흰 바탕에 파란 물체(넣은 그림)."""
    pixels = np.full((256, 256, 3), 255, np.uint8)
    pixels[60:200, 80:180] = (86, 150, 214)
    Image.fromarray(pixels).save(path)
    return path


def _texture(path: Path, bright: bool) -> Path:
    pixels = np.zeros((128, 128, 3), np.uint8)
    if bright:
        pixels[:] = (90, 150, 210)
    else:
        pixels[:, :40] = (40, 40, 60)  # 대부분 검정
    Image.fromarray(pixels).save(path)
    return path


def test_measure_flags_dark_and_passes_normal(tmp_path: Path) -> None:
    image = _robot(tmp_path / "in.png")
    bad = measure(image, _texture(tmp_path / "dark.png", bright=False))
    good = measure(image, _texture(tmp_path / "ok.png", bright=True))
    assert bad["ok"] is False and bad["dark_share"] > 0.5 and bad["why"]
    assert good["ok"] is True and good["dark_share"] == 0 and 0.8 < good["ratio"] < 1.3
    assert measure(image, tmp_path / "missing.png")["ok"] is None, "못 읽으면 모름 — 막지 않는다"


def _runner(tmp_path: Path, brights: list[bool], calls: list) -> Gen3DRunner:
    bin_dir, models = _base._ready_dirs(tmp_path)
    log = (_base.FIXTURES / "ship_color_512.log.txt").read_bytes()
    seq = iter(brights)

    def popen(cmd: list[str], **kwargs: Any) -> Any:
        calls.append(cmd)
        seeded = f"seed {len(calls) * 111} (auto)\n".encode() + log  # 실행기 기록 첫 줄의 씨앗(판마다 다름)
        process = _base._FakeProcess(cmd, seeded, _base._cube(), 0)
        out = Path(cmd[cmd.index("-o") + 1])
        _texture(out.with_name(f"{out.stem}_base.png"), next(seq))
        return process

    vram = itertools.repeat(1200)
    return Gen3DRunner(tmp_path / "out", bin_dir, models, popen=popen, vram_probe=lambda gpu: next(vram), poll_sec=0.01)


def test_auto_seed_retries_and_keeps_the_best(tmp_path: Path) -> None:
    calls: list = []
    runner = _runner(tmp_path, [False, True], calls)
    job_id = runner.submit(_robot(tmp_path / "robot.png"), res=512, gpu=1)
    found = _base._wait(runner, job_id)
    assert found["state"] == "done", found
    assert len(calls) == 2, "색이 이상하면 한 번 더 굽는다"
    receipt = found["receipt"]
    assert receipt["measured"]["color"]["ok"] is True
    tries = receipt["measured"]["color_tries"]
    assert [row["ok"] for row in tries] == [False, True]
    assert [row["seed"] for row in tries] == [111, 222], "마지막 판 씨앗도 기록한다(11-17 null)"
    assert receipt["files"]["glb"].endswith("_try2.glb"), "가장 나은(두 번째) 판을 남긴다"
    assert Path(tries[0]["glb"]).is_file(), "앞 판 파일은 지우지 않는다"
    assert any("다시 구웠다" in line for line in receipt["not_done"])


def test_gives_up_after_the_retries_and_says_so(tmp_path: Path) -> None:
    calls: list = []
    runner = _runner(tmp_path, [False] * (COLOR_RETRIES + 1), calls)
    found = _base._wait(runner, runner.submit(_robot(tmp_path / "robot.png"), res=512, gpu=1))
    assert found["state"] == "done" and len(calls) == COLOR_RETRIES + 1
    seeds = [row["seed"] for row in found["receipt"]["measured"]["color_tries"]]
    assert seeds == [111 * (i + 1) for i in range(COLOR_RETRIES + 1)] and None not in seeds
    assert any("못 맞췄다" in line for line in found["receipt"]["not_done"])


def test_fixed_seed_is_not_retried(tmp_path: Path) -> None:
    calls: list = []
    runner = _runner(tmp_path, [False, True], calls)
    found = _base._wait(runner, runner.submit(_robot(tmp_path / "robot.png"), res=512, gpu=1, seed=42))
    assert len(calls) == 1, "사람이 정한 씨앗은 그 결과를 원한 것"
    assert found["receipt"]["measured"]["color"]["ok"] is False
    assert "color_tries" not in found["receipt"]["measured"]


def test_normal_color_bakes_once(tmp_path: Path) -> None:
    calls: list = []
    runner = _runner(tmp_path, [True], calls)
    found = _base._wait(runner, runner.submit(_robot(tmp_path / "robot.png"), res=512, gpu=1))
    assert len(calls) == 1 and found["receipt"]["measured"]["color"]["ok"] is True
    assert not any("다시 구웠다" in line for line in found["receipt"]["not_done"])
