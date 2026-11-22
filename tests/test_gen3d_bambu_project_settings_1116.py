"""넘길 뱀부 프로젝트 3MF 의 「시스템과 다른 설정」 목록 (2026-11-16).

뱀부 화면은 3MF 를 열 때 `different_settings_to_system` 에 없는 공정 칸을 시스템 값으로 되돌린다(BambuStudio
`Preset.cpp` `load_external_preset`). 명령줄이 내보낸 파일은 목록이 비어 있어 서포트가 꺼진 채 열렸다(대표 11-16 저녁).
시험 자료는 상자 도형만."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from alture_jarvis.gen3d import slicer
from alture_jarvis.gen3d.printing import write_3mf_multi

CFG = "Metadata/project_settings.config"


def _fake_project(path: Path, diff) -> None:
    cfg = {"print_settings_id": "0.20mm Standard @BBL X2D", "enable_support": "1", "support_type": "tree(auto)"}
    if diff is not None:
        cfg["different_settings_to_system"] = diff
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("3D/3dmodel.model", "<model/>")
        z.writestr(CFG, json.dumps(cfg))
        z.writestr("Metadata/plate_1.png", b"\x89PNG fake")


def _cfg(path: Path) -> dict:
    return json.loads(zipfile.ZipFile(path).read(CFG))


def test_overridden_process_keys_are_listed_so_the_gui_keeps_them(tmp_path):
    p = tmp_path / "p.3mf"
    _fake_project(p, ["", "", ""])
    before = {i.filename: zipfile.ZipFile(p).read(i.filename) for i in zipfile.ZipFile(p).infolist()}
    assert slicer.mark_changed_settings(p, {"enable_support": "1", "support_type": "tree(auto)", "brim_type": "no_brim"})
    cfg = _cfg(p)
    assert cfg["different_settings_to_system"] == ["brim_type;enable_support;support_type", "", ""]
    assert cfg["enable_support"] == "1"  # 값은 그대로
    z = zipfile.ZipFile(p)
    assert [i.filename for i in z.infolist()] == list(before)  # 순서 그대로([Content_Types] 맨 앞)
    for name, data in before.items():
        if name != CFG:
            assert z.read(name) == data


def test_existing_list_is_kept_and_merged(tmp_path):
    p = tmp_path / "p.3mf"
    _fake_project(p, ["seam_position", "filament_x", "printer_y"])
    assert slicer.mark_changed_settings(p, {"enable_support": "1"})
    assert _cfg(p)["different_settings_to_system"] == ["enable_support;seam_position", "filament_x", "printer_y"]


def test_missing_list_or_broken_file_does_not_crash(tmp_path):
    p = tmp_path / "p.3mf"
    _fake_project(p, None)
    assert slicer.mark_changed_settings(p, {"enable_support": "1"})
    assert _cfg(p)["different_settings_to_system"][0] == "enable_support"
    bad = tmp_path / "bad.3mf"
    bad.write_bytes(b"not a zip")
    assert slicer.mark_changed_settings(bad, {"enable_support": "1"}) is False


def _box(lo, hi):
    lo, hi = np.array(lo, float), np.array(hi, float)
    v = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    f = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
                  [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    return v, f


@pytest.mark.skipif(slicer.find_bambu() is None, reason="뱀부 스튜디오 없음")
def test_real_bambu_project_lists_support_and_still_reslices(tmp_path):
    a, fa = _box([-4, -4, 0], [4, 4, 10])
    b, fb = _box([-15, -4, 10], [15, 4, 13])  # 처마 — 서포트가 필요
    write_3mf_multi(tmp_path / "t.3mf", [("t", np.vstack([a, b]), np.vstack([fa, fb + 8]))])
    s = slicer.slice_3mf(tmp_path / "t.3mf", tmp_path / "s", printer="Bambu Lab P1S",
                         overrides={"enable_support": "1", "support_type": "normal(auto)", "brim_type": "no_brim"})
    assert s["ok"] and s["project_3mf"], s
    proj = Path(s["project_3mf"])
    listed = _cfg(proj)["different_settings_to_system"][0].split(";")
    assert {"enable_support", "support_type", "brim_type"} <= set(listed)
    # 고친 파일이 깨지지 않았나: 노즐 하나 기종은 명령줄로 다시 썰린다 · 서포트 그대로
    out = tmp_path / "re"
    out.mkdir()
    # 11-17: 뱀부 명령줄은 동시에 돌면 가끔 다 쓰고도 종료에서 멈춘다 — 종료가 아니라 결과표로 끝을 가르는 실행기로 부른다
    slicer.run_bambu([str(slicer.find_bambu()), "--slice", "0", "--outputdir", str(out), str(proj)], timeout=120)
    g = out / "plate_1.gcode"
    assert g.is_file()
    assert "; FEATURE: Support" in g.read_text(encoding="utf-8", errors="replace")
