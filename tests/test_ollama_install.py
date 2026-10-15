"""Ollama 버튼 한 번 설치 (W2) — 받은 것을 해시 대조 없이 실행하지 않는다."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

from alture_jarvis.ollama_install import ASSET_NAME, OllamaInstaller, parse_sums

CLOSED = "http://127.0.0.1:9"  # 아무도 안 듣는 자리 — 운영 Ollama(11434)를 안 건드린다


def _zip_bytes(with_exe: bool = True, with_runner: bool = True) -> bytes:
    """공식 zip 과 같은 모양: `ollama.exe` + `lib/ollama/…`(러너가 여기 산다, 실측 87개 중 86개)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        if with_exe:
            bundle.writestr("ollama.exe", b"MZ fake")
        if with_runner:
            bundle.writestr("lib/ollama/llama-server.exe", b"MZ runner")
        bundle.writestr("lib/ollama/readme.txt", b"x")
    return buffer.getvalue()


class _Process:
    pid = 4242

    def __init__(self) -> None:
        self.terminated = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


def _installer(tmp_path: Path, payload: bytes, *, sums_hash: str | None = None, api_digest: str | None = None,
               url: str = "https://github.com/ollama/ollama/releases/download/v9.9.9/ollama-windows-amd64.zip"):
    real = hashlib.sha256(payload).hexdigest()
    release = {"tag_name": "v9.9.9", "assets": [
        {"name": ASSET_NAME, "browser_download_url": url, "size": len(payload),
         **({"digest": f"sha256:{api_digest}"} if api_digest else {})},
        {"name": "sha256sum.txt",
         "browser_download_url": "https://github.com/ollama/ollama/releases/download/v9.9.9/sha256sum.txt"},
    ]}
    sums = f"{sums_hash if sums_hash is not None else real}  ./{ASSET_NAME}\nabc  ./other.zip\n"
    started: list[list[str]] = []

    def download(_url, target: Path, progress):
        target.write_bytes(payload)
        progress(len(payload), len(payload))

    def popen(args, **kwargs):
        started.append(list(args))
        return _Process()

    installer = OllamaInstaller(
        install_root=tmp_path / "data" / "ollama", base_url=CLOSED,
        fetch_json=lambda _u: release, fetch_bytes=lambda _u: sums.encode(), download=download, popen=popen,
    )
    return installer, started, real


def test_parse_sums_reads_the_one_asset() -> None:
    text = f"{'a' * 64}  ./{ASSET_NAME}\n{'b' * 64}  ./ollama-linux-amd64.tgz\n"
    assert parse_sums(text) == "a" * 64
    assert parse_sums("nothing here") == ""


def test_verified_zip_is_extracted_and_served(tmp_path: Path, monkeypatch) -> None:
    payload = _zip_bytes()
    installer, started, real = _installer(tmp_path, payload)
    answers = iter(["", ""] + ["0.9.9"] * 10)
    monkeypatch.setattr(installer, "running_version", lambda: next(answers))

    result = installer.install()

    assert result["ok"] is True and result["sha256"] == real
    exe = installer.bundled_exe()
    assert exe is not None and exe.read_bytes() == b"MZ fake"
    assert started and started[0][-1] == "serve"
    assert not list((tmp_path / "data" / "ollama").glob("*.partial"))
    installer.stop()


def test_hash_mismatch_deletes_the_download_and_never_runs_it(tmp_path: Path, monkeypatch) -> None:
    installer, started, _real = _installer(tmp_path, _zip_bytes(), sums_hash="0" * 64)
    monkeypatch.setattr(installer, "running_version", lambda: "")

    result = installer.install()

    assert result == {"ok": False, "error": "hash_mismatch"}
    assert started == []
    assert installer.bundled_exe() is None
    assert not list((tmp_path / "data" / "ollama").glob("*.zip*"))


def test_release_and_api_digest_must_agree(tmp_path: Path, monkeypatch) -> None:
    installer, started, _real = _installer(tmp_path, _zip_bytes(), api_digest="f" * 64)
    monkeypatch.setattr(installer, "running_version", lambda: "")
    try:
        installer.install()
    except RuntimeError as exc:
        assert str(exc) == "release_hashes_disagree"
    else:
        raise AssertionError("disagreeing hashes must stop the install")
    assert started == []


def test_a_download_url_outside_the_official_release_is_refused(tmp_path: Path, monkeypatch) -> None:
    installer, started, _real = _installer(tmp_path, _zip_bytes(), url="https://example.com/ollama.zip")
    monkeypatch.setattr(installer, "running_version", lambda: "")
    try:
        installer.install()
    except RuntimeError as exc:
        assert str(exc) == "download_url_not_official"
    else:
        raise AssertionError("unofficial url must be refused")
    assert started == []


