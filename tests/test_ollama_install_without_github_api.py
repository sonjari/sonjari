"""GitHub API 가 막혀도 Ollama 를 깐다 — 해시 대조는 그대로 (2026-10-01 베타 첫 사용자 · 회사 PC).

「설치하지 못했습니다 (HTTPError: HTTP Error 403: rate limit exceeded)」. 로그인 없는 GitHub API 는 IP 하나당 시간당
60번이라, 직원 수천 명이 한 인터넷 주소를 쓰는 회사에서는 남이 다 써 버린다. 받기 주소(`releases/download/…`)는
이 제한과 상관없다 — `releases/latest` 페이지가 넘겨주는 주소(`…/releases/tag/v0.35.0`)로 판 이름만 알면 된다.

같은 날 두 번째 고장: Ollama 가 안 떠 있어 모델 받기가 「[WinError 10061] 연결 거부」였는데, 화면은 「인터넷 연결과
디스크 여유를 확인하라」고 했다. 받기는 이 PC 의 Ollama 에 부탁하는 일이라 연결 거부는 Ollama 가 꺼졌다는 뜻이다.
"""

from __future__ import annotations

import hashlib
import urllib.error
from pathlib import Path

import pytest

from alture_jarvis.model_setup import pull_failure_reason
from alture_jarvis.ollama_install import ASSET_NAME, OllamaInstaller

TAG_PAGE = "https://github.com/ollama/ollama/releases/tag/v0.35.0"
SUMS = "https://github.com/ollama/ollama/releases/download/v0.35.0/sha256sum.txt"


def _rate_limited(url: str):
    raise urllib.error.HTTPError(url, 403, "rate limit exceeded", {}, None)


def _installer(tmp_path: Path, *, page=lambda: TAG_PAGE, sums_text: str | None = None) -> tuple[OllamaInstaller, list[str]]:
    asked: list[str] = []
    real = hashlib.sha256(b"zip").hexdigest()
    text = sums_text if sums_text is not None else f"{real}  ./{ASSET_NAME}\nabc  ./other.zip\n"

    def fetch_bytes(url: str) -> bytes:
        asked.append(url)
        return text.encode()

    return OllamaInstaller(install_root=tmp_path / "ollama", base_url="http://127.0.0.1:9", fetch_json=_rate_limited,
                           fetch_bytes=fetch_bytes, latest_page_url=page), asked


def test_a_rate_limited_api_falls_back_to_the_release_page(tmp_path: Path) -> None:
    installer, asked = _installer(tmp_path)
    resolved = installer.resolve()
    assert resolved["version"] == "v0.35.0"
    assert resolved["url"] == f"https://github.com/ollama/ollama/releases/download/v0.35.0/{ASSET_NAME}"
    assert resolved["sha256"] == hashlib.sha256(b"zip").hexdigest()
    assert asked == [SUMS], "해시는 그 판의 sha256sum.txt 에서 — 같은 판이어야 한다"


def test_no_published_hash_still_means_no_download(tmp_path: Path) -> None:
    # 받은 것을 그냥 실행하지 않는다는 약속 — 대체 경로에서도 대조할 해시가 없으면 멈춘다.
    installer, _ = _installer(tmp_path, sums_text="abc  ./other.zip\n")
    with pytest.raises(RuntimeError, match="no_published_hash"):
        installer.resolve()


def test_when_both_ways_fail_both_reasons_are_told(tmp_path: Path) -> None:
    def page() -> str:
        raise urllib.error.URLError("blocked by proxy")

    installer, _ = _installer(tmp_path, page=page)
    with pytest.raises(RuntimeError) as caught:
        installer.resolve()
    assert "403" in str(caught.value) and "blocked by proxy" in str(caught.value)


def test_an_unexpected_landing_page_is_refused(tmp_path: Path) -> None:
    installer, _ = _installer(tmp_path, page=lambda: "https://github.com/login?return_to=x")
    with pytest.raises(RuntimeError, match="latest_page_unexpected"):
        installer.resolve()


def test_connection_refused_means_ollama_is_off_not_the_internet() -> None:
    refused = urllib.error.URLError(ConnectionRefusedError(10061, "대상 컴퓨터에서 연결을 거부했으므로 연결하지 못했습니다"))
    assert pull_failure_reason(refused) == "ollama_not_running"
    assert pull_failure_reason(RuntimeError("[WinError 10061] refused")) == "ollama_not_running"
    assert pull_failure_reason(RuntimeError("pull model manifest: file does not exist")) == ""


class _Started:
    pid = 4242


def test_a_hand_installed_ollama_that_is_off_is_started_by_its_own_app(tmp_path: Path, monkeypatch) -> None:
    """403 에 막혀 테스터가 공식 설치 파일로 깔았고, 서버가 꺼져 있어 10061 이었다 — 관리자는 우리가 깐 것만 켰다."""
    from alture_jarvis.ollama_install import OllamaKeeper

    app = tmp_path / "Programs" / "Ollama" / "ollama app.exe"
    app.parent.mkdir(parents=True)
    app.write_bytes(b"exe")
    launched: list[list[str]] = []
    up = {"on": False}

    def popen(command, **kwargs):
        launched.append(command)
        up["on"] = True
        return _Started()

    installer = OllamaInstaller(install_root=tmp_path / "ours", base_url="http://127.0.0.1:9", popen=popen,
                                system_apps=(tmp_path / "missing" / "ollama app.exe", app))
    monkeypatch.setattr(installer, "running_version", lambda: "0.35.0" if up["on"] else "")
    monkeypatch.setattr(installer, "clear_orphan_runners", lambda: [])
    assert installer.bundled_exe() is None
    result = installer.serve(wait_sec=2)
    assert result["ok"] and result["external"]
    assert launched == [[str(app)]], "서버(ollama.exe serve)가 아니라 그 사람의 트레이 앱으로 켠다"
    assert installer._process is None, "사람이 깐 Ollama 는 우리가 쥐지 않는다 — stop() 이 끄면 안 된다"

    keeper = OllamaKeeper(installer, run=lambda fn: fn())
    up["on"] = False
    assert keeper.ensure() is True, "우리 설치가 없어도 켤 것이 있으면 「켜는 중」이다"


def test_nothing_installed_is_still_not_installed(tmp_path: Path) -> None:
    installer = OllamaInstaller(install_root=tmp_path / "ours", base_url="http://127.0.0.1:9",
                                system_apps=(tmp_path / "none" / "ollama app.exe",))
    assert installer.serve(wait_sec=1) == {"ok": False, "error": "not_installed"}
