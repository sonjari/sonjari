"""DJI DUML over BLE for the Osmo Pocket 3 -- gimbal control from this PC.

The Pocket 3 exposes no public SDK. This speaks the same binary protocol the
DJI Mimo app does, reconstructed from community packet captures
(github.com/yigitkonur/lib-osmo-ble). Frames are byte-identical to that
implementation, which is checked against known-good captured frames in
tests/test_osmo_ble.py -- a single wrong CRC bit and the camera drops the frame
in silence, with no error anywhere, so those vectors are the only thing
standing between "working" and "looks fine but does nothing".

Known limitation, reported upstream and not yet disproved here: the Pocket 3
accepts and parses gimbal motor commands over BLE but ignores them unless a
WiFi streaming session is already active. Telemetry streams regardless. Since
the office rig keeps a Mimo livestream running, that precondition may be met --
`scripts/verify_osmo_ble.py` is what answers it against real hardware.
"""

from __future__ import annotations

import asyncio
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# ─── Device addresses ────────────────────────────────────────────────────────
ADDR_APP = 0x02
ADDR_GIMBAL = 0x04
ADDR_WIFI = 0x07
ADDR_CAMERA = 0x01

TARGET_APP_TO_GIMBAL = ADDR_APP | (ADDR_GIMBAL << 8)
TARGET_APP_TO_WIFI = ADDR_APP | (ADDR_WIFI << 8)

FLAG_REQUEST = 0x40
FLAG_RESPONSE = 0xC0
FLAG_NOTIFY = 0x00

CMD_SET_GIMBAL = 0x04
CMD_SET_WIFI = 0x07

GIMBAL_CONTROL_PWM = 0x01
GIMBAL_PARAMS_GET = 0x05
GIMBAL_ANGLE_SET = 0x0A
GIMBAL_SPEED_CTRL = 0x0C
GIMBAL_ABS_ANGLE = 0x14
GIMBAL_MOVEMENT = 0x15
GIMBAL_SET_MODE = 0x4C

WIFI_SET_PAIRING_PIN = 0x45
WIFI_PAIRING_APPROVED = 0x46

GIMBAL_MODES = {"lock": 0, "follow": 1, "fpv": 2}

# 16-bit UUIDs as advertised; bleak wants the full 128-bit form on Windows.
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY = "0000fff4-0000-1000-8000-00805f9b34fb"  # inbound DUML + pairing
CHAR_WRITE = "0000fff5-0000-1000-8000-00805f9b34fb"  # outbound DUML

HEADER_LEN = 11
TRAILER_LEN = 2
MIN_FRAME_LEN = HEADER_LEN + TRAILER_LEN


def _reflect(value: int, width: int) -> int:
    result = 0
    for _ in range(width):
        result = (result << 1) | (value & 1)
        value >>= 1
    return result


def _crc(data: bytes, *, width: int, poly: int, init: int) -> int:
    """Rocksoft CRC with refIn=refOut=true, xorOut=0 -- DJI's two variants.

    Written out longhand rather than table-driven: these run on frames of a few
    dozen bytes at human button-press rates, and a wrong table is much harder to
    spot than a wrong loop.
    """
    top = 1 << (width - 1)
    mask = (1 << width) - 1
    crc = init
    for byte in data:
        crc ^= _reflect(byte, 8) << (width - 8)
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & mask if crc & top else (crc << 1) & mask
    return _reflect(crc, width)


def crc8(data: bytes) -> int:
    return _crc(data, width=8, poly=0x31, init=0xEE)


def crc16(data: bytes) -> int:
    return _crc(data, width=16, poly=0x1021, init=0x496C)


def pack_string(text: str) -> bytes:
    """DJI's length-prefixed string, used by the pairing payloads."""
    raw = text.encode("utf-8")
    return bytes([len(raw)]) + raw


@dataclass(frozen=True, slots=True)
class DumlMessage:
    sender: int
    receiver: int
    msg_id: int
    flags: int
    cmd_set: int
    cmd_id: int
    payload: bytes


def build_message(
    target: int,
    flags: int,
    cmd_set: int,
    cmd_id: int,
    payload: bytes = b"",
    *,
    msg_id: int,
) -> bytes:
    total_len = MIN_FRAME_LEN + len(payload)
    if total_len > 0x3FF:
        raise ValueError("duml_payload_too_long")

    version = 1
    head = bytes([0x55, total_len & 0xFF, ((total_len >> 8) & 0x03) | (version << 2)])
    frame = bytearray(head)
    frame.append(crc8(head))
    frame += struct.pack("<H", target)
    # The only big-endian field in the frame. Getting this backwards produces a
    # frame that still passes both CRCs and is still ignored.
    frame += struct.pack(">H", msg_id & 0xFFFF)
    frame += bytes([flags, cmd_set, cmd_id])
    frame += payload
    frame += struct.pack("<H", crc16(bytes(frame)))
    return bytes(frame)


