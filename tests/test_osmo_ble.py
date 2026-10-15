from __future__ import annotations

import struct

import pytest

from alture_jarvis.osmo_ble import (
    CMD_SET_GIMBAL,
    CMD_SET_WIFI,
    FLAG_REQUEST,
    GIMBAL_ABS_ANGLE,
    GIMBAL_MOVEMENT,
    GIMBAL_PARAMS_GET,
    GIMBAL_SET_MODE,
    TARGET_APP_TO_GIMBAL,
    TARGET_APP_TO_WIFI,
    WIFI_SET_PAIRING_PIN,
    OsmoBleLink,
    OsmoGimbalCommands,
    build_message,
    crc8,
    crc16,
    pack_string,
    parse_message,
    parse_stream,
)

# A real pairing frame captured from the DJI Mimo app talking to a Pocket 3
# (published with the reverse-engineered protocol). Every byte of it is the
# reference: the camera drops a frame with a bad CRC without saying anything,
# so "it runs" proves nothing and only this comparison does.
CAPTURED_PAIRING_FRAME = bytes.fromhex(
    "552204ea020780924007450f3030313734393331393238363130320435313630"
    "2e42"
)


def test_crc8_matches_the_captured_frame() -> None:
    header = CAPTURED_PAIRING_FRAME[:3]
    assert header == bytes([0x55, 0x22, 0x04])
    assert crc8(header) == CAPTURED_PAIRING_FRAME[3] == 0xEA


def test_crc16_matches_the_captured_frame() -> None:
    body = CAPTURED_PAIRING_FRAME[:-2]
    expected = struct.unpack("<H", CAPTURED_PAIRING_FRAME[-2:])[0]
    assert crc16(body) == expected == 0x422E


def test_captured_frame_rebuilds_byte_for_byte() -> None:
    # Same inputs the app used -> the identical frame, which is the only real
    # proof that the header layout, the LE target, the BE message id and both
    # CRCs are all right at once.
    rebuilt = build_message(
        TARGET_APP_TO_WIFI,
        FLAG_REQUEST,
        CMD_SET_WIFI,
        WIFI_SET_PAIRING_PIN,
        pack_string("001749319286102") + pack_string("5160"),
        msg_id=0x8092,
    )
    assert rebuilt == CAPTURED_PAIRING_FRAME


def test_message_id_is_the_only_big_endian_field() -> None:
    # A byte-swapped message id still passes both CRCs and is still ignored, so
    # nothing else catches this.
    frame = build_message(TARGET_APP_TO_GIMBAL, FLAG_REQUEST, CMD_SET_GIMBAL, GIMBAL_SET_MODE, b"\x01\x00", msg_id=0x1234)
    assert frame[4:6] == bytes([0x02, 0x04])  # target, little-endian
    assert frame[6:8] == bytes([0x12, 0x34])  # message id, big-endian


def test_parse_round_trips_a_built_frame() -> None:
    frame = build_message(TARGET_APP_TO_GIMBAL, FLAG_REQUEST, CMD_SET_GIMBAL, GIMBAL_MOVEMENT, b"\x05\x00\x00", msg_id=7)
    message = parse_message(frame)
    assert message is not None
    assert (message.sender, message.receiver) == (0x02, 0x04)
    assert (message.cmd_set, message.cmd_id) == (CMD_SET_GIMBAL, GIMBAL_MOVEMENT)
    assert message.msg_id == 7
    assert message.payload == b"\x05\x00\x00"


def test_stream_splits_concatenated_frames_and_keeps_the_partial_tail() -> None:
    # BLE notifications are not frame-aligned: one packet can hold several
    # frames or half of one, and a dropped tail loses the next frame too.
    first = build_message(TARGET_APP_TO_GIMBAL, FLAG_REQUEST, CMD_SET_GIMBAL, GIMBAL_SET_MODE, b"\x00\x00", msg_id=1)
    second = build_message(TARGET_APP_TO_GIMBAL, FLAG_REQUEST, CMD_SET_GIMBAL, GIMBAL_SET_MODE, b"\x01\x00", msg_id=2)

    messages, remaining = parse_stream(first + second[:6])
    assert [m.msg_id for m in messages] == [1]
    assert remaining == second[:6]

    messages, remaining = parse_stream(remaining + second[6:])
    assert [m.msg_id for m in messages] == [2]
    assert remaining == b""


def test_absolute_angle_payload_layout() -> None:
    cmd_id, payload = OsmoGimbalCommands.absolute_angle(pitch=-15.0, roll=0.0, yaw=30.0, duration_sec=2.0)
    assert cmd_id == GIMBAL_ABS_ANGLE
    pitch, roll, yaw, axes, duration = struct.unpack("<hhhBB", payload)
    # Angles ride as tenths of a degree; sending whole degrees would move the
    # gimbal a tenth as far and look like a mysteriously weak motor.
    assert (pitch, roll, yaw) == (-150, 0, 300)
    assert axes == 0x07
    assert duration == 20


def test_move_clamps_to_the_signed_byte_range() -> None:
    _, payload = OsmoGimbalCommands.move(pitch_delta=500, roll_delta=-500)
    pitch, roll, yaw = struct.unpack_from("<bbb", payload, 0)
    assert (pitch, roll, yaw) == (127, -127, 0)
    assert len(payload) == 20


def test_unknown_gimbal_mode_is_rejected() -> None:
    with pytest.raises((ValueError, KeyError)):
        OsmoGimbalCommands.set_mode("sideways")


def test_telemetry_notification_updates_state() -> None:
    link = OsmoBleLink()
    telemetry = build_message(
        TARGET_APP_TO_GIMBAL,
        0x00,
        CMD_SET_GIMBAL,
        GIMBAL_PARAMS_GET,
        struct.pack("<hhhB", -123, 45, 678, 1),
        msg_id=9,
    )
    link._on_notify(None, bytearray(telemetry))

    assert link.state.pitch == pytest.approx(-12.3)
    assert link.state.roll == pytest.approx(4.5)
    assert link.state.yaw == pytest.approx(67.8)
    assert link.state.mode == 1
    assert link.state.updated_at > 0


def test_status_reports_the_missing_dependency_rather_than_raising() -> None:
    # bleak is an optional hardware extra; JARVIS has to stay up without it.
    status = OsmoBleLink().status()
    assert "ok" in status
    assert status["connected"] is False
