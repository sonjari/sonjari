"""꺼진 Ollama 를 켜는 지킴이 스위치 (2026-11-08).

대표 PC 는 모델 주소가 Strata 다리(:11435)다. 재부팅 뒤 손자리가 다리보다 먼저 떠 /health 에서 「꺼져 있다」를 보고
그 문에 Ollama 를 띄웠고, 다리는 문을 못 잡아 죽었다. `JARVIS_OLLAMA_AUTOSTART=0` 이면 켜지 않는다.
양방향: 켜 두면 예전처럼 켠다 / 끄면 serve 를 부르지 않고 「켜는 중」이라 하지 않는다.
"""

from __future__ import annotations

from alture_jarvis.config import JarvisConfig
from alture_jarvis.ollama_install import OllamaKeeper


class _Installer:
    def __init__(self) -> None:
        self.serves = 0

    def bundled_exe(self):
        return "ollama.exe"

    def serve(self):
        self.serves += 1
        return {"ok": True}


def test_enabled_keeper_still_starts_ollama() -> None:
    inst = _Installer()
    keeper = OllamaKeeper(inst, run=lambda fn: fn())
    assert keeper.ensure() is True and inst.serves == 1


def test_disabled_keeper_never_starts_ollama() -> None:
    inst = _Installer()
    keeper = OllamaKeeper(inst, run=lambda fn: fn(), enabled=False)
    out = keeper.annotate({"ok": False, "error": "connection refused"})
    assert inst.serves == 0 and out["starting"] is False


def test_env_switch_reaches_config(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_OLLAMA_AUTOSTART", "0")
    assert JarvisConfig.from_env().ollama_autostart is False
    monkeypatch.delenv("JARVIS_OLLAMA_AUTOSTART")
    assert JarvisConfig.from_env().ollama_autostart is True
