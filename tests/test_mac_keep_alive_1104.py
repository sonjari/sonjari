"""맥은 모델을 30분만 붙잡아 둔다(11-04 대표 결정 · 통합 메모리) — 윈도우는 그대로 24시간, 환경변수가 있으면 그것을 따른다."""

from __future__ import annotations

import sys

from alture_jarvis.config import JarvisConfig


def test_keep_alive_default_is_30m_on_mac_and_24h_elsewhere(monkeypatch):
    monkeypatch.delenv("JARVIS_OLLAMA_KEEP_ALIVE", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert JarvisConfig.from_env().ollama_keep_alive == "30m"
    monkeypatch.setattr(sys, "platform", "win32")
    assert JarvisConfig.from_env().ollama_keep_alive == "24h"


def test_an_explicit_setting_still_wins_on_mac(monkeypatch):
    monkeypatch.setenv("JARVIS_OLLAMA_KEEP_ALIVE", "2h")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert JarvisConfig.from_env().ollama_keep_alive == "2h"
