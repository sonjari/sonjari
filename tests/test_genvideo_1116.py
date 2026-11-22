"""영상 생성 팩 — 콘티 검사 · 명령줄 · 진행 읽기 · 검사 숫자 · 첫 그림 · 실행기 · 도구 문 · 받기 장치 (2026-11-16 · 설계 §10-12).

양방향(해야 할 것 / 하면 안 되는 것)을 같이 둔다. 그래픽카드 없이 돈다 — 실행기는 실측 로그를 흘리는 가짜다.
시험 자료 `fixtures/genvideo/*.log.txt` 는 실측 로그(`D:\\models\\video\\out_1116\\night\\p1_fast.log` · `ltx\\p1_ltx.log`) 그대로.
실측 명령줄(아래 RUN_SH_*)은 같은 폴더의 run.sh 에서 옮긴 것 — 명령줄 만들기가 이 줄과 인자를 하나씩 맞춰야 한다.
"""
from __future__ import annotations

import hashlib
import io
import json
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from alture_jarvis.genvideo import commands
from alture_jarvis.genvideo.firstframe import make_first_frame
from alture_jarvis.genvideo.inspect import inspect, picture_numbers
from alture_jarvis.genvideo.progress import TOTAL_STAGES, VideoTracker
from alture_jarvis.genvideo.runner import GenVideoError, VideoRunner, valid_job_id
from alture_jarvis.genvideo.storyboard import StoryboardError, frames_for, parse
from alture_jarvis.genvideo_tools import GenVideoTools, genvideo_dirs
from alture_jarvis.pack_models import ModelError, ModelFetcher, parse_models
from alture_jarvis.packs import PackRegistry
from alture_jarvis.tool_gateway import tool_runs_here
from alture_jarvis.video_read.scan import ffmpeg_exe

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "genvideo"
PACKS_DIR = Path(__file__).resolve().parents[1] / "packs"

# run.sh 실측 줄(변수만 이름으로 남김). night/run.sh 의 X(fast) = "--cfg-scale 1.0 --steps 3".
RUN_SH_WAN = ('./sd-cli.exe -M vid_gen --diffusion-model "$M" --taesd "$W/taew2_2.safetensors" --t5xxl "$W/umt5-xxl-encoder-Q8_0.gguf" '
              '-p "$prompt" -n "$NEG" $X $I --sampling-method euler --flow-shift 5.0 -W 832 -H 480 --video-frames 73 --fps 24 '
              '--seed 11 --backend "te=cpu" --diffusion-fa -v -o "$O/${name}_${model}.webm"')
RUN_SH_LTX = ('./sd-cli.exe -M vid_gen --diffusion-model $L/ltx-2.5-22b-distilled-Q8_0.gguf --vae $L/ltx-2.5-video-vae-conv-bf16.safetensors '
              '--audio-vae $L/ltx-2.5-audio-vae-bf16.safetensors --llm $L/gemma4-12b-with-proj-ltx-2.5-Q8_0.gguf -p "$prompt" $I '
              '--cfg-scale 1.0 --steps 8 --sampling-method euler -W 832 -H 480 --video-frames 73 --fps 24 --seed 11 '
              '--backend "te=cpu" --offload-to-cpu -v -o "$O/${name}_ltx.webm"')


def _flags(argv: list[str]) -> list[str]:
    """명령줄에서 값 말고 플래그와 고정 값만 — 경로 · 프롬프트는 이름표로 바꾼다."""
    out = []
    for item in argv[1:]:
        if item.startswith("-") or item in {"vid_gen", "euler", "5.0", "1.0", "3", "8", "832", "480", "73", "24", "11", "te=cpu"}:
            out.append(item)
        else:
            out.append("<v>")
    return out


def _sh_flags(line: str, **subs: str) -> list[str]:
    for key, value in subs.items():
        line = line.replace(key, value)
    return _flags(shlex.split(line))


# ── 콘티 ────────────────────────────────────────────────────────────────

def _board(**over: Any) -> dict[str, Any]:
    base = {"title": "t", "aspect": "16:9", "cuts": [
        {"id": "c1", "kind": "gen", "prompt": "A small orange cat walks across a desk", "seconds": 3, "candidates": 2, "seed": 11},
        {"id": "c2", "kind": "code", "note": "앱 화면"},
    ]}
    base.update(over)
    return base


def test_frames_are_8k_plus_1_and_3_seconds_is_the_measured_73() -> None:
    assert frames_for(3) == 73  # 실측 판(73프레임 · 24fps)과 같다
    for sec in (2, 2.5, 3, 4, 5):
        n = frames_for(sec)
        assert (n - 1) % 8 == 0 and (n - 1) % 4 == 0  # LTX 8k+1 · Wan 4k+1


def test_a_good_board_is_accepted_and_only_gen_cuts_count() -> None:
    board = parse(_board())
    assert (board["width"], board["height"]) == (832, 480)
    assert board["runs"] == 2 and [c["kind"] for c in board["cuts"]] == ["gen", "code"]
    assert board["cuts"][0]["frames"] == 73 and board["notes"] == []


@pytest.mark.parametrize("cuts, why", [
    ([{"id": "a", "kind": "gen", "prompt": "x", "seconds": 6}], "2~5초"),
    ([{"id": "a", "kind": "gen", "prompt": "x", "candidates": 5}], "candidates"),
    ([{"id": "a", "kind": "gen", "prompt": ""}], "prompt 가 비었다"),
    ([{"id": "a", "kind": "gen", "prompt": "x"}, {"id": "a", "kind": "gen", "prompt": "y"}], "두 번"),
    ([{"id": "a", "kind": "code"}], "굽을 것이 없다"),
    ([{"id": f"c{i}", "kind": "gen", "prompt": "x", "candidates": 4} for i in range(5)], "16 이하"),
    ([{"id": "a", "kind": "video", "prompt": "x"}], "kind"),
    ([{"id": "a b", "kind": "gen", "prompt": "x"}], "컷 id"),
])
def test_bad_boards_are_refused_with_a_reason(cuts: list, why: str) -> None:
    with pytest.raises(StoryboardError, match=why):
        parse({"cuts": cuts})


def test_unknown_aspect_and_missing_first_image_are_refused(tmp_path: Path) -> None:
    with pytest.raises(StoryboardError, match="aspect"):
        parse(_board(aspect="4:3"))
    with pytest.raises(StoryboardError, match="없다"):
        parse({"cuts": [{"id": "a", "prompt": "x", "first_image": str(tmp_path / "nope.png")}]})


