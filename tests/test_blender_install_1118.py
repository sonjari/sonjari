"""블렌더 받기 · 깔기 (2026-11-18 · 설계 `설계_블렌더공통층_워크플로우` §5-1 · G3) — 가짜 서버로(진짜로 0.4GB 를 받지 않는다).

해야 할 것: 동의 없으면 안내문만 / 목록에서 가장 큰 4.5 고침 판 / 공식 지문 줄로 맞춤 / 윈도우는 손자리 자리에 풀고 zip 은 지움 ·
찾기가 그 자리를 찾음 / 맥은 dmg 를 열고 끌어 넣기는 사람에게(next_for_human)
하면 안 되는 것: 지문이 다른 파일을 남김 · 씀 / zip 안 ../ 이름을 풀 자리 밖에 씀 / 다른 운영체제에서 조용히 받음
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.blender_host import find as hf
from alture_jarvis.blender_host import install as bi

INDEX = b'<a href="blender-4.5.7-windows-x64.zip">x</a><a href="blender-4.5.10-windows-x64.zip">x</a><a href="blender-4.5.9-macos-arm64.dmg">x</a>'


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class _Server:
    def __init__(self, payload: bytes, name: str, sha: str | None = None) -> None:
        self.payload, self.name = payload, name
        self.sha = sha or hashlib.sha256(payload).hexdigest()
        self.urls: list[str] = []

    def fetch(self, url: str) -> bytes:
        self.urls.append(url)
        if url == bi.BASE:
            return INDEX
        if url.endswith(".sha256"):
            return f"{'0' * 64}  other-file.zip\n{self.sha}  {self.name}\n".encode()
        raise AssertionError(url)

    def download(self, url: str, dst: Path, progress: Any) -> None:
        self.urls.append(url)
        dst.write_bytes(self.payload)


@pytest.fixture(autouse=True)
def _clean_job() -> None:
    bi._JOB.clear()


@pytest.fixture
def local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    return tmp_path / "Local"


def test_without_agreement_only_the_notice_comes_back() -> None:
    out = bi.install(False, fetch=lambda url: pytest.fail("동의 전에 서버에 갔다"))
    assert out["ok"] is False and "blender.org" in out["notice"] and "GPL" in out["notice"] and "agree=true" in out["next"]


def test_latest_picks_the_highest_patch_not_text_order() -> None:
    assert bi.latest(lambda url: INDEX) == "4.5.10"  # 글자 순서면 4.5.9 가 이긴다


def test_windows_installs_into_the_sonjari_folder_and_find_sees_it(local: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    name = "blender-4.5.10-windows-x64.zip"
    server = _Server(_zip({"blender-4.5.10-windows-x64/blender.exe": b"exe", "blender-4.5.10-windows-x64/4.5/x.txt": b"x"}), name)
    out = bi.install(True, platform="win32", fetch=server.fetch, downloader=server.download, background=False)
    assert out["started"] and bi._JOB["state"] == "done", bi._JOB
    exe = local / "Sonjari" / "blender" / "blender-4.5.10-windows-x64" / "blender.exe"
    assert exe.is_file() and bi._JOB["done"]["exe"] == str(exe)
    assert not list((local / "Sonjari" / "blender").glob("*.zip*"))  # 받은 zip 은 지웠다
    assert server.urls[-1] == bi.BASE + name and all(u.startswith("https://download.blender.org/") for u in server.urls)
    from alture_jarvis import config

    monkeypatch.setattr(config, "setting", lambda name, default="": default)
    import glob

    seen = {Path(p) for pat in hf.patterns("win32", home=local.parent) for p in glob.glob(pat)}
    assert exe in seen and hf.version_of(exe) == (4, 5, 10)  # 찾기가 보는 자리 · 판을 폴더 이름에서 읽는다


def test_a_wrong_fingerprint_is_deleted_and_never_used(local: Path) -> None:
    name = "blender-4.5.10-windows-x64.zip"
    server = _Server(_zip({"blender-4.5.10-windows-x64/blender.exe": b"exe"}), name, sha="f" * 64)
    bi.install(True, platform="win32", fetch=server.fetch, downloader=server.download, background=False)
    assert bi._JOB["state"] == "failed" and "지문이 다르다" in bi._JOB["error"]
    home = local / "Sonjari" / "blender"
    assert not any(home.rglob("blender.exe")) and not any(home.glob("*.zip*"))


def test_a_zip_that_climbs_out_is_refused(local: Path) -> None:
    name = "blender-4.5.10-windows-x64.zip"
    server = _Server(_zip({"../../evil.txt": b"x", "blender-4.5.10-windows-x64/blender.exe": b"exe"}), name)
    bi.install(True, platform="win32", fetch=server.fetch, downloader=server.download, background=False)
    assert bi._JOB["state"] == "failed" and "이상한 경로" in bi._JOB["error"]
    assert not (local / "evil.txt").exists() and not (local.parent / "evil.txt").exists()


def test_mac_opens_the_dmg_and_hands_the_drag_to_the_person(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bi, "download_dir", lambda: tmp_path / "Downloads")
    name = "blender-4.5.10-macos-arm64.dmg"
    server = _Server(b"dmg-bytes", name)
    opened: list[Path] = []
    bi.install(True, platform="darwin", fetch=server.fetch, downloader=server.download, opener=opened.append, background=False)
    assert bi._JOB["state"] == "done" and opened == [tmp_path / "Downloads" / name]
    assert "Applications" in bi._JOB["next_for_human"]


def test_other_systems_are_told_not_silently_downloaded() -> None:
    with pytest.raises(RuntimeError, match="JARVIS_BLENDER"):
        bi.install(True, platform="linux", fetch=lambda url: pytest.fail("받으려 했다"))


def test_the_tool_status_carries_the_notice_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bi, "status", lambda find=None: {"found": False, "downloading": False, "exe": None})
    out = bi.tool({"action": "status"})
    assert out["ok"] and out["notice"] == bi.NOTICE and "agree=true" in out["next"]
    assert bi.tool({"action": "install"})["ok"] is False  # agree 없음 → 안내문만


def test_both_packs_expose_it_under_their_own_names() -> None:
    from alture_jarvis.animator import specs
    from alture_jarvis.gen3d_tools import GEN_3D_BLENDER_TOOL

    assert GEN_3D_BLENDER_TOOL["function"]["name"] == "gen_3d_blender"
    assert specs.BLENDER_SETUP["function"]["name"] == "anim_blender_setup"