def parse_message(data: bytes) -> DumlMessage | None:
    if len(data) < MIN_FRAME_LEN or data[0] != 0x55:
        return None
    declared = data[1] | ((data[2] & 0x03) << 8)
    if declared < MIN_FRAME_LEN or len(data) < declared:
        return None
    return DumlMessage(
        sender=data[4],
        receiver=data[5],
        msg_id=struct.unpack(">H", data[6:8])[0],
        flags=data[8],
        cmd_set=data[9],
        cmd_id=data[10],
        payload=bytes(data[HEADER_LEN : declared - TRAILER_LEN]),
    )


def parse_stream(buffer: bytes) -> tuple[list[DumlMessage], bytes]:
    """Split a BLE notification buffer into frames, keeping any partial tail.

    Notifications are not frame-aligned: one packet can carry several frames or
    half of one, so the leftover has to survive to the next callback.
    """
    messages: list[DumlMessage] = []
    view = buffer
    while len(view) >= MIN_FRAME_LEN:
        start = view.find(0x55)
        if start == -1:
            return messages, b""
        if start:
            view = view[start:]
            continue
        declared = view[1] | ((view[2] & 0x03) << 8)
        if declared < MIN_FRAME_LEN or declared > 1024:
            view = view[1:]
            continue
        if len(view) < declared:
            break
        message = parse_message(view[:declared])
        if message is not None:
            messages.append(message)
        view = view[declared:]
    return messages, view


@dataclass
class GimbalState:
    pitch: float = 0.0
    roll: float = 0.0
    yaw: float = 0.0
    mode: int | None = None
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pitch": self.pitch,
            "roll": self.roll,
            "yaw": self.yaw,
            "mode": self.mode,
            "updated_at": self.updated_at,
            "age_sec": round(time.time() - self.updated_at, 2) if self.updated_at else None,
        }


class OsmoGimbalCommands:
    """Payload encoders. Separated from transport so they can be tested offline."""

    @staticmethod
    def speed(pitch_dps: float = 0.0, yaw_dps: float = 0.0, roll_dps: float = 0.0) -> tuple[int, bytes]:
        payload = struct.pack(
            "<hhhB",
            round(pitch_dps * 10),
            round(roll_dps * 10),
            round(yaw_dps * 10),
            0x01,
        )
        return GIMBAL_SPEED_CTRL, payload

    @staticmethod
    def absolute_angle(pitch: float, roll: float = 0.0, yaw: float = 0.0, duration_sec: float = 2.0) -> tuple[int, bytes]:
        payload = struct.pack(
            "<hhhBB",
            round(pitch * 10),
            round(roll * 10),
            round(yaw * 10),
            0x07,  # all three axes enabled
            min(255, round(duration_sec * 10)),
        )
        return GIMBAL_ABS_ANGLE, payload

    @staticmethod
    def move(pitch_delta: float, roll_delta: float = 0.0, yaw_delta: float = 0.0, speed_percent: int = 50) -> tuple[int, bytes]:
        def clamp(value: float) -> int:
            return max(-127, min(127, round(value)))

        payload = bytearray(20)
        struct.pack_into("<bbb", payload, 0, clamp(pitch_delta), clamp(roll_delta), clamp(yaw_delta))
        payload[6] = max(0, min(100, speed_percent))
        payload[7] = max(0, min(100, speed_percent))
        return GIMBAL_MOVEMENT, bytes(payload)

    @staticmethod
    def set_mode(mode: str | int) -> tuple[int, bytes]:
        value = GIMBAL_MODES[mode] if isinstance(mode, str) else int(mode)
        if value not in GIMBAL_MODES.values():
            raise ValueError(f"unknown_gimbal_mode:{mode}")
        return GIMBAL_SET_MODE, bytes([value, 0])

    @staticmethod
    def pwm(pitch: int = 1024, roll: int = 1024, yaw: int = 1024) -> tuple[int, bytes]:
        def clamp(value: int) -> int:
            return max(363, min(1685, round(value)))

        return GIMBAL_CONTROL_PWM, struct.pack("<HHH", clamp(pitch), clamp(roll), clamp(yaw))


