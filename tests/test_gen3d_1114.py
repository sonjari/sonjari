"""3D 생성 팩 — 진행 줄 읽기 · 영수증 꼴 · 파일 내주기 막기 · 프린트 검사 (2026-11-14 · 설계 §3-1 · 계약 gen3d_계약_1114).

양방향: 해야 할 것(실제 로그에서 단계 7 · 단계 안 비율 · 정리 숫자 · 닫힌 메시는 통과 · 이름표 있는 파일은 내줌) /
하면 안 되는 것(로그의 분모 6 을 믿음 · 「~12s left」 를 실음 · 구멍 난 메시를 통과 · 영수증 밖 이름 · 경로 빠져나가기).
시험 자료 `fixtures/gen3d/*.log.txt` 는 실측 로그(`D:\\models\\img2_3d\\results\\`)에서 디버그 줄만 뺀 것이다(`\\r` 덮어쓰기는 그대로).
"""
from __future__ import annotations

import io
import json
import struct
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from alture_jarvis.gen3d.glb import Mesh, read_glb
from alture_jarvis.gen3d.printing import check_printable, export_print, print_space
from alture_jarvis.gen3d.progress import TOTAL_STAGES, StageTracker
from alture_jarvis.gen3d.runner import Gen3DRunner, valid_job_id
from alture_jarvis.gen3d_tools import Gen3DTools, gen3d_dirs
from alture_jarvis.packs import PackRegistry
from alture_jarvis.tool_gateway import tool_runs_here

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gen3d"


@pytest.fixture(autouse=True)
def _no_real_slicer(monkeypatch: pytest.MonkeyPatch) -> None:
    """시험 중에는 이 PC 에 깔린 뱀부 스튜디오를 부르지 않는다(썰기는 `test_gen3d_print_1114.py` 가 가짜 프로세스로)."""
    monkeypatch.setenv("JARVIS_GEN3D_SLICE", "0")
    monkeypatch.setenv("JARVIS_GEN3D_PITCH", "2.0")  # 시험 정육면체(80~120mm)를 굵은 칸으로 — 0.2 면 칸 1,600만 개
PACKS_DIR = Path(__file__).resolve().parents[1] / "packs"


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


# ── 진행 줄 ─────────────────────────────────────────────────────────────

def _feed(name: str) -> StageTracker:
    tracker = StageTracker(clock=_Clock())
    tracker.feed_text((FIXTURES / name).read_text(encoding="utf-8"))
    tracker.finish()
    return tracker


@pytest.mark.parametrize("name", ["ship_color_512.log.txt", "warrior_512.log.txt"])
def test_stages_are_seven_by_number_even_though_the_log_says_six(name: str) -> None:
    raw = (FIXTURES / name).read_text(encoding="utf-8")
    assert "[1/6]" in raw and "[7/7]" in raw  # 자료가 정말 분모가 섞인 로그인지
    tracker = _feed(name)
    assert [s["index"] for s in tracker.stages] == [1, 2, 3, 4, 5, 6, 7]
    assert TOTAL_STAGES == 7
    names = [s["name"] for s in tracker.stages]
    assert names[1] == "DINOv3 conditioning" and names[3].startswith("shape SLAT flow")
    # 경로는 파일 이름만 남는다(사용자 폴더가 화면 · 영수증에 안 샌다)
    assert all("D:/" not in n and "models/img2_3d" not in n for n in names)
    assert names[6].startswith("write ") and names[6].endswith(".glb")


def test_cleanup_numbers_match_the_experiment_record() -> None:
    ship = _feed("ship_color_512.log.txt")
    assert ship.holes_filled == 1327          # fill_holes: 1327 boundary loops filled
    assert ship.floaters_dropped == 208 + 2   # remesh postproc 208 + decimated postproc 2
    assert ship.exe_sec == 101.8              # done in 101.8s
    assert ship.decimate_target == 150000


def test_flow_ratio_is_carried_but_never_the_remaining_time() -> None:
    tracker = StageTracker(clock=_Clock())
    tracker.feed("[3/6] sparse-structure flow + decode")
    tracker.feed_text("      [flow] [####....]  4/12    8.5s  ~17s left   \r      [flow] [#####...]  5/12   10.6s  ~15s left   \r")
    current = tracker.current()
    assert current["index"] == 3 and current["total"] == 7
    assert current["sub"] == {"done": 5, "total": 12}
    assert "left" not in json.dumps(current) and "17" not in json.dumps(current)
    # 다음 단계로 넘어가면 비율은 지워진다
    tracker.feed("[4/7] shape SLAT flow (512)")
    assert "sub" not in tracker.current()


def test_a_flow_line_is_not_taken_for_a_stage() -> None:
    tracker = StageTracker(clock=_Clock())
    tracker.feed("[2/6] DINOv3 conditioning")
    tracker.feed("      [flow] [####################] 12/12   23.3s  ~0s left")
    assert tracker.current()["index"] == 2


# ── 시험용 GLB · 메시 ──────────────────────────────────────────────────