@pytest.mark.parametrize("prompt, flagged", [
    ("A neon sign that reads OPEN above a door", True),
    ("The Sonjari logo spins on a desk", True),
    ("화면에 「손자리」 글자가 떠오른다", True),
    # 반례: 낱말 안에 text 가 들어 있어도 걸리면 안 된다
    ("A textured wooden desk with a coffee cup, soft light", False),
    ("A dog playing with a ball in the park", False),
])
def test_text_or_logo_in_a_prompt_is_flagged_not_blocked(prompt: str, flagged: bool) -> None:
    board = parse({"cuts": [{"id": "a", "prompt": prompt}]})
    assert bool(board["notes"]) is flagged


# ── 명령줄: 실측 run.sh 와 같아야 한다 ──────────────────────────────────

def _files(root: Path) -> dict[str, Path]:
    return {role: root / name for role, name in {
        "fastwan": "FastWan2.2-TI2V-5B-q8_0.gguf", "wan": "Wan2.2-TI2V-5B-Q8_0.gguf", "umt5": "umt5-xxl-encoder-Q8_0.gguf",
        "wan_vae": "wan2.2_vae.safetensors", "tae": "taew2_2.safetensors", "ltx": "ltx-2.5-22b-distilled-Q8_0.gguf",
        "ltx_vae": "ltx-2.5-video-vae-conv-bf16.safetensors", "ltx_audio_vae": "ltx-2.5-audio-vae-bf16.safetensors",
        "ltx_text": "gemma4-12b-with-proj-ltx-2.5-Q8_0.gguf"}.items()}


def test_fastwan_command_matches_the_measured_run_sh(tmp_path: Path) -> None:
    files = _files(tmp_path)
    cmd = commands.build("fastwan", tmp_path / "sd-cli.exe", files, prompt="p", out=tmp_path / "o.webm",
                         width=832, height=480, frames=73, seed=11)
    want = _sh_flags(RUN_SH_WAN, **{"$X": "--cfg-scale 1.0 --steps 3", "$I": ""})
    assert _flags(cmd) == want
    assert cmd[cmd.index("-n") + 1] == commands.WAN_NEGATIVE and "-i" not in cmd and "--vae" not in cmd


def test_wan_final_uses_the_full_vae_and_cfg_5(tmp_path: Path) -> None:
    files = _files(tmp_path)
    cmd = commands.build("wan", tmp_path / "sd-cli.exe", files, prompt="p", out=tmp_path / "o.webm",
                         width=832, height=480, frames=73, seed=11, first_image=str(tmp_path / "f.png"))
    assert cmd[cmd.index("--vae") + 1].endswith("wan2.2_vae.safetensors") and "--taesd" not in cmd
    assert cmd[cmd.index("--cfg-scale") + 1] == "5.0" and "--steps" not in cmd  # run.sh 처럼 단계는 실행기 기본
    assert cmd[cmd.index("-i") + 1].endswith("f.png")


def test_ltx_command_matches_the_measured_run_sh(tmp_path: Path) -> None:
    files = _files(tmp_path)
    cmd = commands.build("ltx", tmp_path / "sd-cli.exe", files, prompt="p", out=tmp_path / "o.webm",
                         width=832, height=480, frames=73, seed=11, first_image=str(tmp_path / "icon.png"))
    want = _sh_flags(RUN_SH_LTX, **{"$I": "-i $N/icon_first.png"})
    assert _flags(cmd) == want
    assert "--offload-to-cpu" in cmd and "-n" not in cmd and "--t5xxl" not in cmd


def test_a_missing_file_is_named_and_no_command_is_built(tmp_path: Path) -> None:
    files = _files(tmp_path)
    del files["tae"]
    assert commands.missing("fastwan", files) == ["tae"]
    with pytest.raises(ValueError, match="tae"):
        commands.build("fastwan", tmp_path / "x", files, prompt="p", out=tmp_path / "o", width=832, height=480, frames=73, seed=1)


def test_find_files_by_name_two_levels_down_and_never_mixes_fastwan_with_wan(tmp_path: Path) -> None:
    (tmp_path / "fastwan").mkdir()
    (tmp_path / "fastwan" / "FastWan2.2-TI2V-5B-q8_0.gguf").write_bytes(b"x")
    (tmp_path / "wanvae" / "split_files" / "vae").mkdir(parents=True)  # 허깅페이스 include 가 하위 폴더를 남긴다
    (tmp_path / "wanvae" / "split_files" / "vae" / "wan2.2_vae.safetensors").write_bytes(b"x")
    (tmp_path / "wan5b").mkdir()
    (tmp_path / "wan5b" / "Wan2.2-TI2V-5B-Q8_0.gguf.part").write_bytes(b"x")  # 받는 중 — 있는 것으로 치면 안 된다
    found = commands.find_files([tmp_path])
    assert found["fastwan"].name.startswith("FastWan") and "wan" not in found and found["wan_vae"].is_file()


# ── 진행 읽기 ───────────────────────────────────────────────────────────

class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


@pytest.mark.parametrize("name, want", [
    ("fast_p1.log.txt", {"text_sec": 40.69, "sample_sec": 15.08, "decode_sec": 1.13, "exe_sec": 57.14}),
    ("ltx_p1.log.txt", {"text_sec": 77.17, "sample_sec": 192.23, "decode_sec": 10.6, "exe_sec": 285.27}),
])
def test_stage_numbers_match_the_measured_times_csv(name: str, want: dict) -> None:
    tracker = VideoTracker(clock=_Clock())
    tracker.feed_text((FIXTURES / name).read_text(encoding="utf-8", errors="replace"))
    tracker.finish()
    assert tracker.numbers() == want  # times.csv 의 같은 판 숫자
    assert [s["index"] for s in tracker.stages] == list(range(1, TOTAL_STAGES + 1)) and tracker.saved


