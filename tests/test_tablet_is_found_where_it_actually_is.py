"""태블릿이 **눈앞에 꽂혀 있는데** 없는 IP 를 두드리면 "카메라 고장"으로 보인다.

## 실측 (2026-08-14)

    자비스 vision status
      source : tablet_screen
      serial : 192.168.0.68:5555
      error  : capture:tablet_screen_open_failed:no_frames
      reconnecting: true

    실제
      adb devices        HA2B3MSC  device  (TB373FU, **USB 로 꽂혀 있음**)
      태블릿 wlan0       192.168.0.98
      ping 192.168.0.68   100% 손실

설정에 박힌 주소는 죽었고, 태블릿은 USB 로 꽂힌 채 Wi-Fi 주소도 바뀌어 있었다.

## 주석과 코드가 어긋나 있었다

`_discover_host` 의 1번 규칙은 이렇게 적혀 있었다:

    1. 이미 붙어 있는 기기 (USB 로 꽂혀 있으면 여기서 끝난다)

그런데 코드는 `":" in serial` 을 요구했다. **USB 시리얼에는 콜론이 없다.**
그래서 "여기서 끝난다"는 자리가 실제로는 언제나 건너뛰어졌다.

DHCP 임대 주소는 언젠가 반드시 바뀐다(2026-08-06 에도 같은 일이 있었다 —
설정 192.168.0.44 / 실제 192.168.0.68). **USB 는 안 바뀐다.**
"""

from __future__ import annotations

from typing import Any

from alture_jarvis.android_bridge import AndroidBridge


class _Bridge(AndroidBridge):
    """`devices()` 만 흉내 낸다 — 진짜 adb 는 안 부른다."""

    def __init__(self, rows: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(adb_path="adb", **kwargs)
        self._rows = rows
        self.connect_calls: list[str] = []

    def devices(self) -> list[dict[str, Any]]:  # type: ignore[override]
        return self._rows

    def _connect_to(self, host: str) -> None:  # type: ignore[override]
        self.connect_calls.append(host)


USB = {"serial": "HA2B3MSC", "state": "device"}
WIFI = {"serial": "192.168.0.98:5555", "state": "device"}
OFFLINE = {"serial": "192.168.0.68:5555", "state": "offline"}


def test_a_usb_tablet_is_used_instead_of_a_dead_ip() -> None:
    """★ 이것이 이 시험의 요점이다.

    설정에는 죽은 주소가 박혀 있고, 태블릿은 USB 로 꽂혀 있다. 예전 코드는
    콜론이 없다는 이유로 USB 를 건너뛰고 죽은 주소만 두드렸다.
    """
    bridge = _Bridge([USB], host="192.168.0.68")

    result = bridge.connect()

    assert result["serial"] == "HA2B3MSC"
    assert bridge.connect_calls == [], "USB 가 있는데 네트워크로 붙으려 했다"


def test_a_live_network_device_is_preferred_over_usb() -> None:
    """평소 모습은 벽에 걸린 태블릿이고, USB 는 사람이 잠깐 꽂아 둔 것이다."""
    bridge = _Bridge([USB, WIFI], host="192.168.0.68")

    assert bridge.connect()["serial"] == "192.168.0.98:5555"
    assert bridge.host == "192.168.0.98", "호스트도 실제 주소로 따라가야 한다"


def test_an_offline_row_is_not_a_device() -> None:
    """`adb devices` 는 죽은 것도 줄에 남긴다. 그걸 잡으면 또 no_frames 다."""
    bridge = _Bridge([OFFLINE], host="192.168.0.68")

    bridge.connect()

    assert bridge.connect_calls == ["192.168.0.68"], "죽은 줄을 살아 있는 기기로 봤다"


def test_a_configured_serial_wins_when_it_is_alive() -> None:
    """기기가 둘 이상일 때 엉뚱한 쪽을 잡으면 안 된다."""
    bridge = _Bridge([USB, WIFI], serial="HA2B3MSC")

    assert bridge.connect()["serial"] == "HA2B3MSC"


def test_nothing_attached_falls_back_to_the_configured_host() -> None:
    """아무것도 안 붙어 있으면 예전 길 그대로 — 설정 주소로 붙어 본다."""
    bridge = _Bridge([], host="192.168.0.68")

    bridge.connect()

    assert bridge.connect_calls == ["192.168.0.68"]