def test_already_running_ollama_is_used_as_is(tmp_path: Path, monkeypatch) -> None:
    installer, started, _real = _installer(tmp_path, _zip_bytes())
    monkeypatch.setattr(installer, "running_version", lambda: "0.12.0")
    assert installer.start_install() == {"ok": False, "error": "already_running"}
    status = installer.status()
    assert status["running"] is True and status["can_install"] is False
    assert started == []


def test_zip_without_ollama_exe_is_not_installed(tmp_path: Path, monkeypatch) -> None:
    installer, started, _real = _installer(tmp_path, _zip_bytes(with_exe=False))
    monkeypatch.setattr(installer, "running_version", lambda: "")
    try:
        installer.install()
    except RuntimeError as exc:
        assert str(exc) == "zip_has_no_ollama_exe"
    assert installer.bundled_exe() is None and started == []


# ── 반쪽 설치 (2026-09-18 노트북 실측) ──────────────────────────────────────────
#
# 노트북에서 설치는 「성공」이라 했는데 모델을 올릴 때
#   error starting llama-server: llama-server binary not found (checked: …\v0.34.1\lib\ollama\llama-server.exe, …)
# 로 터졌다. 화면은 「글자가 나오지 않았습니다 — 그래픽카드 드라이버를 확인해 주세요」였다(틀린 안내).
# 공식 zip 에는 러너가 분명히 들어 있다. 노트북에서도 파일은 **멀쩡히 있었다** — 스토어판에서 앱 데이터에 깐 탓에
# 패키지 밖 실행 파일인 Ollama 가 그 칸을 못 봤다(뿌리는 자리, test_paths_outside_app_data.py). 여기서는 러너가
# 없는 설치를 「설치 완료」로 받지 않고, 반쪽이면 **다시 깔 수 있어야** 한다는 것만 잰다.

def test_a_zip_without_the_runner_is_not_accepted_as_installed(tmp_path: Path, monkeypatch) -> None:
    installer, started, _real = _installer(tmp_path, _zip_bytes(with_runner=False))
    monkeypatch.setattr(installer, "running_version", lambda: "")
    try:
        installer.install()
    except RuntimeError as exc:
        assert str(exc) == "zip_has_no_runner"
    else:
        raise AssertionError("러너 없는 압축을 설치 완료로 받으면 안 된다")
    assert started == [], "켜지도 말아야 한다"
    assert installer.bundled_exe() is None


def test_a_half_install_is_reported_and_can_be_repaired_even_while_ollama_answers(tmp_path: Path, monkeypatch) -> None:
    installer, _started, _real = _installer(tmp_path, _zip_bytes())
    answers = iter(["", ""] + ["0.34.1"] * 20)
    monkeypatch.setattr(installer, "running_version", lambda: next(answers))
    installer.install()
    installer.stop()
    runner = installer.runner_exe()
    assert runner is not None
    runner.unlink()  # 백신이 지운 그 자리

    status = installer.status()
    assert status["runner_missing"] is True
    assert status["running"] is True, "서버는 여전히 답한다 — 그래서 이 고장이 안 보였다"
    assert status["can_install"] is True, "돌고 있어도 반쪽이면 다시 설치를 열어 줘야 한다"
    assert installer.start_install()["ok"] is True


def test_a_healthy_running_install_still_hides_the_button(tmp_path: Path, monkeypatch) -> None:
    installer, _started, _real = _installer(tmp_path, _zip_bytes())
    answers = iter(["", ""] + ["0.34.1"] * 20)
    monkeypatch.setattr(installer, "running_version", lambda: next(answers))
    installer.install()
    installer.stop()

    status = installer.status()
    assert status["runner_missing"] is False and status["can_install"] is False
    assert installer.start_install() == {"ok": False, "error": "already_running"}


def test_a_good_install_in_the_old_place_is_moved_instead_of_downloaded_again(tmp_path: Path, monkeypatch) -> None:
    """자리를 옮겼다고 1.4GB 를 다시 받게 하지 않는다 — 우리는 옛 자리를 읽을 수 있다(못 보는 건 Ollama)."""
    legacy_root = tmp_path / "appdata" / "ollama"
    legacy, started, _real = _installer(tmp_path / "old", _zip_bytes())
    legacy.install_root = legacy_root
    monkeypatch.setattr(legacy, "running_version", lambda: "")
    legacy.install()
    legacy.stop()
    assert legacy.runner_exe() is not None

    fresh, downloads, _ = _installer(tmp_path / "new", _zip_bytes())
    fresh.install_root = tmp_path / "home" / "Ontelic" / "engine" / "ollama"
    fresh.legacy_roots = (legacy_root,)
    monkeypatch.setattr(fresh, "running_version", lambda: "")

    moved = fresh.adopt_legacy_install()

    assert moved["ok"] is True and moved["folder"] == "v9.9.9"
    assert fresh.bundled_exe() is not None and fresh.runner_exe() is not None
    assert fresh.install_root in fresh.runner_exe().parents
    assert downloads == [], "받지도 켜지도 않는다 — 옮기기만 한다"