def test_an_out_of_memory_log_names_the_real_error_not_the_tail() -> None:
    # 11-16 홍보 초안 c5(LTX) 실측: 그리기 5/8 에서 CUDA 메모리 부족 — 마지막 [E] 줄은 「ggml:   err」 뿐이었다.
    tracker = VideoTracker(clock=_Clock())
    tracker.feed_text((FIXTURES / "ltx_oom.log.txt").read_text(encoding="utf-8", errors="replace"))
    assert tracker.last_error.strip().endswith("err")  # 꼬리 줄은 뜻이 없다(자료가 정말 그 꼴인지)
    assert tracker.out_of_memory and "out of memory" in tracker.error_summary()
    assert tracker.current()["index"] == 3 and tracker.current()["sub"] == {"done": 5, "total": 8}


def test_an_out_of_memory_bake_says_so_in_the_receipt(tmp_path: Path) -> None:
    bins, _cudart, models = _model_dirs(tmp_path)
    log = (FIXTURES / "ltx_oom.log.txt").read_bytes()
    runner = VideoRunner(tmp_path / "out", [bins], [models], tmp_path / "ltx",
                         popen=lambda cmd, **kw: _FakeProcess(cmd, log, 3221226505), vram_probe=lambda gpu: 9704,
                         gpus=list, inspect_fn=_fake_inspect)
    found = _wait(runner, runner.submit_batch(parse(_board(cuts=[{"id": "a", "prompt": "x", "candidates": 1}]))))
    error = found["receipt"]["runs"][0]["error"]
    assert error.startswith("gpu_out_of_memory") and "그리기 5/8" in error


def test_the_sampling_ratio_is_carried_but_never_the_eta() -> None:
    tracker = VideoTracker(clock=_Clock())
    tracker.feed("[I] loading diffusion model from 'D:/x/FastWan.gguf' --- diffusion_engine.cpp:693")
    tracker.feed("  |================>                                 | 1/3 -   8.08s/it - ETA 00:16\x1b[K")
    current = tracker.current()
    assert current["index"] == 3 and current["sub"] == {"done": 1, "total": 3}
    assert "ETA" not in json.dumps(current) and "00:16" not in json.dumps(current)
    assert all("D:/" not in s["name"] for s in tracker.stages)


# ── 검사 숫자 ───────────────────────────────────────────────────────────

def test_picture_numbers_tell_still_moving_dark_and_jumps() -> None:
    still = np.full((24, 108, 192), 120, dtype=np.uint8)
    out = picture_numbers(still)
    assert out["still_share"] == 1.0 and out["motion_mean"] == 0.0 and out["jumps"] == 0 and out["dark_share"] == 0.0
    moving = np.full((24, 108, 192), 120, dtype=np.uint8)
    for i in range(24):
        moving[i, 40:70, i * 6:i * 6 + 30] = 250
    out = picture_numbers(moving)
    assert out["still_share"] == 0.0 and out["motion_mean"] > 0.6 and out["jumps"] == 0  # 반례: 움직이는 네모를 멈춤이라 하면 안 됨
    dark = np.full((24, 108, 192), 10, dtype=np.uint8)
    assert picture_numbers(dark)["dark_share"] == 1.0
    flash = moving.copy()
    flash[12] = 255
    assert picture_numbers(flash)["jumps"] >= 1
    assert picture_numbers(np.zeros((0, 108, 192), dtype=np.uint8))["motion_mean"] is None  # 못 재면 None


@pytest.mark.skipif(ffmpeg_exe() is None, reason="ffmpeg 없음")
def test_inspect_reads_a_real_clip_sound_and_makes_a_sheet(tmp_path: Path) -> None:
    exe = ffmpeg_exe()
    clip = tmp_path / "t.webm"
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libvpx-vp9", "-c:a", "libopus", "-shortest", str(clip)],
                   check=True, timeout=120)
    out = inspect(clip, tmp_path / "sheet.png", label="t")
    assert out["ok"] and out["has_audio"] is True and out["mean_db"] is not None and out["mean_db"] > -60
    assert out["frames_read"] >= 14 and out["duration_sec"] == pytest.approx(2.0, abs=0.2)
    assert Path(out["sheet"]).is_file()
    silent = tmp_path / "black.webm"
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=black:size=320x180:rate=24:duration=2",
                    "-c:v", "libvpx-vp9", str(silent)], check=True, timeout=120)
    out = inspect(silent)
    assert out["has_audio"] is False and out["dark_share"] == 1.0 and out["still_share"] == 1.0


def test_layout_diff_is_zero_for_the_same_clip_and_large_for_a_different_scene() -> None:
    from alture_jarvis.genvideo.inspect import layout_diff

    rng = np.random.default_rng(3)
    clip = rng.integers(0, 255, (24, 9, 16, 3), dtype=np.uint8)
    same = layout_diff(clip, clip)
    assert same["mean"] == 0.0 and same["diff"] == [0.0, 0.0, 0.0, 0.0]
    shifted = np.clip(clip.astype(int) + 8, 0, 255).astype(np.uint8)  # 밝기만 조금 — 작아야 한다
    assert layout_diff(clip, shifted)["mean"] < 0.05
    other = rng.integers(0, 255, (24, 9, 16, 3), dtype=np.uint8)  # 딴 장면 — 커야 한다
    assert layout_diff(clip, other)["mean"] > 0.2
    # 길이가 달라도 같은 상대 시각(처음 · 끝)을 견준다
    assert layout_diff(clip[:10], clip)["diff"][0] == 0.0
    assert layout_diff(np.zeros((0, 9, 16, 3), dtype=np.uint8), clip)["mean"] is None


# ── 첫 그림 ─────────────────────────────────────────────────────────────

def _png(path: Path, array: np.ndarray) -> Path:
    from PIL import Image

    Image.fromarray(array).save(path)
    return path


def test_first_frame_keeps_alpha_and_lands_in_the_middle(tmp_path: Path) -> None:
    from PIL import Image

    rgba = np.zeros((200, 200, 4), dtype=np.uint8)
    rgba[50:150, 50:150] = [200, 30, 30, 255]
    made = make_first_frame(_png(tmp_path / "a.png", rgba), tmp_path / "o.png", size=(832, 480), background="#102030")
    assert made["cutout"] == "alpha" and made["size"] == [832, 480] and made["notes"] == []
    out = np.array(Image.open(made["first_image"]).convert("RGB"))
    assert out.shape == (480, 832, 3) and tuple(out[0, 0]) == (16, 32, 48) and tuple(out[240, 416]) == (200, 30, 30)


