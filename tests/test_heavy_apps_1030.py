"""그래픽카드를 같이 쓰는 무거운 작업 프로그램을 알아본다 (2026-10-30 대표).

윈도우는 다른 프로그램이 쥔 카드 메모리를 잘 안 보여 준다(`nvidia-smi` 프로그램별 사용량 `[N/A]`). 그래서 숫자 대신
「켜져 있음」(판 시작 → 빠른 모델로)과 「깔려 있음」(마법사 → 같이 받아 두기)을 본다. 16GB 이하 카드에서만.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis import heavy_apps
from alture_jarvis import setup_profile as sp
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.jobs import JobStore


def test_running_apps_are_named_once() -> None:
    found = heavy_apps.match_running([
        ("3dsmax.exe", r"C:\Program Files\Autodesk\3ds Max 2025\3dsmax.exe"),
        ("3dsmax.exe", r"C:\Program Files\Autodesk\3ds Max 2025\3dsmax.exe"),
        ("Unity.exe", r"C:\Program Files\Unity\Hub\Editor\6000.0\Editor\Unity.exe"),
        ("eldenring.exe", r"D:\SteamLibrary\steamapps\common\ELDEN RING\Game\eldenring.exe"),
        ("chrome.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("steam.exe", r"C:\Program Files (x86)\Steam\steam.exe"),   # 가게 프로그램 자체는 게임이 아니다
    ])
    assert found == ["3ds Max", "Unity", "game (eldenring)"]


def test_installed_counts_work_apps_but_not_games() -> None:
    found = heavy_apps.match_installed(["Autodesk 3ds Max 2025", "Unity Hub 3.9.1", "Steam", "Google Chrome", "Blender"])
    assert found == ["3ds Max", "Blender", "Unity"]
    assert heavy_apps.match_installed(["Steam", "Epic Games Launcher", "Microsoft Office"]) == []


@pytest.mark.parametrize("total, small", [(16.0, True), (12.0, True), (24.0, False), (None, False), ("?", False)])
def test_only_small_cards_count(total: Any, small: bool) -> None:
    assert heavy_apps.small_card(total) is small


# ── 판 시작 ─────────────────────────────────────────────────────────────

class _Model:
    def chat_messages_stream(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return {"role": "assistant", "content": "끝"}


def _agent(tmp_path: Path, *, card_gb: float, busy: list[str], outcome: dict | None) -> tuple[BrowserAgent, list]:
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs")
    store = JobStore(tmp_path / "jarvis.db")
    tools = SimpleNamespace(names=set(), ollama_tools=[])
    agent = BrowserAgent(config, _Model(), SimpleNamespace(), SimpleNamespace(status=lambda: {}), tools, store, EventBus())
    # 윈도우가 숨긴 경우: 몫 1.0 · 남은 메모리 넉넉 — 숫자로는 아무 일 없어 보인다.
    agent._gpu_facts = lambda role="chat": {"gpu_share": 1.0, "card_total_gb": card_gb, "card_free_gb": 3.5, "card_full": False}
    agent._heavy_running = lambda: list(busy)
    calls: list = []

    def fallback(job_id: str, facts: dict) -> dict:
        calls.append(facts)
        return outcome or {}

    agent.model_fallback = fallback
    job = store.create_job("chat", "일", {"prompt": "x", "origin": "workspace"})
    agent.__dict__["_job"] = job["id"]
    return agent, calls


def _audits(agent: BrowserAgent) -> list:
    return [row for row in agent.store.list_audit(limit=50) if row.get("event") == "agent_model_spill"] \
        if hasattr(agent.store, "list_audit") else []


def test_a_heavy_app_on_a_16gb_card_switches_even_when_the_numbers_look_fine(tmp_path: Path) -> None:
    agent, calls = _agent(tmp_path, card_gb=16.0, busy=["3ds Max"],
                          outcome={"action": "switched", "from": "swift", "to": "qwen3.6"})
    agent._warn_if_model_spills(agent.__dict__["_job"], "chat")
    assert len(calls) == 1 and calls[0]["heavy_running"] == ["3ds Max"]


def test_no_heavy_app_and_fine_numbers_means_nothing_happens(tmp_path: Path) -> None:
    agent, calls = _agent(tmp_path, card_gb=16.0, busy=[], outcome={"action": "switched"})
    agent._warn_if_model_spills(agent.__dict__["_job"], "chat")
    assert calls == []


def test_a_24gb_card_is_left_alone_with_a_heavy_app_open(tmp_path: Path) -> None:
    agent, calls = _agent(tmp_path, card_gb=24.0, busy=["3ds Max"], outcome={"action": "switched"})
    agent._warn_if_model_spills(agent.__dict__["_job"], "chat")
    assert calls == []


def test_already_on_the_fast_model_does_not_warn_every_job(tmp_path: Path) -> None:
    agent, calls = _agent(tmp_path, card_gb=16.0, busy=["Unity"], outcome={"action": "none", "why": "already_fast"})
    seen: list = []
    agent.events.publish = lambda name, payload: seen.append(name)  # type: ignore[method-assign]
    agent._warn_if_model_spills(agent.__dict__["_job"], "chat")
    assert len(calls) == 1 and "agent_model_spill" not in seen


def test_the_warning_names_the_app() -> None:
    text = BrowserAgent._gpu_warning(SimpleNamespace(_SPILL_WARN_BELOW=0.9), {"heavy_running": ["3ds Max", "Unity"]}, False)
    assert text.startswith("3ds Max · Unity 이(가) 켜져 있어") and "끄지 않습니다" in text


# ── 마법사 ─────────────────────────────────────────────────────────────

def _profile(vram_gb: float, heavy: list[str]) -> dict:
    return {
        "gpus": [{"index": 0, "name": "RTX 5070 Ti", "vram_total_gb": vram_gb, "vram_used_gb": 0.5,
                  "driver": "580.00", "display_active": False}],
        "gpu_error": "", "ram_gb": 32.0, "disk_free_gb": 200.0,
        "ollama": {"reachable": True, "installed": [], "vulkan_enabled": False},
        "heavy_apps": heavy,
    }


def test_the_wizard_says_to_also_get_the_fast_model_when_work_apps_are_installed() -> None:
    rec = sp.recommend(_profile(16.0, ["3ds Max", "Unity"]))
    line = next((r for r in rec["reasons"] if "깔려 있습니다" in r), "")
    assert "3ds Max · Unity" in line and "빠른 모델 받기" in line
    fast = next(p for p in rec["picks"] if p.get("role") == "fast")
    assert fast["heavy_apps"] == ["3ds Max", "Unity"]


@pytest.mark.parametrize("vram, heavy", [(16.0, []), (24.0, ["3ds Max"])])
def test_the_wizard_stays_quiet_otherwise(vram: float, heavy: list[str]) -> None:
    rec = sp.recommend(_profile(vram, heavy))
    assert not any("깔려 있습니다" in r for r in rec["reasons"])


def test_the_new_lines_have_english() -> None:
    from alture_jarvis import ui_i18n

    ui_i18n.reload()
    warn = BrowserAgent._gpu_warning(SimpleNamespace(_SPILL_WARN_BELOW=0.9), {"heavy_running": ["3ds Max"]}, False)
    assert ui_i18n.translate_text(warn).startswith("3ds Max is open")
    rec = sp.recommend(_profile(16.0, ["Blender"]))
    line = next(r for r in rec["reasons"] if "깔려 있습니다" in r)
    assert ui_i18n.translate_text(line).startswith("Blender is installed on this PC")


def test_without_psutil_it_asks_windows_instead(monkeypatch) -> None:  # noqa: ANN001
    """스토어 패키지에는 psutil 이 없다(`check_bundle.py` 선택 부품) — 0.4.37.0 첫 굽기에서 이 기능이 조용히 꺼져 있었다."""
    import builtins

    real_import = builtins.__import__

    def no_psutil(name, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if name == "psutil":
            raise ImportError("not bundled")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_psutil)
    monkeypatch.setattr(heavy_apps, "_powershell_processes", lambda: [("3dsmax.exe", r"C:\Autodesk\3dsmax.exe")])
    assert heavy_apps._processes() == [("3dsmax.exe", r"C:\Autodesk\3dsmax.exe")]
