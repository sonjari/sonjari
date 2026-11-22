"""3D 프린트 갈래 — 닫힌 메시 검사 · STL · 3MF 내보내기 (2026-11-14 · 설계 §3-6 · 실험기록 「3D 프린트 갈래」).

검사는 손자리 코드가 잰 것만 말한다(모델 말은 숫자에 안 넣는다):
- GLB 는 UV 이음매마다 꼭짓점을 쪼개 둔다 → 같은 자리 꼭짓점을 먼저 합친다(크기 대비 1e-6). 안 합치면 멀쩡한 메시도 구멍투성이로 나온다.
- 가장자리마다 붙은 면 수: 1 = 열린 가장자리(구멍) · 3 이상 = 비다양체. 둘 다 0 이어야 닫힌 메시(watertight).
- 같은 방향 가장자리가 두 번 = 면 방향 엇갈림(안팎이 뒤집힌 면).
- 떨어진 조각 수는 실패가 아니라 주의(notes) — 프린트하면 따로 떨어진다.

색 나누기(여러 색 프린트 · AMS)는 이번 판에 없다 — 설계 §3-6 「다음」. 지금 3MF 는 한 색.
"""
from __future__ import annotations

import struct
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from .glb import Mesh


def weld(mesh: Mesh) -> tuple[np.ndarray, np.ndarray]:
    """같은 자리 꼭짓점을 합치고, 꼭짓점이 겹친 납작한 삼각형을 뺀다 → (위치, 면)."""
    pos = mesh.positions
    if not len(pos):
        return pos, mesh.faces.reshape(0, 3)
    lo, hi = pos.min(axis=0), pos.max(axis=0)
    eps = max(float(np.linalg.norm(hi - lo)) * 1e-6, 1e-12)
    keys = np.round((pos - lo) / eps).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    faces = inverse.reshape(-1)[mesh.faces]
    ok = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    return pos[first], faces[ok]


def _components(n_vertices: int, faces: np.ndarray) -> int:
    parent = np.arange(n_vertices)

    def find(a: np.ndarray) -> np.ndarray:
        while True:
            up = parent[a]
            if np.array_equal(up, a):
                return a
            parent[a] = parent[up]
            a = parent[a]

    # 면의 세 꼭짓점을 같은 무리로 — 벡터로 여러 번 돌려 고정점까지(꼭짓점 십만 단위에서 수십 번이면 멈춘다).
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]]])
    for _ in range(200):
        ra, rb = find(edges[:, 0].copy()), find(edges[:, 1].copy())
        diff = ra != rb
        if not diff.any():
            break
        lo = np.minimum(ra[diff], rb[diff])
        hi = np.maximum(ra[diff], rb[diff])
        np.minimum.at(parent, hi, lo)
    used = np.unique(faces)
    return len(np.unique(find(used.copy())))


def check_printable(mesh: Mesh) -> dict[str, Any]:
    """닫힌 메시 검사. 돌려주는 것: 숫자(measured 에 섞어 쓴다)와 printable{ok, why, notes}."""
    pos, faces = weld(mesh)
    if not len(faces):
        return {"watertight": False, "boundary_edges": 0, "non_manifold_edges": 0, "flipped_edges": 0, "parts": 0,
                "printable": {"ok": False, "why": ["삼각형이 없다"], "notes": []}}
    directed = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    undirected = np.sort(directed, axis=1)
    _, edge_id, counts = np.unique(undirected, axis=0, return_inverse=True, return_counts=True)
    edge_id = edge_id.reshape(-1)
    boundary = int((counts == 1).sum())
    non_manifold = int((counts > 2).sum())
    # 엇갈림은 면 둘이 붙은 가장자리에서만 센다 — 넷이 붙은 비다양체 가장자리는 방향마다 둘씩이라 저절로 「겹침」으로 잡혀
    # 같은 고장을 두 번 센다(11-14 배 GLB: 비다양체 388 · 엇갈림 776 = 정확히 두 배였다).
    manifold = counts[edge_id] == 2
    _, dcounts = np.unique(directed[manifold], axis=0, return_counts=True)
    flipped = int((dcounts > 1).sum())
    parts = _components(len(pos), faces)
    watertight = boundary == 0 and non_manifold == 0
    why: list[str] = []
    if boundary:
        why.append(f"열린 가장자리 {boundary}개 — 구멍이 있어 안이 비지 않은 덩어리로 못 읽는다")
    if non_manifold:
        why.append(f"비다양체 가장자리 {non_manifold}개 — 한 가장자리에 면이 셋 이상 붙었다")
    if flipped:
        why.append(f"면 방향 엇갈림 {flipped}곳 — 안팎이 뒤집힌 면이 있다")
    notes: list[str] = []
    if parts > 1:
        notes.append(f"떨어진 조각 {parts}개 — 프린트하면 따로 떨어진다")
    volume = None
    if watertight:
        a, b, c = pos[faces[:, 0]], pos[faces[:, 1]], pos[faces[:, 2]]
        volume = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
        if volume < 0:
            notes.append("면이 안쪽을 향한다(부피가 음수) — 슬라이서가 대개 스스로 뒤집지만 확인 필요")
    return {
        "watertight": watertight, "boundary_edges": boundary, "non_manifold_edges": non_manifold,
        "flipped_edges": flipped, "parts": parts,
        "printable": {"ok": watertight and not flipped, "why": why, "notes": notes},
    }


