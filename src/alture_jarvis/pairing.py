"""짝짓기 — 이 맥(자식)이 집 PC(부모) 손자리의 그래픽카드를 빌린다 (설계_짝짓기_모델자리_2026-11-03 §2-1 · §4-1 · §4-2 · 순서 2 · 3).

사람이 하는 일은 둘뿐이다: 「집 PC 빌려 쓰기」 누르기, 집 PC 화면에 뜬 숫자 6개를 맥에 치기. 주소 · 토큰 · `.env` 는 사람이 안 본다.

## 집 PC 쪽(`PairingHost`)
- `hello` — 찾기용. 이름 · 판 · 그래픽카드만. 모델 · 파일 내용은 없다.
- `request` — 맥이 짝을 청한다. 6자리 코드를 만들어 **집 PC 화면에만** 띄운다(돌려주지 않는다). 5분 · 한 번 · 세 번 틀리면 닫힌다.
- `confirm` — 코드가 맞으면 **이 기기 전용 토큰**을 준다. 집 PC 의 제어 토큰과 다른 값이고, 파일에는 해시만 둔다(끊기 = 그 줄 지우기).
- `verify` — 모델 빌리기(`/v1/llm/…`)가 기기 토큰을 확인한다.
- 같은 네트워크(사설 주소)에서도 이 길들만 열린다(`peer_guard.PAIRING_PATHS`). 나머지 제어 API 는 그대로 루프백 · 테일넷만.

## 이 맥 쪽(`PairingClient`)
- 찾기: 기억한 주소 → 같은 네트워크 /24 를 짧게 훑기(0.3초 · 동시에).
- 짝을 지으면 토큰은 운영체제 열쇠 보관함(맥 키체인 · 윈도우 자격 증명 관리자)에, 주소 · 이름은 `data/paired_home.json` 에.
- 모델 호출은 이 맥 손자리의 `/v1/home-llm/…` 로 보내고, 거기서 토큰을 붙여 집 PC `/v1/llm/…` 로 넘긴다 — 토큰이 모델 주소 ·
  기록 · 문제 보내기에 실리지 않게.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

# 집 PC 의 짝짓기 전용 문(2026-11-04 · pair_door.py). 예전엔 본 백엔드 8091 로 찾았다 — 손님 PC 는 그 문이 127.0.0.1 이라 안 보였다.
PAIR_PORT = 8092
OLD_PAIR_PORT = 8091
CODE_TTL_SEC = 300
MAX_TRIES = 3
MAX_OPEN_REQUESTS = 5
REQUEST_GAP_SEC = 2.0
# ★ 11-04 보안 점검: 틀린 숫자를 요청마다만 세면(요청당 3번) 같은 와이파이의 누군가가 2초마다 새 요청을 만들어
#   한 시간에 ~5,400번 맞혀 볼 수 있었다 — 6자리(100만)에 하루 ~12%. **이 PC 전체로** 센다:
#   24시간에 틀린 숫자 10번이면 짝짓기를 잠그고(열린 요청도 닫음), 새 요청은 한 시간에 20개까지.
#   그러면 맞힐 확률은 하루 0.001%(10/1,000,000) 아래다. 사람이 하루 10번 틀릴 일은 드물다.
MAX_WRONG_PER_DAY = 10
MAX_REQUESTS_PER_HOUR = 20
DEVICES_FILE = "paired_devices.json"
HOME_FILE = "paired_home.json"
SECRET_TARGET = "Sonjari/home-pc-token"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def this_name() -> str:
    return (socket.gethostname() or "Sonjari").split(".")[0][:60]


# ── 집 PC 쪽 ────────────────────────────────────────────────────────────────────────────────────

class PairingHost:
    def __init__(self, data_dir: Path | str, *, publish: Callable[[str, dict[str, Any]], Any] | None = None,
                 info: Callable[[], dict[str, Any]] | None = None, clock: Callable[[], float] = time.time) -> None:
        self.data_dir = Path(data_dir)
        self._publish = publish or (lambda _e, _p: None)
        self._info = info or (lambda: {})
        self._clock = clock
        self._lock = threading.Lock()
        self._requests: dict[str, dict[str, Any]] = {}
        self._last_request_at = 0.0
        self._wrong_at: list[float] = []      # 틀린 숫자 시각(이 PC 전체 · 24시간)
        self._requested_at: list[float] = []  # 새 요청 시각(한 시간)

    def locked(self) -> bool:
        """짝짓기가 잠겼나 — 24시간 안에 틀린 숫자가 MAX_WRONG_PER_DAY 번이면."""
        with self._lock:
            return self._locked(self._clock())

    def _locked(self, now: float) -> bool:
        self._wrong_at = [at for at in self._wrong_at if now - at < 86_400]
        return len(self._wrong_at) >= MAX_WRONG_PER_DAY

    # 찾기
    def hello(self) -> dict[str, Any]:
        info = dict(self._info() or {})
        return {"service": "sonjari", "name": info.get("name") or this_name(), "version": info.get("version") or "",
                "gpu": info.get("gpu") or "", "accepting": not self.locked()}

    # 짝 청하기 — 코드는 돌려주지 않는다(집 PC 화면에만)
    def request(self, child_name: str, child_id: str, *, peer: str = "") -> dict[str, Any]:
        child_name = " ".join(str(child_name or "").split())[:60] or "기기"
        child_id = str(child_id or "")[:80]
        with self._lock:
            now = self._clock()
            self._drop_expired(now)
            if self._locked(now):
                return {"ok": False, "error": "locked"}
            if now - self._last_request_at < REQUEST_GAP_SEC:
                return {"ok": False, "error": "too_fast"}
            if len(self._requests) >= MAX_OPEN_REQUESTS:
                return {"ok": False, "error": "too_many"}
            self._requested_at = [at for at in self._requested_at if now - at < 3_600]
            if len(self._requested_at) >= MAX_REQUESTS_PER_HOUR:
                return {"ok": False, "error": "too_many"}
            self._last_request_at = now
            self._requested_at.append(now)
            request_id = uuid.uuid4().hex
            code = f"{secrets.randbelow(1_000_000):06d}"
            self._requests[request_id] = {"code": code, "child_name": child_name, "child_id": child_id,
                                          "peer": str(peer or "")[:64], "expires_at": now + CODE_TTL_SEC, "tries": 0}
        # ★ 11-04 보안 점검: 사건 기록(/v1/events)은 열쇠 없이 읽히는 길이라 **코드를 싣지 않는다** — 집 PC 띠는
        #   열쇠가 있는 /v1/pair/pending 으로 코드를 받는다. 사건은 「다시 읽어라」는 신호일 뿐이다.
        self._publish("pair_request", {"request_id": request_id, "child_name": child_name,
                                       "expires_at": now + CODE_TTL_SEC})
        return {"ok": True, "request_id": request_id, "expires_in": CODE_TTL_SEC}

    def pending(self) -> list[dict[str, Any]]:
        """집 PC 화면의 띠가 그리는 것 — 코드가 여기 있다(이 길은 제어 토큰으로만 열린다)."""
        with self._lock:
            self._drop_expired(self._clock())
            return [{"request_id": rid, "child_name": row["child_name"], "code": row["code"],
                     "expires_at": row["expires_at"]} for rid, row in self._requests.items()]

    def reject(self, request_id: str) -> bool:
        with self._lock:
            gone = self._requests.pop(str(request_id), None) is not None
        if gone:
            self._publish("pair_request_closed", {"request_id": request_id, "why": "rejected"})
        return gone

    def confirm(self, request_id: str, code: str) -> dict[str, Any]:
        code = "".join(ch for ch in str(code or "") if ch.isdigit())
        closed: list[tuple[str, str]] = []   # (request_id, why) — 잠금 밖에서 알린다
        result: dict[str, Any]
        with self._lock:
            now = self._clock()
            self._drop_expired(now)
            if self._locked(now):
                return {"ok": False, "error": "locked"}
            row = self._requests.get(str(request_id))
            if not row:
                return {"ok": False, "error": "no_request"}
            if not hmac.compare_digest(code, row["code"]):
                row["tries"] += 1
                self._wrong_at.append(now)
                if self._locked(now):
                    # 이 PC 전체로 하루 10번 틀림 — 잠그고 열린 요청을 모두 닫는다(도배된 띠도 함께 사라진다).
                    closed = [(rid, "locked") for rid in self._requests]
                    self._requests.clear()
                    result = {"ok": False, "error": "locked"}
                elif row["tries"] >= MAX_TRIES:
                    self._requests.pop(str(request_id), None)
                    closed = [(str(request_id), "too_many_tries")]
                    result = {"ok": False, "error": "closed"}
                else:
                    result = {"ok": False, "error": "wrong_code", "tries_left": MAX_TRIES - row["tries"]}
            else:
                self._requests.pop(str(request_id), None)
                token = secrets.token_urlsafe(32)
                device_id = row["child_id"] or uuid.uuid4().hex
                devices = [d for d in self._devices() if d.get("device_id") != device_id]
                devices.append({"device_id": device_id, "name": row["child_name"], "token_sha256": _hash(token),
                                "paired_at": int(self._clock()), "last_used": 0})
                _atomic_write(self.data_dir / DEVICES_FILE, devices)
                closed = [(str(request_id), "paired")]
                result = {"ok": True, "token": token, "device_id": device_id}
        for rid, why in closed:
            self._publish("pair_request_closed", {"request_id": rid, "why": why})
        if result.get("error") == "locked":
            self._publish("pair_locked", {"wrong_in_day": MAX_WRONG_PER_DAY})
        if not result.get("ok"):
            return result
        self._publish("paired_device_added", {"device_id": result["device_id"], "name": row["child_name"]})
        info = self.hello()
        return {**result, "home_name": info["name"], "home_gpu": info["gpu"]}

    def verify(self, token: str) -> dict[str, Any] | None:
        token = str(token or "")
        if not token:
            return None
        digest = _hash(token)
        with self._lock:
            devices = self._devices()
            for device in devices:
                if hmac.compare_digest(str(device.get("token_sha256") or ""), digest):
                    now = int(self._clock())
                    if now - int(device.get("last_used") or 0) > 60:  # 1분에 한 번만 적는다
                        device["last_used"] = now
                        _atomic_write(self.data_dir / DEVICES_FILE, devices)
                    return {k: device.get(k) for k in ("device_id", "name")}
        return None

    def devices(self) -> list[dict[str, Any]]:
        return [{k: d.get(k) for k in ("device_id", "name", "paired_at", "last_used")} for d in self._devices()]

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            devices = self._devices()
            kept = [d for d in devices if d.get("device_id") != device_id]
            if len(kept) == len(devices):
                return False
            _atomic_write(self.data_dir / DEVICES_FILE, kept)
        self._publish("paired_device_removed", {"device_id": device_id})
        return True

    def _devices(self) -> list[dict[str, Any]]:
        rows = _read(self.data_dir / DEVICES_FILE, [])
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    def _drop_expired(self, now: float) -> None:
        for rid in [rid for rid, row in self._requests.items() if row["expires_at"] <= now]:
            self._requests.pop(rid, None)
            self._publish("pair_request_closed", {"request_id": rid, "why": "expired"})


# ── 이 맥(자식) 쪽 ───────────────────────────────────────────────────────────────────────────────

def device_id(data_dir: Path | str) -> str:
    """이 기기의 짝짓기 이름표 — 한 번 만들고 그대로 쓴다(다시 짝지으면 집 PC 가 같은 줄을 바꾼다)."""
    path = Path(data_dir) / "device_id.txt"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    value = uuid.uuid4().hex
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return value


def read_home(data_dir: Path | str) -> dict[str, Any]:
    raw = _read(Path(data_dir) / HOME_FILE, {})
    home = raw if isinstance(raw, dict) else {}
    # 11-04 이전에 짝지은 기억은 집 PC 본 백엔드(8091)를 가리킨다 — 이제 짝짓기 문(8092)으로 읽는다(파일은 다시 쓰지 않는다).
    address = str(home.get("address") or "")
    if address.endswith(f":{OLD_PAIR_PORT}"):
        home = {**home, "address": address[: -len(str(OLD_PAIR_PORT))] + str(PAIR_PORT)}
    return home


def save_home(data_dir: Path | str, home: dict[str, Any]) -> None:
    _atomic_write(Path(data_dir) / HOME_FILE, home)


def forget_home(data_dir: Path | str, store: Any) -> None:
    try:
        (Path(data_dir) / HOME_FILE).unlink()
    except OSError:
        pass
    try:
        store.delete(SECRET_TARGET)
    except Exception:  # noqa: BLE001 — 보관함에 없으면 됐다
        pass


def home_base(home: dict[str, Any]) -> str:
    address = str(home.get("address") or "")
    return f"http://{address}" if address else ""


def subnet_hosts(local_ip: str, prefix: int = 24) -> list[str]:
    try:
        net = ipaddress.ip_network(f"{local_ip}/{prefix}", strict=False)
    except ValueError:
        return []
    if not net.is_private or net.num_addresses > 1024:
        return []
    return [str(host) for host in net.hosts() if str(host) != local_ip]


def local_ipv4() -> str:
    """이 기기가 같은 네트워크로 나가는 주소 — 패킷을 실제로 보내지 않는다(UDP connect 는 길만 고른다)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return str(probe.getsockname()[0])
    except OSError:
        return ""
    finally:
        probe.close()


