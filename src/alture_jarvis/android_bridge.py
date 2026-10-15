"""Drive an Android device over ADB -- the transport under Mimo automation.

The Osmo Pocket 3 accepts no motor commands over BLE (verified against the real
camera: telemetry streams, every motor command shape is ignored, with and
without an active livestream). The one piece of software that can definitely
drive the gimbal is DJI's own Mimo app, so JARVIS drives that instead, on the
tablet, over wireless ADB.

Everything here resolves UI elements through uiautomator by resource-id,
content-desc or text -- never by hardcoded pixel coordinates. Coordinates read
as "working" right up until the tablet rotates, the launcher rescales, or Mimo
ships an update, and then they tap empty space forever while every call still
reports success.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")

# platform-tools ships as a zip with no installer, so adb is often not on
# PATH. Check standard per-user SDK locations before giving up. A packaged
# integration can still provide an explicit path through the main config.
ADB_SEARCH_PATHS = (
    Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe",
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    / "Android/Sdk/platform-tools/adb.exe",
)


def default_adb_path() -> str:
    found = shutil.which("adb")
    if found:
        return found
    for candidate in ADB_SEARCH_PATHS:
        if candidate.exists():
            return str(candidate)
    return ""


class AdbError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class UiNode:
    resource_id: str
    content_desc: str
    text: str
    klass: str
    clickable: bool
    enabled: bool
    bounds: tuple[int, int, int, int]

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.bounds
        return (left + right) // 2, (top + bottom) // 2

    @property
    def area(self) -> int:
        left, top, right, bottom = self.bounds
        return max(0, right - left) * max(0, bottom - top)

    def describe(self) -> str:
        label = self.resource_id or self.content_desc or self.text or self.klass
        return f"{label} @{self.center} {'' if self.clickable else '(not clickable)'}".strip()


def parse_bounds(value: str) -> tuple[int, int, int, int]:
    match = BOUNDS_RE.search(value or "")
    if not match:
        return (0, 0, 0, 0)
    left, top, right, bottom = (int(g) for g in match.groups())
    return (left, top, right, bottom)


def parse_ui_dump(xml_text: str) -> list[UiNode]:
    """Flatten a uiautomator dump into nodes we can search.

    The dump is a tree but nesting carries no meaning for us -- what matters is
    which node has the id we want and where it sits.
    """
    # Devices sometimes prefix the XML with a status line from the shell.
    start = xml_text.find("<?xml")
    if start > 0:
        xml_text = xml_text[start:]
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise AdbError(f"ui_dump_unparseable:{exc}") from exc

    nodes: list[UiNode] = []
    for element in root.iter("node"):
        get = element.attrib.get
        nodes.append(
            UiNode(
                resource_id=get("resource-id", ""),
                content_desc=get("content-desc", ""),
                text=get("text", ""),
                klass=get("class", ""),
                clickable=get("clickable", "false") == "true",
                enabled=get("enabled", "true") == "true",
                bounds=parse_bounds(get("bounds", "")),
            )
        )
    return nodes


def find_node(
    nodes: list[UiNode],
    *,
    resource_id: str = "",
    content_desc: str = "",
    text: str = "",
    clickable_only: bool = True,
) -> UiNode | None:
    """Match on whichever selector was given; substring for desc/text.

    resource-id is exact because ids are stable and unique; desc and text are
    substring and case-insensitive because they are user-facing strings that
    shift with locale and wording.
    """

    def matches(node: UiNode) -> bool:
        if clickable_only and not node.clickable:
            return False
        if resource_id and node.resource_id != resource_id:
            return False
        if content_desc and content_desc.lower() not in node.content_desc.lower():
            return False
        if text and text.lower() not in node.text.lower():
            return False
        return bool(resource_id or content_desc or text)

    candidates = [node for node in nodes if matches(node)]
    if not candidates:
        return None
    # Smallest match wins: a matching container usually encloses the real
    # control, and tapping the container's centre can land on a neighbour.
    return min(candidates, key=lambda node: node.area or 1 << 30)


class AndroidBridge:
    def __init__(
        self,
        *,
        adb_path: str = "",
        serial: str = "",
        host: str = "",
        port: int = 5555,
        timeout_sec: float = 20.0,
    ) -> None:
        self.adb_path = adb_path or default_adb_path()
        self.serial = serial
        self.host = host
        self.port = port
        self.timeout_sec = timeout_sec

    # ── plumbing ─────────────────────────────────────────────────────────────
    def available(self) -> dict[str, Any]:
        if not self.adb_path or not Path(self.adb_path).exists():
            return {"ok": False, "error": "adb_not_found"}
        return {"ok": True, "adb": self.adb_path}

    def _run(self, args: list[str], *, timeout: float | None = None, binary: bool = False) -> Any:
        if not self.adb_path:
            raise AdbError("adb_not_found")
        command = [self.adb_path]
        # ★ 시리얼이 비어 있으면 **명령을 내기 전에 정한다** (2026-08-14).
        #
        # 기기가 하나뿐이면 adb 가 알아서 고르지만, 둘이면
        # `more than one device/emulator` 로 **모든 명령이 죽는다.** 태블릿이
        # USB 로도 꽂히고 무선으로도 붙어 있으면 정확히 그 상태가 된다.
        #
        # 그날 실측: 런처에 박힌 IP 를 지웠더니(그건 맞는 일이었다) 시리얼이 비었고,
        # 그 순간 짐벌 영역 조회(`preview_region`)가 저 오류로 죽었다. 그리고 그것이
        # 화면 캡처를 같이 죽여서 결국 `no_frames` 였다 — "카메라 고장"으로 보인다.
        #
        # `connect()` 를 거치는 길만 탐색이 있었는데, `MimoController` 는 그걸 안 부른다.
        # 그래서 **명령이 나가는 길목**인 여기에 둔다. 한 번 정하면 그대로 쓴다.
        if not self.serial and args[:1] != ["devices"]:
            try:
                self.serial = self._attached_serial()
            except Exception:
                pass
        if self.serial:
            command += ["-s", self.serial]
        command += args
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout or self.timeout_sec,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or b"").decode("utf-8", "replace").strip()
            raise AdbError(f"adb_failed:{' '.join(args[:2])}:{detail[:300]}")
        return result.stdout if binary else result.stdout.decode("utf-8", "replace")

    def connect(self) -> dict[str, Any]:
        # ★ **이미 붙어 있는 기기가 있으면 그걸 쓴다** (2026-08-14).
        #
        # `_discover_host` 의 주석은 "USB 로 꽂혀 있으면 여기서 끝난다"였는데
        # **코드는 반대였다** — `":" in serial` 을 요구해서 네트워크 시리얼만 받았다.
        # USB 시리얼(`HA2B3MSC`)에는 콜론이 없으니 통째로 건너뛰었다.
        #
        # 실측(2026-08-14): 태블릿이 USB 로 멀쩡히 꽂혀 있는데(그리고 Wi-Fi 주소도
        # 192.168.1.50 로 살아 있는데) 자비스는 설정에 박힌 192.168.1.50 만 두드리며
        # `capture:tablet_screen_open_failed:no_frames` 를 반복했다. 화면에는
        # "카메라가 고장났다"로 보인다.
        #
        # USB 는 임대 주소가 없어 안 바뀐다. 있으면 그게 제일 확실한 길이다.
        attached = self._attached_serial()
        if attached:
            self.serial = attached
            if ":" in attached:
                self.host = attached.rsplit(":", 1)[0]
            return {"connected": True, "serial": self.serial, "devices": self.devices()}
        if self.host:
            try:
                self._connect_to(self.host)
            except AdbError:
                # ★ 주소를 외우지 않는다. 태블릿 IP 는 DHCP 임대라 언젠가 반드시
                #   바뀌고, 그날 증상은 "카메라가 고장났다"로 보인다.
                #   2026-08-06 실측: 설정은 192.168.1.50 인데 태블릿은 192.168.1.50
                #   에 있었다. 그 사이 자비스는 몇 시간 동안 재접속만 반복하며
                #   에러 로그를 45MB 쌓았고, 프레임은 한 장도 못 받았다.
                found = self._discover_host()
                if not found:
                    raise
                self._connect_to(found)
                self.host = found
            if not self.serial:
                self.serial = f"{self.host}:{self.port}"
        return {"connected": True, "serial": self.serial, "devices": self.devices()}

    def _connect_to(self, host: str) -> None:
        output = self._run(["connect", f"{host}:{self.port}"], timeout=25.0)
        # adb connect exits 0 even when it failed to reach the device, so
        # the text is the only signal that this worked.
        if "cannot" in output.lower() or "failed" in output.lower():
            raise AdbError(f"adb_connect_refused:{output.strip()[:200]}")

    def _attached_serial(self) -> str:
        """지금 `adb devices` 에 **살아 있는** 기기 시리얼. 없으면 빈 문자열.

        네트워크로 붙은 것(`192.168.1.50:5555`)과 USB 로 꽂힌 것(`HA2B3MSC`)을
        **둘 다** 받는다. 예전에는 콜론이 있는 것만 받아서, USB 로 꽂혀 있어도
        못 본 채로 없는 IP 를 계속 두드렸다.

        설정에 시리얼이 박혀 있고 그게 지금 살아 있으면 그것을 그대로 쓴다 —
        기기가 둘 이상 붙어 있을 때 엉뚱한 쪽을 잡지 않기 위해서다.
        """
        rows = [row for row in self.devices() if row.get("state") == "device"]
        serials = [str(row.get("serial") or "") for row in rows]
        if self.serial and self.serial in serials:
            return self.serial
        # 네트워크 쪽을 먼저 본다: 태블릿이 벽에 걸린 채 USB 는 안 꽂힌 것이 평소
        # 모습이고, USB 는 사람이 잠깐 꽂아 둔 상태일 때가 많다.
        for serial in serials:
            if ":" in serial:
                return serial
        return serials[0] if serials else ""

    def _discover_host(self) -> str:
        """설정된 주소에 없을 때 태블릿을 실제로 찾는다.

        찾는 순서가 곧 확실한 순서다:
          1. 이미 네트워크로 붙어 있는 기기 (USB 는 `_attached_serial` 이 먼저 잡는다)
          2. 같은 대역에서 5555 가 열린 주소 (무선 adb 는 그 포트로만 뜬다)

        대역은 이 PC 의 주소에서 가져온다. 못 박아 두면 사무실을 옮긴 날 또 깨진다.
        """
        for row in self.devices():
            serial = str(row.get("serial") or "")
            if row.get("state") == "device" and ":" in serial:
                return serial.rsplit(":", 1)[0]

        import concurrent.futures
        import socket

        prefixes = []
        for family, _, _, _, address in socket.getaddrinfo(socket.gethostname(), None):
            if family == socket.AF_INET:
                octets = str(address[0]).split(".")
                if len(octets) == 4 and not octets[0].startswith("127"):
                    prefixes.append(".".join(octets[:3]))
        if self.host:
            prefixes.insert(0, ".".join(self.host.split(".")[:3]))

        def probe(address: str) -> str:
            try:
                with socket.create_connection((address, self.port), timeout=0.4):
                    return address
            except OSError:
                return ""

        for prefix in dict.fromkeys(prefixes):
            candidates = [f"{prefix}.{n}" for n in range(1, 255)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
                for address in pool.map(probe, candidates):
                    if address:
                        return address
        return ""

    def devices(self) -> list[dict[str, str]]:
        rows = []
        for line in self._run(["devices", "-l"]).splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            rows.append({"serial": parts[0], "state": parts[1] if len(parts) > 1 else ""})
        return rows

    def shell(self, command: str, *, timeout: float | None = None) -> str:
        return self._run(["shell", command], timeout=timeout)

    # ── input ────────────────────────────────────────────────────────────────
    def tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {int(x)} {int(y)}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}")

    def hold_drag(self, x1: int, y1: int, x2: int, y2: int, seconds: float) -> None:
        """Press, move, hold, release -- what `swipe` cannot do.

        `input swipe` interpolates to the end point and lets go immediately, so
        a control that responds to sustained pressure (a joystick) only gets a
        flick. Measured on Mimo's gimbal stick, holding moves the camera about
        1.6x as far as the equivalent swipe.

        Each `input` call is a separate process, so the three events carry
        different down-times. Android still threads them into one gesture on the
        touchscreen device; if a future release stops doing so, this degrades
        into the same flick `swipe` gives rather than failing loudly, so verify
        against the preview rather than trusting the exit code.
        """
        self.shell(f"input motionevent DOWN {int(x1)} {int(y1)}")
        try:
            self.shell(f"input motionevent MOVE {int(x2)} {int(y2)}")
            time.sleep(max(0.0, seconds))
        finally:
            # Never leave the pointer down: a stuck DOWN keeps the gimbal
            # sweeping and blocks every later touch on the device.
            self.shell(f"input motionevent UP {int(x2)} {int(y2)}")

    def key(self, keycode: str) -> None:
        self.shell(f"input keyevent {keycode}")

    def is_dreaming(self) -> bool:
        """Is a screensaver/daydream holding the foreground?"""
        focus = self.shell("dumpsys window | grep -E 'mCurrentFocus'").lower()
        return "dream" in focus or "screensaver" in focus

    def wake(self) -> None:
        """Wake and unlock far enough for the UI to be tappable.

        A tablet on a charging stand blanks its screen, and every tap sent to a
        blank screen succeeds and does nothing.
        """
        self.shell("input keyevent KEYCODE_WAKEUP")
        self.shell("input keyevent KEYCODE_MENU")
        # A screensaver survives WAKEUP: the screen is already on and the dream
        # is a real foreground activity, so the device looks awake while every
        # tap lands on the screensaver instead of the app. BACK dismisses it --
        # measured on the Lenovo tab, where WAKEUP alone did nothing.
        if self.is_dreaming():
            self.shell("input keyevent KEYCODE_BACK")
            time.sleep(0.8)

    def screen_on(self) -> bool:
        output = self.shell("dumpsys power | grep -E 'mWakefulness='")
        return "Awake" in output

    def screen_size(self) -> tuple[int, int]:
        output = self.shell("wm size")
        match = re.search(r"(\d+)x(\d+)", output)
        if not match:
            raise AdbError("screen_size_unavailable")
        return int(match.group(1)), int(match.group(2))

    # ── apps ─────────────────────────────────────────────────────────────────
    def current_app(self) -> str:
        output = self.shell(
            "dumpsys window 2>/dev/null | grep -E 'mCurrentFocus|mFocusedApp' || "
            "dumpsys activity activities | grep -E 'ResumedActivity'"
        )
        match = re.search(r"([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)", output)
        return match.group(1) if match else ""

    def is_installed(self, package: str) -> bool:
        return package in self.shell(f"pm list packages {package}")

    def launch(self, package: str) -> None:
        self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")

    # ── UI ───────────────────────────────────────────────────────────────────
    def ui_dump(self, *, retries: int = 5) -> list[UiNode]:
        """Read the current screen's accessibility tree.

        uiautomator refuses while the screen is mid-animation, so a single
        failure means "try again", not "the screen has no elements".

        It also loses races against `screenrecord`: with the screen capture
        running, dumps succeeded 8 times in 12 against 11-12 with it off, and
        the loser exits non-zero with an empty stderr.

        Those failures are *correlated*, not independent -- five attempts in
        quick succession all failed once, and a plain dump seconds later
        worked. Something stays busy for a while. So the backoff is wide rather
        than the retry count high: retrying faster just spends the attempts
        inside the same bad window. A dump only happens when MimoController's
        cached screen has expired, so waiting is cheap and losing is not.
        """
        last: Exception | None = None
        for attempt in range(retries):
            try:
                raw = self.shell("uiautomator dump /dev/tty 2>/dev/null", timeout=30.0)
                if "<?xml" in raw:
                    return parse_ui_dump(raw)
                self.shell("uiautomator dump /sdcard/jarvis-ui.xml", timeout=30.0)
                raw = self.shell("cat /sdcard/jarvis-ui.xml", timeout=30.0)
                return parse_ui_dump(raw)
            except (AdbError, subprocess.TimeoutExpired) as exc:
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise AdbError(f"ui_dump_failed:{last}")

    def find(self, **selector: Any) -> UiNode | None:
        return find_node(self.ui_dump(), **selector)

    def tap_element(self, **selector: Any) -> UiNode:
        node = self.find(**selector)
        if node is None:
            raise AdbError(f"ui_element_not_found:{selector}")
        x, y = node.center
        self.tap(x, y)
        return node

    def screenshot(self, destination: Path) -> Path:
        data = self._run(["exec-out", "screencap", "-p"], timeout=40.0, binary=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return destination

    def status(self) -> dict[str, Any]:
        info = self.available()
        if not info["ok"]:
            return {**info, "connected": False}
        try:
            devices = self.devices()
        except Exception as exc:
            return {**info, "connected": False, "error": str(exc)}
        online = [d for d in devices if d["state"] == "device"]
        return {
            **info,
            "connected": bool(online),
            "devices": devices,
            "serial": self.serial,
        }
