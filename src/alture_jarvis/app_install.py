"""받은 프로그램을 **서명을 확인한 뒤에만** 사람 승인으로 들인다 (2026-11-08 대표 결정).

★ 게임 시험 2-1: 맥 손자리가 공식 주소에서 Unity Hub(.dmg)를 받아 열었는데, 응용 프로그램 폴더로 옮기는 셸 명령은
  시스템 폴더 규칙에 막혀 사람이 끌어다 놓아야 했다. 대표: 「이것도 AI 가 하게 — 승인 카드로」.
  위험은 모델이 똑똑하냐가 아니라 **엉뚱한 파일을 들이느냐**다. 그래서 모델 크기로 가르지 않고, 기계로 확인할 수 있는 것
  (맥: 코드 서명 + 애플 공증 · 윈도우: Authenticode 서명)을 먼저 보고, 통과한 것만 카드에 올린다.
  카드에는 무엇을(앱 · 판) · 누가 서명했나 · 어디서 받았나를 보인다. 누른 뒤 넣기 직전에 한 번 더 확인한다.

셸로 시스템 · 프로그램 폴더에 쓰는 것은 그대로 막는다 — 들이는 길은 이 하나다.
관리자 암호가 필요한 설치(맥 .pkg · 윈도우 설치 프로그램)는 확인 뒤 **설치 창을 띄우고** 사람이 마친다.
"""
from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

Run = Callable[..., Any]

_MAC_KINDS = {".dmg": "mac_dmg", ".app": "mac_app", ".pkg": "mac_pkg"}
_WIN_KINDS = {".exe": "win_exe", ".msi": "win_msi"}


class InstallerNotTrusted(ValueError):
    pass


