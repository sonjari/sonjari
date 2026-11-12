"""깃허브 연결 1단계(2026-11-12 · 설계 docs/설계_깃허브연결_2026-11-12.ko.md) — 네트워크 · 진짜 gh 없이."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

from alture_jarvis.github_link import (
    GH_RELEASE_API, MAC_TEAM_ID, GithubLink, parse_login_prompt, parse_status, pick_asset,
)

# 11-12 PC 실측(gh 2.92 · 표준 입력이 터미널 아님)에서 코드만 바꾼 원문.
REAL_PROMPT = ("\n! First copy your one-time code: AB12-CD34\n"
               "Open this URL to continue in your web browser: https://github.com/login/device\n")
REAL_STATUS_KEYRING = ("github.com\n  ✓ Logged in to github.com account someone (keyring)\n"
                       "  - Active account: true\n  - Token: gho_************************************\n")
REAL_STATUS_FILE = "github.com\n  ✓ Logged in to github.com account someone (/Users/x/.config/gh/hosts.yml)\n"


def _done(code: int = 0, out: str = "", err: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, out, err)


def test_the_one_time_code_and_url_are_read_from_real_output() -> None:
    assert parse_login_prompt(REAL_PROMPT) == ("AB12-CD34", "https://github.com/login/device")
    assert parse_login_prompt("error connecting to api.github.com") == ("", "")


def test_status_tells_keyring_from_a_plain_file_and_never_carries_the_token() -> None:
    assert parse_status(REAL_STATUS_KEYRING) == {"logged_in": True, "user": "someone", "storage": "keyring"}
    assert parse_status(REAL_STATUS_FILE)["storage"] == "file"
    assert parse_status("You are not logged into any GitHub hosts.")["logged_in"] is False
    assert "gho_" not in json.dumps(parse_status(REAL_STATUS_KEYRING))


def test_the_right_zip_is_picked_for_each_machine() -> None:
    assets = [{"name": f"gh_2.103.3_{n}"} for n in
              ("macOS_arm64.zip", "macOS_amd64.zip", "windows_amd64.zip", "windows_arm64.zip", "linux_amd64.tar.gz", "checksums.txt")]
    assert pick_asset(assets, "darwin", "arm64")[0]["name"].endswith("macOS_arm64.zip")
    assert pick_asset(assets, "win32", "AMD64")[0]["name"].endswith("windows_amd64.zip")
    assert pick_asset(assets, "darwin", "arm64")[1]["name"].endswith("checksums.txt")
    assert pick_asset(assets, "linux", "x86_64")[0] is None


def _release(tmp_path: Path, *, tamper: bool = False) -> tuple[dict[str, bytes], bytes]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("gh_2.103.3_macOS_arm64/bin/gh", b"#!/bin/sh\necho fake gh\n")
        z.writestr("gh_2.103.3_macOS_arm64/LICENSE", b"MIT")
    blob = buf.getvalue()
    digest = hashlib.sha256(blob + (b"x" if tamper else b"")).hexdigest()
    release = {"tag_name": "v2.103.3", "assets": [
        {"name": "gh_2.103.3_macOS_arm64.zip", "browser_download_url": "https://dl/zip"},
        {"name": "gh_2.103.3_checksums.txt", "browser_download_url": "https://dl/sums"}]}
    return {GH_RELEASE_API: json.dumps(release).encode(), "https://dl/zip": blob,
            "https://dl/sums": f"{digest}  gh_2.103.3_macOS_arm64.zip\n".encode()}, blob


def _mac_signed(args: list[str], **_: Any) -> subprocess.CompletedProcess:
    if args[0] == "spctl":
        return _done(0, err="accepted\nsource=Notarized Developer ID")
    if args[:2] == ["codesign", "-dv"]:
        return _done(0, err=f"TeamIdentifier={MAC_TEAM_ID}")
    return _done(0)


def test_install_puts_gh_in_place_only_when_the_checksum_and_signature_match(tmp_path: Path) -> None:
    files, _ = _release(tmp_path)
    link = GithubLink(tmp_path / "gh", fetch=files.__getitem__, run=_mac_signed, system="darwin", machine="arm64")
    out = link.install()
    assert out["version"] == "2.103.3" and link.our_gh.read_bytes().startswith(b"#!/bin/sh")


def test_a_tampered_download_is_refused_and_nothing_is_left(tmp_path: Path) -> None:
    files, _ = _release(tmp_path, tamper=True)
    link = GithubLink(tmp_path / "gh", fetch=files.__getitem__, run=_mac_signed, system="darwin", machine="arm64")
    with pytest.raises(RuntimeError, match="gh_checksum_mismatch"):
        link.install()
    assert not link.our_gh.exists()


def test_a_gh_signed_by_someone_else_is_refused(tmp_path: Path) -> None:
    files, _ = _release(tmp_path)

    def other_team(args: list[str], **kw: Any) -> subprocess.CompletedProcess:
        if args[:2] == ["codesign", "-dv"]:
            return _done(0, err="TeamIdentifier=ZZZZZZZZZZ")
        return _mac_signed(args, **kw)

    link = GithubLink(tmp_path / "gh", fetch=files.__getitem__, run=other_team, system="darwin", machine="arm64")
    with pytest.raises(RuntimeError, match="gh_not_signed"):
        link.install()
    assert not link.our_gh.exists() and not (tmp_path / "gh" / "staging" / "gh").exists()


class _FakeLogin:
    """`gh auth login --web` 대역 — 코드를 찍고, 사람이 승인할 때까지 안 끝난다."""

    def __init__(self, text: str) -> None:
        self.stdin = io.StringIO()
        self.stderr = io.StringIO(text)
        self.stdout = io.StringIO("")
        self.returncode: int | None = None
        self.args: list[str] = []
        self.env: dict[str, str] = {}

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


def _gh_runner(logged_in: dict[str, bool]):
    def run(args: list[str], **kw: Any) -> subprocess.CompletedProcess:
        if args[1:] == ["--version"]:
            return _done(0, "gh version 2.103.3 (2026-11-01)\n")
        if args[1:3] == ["auth", "status"]:
            ours = "GH_CONFIG_DIR" in (kw.get("env") or {})
            return _done(0, REAL_STATUS_KEYRING) if logged_in.get("ours" if ours else "user") else _done(1, "", "not logged in")
        return _done(0)
    return run


def _link_with_gh(tmp_path: Path, logged_in: dict[str, bool], proc: _FakeLogin, opened: list[str]) -> GithubLink:
    link = GithubLink(tmp_path / "gh", run=_gh_runner(logged_in), system="darwin", which=lambda name: None,
                      open_url=opened.append, popen=lambda args, **kw: (setattr(proc, "args", args), setattr(proc, "env", kw["env"]), proc)[2])
    link.our_gh.parent.mkdir(parents=True)
    link.our_gh.write_text("fake")
    return link


def test_login_shows_the_code_opens_the_browser_and_finishes_when_a_person_approves(tmp_path: Path) -> None:
    proc, opened, logged = _FakeLogin(REAL_PROMPT), [], {"ours": False}
    link = _link_with_gh(tmp_path, logged, proc, opened)
    started = link.login_start()
    assert started["ok"] and started["code"] == "AB12-CD34" and opened == ["https://github.com/login/device"]
    assert proc.env["GH_CONFIG_DIR"] == str(link.config_dir), "우리 설정 자리(앱 칸 밖)로만"
    assert "--web" in proc.args and proc.stdin.getvalue() == "\n"
    assert link.login_poll()["state"] == "waiting"
    assert link.login_start()["code"] == "AB12-CD34", "진행 중에 또 누르면 같은 코드"
    logged["ours"], proc.returncode = True, 0          # 사람이 브라우저에서 승인
    assert link.login_poll() == {"state": "done", "user": "someone", "storage": "keyring"}


def test_a_login_nobody_approves_is_cut_after_the_wait(tmp_path: Path) -> None:
    now = [0.0]
    proc = _FakeLogin(REAL_PROMPT)
    link = _link_with_gh(tmp_path, {}, proc, [])
    link._clock = lambda: now[0]
    link.login_start()
    now[0] += 15 * 60 + 1
    assert link.login_poll()["state"] == "expired" and proc.returncode == -9


def test_no_code_means_failure_not_a_hang(tmp_path: Path) -> None:
    proc = _FakeLogin("error connecting to api.github.com\n")
    proc.returncode = 1
    link = _link_with_gh(tmp_path, {}, proc, [])
    out = link.login_start()
    assert out == {"ok": False, "error": "login_code_not_found", "detail": "error connecting to api.github.com\n"}


def test_an_existing_user_login_is_offered_as_is(tmp_path: Path) -> None:
    link = GithubLink(tmp_path / "gh", run=_gh_runner({"user": True}), system="darwin", which=lambda name: "/usr/local/bin/gh")
    state = link.status()
    assert state["gh"]["source"] == "system" and state["login"] == {
        "logged_in": True, "user": "someone", "storage": "keyring", "config": "user"}
    assert "gho_" not in json.dumps(state)


def test_our_git_gets_the_helper_but_the_global_gitconfig_is_untouched(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GH_TOKEN", "ghp_should_not_leak")
    link = _link_with_gh(tmp_path, {"ours": True}, _FakeLogin(""), [])
    args, env = link.git_auth()
    assert args[:2] == ["-c", "credential.https://github.com.helper="], "위에서 물려받은 도우미를 비운다"
    assert args[3].endswith("auth git-credential") and str(link.our_gh.as_posix()) in args[3]
    assert env["GH_CONFIG_DIR"] == str(link.config_dir) and "GH_TOKEN" not in env
    assert not (tmp_path / "home" / ".gitconfig").exists()


def test_not_logged_in_means_no_helper(tmp_path: Path) -> None:
    assert _link_with_gh(tmp_path, {}, _FakeLogin(""), []).git_auth() is None


def test_the_api_doors_need_the_control_token_and_status_answers(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    monkeypatch.setattr("shutil.which", lambda name: None)  # 이 PC 의 진짜 gh 를 안 부른다
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                          control_token="test-token", camera_enabled=False, vision_enabled=False,
                          voice_enabled=False, tts_enabled=False, github_dir=tmp_path / "gh")
    app = create_app(config, start_services=False)
    with TestClient(app) as client:
        for method, path in (("get", "/v1/github/status"), ("post", "/v1/github/install"), ("post", "/v1/github/login/start"),
                             ("get", "/v1/github/login/poll"), ("post", "/v1/github/logout")):
            assert getattr(client, method)(path).status_code == 401, path
        state = client.get("/v1/github/status", headers={"X-Jarvis-Token": "test-token"}).json()
        assert state["gh"] is None and state["login"]["logged_in"] is False
        assert client.post("/v1/github/login/start", headers={"X-Jarvis-Token": "test-token"}).json() == {
            "ok": False, "error": "gh_missing"}


def test_every_gh_and_git_call_reads_utf8_not_the_windows_codepage(tmp_path: Path) -> None:
    """11-12 이 PC: cp949 로 읽다 「✓」에서 깨져 로그인돼 있는데 「안 됨」이었다."""
    calls: list[dict[str, Any]] = []

    def run(args: list[str], **kw: Any) -> subprocess.CompletedProcess:
        calls.append(kw)
        return _gh_runner({"user": True})(args, **kw)

    link = GithubLink(tmp_path / "gh", run=run, system="win32", which=lambda name: f"C:/bin/{name}.exe")
    link.status()
    assert calls and all(kw.get("encoding") == "utf-8" for kw in calls)
    proc = _FakeLogin(REAL_PROMPT)
    seen: dict[str, Any] = {}
    link._popen = lambda args, **kw: (seen.update(kw), proc)[1]
    link.login_start()
    assert seen.get("encoding") == "utf-8"