def print_space(mesh: Mesh, size_mm: float) -> tuple[np.ndarray, np.ndarray]:
    """glTF(y 위 · 미터 단위 아님 — 생성기는 대략 1 크기)를 프린트 자리로: z 위 · 긴 변 = size_mm · 바닥 z=0 · 가운데."""
    pos, faces = weld(mesh)
    if not len(pos):
        return pos, faces
    # y 위 → z 위: (x, y, z) → (x, -z, y). 오른손 좌표계를 지키는 회전이라 면 방향이 안 뒤집힌다.
    p = np.stack([pos[:, 0], -pos[:, 2], pos[:, 1]], axis=1)
    lo, hi = p.min(axis=0), p.max(axis=0)
    longest = float((hi - lo).max()) or 1.0
    p = (p - lo) * (float(size_mm) / longest)
    span = p.max(axis=0)
    p[:, 0] -= span[0] / 2
    p[:, 1] -= span[1] / 2
    return p, faces


def write_stl(path: Path, pos: np.ndarray, faces: np.ndarray) -> None:
    tri = pos[faces].astype(np.float32)
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(normal, axis=1, keepdims=True)
    normal = np.where(length > 0, normal / np.maximum(length, 1e-20), 0).astype(np.float32)
    record = np.zeros(len(faces), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    record["n"] = normal
    record["v"] = tri
    with open(path, "wb") as fh:
        fh.write(b"Sonjari gen3d STL (mm)".ljust(80, b" "))
        fh.write(struct.pack("<I", len(faces)))
        fh.write(record.tobytes())


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    "</Relationships>"
)


def write_3mf(path: Path, pos: np.ndarray, faces: np.ndarray, name: str = "sonjari") -> None:
    """3MF 핵심 규격만(한 물체 · 한 색 · 밀리미터). 뱀부 스튜디오 · 프루사 슬라이서가 여는 최소 꼴."""
    verts = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in pos.tolist())
    tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces.tolist())
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_")[:40] or "sonjari"
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f'<metadata name="Application">Sonjari gen3d</metadata>'
        f'<resources><object id="1" type="model" name="{safe}"><mesh>'
        f"<vertices>{verts}</vertices><triangles>{tris}</triangles>"
        "</mesh></object></resources>"
        '<build><item objectid="1"/></build></model>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("3D/3dmodel.model", model)


def _mesh_xml(pos: np.ndarray, faces: np.ndarray) -> str:
    verts = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in pos.tolist())
    tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces.tolist())
    return f"<mesh><vertices>{verts}</vertices><triangles>{tris}</triangles></mesh>"