def _cube() -> Mesh:
    v = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], dtype=np.float64)
    # 바깥을 향하는 12 삼각형
    f = np.array([
        [0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
        [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3],
    ])
    return Mesh(positions=v * [2.0, 1.0, 0.5], faces=f)


def _split_uv_cube() -> Mesh:
    """GLB 처럼 면마다 꼭짓점을 따로 둔 상자 — 합치지 않으면 구멍투성이로 읽힌다."""
    cube = _cube()
    return Mesh(positions=cube.positions[cube.faces].reshape(-1, 3), faces=np.arange(36).reshape(12, 3))


def _write_glb(path: Path, mesh: Mesh) -> None:
    pos = mesh.positions.astype(np.float32)
    idx = mesh.faces.astype(np.uint32).reshape(-1)
    binary = pos.tobytes() + idx.tobytes()
    gltf = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": pos.nbytes},
                        {"buffer": 0, "byteOffset": pos.nbytes, "byteLength": idx.nbytes}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(pos), "type": "VEC3",
             "min": pos.min(axis=0).tolist(), "max": pos.max(axis=0).tolist()},
            {"bufferView": 1, "componentType": 5125, "count": len(idx), "type": "SCALAR"},
        ],
    }
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
                     + struct.pack("<II", len(binary), 0x004E4942) + binary)


# ── 프린트 검사 ─────────────────────────────────────────────────────────

def test_a_closed_box_is_printable_even_with_split_uv_vertices() -> None:
    result = check_printable(_split_uv_cube())
    assert result["watertight"] is True
    assert result["boundary_edges"] == 0 and result["non_manifold_edges"] == 0 and result["flipped_edges"] == 0
    assert result["parts"] == 1
    assert result["printable"] == {"ok": True, "why": [], "notes": []}


def test_a_box_with_a_hole_is_not_printable() -> None:
    cube = _cube()
    holed = Mesh(positions=cube.positions, faces=cube.faces[2:])  # 한 면(삼각형 둘)을 뺀다
    result = check_printable(holed)
    assert result["watertight"] is False
    assert result["boundary_edges"] == 4
    assert result["printable"]["ok"] is False
    assert any("열린 가장자리 4개" in why for why in result["printable"]["why"])


def test_a_flipped_face_is_caught() -> None:
    cube = _cube()
    faces = cube.faces.copy()
    faces[0] = faces[0][::-1]
    result = check_printable(Mesh(positions=cube.positions, faces=faces))
    assert result["printable"]["ok"] is False and result["flipped_edges"] > 0


def test_a_shared_edge_of_four_faces_is_non_manifold_not_double_flipped() -> None:
    # 상자 둘이 가장자리 하나로만 맞닿음 — 그 가장자리에 면 넷.
    a = _cube()
    b = Mesh(positions=a.positions + a.positions.max(axis=0) * [1, 1, 0], faces=a.faces)
    both = Mesh(positions=np.concatenate([a.positions, b.positions]), faces=np.concatenate([a.faces, b.faces + 8]))
    result = check_printable(both)
    assert result["non_manifold_edges"] == 1
    assert result["flipped_edges"] == 0
    assert result["printable"]["ok"] is False


def test_print_files_are_millimetres_with_the_longest_side_as_asked(tmp_path: Path) -> None:
    files = export_print(_cube(), tmp_path, "box", ["stl", "3mf"], 80)
    stl = Path(files["stl"]).read_bytes()
    count = struct.unpack_from("<I", stl, 80)[0]
    assert count == 12 and len(stl) == 84 + 50 * 12
    tri = np.frombuffer(stl[84:], dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])["v"].reshape(-1, 3)
    span = tri.max(axis=0) - tri.min(axis=0)
    assert abs(span.max() - 80) < 1e-3
    assert abs(tri[:, 2].min()) < 1e-4  # 바닥 z = 0
    with zipfile.ZipFile(files["3mf"]) as zf:
        assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= set(zf.namelist())
        model = zf.read("3D/3dmodel.model").decode()
        assert 'unit="millimeter"' in model and model.count("<triangle ") == 12


def test_y_up_becomes_z_up_for_the_printer() -> None:
    tall = Mesh(positions=_cube().positions * [1, 10, 1], faces=_cube().faces)  # glTF 에서 y 로 길쭉
    pos, _ = print_space(tall, 100)
    span = pos.max(axis=0) - pos.min(axis=0)
    assert span.argmax() == 2  # 프린터에서는 z 로 길쭉


# ── 실행기 · 영수증 ─────────────────────────────────────────────────────

class _FakeProcess:
    """로그를 흘리고 GLB 를 쓰는 가짜 trellis-cli."""

    def __init__(self, cmd: list[str], log: bytes, glb_mesh: Mesh | None, rc: int = 0, hold: threading.Event | None = None) -> None:
        self.cmd = cmd
        self.stdout = io.BytesIO(log)
        self._rc = rc
        self.killed = False
        self._hold = hold
        out = Path(cmd[cmd.index("-o") + 1])
        if glb_mesh is not None and rc == 0:
            _write_glb(out, glb_mesh)

    def wait(self, timeout: float | None = None) -> int:
        if self._hold is not None:
            self._hold.wait(timeout or 5)
        else:
            time.sleep(0.2)  # 메모리 재기가 몇 번 돌 시간
        return -9 if self.killed else self._rc

    def kill(self) -> None:
        self.killed = True
        if self._hold is not None:
            self._hold.set()


def _ready_dirs(root: Path) -> tuple[Path, Path]:
    bin_dir, models = root / "bin", root / "models"
    bin_dir.mkdir()
    models.mkdir()
    (bin_dir / "trellis-cli.exe").write_bytes(b"")
    (bin_dir / "trellis-cli").write_bytes(b"")
    for name in ("birefnet.gguf", "dinov3.gguf", "ss_flow.gguf", "ss_dec.gguf", "shape_dec.gguf", "tex_dec.gguf"):
        (models / name).write_bytes(b"")
    return bin_dir, models