def test_a_flat_background_is_cut_but_the_same_colour_inside_the_object_stays(tmp_path: Path) -> None:
    from PIL import Image

    rgb = np.full((300, 300, 3), 255, dtype=np.uint8)
    rgb[80:220, 80:220] = [20, 120, 220]
    rgb[120:180, 120:180] = 255  # 물체 안의 흰 구멍 — 가장자리와 안 이어졌으니 남아야 한다
    made = make_first_frame(_png(tmp_path / "b.png", rgb), tmp_path / "o.png", size=(832, 480), background="#000000")
    assert made["cutout"] == "flat_border"
    out = np.array(Image.open(made["first_image"]).convert("RGB"))
    assert tuple(out[5, 5]) == (0, 0, 0)  # 바탕은 지워져 검정
    assert tuple(out[240, 416]) == (255, 255, 255)  # 가운데 흰 구멍은 남음


def test_a_busy_background_is_not_claimed_as_cut(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    rgb = rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)
    made = make_first_frame(_png(tmp_path / "c.png", rgb), tmp_path / "o.png", size=(832, 480))
    assert made["cutout"] == "none" and "못 지웠다" in made["notes"][0]


# ── 실행기 ──────────────────────────────────────────────────────────────

class _FakeProcess:
    """실측 로그를 흘리고 webm 을 쓰는 가짜 sd-cli."""

    def __init__(self, cmd: list[str], log: bytes, rc: int = 0, hold: threading.Event | None = None) -> None:
        self.cmd, self.stdout, self._rc, self._hold, self.killed = cmd, io.BytesIO(log), rc, hold, False
        if rc == 0:
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"webm")

    def wait(self, timeout: float | None = None) -> int:
        if self._hold is not None:
            self._hold.wait(timeout or 5)
        else:
            time.sleep(0.15)  # 메모리 재기가 몇 번 돌 시간(3D 시험과 같은 꼴)
        return -9 if self.killed else self._rc

    def kill(self) -> None:
        self.killed = True
        if self._hold is not None:
            self._hold.set()


def _fake_inspect(clip: Path, sheet: Path | None = None, *, label: str = "") -> dict[str, Any]:
    from PIL import Image

    if sheet is not None:
        Image.new("RGB", (512, 300), (40, 40, 40)).save(sheet)
    return {"ok": True, "motion_mean": 3.1, "still_share": 0.0, "dark_share": 0.0, "jumps": 0, "has_audio": False,
            "sheet": str(sheet) if sheet else None}


def _model_dirs(root: Path, engines: tuple[str, ...] = ("fastwan", "wan")) -> tuple[Path, Path, Path]:
    bins, cudart, models = root / "bin", root / "cudart", root / "models"
    for d in (bins, cudart, models):
        d.mkdir(parents=True)
    (bins / "sd-cli.exe").write_bytes(b"")
    for engine in engines:
        for role in commands.NEEDS[engine]:
            name = commands.FILE_PATTERNS[role][0].replace("*", "-q8")
            (models / name).write_bytes(b"x")
    return bins, cudart, models


def _runner(tmp_path: Path, *, rc: int = 0, calls: list | None = None, gpus: list | None = None, **kw: Any) -> VideoRunner:
    bins, cudart, models = _model_dirs(tmp_path)
    log = (FIXTURES / "fast_p1.log.txt").read_bytes()

    def popen(cmd: list[str], **kwargs: Any) -> _FakeProcess:
        if calls is not None:
            calls.append((cmd, kwargs))
        return _FakeProcess(cmd, log, rc)

    cards = gpus if gpus is not None else [{"index": 0, "name": "3090", "free_mib": 4000, "total_mib": 24576},
                                           {"index": 1, "name": "3060", "free_mib": 11800, "total_mib": 12288}]
    vram = iter([417, 9000, 10500] + [9000] * 10000)
    kw.setdefault("inspect_fn", _fake_inspect)
    return VideoRunner(tmp_path / "out", [bins, cudart], [models], tmp_path / "ltx", popen=popen,
                       vram_probe=lambda gpu: next(vram), gpus=lambda: cards, ram_probe=lambda: 30000, poll_sec=0.01, **kw)


def _wait(runner: VideoRunner, job_id: str) -> dict[str, Any]:
    for _ in range(500):
        found = runner.get(job_id)
        if found and found["state"] in {"done", "failed"}:
            return found
        time.sleep(0.02)
    raise AssertionError(f"끝나지 않음: {runner.get(job_id)}")


