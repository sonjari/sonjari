"""3D 블렌더 마무리 — `gen_3d_finish` · 겉면 펴기 `smooth_surface` (2026-11-16 · 설계 `설계_3D작업대_블렌더마무리` §4-③ · §6).

블렌더 없이 도는 것(가짜 블렌더):
- 해야 할 것: 도구가 목록 · 문에 L1 로 오름 / finish_v1 · v2 차례 · 원본 GLB 바이트 그대로 / 두 번째는 앞 판에서 시작(base=last) ·
  original 이면 원본에서 / 영수증에 한 일 · 숫자 · 파일 · 못 한 것 · 전후 판 / 프린트 준비가 마지막 마무리 판을 씀
- 하면 안 되는 것: 블렌더가 없는데 폴더를 만들거나 다른 단계를 막음 / 실패한 판을 「마지막 판」으로 씀 / 굽기와 겹쳐 돎 /
  모르는 작업 · 상자 없는 지우기 · 1~60 밖 횟수를 그대로 넘김
블렌더가 있을 때만(`find_blender` 로 찾음 · 없으면 건너뜀):
- 울퉁불퉁한 공을 8번 펴면 꺾임이 크게 줄고 부피는 ±2% 안
- 일부러 판 홈(입선 · 눈 새김 꼴)은 8번 뒤에도 깊이가 절반 넘게 남는다 — 30번이면 그보다 더 지워진다(잣대가 횟수를 가르는지)
"""
from __future__ import annotations

import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from test_gen3d_1114 import (  # noqa: F401 — 자동 고정(진짜 슬라이서 안 부름)
    _Config,
    _no_real_slicer,
    _Packs,
    _runner,
    _wait,
    _write_glb,
)

from alture_jarvis.gen3d.blender import SCRIPTS, find_blender, run_finish
from alture_jarvis.gen3d.glb import Mesh, read_glb
from alture_jarvis.gen3d.runner import FINISH_OPS, SMOOTH_SURFACE_ROUNDS, Gen3DError
from alture_jarvis.gen3d_tools import Gen3DTools


# ── 가짜 블렌더 ──────────────────────────────────────────────────────────
class _FakeBlender:
    """run_finish 와 같은 꼴: src 를 dst 로 베끼고(모양은 그대로) 정해 둔 결과를 돌려준다."""

    def __init__(self, ok: bool = True, hold: threading.Event | None = None, write: Mesh | None = None) -> None:
        self.calls: list[tuple[Path, Path, list[dict[str, Any]]]] = []
        self.ok = ok
        self.hold = hold
        #: 주면 베끼지 않고 이 모양을 쓴다 — 뒤 단계가 정말 마무리 판을 읽는지 모양으로 가른다.
        self.write = write
        self.started = threading.Event()

    def __call__(self, src: Path, dst: Path, ops: list[dict[str, Any]], *, exe: str | None = None) -> dict[str, Any]:
        self.calls.append((Path(src), Path(dst), ops))
        self.started.set()
        if self.hold is not None:
            self.hold.wait(5)
        if not self.ok:
            return {"ok": False, "error": "RuntimeError: 일부러 실패", "rc": 1}
        if self.write is not None:
            _write_glb(dst, self.write)
        else:
            shutil.copyfile(src, dst)
        return {"ok": True, "blender": "5.2.3 LTS", "rc": 0, "before": {"verts": 8, "faces": 12},
                "after": {"verts": 8, "faces": 12, "parts": 1, "open_edges": 0},
                "ops": [{"op": "smooth_surface", "rounds": op.get("rounds"), "verts": 8, "merged_verts": 0,
                         "move_mm": {"median": 0.11, "p95": 0.27, "max": 1.32, "long_side_mm": op.get("size_mm")},
                         "volume_change_pct": -0.163, "volume_closed": False} for op in ops]}


def _found() -> dict[str, Any]:
    return {"found": True, "exe": "blender.exe", "version": "5.2", "why": ""}


