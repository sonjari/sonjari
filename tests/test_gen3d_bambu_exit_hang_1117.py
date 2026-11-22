"""뱀부 명령줄이 다 쓰고도 종료에서 멈출 때 (2026-11-17).

11-17 실측: 뱀부 명령줄 6개 동시 × 5번 중 60번에 5번이 result.json(Success)과 G-code 를 다 쓰고도 끝나지 않았다.
`subprocess.run` 은 종료만 기다려 240초를 버리고(운영) · 시험은 280초 감시에 끊기고 고아 프로세스를 남겼다.
`slicer.run_bambu` 는 끝을 **결과표**로 가르고, 그 뒤에도 안 나가면 자기가 띄운 프로세스 하나만 끊는다.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from alture_jarvis.gen3d import slicer

_FAKE = r'''
import json, sys, time
from pathlib import Path
out = Path(sys.argv[sys.argv.index("--outputdir") + 1])
mode = sys.argv[1]
if mode == "hang_after_result":
    (out / "plate_1.gcode").write_text("; ok", encoding="utf-8")
    (out / "result.json").write_text(json.dumps({"return_code": 0, "error_string": "Success."}), encoding="utf-8")
    time.sleep(600)
elif mode == "slow_then_exit":
    time.sleep(1.5)
    (out / "result.json").write_text(json.dumps({"return_code": 0}), encoding="utf-8")
elif mode == "hang_no_result":
    time.sleep(600)
'''


def _cmd(tmp_path: Path, mode: str) -> tuple[list[str], Path]:
    script = tmp_path / "fake_bambu.py"
    script.write_text(_FAKE, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return [sys.executable, str(script), mode, "--slice", "0", "--outputdir", str(out), "m.3mf"], out


def test_a_bambu_that_hangs_after_writing_the_result_is_cut_after_the_grace(tmp_path: Path) -> None:
    cmd, out = _cmd(tmp_path, "hang_after_result")
    t = time.monotonic()
    done = slicer.run_bambu(cmd, timeout=60, grace=1.0, creationflags=0)
    assert time.monotonic() - t < 20  # 종료를 기다렸다면 60초 제한에 걸렸다
    assert done.returncode == 0 and b"exit_hung" in done.stderr
    assert (out / "plate_1.gcode").is_file()


def test_an_old_result_from_the_previous_step_is_not_taken_as_the_end(tmp_path: Path) -> None:
    cmd, out = _cmd(tmp_path, "slow_then_exit")
    (out / "result.json").write_text('{"return_code": 0, "old": true}', encoding="utf-8")  # 썰기 단계가 남긴 결과표
    done = slicer.run_bambu(cmd, timeout=60, grace=0.2, creationflags=0)
    assert done.returncode == 0 and done.stderr == b""  # 스스로 끝날 때까지 기다렸다(끊지 않음)
    assert "old" not in (out / "result.json").read_text(encoding="utf-8")


def test_a_bambu_that_never_writes_a_result_still_times_out(tmp_path: Path) -> None:
    cmd, _ = _cmd(tmp_path, "hang_no_result")
    t = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        slicer.run_bambu(cmd, timeout=2, grace=0.5, creationflags=0)
    assert time.monotonic() - t < 15


def test_slice_3mf_uses_the_result_based_runner_by_default() -> None:
    import inspect
    assert inspect.signature(slicer.slice_3mf).parameters["run"].default is slicer.run_bambu
