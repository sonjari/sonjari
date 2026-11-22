"""3D 색 렌더 — 조명 있는 앞 · 3/4 (2026-11-16 · `gen3d/beauty.py` · 팩 잇기 낙서 → 3D → 영상).

블렌더 없이(가짜):
- 해야 할 것: 굽기 영수증 files.beauty 에 [앞, 3/4] · receipt.beauty 에 시간 · 밝기 / gen_3d_views source=beauty 가 그 두 장을 돌려줌 ·
  없으면 지금 찍음 / 도구 목록에 beauty
- 하면 안 되는 것: 블렌더가 없거나 렌더가 터졌다고 굽기가 실패함 / 블렌더가 없는데 조용히 빠짐(not_done 에 까닭 · 대신 쓸 것) /
  새까만 판(텍스처 바탕색 검정)을 그냥 넘김 / 블렌더 안 스크립트가 우리 코드를 import 함
블렌더가 있을 때만: 회색 상자 · 금속 공이 실제로 찍히고 밝기가 0 이 아님(금속도 새까맣지 않음) · 투명 PNG 는 알파가 있음
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from test_gen3d_1114 import (  # noqa: F401 — 자동 고정(진짜 슬라이서 안 부름)
    _Config,
    _cube,
    _no_real_slicer,
    _Packs,
    _runner,
    _wait,
    _write_glb,
)

from alture_jarvis.gen3d import beauty as beauty_mod
from alture_jarvis.gen3d.beauty import BG, measure, render_beauty
from alture_jarvis.gen3d.blender import SCRIPTS, find_blender
from alture_jarvis.gen3d.glb import Mesh
from alture_jarvis.gen3d.runner import Gen3DError
from alture_jarvis.gen3d_tools import GEN_3D_VIEWS_TOOL, Gen3DTools


def _found() -> dict[str, Any]:
    return {"found": True, "exe": "blender.exe", "version": "5.2", "why": ""}


def _missing() -> dict[str, Any]:
    return {"found": False, "exe": None, "version": None, "why": "블렌더를 못 찾았다"}


def _paint(path: str, color: tuple[int, int, int], share: float = 0.3) -> None:
    """바탕(BG) 가운데에 color 네모 — share 만큼 차지."""
    bg = tuple(round(c * 255) for c in BG)
    img = np.zeros((100, 100, 3), dtype=np.uint8) + np.asarray(bg, dtype=np.uint8)
    side = round(100 * share ** 0.5)
    lo = (100 - side) // 2
    img[lo:lo + side, lo:lo + side] = color
    Image.fromarray(img).save(path)


class _FakeRun:
    """run_script 꼴: 받은 views 자리에 그림을 그리고 결과를 돌려준다."""

    def __init__(self, color: tuple[int, int, int] = (200, 120, 60), ok: bool = True, boom: bool = False) -> None:
        self.color, self.ok, self.boom = color, ok, boom
        self.jobs: list[dict[str, Any]] = []

    def __call__(self, script: str, job: dict[str, Any], *, exe: str | None = None) -> dict[str, Any]:
        assert script == "beauty.py"
        self.jobs.append(job)
        if self.boom:
            raise RuntimeError("블렌더가 터짐")
        if not self.ok:
            return {"ok": False, "error": "RuntimeError: 일부러 실패", "rc": 1}
        for path in job["views"].values():
            _paint(path, self.color)
        return {"ok": True, "engine": "CYCLES/CPU", "samples": job["samples"], "view_transform": "Standard", "metallic": [], "rc": 0}


# ── 우리 쪽(beauty.py) ──────────────────────────────────────────────────
def test_no_blender_is_said_with_a_reason_and_what_to_use_instead(tmp_path: Path) -> None:
    out = render_beauty(tmp_path / "a.glb", tmp_path / "out", "a", find=_missing, run=_FakeRun())
    assert out["ok"] is False and out["files"] == []
    assert len(out["not_done"]) == 1
    note = out["not_done"][0]
    assert "블렌더를 못 찾았다" in note and "source=model" in note
    assert not (tmp_path / "out").exists()  # 아무것도 안 만든다


def test_a_render_gives_front_and_three_quarter_and_measures_them(tmp_path: Path) -> None:
    run = _FakeRun()
    out = render_beauty(tmp_path / "a.glb", tmp_path / "out", "a", find=_found, run=run)
    assert out["ok"] is True and out["not_done"] == []
    assert [Path(p).name for p in out["files"]] == ["a_beauty_front.png", "a_beauty_three_quarter.png"]
    assert set(out["measured"]) == {"앞", "3/4"}
    assert out["measured"]["앞"]["cover"] == pytest.approx(0.3, abs=0.02)
    assert out["measured"]["앞"]["mean"] > 0.3 and out["measured"]["앞"]["black"] == 0
    job = run.jobs[0]
    assert job["transparent"] is False and job["threads"] >= 2 and job["size"] == 768


def test_a_black_model_is_flagged_not_passed_as_fine(tmp_path: Path) -> None:
    """11-16 로봇: 텍스처 바탕색이 검정(금속도 0.82 자리) — 조명을 받고도 새까맣다. 그냥 넘기면 안 된다."""
    out = render_beauty(tmp_path / "a.glb", tmp_path / "out", "a", find=_found, run=_FakeRun(color=(2, 2, 3)))
    assert out["ok"] is True  # 그림은 나왔다 — 판단은 not_done 으로
    assert len(out["not_done"]) == 2 and all("새까맣다" in n for n in out["not_done"])


def test_a_failed_or_crashed_render_says_so(tmp_path: Path) -> None:
    for run in (_FakeRun(ok=False), _FakeRun(boom=True)):
        out = render_beauty(tmp_path / "a.glb", tmp_path / "out", "a", find=_found, run=run)
        assert out["ok"] is False and out["files"] == []
        assert "색 렌더 실패" in out["not_done"][0] and "source=model" in out["not_done"][0]


def test_measure_uses_alpha_when_the_png_is_transparent(tmp_path: Path) -> None:
    img = np.zeros((10, 10, 4), dtype=np.uint8)
    img[:5, :, :3] = 255
    img[:5, :, 3] = 255
    Image.fromarray(img).save(tmp_path / "t.png")
    m = measure(tmp_path / "t.png")
    assert m["cover"] == 0.5 and m["mean"] == pytest.approx(1.0, abs=0.01) and m["black"] == 0


# ── 굽기 영수증 · views ────────────────────────────────────────────────
def _bake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, find: Any = _found, run: Any = None, on: bool = True) -> tuple[Any, str, dict]:
    monkeypatch.setenv("JARVIS_GEN3D_BEAUTY", "1" if on else "0")
    runner = _runner(tmp_path)
    runner._find_blender = find
    fake = run or _FakeRun()
    runner._render_beauty = lambda glb, folder, stem, find=None: render_beauty(glb, folder, stem, find=find, run=fake)
    image = tmp_path / "a.png"
    image.write_bytes(b"png")
    job_id = runner.submit(image)
    return runner, job_id, _wait(runner, job_id)


def test_the_bake_receipt_carries_the_beauty_renders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, job_id, found = _bake(tmp_path, monkeypatch)
    assert found["state"] == "done"
    receipt = found["receipt"]
    files = receipt["files"]["beauty"]
    assert len(files) == 2 and all(Path(p).is_file() for p in files)
    assert Path(files[0]).parent == Path(receipt["files"]["glb"]).parent
    assert set(receipt["beauty"]["measured"]) == {"앞", "3/4"}
    assert not any("색 렌더" in n for n in receipt["not_done"])
    # views source=beauty 는 그 두 장을 그대로(다시 찍지 않음)
    out = runner.views(job_id, source="beauty")
    assert out["cached"] is True and out["files"] == files


def test_no_blender_or_a_crash_never_fails_the_bake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for i, kw in enumerate(({"find": _missing}, {"run": _FakeRun(boom=True)}, {"on": False})):
        home = tmp_path / str(i)
        home.mkdir()
        _, _, found = _bake(home, monkeypatch, **kw)
        assert found["state"] == "done", kw
        receipt = found["receipt"]
        assert "beauty" not in receipt["files"] and "beauty" not in receipt
        notes = [n for n in receipt["not_done"] if "색 렌더" in n]
        assert len(notes) == 1 and "source=model" in notes[0], notes
        assert receipt["files"]["views"] and receipt["files"]["glb"]  # 다른 판은 그대로


def test_views_beauty_renders_now_for_an_old_job_and_errors_without_blender(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, job_id, _ = _bake(tmp_path, monkeypatch, on=False)  # 색 렌더 없이 구운 옛 판
    monkeypatch.setenv("JARVIS_GEN3D_BEAUTY", "1")
    out = runner.views(job_id, source="beauty")
    assert out["cached"] is False and len(out["files"]) == 2
    assert all(Path(p).parent.name == "views" for p in out["files"])
    runner._find_blender = _missing
    tools = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    tools._runner = runner
    # views 폴더의 그림은 영수증 칸이 아니므로 다시 찍으러 간다 → 블렌더 없음
    with pytest.raises(Gen3DError, match="블렌더를 못 찾았다"):
        runner.views(job_id, source="beauty")
    said = tools.gen_3d_views({"job_id": job_id, "source": "beauty"})
    assert said["ok"] is False and "source=model" in said["error"]


def test_the_views_tool_offers_beauty() -> None:
    source = GEN_3D_VIEWS_TOOL["function"]["parameters"]["properties"]["source"]
    assert "beauty" in source["enum"] and "beauty" in source["description"]


def test_the_blender_script_stays_apart() -> None:
    script = (SCRIPTS / "beauty.py").read_text(encoding="utf-8")
    assert script.startswith("# SPDX-License-Identifier: GPL-3.0-or-later")
    assert "alture_jarvis" not in script and "from ." not in script
    assert 'device = "CPU"' in script  # 그래픽카드는 굽기 · 영상 몫
    ours = Path(beauty_mod.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+bpy", ours, re.MULTILINE)


# ── 블렌더가 있을 때만 ──────────────────────────────────────────────────
_BLENDER = find_blender()
needs_blender = pytest.mark.skipif(not _BLENDER["found"], reason="블렌더가 없는 기계")


def _sphere(n: int = 24) -> Mesh:
    lat = np.linspace(0, np.pi, n)
    lon = np.linspace(0, 2 * np.pi, 2 * n, endpoint=False)
    pts = [[0, 1, 0]] + [[np.sin(a) * np.cos(b), np.cos(a), np.sin(a) * np.sin(b)] for a in lat[1:-1] for b in lon] + [[0, -1, 0]]
    rows, m = n - 2, 2 * n
    faces = [[0, 1 + (j + 1) % m, 1 + j] for j in range(m)]
    for i in range(rows - 1):
        for j in range(m):
            a, b = 1 + i * m + j, 1 + i * m + (j + 1) % m
            faces += [[a, b, b + m], [a, b + m, a + m]]
    last = len(pts) - 1
    faces += [[last, 1 + (rows - 1) * m + j, 1 + (rows - 1) * m + (j + 1) % m] for j in range(m)]
    return Mesh(positions=np.asarray(pts, dtype=np.float64), faces=np.asarray(faces))


def _with_material(path: Path, base: list[float], metallic: float, rough: float) -> None:
    """_write_glb 가 쓴 GLB 에 PBR 재질 하나를 붙인다(JSON 덩이만 바꿈)."""
    raw = path.read_bytes()
    n = struct.unpack("<I", raw[12:16])[0]
    gltf = json.loads(raw[20:20 + n])
    rest = raw[20 + n:]
    gltf["materials"] = [{"pbrMetallicRoughness": {"baseColorFactor": [*base, 1.0], "metallicFactor": metallic, "roughnessFactor": rough}}]
    gltf["meshes"][0]["primitives"][0]["material"] = 0
    text = json.dumps(gltf).encode()
    text += b" " * (-len(text) % 4)
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + rest
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


@needs_blender
def test_a_gray_box_and_a_metal_ball_really_render_and_are_not_black(tmp_path: Path) -> None:
    box = tmp_path / "box.glb"
    _write_glb(box, _cube())  # 재질 없음 → 회색 기본 재질
    ball = tmp_path / "ball.glb"
    _write_glb(ball, _sphere())
    _with_material(ball, [0.8, 0.8, 0.8], metallic=1.0, rough=0.25)  # 금속 — 조명 없는 판이면 새까맣던 꼴
    for glb in (box, ball):
        out = render_beauty(glb, tmp_path / "out", glb.stem, size=256, samples=16)
        assert out["ok"] is True, out
        assert out["not_done"] == [], out
        for name, m in out["measured"].items():
            assert 0.05 < m["cover"] < 0.9, (glb.stem, name, m)
            assert m["mean"] > 0.15 and m["black"] < 0.25, (glb.stem, name, m)
        assert out["metallic"] == ([1.0] if glb is ball else [0.0])  # 상자는 회색 기본 재질(금속 0)


@needs_blender
def test_a_transparent_render_has_alpha(tmp_path: Path) -> None:
    box = tmp_path / "box.glb"
    _write_glb(box, _cube())
    out = render_beauty(box, tmp_path / "out", "box", size=128, samples=8, transparent=True)
    assert out["ok"] is True and all(p.endswith("_alpha.png") for p in out["files"])
    alpha = np.asarray(Image.open(out["files"][0]).convert("RGBA"))[..., 3]
    assert alpha.min() == 0 and alpha.max() == 255
