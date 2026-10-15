"""Read-only multi-site soak for the live JARVIS browser worker.

The script owns one temporary Chrome tab, cycles three public sites, and records
tool latency plus the listening JARVIS process' resource usage. It never calls a
write tool and closes only the CDP target it created.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


SITES = (
    ("w3c-aria", "https://www.w3.org/WAI/ARIA/apg/patterns/switch/examples/switch-button/"),
    ("wikipedia", "https://en.wikipedia.org/wiki/Web_accessibility"),
    ("react-spa", "https://react.dev/learn"),
)


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str = "",
    timeout: float = 90,
) -> Any:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["X-Jarvis-Token"] = token
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def _token(env_path: Path) -> str:
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("JARVIS_CONTROL_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"JARVIS_CONTROL_TOKEN missing: {env_path}")


def _tool(base_url: str, token: str, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], float]:
    started = time.monotonic()
    result = _json_request(
        f"{base_url}/v1/tools/execute",
        method="POST",
        payload={"name": name, "arguments": arguments},
        token=token,
    )
    return dict(result or {}), time.monotonic() - started


def _listener_process(port: int) -> psutil.Process:
    for connection in psutil.net_connections(kind="tcp"):
        if (
            connection.status == psutil.CONN_LISTEN
            and connection.laddr
            and int(connection.laddr.port) == port
            and connection.pid
        ):
            return psutil.Process(connection.pid)
    raise RuntimeError(f"no listening process on port {port}")


def _resource_sample(process: psutil.Process) -> dict[str, Any]:
    children = process.children(recursive=True)
    child_rss = 0
    living_children = 0
    for child in children:
        try:
            child_rss += int(child.memory_info().rss)
            living_children += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    sample = {
        "at": time.time(),
        "pid": process.pid,
        "rss_bytes": int(process.memory_info().rss),
        "threads": int(process.num_threads()),
        "children": living_children,
        "child_rss_bytes": child_rss,
    }
    try:
        sample["handles"] = int(process.num_handles())
    except (AttributeError, psutil.AccessDenied, psutil.NoSuchProcess):
        sample["handles"] = None
    return sample


def _linear_slope(samples: list[dict[str, Any]], key: str) -> float:
    points = [
        (float(item["at"]), float(item[key]))
        for item in samples
        if item.get(key) is not None
    ]
    if len(points) < 2:
        return 0.0
    origin = points[0][0]
    xs = [(at - origin) / 60.0 for at, _ in points]
    ys = [value for _, value in points]
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(ys)
    denominator = sum((value - x_mean) ** 2 for value in xs)
    if denominator == 0:
        return 0.0
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator


def _summary(resources: list[dict[str, Any]], calls: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(item["seconds"]) for item in calls]
    failed = [item for item in calls if item.get("ok") is not True]
    first = resources[0] if resources else {}
    last = resources[-1] if resources else {}
    return {
        "calls": len(calls),
        "failed_calls": len(failed),
        "latency_seconds": {
            "mean": statistics.fmean(latencies) if latencies else 0.0,
            "max": max(latencies, default=0.0),
        },
        "resources": {
            "samples": len(resources),
            "rss_start": first.get("rss_bytes"),
            "rss_end": last.get("rss_bytes"),
            "rss_delta": (
                int(last["rss_bytes"]) - int(first["rss_bytes"])
                if first.get("rss_bytes") is not None and last.get("rss_bytes") is not None
                else None
            ),
            "rss_slope_bytes_per_minute": _linear_slope(resources, "rss_bytes"),
            "threads_start": first.get("threads"),
            "threads_end": last.get("threads"),
            "handles_start": first.get("handles"),
            "handles_end": last.get("handles"),
            "children_start": first.get("children"),
            "children_end": last.get("children"),
        },
    }


def run(args: argparse.Namespace) -> int:
    token = _token(Path(args.env))
    process = _listener_process(urllib.parse.urlparse(args.base_url).port or 8091)
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "duration_minutes_requested": args.duration_minutes,
        "cycle_seconds": args.cycle_seconds,
        "sites": [{"name": name, "url": url} for name, url in SITES],
        "pid": process.pid,
        "calls": [],
        "resources": [],
        "health": [],
    }
    calls: list[dict[str, Any]] = report["calls"]
    resources: list[dict[str, Any]] = report["resources"]
    target_id = ""
    started = time.monotonic()
    deadline = started + args.duration_minutes * 60.0
    cycle = 0
    marker = f"jarvis-soak-{int(time.time())}"
    first_url = f"{SITES[0][1]}#{marker}"

    try:
        target = _json_request(
            f"{args.cdp_url}/json/new?{urllib.parse.quote(first_url, safe='')}",
            method="PUT",
            timeout=15,
        )
        target_id = str((target or {}).get("id") or "")
        if not target_id:
            raise RuntimeError("CDP did not return a temporary target id")
        candidates: list[dict[str, Any]] = []
        for _ in range(20):
            time.sleep(0.5)
            tabs, _ = _tool(args.base_url, token, "browser_tabs", {})
            visible_tabs = list((tabs.get("result") or {}).get("tabs") or [])
            candidates = [
                item
                for item in visible_tabs
                if marker in str(item.get("url") or "")
                or str(item.get("url") or "").startswith(SITES[0][1])
            ]
            if candidates:
                break
        if not candidates:
            raise RuntimeError("temporary soak tab is not visible to JARVIS")
        _tool(
            args.base_url,
            token,
            "browser_switch_tab",
            {"index": int(candidates[-1]["index"])},
        )

        while time.monotonic() < deadline:
            cycle += 1
            cycle_started = time.monotonic()
            for site_name, url in SITES:
                for tool_name, arguments in (
                    ("browser_open", {"url": url}),
                    ("browser_read", {"max_chars": args.max_chars}),
                    ("browser_snapshot", {"limit": args.snapshot_limit, "include_box": False}),
                ):
                    try:
                        result, elapsed = _tool(args.base_url, token, tool_name, arguments)
                        payload = result.get("result") or {}
                        calls.append(
                            {
                                "at": time.time(),
                                "cycle": cycle,
                                "site": site_name,
                                "tool": tool_name,
                                "ok": result.get("ok") is True,
                                "status": str(result.get("status") or ""),
                                "error": str(result.get("error") or "")[:500],
                                "seconds": elapsed,
                                "char_count": payload.get("char_count"),
                                "element_count": len(payload.get("elements") or []),
                            }
                        )
                    except Exception as exc:
                        calls.append(
                            {
                                "at": time.time(),
                                "cycle": cycle,
                                "site": site_name,
                                "tool": tool_name,
                                "ok": False,
                                "status": "request_failed",
                                "error": str(exc)[:500],
                                "seconds": time.monotonic() - cycle_started,
                            }
                        )
            resources.append(_resource_sample(process))
            health = _json_request(f"{args.base_url}/health", timeout=20) or {}
            browser = dict(health.get("browser") or {})
            report["health"].append(
                {
                    "at": time.time(),
                    "ok": health.get("ok") is True,
                    "state": health.get("state"),
                    "connect_mode": browser.get("connect_mode"),
                    "stuck": browser.get("stuck"),
                    "recoveries": browser.get("recoveries"),
                    "circuit_open": browser.get("circuit_open"),
                    "last_timeout": browser.get("last_timeout"),
                }
            )
            recent = calls[-9:]
            failures = sum(item.get("ok") is not True for item in recent)
            rss_mb = resources[-1]["rss_bytes"] / (1024 * 1024)
            print(
                f"cycle={cycle:03d} elapsed_min={(time.monotonic() - started) / 60:.1f} "
                f"failures={failures} rss_mb={rss_mb:.1f} threads={resources[-1]['threads']} "
                f"handles={resources[-1]['handles']} stuck={browser.get('stuck')} "
                f"recoveries={browser.get('recoveries')}",
                flush=True,
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sleep_for = min(
                remaining,
                max(0.0, args.cycle_seconds - (time.monotonic() - cycle_started)),
            )
            if sleep_for:
                time.sleep(sleep_for)
    finally:
        if target_id:
            try:
                _json_request(f"{args.cdp_url}/json/close/{target_id}", timeout=15)
            except Exception:
                pass

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["elapsed_seconds"] = time.monotonic() - started
    report["summary"] = _summary(resources, calls)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2), flush=True)
    print(f"report={output.resolve()}", flush=True)
    return 0 if report["summary"]["failed_calls"] == 0 else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-minutes", type=float, default=45.0)
    parser.add_argument("--cycle-seconds", type=float, default=60.0)
    parser.add_argument("--max-chars", type=int, default=6000)
    parser.add_argument("--snapshot-limit", type=int, default=80)
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    parser.add_argument(
        "--env", default=r"C:\RoboMetaFit\tools\alture-jarvis\.env"
    )
    parser.add_argument(
        "--output",
        default=str(
            Path(__file__).resolve().parents[1]
            / "outputs"
            / "soak"
            / f"operational_agent_{time.strftime('%Y%m%d_%H%M%S')}.json"
        ),
    )
    return parser


if __name__ == "__main__":
    sys.exit(run(_parser().parse_args()))
