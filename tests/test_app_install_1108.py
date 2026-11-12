"""프로그램 들이기 — 서명을 확인한 뒤에만, 사람 승인으로 (2026-11-08 대표 결정 · 게임 시험 2-1)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from alture_jarvis import app_install
from alture_jarvis.permissions import ALWAYS_ASK


def _fake_run(*, notarized: bool = True, broken: bool = False, signer: str = "Unity Technologies ApS (BVPN9UFA9B)"):
    calls: list[list[str]] = []

    def run(args, **_k):
        calls.append(list(args))
        head = args[0]
        if head == "codesign" and "--verify" in args:
            return subprocess.CompletedProcess(args, 1 if broken else 0, "", "invalid signature" if broken else "")
        if head == "spctl":
            source = "Notarized Developer ID" if notarized else "Developer ID"
            ok = notarized and not broken
            return subprocess.CompletedProcess(args, 0 if ok else 3, "", f"{args[-1]}: {'accepted' if ok else 'rejected'}\nsource={source}\n")
        if head == "codesign" and "-dv" in args:
            return subprocess.CompletedProcess(args, 0, "", f"Executable=x\nAuthority=Developer ID Application: {signer}\nAuthority=Apple Root CA\n")
        if head == "ditto":
            Path(args[2]).mkdir(parents=True)
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    return run, calls


def _app(tmp_path: Path, name: str = "Unity Hub.app") -> Path:
    app = tmp_path / name
    (app / "Contents").mkdir(parents=True)
    import plistlib
    with (app / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleShortVersionString": "3.15.2"}, handle)
    return app


def test_notarized_app_is_trusted_and_card_names_signer(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_install, "kind_of", lambda p: "mac_app")
    run, _ = _fake_run()
    card = app_install.describe(_app(tmp_path), run)
    assert card["설치할 것"] == "Unity Hub.app 3.15.2"
    assert card["서명한 곳"].startswith("Unity Technologies") and "애플 공증" in card["서명한 곳"]
    assert card["넣을 자리"] == "/Applications/Unity Hub.app"


@pytest.mark.parametrize("kw", [{"notarized": False}, {"broken": True}, {"signer": ""}])
def test_untrusted_never_reaches_the_card(tmp_path, monkeypatch, kw) -> None:
    monkeypatch.setattr(app_install, "kind_of", lambda p: "mac_app")
    run, _ = _fake_run(**kw)
    with pytest.raises(app_install.InstallerNotTrusted, match="installer_not_trusted"):
        app_install.require_trusted(_app(tmp_path), run)


def test_install_rechecks_then_copies_and_refuses_to_overwrite(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_install, "kind_of", lambda p: "mac_app")
    run, calls = _fake_run()
    applications = tmp_path / "Applications"
    applications.mkdir()
    done = app_install.install(_app(tmp_path), run=run, applications=applications)
    assert done["done"] == "installed" and done["verified"] is True
    assert sum(1 for c in calls if c[0] == "spctl") >= 1, "넣기 직전에 다시 확인한다"
    with pytest.raises(app_install.InstallerNotTrusted, match="already_installed"):
        app_install.install(_app(tmp_path / "again"), run=run, applications=applications)


def test_unknown_kind_is_refused(tmp_path) -> None:
    junk = tmp_path / "setup.zip"
    junk.write_bytes(b"x")
    with pytest.raises(app_install.InstallerNotTrusted, match="installer_kind_unknown"):
        app_install.inspect(junk)


def test_install_is_always_asked() -> None:
    assert "local_install_app" in ALWAYS_ASK
