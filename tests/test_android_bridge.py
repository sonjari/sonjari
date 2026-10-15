from __future__ import annotations

import pytest

from alture_jarvis.android_bridge import (
    AdbError,
    AndroidBridge,
    UiNode,
    find_node,
    parse_bounds,
    parse_ui_dump,
)

# Trimmed from a real uiautomator dump: a container that encloses the actual
# button, which is exactly the shape that makes naive matching tap the wrong
# spot.
DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" resource-id="" content-desc="" text=""
        clickable="false" enabled="true" bounds="[0,0][2000,1200]">
    <node class="android.widget.FrameLayout" resource-id="dji.go.v5:id/live_panel"
          content-desc="Live panel" text="" clickable="true" enabled="true"
          bounds="[100,100][900,700]">
      <node class="android.widget.Button" resource-id="dji.go.v5:id/btn_live_start"
            content-desc="Start Live" text="라이브 시작" clickable="true" enabled="true"
            bounds="[300,300][500,400]"/>
    </node>
    <node class="android.widget.Button" resource-id="dji.go.v5:id/btn_recenter"
          content-desc="Recenter gimbal" text="" clickable="true" enabled="false"
          bounds="[1500,900][1700,1000]"/>
  </node>
</hierarchy>"""


def test_parse_bounds() -> None:
    assert parse_bounds("[100,200][300,450]") == (100, 200, 300, 450)
    assert parse_bounds("garbage") == (0, 0, 0, 0)


def test_parse_dump_reads_every_node() -> None:
    nodes = parse_ui_dump(DUMP)
    ids = {node.resource_id for node in nodes}
    assert "dji.go.v5:id/btn_live_start" in ids
    assert "dji.go.v5:id/btn_recenter" in ids


def test_parse_dump_tolerates_a_shell_prefix() -> None:
    # `uiautomator dump /dev/tty` prints a status line before the XML, and
    # feeding that straight to an XML parser fails on a perfectly good dump.
    nodes = parse_ui_dump("UI hierchary dumped to: /dev/tty\r\n" + DUMP)
    assert any(node.resource_id.endswith("btn_live_start") for node in nodes)


def test_find_prefers_the_smallest_match_not_the_container() -> None:
    # Both the panel and the button carry "Live" in their description. Tapping
    # the panel's centre would miss the button entirely.
    nodes = parse_ui_dump(DUMP)
    node = find_node(nodes, content_desc="Live")
    assert node is not None
    assert node.resource_id == "dji.go.v5:id/btn_live_start"
    assert node.center == (400, 350)


def test_find_by_exact_resource_id() -> None:
    node = find_node(parse_ui_dump(DUMP), resource_id="dji.go.v5:id/btn_live_start")
    assert node is not None and node.text == "라이브 시작"


def test_find_ignores_non_clickable_nodes_by_default() -> None:
    nodes = parse_ui_dump(DUMP)
    assert find_node(nodes, text="라이브") is not None
    root = find_node(nodes, resource_id="", clickable_only=False)
    assert root is None  # an empty selector must never match everything


def test_find_returns_none_rather_than_guessing() -> None:
    assert find_node(parse_ui_dump(DUMP), resource_id="nope") is None


def test_disabled_elements_are_still_found_so_the_caller_can_report_why() -> None:
    node = find_node(parse_ui_dump(DUMP), resource_id="dji.go.v5:id/btn_recenter")
    assert node is not None
    assert node.enabled is False


def test_unparseable_dump_raises_instead_of_returning_nothing() -> None:
    # Silently returning [] here would read as "the screen is empty" and send
    # the caller looking for a missing button that is right there.
    with pytest.raises(AdbError):
        parse_ui_dump("not xml at all")


def test_status_reports_a_missing_adb_without_raising(tmp_path) -> None:
    # An explicit bad path, not "": an empty path now falls through to
    # auto-discovery, which finds the real adb and would make this pass for
    # entirely the wrong reason.
    bridge = AndroidBridge(adb_path=str(tmp_path / "no-such-adb.exe"))
    status = bridge.status()
    assert status["ok"] is False
    assert status["connected"] is False
    assert status["error"] == "adb_not_found"


def test_tap_element_raises_when_the_control_is_absent(monkeypatch) -> None:
    bridge = AndroidBridge(adb_path="adb")
    monkeypatch.setattr(bridge, "ui_dump", lambda **_: parse_ui_dump(DUMP))
    tapped: list[tuple[int, int]] = []
    monkeypatch.setattr(bridge, "tap", lambda x, y: tapped.append((x, y)))

    node = bridge.tap_element(resource_id="dji.go.v5:id/btn_live_start")
    assert tapped == [(400, 350)]
    assert node.center == (400, 350)

    with pytest.raises(AdbError):
        bridge.tap_element(resource_id="dji.go.v5:id/does_not_exist")
    assert len(tapped) == 1


def test_wake_dismisses_a_screensaver(monkeypatch) -> None:
    # A daydream survives KEYCODE_WAKEUP: the screen is already on and the
    # dream is a real foreground activity, so the tablet looks awake while
    # every tap lands on the screensaver and does nothing.
    bridge = AndroidBridge(adb_path="adb")
    sent: list[str] = []
    dreaming = {"value": True}

    def fake_shell(command: str, **_: object) -> str:
        sent.append(command)
        if "mCurrentFocus" in command:
            return (
                "mCurrentFocus=Window{f0 u0 com.lenovo.screensaver/android.service.dreams.DreamActivity}"
                if dreaming["value"]
                else "mCurrentFocus=Window{f0 u0 mimo.sz/mimo.sz.MainActivity}"
            )
        if "KEYCODE_BACK" in command:
            dreaming["value"] = False
        return ""

    monkeypatch.setattr(bridge, "shell", fake_shell)
    bridge.wake()
    assert any("KEYCODE_BACK" in command for command in sent)

    sent.clear()
    bridge.wake()
    # Already awake in the app -- no stray BACK, which would navigate the app.
    assert not any("KEYCODE_BACK" in command for command in sent)


def test_ui_node_center_and_describe() -> None:
    node = UiNode("id/x", "desc", "text", "android.widget.Button", True, True, (10, 20, 30, 60))
    assert node.center == (20, 40)
    assert node.area == 800
    assert "id/x" in node.describe()
