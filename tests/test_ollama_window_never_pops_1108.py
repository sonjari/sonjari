"""Ollama 창이 앞으로 튀어나오지 않게 (2026-11-08 대표 · 윈도우 · 맥 둘 다).

뿌리 둘:
1. 위성(모델이 집 PC 에서 돈다)일 때 /health 의 「안 닿음」은 집 PC 이야기인데, 지킴이가 이 기기 Ollama 앱을 켰다.
2. 켤 때 창 있는 앱을 띄웠다 — 윈도우 `ollama app.exe` · 맥 `open -g -a Ollama.app`(앞으로만 안 끌 뿐 창은 연다).
양방향: 이 기기 자리면 예전처럼 켠다 / 집 PC 자리면 안 켠다 · 서버 파일이 있으면 서버만 / 없으면 예전처럼 앱.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.ollama_install import OllamaInstaller, OllamaKeeper


class _Installer:
    def __init__(self) -> None:
        self.serves = 0

    def bundled_exe(self):
        return "ollama.exe"

    def serve(self):
        self.serves += 1
        return {"ok": True}


def test_satellite_never_starts_this_devices_ollama() -> None:
    inst = _Installer()
    place = {"value": "home_pc"}
    keeper = OllamaKeeper(inst, run=lambda fn: fn(), applies=lambda: place["value"] != "home_pc")
    out = keeper.annotate({"ok": False, "error": "relay_unreachable"})
    assert inst.serves == 0 and out["starting"] is False
    place["value"] = "this_pc"  # 자리를 이 기기로 바꾸면 다시 켠다
    assert keeper.ensure() is True and inst.serves == 1


class _Started:
    pid = 4242


def test_windows_starts_the_server_not_the_tray_window(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "Programs" / "Ollama"
    folder.mkdir(parents=True)
    app = folder / "ollama app.exe"
    app.write_bytes(b"exe")
    server = folder / "ollama.exe"
    server.write_bytes(b"exe")
    launched: list[list[str]] = []
    up = {"on": False}

    def popen(command, **kwargs):
        launched.append(command)
        up["on"] = True
        return _Started()

    installer = OllamaInstaller(install_root=tmp_path / "ours", base_url="http://127.0.0.1:9", popen=popen,
                                system_apps=(app,))
    monkeypatch.setattr(installer, "running_version", lambda: "0.40.10" if up["on"] else "")
    monkeypatch.setattr(installer, "clear_orphan_runners", lambda: [])
    result = installer.serve(wait_sec=2)
    assert result["ok"]
    assert launched == [[str(server), "serve"]], "창 있는 트레이 앱 대신 같은 폴더의 서버만"


def test_mac_opens_ollama_hidden(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: calls.append(list(command)))
    installer = OllamaInstaller(install_root=tmp_path / "ours", base_url="http://127.0.0.1:9")
    app = Path("/Applications/Ollama.app")
    installer.mac_open(app)
    assert calls == [["open", "-g", "-a", str(app), "--args", "hidden"]], "맥 로그인 항목과 같은 `hidden` — 창 없이"