def _wait(runner: Gen3DRunner, job_id: str, want: set[str] = frozenset({"done", "failed"})) -> dict[str, Any]:
    # 11-17: 6초(0.02×300)였다 — 전체 회귀(6갈래)로 PC 가 바쁠 때 흉내 굽기의 마지막 단계가 6초를 넘겨 두 번 연달아 떨어졌다(혼자는 통과).
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        found = runner.get(job_id)
        if found and found["state"] in want:
            return found
        time.sleep(0.02)
    raise AssertionError(f"끝나지 않음: {runner.get(job_id)}")


def _runner(tmp_path: Path, mesh: Mesh | None | str = "cube", rc: int = 0, calls: list | None = None) -> Gen3DRunner:
    if mesh == "cube":
        mesh = _cube()
    bin_dir, models = _ready_dirs(tmp_path)
    log = (FIXTURES / "ship_color_512.log.txt").read_bytes()

    def popen(cmd: list[str], **kwargs: Any) -> _FakeProcess:
        if calls is not None:
            calls.append((cmd, kwargs))
        return _FakeProcess(cmd, log, mesh, rc)

    vram = iter([1117, 2000, 3246, 3000] + [1200] * 1000)
    return Gen3DRunner(tmp_path / "out", bin_dir, models, popen=popen, vram_probe=lambda gpu: next(vram), poll_sec=0.01)


