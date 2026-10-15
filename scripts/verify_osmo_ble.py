"""Does BLE gimbal control actually work on this Pocket 3?

The protocol layer is proven byte-for-byte against a captured frame in
tests/test_osmo_ble.py, so anything that fails here is the camera's answer, not
a framing bug. The open question is the one the upstream project could not
settle: the Pocket 3 parses gimbal commands over BLE but is reported to ignore
them unless a WiFi streaming session is already running. Telemetry is said to
work regardless.

So this script separates the two, because they fail for different reasons and
need different fixes:

  1. Does the camera answer at all?      -> telemetry arriving means BLE is fine
  2. Does the camera obey?               -> telemetry angle changes after a move

Run it with the camera ON. Run it twice -- once with the tablet's Mimo
livestream stopped, once with it running -- and compare. That comparison is the
whole point: it tells us whether an active stream is the missing precondition.

  python scripts/verify_osmo_ble.py
  python scripts/verify_osmo_ble.py --scan-only
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from alture_jarvis.osmo_ble import OsmoBleLink  # noqa: E402


def _angles(link: OsmoBleLink) -> tuple[float, float, float]:
    return (link.state.pitch, link.state.roll, link.state.yaw)


def _moved(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return max(abs(x - y) for x, y in zip(a, b))


def _hold_and_retry(link: OsmoBleLink, baseline: tuple[float, float, float], args) -> int:
    """Keep the BLE link open and retry every command shape on a cycle.

    Two unknowns get answered at once here, and they need the same long-lived
    connection to answer: whether our BLE link survives the tablet attaching
    over WiFi, and whether an active stream is what makes motor commands land.
    """
    print(f"\n== 4. holding the link for {args.hold:.0f}s ==")
    print("   START THE MIMO LIVESTREAM NOW -- that is the thing being tested.")
    print("   Watch the camera; the log below says what it is being told.\n")

    # Upstream tried 20+ shapes with no ACK. Cycling them costs nothing here and
    # rules out "the one command we picked happens to be the unsupported one".
    variants = [
        ("abs_angle", lambda: link.set_angle(pitch=args.pitch, duration_sec=2.0)),
        ("move", lambda: link.move(pitch_delta=25)),
        ("speed", lambda: link.set_speed(pitch_dps=20)),
    ]

    deadline = time.time() + args.hold
    round_no = 0
    first_success = ""
    ble_dropped = False
    telemetry_went_stale_at = 0.0
    started = time.time()
    while time.time() < deadline:
        round_no += 1
        name, send = variants[(round_no - 1) % len(variants)]
        before = _angles(link)
        connected = link.connected
        try:
            send()
            sent = "sent"
        except Exception as exc:
            sent = f"send failed: {exc}"
        time.sleep(3.0)
        after = _angles(link)
        delta = _moved(before, after)
        fresh = link.state.updated_at and (time.time() - link.state.updated_at) < 5.0
        print(
            f"   [{int(deadline - time.time()):>3}s] {name:<9} ble={'up' if connected else 'DOWN'} "
            f"telemetry={'live' if fresh else 'stale'} "
            f"pitch={after[0]:7.1f} delta={delta:5.1f}  {sent}"
        )
        if not fresh and not telemetry_went_stale_at:
            telemetry_went_stale_at = time.time() - started
        if delta > 2.0 and not first_success:
            first_success = name
            print(f"\n   *** THE GIMBAL MOVED on '{name}'. ***")
            break
        if not connected:
            # Record it here. Checking link.connected after the loop is wrong --
            # we disconnect ourselves on the way out, so that reads as a drop
            # every single time and reported a failure that never happened.
            ble_dropped = True
            print("\n   BLE link dropped -- the tablet attaching almost certainly took it.")
            break

    try:
        link.stop_motion()
        link.recenter()
    except Exception:
        pass
    time.sleep(1.0)
    link.stop()

    print()
    if first_success:
        print(f"PASS: motor control works via '{first_success}'.")
        print("      Compare against the earlier run: if the only thing that changed")
        print("      was the livestream, that is the precondition confirmed.")
        print("      Next: wire the gimbal into tool_gateway at L1 or above.")
        return 0
    if ble_dropped:
        print("BLOCKED: the BLE link did not survive. If it dropped exactly when the")
        print("         tablet connected, then wireless video and PC gimbal control")
        print("         cannot both run -- USB video plus BLE control may be the only")
        print("         combination that gives you both.")
        return 4
    print("PARTIAL: the BLE link stayed up the whole time, so PC-over-Bluetooth and")
    print("         tablet-over-WiFi do coexist. Motor commands were still ignored.")
    print(f"         Baseline: pitch={baseline[0]:.1f} roll={baseline[1]:.1f} yaw={baseline[2]:.1f}")
    if telemetry_went_stale_at:
        print(f"         Telemetry stopped {telemetry_went_stale_at:.0f}s in -- worth knowing")
        print("         whether that lines up with the moment Mimo attached, because a")
        print("         camera that stops talking has likely handed control to the app.")
    print("         For these three command shapes, an active livestream is not the")
    print("         missing precondition.")
    return 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="", help="BLE address; discovered by name when omitted")
    parser.add_argument("--name-prefix", default="Osmo")
    parser.add_argument("--pin", default="love")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument(
        "--watch",
        type=float,
        default=0.0,
        help="Keep rescanning this many seconds until the camera shows up. Use this "
        "while power-cycling it -- a Pocket 3 advertises only in short bursts.",
    )
    parser.add_argument("--settle-sec", type=float, default=6.0, help="How long to listen for telemetry")
    parser.add_argument("--pitch", type=float, default=-20.0, help="Test move, in degrees")
    parser.add_argument(
        "--hold",
        type=float,
        default=0.0,
        help="Stay connected this many seconds, retrying every command variant on a "
        "cycle. Start the Mimo livestream partway through: this is what answers "
        "whether an active stream is the missing precondition, and whether our BLE "
        "link even survives the tablet connecting.",
    )
    args = parser.parse_args()

    status = OsmoBleLink.dependency_status()
    if not status["ok"]:
        print(f"FAIL: {status['error']} -- install with: pip install bleak")
        return 2

    link = OsmoBleLink(address=args.address, name_prefix=args.name_prefix, pairing_pin=args.pin)

    print("== 1. scanning ==")
    deadline = time.time() + args.watch if args.watch else 0.0
    devices: list[dict] = []
    while True:
        try:
            devices = link.scan(timeout_sec=10.0)
        except Exception as exc:
            print(f"FAIL: scan failed: {exc}")
            return 2
        if any(d["is_osmo"] for d in devices) or time.time() >= deadline:
            break
        print(f"   ...nothing yet, {int(deadline - time.time())}s left "
              f"(power-cycle the camera now if you have not)")
    for device in devices:
        marker = "  <-- OSMO" if device["is_osmo"] else ""
        uuids = ",".join(u[:8] for u in device["service_uuids"]) or "-"
        mfr = ",".join(str(m) for m in device["manufacturer_ids"]) or "-"
        print(
            f"   {device['address']}  rssi={device['rssi']:>4}  "
            f"{(device['name'] or '(no name)'):<24} svc=[{uuids}] mfr=[{mfr}]{marker}"
        )
    candidates = [d for d in devices if d["is_osmo"]]
    if not candidates:
        print(f"\nFAIL: nothing advertising the fff0 service or an Osmo/DJI name.")
        print("      USB is irrelevant here -- BLE is a separate radio. Check instead:")
        print("        - the camera is powered on (not just charging with the screen dark)")
        print("        - the tablet is not already holding the BLE link. A Pocket 3 bonded")
        print("          to Mimo stops advertising, so close Mimo or turn the tablet's")
        print("          Bluetooth off, then run this again.")
        print("        - Windows has not bonded to it already: Settings > Bluetooth,")
        print("          remove any OsmoPocket3 entry and retry.")
        print("      A Pocket 3 also advertises in short bursts, so retry while")
        print("      power-cycling it:  --watch 120")
        return 1
    print(f"\nfound: {candidates[0]['address']}  {candidates[0]['name'] or '(no name)'}")
    if not args.address:
        # Connect by address, not by name filter -- the advertisement often has
        # no name at all, which is what made the name-based lookup fail.
        link.address = candidates[0]["address"]
    if args.scan_only:
        link.stop()
        return 0

    print("\n== 2. connecting and pairing ==")
    try:
        info = link.connect()
    except Exception as exc:
        print(f"FAIL: connect failed: {exc}")
        link.stop()
        return 1
    print(f"   connected to {info['address']}")
    print(f"   services: {', '.join(info['services']) or '(none reported)'}")

    print(f"\n== 3. listening {args.settle_sec:.0f}s for telemetry ==")
    deadline = time.time() + args.settle_sec
    while time.time() < deadline and not link.state.updated_at:
        time.sleep(0.2)
    if not link.state.updated_at:
        print("   no telemetry. The link is up but the camera is not pushing gimbal state.")
        print("   -> BLE reached the device but it is not talking. Check pairing/PIN.")
        link.stop()
        return 1
    before = (link.state.pitch, link.state.roll, link.state.yaw)
    print(f"   telemetry OK: pitch={before[0]:.1f} roll={before[1]:.1f} yaw={before[2]:.1f}")

    if args.hold:
        return _hold_and_retry(link, before, args)

    print(f"\n== 4. commanding a {args.pitch:+.0f} degree pitch move ==")
    print("   watch the camera -- does it physically move?")
    link.set_mode("follow")
    time.sleep(0.4)
    link.set_angle(pitch=args.pitch, duration_sec=2.0)

    moved = False
    deadline = time.time() + 5.0
    while time.time() < deadline:
        time.sleep(0.25)
        now = (link.state.pitch, link.state.roll, link.state.yaw)
        if max(abs(a - b) for a, b in zip(now, before)) > 2.0:
            moved = True
            break

    after = (link.state.pitch, link.state.roll, link.state.yaw)
    print(f"   after: pitch={after[0]:.1f} roll={after[1]:.1f} yaw={after[2]:.1f}")

    link.recenter()
    time.sleep(1.5)
    link.stop()

    print()
    if moved:
        print("PASS: the gimbal obeyed. BLE control works on this setup --")
        print("      wire it into the runtime.")
        return 0
    print("PARTIAL: telemetry works, motor commands were ignored.")
    print("         This is the documented Pocket 3 behaviour. If the Mimo")
    print("         livestream was NOT running, start it and run this again --")
    print("         that comparison is what decides whether control is possible.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
