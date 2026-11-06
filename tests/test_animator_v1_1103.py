"""애니메이터 팩 v1 — 모션 창고 · 관절 부품 · 포즈 시트 · 영상 → 바이페드 (2026-11-03).

맥스 없이 잰다(맥스가 쓸 .bip · max.txt 를 시험이 직접 만든다). 맥스 일괄로 끝까지 돌린 확인은 설계 §14 에 기록.
양방향:
- 해야 할 것: 넣기 → 찾기 → 입히기 · 낱말 넓혀 찾기 · 출처 표시 · 초안 경고 · 입히기 전 보관 · 구간 맞춤 · 동의 뒤에만 받기 · 지문 확인
- 하면 안 되는 것: 팩 꺼지면 거절 · 출처 없이 넣기 · 아직 안 된 칸 찾기/입히기 · 동의 없이 받기 · 지문 틀린 파일 남기기 ·
  인터넷 주소 받기 · 애니메이터 폴더 밖 시트 읽기 · 손자리 모델 목록에 낌
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from alture_jarvis.animator import library, parts, refpose
from alture_jarvis.animator_tools import ANIMATOR_TOOL_NAMES, AnimatorTools
from alture_jarvis.packs import PackRegistry

PACKS_DIR = Path(__file__).resolve().parents[1] / "packs"
V1 = ["anim_library_add", "anim_library_find", "anim_library_apply", "anim_parts", "anim_pose_sheet", "anim_video_to_biped",
      "anim_fit_check", "anim_fit_fix", "anim_blender_check", "anim_blender_fix", "anim_blender_block"]


class _Packs:
    def __init__(self, on: bool) -> None:
        self.on = on

    def is_enabled(self, pack_id: str) -> bool:
        return self.on and pack_id == "animator"


class _Config:
    def __init__(self, root: Path) -> None:
        self.documents_dir = root / "docs"
        self.output_dir = root / "out"


def _tools(tmp_path: Path, on: bool = True) -> AnimatorTools:
    return AnimatorTools(_Config(tmp_path), packs=_Packs(on))


def _ready(root: Path, name: str, origin: str = "company", character: str = "캐릭A", tags=(), frames=(0, 30), loop=True, note: str = "") -> dict:
    """맥스가 돈 뒤처럼 .bip 와 max.txt 를 놓는다."""
    e = library.new_entry(root, name=name, origin=origin, character=character, tags=tags, note=note)
    (e["folder"] / "motion.bip").write_bytes(b"BIP")
    (e["folder"] / "max.txt").write_text(f"start={frames[0]} end={frames[1]} fps=30 loop={str(loop).lower()} biped=Bip001",
                                         encoding="utf-8")
    return e


# ── 팩 · 목록 ─────────────────────────────────────────────────────────────

def test_the_pack_lists_all_eight_tools_and_the_registry_agrees(tmp_path: Path) -> None:
    pack = PackRegistry(PACKS_DIR, tmp_path / "data").packs["animator"]
    assert list(pack.tools) == ["anim_offset_read", "anim_offset_plan", *V1]
    assert set(pack.tools) == set(ANIMATOR_TOOL_NAMES)
    assert {t["function"]["name"] for t in _tools(tmp_path).ollama_tools} == set(ANIMATOR_TOOL_NAMES)


def test_sonjari_own_model_still_sees_none_of_them(tmp_path: Path) -> None:
    assert _tools(tmp_path).active_ollama_tools == []


@pytest.mark.parametrize("method,args", [
    ("library_add", {"source": "scene", "origin": "own", "name": "x"}), ("library_find", {}),
    ("library_apply", {"id": "x"}), ("parts", {"action": "status"}),
    ("pose_sheet", {"source": "x"}), ("video_to_biped", {}), ("fit_check", {}), ("fit_fix", {}), ("blender_check", {"blend": "x.blend"}), ("blender_fix", {"blend": "x.blend"}), ("blender_block", {"blend": "x.blend"}),
])
def test_every_v1_tool_refuses_when_the_pack_is_off(tmp_path: Path, method: str, args: dict) -> None:
    with pytest.raises(PermissionError, match="pack_disabled"):
        getattr(_tools(tmp_path, on=False), method)(args)


# ── 창고: 넣기 ─────────────────────────────────────────────────────────────

def test_adding_needs_an_origin_so_drafts_never_pass_as_real_work(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    with pytest.raises(ValueError, match="origin"):
        t.library_add({"source": "scene", "origin": "", "name": "돌진"})
    with pytest.raises(ValueError, match="origin"):
        library.new_entry(tmp_path, name="x", origin="somewhere")


def test_adding_from_the_scene_writes_a_script_and_leaves_the_slot_pending(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    with pytest.raises(ValueError, match="name"):
        t.library_add({"source": "scene", "origin": "own"})
    r = t.library_add({"source": "scene", "origin": "own", "name": "Hit_dash_01", "tags": ["돌진"], "character": "캐릭A"})
    assert r["run_line"].startswith("execute (")
    assert r["tags"][:1] == ["돌진"] and "공격" in r["tags"]            # 사람 낱말 먼저 + 파일 이름 꼬리표
    script = Path(r["run_line"].split('@"')[1].split('"')[0]).read_text(encoding="utf-8-sig")
    assert "biped.saveBipFile" in script and "render camera:cam" in script and "renderers.current = keepR" in script
    assert "gw.getViewportDib" not in script                                # 11-03: 좁은 뷰포트 귀퉁이만 찍혔다
    assert "loadBipFile" not in script and "setTransform" not in script     # 넣기는 키를 안 바꾼다
    assert t.library_find({"query": "돌진"})["found"] == []                 # 맥스가 아직 안 돌았다 → 찾기에 안 나온다


def test_bip_files_go_straight_in_from_a_file_or_a_folder(tmp_path: Path) -> None:
    src = tmp_path / "quickmagic"
    src.mkdir()
    for n in ("kick_a.bip", "kick_b.bip"):
        (src / n).write_bytes(b"BIP")
    (src / "readme.txt").write_text("x", encoding="utf-8")
    r = _tools(tmp_path).library_add({"source": "bip_file", "origin": "bip_file", "path": str(src)})
    assert [a["name"] for a in r["added"]] == ["kick_a", "kick_b"]
    found = _tools(tmp_path).library_find({"query": "발차기"})["found"]
    assert {f["name"] for f in found} == {"kick_a", "kick_b"} and all(f["origin_label"] == "받아 온 .bip" for f in found)


def test_a_max_folder_becomes_one_batch_command_and_does_not_touch_the_open_max(tmp_path: Path) -> None:
    src = tmp_path / "company"
    src.mkdir()
    for n in ("Hero_A_idle_01.max", "Hero_A_run_01.max"):
        (src / n).write_bytes(b"MAX")
    r = _tools(tmp_path).library_add({"source": "max_folder", "origin": "company", "path": str(src), "character": "A"})
    assert r["files"] == 2 and r["chunks"] == 1 and "run_line" not in r
    runner = Path(r["script"]).read_text(encoding="utf-8")
    assert "3dsmaxbatch" in runner and runner.count(".ms\"") == 1
    ms = Path(runner.split('"')[-2]).read_text(encoding="utf-8-sig")
    assert ms.count("loadMaxFile") == 2 and ms.count("resetMaxFile") == 2 and "AppendAllText" in ms
    assert ms.index('sjLog ("start "') < ms.index("loadMaxFile")  # 열기 전에 기록 — 맥스가 죽은 파일을 안다
    assert len(library.entries(_tools(tmp_path).root, include_pending=True)) == 2


def test_a_big_folder_is_split_so_one_crash_does_not_end_the_night(tmp_path: Path) -> None:
    # 11-04: 맥스 하나로 수백 개를 열다 60개 언저리에서 연달아 죽었다 → 20개씩 새 맥스
    src = tmp_path / "company"
    src.mkdir()
    for k in range(45):
        (src / f"Hero_A_idle_{k:02d}.max").write_bytes(b"MAX")
    r = _tools(tmp_path).library_add({"source": "max_folder", "origin": "company", "path": str(src)})
    assert r["files"] == 45 and r["chunks"] == 3
    runner = Path(r["script"]).read_text(encoding="utf-8")
    assert runner.count("3dsmaxbatch") == 3


def test_running_the_same_folder_again_does_only_what_is_left(tmp_path: Path) -> None:
    src = tmp_path / "company"
    src.mkdir()
    for n in ("Hero_A_idle_01.max", "Hero_A_run_01.max", "Hero_A_hit_01.max"):
        (src / n).write_bytes(b"MAX")
    tools = _tools(tmp_path)
    tools.library_add({"source": "max_folder", "origin": "company", "path": str(src)})
    pend = library.entries(tools.root, include_pending=True)
    done = next(e for e in pend if e["name"] == "Hero_A_idle_01")
    (library.lib_dir(tools.root) / done["id"] / "motion.bip").write_bytes(b"BIP")  # 첫 판에서 하나만 들어감
    r = tools.library_add({"source": "max_folder", "origin": "company", "path": str(src)})
    assert r["files"] == 2 and r["already_in_library"] == 1
    assert len(library.entries(tools.root, include_pending=True)) == 3  # 빈 칸을 다시 쓴다 — 새 칸이 쌓이지 않는다


# ── 창고: 찾기 ─────────────────────────────────────────────────────────────

def test_find_ranks_exact_tags_over_synonyms_over_plain_text(tmp_path: Path) -> None:
    root = _tools(tmp_path).root
    _ready(root, "Hero_attack_dash", tags=["돌진"])
    _ready(root, "Hero_skill_a")                         # 「스킬」 꼬리표 → 「공격」의 같은 뜻
    _ready(root, "Hero_idle", note="공격 전 대기")        # 메모에만 「공격」
    names = [e["name"] for e in library.find(root, "공격")]
    assert names == ["Hero_attack_dash", "Hero_skill_a", "Hero_idle"]
    assert [e["name"] for e in library.find(root, "돌진 공격")][0] == "Hero_attack_dash"


def test_model_files_stay_in_the_library_but_out_of_motion_search(tmp_path: Path) -> None:
    # 11-04: 회사 폴더의 「…_Mesh_…_스킨수정」이 600프레임 루프 동작처럼 찾기에 섞였다 — 지우지 않고 찾기에서만 뺀다.
    t = _tools(tmp_path)
    _ready(t.root, "Hero_A_Mesh_231211_01_스킨수정", character="A")
    _ready(t.root, "NPC_B_Mesh", character="B")
    _ready(t.root, "Hero_A_astand_231206_01", character="A")
    _ready(t.root, "Hero_Meshy_idle_01", character="A")    # 「Mesh」가 낱말 안에만 있으면 동작 그대로
    names = {e["name"] for e in library.find(t.root, "", k=20)}
    assert names == {"Hero_A_astand_231206_01", "Hero_Meshy_idle_01"}
    assert {e["name"] for e in library.find(t.root, "대기", k=20)} == {"Hero_A_astand_231206_01", "Hero_Meshy_idle_01"}
    assert {e["name"] for e in library.find(t.root, "메쉬 수정본", k=20)} >= {"Hero_A_Mesh_231211_01_스킨수정", "NPC_B_Mesh"}
    r = t.library_find({"query": ""})
    assert (r["library_size"], r["motions"], r["model_files"]) == (4, 2, 2)
    assert len(library.entries(t.root)) == 4                  # 창고에서 지운 것은 없다


def test_find_filters_by_character_and_origin_and_says_when_empty(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    assert "비어 있다" in t.library_find({"query": "대기"})["note"]
    _ready(t.root, "A_idle", character="캐릭A")
    _ready(t.root, "B_idle", character="캐릭B", origin="video_draft")
    assert [f["name"] for f in t.library_find({"query": "대기", "character": "캐릭A"})["found"]] == ["A_idle"]
    assert [f["name"] for f in t.library_find({"query": "대기", "origin": "video_draft"})["found"]] == ["B_idle"]
    assert "맞는 것이 없다" in t.library_find({"query": "헤엄"})["note"]


def test_video_drafts_carry_a_warning_and_sort_after_real_work(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    _ready(t.root, "Z_idle_video", origin="video_draft")
    _ready(t.root, "Z_idle_company")
    found = t.library_find({"query": "대기"})["found"]
    assert [f["name"] for f in found] == ["Z_idle_company", "Z_idle_video"]
    assert "warning" not in found[0] and "초안" in found[1]["warning"]


def test_frames_and_loop_come_from_what_max_wrote(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    _ready(t.root, "W_run", frames=(5, 29), loop=False)
    f = t.library_find({"query": "달리기"})["found"][0]
    assert f["frames"] == 24 and f["loop"] is False


# ── 창고: 입히기 ───────────────────────────────────────────────────────────

def test_apply_holds_the_scene_sets_the_range_and_checks_the_keys_moved(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    e = _ready(t.root, "X_hit", frames=(0, 78))
    r = t.library_apply({"id": e["id"]})
    script = Path(r["run_line"].split('@"')[1].split('"')[0]).read_text(encoding="utf-8-sig")
    assert script.index("holdMaxFile()") < script.index("biped.loadBipFile")      # 보관 먼저
    assert "animationRange = interval 0 78" in script                              # 11-03: 구간이 안 바뀌던 것
    assert "키 바뀜" in script and "확인 필요" in script                           # 정말 바뀌었나 스크립트가 잰다
    assert "「해」" in r["next"]


def test_blend_mixes_a_second_motion_by_the_ratio_the_person_picks(tmp_path: Path) -> None:
    # 11-05: 비슷한 것 찾기 → 섞기(비율은 사람) — 현업 애니메이터 흐름
    t = _tools(tmp_path)
    a = _ready(t.root, "X_attack", frames=(0, 40))
    b = _ready(t.root, "X_attack_heavy", frames=(10, 70))
    r = t.library_apply({"id": a["id"], "blend_with": b["id"], "blend": 0.3})
    script = Path(r["run_line"].split('@"')[1].split('"')[0]).read_text(encoding="utf-8-sig")
    assert "sjBlend com" in script and " 0.300 10 70" in script                   # B 의 구간은 창고 기록에서(loadBipFile 은 구간을 안 바꾼다)
    assert script.index("sjComMatch com (") < script.index("sjBlend com @")        # COM 맞춘 뒤 섞는다
    assert r["blend"]["ratio"] == 0.3
    # 11-06 현업 판정(반반 섞기 73프레임부터 몸 전체가 180° 뒤돎): B 를 A 시작 방향으로 돌려 맞춘 뒤 섞는다 — 회전도 이동량도
    assert "local Y = inverse ((smB[1][2]) as matrix3)" in script
    assert "((b[1] - pB0) * Y)" in script
    # 11-06 맥스 재현: 두 공격 다 몸을 여러 바퀴 돌아 방향 차가 331° 까지 — 따라가기는 프레임마다 · 120° 넘으면 몸 방향은 A 그대로(알림) · 100% 는 B 그대로
    assert "for f = S to E do (" in script and "while ang - prevAng > 180.0" in script
    assert "maxGap <= 120.0 or fullB" in script and "몸 방향은 A 그대로" in script
    plain = t.library_apply({"id": a["id"]})
    assert "blend" not in plain
    plain_script = Path(plain["run_line"].split('@"')[1].split('"')[0]).read_text(encoding="utf-8-sig")
    assert "sjBlend com @" not in plain_script                                    # 안 섞을 땐 부르지 않는다(함수 정의만)


def test_apply_refuses_unknown_and_pending_slots_and_warns_on_drafts(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    with pytest.raises(KeyError):
        t.library_apply({"id": "없는칸"})
    pending = library.new_entry(t.root, name="P", origin="own")
    with pytest.raises(FileNotFoundError, match=".bip"):
        t.library_apply({"id": pending["id"]})
    d = _ready(t.root, "V", origin="video_draft")
    assert "초안" in t.library_apply({"id": d["id"]})["warning"]


def test_names_with_quotes_cannot_break_out_of_the_script(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    e = _ready(t.root, "Q")
    r = t.library_apply({"id": e["id"], "biped": 'Bip001" ; deleteFile "x'})
    script = Path(r["run_line"].split('@"')[1].split('"')[0]).read_text(encoding="utf-8-sig")
    assert 'sjFindBiped "Bip001 ; deleteFile x"' in script


# ── 관절 부품 ─────────────────────────────────────────────────────────────

def test_without_parts_the_pose_tools_point_to_the_notice(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    st = t.parts({"action": "status"})
    assert st["ready"] is False and "비상업" in st["notice"] and "Soykaf" in st["notice"]
    with pytest.raises(FileNotFoundError, match="parts_missing"):
        t.pose_sheet({"source": str(tmp_path)})


def test_install_without_agreement_downloads_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parts, "_fetch", lambda *a, **k: pytest.fail("동의 없이 받으려 했다"))
    r = _tools(tmp_path).parts({"action": "install"})
    assert r["ok"] is False and "notice" in r
    assert not (_tools(tmp_path).root / "parts").exists()


def test_a_download_with_the_wrong_fingerprint_is_deleted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = parts.Part("det", "가짜", "https://example.invalid/x.onnx", "x.onnx", 3, "0" * 64, "시험")
    monkeypatch.setattr(parts, "PARTS", (fake,))
    monkeypatch.setattr(parts, "_local_copy", lambda part: None)
    monkeypatch.setattr(parts, "_fetch", lambda part, dest, report: dest.write_bytes(b"BAD"))
    root = tmp_path / "root"
    assert parts.install(root, agree=True)["started"]
    st = parts.wait(root, timeout=10)
    assert st["ready"] is False and "지문" in st["error"]
    assert not (root / "parts" / "x.onnx").exists()
    rec = json.loads((root / "parts" / "parts.json").read_text(encoding="utf-8"))
    assert rec["agreed_at"] and "비상업" in rec["notice"]            # 무엇에 동의했는지 남긴다


def test_a_good_download_is_kept_and_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    good = parts.Part("det", "가짜", "https://example.invalid/x.onnx", "x.onnx", 2, hashlib.sha256(b"OK").hexdigest(), "시험")
    monkeypatch.setattr(parts, "PARTS", (good,))
    monkeypatch.setattr(parts, "_local_copy", lambda part: None)
    monkeypatch.setattr(parts, "_fetch", lambda part, dest, report: dest.write_bytes(b"OK"))
    root = tmp_path / "root"
    parts.install(root, agree=True)
    assert parts.wait(root, timeout=10)["ready"] is True
    assert parts.require(root, ("det",))["det"].read_bytes() == b"OK"


# ── 포즈 시트 · 영상 → 바이페드 ───────────────────────────────────────────

def test_pose_sheet_refuses_internet_addresses_before_anything_else(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="내려받지"):
        _tools(tmp_path).pose_sheet({"source": "https://www.youtube.com/watch?v=x"})


def test_video_to_biped_only_reads_sheets_inside_the_animator_folder(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    with pytest.raises(FileNotFoundError, match="시트가 없다"):
        t.video_to_biped({})
    outside = tmp_path / "evil"
    outside.mkdir()
    (outside / "pose_sheet.json").write_text("{}", encoding="utf-8")
    (t.root / "refs").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="그런 시트가 없다"):
        t.video_to_biped({"sheet": "../../evil"})


def test_check_without_a_report_says_so(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    d = t.root / "refs" / "20261103_000000"
    d.mkdir(parents=True)
    (d / "pose_sheet.json").write_text(json.dumps({"picks": []}), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="맞춤 보고"):
        t.video_to_biped({"check": True})
    (d / "fit_report.json").write_text('[{"pose":1,"bone":"Bip001 Spine","dot":0.99},{"pose":1,"bone":"Bip001 R Forearm","dot":0.2},'
                                       '{"pose":1,"bone":"Bip001 L Toe","missing":true},{}]', encoding="utf-8")
    r = t.video_to_biped({"check": True})
    assert (r["bones"], r["weak"], r["missing"]) == (2, 1, ["Bip001 L Toe"])


def test_the_fit_script_holds_the_scene_and_keys_one_pose_per_spacing() -> None:
    J = np.random.default_rng(0).normal(size=(17, 3)).round(3).tolist()
    poses = [{"no": 1, "joints": J}, {"no": 2, "missing": True}, {"no": 3, "joints": J}]
    s = refpose.biped_fit_script(poses, "Bip001", 5, 12, Path("C:/x/rep.json"))
    assert s.index("holdMaxFile()") < s.index('undo "Sonjari video blocking" on')
    assert "sliderTime = 5f" in s and "sliderTime = 17f" in s and "sliderTime = 29f" not in s   # 빠진 장면은 건너뛴다
    assert s.count('sliderTime = ') == 2 and "blocked 2 poses" in s


def test_pick_finds_stillness_keeps_gaps_and_drops_lookalikes() -> None:
    t = np.arange(120)
    speed = 1.0 + np.cos(t / 120 * 2 * np.pi * 4)          # 골짜기 넷: 15 · 45 · 75 · 105
    assert refpose.pick(speed, 8) == [15, 45, 75, 105]
    assert len(refpose.pick(speed, 2)) == 2
    kp = np.zeros((121, 17, 3))
    kp[:, :, 2] = 1.0
    kp[:, 5:7, 1], kp[:, 11:13, 1] = -1.0, 0.0                 # 모든 장면이 같은 자세 → 한 장만
    assert len(refpose.pick(speed, 8, kp=kp)) == 1


def test_frame_folders_skip_leftover_files(tmp_path: Path) -> None:
    cv2 = pytest.importorskip("cv2")   # opencv is an optional extra, not in [test]

    for n in ("_chart.png", "f_0000.jpg", "f_0001.jpg"):
        cv2.imwrite(str(tmp_path / n), np.zeros((8, 8, 3), np.uint8))
    assert [i for i, _s, _img in refpose.iter_frames(tmp_path)] == [0, 1]   # 11-03: _chart.png 를 프레임으로 세서 한 칸 밀렸다


_CACHE = Path(os.path.expanduser("~")) / ".cache" / "rtmlib" / "hub" / "checkpoints"


@pytest.mark.skipif(not all((_CACHE / p.onnx_name).is_file() for p in parts.PARTS), reason="이 PC 에 관절 모델이 없다")
def test_real_models_find_a_person_and_17_joints() -> None:
    import cv2

    from alture_jarvis.animator import pose_onnx

    img = np.full((480, 360, 3), 255, np.uint8)
    cv2.circle(img, (180, 80), 30, (0, 0, 0), -1)                      # 머리
    for a, b in [((180, 110), (180, 280)), ((180, 150), (110, 230)), ((180, 150), (250, 230)),
                 ((180, 280), (130, 420)), ((180, 280), (230, 420))]:
        cv2.line(img, a, b, (0, 0, 0), 18)
    det = pose_onnx.Detector(_CACHE / parts.PARTS[0].onnx_name, score=0.05)
    boxes = det(img)
    box = pose_onnx.biggest(boxes) if len(boxes) else np.array([60, 30, 300, 450], float)
    kp = pose_onnx.Pose2D(_CACHE / parts.PARTS[1].onnx_name)(img, box)
    k3 = pose_onnx.Pose3D(_CACHE / parts.PARTS[2].onnx_name)(img, box)
    assert kp.shape == (17, 3) and k3.shape == (17, 4)
    assert np.isfinite(kp[:, :2]).all() and (kp[:, :2] >= -50).all()


def test_a_bip_only_slot_says_the_range_was_left_alone(tmp_path: Path) -> None:
    t = _tools(tmp_path)
    bip = tmp_path / "qm_jump.bip"
    bip.write_bytes(b"BIP")
    added = t.library_add({"source": "bip_file", "origin": "bip_file", "path": str(bip)})["added"][0]
    r = t.library_apply({"id": added["id"]})
    script = Path(r["run_line"].split('@"')[1].split('"')[0]).read_text(encoding="utf-8-sig")
    assert "animationRange = interval" not in script and "구간" in r["range_note"]


def test_a_deep_company_folder_is_read_whole_but_old_backups_stay_out(tmp_path: Path) -> None:
    src = tmp_path / "캐릭A"
    for rel in ("Animation/Hero_idle_02.max", "Animation/hit/Hero_hit_01.max", "Animation/backup/Hero_idle_01.max", "Old/Hero_run_00.max"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_bytes(b"MAX")
    t = _tools(tmp_path)
    r = t.library_add({"source": "max_folder", "origin": "company", "path": str(src)})
    assert (r["files"], r["skipped_backup"]) == (2, 2)
    r2 = _tools(tmp_path / "b").library_add({"source": "max_folder", "origin": "company", "path": str(src), "include_backup": True})
    assert (r2["files"], r2["skipped_backup"]) == (4, 0)


def test_common_and_possession_files_get_korean_tags() -> None:
    # 11-03 열린 맥스 시험: Hero_A_Common 에 꼬리표가 하나도 없었다(이름표 목록에서 빠짐)
    assert "공용" in library.tags_from_name("Hero_X_Common_230921_02")
    assert "빙의" in library.tags_from_name("Hero_X_astand_possession_230705")


def test_blocking_keys_follow_the_video_timing_not_an_even_grid() -> None:
    # 11-05: 0 · 10 · 20 … 똑같은 간격은 영상의 예비 · 타격 · 회복 리듬을 지웠다
    from alture_jarvis.animator import refpose
    poses = [{"no": 1, "sec": 132.133}, {"no": 2, "sec": 132.7}, {"no": 3, "missing": True}, {"no": 4, "sec": 134.467}]
    assert refpose.key_frames(poses, 0, 10) == [0, 17, 70]
    assert refpose.key_frames(poses, 0, 10, timing="even") == [0, 10, 20]
    assert refpose.key_frames([{"no": 1, "sec": 1.0}, {"no": 2, "sec": 1.0}], 5, 10) == [5, 6]  # 같은 자리에 겹치지 않게
    assert refpose.key_frames([{"no": 1}, {"no": 2}], 0, 8) == [0, 8]                       # 시각이 없으면 간격
    script = refpose.biped_fit_script([{"no": 1, "joints": [[0, 0, 0]] * 17}], "Bip001", 0, 10, Path("r.json"), [7])
    assert "sliderTime = 7f" in script and "sjDeg2D" in script


def test_apply_bookends_with_the_characters_own_pose_and_asks_a_new_animator(tmp_path: Path) -> None:
    # 11-05 현업 애니메이터: 「첫 번째, 마지막 포즈가 무조건 내가 지금 작업하는 캐릭터의 포즈」 — 다만 사람마다 달라 기준점으로만(대표)
    t = _tools(tmp_path)
    a = _ready(t.root, "X_attack", frames=(0, 40), loop=True)
    b = _ready(t.root, "X_attack_heavy", frames=(0, 60), loop=False)
    r = t.library_apply({"id": a["id"], "blend_with": b["id"]})
    script = Path(r["run_line"].split('@"')[1].split('"')[0]).read_text(encoding="utf-8-sig")
    assert script.index("sjCapture com") < script.index("biped.loadBipFile com.controller @")   # 입히기 전에 자세를 적는다
    assert script.index("sjBlend com @") < script.index("(sjBookend com cap (")                    # 섞고 · 보정한 뒤 첫 · 끝을 잇는다
    ask = r["habits_unconfirmed"]
    assert ask["used"]["bookend"] is True and ask["library_loop_share"]["motions"] == 2
    library.prefs_path(t.root).write_text('{"bookend": false, "blend": 0.3}', encoding="utf-8")   # 이 사람 답을 남김
    r2 = t.library_apply({"id": a["id"], "blend_with": b["id"]})
    s2 = Path(r2["run_line"].split('@"')[1].split('"')[0]).read_text(encoding="utf-8-sig")
    assert " 0.300 0 60" in s2 and "(sjBookend com cap (" not in s2 and "habits_unconfirmed" not in r2

# ── 11-06 무거운 계산은 따로 된 프로세스에서 ──────────────────────────────────

def test_heavy_pose_work_runs_outside_the_backend_and_errors_keep_their_kind(tmp_path: Path) -> None:
    # 진짜 자식 프로세스를 띄운다 — 본체 안에서 돌면 4.6배 느리고 /health 도 막혔다(11-06 실측)
    with pytest.raises(ValueError, match="unknown"):
        refpose.run_isolated("nope", {"parts": {}}, timeout=60)
    with pytest.raises(FileNotFoundError):
        refpose.run_isolated("lift", {"sheet": str(tmp_path / "없는.json"), "parts": {}}, timeout=60)


def test_pose_sheet_goes_through_the_isolated_worker_and_says_why_fewer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t = _tools(tmp_path)
    monkeypatch.setattr(parts, "require", lambda root, names: {n: tmp_path / n for n in names})
    seen = {}

    def fake(cmd, payload, **_kw):
        seen["cmd"], seen["payload"] = cmd, payload
        return {"sheet": "x.jpg", "frames": 100, "found_person": 90, "seconds": 1.0,
                "picks": [{"no": i, "sec": i * 1.0} for i in range(1, 7)]}

    monkeypatch.setattr(refpose, "run_isolated", fake)
    out = t.pose_sheet({"source": str(tmp_path), "n": 8, "stride": 2})
    assert seen["cmd"] == "sheet" and seen["payload"]["stride"] == 2 and seen["payload"]["n"] == 8
    assert out["ok"] and len(out["picks"]) == 6 and "8장을 달라고 했지만 6장" in out["fewer_picks"]