def _done_runner(tmp_path: Path, fake: _FakeBlender | None = None) -> tuple[Any, str]:
    runner = _runner(tmp_path)
    image = tmp_path / "a.png"
    image.write_bytes(b"png")
    job_id = runner.submit(image)
    assert _wait(runner, job_id)["state"] == "done"
    runner._find_blender = _found
    runner._run_finish = fake or _FakeBlender()
    return runner, job_id


# ── 블렌더 없이 ──────────────────────────────────────────────────────────
def test_the_tool_is_listed_and_registered_as_a_write_tool(tmp_path: Path) -> None:
    tools = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    names = [t["function"]["name"] for t in tools.active_ollama_tools]
    assert "gen_3d_finish" in names

    class _Gateway:
        def __init__(self) -> None:
            self.specs: dict[str, Any] = {}

        def register(self, spec: Any) -> None:
            self.specs[spec.name] = spec

    gateway = _Gateway()
    tools.register(gateway)
    spec = gateway.specs["gen_3d_finish"]
    assert spec.risk_level.name == "L1" and spec.parameters["required"] == ["job_id"]
    off = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(False))
    with pytest.raises(PermissionError, match="pack_disabled"):
        off.gen_3d_finish({"job_id": "g3_x"})


def test_versions_count_up_and_the_original_is_never_touched(tmp_path: Path) -> None:
    fake = _FakeBlender()
    runner, job_id = _done_runner(tmp_path, fake)
    home = runner.out_root / job_id
    original = next(home.glob("*.glb"))
    before = original.read_bytes()
    first = runner.finish(job_id, [{"op": "smooth_surface"}])
    second = runner.finish(job_id, [{"op": "smooth_surface", "rounds": 5}])
    assert first["ok"] and second["ok"]
    assert (first["version"], second["version"]) == ("finish_v1", "finish_v2")
    assert original.read_bytes() == before
    # 두 번째는 앞 판에서 시작 · original 이면 원본에서
    assert fake.calls[0][0] == original.resolve() and first["from"] == "구운 원본"
    assert fake.calls[1][0].parent.name == "finish_v1" and second["from"] == "finish_v1"
    third = runner.finish(job_id, [{"op": "smooth_surface"}], base="original")
    assert fake.calls[2][0] == original.resolve() and third["version"] == "finish_v3"
    with pytest.raises(ValueError, match="base"):
        runner.finish(job_id, [{"op": "smooth_surface"}], base="finish_v9")


def test_the_receipt_reads_the_blender_result(tmp_path: Path) -> None:
    runner, job_id = _done_runner(tmp_path)
    out = runner.finish(job_id, [{"op": "smooth_surface"}], size_mm=80, zoom="앞")
    assert out["ok"] and out["numbers"][0]["move_mm"]["long_side_mm"] == 80
    line = out["did"][0]
    for piece in ("8번", "0.11mm", "0.27mm", "1.32mm", "80.0mm", "-0.163%"):
        assert piece in line, (piece, line)
    assert any("숫자로 재지 않았다" in n for n in out["not_done"])
    assert any("어림값" in n for n in out["not_done"])  # 열린 메시
    sheet = Image.open(out["files"]["before_after"])
    assert sheet.size == (400 * 4, 400 * 3)  # 방향마다 전 · 후 한 쌍 × 6
    assert Image.open(out["files"]["before_after_zoom"]).size == (900 * 2, 900)
    saved = (runner.out_root / job_id / "finish_v1" / "finish.json").read_text(encoding="utf-8")
    assert '"ok": true' in saved and "before_after.png" in saved