def write_3mf_multi(path: Path, objects: list[tuple[str, np.ndarray, np.ndarray]],
                    blockers: dict[str, list[tuple[np.ndarray, np.ndarray]]] | None = None) -> None:
    """한 판에 물체 여럿(조립 부품 · 핀). 물체마다 따로 — 슬라이서가 부품 하나씩 따로 다룬다(서포트 · 순서 · 지우기).

    blockers = 물체 이름 → 지지대 금지 부피들(판 자리 · 핀 구멍을 감싸는 원기둥). 하나라도 있으면 뱀부 꼴로 쓴다:
    물체마다 「본체 부품 + support_blocker 부품」 묶음 + `Metadata/model_settings.config`(11-16 명령줄 썰기로 지키는 것 확인)."""
    blockers = {k: v for k, v in (blockers or {}).items() if v}
    res, items, cfg = [], [], []
    next_id = 1
    for i, (name, pos, faces) in enumerate(objects, start=1):
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_")[:40] or f"part{i}"
        if not blockers:
            res.append(f'<object id="{next_id}" type="model" name="{safe}">{_mesh_xml(pos, faces)}</object>')
            items.append(f'<item objectid="{next_id}"/>')
            next_id += 1
            continue
        body = next_id
        res.append(f'<object id="{body}" type="model">{_mesh_xml(pos, faces)}</object>')
        comps = [f'<component objectid="{body}"/>']
        parts = [f'<part id="{body}" subtype="normal_part"><metadata key="name" value="{safe}"/></part>']
        next_id += 1
        for k, (bp, bf) in enumerate(blockers.get(name, []), start=1):
            res.append(f'<object id="{next_id}" type="model">{_mesh_xml(bp, bf)}</object>')
            comps.append(f'<component objectid="{next_id}"/>')
            parts.append(f'<part id="{next_id}" subtype="support_blocker">'
                         f'<metadata key="name" value="{safe}_구멍{k}_지지대금지"/></part>')
            next_id += 1
        top = next_id
        next_id += 1
        res.append(f'<object id="{top}" type="model" name="{safe}"><components>{"".join(comps)}</components></object>')
        items.append(f'<item objectid="{top}"/>')
        cfg.append(f'<object id="{top}"><metadata key="name" value="{safe}"/>{"".join(parts)}</object>')
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        '<metadata name="Application">Sonjari gen3d</metadata>'
        f'<resources>{"".join(res)}</resources><build>{"".join(items)}</build></model>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("3D/3dmodel.model", model)
        if cfg:
            zf.writestr("Metadata/model_settings.config",
                        '<?xml version="1.0" encoding="UTF-8"?>\n<config>' + "".join(cfg) + "</config>")


def export_print(mesh: Mesh, out_dir: Path, stem: str, formats: list[str], size_mm: float) -> dict[str, str]:
    pos, faces = print_space(mesh, size_mm)
    files: dict[str, str] = {}
    if "stl" in formats:
        target = out_dir / f"{stem}_{round(size_mm)}mm.stl"
        write_stl(target, pos, faces)
        files["stl"] = str(target)
    if "3mf" in formats:
        target = out_dir / f"{stem}_{round(size_mm)}mm.3mf"
        write_3mf(target, pos, faces, stem)
        files["3mf"] = str(target)
    return files