def _run(run: Run | None, args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    return (run or subprocess.run)(args, capture_output=True, text=True, timeout=timeout, check=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def kind_of(path: Path) -> str:
    suffix = path.suffix.lower()
    if sys.platform == "darwin":
        return _MAC_KINDS.get(suffix, "")
    if os.name == "nt":
        return _WIN_KINDS.get(suffix, "")
    return ""


def _app_version(app: Path) -> str:
    try:
        with (app / "Contents" / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return ""
    return str(info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or "")


def check_mac_app(app: Path, run: Run | None = None) -> dict[str, Any]:
    """맥 .app — 서명이 온전하고(codesign) 애플이 공증한 Developer ID 인가(spctl). 서명한 곳 이름을 읽는다."""
    verify = _run(run, ["codesign", "--verify", "--deep", "--strict", str(app)])
    assess = _run(run, ["spctl", "--assess", "--type", "execute", "-vv", str(app)])
    detail = _run(run, ["codesign", "-dv", "--verbose=4", str(app)])
    said = f"{assess.stdout}\n{assess.stderr}"
    signer = ""
    for line in f"{detail.stdout}\n{detail.stderr}".splitlines():
        if line.startswith("Authority=Developer ID Application:"):
            signer = line.split(":", 1)[1].strip()
            break
    notarized = "source=Notarized Developer ID" in said
    trusted = verify.returncode == 0 and assess.returncode == 0 and "accepted" in said and notarized and bool(signer)
    reason = "" if trusted else (
        "서명이 깨졌다(codesign)" if verify.returncode != 0
        else "애플 공증을 받은 Developer ID 앱이 아니다(spctl)" if not (assess.returncode == 0 and notarized)
        else "서명한 곳을 읽지 못했다")
    return {"name": app.name, "version": _app_version(app), "signer": signer, "notarized": notarized,
            "trusted": trusted, "reason": reason}


def check_mac_pkg(pkg: Path, run: Run | None = None) -> dict[str, Any]:
    signature = _run(run, ["pkgutil", "--check-signature", str(pkg)])
    assess = _run(run, ["spctl", "--assess", "--type", "install", "-vv", str(pkg)])
    text = signature.stdout + signature.stderr
    signer = ""
    match = re.search(r"1\.\s*Developer ID Installer:\s*(.+)", text)
    if match:
        signer = match.group(1).strip()
    said = assess.stdout + assess.stderr
    notarized = "Notarized" in text or "source=Notarized Developer ID" in said
    trusted = signature.returncode == 0 and assess.returncode == 0 and "accepted" in said and bool(signer)
    return {"name": pkg.name, "version": "", "signer": signer, "notarized": notarized, "trusted": trusted,
            "reason": "" if trusted else "애플이 인정한 Developer ID 설치 꾸러미 서명이 아니다(pkgutil · spctl)"}


def check_windows(installer: Path, run: Run | None = None) -> dict[str, Any]:
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $args[0]; "
              "Write-Output ($s.Status.ToString() + '|' + ($s.SignerCertificate.Subject -as [string]))")
    done = _run(run, ["powershell", "-NoProfile", "-NonInteractive", "-Command", script, str(installer)])
    status, _, subject = (done.stdout or "").strip().partition("|")
    match = re.search(r"CN=\"?([^,\"]+)", subject)
    signer = match.group(1).strip() if match else ""
    trusted = done.returncode == 0 and status.strip() == "Valid" and bool(signer)
    return {"name": installer.name, "version": "", "signer": signer, "notarized": False, "trusted": trusted,
            "reason": "" if trusted else f"윈도우 서명이 유효하지 않다(Authenticode: {status.strip() or '읽지 못함'})"}


def _single_app_in(folder: Path) -> Path:
    apps = [item for item in folder.iterdir() if item.suffix.lower() == ".app" and item.is_dir()]
    if len(apps) != 1:
        raise InstallerNotTrusted(f"installer_unclear: 디스크 이미지 안에 앱이 {len(apps)}개다 — 하나일 때만 들인다.")
    return apps[0]


class _Mounted:
    """맥 .dmg 를 읽기 전용으로 잠깐 붙였다가 뗀다."""

    def __init__(self, dmg: Path, run: Run | None) -> None:
        self.dmg, self.run, self.point = dmg, run, Path(tempfile.mkdtemp(prefix="sonjari-dmg-"))

    def __enter__(self) -> Path:
        done = _run(self.run, ["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen",
                               "-mountpoint", str(self.point), str(self.dmg)], timeout=180)
        if done.returncode != 0:
            raise InstallerNotTrusted(f"dmg_open_failed: 디스크 이미지를 열지 못했다 — {(done.stderr or '').strip()[:200]}")
        return self.point

    def __exit__(self, *exc: Any) -> None:
        _run(self.run, ["hdiutil", "detach", str(self.point), "-quiet"], timeout=60)
        shutil.rmtree(self.point, ignore_errors=True)


def inspect(path: Path, run: Run | None = None) -> dict[str, Any]:
    """설치 파일을 보고 무엇인지 · 누가 서명했나 · 믿을 만한가. 바꾸지 않는다."""
    kind = kind_of(path)
    if not kind:
        raise InstallerNotTrusted(
            "installer_kind_unknown: 이 OS 에서 들일 수 있는 것은 맥 .dmg · .app · .pkg / 윈도우 .exe · .msi 다.")
    if not path.exists():
        raise InstallerNotTrusted(f"installer_missing: {path} 가 없다.")
    if kind == "mac_dmg":
        with _Mounted(path, run) as point:
            found = check_mac_app(_single_app_in(point), run)
    elif kind == "mac_app":
        found = check_mac_app(path, run)
    elif kind == "mac_pkg":
        found = check_mac_pkg(path, run)
    else:
        found = check_windows(path, run)
    return {"kind": kind, "file": str(path), **found}


def require_trusted(path: Path, run: Run | None = None) -> dict[str, Any]:
    found = inspect(path, run)
    if not found["trusted"]:
        raise InstallerNotTrusted(
            f"installer_not_trusted: {found['name']} — {found['reason']}. 들이지 않는다. 공식 사이트의 받는 곳에서 다시 받거나 "
            "사람에게 넘겨라(서명 확인을 건너뛰는 길은 없다).")
    return found


def describe(path: Path, run: Run | None = None) -> dict[str, Any]:
    """승인 카드에 보일 것 — 무엇을(앱 · 판) · 누가 서명했나 · 받은 파일 · 넣을 자리."""
    found = require_trusted(path, run)
    target = (
        f"/Applications/{found['name']}" if found["kind"] in {"mac_dmg", "mac_app"}
        else "맥 설치 창이 뜬다(관리자 암호는 사람이)" if found["kind"] == "mac_pkg"
        else "윈도우 설치 프로그램이 뜬다(관리자 확인은 사람이)"
    )
    return {"설치할 것": found["name"] + (f" {found['version']}" if found["version"] else ""),
            "서명한 곳": found["signer"] + (" · 애플 공증" if found["notarized"] else ""),
            "받은 파일": found["file"], "넣을 자리": target}


def install(path: Path, *, run: Run | None = None, popen: Callable[..., Any] | None = None,
            applications: Path = Path("/Applications")) -> dict[str, Any]:
    """승인 뒤 — 넣기 **직전에 다시** 확인하고 들인다."""
    found = require_trusted(path, run)
    kind = found["kind"]
    if kind in {"mac_dmg", "mac_app"}:
        target = applications / found["name"]
        if target.exists():
            raise InstallerNotTrusted(f"already_installed: {target} 가 이미 있다 — 덮어쓰지 않는다. 바꾸려면 사람이 먼저 지운다.")
        if kind == "mac_dmg":
            with _Mounted(path, run) as point:
                source = _single_app_in(point)
                again = check_mac_app(source, run)
                if not again["trusted"]:
                    raise InstallerNotTrusted(f"installer_not_trusted: {again['reason']}")
                copied = _run(run, ["ditto", str(source), str(target)], timeout=600)
        else:
            copied = _run(run, ["ditto", str(path), str(target)], timeout=600)
        if copied.returncode != 0:
            raise OSError(f"install_copy_failed: {(copied.stderr or '').strip()[:200]}")
        return {**found, "installed_to": str(target), "verified": target.exists(), "done": "installed"}
    launcher = popen or subprocess.Popen
    if kind == "mac_pkg":
        launcher(["open", str(path)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606 — 서명 확인을 지난 설치 프로그램 하나
    return {**found, "installed_to": "", "verified": False, "done": "installer_opened",
            "instruction": "설치 창을 띄웠다. 관리자 확인 · 암호는 사람이 한다 — 끝난 것을 확인하기 전에는 「설치했다」고 말하지 마라."}
