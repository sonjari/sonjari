"""3D 프린트 갈래 — 일부러 깨 보는 시험 (2026-11-14 · 설계 `설계_3D프린트갈래` §8 · 대표 「기계를 만지는 거니 적대적 검토」).

다시 뜨기 · 재서 고르기 · 썰기를 반례로 친다. 실제 뱀부 스튜디오는 부르지 않는다(가짜 실행 · 가짜 설정 폴더).
- 깨진 메시(비다양체 · 구멍) → 늘 닫힌 메시 / 이미 깨끗한 상자 → 모양이 거의 그대로
- 큰 구멍 → 「샘」을 정직하게 / 빈 입력 → 빈 결과
- 오버행 → 서포트 켜짐 / 바닥 넓은 상자 → 꺼짐 / 키 큰 기둥 → 브림
- 썰기: 판보다 큼 → 썰기 전 거절 · 지원 안 하는 기종(A1) → 거절 · rc 139 + G-code → 성공 · rc 0 + G-code 없음 → 실패 ·
  높이 어긋남 → 표시 · 설정 상속을 풀어 밀도가 들어감 · 고른 설정이 공정 파일에 써짐 · 프린터로 보내는 명령이 없음
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from alture_jarvis.gen3d.glb import Mesh
from alture_jarvis.gen3d.print_plan import plan_print
from alture_jarvis.gen3d.printing import check_printable
from alture_jarvis.gen3d.remesh import remesh
from alture_jarvis.gen3d import slicer

SRC = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "gen3d"


# ── 메시 재료 ──────────────────────────────────────────────────────────
def _box(lo=(0, 0, 0), hi=(10, 10, 10), open_top: bool = False) -> tuple[np.ndarray, np.ndarray]:
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], dtype=float)
    f = [[0, 2, 1], [0, 3, 2], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
         [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
    if not open_top:
        f += [[4, 5, 6], [4, 6, 7]]
    return v, np.array(f, dtype=np.int64)


def _merge(*parts: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    vs, fs, off = [], [], 0
    for v, f in parts:
        vs.append(v)
        fs.append(f + off)
        off += len(v)
    return np.concatenate(vs), np.concatenate(fs)


def _closed_ok(pos: np.ndarray, faces: np.ndarray) -> dict[str, Any]:
    check = check_printable(Mesh(pos, faces))
    assert check["boundary_edges"] == 0 and check["non_manifold_edges"] == 0 and check["flipped_edges"] == 0, check
    return check


def _volume(pos: np.ndarray, faces: np.ndarray) -> float:
    a, b, c = pos[faces[:, 0]], pos[faces[:, 1]], pos[faces[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


# ── 다시 뜨기 ──────────────────────────────────────────────────────────
def test_a_non_manifold_mesh_comes_out_closed() -> None:
    """모서리 하나만 맞댄 두 상자 — 그 모서리에 면이 넷 붙어 비다양체다(실행기 결과의 흔한 꼴)."""
    pos, faces = _merge(_box((0, 0, 0), (10, 10, 10)), _box((10, 10, 0), (20, 20, 10)))
    assert check_printable(Mesh(pos, faces))["non_manifold_edges"] > 0  # 정말 깨진 입력인지
    r = remesh(pos, faces, pitch=0.5, smooth_rounds=0)
    _closed_ok(r.positions, r.faces)


def _box_with_fine_top(size: float = 20.0, step: float = 2.0, drop: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """윗면을 step 간격 작은 삼각형으로 덮은 상자. drop 번째 윗면 삼각형을 빼면 칸보다 작은 구멍이 난다."""
    v, f = _box((0, 0, 0), (size, size, size), open_top=True)
    n = int(size / step)
    grid = np.array([[i * step, j * step, size] for i in range(n + 1) for j in range(n + 1)])
    top = []
    for i in range(n):
        for j in range(n):
            a, b, c, d = i * (n + 1) + j, (i + 1) * (n + 1) + j, (i + 1) * (n + 1) + j + 1, i * (n + 1) + j + 1
            top += [[a, b, c], [a, c, d]]
    top_f = np.array(top, dtype=np.int64) + len(v)
    if drop is not None:
        top_f = np.delete(top_f, drop, axis=0)
    return np.concatenate([v, grid]), np.concatenate([f, top_f])


def test_a_small_hole_is_closed_and_the_box_keeps_its_shape() -> None:
    pos, faces = _box_with_fine_top(drop=37)  # 2mm 삼각형 하나만큼 뚫림(칸 2.5mm 보다 작다)
    assert check_printable(Mesh(pos, faces))["boundary_edges"] > 0  # 정말 구멍 난 입력인지
    r = remesh(pos, faces, pitch=2.5, smooth_rounds=0)
    _closed_ok(r.positions, r.faces)
    assert not r.leaked and r.shell_thickened == 0
    vol = _volume(r.positions, r.faces)
    assert 8000 * 0.9 < vol < 8000 * 1.6, vol  # 껍질 칸까지 안이라 부푼다(칸이 굵을수록 더)


def test_half_the_lid_missing_still_comes_out_closed() -> None:
    """큰 구멍(윗면 절반) — 두껍게 해도 새면 「샘」을 말하되, 겉은 닫혀야 한다(11-14: 여기서 테두리 버그를 잡았다)."""
    pos, faces = _box((0, 0, 0), (20, 20, 20))
    faces = faces[:-1]
    r = remesh(pos, faces, pitch=0.5, smooth_rounds=0)
    _closed_ok(r.positions, r.faces)
    # 11-15: 구멍 난 닫힌 모양은 세 방향 투표로 속을 채운다(예전: 껍질을 불리거나 「샜다」)
    assert r.leaked or r.shell_thickened > 0 or any("세 방향 투표" in n for n in r.notes)


def test_a_clean_box_is_not_changed_much() -> None:
    pos, faces = _box((0, 0, 0), (30, 20, 10))
    r = remesh(pos, faces, pitch=0.5)
    _closed_ok(r.positions, r.faces)
    span = np.ptp(r.positions, axis=0)
    assert np.allclose(span, [30, 20, 10], atol=1.2), span
    assert 6000 * 0.9 < _volume(r.positions, r.faces) < 6000 * 1.2


def test_an_open_cup_is_reported_not_faked() -> None:
    """뚜껑 없는 컵(입구가 칸보다 훨씬 크다) — 닫힌 결과는 나오되 「속이 샜다」를 숨기지 않는다."""
    pos, faces = _box((0, 0, 0), (20, 20, 20), open_top=True)
    r = remesh(pos, faces, pitch=0.5, smooth_rounds=0)
    _closed_ok(r.positions, r.faces)
    assert r.leaked or r.shell_thickened > 0
    if r.leaked:
        assert any("구멍이 커서" in n for n in r.notes)
    # 11-15: 세 방향 투표가 컵 속을 꽉 채우면 안 된다(진짜 입구 · 돛 같은 모양) — 믿을 만한 칸 0%
    assert not any("세 방향 투표" in n for n in r.notes)


def test_outward_normals_give_positive_volume() -> None:
    pos, faces = _box((0, 0, 0), (10, 10, 10))
    r = remesh(pos, faces, pitch=0.5)
    assert _volume(r.positions, r.faces) > 0  # 면이 바깥을 본다(뒤집혔으면 음수)


def test_empty_input_is_empty_not_a_crash() -> None:
    r = remesh(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    assert len(r.faces) == 0 and r.notes


def test_a_huge_grid_widens_the_cell_and_says_so() -> None:
    pos, faces = _box((0, 0, 0), (2000, 2000, 2000))
    r = remesh(pos, faces, pitch=0.2, smooth_rounds=0)
    assert r.pitch > 0.2 and any("칸을" in n for n in r.notes)
    assert int(np.prod(r.grid)) <= 16_000_000


# ── 재서 고르기 ────────────────────────────────────────────────────────
def test_an_overhang_turns_support_on_and_says_why() -> None:
    """T 자: 가는 기둥 위 넓은 판 — 판 아랫면이 공중에 뜬다."""
    pos, faces = _merge(_box((8, 8, 0), (12, 12, 20)), _box((0, 0, 20), (20, 20, 24)))
    plan = plan_print(pos, faces, 24)
    assert plan.support and plan.overrides()["enable_support"] == "1"
    assert "받침 필요" in plan.decisions[0]["why"]


def test_a_flat_box_needs_no_support_and_no_brim() -> None:
    pos, faces = _box((0, 0, 0), (60, 60, 20))
    plan = plan_print(pos, faces, 60)
    assert not plan.support and not plan.brim
    assert plan.overrides() == {"enable_support": "0", "brim_type": "no_brim", "seam_position": "back"}  # 11-20 솔기는 판 뒤로


def test_a_tall_thin_pillar_gets_a_brim() -> None:
    pos, faces = _box((0, 0, 0), (8, 8, 80))
    plan = plan_print(pos, faces, 80)
    assert plan.brim and plan.overrides()["brim_type"] == "outer_only"


def test_small_objects_get_fine_layers() -> None:
    pos, faces = _box((0, 0, 0), (30, 30, 30))
    assert plan_print(pos, faces, 30).layer_height <= 0.12


# ── 썰기(가짜 뱀부) ────────────────────────────────────────────────────
def _profiles(root: Path, printer: str = "Bambu Lab X2D", bed: str = "256", nozzles: int = 1) -> Path:
    base = root / "BBL"
    short = printer.replace("Bambu Lab ", "")
    for kind in ("machine", "process", "filament"):
        (base / kind).mkdir(parents=True, exist_ok=True)
    (base / "machine" / "m_base.json").write_text(json.dumps({"name": "fdm_machine_common", "printable_height": "250"}), encoding="utf-8")
    (base / "machine" / "m.json").write_text(json.dumps({
        "name": f"{printer} 0.4 nozzle", "inherits": "fdm_machine_common",
        "printable_area": ["0x0", f"{bed}x0", f"{bed}x{bed}", f"0x{bed}"],
        "nozzle_diameter": ["0.4"] * nozzles}), encoding="utf-8")
    (base / "process" / "p.json").write_text(json.dumps({"name": f"0.20mm Standard @BBL {short}", "layer_height": "0.2",
                                                         "enable_support": "0"}), encoding="utf-8")
    (base / "filament" / "f_base.json").write_text(json.dumps({"name": "Bambu PLA Basic @base", "filament_density": ["1.26"]}), encoding="utf-8")
    (base / "filament" / "f.json").write_text(json.dumps({"name": f"Bambu PLA Basic @BBL {short} 0.4 nozzle",
                                                          "inherits": "Bambu PLA Basic @base"}), encoding="utf-8")
    return base


class _FakeBambu:
    def __init__(self, rc: int = 0, gcode: bool = True, max_z: float = 20.0, project: bool = True,
                 recheck_ok: bool = True, hangs: int = 0) -> None:
        self.rc, self.gcode, self.max_z, self.project, self.recheck_ok = rc, gcode, max_z, project, recheck_ok
        self.hangs = hangs  # 첫 썰기를 몇 번 멈추게 할지(뱀부가 가끔 끝없이 멈춤 · 11-14)
        self.cmds: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.cmds.append(cmd)
        out = Path(cmd[cmd.index("--outputdir") + 1])
        if self.hangs and "--load-settings" in cmd and "--slice" in cmd:
            self.hangs -= 1
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout") or 0)
        if cmd[-1].endswith("_bambu.3mf") and "--slice" in cmd and not self.recheck_ok:  # 다시 썰어 보기 실패 흉내
            return subprocess.CompletedProcess(cmd, 127, b"", b"")
        if "--export-3mf" in cmd:  # 프로젝트 내보내기(썰기와 따로 부름)
            if self.project:
                (out / cmd[cmd.index("--export-3mf") + 1]).write_bytes(b"PK")
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        if self.gcode:
            (out / "plate_1.gcode").write_text(
                "; HEADER_BLOCK_START\n; model printing time: 1h 2m 3s; total estimated time: 1h 2m 9s\n"
                f"; total layer number: 100\n; total filament length [mm] : 10000.00\n; max_z_height: {self.max_z:.2f}\n",
                encoding="utf-8")
            (out / "result.json").write_text(json.dumps({"error_string": "Success.", "sliced_plates": [
                {"total_predication": 3729.0, "warning_message": ""}]}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.rc, b"", b"")


def _slice(tmp_path: Path, fake: _FakeBambu, **kw: Any) -> dict[str, Any]:
    root = _profiles(tmp_path / "res", kw.pop("profile_printer", "Bambu Lab X2D"), kw.pop("bed", "256"), kw.pop("nozzles", 1))
    exe = tmp_path / "bambu-studio.exe"
    exe.write_bytes(b"")
    model = tmp_path / "m.3mf"
    model.write_bytes(b"x")
    kw.setdefault("mesh_dims", (50.0, 50.0, 20.0))
    kw.setdefault("mesh_height", 20.0)
    original = slicer.profiles_root
    slicer.profiles_root = lambda _exe: root  # type: ignore[assignment]
    try:
        return slicer.slice_3mf(model, tmp_path / "out", exe=exe, run=fake, **kw)
    finally:
        slicer.profiles_root = original  # type: ignore[assignment]


def test_a_model_bigger_than_the_bed_is_refused_before_slicing(tmp_path: Path) -> None:
    fake = _FakeBambu()
    res = _slice(tmp_path, fake, mesh_dims=(300.0, 40.0, 20.0))
    assert not res["ok"] and res["error"].startswith("too_big") and not fake.cmds  # 뱀부를 부르지도 않는다


def test_a_model_too_tall_is_refused(tmp_path: Path) -> None:
    fake = _FakeBambu()
    res = _slice(tmp_path, fake, mesh_dims=(50.0, 50.0, 251.0))  # 상속받은 높이 250
    assert not res["ok"] and "too_big" in res["error"] and not fake.cmds


def test_the_margin_is_kept_at_the_bed_edge(tmp_path: Path) -> None:
    fake = _FakeBambu()
    res = _slice(tmp_path, fake, mesh_dims=(250.0, 40.0, 20.0))  # 256 - 2×5 = 246 넘음
    assert not res["ok"] and not fake.cmds


def test_an_unsupported_printer_is_refused(tmp_path: Path) -> None:
    fake = _FakeBambu()
    res = _slice(tmp_path, fake, printer="Bambu Lab A1")
    assert not res["ok"] and "unsupported_printer" in res["error"] and not fake.cmds


def test_rc_139_with_gcode_is_success(tmp_path: Path) -> None:
    res = _slice(tmp_path, _FakeBambu(rc=139))
    assert res["ok"] and res["layers"] == 100 and res["estimated_sec"] == 3729.0


def test_rc_0_without_gcode_is_failure(tmp_path: Path) -> None:
    res = _slice(tmp_path, _FakeBambu(rc=0, gcode=False))
    assert not res["ok"] and "slice_failed" in res["error"]


def test_a_height_mismatch_is_flagged(tmp_path: Path) -> None:
    res = _slice(tmp_path, _FakeBambu(max_z=12.0), mesh_height=20.0)
    assert res["ok"] and any("안 썰렸을 수" in n for n in res["notes"])


def test_inherited_density_reaches_the_weight(tmp_path: Path) -> None:
    res = _slice(tmp_path, _FakeBambu())
    area = np.pi * (1.75 / 2) ** 2
    # 길이 10,000mm 로 재야 갈린다 — 1.26(상속된 밀도)이면 30.3g, 기본값 1.24 면 29.8g(1,000mm 로는 둘 다 3.0g 이라 못 잡았다)
    assert res["filament_g"] == round(10000 * area / 1000 * 1.26, 1) == 30.3


def test_chosen_settings_are_written_into_the_process_file_not_the_command_line(tmp_path: Path) -> None:
    fake = _FakeBambu()
    res = _slice(tmp_path, fake, overrides={"enable_support": "1", "support_type": "tree(auto)", "brim_type": "no_brim"})
    assert res["ok"]
    cmd = fake.cmds[0]
    assert not any(c.startswith("--enable_support") or c.startswith("--support_type") for c in cmd)  # 11-14: 명령줄 덮어쓰기는 실패했다
    proc = json.loads((tmp_path / "out" / "_slice_process.json").read_text(encoding="utf-8"))
    assert proc["enable_support"] == "1" and proc["support_type"] == "tree(auto)"


def test_other_printers_are_marked_as_not_measured(tmp_path: Path) -> None:
    res = _slice(tmp_path, _FakeBambu(), printer="Bambu Lab P2S", profile_printer="Bambu Lab P2S")
    assert res["ok"] and any("설정만" in n for n in res["notes"])


def test_nothing_here_sends_a_job_to_the_printer() -> None:
    """출력 단추는 사람이 누른다 — 프린트 갈래 코드에 프린터로 보내는 길(뱀부 네트워크 · MQTT · FTP · 클라우드 업로드)이 없다."""
    text = "".join((SRC / name).read_text(encoding="utf-8") for name in ("slicer.py", "printing.py", "print_plan.py", "remesh.py"))
    for word in ("mqtt", "ftp", "--send", "upload", "start_print", "print_now", "bambu_network", "8883", "990"):
        assert not re.search(re.escape(word), text, re.IGNORECASE), word


def test_slicing_and_project_export_are_separate_calls(tmp_path: Path) -> None:
    """11-14: 썰기와 --export-3mf 를 한 번에 시키면 뱀부가 rc 139 로 죽었다 → 두 번 따로 부른다."""
    fake = _FakeBambu()
    res = _slice(tmp_path, fake)
    assert res["ok"] and res["project_3mf"] and res["project_3mf"].endswith("_bambu.3mf")
    assert len(fake.cmds) == 3
    assert "--slice" in fake.cmds[0] and "--export-3mf" not in fake.cmds[0]
    assert "--export-3mf" in fake.cmds[1] and "--slice" not in fake.cmds[1]
    # 세 번째: 넘길 프로젝트 파일을 설정 없이 그대로 다시 썰어 본다
    assert "--slice" in fake.cmds[2] and fake.cmds[2][-1].endswith("_bambu.3mf") and "--load-settings" not in fake.cmds[2]


def test_a_missing_project_file_is_said_not_hidden(tmp_path: Path) -> None:
    res = _slice(tmp_path, _FakeBambu(project=False))
    assert res["ok"] and res["project_3mf"] is None
    assert any("프로젝트 3MF 를 못 만들었다" in n for n in res["notes"])



def test_a_project_file_that_does_not_slice_is_said(tmp_path: Path) -> None:
    """11-14: 넘긴 프로젝트 파일이 명령줄 다시 썰기에서 실패(화면에선 성공) — 숨기지 말고 「화면에서 확인」을 말한다."""
    res = _slice(tmp_path, _FakeBambu(recheck_ok=False))
    assert res["ok"] and any("다시 썰어 보니 실패" in n for n in res["notes"])
    ok = _slice(tmp_path / "b", _FakeBambu())
    assert not any("실패" in n for n in ok["notes"])


def test_two_nozzle_printers_skip_the_cli_recheck_and_say_why(tmp_path: Path) -> None:
    """11-14 실측: 노즐 둘 4기종은 내보낸 프로젝트를 명령줄로 다시 썰면 4/4 실패 · 노즐 하나 7기종은 7/7 성공.
    노즐 둘은 헛 「실패」를 내지 않고 「명령줄로 못 확인 · 화면에서 한 번」을 말한다."""
    fake = _FakeBambu(recheck_ok=False)
    res = _slice(tmp_path, fake, nozzles=2)
    assert res["ok"] and len(fake.cmds) == 2  # 썰기 · 내보내기만 — 다시 썰기는 안 부른다
    assert any("노즐 둘 기종" in n for n in res["notes"])
    assert not any("실패" in n for n in res["notes"])


def test_a_hung_slice_is_cut_and_tried_once_more(tmp_path: Path) -> None:
    """11-14: X2D 가 약 스무 번에 두 번 끝없이 멈췄다 — 끊고 한 번 더 썰면 10초에 끝났다."""
    fake = _FakeBambu(hangs=1)
    res = _slice(tmp_path, fake)
    assert res["ok"] and any("다시 썰었다" in n for n in res["notes"])
    twice = _slice(tmp_path / "b", _FakeBambu(hangs=2))
    assert twice["ok"] is False and "두 번 다" in twice["error"]


def test_the_bed_type_goes_into_the_process_file(tmp_path: Path) -> None:
    res = _slice(tmp_path, _FakeBambu(), overrides={"curr_bed_type": "Textured PEI Plate"})
    assert res["ok"]
    proc = json.loads((tmp_path / "out" / "_slice_process.json").read_text(encoding="utf-8"))
    assert proc["curr_bed_type"] == "Textured PEI Plate"


def test_printer_prefs_default_to_the_bambu_default_plate(monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis.gen3d.printing import printer_prefs

    for k in ("JARVIS_GEN3D_PRINTER", "JARVIS_GEN3D_BED", "JARVIS_GEN3D_FILAMENT", "JARVIS_GEN3D_FLOOR_CUT"):
        monkeypatch.delenv(k, raising=False)
    p = printer_prefs()
    assert p == {"printer": "Bambu Lab X2D", "bed": "Textured PEI Plate", "filament": "Bambu PLA Basic", "floor_cut_mm": 0.0,
                 "thicken_to_mm": 1.6, "snap": True}
    monkeypatch.setenv("JARVIS_GEN3D_FLOOR_CUT", "말도 안 되는 값")
    assert printer_prefs()["floor_cut_mm"] == 0.0  # 이상한 값은 자르지 않음


# ── 얇은 곳 · 바닥 자르기 · 방향 ──────────────────────────────────────────
def test_a_thin_rod_is_found_and_a_thick_block_is_not() -> None:
    """두꺼운 받침(20mm) 위 가는 기둥(0.6mm) — 기둥만 「얇은 곳」으로 잡힌다(11-14 밧줄 · 돛대)."""
    rod = _box((9.7, 9.7, 5), (10.3, 10.3, 25))
    base = _box((0, 0, 0), (20, 20, 5))
    pos, faces = _merge(base, rod)
    r = remesh(pos, faces, pitch=0.2, smooth_rounds=0, min_thickness_mm=1.2)
    assert r.thin_share > 0 and r.thin_bbox_mm is not None
    (x0, y0, z0), (x1, y1, z1) = r.thin_bbox_mm
    assert z0 >= 4.0 and 9.0 <= x0 and x1 <= 11.0 and 9.0 <= y0 and y1 <= 11.0  # 얇은 곳은 기둥 자리에만
    for w in (1.6, 3.0):  # 최소 굵기(1.2)보다 굵은 기둥 · 두꺼운 받침은 하나도 안 잡힌다(모서리 포함)
        c = 10 - w / 2
        ok = remesh(*_merge(base, _box((c, c, 5), (c + w, c + w, 25))), pitch=0.2, smooth_rounds=0, min_thickness_mm=1.2)
        assert ok.thin_share == 0 and ok.thin_bbox_mm is None, w


def _rod_on_base(w: float) -> tuple[np.ndarray, np.ndarray]:
    c = 10 - w / 2
    return _merge(_box((0, 0, 0), (20, 20, 5)), _box((c, c, 5), (c + w, c + w, 25)))


def _xy_width_at(pos: np.ndarray, z: float) -> float:
    sel = np.abs(pos[:, 2] - z) < 0.3
    return float(np.ptp(pos[sel, 0]))


def test_a_thin_rod_is_thickened_and_the_base_is_not_touched() -> None:
    """11-14 첫 실물: 1mm 안팎 밧줄이 털 · 구슬로 망가졌다 → 가는 곳만 목표 굵기까지 불린다."""
    pos, faces = _rod_on_base(0.6)
    plain = remesh(pos, faces, pitch=0.2, smooth_rounds=0, min_thickness_mm=1.2)
    r = remesh(pos, faces, pitch=0.2, smooth_rounds=0, min_thickness_mm=1.2, thicken_to_mm=1.6)
    _closed_ok(r.positions, r.faces)
    assert r.thin_share_before > 0 and r.thin_share == 0  # 굵힌 뒤엔 1.2mm 보다 가는 곳이 없다
    assert r.thickened_cells > 0 and r.thicken_rounds >= 1 and r.thicken_to_mm == 1.6
    assert _xy_width_at(r.positions, 15.0) >= 1.6 > _xy_width_at(plain.positions, 15.0)  # 기둥 가운데가 실제로 굵어짐
    # 받침(20×20×5)은 그대로: 바닥 높이 · 옆 폭이 같다
    assert float(r.positions[:, 2].min()) == pytest.approx(float(plain.positions[:, 2].min()))
    assert float(np.ptp(r.positions[:, 0])) == pytest.approx(float(np.ptp(plain.positions[:, 0])))
    # 더한 부피는 기둥 둘레만큼(기둥 높이 20mm × 굵기 2mm 안팎) — 몸통을 부풀렸다면 수백 mm³
    added = _volume(r.positions, r.faces) - _volume(plain.positions, plain.faces)
    assert 0 < added < 20 * 2.4 * 2.4


def test_thick_parts_are_left_alone_and_thickening_can_be_turned_off() -> None:
    """반례: 굵은 기둥(3mm) · 상자는 하나도 안 바뀐다 · 끄면(0) 예전 그대로 경고만."""
    for w in (3.0,):
        r = remesh(*_rod_on_base(w), pitch=0.2, smooth_rounds=0, thicken_to_mm=1.6)
        assert r.thickened_cells == 0 and r.thicken_to_mm == 0.0
    off = remesh(*_rod_on_base(0.6), pitch=0.2, smooth_rounds=0, thicken_to_mm=0.0)
    assert off.thickened_cells == 0 and off.thin_share > 0 and off.thin_share == off.thin_share_before


def test_thin_plates_and_short_stubs_are_not_thickened() -> None:
    """반례(11-14 배 실물): 얇은 판(1mm 벽 20×20mm) · 짧은 돌기(0.6mm × 5mm)는 잘 출력됐다 — 굵히지도, 경고하지도 않는다.
    길고 가는 막대(0.6mm × 20mm)만 굵힌다."""
    base = _box((0, 0, 0), (30, 30, 5))
    wall = _merge(base, _box((5, 14.5, 5), (25, 15.5, 25)))
    r = remesh(*wall, pitch=0.2, smooth_rounds=0, thicken_to_mm=1.6)
    assert r.thickened_cells == 0 and r.thin_share == 0 and r.thin_wall_share > 0  # 얇은 건 알지만 막대는 아님
    stub = _merge(base, _box((14.7, 14.7, 5), (15.3, 15.3, 10)))
    r = remesh(*stub, pitch=0.2, smooth_rounds=0, thicken_to_mm=1.6)
    assert r.thickened_cells == 0 and r.thin_share == 0


def test_thickening_does_not_grow_below_the_floor() -> None:
    """판에 닿는 바닥에 서 있는 가는 기둥 — 바닥 아래로 불리면 판 높이가 바뀐다."""
    r = remesh(*_box((9.7, 9.7, 0), (10.3, 10.3, 20)), pitch=0.2, smooth_rounds=0, thicken_to_mm=1.6)
    plain = remesh(*_box((9.7, 9.7, 0), (10.3, 10.3, 20)), pitch=0.2, smooth_rounds=0)
    _closed_ok(r.positions, r.faces)
    assert r.thickened_cells > 0
    assert float(r.positions[:, 2].min()) == pytest.approx(float(plain.positions[:, 2].min()))


def test_the_print_receipt_says_what_was_thickened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis.gen3d.printing import prepare_print

    monkeypatch.setenv("JARVIS_GEN3D_SLICE", "0")
    monkeypatch.delenv("JARVIS_GEN3D_THICKEN", raising=False)
    pos, faces = _rod_on_base(0.6)
    out = prepare_print(Mesh(pos, faces), tmp_path, "rod", ["stl"], 25.0, pitch=0.2)
    rm = out["report"]["remesh"]
    assert rm["thickened_cells"] > 0 and rm["thin_share"] == 0 and rm["thin_share_before"] > 0
    assert any("가는 막대를 굵게 했다" in n for n in out["printable"]["notes"])
    assert not any(n.startswith("얇은 곳:") for n in out["printable"]["notes"])
    monkeypatch.setenv("JARVIS_GEN3D_THICKEN", "0")  # 끄면 예전처럼 경고만
    out2 = prepare_print(Mesh(pos, faces), tmp_path, "rod2", ["stl"], 25.0, pitch=0.2)
    assert out2["report"]["remesh"]["thickened_cells"] == 0
    assert any(n.startswith("얇은 곳:") for n in out2["printable"]["notes"])


def test_a_big_hole_is_filled_by_three_way_vote_not_left_hollow() -> None:
    """11-15 리락쿠마: 트렐리스 결과의 큰 구멍으로 바깥 물 채우기가 속까지 새 속 빈 껍질(8분)이 됐다.
    뚜껑 반쪽이 없는 상자 — 세 방향 투표로 속이 차고 모양은 부풀지 않으며, 투표 부스러기 덩이가 남지 않는다."""
    v, f = _box((0, 0, 0), (20, 20, 20))
    r = remesh(v, f[:-1], pitch=0.5, smooth_rounds=0)  # 뚜껑 반쪽(삼각형 하나)이 없는 상자
    assert not r.leaked and r.shell_thickened == 0
    assert any("세 방향 투표" in n for n in r.notes)
    assert r.solid_cells > 0.8 * (20 ** 3) / 0.5 ** 3  # 속이 찼다
    c = check_printable(Mesh(r.positions, r.faces))
    assert c["watertight"] and c["parts"] == 1
    assert float(np.ptp(r.positions[:, 0])) < 21.5  # 껍질을 불려 부풀린 게 아니다


def test_parity_vote_drops_specks() -> None:
    from alture_jarvis.gen3d.remesh import drop_specks

    m = np.zeros((40, 40, 40), dtype=bool)
    m[5:30, 5:30, 5:30] = True
    m[35, 35, 35] = True  # 부스러기
    m[2:4, 33:38, 2:4] = True  # 작은 덩이(20칸 · 1% 미만)
    out = drop_specks(m)
    assert out[5:30, 5:30, 5:30].all() and not out[35, 35, 35] and not out[2:4, 33:38, 2:4].any()


def test_big_flat_triangles_are_filled_not_hollow() -> None:
    """11-14 적대적 시험에서 찾음: 삼각형 하나에 찍는 점을 64칸으로 잘라 20mm 면에 틈이 나고 속이 비었다(새는 검사도 못 잡음)."""
    r = remesh(*_box((0, 0, 0), (20, 20, 20)), pitch=0.2, smooth_rounds=0)
    assert r.shell_thickened == 0 and not r.leaked
    assert r.solid_cells > 0.95 * (20 ** 3) / 0.2 ** 3  # 속이 꽉 찼다(빈 껍질이면 6% 남짓)


def test_floor_cut_makes_a_flat_closed_bottom() -> None:
    v, f = _box((0, 0, 0), (20, 20, 20))
    r = remesh(v, f, pitch=0.5, smooth_rounds=0, floor_cut_mm=1.0)
    _closed_ok(r.positions, r.faces)
    assert r.floor_cut_mm == 1.0
    assert float(r.positions[:, 2].min()) >= 0.5  # 아래 1mm 가 잘려 바닥이 올라간다


def test_orientation_is_suggested_not_applied() -> None:
    """T 자를 거꾸로 놓으면 받침이 거의 필요 없다 — 제안만 하고, 고른 설정은 지금 방향 그대로."""
    pos, faces = _merge(_box((8, 8, 0), (12, 12, 20)), _box((0, 0, 20), (20, 20, 24)))
    plan = plan_print(pos, faces, 24)
    options = {o["orientation"]: o["overhang_area_mm2"] for o in plan.measured["orientations"]}
    assert options["거꾸로"] < options["지금 그대로"]
    sugg = [d for d in plan.decisions if d["what"] == "orientation"]
    assert sugg and "제안만" in sugg[0]["value"]
    assert plan.support  # 지금 방향 기준 서포트는 그대로 켜짐


# ── 설정 고르기: 이름 짐작이 아니라 「맞는 기계 목록」 (11-14 실측: 지원 11기종 중 6기종이 설정을 못 찾아 못 썰었다) ──
def _real_like_profiles(root: Path) -> Path:
    """뱀부 2.8 의 실제 짜임을 줄인 것 — P1S · X1E 는 「@BBL X1C」 설정을 쓰고, P1P 에는 PLA Basic 이 없다."""
    base = root / "BBL"
    for kind in ("machine", "process", "filament"):
        (base / kind).mkdir(parents=True, exist_ok=True)
    for i, pr in enumerate(("P1P", "P1S", "X1 Carbon", "X1E", "H2D Pro", "X2D")):
        (base / "machine" / f"m{i}.json").write_text(json.dumps({"name": f"Bambu Lab {pr} 0.4 nozzle"}), encoding="utf-8")

    def put(kind: str, name: str, fits: list[str]) -> None:
        (base / kind / f"{name}.json").write_text(json.dumps({
            "name": name, "compatible_printers": [f"Bambu Lab {f} 0.4 nozzle" for f in fits]}), encoding="utf-8")

    put("process", "0.20mm Standard @BBL X1C", ["X1 Carbon", "P1S", "X1E"])
    put("process", "0.20mm Standard @BBL P1P", ["P1P"])
    put("process", "0.20mm Standard @BBL H2DP", ["H2D Pro"])
    put("process", "0.20mm Standard @BBL X2D", ["X2D"])
    # 이름은 짐작과 같지만 목록에 그 기계가 없다 — 이름만 보고 고르면 틀린 설정이 들어간다.
    put("process", "0.20mm Standard @BBL X1E", ["H2D Pro"])
    put("filament", "Bambu PLA Basic @BBL X1C", ["X1 Carbon", "X1E"])
    put("filament", "Bambu PLA Basic @BBL P1S 0.4 nozzle", ["P1S"])
    put("filament", "Bambu PLA Basic @BBL H2DP", ["H2D Pro"])
    put("filament", "Bambu PLA Basic @BBL X2D 0.4 nozzle", ["X2D"])
    put("filament", "Generic PLA High Speed @BBL P1P", ["P1P"])
    put("filament", "Bambu PETG HF @BBL X1C", ["X1 Carbon"])
    return base


@pytest.mark.parametrize("printer,process,filament", [
    ("Bambu Lab P1S", "0.20mm Standard @BBL X1C", "Bambu PLA Basic @BBL P1S 0.4 nozzle"),
    ("Bambu Lab X1 Carbon", "0.20mm Standard @BBL X1C", "Bambu PLA Basic @BBL X1C"),
    ("Bambu Lab X1E", "0.20mm Standard @BBL X1C", "Bambu PLA Basic @BBL X1C"),
    ("Bambu Lab H2D Pro", "0.20mm Standard @BBL H2DP", "Bambu PLA Basic @BBL H2DP"),
    ("Bambu Lab X2D", "0.20mm Standard @BBL X2D", "Bambu PLA Basic @BBL X2D 0.4 nozzle"),
    ("Bambu Lab P1P", "0.20mm Standard @BBL P1P", "Generic PLA High Speed @BBL P1P"),
])
def test_presets_are_picked_by_the_compatible_printer_list(tmp_path: Path, printer: str, process: str, filament: str) -> None:
    from alture_jarvis.gen3d.slicer import write_presets
    paths = write_presets(_real_like_profiles(tmp_path), tmp_path, printer, 0.4, "0.20mm Standard", "Bambu PLA Basic")
    assert json.loads(paths["process"].read_text(encoding="utf-8"))["name"] == process
    assert json.loads(paths["filament"].read_text(encoding="utf-8"))["name"] == filament


def test_a_non_pla_filament_is_not_silently_swapped(tmp_path: Path) -> None:
    from alture_jarvis.gen3d.slicer import write_presets
    with pytest.raises(FileNotFoundError):  # PETG 를 고르면 PLA 로 몰래 바꾸지 않는다
        write_presets(_real_like_profiles(tmp_path), tmp_path, "Bambu Lab P1P", 0.4, "0.20mm Standard", "Bambu PETG HF")


def test_a_swapped_filament_is_written_on_the_receipt(tmp_path: Path) -> None:
    root = _real_like_profiles(tmp_path / "res")
    (root / "machine" / "m5.json").write_text(json.dumps({  # 썰기는 판 크기를 읽는다
        "name": "Bambu Lab P1P 0.4 nozzle", "printable_area": ["0x0", "256x0", "256x256", "0x256"]}), encoding="utf-8")
    model = tmp_path / "m.3mf"
    model.write_bytes(b"PK")
    fake = _FakeBambu(max_z=20.0)
    original = slicer.profiles_root
    slicer.profiles_root = lambda _exe: root  # type: ignore[assignment]
    try:
        out = slicer.slice_3mf(model, tmp_path / "out", printer="Bambu Lab P1P", exe=tmp_path / "bambu.exe", run=fake)
    finally:
        slicer.profiles_root = original  # type: ignore[assignment]
    assert out["ok"] is True
    assert any("Generic PLA High Speed @BBL P1P" in n for n in out["notes"])