def prepare_print(mesh: Mesh, out_dir: Path, stem: str, formats: list[str], size_mm: float, *,
                  printer: str | None = None, detail: str = "auto", pitch: float | None = None,
                  slice_it: bool | None = None, orientation: str | None = None, floor_cut_mm: float | None = None,
                  on_stage: Any = None) -> dict[str, Any]:
    """프린트 갈래 한 번에(설계 `설계_3D프린트갈래`): 프린트 자리로 옮김 → **다시 뜨기**(닫힌 메시) → 다시 잼 →
    재서 설정 고르기 → STL · 3MF → (뱀부 스튜디오가 있으면) 썰기. 돌려주는 것: files · printable(다시 뜬 메시 기준) · report."""
    import os

    from .print_plan import orient, plan_print
    from .remesh import remesh
    from .simplify import simplify_closed
    from .slicer import slice_3mf

    if slice_it is None:
        # 끄기: `JARVIS_GEN3D_SLICE=0`(시험 · 뱀부가 있어도 썰지 않을 때).
        slice_it = os.environ.get("JARVIS_GEN3D_SLICE", "1").strip() != "0"
    if pitch is None:
        # 칸 크기(mm) — 노즐 0.4 의 절반이 기본. `JARVIS_GEN3D_PITCH` 로 바꾼다(시험은 굵게).
        pitch = float(os.environ.get("JARVIS_GEN3D_PITCH", "0.2") or 0.2)
    pos, faces = print_space(mesh, size_mm)
    if orientation and orientation != "지금 그대로":
        # 방향 제안을 사람이 받아들였을 때(11-14 폐루프): 돌린 뒤 판 위에 다시 놓는다 — 긴 변(size_mm)은 그대로.
        pos = orient(pos, orientation)
    # 「내 프린터」(11-14 첫 출력 평가 #3): 기종 · 판 · 필라멘트 · 바닥 자르기 — 처음 한 번 묻고 설정에 둔다(지금은 환경 설정).
    prefs = printer_prefs(printer)
    cut = prefs["floor_cut_mm"] if floor_cut_mm is None else max(0.0, float(floor_cut_mm))
    steps: list[dict[str, Any]] = []
    stepper = _Steps(steps, on_stage)
    with stepper("다시 뜨기"):
        rm = remesh(pos, faces, pitch=pitch, floor_cut_mm=cut, thicken_to_mm=prefs["thicken_to_mm"],
                    snap_to_source=prefs["snap"], keep_grid=True)
        stepper.info(f"면 {len(rm.faces):,} · 칸 {rm.pitch:.3f}mm" + (" · 세 방향 투표" if any("세 방향 투표" in n for n in rm.notes) else ""))
    floor_hint = suggest_floor_cut(rm) if not cut else None
    rm.cells = None  # 큰 격자는 여기서 놓는다
    # 면 줄이기(ADR-3D-2): 닫힘 · 오차(99.9% ≤ 0.05mm · 최대 ≤ 0.15mm)를 지키는 가장 적은 면. 못 하면 그대로.
    with stepper("면 줄이기"):
        sm = simplify_closed(rm.positions, rm.faces) if len(rm.faces) else None
        stepper.info(f"면 {len(sm.faces):,}" if sm is not None else "그대로")
    mp, mf = (sm.positions, sm.faces) if sm is not None else (rm.positions, rm.faces)
    after = check_printable(Mesh(mp, mf))
    report: dict[str, Any] = {"orientation": orientation or "지금 그대로",
                              "remesh": {**rm.receipt(), "notes": rm.notes,
                                         "after": {k: after[k] for k in ("watertight", "boundary_edges",
                                                                         "non_manifold_edges", "flipped_edges", "parts")}}}
    if sm is not None:
        report["simplify"] = {**sm.receipt(), "notes": sm.notes}
    files: dict[str, str] = {}
    if not len(rm.faces):
        return {"files": files, "printable": {"ok": False, "why": ["다시 뜨기 결과가 비었다"], "notes": rm.notes},
                "report": report}
    with stepper("받침 고르기"):
        plan = plan_print(mp, mf, size_mm, detail)
        report["plan"] = plan.receipt()
        stepper.info(f"받침 {plan.receipt()['decisions'][0]['value']} · 바닥 닿음 {plan.receipt()['measured']['base_area_mm2']:.0f}mm²")
    tag = f"{stem}_{round(size_mm)}mm"
    if "stl" in formats:
        target = out_dir / f"{tag}.stl"
        write_stl(target, mp, mf)
        files["stl"] = str(target)
    if "3mf" in formats:
        target = out_dir / f"{tag}.3mf"
        write_3mf(target, mp, mf, stem)
        files["3mf"] = str(target)
        if slice_it:
            with stepper("썰기"):
                sliced = slice_3mf(target, out_dir / "slice", printer=prefs["printer"], process=plan.process,
                                   filament=prefs["filament"],
                                   overrides={**plan.overrides(), "curr_bed_type": prefs["bed"]},
                                   mesh_height=float(np.ptp(mp[:, 2])),
                                   mesh_dims=tuple(float(v) for v in np.ptp(mp, axis=0)))
                stepper.info(f"{sliced.get('estimated_time')} · {sliced.get('filament_g')}g" if sliced.get("ok")
                             else f"실패: {sliced.get('error') or sliced.get('skipped')}")
            report["slice"] = sliced
            if sliced.get("ok") and sliced.get("gcode"):
                files["gcode"] = sliced["gcode"]
            if sliced.get("project_3mf"):
                # 사람이 뱀부 스튜디오에서 열 파일 — 고른 설정(프린터 · 서포트 · 브림 · 층)이 이미 들어 있다.
                files["bambu_3mf"] = sliced["project_3mf"]
    ok = bool(after["printable"]["ok"]) and not rm.leaked
    why = list(after["printable"]["why"])
    if rm.leaked:
        why.append("구멍이 커서 속이 빈 껍질로 나왔다 — 그대로 뽑으면 약하다")
    notes = list(after["printable"]["notes"]) + list(rm.notes) + (list(sm.notes) if sm is not None else [])
    if rm.thickened_cells and rm.thin_bbox_before_mm:
        lo, hi = rm.thin_bbox_before_mm
        notes.append(f"가는 막대를 굵게 했다: {rm.min_thickness_mm:g}mm 보다 가는 길쭉한 부분 {rm.thin_share_before:.1%} → "
                     f"{rm.thin_share:.1%} (높이 {lo[2]:.0f}~{hi[2]:.0f}mm 사이 · 목표 {rm.thicken_to_mm:g}mm · "
                     f"{rm.thickened_cells * rm.pitch ** 3:.0f}mm³ 더함) — 밧줄 · 돛대 같은 가는 줄이 그림보다 굵어진다. "
                     "얇은 판(벽 · 돛 · 깃발)은 그대로 둔다")
    if rm.thin_share > 0.002 and rm.thin_bbox_mm:
        lo, hi = rm.thin_bbox_mm
        notes.append(f"얇은 곳: {rm.min_thickness_mm:g}mm 보다 가는 길쭉한 부분이 부피의 {rm.thin_share:.1%} "
                     f"(높이 {lo[2]:.0f}~{hi[2]:.0f}mm 사이) — 끊기거나 실이 늘어질 수 있다. 그림에서 굵게 하거나 크기를 키워라")
    report["steps"] = steps
    if floor_hint:
        report["floor_suggestion"] = floor_hint
    report["needs_decision"] = needs_decision(rm, report, steps, floor_hint)
    return {"files": files, "printable": {"ok": ok, "why": why, "notes": notes, "size_mm": size_mm,
                                           "fixed_by": "다시 뜨기(블록 · 사면체)"}, "report": report}