def test_no_blender_gives_a_reason_and_blocks_nothing_else(tmp_path: Path) -> None:
    runner, job_id = _done_runner(tmp_path)
    runner._find_blender = lambda: {"found": False, "exe": None, "version": None, "why": "블렌더를 못 찾았다"}
    with pytest.raises(Gen3DError, match="no_blender"):
        runner.finish(job_id, [{"op": "smooth_surface"}])
    assert not list((runner.out_root / job_id).glob("finish_v*"))  # 빈 폴더도 안 남김
    # 도구 문은 까닭을 돌려준다
    tools = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    tools._runner = runner
    got = tools.gen_3d_finish({"job_id": job_id})
    assert got["ok"] is False and "no_blender" in got["error"]
    # 다른 단계(프린트 준비 · 6방향 판)는 그대로
    assert runner.reprint(job_id, export=["stl"])["from"] == "구운 원본"
    assert Path(runner.views(job_id, source="shape")["file"]).is_file()


def test_a_failed_finish_is_recorded_but_never_used_as_the_last_version(tmp_path: Path) -> None:
    runner, job_id = _done_runner(tmp_path, _FakeBlender(ok=False))
    out = runner.finish(job_id, [{"op": "smooth_surface"}])
    assert out["ok"] is False and "일부러 실패" in out["error"] and out["not_done"]
    assert (runner.out_root / job_id / "finish_v1" / "finish.json").is_file()
    assert runner.finish_versions(runner.out_root / job_id) == []
    assert runner.reprint(job_id, export=["stl"])["from"] == "구운 원본"


def _printed_extent(runner: Any, job_id: str, version: str) -> np.ndarray:
    from alture_jarvis.gen3d.runner import _read_stl

    stl = next((runner.out_root / job_id / version).glob("*.stl"))
    pos, _ = _read_stl(stl)
    ext = pos.max(axis=0) - pos.min(axis=0)
    return np.sort(ext) / ext.max()


def test_print_uses_the_last_finished_version(tmp_path: Path) -> None:
    # 구운 원본은 2 × 1 × 0.5 상자 — 마무리 판은 정육면체로 써서 무엇을 뽑았는지 모양으로 가른다(이름표만 보지 않는다)
    from test_gen3d_1114 import _cube

    cube = Mesh(_cube().positions / [2.0, 1.0, 0.5], _cube().faces)
    runner, job_id = _done_runner(tmp_path, _FakeBlender(write=cube))
    plain = runner.reprint(job_id, export=["stl"])
    assert plain["from"] == "구운 원본"
    assert np.allclose(_printed_extent(runner, job_id, plain["version"]), [0.25, 0.5, 1.0], atol=0.05)
    runner.finish(job_id, [{"op": "smooth_surface"}])
    runner.finish(job_id, [{"op": "smooth_surface"}])
    out = runner.reprint(job_id, export=["stl"])
    assert out["from"] == "finish_v2"
    assert np.allclose(_printed_extent(runner, job_id, out["version"]), [1.0, 1.0, 1.0], atol=0.05)
    saved = (runner.out_root / job_id / out["version"] / "print.json").read_text(encoding="utf-8")
    assert '"from": "finish_v2"' in saved


def test_finish_and_bake_share_one_line(tmp_path: Path) -> None:
    hold = threading.Event()
    fake = _FakeBlender(hold=hold)
    runner, job_id = _done_runner(tmp_path, fake)
    # ① 마무리가 도는 동안 들어온 굽기는 기다렸다가(queued) 마무리가 끝난 뒤 돈다
    worker = threading.Thread(target=runner.finish, args=(job_id, [{"op": "smooth_surface"}]))
    worker.start()
    assert fake.started.wait(3)
    image = tmp_path / "b.png"
    image.write_bytes(b"png")
    second = runner.submit(image)
    time.sleep(0.3)
    assert runner.get(second)["state"] == "queued"
    # 마무리 둘은 겹치지 않는다
    with pytest.raises(Gen3DError, match="busy"):
        runner.finish(job_id, [{"op": "smooth_surface"}])
    hold.set()
    worker.join(5)
    assert _wait(runner, second)["state"] == "done"
    # ② 굽기가 돌거나 기다리면 마무리는 바로 busy
    runner._heavy.acquire()  # 굽기를 붙잡아 둔다
    try:
        third = runner.submit(image)
        with pytest.raises(Gen3DError, match="busy"):
            runner.finish(job_id, [{"op": "smooth_surface"}])
    finally:
        runner._heavy.release()
    assert _wait(runner, third)["state"] == "done"


