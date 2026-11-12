"""11-11 측정용 스위치 — 작은 창 조사 묶음에 손을 더 싣는다(기본 비어 있음 = 동작 같음). 양방향."""
from __future__ import annotations

from alture_jarvis.tool_roster import _small_window_research_tools


def _tools(*names: str) -> list[dict]:
    return [{"type": "function", "function": {"name": name}} for name in names]


ALL = _tools("browser_open", "browser_read", "browser_annotate", "browser_screenshot", "local_write_document")


def _names(tools):
    return [t["function"]["name"] for t in tools]


def test_default_bundle_has_no_annotate() -> None:
    kept = _small_window_research_tools(ALL, enabled=True, compact=True, web_research=True)
    assert "browser_annotate" not in _names(kept) and "browser_open" in _names(kept)


def test_extra_switch_adds_annotate_and_keeps_order() -> None:
    kept = _small_window_research_tools(ALL, enabled=True, compact=True, web_research=True, extra=("browser_annotate",))
    assert _names(kept) == ["browser_open", "browser_read", "browser_annotate", "local_write_document"]


def test_config_reads_the_switch(monkeypatch) -> None:
    from alture_jarvis import config as cfg

    assert cfg.JarvisConfig().small_window_extra_tools == ()
    monkeypatch.setattr(cfg, "_env", lambda name, default="": "browser_annotate, browser_screenshot" if name == "JARVIS_SMALL_WINDOW_EXTRA_TOOLS" else default)
    assert cfg.JarvisConfig.from_env().small_window_extra_tools == ("browser_annotate", "browser_screenshot")
