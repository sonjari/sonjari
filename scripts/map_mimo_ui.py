"""Map the DJI Mimo UI on the tablet so the controller can target it by id.

Nothing about Mimo's layout can be guessed. This connects to the tablet, brings
Mimo to the front, and prints every control it exposes -- resource-id,
content-desc, text, position -- plus a screenshot and the raw dump.

The output is what the selector map in mimo_control.py is built from. Writing
that map from hardcoded pixel coordinates instead would appear to work and then
break the first time the tablet rotates or Mimo updates, with every tap still
reporting success while hitting empty screen.

  python scripts/map_mimo_ui.py --host 192.168.0.x
  python scripts/map_mimo_ui.py --host 192.168.0.x --watch 60   # re-dump as you navigate
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from alture_jarvis.android_bridge import AdbError, AndroidBridge  # noqa: E402

# "mimo.sz" is what the real install reports -- confirmed on the Lenovo tab, and
# not a name any of the obvious guesses would have found.
MIMO_PACKAGES = ("mimo.sz", "dji.mimo", "com.dji.mimo", "dji.go.v5", "com.dji.industry.mimo")


def dump_once(bridge: AndroidBridge, out_dir: Path, tag: str) -> int:
    try:
        nodes = bridge.ui_dump()
    except AdbError as exc:
        print(f"   ui dump failed: {exc}")
        return 0

    clickable = [n for n in nodes if n.clickable and n.area > 0]
    print(f"\n--- {tag}: {len(nodes)} nodes, {len(clickable)} clickable ---")
    for node in sorted(clickable, key=lambda n: (n.bounds[1], n.bounds[0])):
        parts = []
        if node.resource_id:
            parts.append(f"id={node.resource_id}")
        if node.content_desc:
            parts.append(f"desc={node.content_desc!r}")
        if node.text:
            parts.append(f"text={node.text!r}")
        if not node.enabled:
            parts.append("DISABLED")
        print(f"   {str(node.center):>14}  {' '.join(parts) or node.klass}")

    payload = [
        {
            "resource_id": n.resource_id,
            "content_desc": n.content_desc,
            "text": n.text,
            "class": n.klass,
            "clickable": n.clickable,
            "enabled": n.enabled,
            "bounds": list(n.bounds),
        }
        for n in nodes
    ]
    (out_dir / f"mimo-ui-{tag}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        bridge.screenshot(out_dir / f"mimo-ui-{tag}.png")
    except Exception as exc:
        print(f"   (screenshot failed: {exc})")
    return len(clickable)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="", help="Tablet IP for wireless ADB")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--serial", default="", help="Use an already-listed device instead")
    parser.add_argument("--package", default="", help="Force the Mimo package name")
    parser.add_argument("--watch", type=float, default=0.0, help="Re-dump every 8s for N seconds")
    parser.add_argument("--out", default="outputs/mimo-ui")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    bridge = AndroidBridge(serial=args.serial, host=args.host, port=args.port)
    info = bridge.available()
    if not info["ok"]:
        print("FAIL: adb not found. Install Google platform-tools and put adb on PATH,")
        print("      or pass its full path via AndroidBridge(adb_path=...).")
        return 2

    print("== connecting ==")
    try:
        print(f"   {bridge.connect()}")
    except AdbError as exc:
        print(f"FAIL: {exc}")
        print("      On the tablet: Settings > Developer options > Wireless debugging ON.")
        print("      First time also needs `adb pair <ip>:<pairPort>` with the 6-digit code.")
        return 1

    online = [d for d in bridge.devices() if d["state"] == "device"]
    if not online:
        print("FAIL: adb sees no authorised device.")
        print("      Check the tablet for the 'Allow USB debugging?' prompt and accept it.")
        return 1
    print(f"   device: {online[0]['serial']}")

    print("\n== waking the screen ==")
    bridge.wake()
    time.sleep(1.0)
    print(f"   awake={bridge.screen_on()}  size={bridge.screen_size()}")

    package = args.package
    if not package:
        for candidate in MIMO_PACKAGES:
            if bridge.is_installed(candidate):
                package = candidate
                break
    if not package:
        print(f"\nFAIL: none of {MIMO_PACKAGES} is installed.")
        print("      Find the real name with: adb shell pm list packages | findstr -i dji")
        return 1
    print(f"\n== launching {package} ==")
    bridge.launch(package)
    time.sleep(4.0)
    print(f"   foreground app: {bridge.current_app()}")

    dump_once(bridge, out_dir, "main")

    if args.watch:
        deadline = time.time() + args.watch
        index = 0
        print(f"\n== watching {args.watch:.0f}s -- navigate Mimo now, each screen gets dumped ==")
        while time.time() < deadline:
            time.sleep(8.0)
            index += 1
            dump_once(bridge, out_dir, f"watch{index:02d}")

    print(f"\nSaved dumps and screenshots to {out_dir.resolve()}")
    print("Next: turn the ids above into the selector map in mimo_control.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