def test_a_batch_bakes_each_candidate_and_gives_the_receipt(tmp_path: Path) -> None:
    calls: list = []
    runner = _runner(tmp_path, calls=calls)
    job_id = runner.submit_batch(parse(_board()))
    assert valid_job_id(job_id)
    found = _wait(runner, job_id)
    assert found["state"] == "done", found
    receipt = found["receipt"]
    assert receipt["did"] == "시안 2/2개 · fastwan"
    runs = receipt["runs"]
    assert [(r["cut"], r["candidate"], r["seed"]) for r in runs] == [("c1", 1, 11), ("c1", 2, 12)]
    assert runs[0]["text_sec"] == 40.69 and runs[0]["sample_sec"] == 15.08 and runs[0]["exe_sec"] == 57.14
    assert runs[0]["check"]["motion_mean"] == 3.1 and runs[0]["busy_wait_sec"] == 0.0
    assert receipt["measured"]["vram_peak_mib"] == 10500 and receipt["measured"]["gpu_pick"]["index"] == 1  # 남은 메모리가 큰 3060
    assert any("c2(code)" in item for item in receipt["not_done"])  # 굽지 않은 컷
    assert receipt["model"]["license"] == "Apache-2.0"
    files = receipt["files"]
    assert files["pick_sheet"] == "pick_sheet.png" and len(files["clips"]) == 2 and len(files["sheets"]) == 2
    # 판 이름표는 기본 글꼴로 그린다 — 한글이 섞이면 네모로 깨진다(11-16 실측). 이름표 글은 아스키만.
    import inspect as _inspect

    from alture_jarvis.genvideo import runner as _runner_module
    labels = [line for line in _inspect.getsource(_runner_module).splitlines() if "draw.text(" in line or "label=f\"" in line]
    assert labels and all(line.isascii() for line in labels), labels
    # 카드 번호는 nvidia-smi 번호와 맞춰 넘기고, cudart 폴더를 PATH 앞에 붙인다
    cmd, kwargs = calls[0]
    assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "1" and kwargs["env"]["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    import os

    assert str(tmp_path / "cudart") in kwargs["env"]["PATH"].split(os.pathsep)[:3]
    assert cmd[cmd.index("--steps") + 1] == "3" and cmd[cmd.index("--seed") + 1] == "11"
    # 본체를 다시 켜도 영수증은 디스크에서 읽힌다
    again = VideoRunner(tmp_path / "out", [], [], tmp_path / "ltx")
    assert again.get(job_id)["receipt"]["runs"][1]["seed"] == 12


def test_a_pinned_card_wins_over_the_free_memory_pick(tmp_path: Path) -> None:
    calls: list = []
    runner = _runner(tmp_path, calls=calls, gpu_pin=0)
    _wait(runner, runner.submit_batch(parse(_board())))
    assert calls[0][1]["env"]["CUDA_VISIBLE_DEVICES"] == "0"


def test_it_waits_while_someone_is_using_sonjari_and_records_the_wait(tmp_path: Path) -> None:
    states = iter(["working", "working", "idle"] + ["idle"] * 100)
    slept: list = []

    def probe() -> str:
        return next(states)

    calls: list = []
    runner = _runner(tmp_path, calls=calls, busy_probes=[probe], busy_poll_sec=20.0, sleep=lambda s: (slept.append((s, len(calls)))))
    found = _wait(runner, runner.submit_batch(parse(_board(cuts=[{"id": "a", "prompt": "x", "candidates": 1}]))))
    assert found["state"] == "done"
    assert slept == [(20.0, 0), (20.0, 0)]  # 기다리는 동안 실행기를 띄우지 않았다
    assert found["receipt"]["runs"][0]["busy_wait_sec"] == 40.0 and found["receipt"]["measured"]["busy_wait_sec_sum"] == 40.0


def test_too_long_busy_stops_the_batch_and_says_why(tmp_path: Path) -> None:
    calls: list = []
    runner = _runner(tmp_path, calls=calls, busy_probes=[lambda: "working"], busy_poll_sec=10.0, busy_wait_max_sec=30.0,
                     sleep=lambda s: None)
    found = _wait(runner, runner.submit_batch(parse(_board())))
    assert found["state"] == "failed" and calls == []
    assert found["receipt"]["runs"][0]["error"].startswith("busy_too_long")
    assert found["receipt"]["runs"][1]["state"] == "skipped"


def test_a_failing_probe_does_not_block(tmp_path: Path) -> None:
    def broken() -> str:
        raise OSError("ssh 끊김")

    runner = _runner(tmp_path, busy_probes=[broken], sleep=lambda s: (_ for _ in ()).throw(AssertionError("기다리면 안 됨")))
    assert _wait(runner, runner.submit_batch(parse(_board())))["state"] == "done"


class _TextModels:
    def __init__(self) -> None:
        self.unloaded: list = []

    def loaded(self) -> list[dict]:
        return [{"name": "swift-27b", "mib": 20000}]

    def unload(self, names: list[str]) -> list[str]:
        self.unloaded.extend(names)
        return []


def test_text_model_is_unloaded_only_on_a_single_card_pc(tmp_path: Path) -> None:
    two = _TextModels()
    found = _wait(r := _runner(tmp_path / "two", text_models=two), r.submit_batch(parse(_board())))
    assert two.unloaded == [] and not any("내렸다" in x for x in found["receipt"]["not_done"])  # 이 PC(카드 둘): 27B 를 안 내린다
    one = _TextModels()
    single = [{"index": 0, "name": "4070", "free_mib": 9000, "total_mib": 12288}]
    found = _wait(r := _runner(tmp_path / "one", text_models=one, gpus=single), r.submit_batch(parse(_board())))
    assert one.unloaded == ["swift-27b"] and any("내렸다" in x for x in found["receipt"]["not_done"])


def test_a_failed_bake_still_gives_a_receipt(tmp_path: Path) -> None:
    runner = _runner(tmp_path, rc=3)
    found = _wait(runner, runner.submit_batch(parse(_board())))
    assert found["state"] == "failed" and found["error"].startswith("all_failed")
    run = found["receipt"]["runs"][0]
    assert run["state"] == "failed" and run["error"].startswith("exit_3") and "file" not in run
    assert found["receipt"]["files"]["clips"] == []


def test_only_one_batch_runs_and_one_waits(tmp_path: Path) -> None:
    bins, _cudart, models = _model_dirs(tmp_path)
    hold = threading.Event()
    runner = VideoRunner(tmp_path / "out", [bins], [models], tmp_path / "ltx",
                         popen=lambda cmd, **kw: _FakeProcess(cmd, b"[I] loading diffusion model from 'x'\n", 0, hold),
                         vram_probe=lambda gpu: None, gpus=list, inspect_fn=_fake_inspect)
    board = parse(_board())
    first = runner.submit_batch(board)
    second = runner.submit_batch(board)
    with pytest.raises(GenVideoError, match="busy"):
        runner.submit_batch(board)
    assert runner.get(second)["state"] == "queued"
    assert runner.cancel(second) is True and runner.get(second)["error"] == "cancelled"
    assert runner.cancel(first) is True
    found = _wait(runner, first)
    assert found["state"] == "failed" and found["error"] == "cancelled"


def test_not_ready_without_the_runner_or_models(tmp_path: Path) -> None:
    runner = VideoRunner(tmp_path / "out", [tmp_path / "nobin"], [tmp_path / "nomodels"], tmp_path / "ltx", gpus=list)
    with pytest.raises(GenVideoError, match="not_ready.*sd-cli"):
        runner.submit_batch(parse(_board()))


def test_files_are_served_only_by_receipt_name(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    job_id = runner.submit_batch(parse(_board()))
    _wait(runner, job_id)
    assert runner.file_for(job_id, "c1_1_fastwan.webm").name == "c1_1_fastwan.webm"
    assert runner.file_for(job_id, "pick_sheet.png") is not None
    (tmp_path / "out" / job_id / "secret.txt").write_text("x")
    assert runner.file_for(job_id, "secret.txt") is None  # 영수증에 없는 이름
    assert runner.file_for(job_id, "../" + job_id + "/job.json") is None
    assert runner.file_for("gv_bad", "c1_1_fastwan.webm") is None


def test_finish_rebakes_the_picks_with_the_same_seed_and_says_it_may_differ(tmp_path: Path) -> None:
    calls: list = []
    runner = _runner(tmp_path, calls=calls)
    batch = runner.submit_batch(parse(_board()))
    _wait(runner, batch)
    with pytest.raises(GenVideoError, match="not_found"):
        runner.submit_finish(batch, [{"cut": "c1", "candidate": 9}])
    with pytest.raises(ValueError, match="본판 engine"):
        runner.submit_finish(batch, [{"cut": "c1", "candidate": 2}], engine="fastwan")
    final = runner.submit_finish(batch, [{"cut": "c1", "candidate": 2}], engine="wan")
    found = _wait(runner, final)
    assert found["state"] == "done" and found["kind"] == "finish"
    cmd = calls[-1][0]
    assert cmd[cmd.index("--seed") + 1] == "12" and "--vae" in cmd and cmd[cmd.index("-p") + 1].startswith("A small orange cat")
    assert any("다시 구웠다" in item for item in found["receipt"]["not_done"]) and found["receipt"]["source_job"] == batch


def test_ltx_is_never_fetched_for_the_user_and_says_how(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    batch = runner.submit_batch(parse(_board()))
    _wait(runner, batch)
    with pytest.raises(GenVideoError) as caught:
        runner.submit_finish(batch, [{"cut": "c1", "candidate": 1}], engine="ltx")
    text = str(caught.value)
    assert "받아 주지 않는다" in text and "Lightricks/LTX-2.5" in text and "AI 생성" in text
    check = runner.check()
    assert check["engines"]["ltx"]["ready"] is False and check["engines"]["fastwan"]["ready"] is True
    assert check["engines"]["fastwan"]["measured_sec_per_cut"]["n"] == 4


def test_ltx_end_image_and_sigmas_go_before_the_output_and_only_for_ltx(tmp_path: Path) -> None:
    files = _files(tmp_path)
    cmd = commands.build("ltx", tmp_path / "sd-cli.exe", files, prompt="p", out=tmp_path / "o.webm", width=832, height=480,
                         frames=73, seed=11, first_image="f.png", end_image="l.png", sigmas=commands.LTX_DISTILLED_SIGMAS)
    assert cmd[cmd.index("--end-img") + 1] == "l.png" and cmd[cmd.index("-i") + 1] == "f.png"
    assert cmd[cmd.index("--sigmas") + 1].startswith("1,0.99375") and cmd[-3:-1] == ["-v", "-o"]
    with pytest.raises(ValueError, match="ltx 에서만"):
        commands.build("wan", tmp_path / "x", files, prompt="p", out=tmp_path / "o", width=832, height=480, frames=73, seed=1,
                       end_image="l.png")


def _ltx_runner(tmp_path: Path, calls: list, drift_mean: float | None, grabs: list) -> tuple[VideoRunner, Any]:
    from alture_jarvis.genvideo import runner as runner_module

    bins, cudart, models = _model_dirs(tmp_path)
    ltx = tmp_path / "ltx"
    ltx.mkdir()
    for role in commands.NEEDS["ltx"]:
        (ltx / commands.FILE_PATTERNS[role][0].replace("*", "-q8")).write_bytes(b"x")
    log = (FIXTURES / "fast_p1.log.txt").read_bytes()

    def popen(cmd: list[str], **kwargs: Any) -> _FakeProcess:
        calls.append(cmd)
        return _FakeProcess(cmd, log, 0)

    def grab(clip: Path, first: Path, last: Path) -> tuple[str, str]:
        grabs.append(clip.name)
        first.write_bytes(b"png")
        last.write_bytes(b"png")
        return str(first), str(last)

    def drift(final: Path, draft: Path) -> dict[str, Any]:
        return {"ok": True, "diff": [drift_mean] * 4, "mean": drift_mean}

    return VideoRunner(tmp_path / "out", [bins, cudart], [models], ltx, popen=popen, vram_probe=lambda gpu: 9000,
                       gpus=list, ram_probe=lambda: 999999, poll_sec=0.01, inspect_fn=_fake_inspect,
                       grab_fn=grab, drift_fn=drift), runner_module


@pytest.mark.parametrize("mean, flag", [(0.30, "drift"), (0.02, "kept"), (0.11, "unclear")])
def test_ltx_finish_anchors_to_the_draft_ends_and_flags_drift(tmp_path: Path, mean: float, flag: str) -> None:
    calls: list = []
    grabs: list = []
    runner, module = _ltx_runner(tmp_path, calls, mean, grabs)
    batch = runner.submit_batch(parse(_board()))
    _wait(runner, batch)
    final = runner.submit_finish(batch, [{"cut": "c1", "candidate": 2}], engine="ltx")
    found = _wait(runner, final)
    cmd = calls[-1]
    assert grabs == ["c1_2_fastwan.webm"]  # 고른 그 시안의 첫 · 끝
    assert cmd[cmd.index("-i") + 1].endswith("c1_2_ltx_first.png") and cmd[cmd.index("--end-img") + 1].endswith("c1_2_ltx_last.png")
    assert ("--sigmas" in cmd) is module.LTX_SIGMAS_ON
    run = found["receipt"]["runs"][0]
    assert run["anchor"] == {"first": "c1_2_ltx_first.png", "last": "c1_2_ltx_last.png"}
    assert run["drift"]["flag"] == flag and run["drift"]["mean"] == mean


def test_ltx_finish_without_anchor_and_the_wan_finish_never_anchor(tmp_path: Path) -> None:
    calls: list = []
    grabs: list = []
    runner, _module = _ltx_runner(tmp_path, calls, 0.2, grabs)
    batch = runner.submit_batch(parse(_board()))
    _wait(runner, batch)
    _wait(runner, runner.submit_finish(batch, [{"cut": "c1", "candidate": 1}], engine="ltx", anchor=False))
    assert "--end-img" not in calls[-1] and grabs == []
    found = _wait(runner, runner.submit_finish(batch, [{"cut": "c1", "candidate": 1}], engine="wan"))
    assert "--end-img" not in calls[-1] and "--sigmas" not in calls[-1] and grabs == []
    assert found["receipt"]["runs"][0]["drift"]["flag"] == "drift"  # 어긋남 검사는 엔진과 상관없이 붙는다


def test_ltx_refuses_when_ram_is_short(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    runner.ltx_dir.mkdir()
    for role in commands.NEEDS["ltx"]:
        with open(runner.ltx_dir / commands.FILE_PATTERNS[role][0].replace("*", "-q8"), "wb") as handle:
            handle.truncate(2 * 1024 * 1024)
    runner._ram = lambda: 1000
    assert any("램이 모자라다" in p for p in runner.engine_problems("ltx"))
    runner._ram = lambda: 999999
    assert runner.engine_problems("ltx") == []


# ── 도구 문 · 팩 ────────────────────────────────────────────────────────

class _Config:
    def __init__(self, root: Path) -> None:
        self.data_dir = root / "data"
        self.documents_dir = root / "docs"
        self.output_dir = root / "outputs"
        self.genvideo_bin_dir = ""
        self.genvideo_models_dir = ""
        self.genvideo_ltx_dir = ""
        self.genvideo_gpu = ""
        self.genvideo_busy_cmd = ""


class _Packs:
    def __init__(self, on: bool) -> None:
        self.on = on

    def is_enabled(self, pack_id: str) -> bool:
        return self.on and pack_id == "genvideo"


NAMES = ["gen_video_check", "gen_video_prep", "gen_video_batch", "gen_video_status", "gen_video_finish"]


def test_the_pack_loads_off_with_five_tools_and_never_lists_ltx(tmp_path: Path) -> None:
    registry = PackRegistry(PACKS_DIR, tmp_path / "data")
    pack = {p["id"]: p for p in registry.listing()["packs"]}["genvideo"]
    assert pack["tools"] == NAMES and pack["enabled"] is False
    manifest = json.loads((PACKS_DIR / "genvideo" / "pack.json").read_text(encoding="utf-8"))
    models = parse_models("genvideo", manifest["models"])
    assert not any("ltx" in m["id"] or "ltx" in json.dumps(m["source"]).lower() for m in models)  # 대표 결정: 우리가 받아 주지 않는다
    assert all(m["license"] for m in models) and {m["dir"] for m in models if m["kind"] == "binary"} == {"sdcpp", "sdcpp-cudart"}
    assert (PACKS_DIR / "genvideo" / "guide" / "SKILL.md").is_file()


def test_a_disabled_pack_hides_and_refuses(tmp_path: Path) -> None:
    tools = GenVideoTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(False))
    assert tools.active_ollama_tools == []
    with pytest.raises(PermissionError, match="pack_disabled"):
        tools.gen_video_check({})
    on = GenVideoTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    assert [t["function"]["name"] for t in on.active_ollama_tools] == NAMES


def test_paths_go_through_the_file_tool_check(tmp_path: Path) -> None:
    def refuse(raw: str) -> Path:
        raise PermissionError("path_outside_allowed_roots")

    tools = GenVideoTools(_Config(tmp_path), resolve=refuse, packs=_Packs(True))
    with pytest.raises(PermissionError, match="outside_allowed"):
        tools.gen_video_prep({"image_path": "C:/Windows/secret.png"})


def test_a_first_image_outside_the_allowed_roots_is_refused_in_the_batch(tmp_path: Path) -> None:
    def refuse(raw: str) -> Path:
        raise PermissionError("path_outside_allowed_roots")

    tools = GenVideoTools(_Config(tmp_path), resolve=refuse, packs=_Packs(True))
    with pytest.raises(PermissionError):
        tools.gen_video_batch({"storyboard": {"cuts": [{"id": "a", "prompt": "x", "first_image": "C:/Windows/x.png"}]}})


def test_a_bad_board_comes_back_as_a_reason_not_a_crash(tmp_path: Path) -> None:
    tools = GenVideoTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    out = tools.gen_video_batch({"storyboard": {"cuts": [{"id": "a", "prompt": "x", "seconds": 9}]}})
    assert out["ok"] is False and "2~5초" in out["error"]


def test_default_dirs_follow_the_pack_layout(tmp_path: Path) -> None:
    config = _Config(tmp_path)
    bins, models, ltx = genvideo_dirs(config)
    data = tmp_path / "data"
    assert bins == [data / "tools" / "genvideo" / "sdcpp", data / "tools" / "genvideo" / "sdcpp-cudart"]
    assert models == [data / "models" / "genvideo"] and ltx == data / "models" / "genvideo" / "ltx25"
    config.genvideo_models_dir = str(tmp_path / "D")
    assert genvideo_dirs(config)[1][0] == tmp_path / "D"


def test_the_tools_run_on_windows_only_for_now() -> None:
    for name in NAMES:
        assert tool_runs_here(name, "win32") is True
        assert tool_runs_here(name, "darwin") is False and tool_runs_here(name, "linux") is False


def test_the_busy_command_probe_reads_working(tmp_path: Path) -> None:
    from alture_jarvis.genvideo_tools import command_probe

    assert command_probe("echo working")() == "working"
    assert command_probe("echo idle")() == "idle"
    assert command_probe("exit 1")() is None  # 아무것도 못 읽으면 「못 봄」 — 막지 않는다
    # /health JSON 통째: state 만 본다(반례 — 다른 칸에 working 이 있어도 idle)
    assert command_probe('echo {"state": "idle", "state_reason": "working dir ok"}')() == "idle"
    assert command_probe('echo {"state": "working"}')() == "working"


# ── 받기 장치: github_file ──────────────────────────────────────────────

BODY = b"TAE" * 1000
BODY_SHA = hashlib.sha256(BODY).hexdigest()
COMMIT = "fa579a9a726b0a55951998d73e309bfdf0abd342"


def _gf(**over: Any) -> dict[str, Any]:
    base = {"id": "tae", "kind": "weights", "dir": "tae",
            "source": {"github_file": "o/r", "commit": COMMIT, "path": "safetensors/taew2_2.safetensors"},
            "sha256": BODY_SHA, "size": len(BODY), "license": "MIT"}
    base.update(over)
    return base


@pytest.mark.parametrize("over, why", [
    ({"sha256": ""}, "sha256 을 꼭"),
    ({"source": {"github_file": "o/r", "commit": "main", "path": "a.bin"}}, "40자리 커밋"),
    ({"source": {"github_file": "o/r", "commit": COMMIT, "path": "../a.bin"}}, "상대 경로"),
])
def test_github_file_needs_a_pinned_commit_and_a_hash(over: dict, why: str) -> None:
    with pytest.raises(ModelError, match=why):
        parse_models("genvideo", [_gf(**over)])


class _Net:
    def __init__(self, routes: dict[str, bytes]) -> None:
        self.routes, self.calls = routes, []

    def __call__(self, url: str, headers: dict[str, str]) -> Any:
        from alture_jarvis.pack_models import _Resp

        self.calls.append(url)
        if url not in self.routes:
            raise ModelError(f"http_404: {url}")
        body = self.routes[url]
        return _Resp(200, {"content-length": str(len(body))}, io.BytesIO(body))


class _OnePack:
    def __init__(self, model: dict) -> None:
        self.packs = {"genvideo": type("P", (), {"models": parse_models("genvideo", [model])})()}


def test_github_file_downloads_the_pinned_raw_file_and_checks_the_hash(tmp_path: Path) -> None:
    url = f"https://raw.githubusercontent.com/o/r/{COMMIT}/safetensors/taew2_2.safetensors"
    net = _Net({url: BODY})
    fetcher = ModelFetcher(_OnePack(_gf()), tmp_path / "data", opener=net, hf_snapshot=None, free_bytes=lambda _p: 10**12)
    fetcher.fetch("genvideo", wait=True)
    target = tmp_path / "data" / "models" / "genvideo" / "tae" / "taew2_2.safetensors"
    assert target.read_bytes() == BODY and net.calls[0] == url
    assert fetcher.status("genvideo")["all_ready"] is True
    # 해시가 틀리면 지우고 멈춘다(파일 안 남김)
    bad = ModelFetcher(_OnePack(_gf()), tmp_path / "d2", opener=_Net({url: b"evil"}), hf_snapshot=None, free_bytes=lambda _p: 10**12)
    bad.fetch("genvideo", wait=True)
    assert not (tmp_path / "d2" / "models" / "genvideo" / "tae" / "taew2_2.safetensors").exists()
    assert bad.status("genvideo")["all_ready"] is False


# --- 11-18 콘티 컷의 끝 그림(last_image) — 실물 사진으로 끝내기(영상 세션이 짚은 빈틈) ---

def _board_with_end(tmp_path: Path, **cut_over: Any) -> dict[str, Any]:
    end = tmp_path / "product_photo.png"
    end.write_bytes(b"png")
    board = _board()
    board["cuts"][0] = {**board["cuts"][0], "last_image": str(end), **cut_over}
    return board


def test_a_cut_takes_a_last_image_checked_like_the_first(tmp_path: Path) -> None:
    board = parse(_board_with_end(tmp_path))
    cut = board["cuts"][0]
    assert cut["last_image"].endswith("product_photo.png") and cut["first_image"] is None
    assert any("LTX" in note and "last_image" in note for note in board["notes"])
    assert parse(_board())["cuts"][0]["last_image"] is None
    with pytest.raises(StoryboardError, match="last_image 가 없다"):
        parse(_board_with_end(tmp_path, last_image=str(tmp_path / "nope.png")))
    (tmp_path / "a.txt").write_text("x")
    with pytest.raises(StoryboardError, match="last_image 가 그림 파일이 아니다"):
        parse(_board_with_end(tmp_path, last_image=str(tmp_path / "a.txt")))


def test_a_last_image_outside_the_allowed_roots_is_refused_in_the_batch(tmp_path: Path) -> None:
    def refuse(raw: str) -> Path:
        raise PermissionError("path_outside_allowed_roots")

    tools = GenVideoTools(_Config(tmp_path), resolve=refuse, packs=_Packs(True))
    with pytest.raises(PermissionError):
        tools.gen_video_batch({"storyboard": {"cuts": [{"id": "a", "prompt": "x", "last_image": "C:/Windows/x.png"}]}})


def test_the_fastwan_draft_never_gets_the_end_image(tmp_path: Path) -> None:
    calls: list = []
    grabs: list = []
    runner, _module = _ltx_runner(tmp_path, calls, 0.02, grabs)
    found = _wait(runner, runner.submit_batch(parse(_board_with_end(tmp_path))))
    assert found["state"] == "done" and all("--end-img" not in cmd for cmd in calls)
    assert all("end_image" not in run for run in found["receipt"]["runs"])


def test_ltx_finish_ends_on_the_given_picture_not_the_draft_last_frame(tmp_path: Path) -> None:
    calls: list = []
    grabs: list = []
    runner, _module = _ltx_runner(tmp_path, calls, 0.02, grabs)
    batch = runner.submit_batch(parse(_board_with_end(tmp_path)))
    _wait(runner, batch)
    found = _wait(runner, runner.submit_finish(batch, [{"cut": "c1", "candidate": 2}], engine="ltx"))
    cmd = calls[-1]
    assert cmd[cmd.index("--end-img") + 1].endswith("product_photo.png")  # 사람이 준 끝 그림이 앞선다
    assert cmd[cmd.index("-i") + 1].endswith("c1_2_ltx_first.png")  # 처음은 여전히 시안의 첫 프레임
    run = found["receipt"]["runs"][0]
    assert run["anchor"] == {"first": "c1_2_ltx_first.png", "last": "product_photo.png"}
    assert run["end_image"] == "product_photo.png"


def test_ltx_finish_without_anchor_still_ends_on_the_given_picture(tmp_path: Path) -> None:
    calls: list = []
    grabs: list = []
    runner, _module = _ltx_runner(tmp_path, calls, 0.02, grabs)
    batch = runner.submit_batch(parse(_board_with_end(tmp_path)))
    _wait(runner, batch)
    _wait(runner, runner.submit_finish(batch, [{"cut": "c1", "candidate": 1}], engine="ltx", anchor=False))
    assert calls[-1][calls[-1].index("--end-img") + 1].endswith("product_photo.png") and grabs == []


def test_wan_finish_refuses_a_cut_with_an_end_image_instead_of_dropping_it(tmp_path: Path) -> None:
    calls: list = []
    runner = _runner(tmp_path, calls=calls)
    batch = runner.submit_batch(parse(_board_with_end(tmp_path)))
    _wait(runner, batch)
    with pytest.raises(GenVideoError, match="end_image_needs_ltx"):
        runner.submit_finish(batch, [{"cut": "c1", "candidate": 1}], engine="wan")
    tools = GenVideoTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    tools._runner = runner
    out = tools.gen_video_finish({"job_id": batch, "picks": [{"cut": "c1", "candidate": 1}], "engine": "wan"})
    assert out["ok"] is False and "ltx" in out["error"]
