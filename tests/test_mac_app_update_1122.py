"""맥 앱 안 업데이트 — latest.json · 굽기 스크립트 · 화면용 칸 (2026-11-22 · 설계_맥앱안업데이트_2026-11-22.ko.md).

지금까지 굽기는 latest.json 을 안 만들어 앱 꾸러미 갈래가 처음부터 닿을 수 없었다. 타우리는 latest.json 의 판 · 서명 · 절대 주소로
꾸러미를 받고, 화면 앱은 그 서명이 서명된 목록(app.signature)과 글자까지 같을 때만 받는다(mac_update.rs bound_to_manifest).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from alture_jarvis import mac_update

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mac" / "build_mac_update.py"
SIG = "dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZSBmcm9tIHRhdXJpIHNlY3JldCBrZXkK"


def test_latest_json_is_the_shape_tauri_reads() -> None:
    url = mac_update.release_asset_url("v0.4.51-mac", "Sonjari-0.4.51-mac-arm64.app.tar.gz")
    out = mac_update.latest_json("0.4.51", SIG + "\n", url, pub_date="2026-11-23T00:00:00Z")
    assert out == {
        "version": "0.4.51",
        "notes": "",
        "pub_date": "2026-11-23T00:00:00Z",
        "platforms": {"darwin-aarch64": {"signature": SIG, "url": url}},
    }


@pytest.mark.parametrize(("version", "signature", "url"), [
    ("", SIG, "https://github.com/a"),
    ("0.4.51", "", "https://github.com/a"),
    ("0.4.51", SIG, "Sonjari.app.tar.gz"),          # 상대 주소 — 타우리가 못 받는다
    ("0.4.51", SIG, "http://github.com/a"),          # https 아님
])
def test_latest_json_refuses_what_tauri_cannot_use(version: str, signature: str, url: str) -> None:
    with pytest.raises(ValueError):
        mac_update.latest_json(version, signature, url)


def _run(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(tmp_path / "out"), "--seq", "202611230000", *extra],
        capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def test_the_build_script_writes_latest_json_bound_to_the_manifest(tmp_path: Path) -> None:
    sig = tmp_path / "Sonjari-0.4.51-mac-arm64.app.tar.gz.sig"
    sig.write_text(SIG + "\n", encoding="utf-8")
    done = _run(tmp_path, "--app-version", "0.4.51", "--app-sig", str(sig),
                "--app-tarball", "Sonjari-0.4.51-mac-arm64.app.tar.gz", "--release-tag", "v0.4.51-mac")
    assert done.returncode == 0, done.stderr
    out = tmp_path / "out"
    manifest = json.loads((out / mac_update.MANIFEST_NAME).read_text(encoding="utf-8"))
    latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    entry = latest["platforms"]["darwin-aarch64"]
    # 화면 앱이 견주는 두 값 — 글자까지 같아야 받는다.
    assert latest["version"] == manifest["app"]["version"] == "0.4.51"
    assert entry["signature"] == manifest["app"]["signature"] == SIG
    # 꾸러미 · latest.json 주소는 그 태그로 못 박는다.
    assert entry["url"] == "https://github.com/sonjari/sonjari/releases/download/v0.4.51-mac/Sonjari-0.4.51-mac-arm64.app.tar.gz"
    assert manifest["app"]["latest_json"] == "https://github.com/sonjari/sonjari/releases/download/v0.4.51-mac/latest.json"


def test_an_app_without_its_tarball_or_tag_is_refused(tmp_path: Path) -> None:
    sig = tmp_path / "app.sig"
    sig.write_text(SIG, encoding="utf-8")
    done = _run(tmp_path, "--app-version", "0.4.51", "--app-sig", str(sig))
    assert done.returncode != 0 and "--app-tarball" in done.stderr
    assert not (tmp_path / "out" / "latest.json").exists()


def test_python_only_release_writes_no_latest_json(tmp_path: Path) -> None:
    done = _run(tmp_path)
    assert done.returncode == 0, done.stderr
    assert not (tmp_path / "out" / "latest.json").exists()
    assert "app" not in json.loads((tmp_path / "out" / mac_update.MANIFEST_NAME).read_text(encoding="utf-8"))


# ── 화면용 칸(mine · theirs · road) ─────────────────────────────────────────────────────────


def test_an_app_update_is_labelled_with_app_versions() -> None:
    labels = mac_update.screen_labels({
        "app_version": "0.4.50", "mine_build": "aaaaaaaaaaaa",
        "app": {"available": True, "version": "0.4.51"}, "python": {"available": True, "build": "bbbbbbbbbbbb"},
    })
    assert labels == {"mine": "0.4.50", "theirs": "0.4.51", "road": "app"}


def test_a_python_only_update_is_labelled_with_builds() -> None:
    labels = mac_update.screen_labels({
        "app_version": "0.4.50", "mine_build": "aaaaaaaaaaaa",
        "app": {"available": False}, "python": {"available": True, "build": "bbbbbbbbbbbb"},
    })
    assert labels == {"mine": "aaaaaaaa", "theirs": "bbbbbbbb", "road": "python"}


def test_nothing_to_get_has_no_theirs() -> None:
    labels = mac_update.screen_labels({"app_version": "0.4.50", "app": {}, "python": {}})
    assert labels == {"mine": "0.4.50", "theirs": "", "road": ""}