def test_a_half_install_in_the_old_place_is_not_moved(tmp_path: Path, monkeypatch) -> None:
    """반쪽을 옮기면 고장을 옮기는 것이다 — 그때는 새로 받아야 한다."""
    legacy_root = tmp_path / "appdata" / "ollama"
    legacy, _started, _real = _installer(tmp_path / "old", _zip_bytes())
    legacy.install_root = legacy_root
    monkeypatch.setattr(legacy, "running_version", lambda: "")
    legacy.install()
    legacy.stop()
    legacy.runner_exe().unlink()

    fresh, _downloads, _ = _installer(tmp_path / "new", _zip_bytes())
    fresh.install_root = tmp_path / "home" / "engine" / "ollama"
    fresh.legacy_roots = (legacy_root,)
    monkeypatch.setattr(fresh, "running_version", lambda: "")

    assert fresh.adopt_legacy_install() == {"ok": False, "error": "no_legacy_install"}
    assert fresh.bundled_exe() is None


# ── 고치기 (2026-09-18 노트북 두 번째 화면) ─────────────────────────────────────
#
# 「Ollama 다시 설치」가 `already_running` 으로 거절됐다. 돌고 있던 것은 **옛 자리에서 켜진 고장난 우리 서버**였는데
# 검사는 새 자리만 봤다. 「적용하기」도 그 서버에 물어 같은 오류가 났고, 사람 눈엔 「아무것도 안 된다」였다.

def _legacy_ready(tmp_path: Path, monkeypatch) -> Path:
    legacy_root = tmp_path / "appdata" / "ollama"
    legacy, _started, _real = _installer(tmp_path / "old", _zip_bytes())
    legacy.install_root = legacy_root
    monkeypatch.setattr(legacy, "running_version", lambda: "")
    legacy.install()
    legacy.stop()
    return legacy_root


def test_repair_stops_our_old_server_moves_the_files_and_starts_from_the_new_place(tmp_path: Path, monkeypatch) -> None:
    legacy_root = _legacy_ready(tmp_path, monkeypatch)
    fresh, started, _ = _installer(tmp_path / "new", _zip_bytes())
    fresh.install_root = tmp_path / "home" / "Ontelic" / "engine" / "ollama"
    fresh.legacy_roots = (legacy_root,)
    alive = {"old": True, "new": False}
    monkeypatch.setattr(fresh, "running_version", lambda: "0.34.1" if (alive["old"] or alive["new"]) else "")
    old_server = {"pid": "777", "name": "ollama.exe", "path": str(legacy_root / "v9.9.9" / "ollama.exe")}
    killed: list[int] = []

    def kill(pid: int) -> None:
        killed.append(pid)
        alive["old"] = False

    original_popen = fresh.popen

    def popen(args, **kwargs):
        alive["new"] = True
        return original_popen(args, **kwargs)

    fresh.popen = popen

    result = fresh.repair(find=lambda: [old_server], kill=kill)
    assert result["ok"] is True and result["stopped"] == 1
    assert killed == [777], "옛 자리의 우리 서버만 끈다"
    fresh._thread.join(timeout=10)

    assert fresh.runner_exe() is not None and fresh.install_root in fresh.runner_exe().parents
    assert started and started[-1][0].startswith(str(fresh.install_root)), "새 자리에서 켜야 한다"
    assert fresh.status()["install"]["phase"] == "ready"
    fresh.stop()


def test_repair_never_touches_an_ollama_the_person_installed(tmp_path: Path, monkeypatch) -> None:
    fresh, _started, _ = _installer(tmp_path / "new", _zip_bytes())
    fresh.install_root = tmp_path / "home" / "engine" / "ollama"
    fresh.legacy_roots = (tmp_path / "appdata" / "ollama",)
    monkeypatch.setattr(fresh, "running_version", lambda: "0.34.1")
    theirs = {"pid": "555", "name": "ollama.exe", "path": r"C:\Program Files\Ollama\ollama.exe"}
    killed: list[int] = []

    result = fresh.repair(find=lambda: [theirs], kill=killed.append)

    assert result == {"ok": False, "error": "not_ours"}
    assert killed == []


def test_status_calls_it_broken_when_only_our_old_server_is_running(tmp_path: Path, monkeypatch) -> None:
    """새 자리는 비었는데 옛 자리의 우리 서버가 돈다 = 스토어판에서는 러너를 못 보는 그 서버다."""
    fresh, _started, _ = _installer(tmp_path / "new", _zip_bytes())
    fresh.install_root = tmp_path / "home" / "engine" / "ollama"
    legacy_root = tmp_path / "appdata" / "ollama"
    fresh.legacy_roots = (legacy_root,)
    monkeypatch.setattr(fresh, "running_version", lambda: "0.34.1")
    monkeypatch.setattr(fresh, "our_running_servers",
                        lambda find=None: [{"pid": "1", "name": "ollama.exe", "path": str(legacy_root / "v" / "ollama.exe")}])

    status = fresh.status()
    assert status["runner_missing"] is True and status["can_install"] is True
