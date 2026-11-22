"""블렌더 공통 층 1단계 (2026-11-18 · 설계 `설계_블렌더공통층_워크플로우_2026-11-18` §13).

- 찾기 하나: 3D · 애니메이터가 따로 들던 두 벌을 `blender_host.find` 로 합쳤다. 옛 3D 찾기가 놓치던 것(맥 `Blender 4.5.app` ·
  경로 앞쪽 숫자 오독)을 시험으로 박는다.
- GPL 경계: 블렌더 안에서 도는 스크립트(`import bpy`)는 `blender_host/scripts/` 에만 — 결정론으로 막는다(사고 R).
- 옮긴 애니 스크립트는 옮기기 전 글과 바이트가 같다.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from alture_jarvis import config
from alture_jarvis.animator import blender_bridge as bb
from alture_jarvis.blender_host import SCRIPTS
from alture_jarvis.blender_host import find as hf
from alture_jarvis.gen3d import blender as g3

SRC = Path(__file__).resolve().parents[1] / "src" / "alture_jarvis"


@pytest.fixture
def setting(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    values: dict[str, str] = {}
    monkeypatch.setattr(config, "setting", lambda name, default="": values.get(name, default))
    return values


def _mac_app(home: Path, name: str, short: str | None = None) -> Path:
    exe = home / "Applications" / name / "Contents" / "MacOS" / "Blender"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    if short:
        (exe.parent.parent / "Info.plist").write_text(
            f'<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleShortVersionString</key><string>{short}</string></dict></plist>',
            encoding="utf-8")
    return exe


def test_a_mac_app_with_the_version_in_its_name_is_found(tmp_path: Path, setting: dict[str, str]) -> None:
    # 옛 3D 찾기는 `Blender.app` 이름 하나만 봐서 이것을 못 찾았다(애니는 11-13 에 고침) — 이제 둘 다 같은 찾기.
    exe = _mac_app(tmp_path, "Blender 4.5.app")
    got = hf.find((4, 5), platform="darwin", home=tmp_path)
    assert got["found"] and got["exe"] == str(exe) and got["version"] == "4.5"


def test_the_version_comes_from_the_blender_folder_not_from_the_path_in_front(tmp_path: Path, setting: dict[str, str]) -> None:
    # 반례: 앞쪽 작업 폴더 이름의 9.9 를 판으로 읽으면 4.2 블렌더를 4.5 이상으로 착각해 쓴다(옛 3D 찾기의 정규식).
    exe = tmp_path / "blender-9.9-work" / "Blender 4.2" / "blender.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert hf.version_of(exe) == (4, 2, 0)
    setting["JARVIS_BLENDER"] = str(exe)
    low = hf.find((4, 5), platform="linux", home=tmp_path / "nohome")
    assert not low["found"] and "4.2" in low["why"]
    assert hf.find(None, platform="linux", home=tmp_path / "nohome")["exe"] == str(exe)  # 애니는 낮은 판도 그대로 쓴다


def test_the_newest_usable_one_wins_and_unknown_versions_go_last(tmp_path: Path, setting: dict[str, str]) -> None:
    _mac_app(tmp_path, "Blender.app", short="4.5.9")
    newer = _mac_app(tmp_path, "Blender 5.2.app")
    got = hf.find((4, 5), platform="darwin", home=tmp_path)
    assert got["exe"] == str(newer) and got["version_full"] == (5, 2, 0)


def test_the_setting_wins_over_a_newer_install(tmp_path: Path, setting: dict[str, str]) -> None:
    older = _mac_app(tmp_path, "Blender 4.5.app")
    _mac_app(tmp_path, "Blender 5.2.app")
    setting["JARVIS_BLENDER"] = str(older)
    assert hf.find((4, 5), platform="darwin", home=tmp_path)["exe"] == str(older)


def test_too_old_only_is_said_with_the_floor(tmp_path: Path, setting: dict[str, str]) -> None:
    _mac_app(tmp_path, "Blender 3.6.app")
    got = hf.find((4, 5), platform="darwin", home=tmp_path)
    assert not got["found"] and "4.5 미만" in got["why"] and "3.6" in got["why"]
    assert hf.find(None, platform="darwin", home=tmp_path)["found"]  # 애니 쪽(거르지 않음)은 찾는다


def test_the_old_entry_points_keep_their_shapes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, setting: dict[str, str]) -> None:
    exe = _mac_app(tmp_path, "Blender 5.2.app")
    monkeypatch.setattr(hf.sys, "platform", "darwin")
    monkeypatch.setattr(hf.Path, "home", staticmethod(lambda: tmp_path))
    got = g3.find_blender()
    assert set(got) == {"found", "exe", "version", "why"} and got["exe"] == str(exe)
    assert bb.find_blender(platform="darwin", home=tmp_path) == str(exe)
    assert g3.SCRIPTS == SCRIPTS


_BPY = re.compile(r"(?m)^\s*(?:import bpy\b|from bpy\b|import bmesh\b)")


def test_bpy_scripts_live_only_in_the_gpl_folder() -> None:
    """블렌더 API 를 쓰는 스크립트는 배포하면 GPL 호환이어야 한다(blender.org) — 그 폴더 밖 .py 에 `import bpy` 0."""
    outside = [p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py")
               if SCRIPTS not in p.parents and "__pycache__" not in p.parts and _BPY.search(p.read_text(encoding="utf-8"))]
    assert outside == []
    assert (SCRIPTS / "LICENSE").is_file() and "GNU GENERAL PUBLIC LICENSE" in (SCRIPTS / "LICENSE").read_text(encoding="utf-8")


def test_gpl_scripts_never_import_our_code() -> None:
    for script in SCRIPTS.glob("*.py"):
        text = script.read_text(encoding="utf-8")
        assert "alture_jarvis" not in re.sub(r"(?m)#.*$", "", text), script.name


@pytest.mark.parametrize("text, want", [
    ("READ_PY", "50fa91e282d5"),
    ("WRITE_FIX_PY", "d7693c294c31"),
    ("BLOCK_PY", "61dd1d364dda"),
])
def test_moved_animator_scripts_are_byte_identical(text: str, want: str) -> None:
    assert hashlib.sha256(getattr(bb, text).encode("utf-8")).hexdigest()[:12] == want
