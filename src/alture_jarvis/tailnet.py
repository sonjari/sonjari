"""밖에서도 쓰기 — 테일스케일을 몰라도 되는 맥 ↔ 집 PC 연결 (설계_밖에서도쓰기_테일스케일_2026-11-04 §2-2 · §3 · §8).

테일스케일 CLI 를 부르는 곳은 **여기 한 군데**다(두 벌로 갈라지면 한쪽만 고쳐진다 — 사고 Q).
손자리는 가입 · 로그인을 대신하지 않는다. 설치 여부 · 로그인 여부 · 같은 계정인지 알아내기, 바른 페이지 주소 주기,
집 PC 짝짓기 문(8092)을 테일넷 안에만 내놓기(`tailscale serve --tcp`, Funnel 아님)만 한다.

실측(11-04 · 이 PC 1.104.2 · 맥 1.104.4):
- `status --json` 칸: BackendState · AuthURL · CurrentTailnet.{StableID,Name,MagicDNSSuffix} · Self.{DNSName,Online,OS,KeyExpiry} ·
  Peer[].{HostName,DNSName,Online,OS,TailscaleIPs}. 맥 앱스토어판 CLI 도 앱 밖(SSH)에서 된다.
- `serve --bg --tcp 8092 tcp://127.0.0.1:8092` 는 관리자 아닌 권한으로 되고, 문이 0.0.0.0:8092 에 묶여 있어도 부딪히지 않는다
  (맥에서 테일넷 이름:8092 · 와이파이:8092 둘 다 200). `serve status --json` → {"TCP": {"8092": {"TCPForward": "127.0.0.1:8092"}}}.
- 확인 전: NeedsLogin 일 때 AuthURL 이 바로 채워지는지(로그아웃이 필요해 못 잼) — 그래서 login() 은 status 와 CLI 출력 둘 다 본다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .pairing import PAIR_PORT

Runner = Callable[[list[str], float], tuple[int, str]]

INSTALL_PAGES = {"win32": "https://tailscale.com/download/windows", "darwin": "https://tailscale.com/download/mac"}
_URL = re.compile(r"https://login\.tailscale\.com/\S+")


def cli_path() -> str:
    """테일스케일 CLI 자리 — 없으면 ""."""
    candidates: list[str] = []
    if sys.platform == "win32":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            if root:
                candidates.append(str(Path(root) / "Tailscale" / "tailscale.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    found = shutil.which("tailscale")
    if found:
        candidates.append(found)
    return next((path for path in candidates if path and Path(path).is_file()), "")


def _run(args: list[str], timeout: float) -> tuple[int, str]:
    exe = cli_path()
    if not exe:
        return 127, ""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 124, type(exc).__name__
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _name(dns: Any) -> str:
    return str(dns or "").rstrip(".")


def parse_status(raw: dict[str, Any]) -> dict[str, Any]:
    """`status --json` → 손자리가 판정에 쓰는 칸만. 주소 · 열쇠 같은 값은 화면에 안 보낸다."""
    me = raw.get("Self") or {}
    tailnet = raw.get("CurrentTailnet") or {}
    peers = []
    for peer in (raw.get("Peer") or {}).values():
        if isinstance(peer, dict):
            peers.append({"name": str(peer.get("HostName") or ""), "dns_name": _name(peer.get("DNSName")),
                          "online": bool(peer.get("Online")), "os": str(peer.get("OS") or "")})
    return {
        "installed": True,
        "state": str(raw.get("BackendState") or "NoState"),
        "auth_url": str(raw.get("AuthURL") or ""),
        "tailnet_id": str(tailnet.get("StableID") or ""),
        "tailnet_name": str(tailnet.get("Name") or ""),
        "dns_name": _name(me.get("DNSName")),
        "key_expiry": str(me.get("KeyExpiry") or ""),
        "peers": peers,
    }


def status(run: Runner | None = None) -> dict[str, Any]:
    """지금 이 기기의 테일스케일. 설치 안 됨 · 데몬 꺼짐도 사람 말로 가를 수 있게 칸으로 돌려준다."""
    if run is None and not cli_path():
        return {"installed": False, "state": "NotInstalled", "peers": []}
    code, out = (run or _run)(["status", "--json"], 6.0)
    if code == 127:
        return {"installed": False, "state": "NotInstalled", "peers": []}
    # 꺼져 있으면(Stopped) 종료 코드가 0 이 아니어도 JSON 은 나온다 — 출력으로 판정한다.
    start = out.find("{")
    try:
        raw = json.loads(out[start:]) if start >= 0 else {}
    except ValueError:
        raw = {}
    if not isinstance(raw, dict) or not raw:
        return {"installed": True, "state": "NoState", "peers": [], "error": out.strip()[:200]}
    return parse_status(raw)


def install_page() -> str:
    return INSTALL_PAGES.get(sys.platform, "https://tailscale.com/download")


_login_lock = threading.Lock()


def login(run: Runner | None = None, *, wait: float = 12.0, sleep: Callable[[float], None] = time.sleep,
          popen: Callable[..., Any] | None = None, force: bool = False) -> dict[str, Any]:
    """로그인 페이지 주소를 얻는다(여는 것은 화면이 한다). 이미 로그인돼 있으면 주소 없이 ok.

    force=True: 로그인돼 있어도 새 로그인을 연다 — 두 기기가 다른 계정일 때 「이 기기를 집 PC 계정으로 다시 로그인」.
    """
    now = status(run)
    if not now.get("installed"):
        return {"ok": False, "error": "not_installed"}
    if now["state"] == "Running" and not force:
        return {"ok": True, "url": ""}
    if now.get("auth_url"):
        return {"ok": True, "url": now["auth_url"]}
    exe = cli_path() if popen is None else "tailscale"
    if not exe:
        return {"ok": False, "error": "not_installed"}
    with _login_lock:
        # `tailscale login` 은 사람이 브라우저에서 끝낼 때까지 기다리는 명령이다 — 따로 띄우고, 주소가 나올 때까지만 본다.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = (popen or subprocess.Popen)([exe, "login", "--timeout=10m"], stdout=subprocess.PIPE,
                                               stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                               creationflags=flags)
        except OSError as exc:
            return {"ok": False, "error": f"login_failed: {type(exc).__name__}"}
        seen: list[str] = []

        def read() -> None:
            for line in iter(proc.stdout.readline, ""):
                seen.append(line)

        threading.Thread(target=read, name="tailscale-login-out", daemon=True).start()
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            found = _URL.search("".join(seen))
            if found:
                return {"ok": True, "url": found.group(0)}
            again = status(run)
            if again.get("auth_url"):
                return {"ok": True, "url": again["auth_url"]}
            if again.get("state") == "Running" and not force:
                return {"ok": True, "url": ""}
            sleep(0.5)
    return {"ok": False, "error": "no_login_page"}


def turn_on(run: Runner | None = None) -> dict[str, Any]:
    """로그인은 돼 있는데 꺼진(Stopped) 테일스케일을 켠다."""
    code, out = (run or _run)(["up", "--timeout=20s"], 30.0)
    after = status(run)
    if after.get("state") == "Running":
        return {"ok": True}
    return {"ok": False, "error": "turn_on_failed", "detail": out.strip()[:200], "code": code}


def door_served(run: Runner | None = None, port: int = PAIR_PORT) -> bool:
    code, out = (run or _run)(["serve", "status", "--json"], 6.0)
    if code != 0:
        return False
    try:
        data = json.loads(out[out.find("{"):]) if "{" in out else {}
    except ValueError:
        return False
    row = ((data or {}).get("TCP") or {}).get(str(port)) or {}
    return str(row.get("TCPForward") or "").endswith(f":{port}")


def serve_door(run: Runner | None = None, port: int = PAIR_PORT) -> dict[str, Any]:
    """집 PC 짝짓기 문을 테일넷 안에만 내놓는다(Funnel 아님 · 본 8091 은 안 건드린다)."""
    if door_served(run, port):
        return {"ok": True, "already": True}
    code, out = (run or _run)(["serve", "--bg", "--tcp", str(port), f"tcp://127.0.0.1:{port}"], 20.0)
    if code == 0 and door_served(run, port):
        return {"ok": True}
    return {"ok": False, "error": "serve_failed", "detail": out.strip()[:200]}


# ── 단계 판정 (§2-2 ①~⑤ · 디스코드 연결 화면처럼 백엔드가 stage 를 정한다) ─────────────────────────────────
STEPS = ("install", "login", "same_account", "door", "reach")


def _side(me: dict[str, Any] | None) -> dict[str, Any]:
    me = me or {}
    installed = bool(me.get("installed"))
    state = str(me.get("state") or "")
    return {"installed": installed, "signed_in": state == "Running", "state": state,
            "tailnet_id": str(me.get("tailnet_id") or ""), "dns_name": str(me.get("dns_name") or "")}


def plan(mac: dict[str, Any] | None, pc: dict[str, Any] | None, *, door_open: bool, reached: bool) -> dict[str, Any]:
    """두 기기 상태 → 지금 단계와 막힌 까닭. 화면은 이 stage 만 그린다(누른다고 앞서 가지 않는다).

    reason 은 §4 까닭 코드: not_installed_mac · not_installed_pc · sign_in_mac · sign_in_pc · turn_on_mac · turn_on_pc ·
    different_account · pc_unknown · serve_failed · pc_offline.
    """
    a, b = _side(mac), _side(pc)
    if pc is None:
        return {"stage": "install", "reason": "pc_unknown", "mac": a, "pc": b}
    for step, key in (("install", "installed"), ("login", "signed_in")):
        for who, side in (("mac", a), ("pc", b)):
            if not side[key]:
                if step == "install":
                    reason = f"not_installed_{who}"
                elif side["state"] == "Stopped":
                    reason = f"turn_on_{who}"
                else:
                    reason = f"sign_in_{who}"
                return {"stage": step, "reason": reason, "mac": a, "pc": b}
    if not a["tailnet_id"] or a["tailnet_id"] != b["tailnet_id"]:
        return {"stage": "same_account", "reason": "different_account", "mac": a, "pc": b}
    if not door_open:
        return {"stage": "door", "reason": "serve_failed" if pc.get("serve_error") else "", "mac": a, "pc": b}
    if not reached:
        return {"stage": "reach", "reason": "", "mac": a, "pc": b}
    return {"stage": "done", "reason": "", "mac": a, "pc": b}


def why_not_found(me: dict[str, Any], pc_dns_name: str) -> str:
    """밖에서 「PC not found」 일 때 까닭 하나(§2-3 표). 테일넷 길이 없으면 ""."""
    if not pc_dns_name:
        return ""
    if not me.get("installed"):
        return ""
    state = str(me.get("state") or "")
    if state == "Stopped":
        return "tailscale_off"
    if state == "NeedsLogin":
        return "sign_in_again"
    if state != "Running":
        return "tailscale_off"
    host = pc_dns_name.split(":")[0]
    for peer in me.get("peers") or []:
        if peer.get("dns_name") == host:
            return "pc_not_answering" if peer.get("online") else "pc_asleep"
    return "pc_asleep"