SLOW_STEP_SEC = 180.0
NARROW_BASE_MM2 = 30.0


class _Steps:
    """프린트 준비 안쪽 단계(설계 `설계_3D두번굽기_분업` §4-4) — 걸린 초 · 숫자 한 줄을 남기고, 시작 · 끝을 알린다.
    11-15 리락쿠마: 8분 동안 「write glb」 한 칸만 보여 멈춘 줄 알았다."""

    def __init__(self, steps: list[dict[str, Any]], on_stage: Any) -> None:
        self.steps, self.on_stage, self._cur = steps, on_stage, None

    def __call__(self, name: str) -> "_Steps":
        self._cur = {"name": name, "sec": None, "info": ""}
        return self

    def __enter__(self) -> "_Steps":
        import time
        self._t = time.time()
        self.steps.append(self._cur)
        self._emit("start")
        return self

    def info(self, text: str) -> None:
        self._cur["info"] = text

    def __exit__(self, *exc: Any) -> None:
        import time
        self._cur["sec"] = round(time.time() - self._t, 1)
        self._emit("done")

    def _emit(self, phase: str) -> None:
        if self.on_stage is not None:
            try:
                self.on_stage({**self._cur, "phase": phase, "steps": list(self.steps)})
            except Exception:  # noqa: BLE001 — 알림이 틀어져도 일은 계속
                pass