class OsmoBleLink:
    """Owns the BLE connection on its own asyncio loop in a background thread.

    The JARVIS runtime is threaded and synchronous while bleak is asyncio-only,
    so the loop lives here and every public method is an ordinary blocking call.
    """

    def __init__(
        self,
        *,
        address: str = "",
        name_prefix: str = "Osmo",
        pairing_pin: str = "love",
        identifier: str = "001749319286102",
        connect_timeout_sec: float = 20.0,
        on_state: Callable[[GimbalState], None] | None = None,
    ) -> None:
        self.address = address
        self.name_prefix = name_prefix
        self.pairing_pin = pairing_pin
        self.identifier = identifier
        self.connect_timeout_sec = connect_timeout_sec
        self._on_state = on_state

        self.state = GimbalState()
        self._client: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._rx_buffer = b""
        self._seq = 0x0100
        self._lock = threading.Lock()
        self._last_error = ""
        self._acks: list[DumlMessage] = field(default_factory=list)  # type: ignore[assignment]
        self._acks = []

    # ── lifecycle ────────────────────────────────────────────────────────────
    @staticmethod
    def dependency_status() -> dict[str, Any]:
        try:
            import bleak  # noqa: F401
        except ImportError as exc:
            return {"ok": False, "error": f"dependency_missing:{exc.name}"}
        return {"ok": True}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run_loop, name="jarvis-osmo-ble", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise RuntimeError("osmo_ble_loop_did_not_start")

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def _submit(self, coro: Any, timeout: float) -> Any:
        if self._loop is None:
            raise RuntimeError("osmo_ble_not_started")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def stop(self) -> None:
        if self._loop is None:
            return
        try:
            self._submit(self._disconnect(), timeout=10.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5.0)
        self._loop = None
        self._thread = None

    # ── discovery / connection ───────────────────────────────────────────────
    def scan(self, timeout_sec: float = 10.0) -> list[dict[str, str]]:
        self.start()
        return self._submit(self._scan(timeout_sec), timeout=timeout_sec + 10.0)

    async def _scan(self, timeout_sec: float) -> list[dict[str, Any]]:
        from bleak import BleakScanner

        # return_adv=True is what carries the advertised name and service UUIDs.
        # Plain discover() hands back BLEDevice objects whose .name is often None
        # on Windows, which reads as "nothing is out there" when in fact the
        # scan worked fine -- the identifying data was simply thrown away.
        found = await BleakScanner.discover(timeout=timeout_sec, return_adv=True)
        rows: list[dict[str, Any]] = []
        for device, adv in found.values():
            uuids = [str(u).lower() for u in (adv.service_uuids or [])]
            name = adv.local_name or device.name or ""
            rows.append(
                {
                    "address": device.address,
                    "name": name,
                    "rssi": adv.rssi,
                    "service_uuids": uuids,
                    "manufacturer_ids": sorted(adv.manufacturer_data or {}),
                    # Identify by the service it advertises, not its name: the
                    # name is optional in an advertisement and DJI does not
                    # always send one.
                    "is_osmo": any(u.startswith("0000fff0") or u == "fff0" for u in uuids)
                    or name.lower().startswith(("osmo", "dji")),
                }
            )
        rows.sort(key=lambda row: (not row["is_osmo"], -(row["rssi"] or -999)))
        return rows

    def connect(self) -> dict[str, Any]:
        self.start()
        return self._submit(self._connect(), timeout=self.connect_timeout_sec + 25.0)

    async def _connect(self) -> dict[str, Any]:
        from bleak import BleakClient, BleakScanner

        address = self.address
        if not address:
            device = await BleakScanner.find_device_by_filter(
                lambda _d, adv: bool(adv.local_name and adv.local_name.startswith(self.name_prefix)),
                timeout=self.connect_timeout_sec,
            )
            if device is None:
                raise RuntimeError(f"osmo_not_found:{self.name_prefix}")
            address = device.address

        client = BleakClient(address, timeout=self.connect_timeout_sec)
        await client.connect()
        self._client = client
        self._rx_buffer = b""

        # fff4 carries the replies. Subscribing before the pairing write matters:
        # the approval arrives on this characteristic, and a late subscription
        # misses it with no retry.
        await client.start_notify(CHAR_NOTIFY, self._on_notify)
        await self._send_pairing()
        return {
            "connected": True,
            "address": address,
            "services": [str(service.uuid) for service in client.services],
        }

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            await client.stop_notify(CHAR_NOTIFY)
        except Exception:
            pass
        try:
            await client.disconnect()
        except Exception:
            pass

    @property
    def connected(self) -> bool:
        client = self._client
        return bool(client and client.is_connected)

    # ── framing ──────────────────────────────────────────────────────────────
    def _next_seq(self) -> int:
        with self._lock:
            self._seq = (self._seq + 1) & 0xFFFF
            return self._seq

    def _on_notify(self, _sender: Any, data: bytearray) -> None:
        self._rx_buffer += bytes(data)
        messages, self._rx_buffer = parse_stream(self._rx_buffer)
        for message in messages:
            self._handle(message)

    def _handle(self, message: DumlMessage) -> None:
        if message.cmd_set == CMD_SET_GIMBAL and message.cmd_id == GIMBAL_PARAMS_GET and len(message.payload) >= 6:
            pitch, roll, yaw = struct.unpack_from("<hhh", message.payload, 0)
            self.state.pitch = pitch / 10.0
            self.state.roll = roll / 10.0
            self.state.yaw = yaw / 10.0
            if len(message.payload) >= 7:
                self.state.mode = message.payload[6]
            self.state.updated_at = time.time()
            if self._on_state:
                try:
                    self._on_state(self.state)
                except Exception:
                    pass
            return
        with self._lock:
            self._acks.append(message)
            del self._acks[:-64]

    def recent_messages(self) -> list[DumlMessage]:
        with self._lock:
            return list(self._acks)

    async def _write(self, frame: bytes) -> None:
        client = self._client
        if client is None or not client.is_connected:
            raise RuntimeError("osmo_ble_not_connected")
        # fff5 only; fff4 accepts writes and silently drops DUML, which is the
        # trap the upstream project documents.
        await client.write_gatt_char(CHAR_WRITE, frame, response=False)

    async def _send_pairing(self) -> None:
        pin = build_message(
            TARGET_APP_TO_WIFI,
            FLAG_REQUEST,
            CMD_SET_WIFI,
            WIFI_SET_PAIRING_PIN,
            pack_string(self.identifier) + pack_string(self.pairing_pin),
            msg_id=self._next_seq(),
        )
        await self._write(pin)
        await asyncio.sleep(0.3)
        approved = build_message(
            TARGET_APP_TO_WIFI,
            FLAG_REQUEST,
            CMD_SET_WIFI,
            WIFI_PAIRING_APPROVED,
            pack_string(self.identifier),
            msg_id=self._next_seq(),
        )
        await self._write(approved)
        await asyncio.sleep(0.3)

    # ── public gimbal API (blocking) ─────────────────────────────────────────
    def _send_gimbal(self, encoded: tuple[int, bytes]) -> dict[str, Any]:
        cmd_id, payload = encoded
        frame = build_message(
            TARGET_APP_TO_GIMBAL,
            FLAG_REQUEST,
            CMD_SET_GIMBAL,
            cmd_id,
            payload,
            msg_id=self._next_seq(),
        )
        self._submit(self._write(frame), timeout=10.0)
        return {"sent": True, "cmd_id": cmd_id, "bytes": len(frame), "frame": frame.hex()}

    def move(self, pitch_delta: float, roll_delta: float = 0.0, yaw_delta: float = 0.0) -> dict[str, Any]:
        return self._send_gimbal(OsmoGimbalCommands.move(pitch_delta, roll_delta, yaw_delta))

    def set_angle(self, pitch: float, roll: float = 0.0, yaw: float = 0.0, duration_sec: float = 2.0) -> dict[str, Any]:
        return self._send_gimbal(OsmoGimbalCommands.absolute_angle(pitch, roll, yaw, duration_sec))

    def set_speed(self, pitch_dps: float = 0.0, yaw_dps: float = 0.0, roll_dps: float = 0.0) -> dict[str, Any]:
        return self._send_gimbal(OsmoGimbalCommands.speed(pitch_dps, yaw_dps, roll_dps))

    def set_mode(self, mode: str | int) -> dict[str, Any]:
        return self._send_gimbal(OsmoGimbalCommands.set_mode(mode))

    def recenter(self) -> dict[str, Any]:
        return self.set_angle(0.0, 0.0, 0.0, duration_sec=3.0)

    def stop_motion(self) -> dict[str, Any]:
        return self.set_speed(0.0, 0.0, 0.0)

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "address": self.address,
            "gimbal": self.state.to_dict(),
            "telemetry_seen": bool(self.state.updated_at),
            "last_error": self._last_error,
            **self.dependency_status(),
        }