def test_receipt_has_the_contract_shape(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    calls: list = []
    runner = _runner(tmp_path, calls=calls)
    job_id = runner.submit(image, res=512, gpu=1, export=["glb", "stl", "3mf"], size_mm=120)
    assert valid_job_id(job_id)
    found = _wait(runner, job_id)
    assert found["state"] == "done", found
    assert set(found) >= {"job_id", "state", "stage", "stages", "receipt", "error"}
    assert found["error"] is None
    assert [s["index"] for s in found["stages"]] == list(range(1, 8))
    receipt = found["receipt"]
    assert set(receipt) >= {"did", "files", "measured", "printable", "not_done", "model"}
    assert receipt["did"] == "3D 초안 1개 · 512"
    files = receipt["files"]
    assert set(files) >= {"glb", "preview", "stl", "3mf"} and len(files["preview"]) == 2
    measured = receipt["measured"]
    assert measured["faces"] == 12
    assert measured["holes_filled"] == 1327 and measured["floaters_dropped"] == 210
    assert measured["bbox_m"] == [2.0, 1.0, 0.5]
    assert measured["vram_peak_mib"] == 3246 and measured["vram_base_mib"] == 1117
    assert measured["watertight"] is True and receipt["printable"]["ok"] is True
    assert receipt["model"]["name"] == "trellis2" and receipt["model"]["res"] == 512
    # 카드 번호는 nvidia-smi 번호와 맞춰 넘긴다
    cmd, kwargs = calls[0]
    assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "1" and kwargs["env"]["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    assert cmd[cmd.index("--res") + 1] == "512" and "-v" not in cmd
    # 미리보기는 긴 변 512 이하
    from PIL import Image
    for preview in files["preview"]:
        assert max(Image.open(preview).size) <= 512
    # 본체를 다시 켜도 영수증은 디스크에서 읽힌다
    again = Gen3DRunner(tmp_path / "out", tmp_path / "bin", tmp_path / "models")
    assert again.get(job_id)["receipt"]["measured"]["faces"] == 12


def test_a_failed_run_still_gives_a_receipt(tmp_path: Path) -> None:
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    runner = _runner(tmp_path, mesh=None, rc=3)
    found = _wait(runner, runner.submit(image))
    assert found["state"] == "failed" and found["error"].startswith("exit_3")
    assert found["receipt"]["files"] == {} and found["receipt"]["printable"]["ok"] is False
    assert any("멈춘 자리" in item for item in found["receipt"]["not_done"])


def test_only_one_runs_and_one_waits(tmp_path: Path) -> None:
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    bin_dir, models = _ready_dirs(tmp_path)
    hold = threading.Event()
    log = b"[1/6] preprocess x.png (512)\n"
    runner = Gen3DRunner(tmp_path / "out", bin_dir, models,
                         popen=lambda cmd, **kw: _FakeProcess(cmd, log, None, 0, hold), vram_probe=lambda gpu: None)
    first = runner.submit(image)
    second = runner.submit(image)
    with pytest.raises(RuntimeError, match="busy"):
        runner.submit(image)
    assert runner.get(second)["state"] == "queued"
    assert runner.cancel(second) is True and runner.get(second)["error"] == "cancelled"
    assert runner.cancel(first) is True
    found = _wait(runner, first)
    assert found["state"] == "failed" and found["error"] == "cancelled"


def test_not_ready_without_the_runner(tmp_path: Path) -> None:
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    runner = Gen3DRunner(tmp_path / "out", tmp_path / "nobin", tmp_path / "nomodels")
    with pytest.raises(RuntimeError, match="not_ready"):
        runner.submit(image)


# ── 파일 내주기: 영수증에 있는 이름만 ────────────────────────────────────

def test_files_are_served_only_by_receipt_name(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    runner = _runner(tmp_path)
    job_id = runner.submit(image, export=["stl"])
    receipt = _wait(runner, job_id)["receipt"]
    glb_name = Path(receipt["files"]["glb"]).name
    assert runner.file_for(job_id, glb_name) == Path(receipt["files"]["glb"]).resolve()
    folder = tmp_path / "out" / job_id
    (folder / "secret.txt").write_text("x")
    (tmp_path / "out" / "outside.glb").write_bytes(b"x")
    for bad in ["secret.txt", "run.log", "job.json", "../outside.glb", "..\\outside.glb", "..", ".",
                str(folder / glb_name), "/etc/passwd", "C:\\Windows\\win.ini", ""]:
        assert runner.file_for(job_id, bad) is None, bad
    # 판 이름으로 빠져나가기
    assert runner.file_for("../" + job_id, glb_name) is None
    assert runner.file_for("g3_x", glb_name) is None


# ── 팩 · 도구 문 ────────────────────────────────────────────────────────

class _Packs:
    def __init__(self, on: bool) -> None:
        self.on = on

    def is_enabled(self, pack_id: str) -> bool:
        return self.on and pack_id == "gen3d"


class _Config:
    def __init__(self, root: Path) -> None:
        self.data_dir = root / "data"
        self.documents_dir = root / "docs"
        self.output_dir = root / "out"
        self.gen3d_bin_dir = ""
        self.gen3d_models_dir = ""


def test_the_pack_loads_off_with_two_tools(tmp_path: Path) -> None:
    registry = PackRegistry(PACKS_DIR, tmp_path / "data")
    pack = {p["id"]: p for p in registry.listing()["packs"]}["gen3d"]
    assert pack["tools"] == ["gen_3d_check", "gen_3d_blender", "gen_3d_prep", "gen_3d", "gen_3d_status", "gen_3d_print", "gen_3d_views", "gen_3d_finish", "gen_3d_render", "gen_3d_export", "gen_3d_split_plan", "gen_3d_split", "gen_3d_fit_test", "gen_3d_fit_set"]
    assert pack["enabled"] is False
    manifest = json.loads((PACKS_DIR / "gen3d" / "pack.json").read_text(encoding="utf-8"))
    binary = next(m for m in manifest["models"] if m["kind"] == "binary")
    assert binary["dir"] == "trellis-cpp" and len(binary["sha256"]) == 64


def test_a_disabled_pack_hides_and_refuses(tmp_path: Path) -> None:
    tools = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(False))
    assert tools.active_ollama_tools == []
    with pytest.raises(PermissionError, match="pack_disabled"):
        tools.gen_3d({"image_path": str(tmp_path / "x.png")})
    on = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    assert [t["function"]["name"] for t in on.active_ollama_tools] == ["gen_3d_check", "gen_3d_blender", "gen_3d_prep", "gen_3d", "gen_3d_status", "gen_3d_print", "gen_3d_views", "gen_3d_finish", "gen_3d_render", "gen_3d_export", "gen_3d_split_plan", "gen_3d_split", "gen_3d_fit_test", "gen_3d_fit_set"]


def test_the_image_path_goes_through_the_file_tool_check(tmp_path: Path) -> None:
    def refuse(raw: str) -> Path:
        raise PermissionError("path_outside_allowed_roots")

    tools = Gen3DTools(_Config(tmp_path), resolve=refuse, packs=_Packs(True))
    with pytest.raises(PermissionError, match="outside_allowed"):
        tools.gen_3d({"image_path": "C:/Windows/secret.png"})


def test_a_non_image_is_refused(tmp_path: Path) -> None:
    text = tmp_path / "x.txt"
    text.write_text("x")
    tools = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    with pytest.raises(ValueError, match="그림 파일이 아니다"):
        tools.gen_3d({"image_path": str(text)})


def test_default_dirs_follow_the_pack_layout_and_the_q8_subfolder(tmp_path: Path) -> None:
    config = _Config(tmp_path)
    bin_dir, models = gen3d_dirs(config)
    assert bin_dir == tmp_path / "data" / "tools" / "gen3d" / "trellis-cpp"
    assert models == tmp_path / "data" / "models" / "gen3d" / "trellis2-q8"
    # hf include ["q8/*"] 로 받으면 q8/ 아래에 놓인다 → 그쪽을 실행기에 넘긴다
    q8 = models / "q8"
    q8.mkdir(parents=True)
    for name in ("birefnet.gguf", "dinov3.gguf", "ss_flow.gguf", "ss_dec.gguf", "shape_dec.gguf", "tex_dec.gguf"):
        (q8 / name).write_bytes(b"")
    assert gen3d_dirs(config)[1] == q8
    config.gen3d_models_dir = str(tmp_path / "elsewhere")
    assert gen3d_dirs(config)[1] == tmp_path / "elsewhere"


def test_the_tools_run_on_windows_and_mac_not_linux() -> None:
    # 11-14: 맥(Metal) 판을 직접 빌드해 실측했다 — darwin 도 연다. 실행기가 없으면 도구가 not_ready 로 거절한다(아래 시험).
    for name in ("gen_3d", "gen_3d_status", "gen_3d_check"):
        assert tool_runs_here(name, "win32") is True
        assert tool_runs_here(name, "darwin") is True
        assert tool_runs_here(name, "linux") is False


def test_glb_reader_reads_a_plain_box(tmp_path: Path) -> None:
    path = tmp_path / "box.glb"
    _write_glb(path, _cube())
    data = path.read_bytes()
    mesh = read_glb(path)
    assert mesh.faces.shape == (12, 3) and np.allclose(mesh.bbox[1], [2, 1, 0.5])
    assert data[:4] == b"glTF"


# ── API 문(계약의 셋) ───────────────────────────────────────────────────

def test_api_needs_the_token_the_pack_and_an_allowed_image(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          documents_dir=tmp_path / "docs", control_token="test-token", camera_enabled=False,
                          vision_enabled=False, voice_enabled=False, tts_enabled=False)
    app = create_app(config, start_services=False)
    client = TestClient(app)
    head = {"X-JARVIS-TOKEN": "test-token"}
    image = tmp_path / "docs" / "ship.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"png")

    assert client.post("/v1/gen3d/jobs", json={"image_path": str(image)}).status_code == 401
    # 팩이 꺼져 있으면 거절
    assert client.post("/v1/gen3d/jobs", json={"image_path": str(image)}, headers=head).status_code == 403
    assert client.post("/v1/packs/gen3d/enable", headers=head).status_code == 200
    # 허락 밖 그림은 파일 도구와 같은 검사로 막힌다
    outside = tmp_path.parent / "outside_gen3d.png"
    assert client.post("/v1/gen3d/jobs", json={"image_path": str(outside)}, headers=head).status_code in {400, 403}
    # 실행기가 없으면 「준비 안 됨」(409) — 지어낸 job 을 주지 않는다
    response = client.post("/v1/gen3d/jobs", json={"image_path": str(image)}, headers=head)
    assert response.status_code == 409 and "not_ready" in response.text

    # 가짜 실행기로 한 판 → 상태 · 파일
    runtime = app.state.jarvis
    runtime.gen3d_tools._runner = _runner(tmp_path)
    response = client.post("/v1/gen3d/jobs", json={"image_path": str(image), "export": ["glb", "3mf"]}, headers=head)
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    _wait(runtime.gen3d_tools._runner, job_id)
    body = client.get(f"/v1/gen3d/jobs/{job_id}", headers=head).json()
    assert body["state"] == "done" and body["receipt"]["files"]["3mf"].endswith(".3mf")
    glb = Path(body["receipt"]["files"]["glb"]).name
    got = client.get(f"/v1/gen3d/jobs/{job_id}/file/{glb}", headers=head)
    assert got.status_code == 200 and got.content[:4] == b"glTF" and got.headers["content-type"] == "model/gltf-binary"
    webp = Path(body["receipt"]["files"]["preview"][0]).name
    assert client.get(f"/v1/gen3d/jobs/{job_id}/file/{webp}", headers=head).headers["content-type"] == "image/webp"
    for bad in ["job.json", "run.log", "..%2Fjob.json", "%2E%2E"]:
        assert client.get(f"/v1/gen3d/jobs/{job_id}/file/{bad}", headers=head).status_code == 404, bad
    assert client.get("/v1/gen3d/jobs/g3_nope", headers=head).status_code == 404


# ── 맥(Metal · 통합 메모리) 갈래 · 모델 갈아타기 (2026-11-14) ──────────────────

class _TextModels:
    """가짜 이 기기 Ollama. loaded 는 내리기 전까지 그대로, unload 를 부르면 비운다(keep 은 끝내 안 내려가는 이름)."""

    def __init__(self, rows: list[dict[str, Any]], keep: tuple[str, ...] = ()) -> None:
        self.rows, self.keep, self.unloaded_calls = list(rows), keep, []

    def loaded(self) -> list[dict[str, Any]]:
        return list(self.rows)

    def unload(self, names: list[str]) -> list[str]:
        self.unloaded_calls.append(list(names))
        self.rows = [row for row in self.rows if row["name"] in self.keep]
        return [row["name"] for row in self.rows]


def _platform_runner(tmp_path: Path, platform: str, *, free: int | None = 12000, total: int | None = 16384,
                     text_models: Any = None, calls: list | None = None, frees: list[int] | None = None) -> Gen3DRunner:
    bin_dir, models = _ready_dirs(tmp_path)
    log = (FIXTURES / "ship_color_512.log.txt").read_bytes()
    free_values = iter(frees or [])

    def popen(cmd: list[str], **kwargs: Any) -> _FakeProcess:
        if calls is not None:
            calls.append((cmd, kwargs))
        return _FakeProcess(cmd, log, _cube(), 0)

    def free_probe() -> int | None:
        return next(free_values, free)

    used = iter([4000, 9000, 10500, 9800] + [5000] * 1000)
    return Gen3DRunner(tmp_path / "out", bin_dir, models, popen=popen, vram_probe=lambda gpu: next(used), poll_sec=0.01,
                       platform=platform, free_probe=free_probe, total_probe=lambda: total,
                       proc_probe=lambda pid: 5800, text_models=text_models)


def _phases(runner: Gen3DRunner) -> list[str]:
    seen: list[str] = []

    def on_change(job_id: str) -> None:
        swap = (runner.get(job_id) or {}).get("swap") or {}
        if swap.get("phase") and (not seen or seen[-1] != swap["phase"]):
            seen.append(swap["phase"])

    runner.on_change = on_change
    return seen


def test_mac_runs_the_metal_runner_ignores_gpu_and_measures_unified_memory(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    calls: list = []
    text = _TextModels([{"name": "gemma3:12b", "mib": 9000}])
    runner = _platform_runner(tmp_path, "darwin", text_models=text, calls=calls)
    phases = _phases(runner)
    found = _wait(runner, runner.submit(image, res=512, gpu=1))
    assert found["state"] == "done", found
    cmd, kwargs = calls[0]
    assert Path(cmd[0]).name == "trellis-cli", "맥은 .exe 가 아닌 Metal 판"
    import os

    assert kwargs["env"].get("CUDA_VISIBLE_DEVICES") == os.environ.get("CUDA_VISIBLE_DEVICES"), "맥은 gpu 인자를 무시한다"
    measured = found["receipt"]["measured"]
    assert measured["unified_memory"] is True and "통합 메모리" in measured["memory_what"]
    assert measured["vram_base_mib"] == 4000 and measured["vram_peak_mib"] == 10500, "계약 칸 이름은 그대로 · 값은 통합 메모리"
    assert measured["proc_peak_mib"] == 5800 and measured["free_before_mib"] == 12000
    assert measured["text_models_unloaded"] == ["gemma3:12b"]
    # 갈아타기 알림이 순서대로: 글 모델 내리기 → 3D 올리기 → 준비됨
    assert text.unloaded_calls == [["gemma3:12b"]]
    assert phases == ["unload", "load", "ready"], phases
    assert any("다음 질문 때 Ollama 가 저절로 다시 올린다" in note for note in found["receipt"]["not_done"])


def test_a_satellite_mac_has_nothing_to_unload_and_still_announces_the_load(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    text = _TextModels([])  # 글 모델이 집 PC 에 있다 — 이 기기 Ollama 는 비어 있다
    runner = _platform_runner(tmp_path, "darwin", text_models=text)
    phases = _phases(runner)
    found = _wait(runner, runner.submit(image))
    assert found["state"] == "done" and text.unloaded_calls == []
    assert phases == ["load", "ready"]
    assert found["receipt"]["measured"]["text_models_unloaded"] == []


def test_windows_never_unloads_the_text_model_and_only_announces(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    calls: list = []
    text = _TextModels([{"name": "strata/qwen3.8", "mib": 20000}])  # 꽂혀 있어도 윈도우는 건드리지 않는다(Strata · 다리)
    runner = _platform_runner(tmp_path, "win32", text_models=text, calls=calls)
    phases = _phases(runner)
    found = _wait(runner, runner.submit(image, gpu=1))
    assert found["state"] == "done" and text.unloaded_calls == []
    assert phases == ["load", "ready"]
    assert calls[0][1]["env"]["CUDA_VISIBLE_DEVICES"] == "1"
    measured = found["receipt"]["measured"]
    assert "그래픽카드" in measured["memory_what"] and "unified_memory" not in measured


def test_mac_refuses_when_memory_is_short_but_counts_what_unloading_frees(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    (tmp_path / "a").mkdir()
    short = _platform_runner(tmp_path / "a", "darwin", free=3000, text_models=_TextModels([]))
    with pytest.raises(RuntimeError, match="not_ready: 메모리가 모자라다"):
        short.submit(image)
    # 글 모델 9GB 를 내리면 넉넉하다 → 받는다
    (tmp_path / "b").mkdir()
    text = _TextModels([{"name": "gemma3:12b", "mib": 9000}])
    ok = _platform_runner(tmp_path / "b", "darwin", free=3000, text_models=text, frees=[3000, 12500])
    found = _wait(ok, ok.submit(image))
    assert found["state"] == "done", found
    assert found["receipt"]["measured"]["free_before_mib"] == 12500


def test_mac_stops_before_starting_when_unloading_did_not_free_enough(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    calls: list = []
    text = _TextModels([{"name": "gemma3:12b", "mib": 9000}], keep=("gemma3:12b",))  # 끝내 안 내려간다
    runner = _platform_runner(tmp_path, "darwin", free=3000, text_models=text, calls=calls)
    found = _wait(runner, runner.submit(image))
    assert found["state"] == "failed" and found["error"].startswith("not_enough_memory"), found
    assert calls == [], "실행기를 띄우지 않는다"
    receipt = found["receipt"]
    assert receipt["did"] == "메모리가 모자라 시작하지 않았다" and receipt["measured"]["free_before_mib"] == 3000
    assert any("다 내리지 못했다" in note for note in receipt["not_done"])


def test_mac_blocks_1024_on_a_16gb_machine(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    runner = _platform_runner(tmp_path, "darwin", free=15000, total=16384, text_models=_TextModels([]))
    with pytest.raises(RuntimeError, match="1024 는 이 맥"):
        runner.submit(image, res=1024)
    (tmp_path / "big").mkdir()
    big = _platform_runner(tmp_path / "big", "darwin", free=30000, total=32768, text_models=_TextModels([]))
    assert valid_job_id(big.submit(image, res=1024))


def test_mac_without_its_runner_is_not_ready_even_if_the_windows_exe_is_there(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    bin_dir, models = _ready_dirs(tmp_path)
    (bin_dir / "trellis-cli").unlink()  # 윈도우 판(.exe)만 남았다 — 11-14 맥에 받아진 그것
    runner = Gen3DRunner(tmp_path / "out", bin_dir, models, platform="darwin", free_probe=lambda: 15000,
                         total_probe=lambda: 16384)
    with pytest.raises(RuntimeError, match="not_ready: 이 맥용 실행기"):
        runner.submit(image)


def test_the_mac_dirs_do_not_share_the_windows_runner_folder(tmp_path: Path) -> None:
    config = _Config(tmp_path)
    assert gen3d_dirs(config, "darwin")[0] == tmp_path / "data" / "tools" / "gen3d" / "trellis-cpp-metal"
    assert gen3d_dirs(config, "win32")[0] == tmp_path / "data" / "tools" / "gen3d" / "trellis-cpp"


def test_local_text_models_unload_with_keep_alive_zero_and_wait_until_gone() -> None:
    from alture_jarvis.gen3d.swap import LocalTextModels

    ps = [{"models": [{"name": "gemma3:12b", "size": 9 * 1048576 * 1024}]}] * 2 + [{"models": []}]
    gets, posts = iter(ps), []

    def get(url: str, timeout: float) -> Any:
        assert url == "http://127.0.0.1:11434/api/ps"
        return next(gets, {"models": []})

    def post(url: str, body: dict, timeout: float) -> Any:
        posts.append((url, body))
        return {}

    models = LocalTextModels(get=get, post=post, sleep=lambda _s: None)
    assert models.loaded() == [{"name": "gemma3:12b", "mib": 9216}]
    assert models.unload(["gemma3:12b"]) == []
    assert posts == [("http://127.0.0.1:11434/api/generate", {"model": "gemma3:12b", "keep_alive": 0, "prompt": ""})]
    # Ollama 가 꺼져 있으면 「없다」(지어내지 않고 3D 는 그대로 간다)
    def down(url: str, timeout: float) -> Any:
        raise OSError("refused")

    assert LocalTextModels(get=down, post=post).loaded() == []


def test_the_stage_event_carries_the_swap(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    tools = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(True))
    tools.publish = lambda kind, payload: events.append(payload)
    tools._runner = _platform_runner(tmp_path, "darwin", text_models=_TextModels([{"name": "gemma3:12b", "mib": 9000}]))
    tools._runner.on_change = tools._emit
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    _wait(tools._runner, tools._runner.submit(image))
    phases = [e["swap"]["phase"] for e in events if e.get("swap")]
    assert phases[0] == "unload" and "load" in phases and phases[-1] == "ready"
    first = next(e for e in events if e.get("swap"))
    assert first["swap"]["from"] == "gemma3:12b" and first["swap"]["to"].startswith("TRELLIS.2")
    assert first["swap"]["from_mib"] == 9000 and first["swap"]["expected_mib"] > 0


# ── 폐루프(11-14): 영수증 보고 → 크기 · 프린터 · 방향을 바꿔 다시 준비 ─────────────────────
def test_reprint_writes_a_new_version_and_keeps_the_old(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    runner = _runner(tmp_path)
    job_id = runner.submit(image, export=["glb", "stl"], size_mm=80)
    assert _wait(runner, job_id)["state"] == "done"
    first = runner.reprint(job_id, size_mm=120, orientation="왼쪽으로 눕힘")
    second = runner.reprint(job_id, size_mm=60, detail="fine")
    assert first["version"] == "print_v1" and second["version"] == "print_v2"
    for out, size in ((first, 120), (second, 60)):
        stl = Path(out["files"]["stl"])
        assert stl.is_file() and stl.parent.name == out["version"] and out["size_mm"] == size
        assert (stl.parent / "print.json").is_file()
    assert first["print"]["orientation"] == "왼쪽으로 눕힘" and second["print"]["orientation"] == "지금 그대로"
    assert Path(first["files"]["stl"]).is_file()  # 둘째가 첫째를 지우지 않는다
    # 방향을 정말 돌렸나: 상자(2 × 1 × 0.5)의 긴 변(x)이 「왼쪽으로 눕힘」이면 높이(z)가 된다 — 글자가 아니라 STL 로 본다
    def z_span(path: str) -> float:
        raw = Path(path).read_bytes()
        n = int.from_bytes(raw[80:84], "little")
        tri = np.frombuffer(raw[84:84 + n * 50], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))["v"]
        return float(np.ptp(tri[..., 2]))
    assert z_span(first["files"]["stl"]) > 100 and z_span(second["files"]["stl"]) < 50  # 시험 칸 2mm 라 겉이 부푼다(15 → 32)
    layer = [d for d in second["print"]["plan"]["decisions"] if d["what"] == "layer"][0]
    assert "곱게" in layer["why"] or "작은" in layer["why"]


def test_reprint_refuses_unknown_values_and_unfinished_or_missing_jobs(tmp_path: Path) -> None:
    from alture_jarvis.gen3d.runner import Gen3DError

    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    runner = _runner(tmp_path)
    job_id = runner.submit(image)
    _wait(runner, job_id)
    for bad in ({"printer": "Bambu Lab A1"}, {"detail": "ultra"}, {"orientation": "옆으로"}, {"size_mm": 1000},
                {"export": ["obj"]}):
        with pytest.raises(ValueError):
            runner.reprint(job_id, **bad)
    with pytest.raises(ValueError):
        runner.reprint("g3_20990101_000000_abcdef")
    with pytest.raises(ValueError):
        runner.reprint("../../etc")
    with pytest.raises(ValueError):  # 만들 때도 같은 검사
        runner.submit(image, printer="Bambu Lab A1")
    # GLB 가 사라진 판은 지어내지 않고 거절
    Path(runner.get(job_id)["receipt"]["files"]["glb"]).unlink()
    with pytest.raises(Gen3DError):
        runner.reprint(job_id)


def test_split_plan_split_and_fit_flow(tmp_path: Path) -> None:
    """나눠 뽑기 한 바퀴(실행기): 후보 → 번호로 나누기 → 새 칸 · 부품 · 핀 · 판 3MF · 조립 그림 · 영수증 / 시험 조각 → 틈 저장 → 나누기가 그 틈을 씀."""
    from alture_jarvis.gen3d.runner import Gen3DError

    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    runner = _runner(tmp_path)
    job_id = runner.submit(image, export=["glb"], size_mm=80)
    assert _wait(runner, job_id)["state"] == "done"
    plan = runner.split_plan(job_id, size_mm=80)
    assert plan["version"] == "split_plan_v1" and all(Path(p).is_file() for p in plan["pictures"])
    # 후보가 없으면 번호로는 못 나눈다 — 점 · 방향으로(상자 80 × 40 × 20 의 가운데를 세로로)
    with pytest.raises(ValueError):
        runner.split(job_id, [{"candidate": 99}], size_mm=80)
    with pytest.raises(ValueError):
        runner.split(job_id, [{"candidate": 1}], size_mm=60)  # 다른 크기로 찾은 후보 번호는 안 맞는다
    out = runner.split(job_id, [{"point": [0, 0, 10], "normal": [1, 0, 0], "name": "가운데"}], size_mm=80)
    assert out["version"] == "split_v1" and len(out["parts"]) == 2
    assert all(Path(p).is_file() for p in out["files"]["parts"]) and all(Path(p).is_file() for p in out["files"]["plates"])
    assert (Path(out["files"]["plates"][0]).parent / "split.json").is_file()
    assert out["clearance_mm"] == 0.2 and "안 잼" in out["clearance_from"]
    assert out["assembly_steps"] and out["cuts"][0]["name"] == "가운데"
    # 시험 조각 → 사람이 고른 틈 저장 → 다음 나누기가 그 값을 쓴다
    fit = runner.fit_test()
    assert fit["clearances_mm"] == [0.1, 0.15, 0.2, 0.25, 0.3] and Path(fit["files"]["block_stl"]).is_file()
    runner.fit_set(0.15, note="0.15 꽉")
    again = runner.split(job_id, [{"point": [0, 0, 10], "normal": [1, 0, 0]}], size_mm=80)
    assert again["version"] == "split_v2" and again["clearance_mm"] == 0.15 and "끼움 시험" in again["clearance_from"]
    for pin in again["pins"]:
        assert pin["hole_d_mm"] == pytest.approx(pin["d_mm"] + 0.3)
    with pytest.raises(ValueError):
        runner.fit_set(5)
    with pytest.raises(ValueError):
        runner.split("g3_20990101_000000_abcdef", [{"point": [0, 0, 0]}])
    Path(runner.get(job_id)["receipt"]["files"]["glb"]).unlink()
    with pytest.raises(Gen3DError):
        runner.split(job_id, [{"point": [0, 0, 10], "normal": [1, 0, 0]}], size_mm=80)


def test_six_view_sheet_shows_each_side_the_right_way() -> None:
    """6방향 판(11-15): 길쭉한 상자(x 40 · y 10 · z 20, glTF y 위)를 그렸을 때 칸마다 실루엣 가로 · 세로 비율이 그 방향과 맞다."""
    from PIL import Image

    from alture_jarvis.gen3d.glb import Mesh as GMesh
    from alture_jarvis.gen3d.preview import SIX_VIEWS, view_sheet

    v = np.array([[x, y, z] for x in (0, 40) for y in (0, 10) for z in (0, 20)], dtype=float)
    f = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
                  [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]], dtype=np.int64)
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = view_sheet(GMesh(v, f), Path(d) / "s.png", cell=300)
        img = np.asarray(Image.open(path).convert("L")).astype(int)
    assert img.shape == (600, 900)
    want = {"앞": 40 / 10, "뒤": 40 / 10, "왼쪽": 20 / 10, "오른쪽": 20 / 10, "위": 40 / 20, "아래": 40 / 20}  # 가로 ÷ 세로
    for i, (name, _) in enumerate(SIX_VIEWS):
        x0, y0 = (i % 3) * 300, (i // 3) * 300
        cell = img[y0 + 40:y0 + 299, x0 + 2:x0 + 298]
        ys, xs = np.nonzero(cell < 230)
        ratio = (np.ptp(xs) + 1) / (np.ptp(ys) + 1)
        assert abs(ratio - want[name]) / want[name] < 0.2, (name, ratio)


def test_views_tool_writes_a_sheet_and_a_zoom(tmp_path: Path) -> None:
    image = tmp_path / "ship.png"
    image.write_bytes(b"png")
    runner = _runner(tmp_path)
    job_id = runner.submit(image, export=["glb", "stl"], size_mm=80)
    assert _wait(runner, job_id)["state"] == "done"
    assert Path(runner.get(job_id)["receipt"]["files"]["views"]).is_file()  # 굽기 끝나면 저절로
    sheet = runner.views(job_id)
    assert Path(sheet["file"]).is_file()
    zoom = runner.views(job_id, zoom="아래")
    assert Path(zoom["file"]).name.endswith("_아래.png")
    printed = runner.views(job_id, source="print")
    assert Path(printed["file"]).is_file()
    with pytest.raises(ValueError):
        runner.views(job_id, zoom="옆")
    with pytest.raises(ValueError):
        runner.views(job_id, source="x")


def test_orientation_keeps_the_longest_side_and_sits_on_the_bed() -> None:
    from alture_jarvis.gen3d.print_plan import ORIENTATIONS, orient

    pos = _cube().positions * 10  # 20 × 10 × 5
    for name in ORIENTATIONS:
        out = orient(pos, name)
        span = np.ptp(out, axis=0)
        assert sorted(np.round(span, 6)) == [5.0, 10.0, 20.0], name
        assert abs(out[:, 2].min()) < 1e-9 and np.allclose((out[:, :2].min(0) + out[:, :2].max(0)) / 2, 0), name
    with pytest.raises(ValueError):
        orient(pos, "옆으로")


def test_the_print_tool_goes_through_the_pack_switch(tmp_path: Path) -> None:
    tools = Gen3DTools(_Config(tmp_path), resolve=lambda raw: Path(raw), packs=_Packs(False))
    with pytest.raises(PermissionError):
        tools.gen_3d_print({"job_id": "g3_20261114_000000_abcdef"})