def test_ops_are_checked_before_blender_runs(tmp_path: Path) -> None:
    fake = _FakeBlender()
    runner, job_id = _done_runner(tmp_path, fake)
    for bad, msg in (([], "하나 이상"), ([{"op": "melt"}], "op 는"), ([{"op": "smooth_surface", "rounds": 0}], "1~60"),
                     ([{"op": "smooth_surface", "rounds": 61}], "1~60"), ([{"op": "erase_fill"}], "box"),
                     ([{"op": "smooth_surface", "box": {"center": [0, 0]}}], "box"), ([{"op": "symmetrize", "keep": "y"}], "keep"),
                     ([{"op": "smooth_surface"}] * 9, "8개")):
        with pytest.raises(ValueError, match=msg):
            runner.finish(job_id, bad)
    assert fake.calls == []
    runner.finish(job_id, [{"op": "smooth_surface", "exe": "rm -rf", "size_mm": 999}], size_mm=60)
    sent = fake.calls[0][2][0]
    # 모르는 칸은 버리고 · 기본 8번 · 크기는 도구 인자에서
    assert sent == {"op": "smooth_surface", "rounds": SMOOTH_SURFACE_ROUNDS, "size_mm": 60.0} and SMOOTH_SURFACE_ROUNDS == 8


def test_the_op_list_matches_the_blender_script_and_the_script_stays_apart() -> None:
    text = (SCRIPTS / "finish.py").read_text(encoding="utf-8")
    handled = set(re.findall(r'op\["op"\] == "(\w+)"', text))
    assert handled == set(FINISH_OPS)
    assert text.startswith("# SPDX-License-Identifier: GPL-3.0-or-later")
    assert "alture_jarvis" not in text and "from ." not in text
    assert "CORRECTIVE_SMOOTH" in text and "LENGTH_WEIGHTED" in text and "ORCO" in text and "use_only_smooth = True" in text


# ── 블렌더가 있을 때만 ─────────────────────────────────────────────────────
_BLENDER = find_blender()
needs_blender = pytest.mark.skipif(not _BLENDER["found"], reason="블렌더가 없는 기계")


def _icosphere(level: int) -> tuple[np.ndarray, np.ndarray]:
    t = (1 + 5 ** 0.5) / 2
    v = [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
         [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]]
    f = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
         [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]]
    verts = [np.array(p, float) / np.linalg.norm(p) for p in v]
    faces = f
    for _ in range(level):
        cache: dict[tuple[int, int], int] = {}

        def mid(a: int, b: int, cache: dict[tuple[int, int], int] = cache) -> int:
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = verts[a] + verts[b]
                verts.append(m / np.linalg.norm(m))
                cache[key] = len(verts) - 1
            return cache[key]

        nxt = []
        for a, b, c in faces:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nxt += [[a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]]
        faces = nxt
    return np.array(verts), np.array(faces, dtype=np.int64)


def _weld(mesh: Mesh) -> tuple[np.ndarray, np.ndarray]:
    """블렌더가 내보낸 GLB 는 면 방향(노멀)마다 꼭짓점을 쪼갤 수 있다 — 자리로 다시 합친다."""
    key = np.round(mesh.positions, 6)
    uniq, inverse = np.unique(key, axis=0, return_inverse=True)
    return uniq, inverse.reshape(-1)[mesh.faces]


def _crease(pos: np.ndarray, faces: np.ndarray) -> float:
    """이웃한 두 면의 꺾임 각(도) 평균 — 울퉁불퉁할수록 크다."""
    tri = pos[faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1)[:, None]
    edges: dict[tuple[int, int], list[int]] = {}
    for i, (a, b, c) in enumerate(faces.tolist()):
        for x, y in ((a, b), (b, c), (c, a)):
            edges.setdefault((min(x, y), max(x, y)), []).append(i)
    pairs = np.array([fs for fs in edges.values() if len(fs) == 2])
    cos = np.clip((n[pairs[:, 0]] * n[pairs[:, 1]]).sum(axis=1), -1, 1)
    return float(np.degrees(np.arccos(cos)).mean())


