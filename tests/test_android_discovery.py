"""태블릿 주소를 외우지 않는다.

2026-08-06 실측: 설정에는 192.168.0.44 로 박혀 있는데 태블릿은 192.168.0.68 에 있었다.
DHCP 임대라 언젠가 반드시 바뀌는 값인데, 바뀐 날의 증상은 "카메라가 고장났다"로
보인다 — 자비스는 몇 시간 동안 재접속만 반복하며 에러 로그를 45MB 쌓았고 프레임은
한 장도 못 받았다. `task_entry.py` 주석에도 "이걸 먼저 확인하라"고 적혀 있었다.
적어 두는 것으로는 안 고쳐진다.

찾는 순서가 곧 확실한 순서다: 이미 붙어 있는 기기 -> 같은 대역의 5555 포트.
"""

from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis.android_bridge import AdbError, AndroidBridge


class _Bridge(AndroidBridge):
    """adb 를 부르지 않고, 무엇을 시도했는지만 기록한다."""

    def __init__(self, *, reachable: str = "", devices: list[dict[str, str]] | None = None, **kwargs: Any) -> None:
        super().__init__(adb_path="adb", **kwargs)
        self.reachable = reachable
        self._devices = devices or []
        self.attempts: list[str] = []
        self.scanned: list[str] = []

    def _connect_to(self, host: str) -> None:
        self.attempts.append(host)
        if host != self.reachable:
            raise AdbError(f"adb_connect_refused:{host}")

    def devices(self) -> list[dict[str, str]]:
        return list(self._devices)


def test_the_configured_address_is_tried_first(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _Bridge(host="192.168.0.44", reachable="192.168.0.44")

    result = bridge.connect()

    assert bridge.attempts == ["192.168.0.44"]
    assert result["serial"] == "192.168.0.44:5555"


def test_a_device_already_attached_wins_before_anything_else() -> None:
    """USB 로 꽂혀 있거나 이미 무선으로 붙어 있으면 **아무것도 더 할 이유가 없다.**

    ★ 2026-08-14 에 계약이 한 걸음 더 갔다. 예전에는 살아 있는 기기를 두고도
    설정 주소를 **먼저** 두드렸다(위 `attempts` 에 192.168.0.44 가 있었다).
    죽은 주소에 붙는 시도는 25초 타임아웃이라, 그 한 줄이 매번 25초였다.

    그리고 같은 날 더 나쁜 것이 드러났다 — 그 뒤의 탐색은 `":" in serial` 을
    요구해서 **USB 시리얼(`HA2B3MSC`)을 통째로 건너뛰었다.** 태블릿이 눈앞에
    꽂혀 있는데 자비스는 없는 IP 만 두드리며 `no_frames` 를 반복했고, 화면에는
    "카메라가 고장났다"로 보였다.

    이 시험의 원래 설명("대역을 훑을 이유가 없다")이 이미 그 방향이었다.
    """
    bridge = _Bridge(
        host="192.168.0.44",
        reachable="192.168.0.68",
        devices=[{"serial": "192.168.0.68:5555", "state": "device"}],
    )

    result = bridge.connect()

    assert bridge.attempts == [], "살아 있는 기기를 두고 죽은 주소를 먼저 두드렸다"
    assert result["serial"] == "192.168.0.68:5555"
    assert bridge.host == "192.168.0.68"


def test_a_usb_serial_counts_as_attached() -> None:
    """콜론이 없다는 이유로 USB 를 건너뛰던 것이 그날의 진짜 원인이다."""
    bridge = _Bridge(
        host="192.168.0.44",
        reachable="",
        devices=[{"serial": "HA2B3MSC", "state": "device"}],
    )

    assert bridge.connect()["serial"] == "HA2B3MSC"
    assert bridge.attempts == []


def test_an_offline_device_row_is_not_trusted() -> None:
    bridge = _Bridge(
        host="192.168.0.44",
        reachable="",
        devices=[{"serial": "192.168.0.99:5555", "state": "offline"}],
    )
    bridge._discover_host = lambda: ""  # type: ignore[method-assign]

    with pytest.raises(AdbError):
        bridge.connect()


def test_it_gives_up_honestly_when_nothing_answers() -> None:
    """못 찾으면 원래 오류를 그대로 올린다 — 조용히 성공한 척하면 그 다음이 더 나쁘다."""
    bridge = _Bridge(host="192.168.0.44", reachable="")
    bridge._discover_host = lambda: ""  # type: ignore[method-assign]

    with pytest.raises(AdbError, match="adb_connect_refused"):
        bridge.connect()


def test_no_host_means_usb_and_needs_no_discovery() -> None:
    bridge = _Bridge(host="", serial="HA2B3MSC")

    result = bridge.connect()

    assert bridge.attempts == []
    assert result["serial"] == "HA2B3MSC"