def suggest_floor_cut(rm: Any, target_mm2: float = 150.0, max_share: float = 0.12) -> dict[str, Any] | None:
    """바닥이 점처럼 닿으면(둥근 엉덩이 · 발끝) 몇 mm 를 잘라야 닿는 넓이가 넉넉해지나 — 칸 격자 층마다 넓이로 잰다.
    제안만(자르면 모양이 바뀐다 · 사람이나 클로드가 정한다). 11-15 리락쿠마 c 판: 바닥 닿음 4mm²."""
    if not rm.cells:
        return None
    solid = rm.cells[0]
    pitch = rm.pitch
    area = solid.sum(axis=(0, 1)).astype(float) * pitch * pitch
    zs = np.nonzero(area > 0)[0]
    if not len(zs):
        return None
    z0, z1 = int(zs[0]), int(zs[-1])
    first = float(area[z0])
    if first >= target_mm2:
        return None
    limit = max(1, int((z1 - z0 + 1) * max_share))
    goal = min(target_mm2, float(area.max()) * 0.25)
    for k in range(1, limit + 1):
        if area[z0 + k] >= goal:
            return {"cut_mm": round(k * pitch, 2), "contact_now_mm2": round(first, 1),
                    "contact_after_mm2": round(float(area[z0 + k]), 1),
                    "how": "gen_3d_print(floor_cut_mm=…)로 바닥을 평평하게 자르면 판에 닿는 넓이가 늘고 받침 · 브림이 준다 — 아래가 깎이니 사람에게 확인"}
    return {"cut_mm": round(limit * pitch, 2), "contact_now_mm2": round(first, 1),
            "contact_after_mm2": round(float(area[z0 + limit]), 1), "how": "높이의 12% 까지 잘라도 넉넉하지 않다 — 받침대를 그려 넣는 쪽을 생각"}


def needs_decision(rm: Any, report: dict[str, Any], steps: list[dict[str, Any]], floor_hint: dict | None) -> list[str]:
    """클로드가 끝까지 기다리지 말고 바로 판단할 것(설계 §4-4) — 결정론으로 잡히는 것만."""
    out: list[str] = []
    if rm.leaked:
        out.append("속 빈 껍질: 큰 구멍(또는 진짜 입구) — 6방향 판으로 보고 사진 손질 · 씨앗 바꾸기")
    base = ((report.get("plan") or {}).get("measured") or {}).get("base_area_mm2")
    if base is not None and base < NARROW_BASE_MM2:
        out.append(f"바닥이 점처럼 닿음({base:.0f}mm²)" + (f" — 바닥 {floor_hint['cut_mm']}mm 자르면 {floor_hint['contact_after_mm2']:.0f}mm²" if floor_hint else ""))
    sl = report.get("slice") or {}
    if sl and not sl.get("ok") and not sl.get("skipped"):
        out.append(f"썰기 실패: {sl.get('error')}")
    for s in steps:
        if (s.get("sec") or 0) > SLOW_STEP_SEC:
            out.append(f"{s['name']} 이(가) {s['sec']:.0f}초 걸림 — 모델이 무겁거나 구멍이 많다")
    if rm.thin_share > 0.002:
        out.append("굵히고도 가는 길쭉한 곳이 남음 — 크기를 키우거나 그림을 굵게")
    return out


def printer_prefs(printer: str | None = None) -> dict[str, Any]:
    """「내 프린터」 — 설정(환경)에서: JARVIS_GEN3D_PRINTER · _BED · _FILAMENT · _FLOOR_CUT(mm).
    판 기본은 뱀부 기계 설정의 기본(「Textured PEI Plate」 · 11-14 이 PC 설정 14곳)과 같게 — 지난번 파일에 「Cool Plate」가 들어갔다."""
    import os

    def env(name: str, default: str) -> str:
        return (os.environ.get(name, "") or "").strip() or default

    try:
        cut = max(0.0, float(env("JARVIS_GEN3D_FLOOR_CUT", "0")))
    except ValueError:
        cut = 0.0
    # 가는 곳 굵게(mm · 0 이면 끔) — 기본 1.6(노즐 0.4 × 4줄). 11-14 첫 실물에서 1mm 안팎 밧줄이 털 · 구슬로 망가졌다.
    try:
        thick = max(0.0, float(env("JARVIS_GEN3D_THICKEN", "1.6")))
    except ValueError:
        thick = 1.6
    return {"printer": printer or env("JARVIS_GEN3D_PRINTER", "Bambu Lab X2D"),
            "bed": env("JARVIS_GEN3D_BED", "Textured PEI Plate"),
            "filament": env("JARVIS_GEN3D_FILAMENT", "Bambu PLA Basic"),
            "floor_cut_mm": cut, "thicken_to_mm": thick,
            # 겉면 다시 붙이기(0 이면 끔) — 11-14 배 옆면 기울기 흔들림 6.1° → 1.7°(원래 1.4°).
            "snap": env("JARVIS_GEN3D_SNAP", "1") != "0"}