def _volume(pos: np.ndarray, faces: np.ndarray) -> float:
    tri = pos[faces]
    return float(abs(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum()) / 6)


def _smooth(tmp_path: Path, pos: np.ndarray, faces: np.ndarray, rounds: int, name: str) -> tuple[np.ndarray, np.ndarray, dict]:
    src, dst = tmp_path / f"{name}_in.glb", tmp_path / f"{name}_out.glb"
    _write_glb(src, Mesh(pos, faces))
    result = run_finish(src, dst, [{"op": "smooth_surface", "rounds": rounds, "size_mm": 80}], exe=_BLENDER["exe"])
    assert result["ok"], result
    out = read_glb(dst)
    # 블렌더는 z 위로 읽었다가 glTF(y 위)로 다시 내보낸다 — 자리는 그대로여야 한다
    welded, wf = _weld(out)
    return welded, wf, result


@needs_blender
def test_a_bumpy_ball_gets_smoother_and_keeps_its_volume(tmp_path: Path) -> None:
    pos, faces = _icosphere(5)  # 10,242 꼭짓점 · 모서리 약 0.03
    rng = np.random.default_rng(7)
    bumpy = pos * (1 + rng.uniform(-0.01, 0.01, len(pos)))[:, None]
    after, af, result = _smooth(tmp_path, bumpy, faces, SMOOTH_SURFACE_ROUNDS, "bumpy")
    c0, c1 = _crease(bumpy, faces), _crease(after, af)
    v0, v1 = _volume(bumpy, faces), _volume(after, af)
    assert len(after) == len(pos)  # 꼭짓점 수 그대로(합칠 것 없음)
    assert c1 < c0 * 0.5, (c0, c1)
    assert abs(v1 / v0 - 1) < 0.02, (v0, v1)
    item = result["ops"][0]
    assert item["rounds"] == 8 and item["volume_closed"] is True and abs(item["volume_change_pct"]) < 2
    move = item["move_mm"]
    assert 0 < move["median"] <= move["p95"] <= move["max"] and move["long_side_mm"] == 80


def _groove_depth(pos: np.ndarray) -> float:
    """적도 띠(홈 가운데)의 반지름이 홈 밖(|y| 0.3~0.4) 반지름보다 얼마나 들어갔나."""
    r = np.linalg.norm(pos, axis=1)
    y = pos[:, 1] / r
    center = r[np.abs(y) < 0.01].mean()
    outside = r[(np.abs(y) > 0.3) & (np.abs(y) < 0.4)].mean()
    return float(outside - center)


@needs_blender
def test_a_deliberate_groove_survives_the_default_but_not_heavy_smoothing(tmp_path: Path) -> None:
    pos, faces = _icosphere(5)
    # 적도에 폭 ±0.09(모서리 약 3개씩) · 깊이 0.04 의 둥근 홈 — 입선 · 눈 새김 꼴
    y = pos[:, 1]
    dip = np.where(np.abs(y) < 0.09, 0.04 * np.cos(np.abs(y) / 0.09 * np.pi / 2) ** 2, 0.0)
    grooved = pos * (1 - dip)[:, None]
    d0 = _groove_depth(grooved)
    after8, _, _ = _smooth(tmp_path, grooved, faces, 8, "g8")
    after30, _, _ = _smooth(tmp_path, grooved, faces, 30, "g30")
    d8, d30 = _groove_depth(after8), _groove_depth(after30)
    assert d8 > 0.5 * d0, (d0, d8)
    assert d30 < d8, (d8, d30)  # 많이 펴면 더 지워진다 — 잣대가 횟수를 가른다
