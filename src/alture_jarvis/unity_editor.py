"""유니티 에디터 다리 — **열려 있는** 에디터를 온텔릭이 보고 만진다 (2026-09-27 · 게임 팩 2단계 · 전략안 §50).

## 배치 모드와 무엇이 다른가

레시피(`unity_tools.py`)는 에디터를 **닫은** 프로젝트를 배치 모드로 열어 점검한다. 사람이 에디터로 일하는 동안에는
잠금 때문에 못 돈다. 이 다리는 반대다 — 사람이 쓰고 있는 에디터 **안에서** 계층·선택·콘솔을 읽고, 승인을 받아 바꾼다.

## 어떻게 붙나 (MCP for Unity 온텔릭 사본, `packs/game/vendor/unity-mcp`)

- 사본 패키지가 에디터 안에서 `127.0.0.1:<포트>` 소켓을 연다(원본의 stdio 다리). 포트와 프로젝트는
  `~/.unity-mcp/unity-mcp-status-<해시>.json` 에 적힌다.
- 붙으면 유니티가 `WELCOME UNITY-MCP 1 FRAMING=1` 한 줄을 보내고, 그 뒤로는 **8바이트 길이(빅엔디언) + UTF-8 JSON**
  한 장씩 주고받는다. 명령은 `{"type": "<도구>", "params": {...}}`, 답은 `{"status": "success"|"error", ...}`.
- 원본의 파이썬 서버는 **안 쓴다.** 온텔릭이 그 자리에 선다. 원본 텔레메트리는 그 서버에만 있었다.
- 유니티는 명령을 **메인 스레드**에서 돌리고, 창이 뒤에 있어도 스스로 한 바퀴 돈다(`QueuePlayerLoopUpdate`) —
  창을 앞으로 끌어올 필요가 없다.

## 지키는 것

- 붙는 곳은 **127.0.0.1 만.** 상태 파일에 다른 주소가 적혀 있어도 따르지 않는다.
- 프로젝트는 허락된 자리만(레시피와 같은 장부 — `UnityTools._project`).
- 읽기는 바로, **바꾸기는 승인 카드**(L2). 우리가 보내는 인자는 표로 정해 둔다 — 원본 도구가 받는 나머지
  (프리팹으로 저장·임의 코드 실행 등)는 이 길로 안 보낸다.
- 바꾼 것은 유니티 Undo 에 그대로 쌓인다(원본 도구가 Undo 에 기록한다). 씬은 **저장하지 않는다** — 저장은 따로 승인.
- 되돌리기는 **우리가 한 변경이 맨 위일 때만.** 되돌려 보고 이름이 다르면(사람이 그 뒤에 한 일이면) 곧바로 다시 한다.

## 우리 방

다리를 지난 명령은 전부 `data_dir/packs/game/unity_bridge_log.jsonl` 에 한 줄씩 남는다(도구·동작·성공·걸린 시간·
오류 앞 200자). 원본이 바깥 서버로 보내던 것과 같은 종류의 기록을 **이 PC 에만** 쌓는다. 사람이 설정에서 켰을 때만
원본 주소로도 보내고, 보낸 것은 `unity_bridge_shared.jsonl` 에 따로 적는다.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from . import msix
from .brand import user_root
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec

EDITOR_TOOL_NAMES = frozenset({"unity_editor_status", "unity_editor_look", "unity_editor_change", "unity_editor_undo"})

PACKAGE_NAME = "com.coplaydev.unity-mcp"
_HANDSHAKE = b"WELCOME UNITY-MCP"
_MAX_FRAME = 16 * 1024 * 1024
#: 원본이 텔레메트리를 보내던 주소. 사람이 「같이 보내기」를 켰을 때만 쓴다.
COPLAY_TELEMETRY_URL = "https://api-prod.coplay.dev/telemetry/events"


class UnityBridgeError(RuntimeError):
    pass


def _norm(path: str | Path) -> str:
    text = str(path).replace("\\", "/").rstrip("/")
    if text.lower().endswith("/assets"):
        text = text[: -len("/assets")]
    return text.lower()


def _frame(payload: bytes) -> bytes:
    return struct.pack(">Q", len(payload)) + payload


def _read_exact(sock: socket.socket, count: int) -> bytes:
    chunks: list[bytes] = []
    left = count
    while left > 0:
        chunk = sock.recv(min(left, 1 << 16))
        if not chunk:
            raise UnityBridgeError("unity_bridge_closed: 유니티가 연결을 닫았다(스크립트 다시 불러오기 중일 수 있다)")
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


class UnityEditorBridge:
    """열린 유니티 에디터 하나에 명령 한 장을 보내고 답 한 장을 받는다. 판마다 새로 붙는다(원본 다리는 한 번에 하나만 받는다)."""

    def __init__(
        self,
        config: Any,
        unity_tools: Any = None,
        *,
        status_dir: Path | None = None,
        connect: Callable[..., socket.socket] = socket.create_connection,
        post: Callable[[str, dict[str, Any]], None] | None = None,
        clock: Callable[[], float] = time.time,
        # 사본을 둘 자리를 정하는 데 쓴다(`installed_copy`). 시험은 가짜 집과 「이 자리는 밖에서 안 보인다」를 넣는다.
        home: Path | None = None,
        hidden: Callable[[Path], bool] | None = None,
    ) -> None:
        self.config = config
        self.unity = unity_tools
        self._home = home
        self._hidden = hidden or msix.hidden_from_other_apps
        env_dir = os.environ.get("UNITY_MCP_STATUS_DIR", "").strip()
        self.status_dir = Path(status_dir or env_dir or (Path.home() / ".unity-mcp"))
        self._connect = connect
        self._post = post or _post_json
        self.clock = clock
        self._lock = threading.Lock()
        #: 우리가 바꾼 것 — 되돌리기가 「맨 위가 우리 것인가」를 확인하는 데 쓴다. 프로젝트별.
        self._changes: dict[str, list[dict[str, Any]]] = {}

    # ── 자리 ─────────────────────────────────────────────────────────────
    @property
    def room_dir(self) -> Path:
        return Path(self.config.data_dir) / "packs" / "game"

    @property
    def log_path(self) -> Path:
        return self.room_dir / "unity_bridge_log.jsonl"

    @property
    def shared_path(self) -> Path:
        return self.room_dir / "unity_bridge_shared.jsonl"

    @property
    def settings_path(self) -> Path:
        return self.room_dir / "unity_bridge.json"

    def settings(self) -> dict[str, Any]:
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not data.get("install_id"):
            data["install_id"] = str(uuid.uuid4())
            self._save_settings(data)
        return {"share_with_coplay": bool(data.get("share_with_coplay")), "install_id": str(data["install_id"])}

    def _save_settings(self, data: dict[str, Any]) -> None:
        self.room_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def set_share(self, on: bool) -> dict[str, Any]:
        """**사람만** 부른다(설정 화면). 켜면 다음 명령부터 원본 주소로도 같은 종류의 기록이 나간다."""
        data = self.settings()
        data["share_with_coplay"] = bool(on)
        self._save_settings(data)
        return self.settings()

    # ── 열린 에디터 찾기 ─────────────────────────────────────────────────
    def live_editors(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.status_dir.is_dir():
            return rows
        for path in sorted(self.status_dir.glob("unity-mcp-status-*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                port = int(data.get("unity_port") or 0)
            except (OSError, ValueError, TypeError):
                continue
            if not 0 < port < 65536:
                continue
            project = str(data.get("project_path") or "").replace("\\", "/")
            if project.lower().endswith("/assets"):
                project = project[: -len("/assets")]
            rows.append({
                "project": project,
                "project_name": str(data.get("project_name") or ""),
                "unity_version": str(data.get("unity_version") or ""),
                "port": port,
                "reloading": bool(data.get("reloading")),
                "reason": str(data.get("reason") or ""),
                "alive": self._probe(port),
            })
        return rows

    def _probe(self, port: int) -> bool:
        try:
            sock = self._connect(("127.0.0.1", port), 0.6)
        except OSError:
            return False
        try:
            sock.settimeout(1.5)
            return sock.recv(64).startswith(_HANDSHAKE)
        except OSError:
            return False
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def _editor_for(self, arguments: dict[str, Any]) -> dict[str, Any]:
        live = [row for row in self.live_editors() if row["alive"]]
        raw = next((str(arguments.get(key) or "").strip() for key in ("project", "project_path", "path") if str(arguments.get(key) or "").strip()), "")
        if raw:
            if self.unity is not None:
                raw = str(self.unity._project(arguments, write=False))  # noqa: SLF001 — 허락 장부를 같이 쓴다
            match = [row for row in live if _norm(row["project"]) == _norm(raw)]
            if not match:
                raise UnityBridgeError(
                    f"unity_editor_not_connected: {raw} 를 연 에디터가 손자리와 이어져 있지 않다. 에디터가 열려 있는지, "
                    "설정 › 팩 › 게임 팩에서 「에디터 잇기」를 했는지 사람에게 물어라."
                )
            return match[0]
        if len(live) == 1:
            row = live[0]
            if self.unity is not None:
                self.unity._project({"project": row["project"]}, write=False)  # noqa: SLF001 — 허락 안 된 프로젝트면 여기서 멈춘다
            return row
        if not live:
            raise UnityBridgeError(
                "unity_editor_not_connected: 손자리와 이어진 유니티 에디터가 없다. 에디터를 열고, 처음이면 설정 › 팩 › 게임 팩의 "
                "「에디터 잇기」를 눌러 달라고 사람에게 말해라."
            )
        raise UnityBridgeError(f"unity_editor_ambiguous: 이어진 에디터가 여럿이다 — project 를 줘라: {[row['project'] for row in live]}")

    # ── 한 장 주고받기 ───────────────────────────────────────────────────
    def call(self, port: int, command: str, params: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        started = time.monotonic()
        error = ""
        reply: dict[str, Any] = {}
        try:
            with self._lock:
                sock = self._connect(("127.0.0.1", int(port)), 3.0)
                try:
                    sock.settimeout(timeout)
                    greeting = b""
                    while not greeting.endswith(b"\n") and len(greeting) < 256:
                        chunk = sock.recv(1)
                        if not chunk:
                            break
                        greeting += chunk
                    if not greeting.startswith(_HANDSHAKE) or b"FRAMING=1" not in greeting:
                        raise UnityBridgeError(f"unity_bridge_handshake: 뜻밖의 인사 {greeting[:60]!r}")
                    body = json.dumps({"type": command, "params": params}, ensure_ascii=False).encode("utf-8")
                    sock.sendall(_frame(body))
                    (length,) = struct.unpack(">Q", _read_exact(sock, 8))
                    if not 0 < length <= _MAX_FRAME:
                        raise UnityBridgeError(f"unity_bridge_frame: 길이가 이상하다({length})")
                    reply = json.loads(_read_exact(sock, length).decode("utf-8"))
                finally:
                    sock.close()
        except socket.timeout:
            error = "unity_bridge_timeout: 유니티가 답하지 않았다(컴파일·가져오기 중이거나 멈춰 있을 수 있다)"
        except (OSError, ValueError) as exc:
            error = f"unity_bridge_io: {type(exc).__name__}: {exc}"
        except UnityBridgeError as exc:
            error = str(exc)
        ok = not error and str(reply.get("status") or "").lower() == "success"
        inner = reply.get("result") if isinstance(reply.get("result"), dict) else {}
        if ok and inner.get("success") is False:
            # ★ 2026-09-27 실측: 다리는 `status: success` 인데 도구 안에서 실패한 답(`result.success: false`)이 온다.
            #   겉만 보면 번호로 찾기가 전부 실패하는데도 「됐다」로 읽혔다.
            ok = False
            error = str(inner.get("error") or inner.get("code") or inner.get("message") or "unity_tool_failed")
        if not error and not ok:
            error = str(reply.get("error") or reply.get("message") or "unity_reported_error")
        self._record(command, str(params.get("action") or ""), ok, round((time.monotonic() - started) * 1000), error)
        if error and not reply:
            raise UnityBridgeError(error)
        return {"ok": ok, **({"error": error[:600]} if error else {}), "reply": reply}

    def _record(self, command: str, action: str, ok: bool, ms: int, error: str) -> None:
        row = {"at": round(self.clock(), 3), "tool": command, "action": action, "ok": ok, "ms": ms,
               **({"error": error[:200]} if error else {})}
        try:
            self.room_dir.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass
        settings = self.settings()
        if not settings["share_with_coplay"]:
            return
        # 원본 서버가 보내던 모양(`record`·`customer_uuid`·`data`)을 따른다. 보낸 것은 따로 적는다 — 무엇이 나갔는지 사람이 본다.
        payload = {
            "record": "tool_execution", "timestamp": row["at"], "customer_uuid": settings["install_id"],
            "session_id": settings["install_id"], "version": self._package_version(), "platform": "Windows", "source": "win32",
            "data": {"tool_name": command, "sub_action": action, "success": ok, "duration_ms": ms,
                     **({"error": error[:200]} if error else {})},
        }
        try:
            self._post(COPLAY_TELEMETRY_URL, payload)
            sent = {"at": row["at"], "to": COPLAY_TELEMETRY_URL, "payload": payload}
        except Exception as exc:  # noqa: BLE001 — 같이 보내기가 실패해도 일은 계속한다
            sent = {"at": row["at"], "to": COPLAY_TELEMETRY_URL, "failed": f"{type(exc).__name__}: {str(exc)[:120]}"}
        try:
            with self.shared_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(sent, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def room(self, limit: int = 200) -> dict[str, Any]:
        """우리 방 요약 — 어떤 도구가 몇 번, 몇 번 실패했나. 교훈·레시피 후보의 원료다."""
        rows: list[dict[str, Any]] = []
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()[-5000:]
        except OSError:
            lines = []
        for line in lines:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        by_tool: dict[str, dict[str, int]] = {}
        for row in rows:
            key = f"{row.get('tool')}:{row.get('action') or '-'}"
            slot = by_tool.setdefault(key, {"calls": 0, "failed": 0})
            slot["calls"] += 1
            slot["failed"] += 0 if row.get("ok") else 1
        shared = 0
        try:
            shared = sum(1 for _ in self.shared_path.open(encoding="utf-8"))
        except OSError:
            pass
        return {"calls": len(rows), "by_tool": dict(sorted(by_tool.items(), key=lambda item: -item[1]["calls"])),
                "recent": rows[-limit:][::-1][:20], "shared_count": shared, **self.settings()}

    # ── 도구 본문 ────────────────────────────────────────────────────────
    def _ask(self, editor: dict[str, Any], command: str, params: dict[str, Any]) -> Any:
        out = self.call(editor["port"], command, params)
        if not out["ok"]:
            raise UnityBridgeError(f"unity_command_failed: {command} — {out.get('error', '')}")
        reply = out["reply"]
        return reply.get("result", reply.get("data", reply))

    def status(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = dict(arguments or {})
        editors = self.live_editors()
        out: dict[str, Any] = {"action": "unity_editor_status", "editors": editors}
        try:
            editor = self._editor_for(arguments)
        except (UnityBridgeError, PermissionError, ValueError) as exc:
            out["connected"] = False
            out["note"] = str(exc)
            return out
        out["connected"] = True
        out["project"] = editor["project"]
        for key, command, params in (
            ("editor_state", "get_editor_state", {}),
            ("active_scene", "manage_scene", {"action": "get_active"}),
            ("selection", "get_selection", {}),
        ):
            try:
                out[key] = _trim(self._ask(editor, command, params))
            except UnityBridgeError as exc:
                out[key] = {"error": str(exc)[:300]}
        out["verified"] = True
        return out

    _LOOK = ("hierarchy", "console", "selection", "find", "components")

    def look(self, arguments: dict[str, Any]) -> dict[str, Any]:
        what = str(arguments.get("what") or "hierarchy").strip().lower()
        if what not in self._LOOK:
            raise ValueError(f"unity_look_what: what 은 {list(self._LOOK)} 중 하나")
        editor = self._editor_for(arguments)
        target = str(arguments.get("target") or "").strip()
        if what == "hierarchy":
            params: dict[str, Any] = {"action": "get_hierarchy", "pageSize": _clamp(arguments.get("limit"), 50, 1, 200),
                                      "maxDepth": _clamp(arguments.get("depth"), 3, 1, 12)}
            if target:
                params["parent"] = target
            if arguments.get("cursor") is not None:
                params["cursor"] = _clamp(arguments.get("cursor"), 0, 0, 1_000_000)
            command = "manage_scene"
        elif what == "console":
            kinds = arguments.get("types") if isinstance(arguments.get("types"), list) else ["error", "warning"]
            params = {"action": "get", "types": [str(kind).lower() for kind in kinds][:3],
                      "count": _clamp(arguments.get("limit"), 30, 1, 200), "format": "plain"}
            if arguments.get("filter"):
                params["filterText"] = str(arguments.get("filter"))[:120]
            command = "read_console"
        elif what == "selection":
            params, command = {}, "get_selection"
        elif what == "find":
            term = str(arguments.get("search") or target).strip()
            if not term:
                raise ValueError("unity_look_find: search 에 찾을 이름을 줘라")
            params = {"searchTerm": term[:120], "searchMethod": str(arguments.get("method") or "by_name"),
                      "includeInactive": bool(arguments.get("include_inactive", True))}
            command = "find_gameobjects"
        else:
            if not target:
                raise ValueError("unity_look_components: target 에 오브젝트 instanceID 또는 이름을 줘라")
            params = {"instanceID": target, "pageSize": 20, "includeProperties": bool(arguments.get("properties", True))}
            command = "get_gameobject_components"
        result = self._ask(editor, command, params)
        return {"action": "unity_editor_look", "what": what, "project": editor["project"], "result": _trim(result), "verified": True}

    #: 우리가 원본 도구에 넘기는 인자 — **여기 없는 것은 안 보낸다**(프리팹 저장·임의 코드 등은 이 길로 못 간다).
    #: (우리 인자, 원본 인자) 짝.
    _CHANGE_KEYS: dict[str, tuple[tuple[str, str], ...]] = {
        "create": (("name", "name"), ("primitive_type", "primitiveType"), ("prefab_path", "prefabPath"),
                   ("position", "position"), ("rotation", "rotation"), ("scale", "scale"), ("parent", "parent"),
                   ("tag", "tag"), ("components", "componentsToAdd")),
        "modify": (("target", "target"), ("new_name", "newName"), ("position", "position"), ("rotation", "rotation"),
                   ("scale", "scale"), ("parent", "parent"), ("active", "setActive"), ("tag", "tag"),
                   ("components", "componentsToAdd"), ("remove_components", "componentsToRemove"),
                   ("properties", "componentProperties")),
        "delete": (("target", "target"),),
        "duplicate": (("target", "target"), ("new_name", "new_name")),
    }

    def change(self, arguments: dict[str, Any]) -> dict[str, Any]:
        op = str(arguments.get("op") or "").strip().lower()
        editor = self._editor_for(arguments)
        if op == "save_scene":
            self._ask(editor, "manage_scene", {"action": "save"})
            return {"action": "unity_editor_change", "op": op, "project": editor["project"], "saved": True, "verified": True}
        keys = self._CHANGE_KEYS.get(op)
        if keys is None:
            raise ValueError(f"unity_change_op: op 은 {sorted(self._CHANGE_KEYS) + ['save_scene']} 중 하나")
        params: dict[str, Any] = {"action": op}
        for ours, theirs in keys:
            if arguments.get(ours) not in (None, "", [], {}):
                params[theirs] = arguments[ours]
        if op != "create" and "target" not in params:
            raise ValueError("unity_change_target: target 에 바꿀 오브젝트 이름·경로·instanceID 를 줘라")
        if op == "create" and not params.get("name"):
            raise ValueError("unity_change_name: 새 오브젝트의 name 을 줘라")
        before_id = 0 if op == "create" else self._resolve_id(editor, str(params["target"]))
        result = self._ask(editor, "manage_gameobject", params)
        data = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else {}
        # 되돌리기가 「맨 위가 우리 것인가」를 **결과로** 확인할 수 있게 적어 둔다: 만든 것은 사라져야 하고,
        # 지운 것은 돌아와야 하고, 바꾼 것은 값이 달라져야 한다.
        object_id = _int(data.get("instanceID")) if op in {"create", "duplicate"} else before_id
        record: dict[str, Any] = {"op": op, "id": object_id, "label": str(arguments.get("target") or arguments.get("name") or ""),
                                  "at": self.clock()}
        if op == "modify" and object_id:
            record["after"] = self._snapshot(editor, object_id)
        self._changes.setdefault(_norm(editor["project"]), []).append(record)
        return {
            "action": "unity_editor_change", "op": op, "project": editor["project"], "result": _trim(result),
            "verified": True, "scene_saved": False,
            "note": "에디터 Undo 에 기록됐다. 씬은 아직 저장하지 않았다 — 저장은 op=save_scene(승인)이나 사람이 Ctrl+S.",
        }

    def _resolve_id(self, editor: dict[str, Any], target: str) -> int:
        if target.lstrip("-").isdigit():
            return int(target)
        method = "by_path" if "/" in target else "by_name"
        found = self._ask(editor, "find_gameobjects", {"searchMethod": method, "searchTerm": target, "includeInactive": True})
        ids = (found.get("data") or {}).get("instanceIDs") if isinstance(found, dict) else None
        return _int(ids[0]) if ids else 0

    def _exists(self, editor: dict[str, Any], object_id: int) -> bool:
        found = self._ask(editor, "find_gameobjects", {"searchMethod": "by_id", "searchTerm": str(object_id), "includeInactive": True})
        return bool(((found.get("data") or {}).get("instanceIDs") if isinstance(found, dict) else None))

    def _snapshot(self, editor: dict[str, Any], object_id: int) -> Any:
        out = self.call(editor["port"], "get_gameobject", {"instanceID": object_id})
        reply = out.get("reply") or {}
        inner = reply.get("result") if isinstance(reply.get("result"), dict) else {}
        return inner.get("data") if out["ok"] else None

    def _took_effect(self, editor: dict[str, Any], change: dict[str, Any]) -> bool:
        if change["op"] in {"create", "duplicate"}:
            return not self._exists(editor, change["id"])
        if change["op"] == "delete":
            # 되살린 오브젝트가 새 번호를 받을 수도 있다 — 번호로 못 찾으면 이름으로 한 번 더 본다.
            return self._exists(editor, change["id"]) or bool(change["label"] and self._resolve_id(editor, change["label"]))
        return self._snapshot(editor, change["id"]) != change.get("after")

    def undo(self, arguments: dict[str, Any]) -> dict[str, Any]:
        editor = self._editor_for(arguments)
        mine = self._changes.get(_norm(editor["project"])) or []
        if not mine:
            return {"action": "unity_editor_undo", "undone": False, "reason": "손자리가 이 에디터에서 바꾼 것이 없다(이번 실행 기준)."}
        last = mine[-1]
        if not last.get("id"):
            return {"action": "unity_editor_undo", "undone": False,
                    "reason": "마지막 변경의 대상을 확인할 수 없어 되돌리지 않았다 — 에디터에서 사람이 Ctrl+Z 로 고르게 해라."}
        self._ask(editor, "manage_editor", {"action": "undo"})
        if not self._took_effect(editor, last):
            # 맨 위가 우리 것이 아니었다 — 사람이 그 뒤에 한 일을 지웠을 수 있으니 곧바로 되살린다.
            # (유니티가 돌려주는 되돌린 작업 이름은 비어 있을 때가 많아 믿지 않는다 — 2026-09-27 실측.)
            self._ask(editor, "manage_editor", {"action": "redo"})
            return {"action": "unity_editor_undo", "undone": False, "restored": True,
                    "reason": "맨 위 작업이 손자리 것이 아니었다 — 사람이 그 뒤에 한 일을 지우지 않도록 곧바로 되살렸다. "
                              "에디터에서 사람이 Ctrl+Z 로 고르게 해라."}
        mine.pop()
        return {"action": "unity_editor_undo", "undone": True, "op": last["op"], "target": last["label"], "verified": True}

    # ── 프로젝트에 잇기·풀기 (사람만 — 설정 화면) ─────────────────────────
    def _package_version(self) -> str:
        try:
            return str(json.loads((self.vendor_dir() / "package.json").read_text(encoding="utf-8"))["version"])
        except (OSError, ValueError, KeyError):
            return ""

    def vendor_dir(self) -> Path:
        return Path(getattr(self.config, "packs_dir", "")) / "game" / "vendor" / "unity-mcp" / "MCPForUnity"

    def installed_copy(self) -> Path:
        """프로젝트가 가리킬 사본 자리 — 앱을 새로 깔아도(스토어판 폴더가 바뀌어도) 그대로이고, **유니티가 읽을 수 있는** 자리.

        ★ 2026-10-12 스토어판으로 게임 팩을 처음 쓴 사람의 화면이 「에디터가 패키지를 읽는 중」에서 안 넘어갔다.
          사본을 데이터 폴더(`data_dir/packs/game` — AppData)에 뒀는데, 스토어 앱이 거기 **새로 만든 파일은 그 앱만 보는
          전용 칸**으로 간다. 프로젝트 설정에 적어 준 폴더에 유니티가 가 보면 아무것도 없다. 09-18 에 Ollama 가 같은
          까닭으로 모델을 못 올려 엔진 자리를 사용자 폴더로 옮겼는데(`brand.engine_dir`) 이 사본은 빠져 있었다.
          밖에서 안 보이는 자리면 사용자 폴더(`~\\Sonjari\\unity-mcp`)에 둔다. 설치형 · 개발 실행은 예전 자리 그대로다.
        """
        version = json.loads((self.vendor_dir() / "package.json").read_text(encoding="utf-8"))["version"]
        inside = self.room_dir / "unity-mcp" / version / "MCPForUnity"
        if self._hidden(inside):
            return user_root(self._home or Path.home()) / "unity-mcp" / version / "MCPForUnity"
        return inside

    def _manifest(self, project: Path) -> Path:
        return project / "Packages" / "manifest.json"

    def install_state(self, project: Path) -> dict[str, Any]:
        try:
            deps = dict(json.loads(self._manifest(project).read_text(encoding="utf-8")).get("dependencies") or {})
        except (OSError, ValueError):
            deps = {}
        value = str(deps.get(PACKAGE_NAME) or "")
        # 온텔릭 사본이면 어느 온텔릭이 이었든 이은 것이다(시험 백엔드·다른 데이터 폴더가 이은 판을 「원본」으로 부르면 틀린다).
        ours = self._is_our_copy(value)
        # 이어 두었지만 그 줄이 **밖에서 안 보이는 자리**를 가리키면 유니티는 못 읽는다(스토어판의 예전 판이 적은 줄).
        # 「다시 잇기」가 읽을 수 있는 자리로 고쳐 적는다(`install`).
        broken = ours and self._hidden(Path(value[len("file:"):]))
        return {"installed": ours, "other_version": bool(value) and not ours, "value": value, "broken": bool(broken)}

    @staticmethod
    def _is_our_copy(value: Any) -> bool:
        text = str(value or "")
        return text.startswith("file:") and "-ontelic." in text and "/unity-mcp/" in text.replace("\\", "/")

    def install(self, project: Path) -> dict[str, Any]:
        import shutil

        manifest_path = self._manifest(project)
        text = manifest_path.read_text(encoding="utf-8")
        data = json.loads(text)
        copy = self.installed_copy()
        if not (copy / "package.json").is_file():
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.vendor_dir(), copy)
        deps = data.setdefault("dependencies", {})
        previous = deps.get(PACKAGE_NAME)
        backups = self.room_dir / "manifest_backups"
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / f"{_slug(project)}-{int(self.clock())}.json"
        backup.write_text(text, encoding="utf-8")
        deps[PACKAGE_NAME] = "file:" + str(copy).replace("\\", "/")
        self._remember_previous(project, previous)
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        resolved = self._resolve_packages(project)
        return {"ok": True, "project": str(project), "package": deps[PACKAGE_NAME], "backup": str(backup),
                "replaced": previous or "", "resolved_now": resolved,
                "next": ("에디터가 새 패키지를 읽고 있습니다(창을 건드리지 않고 20초 안팎)." if resolved else
                         "에디터가 열려 있으면 유니티 창을 한 번 누르면 패키지를 읽습니다. 닫혀 있으면 다음에 열 때 읽습니다.")}

    def _resolve_packages(self, project: Path) -> bool:
        """이미 이어진 에디터면 패키지를 다시 읽으라고 시킨다. ★ 2026-09-27: 매니페스트만 바꾸면 유니티는 창이 포커스를
        받을 때까지 옛 패키지를 쓴다(새로고침으로는 안 읽었다). 이 명령이면 창을 건드리지 않고 19초에 새 판이 올라왔다."""
        for row in self.live_editors():
            if row["alive"] and _norm(row["project"]) == _norm(project):
                try:
                    return bool(self.call(row["port"], "manage_packages", {"action": "resolve_packages"})["ok"])
                except UnityBridgeError:
                    return False
        return False

    def uninstall(self, project: Path) -> dict[str, Any]:
        manifest_path = self._manifest(project)
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        deps = data.setdefault("dependencies", {})
        if not self.install_state(project)["installed"]:
            return {"ok": True, "removed": False}
        previous = self._previous(project)
        if previous:
            deps[PACKAGE_NAME] = previous
        else:
            deps.pop(PACKAGE_NAME, None)
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "removed": True, "restored": previous or ""}

    def _previous_path(self) -> Path:
        return self.room_dir / "unity_mcp_previous.json"

    def _remember_previous(self, project: Path, value: Any) -> None:
        try:
            data = json.loads(self._previous_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        key = _norm(project)
        if key not in data:  # 두 번 잇기해도 맨 처음 값을 지킨다
            # 우리가 적었던 줄(어느 자리의 사본이든)은 「원래 값」이 아니다 — 풀 때 되살리지 않는다.
            data[key] = value if isinstance(value, str) and not self._is_our_copy(value) else ""
        self._previous_path().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def _previous(self, project: Path) -> str:
        try:
            return str(json.loads(self._previous_path().read_text(encoding="utf-8")).get(_norm(project)) or "")
        except (OSError, ValueError):
            return ""

    # ── 등록 ─────────────────────────────────────────────────────────────
    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        project = {"type": "string", "description": "유니티 프로젝트 폴더. 이어진 에디터가 하나면 비워도 된다."}
        return [
            {"type": "function", "function": {
                "name": "unity_editor_status",
                "description": "지금 열려 있어 손자리와 이어진 유니티 에디터와, 그 에디터의 상태(재생 중·컴파일 중)·열린 씬·선택을 본다.",
                "parameters": {"type": "object", "properties": {"project": project}, "required": []},
            }},
            {"type": "function", "function": {
                "name": "unity_editor_look",
                "description": (
                    "열린 유니티 에디터 안을 읽는다(바꾸지 않는다). what: hierarchy(씬 계층) · console(오류·경고) · "
                    "selection(사람이 고른 것) · find(이름으로 찾기) · components(한 오브젝트의 컴포넌트와 값)."
                ),
                "parameters": {"type": "object", "properties": {
                    "what": {"type": "string", "enum": list(self._LOOK)},
                    "target": {"type": "string", "description": "components·hierarchy 의 기준 오브젝트(instanceID 또는 이름)"},
                    "search": {"type": "string", "description": "find 에서 찾을 이름"},
                    "limit": {"type": "integer"}, "project": project,
                }, "required": ["what"]},
            }},
            {"type": "function", "function": {
                "name": "unity_editor_change",
                "description": (
                    "열린 유니티 에디터에서 게임오브젝트를 만들고·바꾸고·지우고·복제한다(op). 손자리 창의 **승인**이 필요하고, "
                    "바꾼 것은 에디터 Undo 에 남는다. 씬은 저장하지 않는다 — 저장은 op=save_scene(따로 승인)."
                ),
                "parameters": {"type": "object", "properties": {
                    "op": {"type": "string", "enum": [*self._CHANGE_KEYS, "save_scene"]},
                    "target": {"type": "string", "description": "바꿀 오브젝트(이름·경로·instanceID)"},
                    "name": {"type": "string", "description": "create 에서 새 이름"},
                    "new_name": {"type": "string"},
                    "primitive_type": {"type": "string", "description": "Cube·Sphere·Plane·Capsule·Cylinder·Quad"},
                    "prefab_path": {"type": "string", "description": "create 에서 이 프리팹으로 만들기(Assets/...prefab)"},
                    "position": {"type": "array", "items": {"type": "number"}},
                    "rotation": {"type": "array", "items": {"type": "number"}},
                    "scale": {"type": "array", "items": {"type": "number"}},
                    "parent": {"type": "string"},
                    "active": {"type": "boolean"},
                    "tag": {"type": "string"},
                    "components": {"type": "array", "items": {"type": "string"}, "description": "붙일 컴포넌트 이름"},
                    "remove_components": {"type": "array", "items": {"type": "string"}},
                    "properties": {"type": "object", "description": "{컴포넌트: {속성: 값}}"},
                    "project": project,
                }, "required": ["op"]},
            }},
            {"type": "function", "function": {
                "name": "unity_editor_undo",
                "description": "손자리가 이 에디터에서 마지막으로 바꾼 것을 되돌린다. 그 뒤에 사람이 한 작업이 맨 위면 건드리지 않는다.",
                "parameters": {"type": "object", "properties": {"project": project}, "required": []},
            }},
        ]

    def register(self, gateway: ToolGateway, guard: Callable[[Any], Any] | None = None) -> None:
        guard = guard or (lambda handler: handler)
        handlers = {
            "unity_editor_status": (self.status, RiskLevel.L0),
            "unity_editor_look": (self.look, RiskLevel.L0),
            "unity_editor_change": (self.change, RiskLevel.L2),
            # 되돌리기는 우리 변경을 지우는 일이고, 사람의 작업이면 스스로 되살린다 — 승인 없이.
            "unity_editor_undo": (self.undo, RiskLevel.L1),
        }
        for tool in self.ollama_tools:
            spec = tool["function"]
            handler, risk = handlers[spec["name"]]
            gateway.register(ToolSpec(
                name=spec["name"], description=str(spec["description"]), parameters=dict(spec["parameters"]),
                risk_level=risk, handler=guard(handler),
                enabled=bool(getattr(self.config, "local_computer_enabled", True)),
                needs_job_context=True,
            ))


def _clamp(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _slug(project: Path) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in Path(project).name)[:40] or "project"


def _trim(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "…"
    if isinstance(value, dict):
        return {key: _trim(item, depth + 1) for key, item in list(value.items())[:80]}
    if isinstance(value, list):
        head = [_trim(item, depth + 1) for item in value[:80]]
        return head + ([{"_truncated": len(value) - 80}] if len(value) > 80 else [])
    if isinstance(value, str) and len(value) > 2000:
        return value[:2000] + "…"
    return value


def _post_json(url: str, payload: dict[str, Any]) -> None:
    import urllib.request

    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 — 사람이 켠 「같이 보내기」 한 곳뿐
        response.read(0)


__all__ = ["COPLAY_TELEMETRY_URL", "EDITOR_TOOL_NAMES", "PACKAGE_NAME", "UnityBridgeError", "UnityEditorBridge"]
