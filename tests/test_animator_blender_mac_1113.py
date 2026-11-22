"""맥에서 블렌더 찾기 (2026-11-13 맥 조사: `~/Applications/Blender.app` 이 있는데 윈도우 자리만 찾아 「못 찾았다」).

진짜 /Applications 는 보지 않는다 — 시험은 가짜 집 폴더(`home`)의 `Applications` 만 쓴다.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from alture_jarvis.animator import blender_bridge as bb


def _app(root: Path, name: str, version: str | None) -> Path:
    exe = root / "Applications" / name / "Contents" / "MacOS" / "Blender"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    if version:
        with (exe.parent.parent / "Info.plist").open("wb") as fh:
            plistlib.dump({"CFBundleShortVersionString": version}, fh)
    return exe


@pytest.fixture(autouse=True)
def _no_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from alture_jarvis import config

    monkeypatch.setattr(config, "setting", lambda name, default="": default)


def test_mac_finds_blender_in_the_home_applications_folder(tmp_path: Path) -> None:
    exe = _app(tmp_path, "Blender.app", "4.2.3")
    assert bb.find_blender(platform="darwin", home=tmp_path) == str(exe)


def test_mac_picks_the_newer_app_by_its_info_plist(tmp_path: Path) -> None:
    _app(tmp_path, "Blender.app", "3.6.0")
    newer = _app(tmp_path, "Blender 4.5.app", None)  # 이름에 판이 있으면 그것으로
    assert bb.find_blender(platform="darwin", home=tmp_path) == str(newer)
    assert bb._blender_version(str(tmp_path / "Applications" / "Blender.app" / "Contents" / "MacOS" / "Blender")) == (3, 6, 0)


def test_mac_patterns_are_mac_and_windows_patterns_are_windows(tmp_path: Path) -> None:
    mac = bb._blender_patterns("darwin", tmp_path)
    assert "/Applications/Blender*.app/Contents/MacOS/Blender" in mac
    assert not any(p.endswith("blender.exe") for p in mac)
    assert all(p.endswith("blender.exe") for p in bb._blender_patterns("win32", tmp_path))


def test_a_folder_named_like_the_exe_is_not_blender(tmp_path: Path) -> None:
    (tmp_path / "Applications" / "Blender.app" / "Contents" / "MacOS" / "Blender").mkdir(parents=True)
    assert bb.find_blender(platform="darwin", home=tmp_path) is None