async def discover(*, remembered: str = "", extra: list[str] | None = None, timeout: float = 0.35,
                   get: Callable[..., Any] | None = None, tailnet_peers: list[str] | None = None) -> list[dict[str, Any]]:
    """같은 네트워크의 손자리를 찾는다 — 기억한 주소 · 따로 준 주소 · /24 · 테일넷 이웃(켜진 것)을 동시에. 5초 안.

    테일넷 이웃(11-04 · 밖에서도 쓰기 §3): 사람이 주소를 칠 일이 없게 `DNSName:8092` 도 두드린다. 같은 PC 가
    와이파이 · 테일넷 둘로 보이면 와이파이 쪽 한 줄만 남긴다(빠르다).
    """
    import asyncio

    import httpx

    targets: list[str] = []
    for item in [remembered, *(extra or [])]:
        if item and item not in targets:
            targets.append(item if ":" in item else f"{item}:{PAIR_PORT}")
    me = local_ipv4()
    targets += [f"{host}:{PAIR_PORT}" for host in subnet_hosts(me) if f"{host}:{PAIR_PORT}" not in targets]
    tailnet_targets = {f"{name}:{PAIR_PORT}" for name in (tailnet_peers or []) if name}
    targets += [address for address in sorted(tailnet_targets) if address not in targets]
    found: list[dict[str, Any]] = []
    limit = asyncio.Semaphore(96)

    async def one(client: Any, address: str) -> None:
        async with limit:
            try:
                response = await client.get(f"http://{address}/v1/pair/hello", timeout=timeout)
                data = response.json()
            except Exception:  # noqa: BLE001 — 안 닿는 주소가 대부분이다
                return
            if isinstance(data, dict) and data.get("service") == "sonjari" and data.get("accepting"):
                found.append({"address": address, "name": str(data.get("name") or ""), "gpu": str(data.get("gpu") or ""),
                              "version": str(data.get("version") or ""), "remembered": address == targets[0] and bool(remembered),
                              "via": "tailnet" if address in tailnet_targets else "lan"})

    async with httpx.AsyncClient() as client:
        try:
            await asyncio.wait_for(asyncio.gather(*(one(client, a) for a in targets)), timeout=5.0)
        except asyncio.TimeoutError:
            pass  # 5초 안에 찾은 것까지
    found.sort(key=lambda row: (not row["remembered"], row["via"] == "tailnet", row["name"]))
    seen: set[str] = set()
    kept = []
    for row in found:
        if row["name"] and row["name"] in seen:
            continue
        seen.add(row["name"])
        kept.append(row)
    return kept


def home_routes(home: dict[str, Any]) -> list[tuple[str, str]]:
    """집 PC 로 가는 길 — (이름, 주소). 집 와이파이 먼저(빠름), 그다음 테일넷(밖에서). 같은 주소는 한 번."""
    routes: list[tuple[str, str]] = []
    for via, key in (("lan", "address"), ("tailnet", "tailnet_address")):
        address = str(home.get(key) or "")
        if address and address not in [a for _v, a in routes]:
            routes.append((via, address))
    return routes
