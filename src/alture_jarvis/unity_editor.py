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
- 읽기는 바로. 바꾸기는 **11-11 대표 결정으로 승인 없이**(L1) — 유니티 Undo 에 남고 우리 되돌리기가 있다.
  (맥 판 전수조사: 사람에게 넘긴 까닭은 모델 실력이 아니라 연결 빈틈이었다.) 예전엔 승인 카드(L2)였다. 우리가 보내는 인자는 표로 정해 둔다 — 원본 도구가 받는 나머지
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
import subprocess
import struct
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from . import msix
from .brand import user_root
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec

EDITOR_TOOL_NAMES = frozenset({
    "unity_editor_status", "unity_editor_look", "unity_editor_change", "unity_editor_undo", "unity_editor_launch",
    "unity_editor_refresh",
})

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
        # 에디터 띄우기(`launch`) — 시험은 가짜를 넣는다(진짜 유니티를 안 띄운다).
        spawn: Callable[[Path, Path], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        # 띄운 뒤 유니티가 스스로 앞으로 나오면 원래 앞 앱으로 돌려놓는다(맥만). 시험은 가짜를 넣는다.
        keep_front: Callable[[], None] | None = None,
    ) -> None:
        self.config = config
        self.unity = unity_tools
        self._home = home
        self._hidden = hidden or msix.hidden_from_other_apps
        env_dir = os.environ.get("UNITY_MCP_STATUS_DIR", "").strip()
        self.status_dir = Path(status_dir or env_dir or (Path.home() / ".unity-mcp"))
        self._connect = connect
        self._spawn = spawn or _spawn_editor
        self._sleep = sleep
        self._monotonic = time.monotonic
        self._keep_front = keep_front if keep_front is not None else (_start_front_keeper if sys.platform == "darwin" else None)
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
                    f"unity_editor_not_connected: {raw} 를 연 에디터가 손자리와 이어져 있지 않다. 사람에게 묻기 전에 "
                    "unity_editor_launch 를 불러라 — 다리를 붙이고, 에디터를 (앞으로 끌어오지 않고) 띄워 이어질 때까지 기다린다. "
                    "셸로 유니티를 직접 띄우거나 manifest.json 을 손으로 고치지 마라."
                )
            return match[0]
        if len(live) == 1:
            row = live[0]
            if self.unity is not None:
                self.unity._project({"project": row["project"]}, write=False)  # noqa: SLF001 — 허락 안 된 프로젝트면 여기서 멈춘다
            return row
        if not live:
            raise UnityBridgeError(
                "unity_editor_not_connected: 손자리와 이어진 유니티 에디터가 없다. 사람에게 묻기 전에 unity_editor_launch 를 "
                "project 와 함께 불러라 — 다리를 붙이고 에디터를 (앞으로 끌어오지 않고) 띄워 이어질 때까지 기다린다. "
                "셸로 유니티를 직접 띄우거나 manifest.json 을 손으로 고치지 마라."
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
            "session_id": settings["install_id"], "version": self._package_version(), "platform": "macOS" if sys.platform == "darwin" else "Windows", "source": sys.platform,
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

    # ── 화면 찍기 (2026-11-08 밤 · 설계 generated_reports/bug_guard_game/설계_유니티_화면보기.md) ─────────────────
    #
    # 유니티가 스스로 카메라 화면을 그려 파일로 저장한다(원본 다리의 manage_scene/screenshot) — 화면 클릭이 아니라 맥 · 윈도우 같다.
    # 저장은 프로젝트의 Temp/SonjariShots(원본은 프로젝트 밖을 거절 · 기본값 Assets/Screenshots 는 에셋 · git 을 더럽힌다).
    # 그림은 다리 응답에 싣지 않고(큰 응답 끊김 · 사고 N) 파일로 받아, 본체의 그림 보기 곁 호출(`viewer`)이 같은 걸음 안에서 본다.
    SHOT_FOLDER = "Temp/SonjariShots"
    SHOT_KEEP = 20
    SHOT_ASYNC_WAIT_SEC = 6.0
    SHOT_DEFAULT_QUESTION = "화면에 무엇이 보이는지, 비어 있거나 잘린 곳, 서로 겹친 것을 말하라."
    #: 본체가 꽂는다 — (그림 JPEG 바이트, 질문) → 답 글 · 그림을 못 읽는 모델이면 True. 없으면 찍기만 한다.
    viewer: Callable[[bytes, str], str] | None = None
    cannot_see: Callable[[], bool] | None = None

    def _screenshot(self, editor: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
        source = str(arguments.get("source") or "game_view").strip().lower()
        if source not in ("game_view", "scene_view"):
            raise ValueError("unity_look_screenshot: source 는 game_view · scene_view 중 하나")
        fell_back = False
        try:
            shot = self._capture_file(editor, source, camera=str(arguments.get("camera") or "").strip(),
                                      target=str(arguments.get("target") or "").strip())
        except UnityBridgeError as exc:
            # Game 탭이 닫혀 있으면 게임 화면은 그려지지 않아 파일이 안 생긴다 — 씬 화면으로 한 번 더 찍는다(11-12).
            if source != "game_view" or "unity_screenshot_missing" not in str(exc):
                raise
            shot = self._capture_file(editor, "scene_view", target=str(arguments.get("target") or "").strip())
            source, fell_back = "scene_view", True
        out: dict[str, Any] = {"action": "unity_editor_look", "what": "screenshot", "project": editor["project"],
                               "source": source, "image_path": str(shot), "verified": True}
        if fell_back:
            out["note"] = "게임 화면이 그려지지 않아(Game 탭이 닫혔을 수 있다) 씬 화면으로 찍었다 — 게임 카메라 시점이 아니다."
        question = str(arguments.get("question") or "").strip()[:500] or self.SHOT_DEFAULT_QUESTION
        if self.viewer is None or (self.cannot_see is not None and self.cannot_see()):
            out["note"] = " ".join(filter(None, [out.get("note"),
                                                 "지금 모델은 그림을 못 읽는다 — 그림은 image_path 로 사람 · 바깥 AI 가 본다(지어내지 않는다)."]))
            return out
        from PIL import Image

        from .image_look import LOOK_PROMPT, compose

        with Image.open(shot) as img:
            jpeg = compose([img.copy()])
        out["question"] = question
        out["answer"] = self.viewer(jpeg, LOOK_PROMPT + question)
        return out

    def stage_shot(self, source: str = "scene_view") -> tuple[bytes, int, int]:
        """손자리 창의 「유니티 무대」용 한 장(JPEG · 가로 · 세로) — 창을 복사할 수 없는 맥에서 쓴다(11-08 밤 대표: 에디터가 있는데 안 뜬다)."""
        editors = [row for row in self.live_editors() if row.get("alive")]
        if not editors:
            raise UnityBridgeError("unity_no_editor")
        shot = self._capture_file(editors[0], source, prefix="stage")
        from PIL import Image

        from .image_look import _jpeg

        with Image.open(shot) as img:
            width, height = img.size
            return _jpeg(img.copy(), 1600), width, height

    def _capture_file(self, editor: dict[str, Any], source: str, *, camera: str = "", target: str = "",
                      prefix: str = "sonjari") -> Path:
        """원본 다리로 찍게 하고, 그 프로젝트의 찍기 폴더 안에 생긴 PNG 경로를 돌려준다."""
        params: dict[str, Any] = {
            "action": "screenshot", "captureSource": source, "outputFolder": self.SHOT_FOLDER,
            "includeImage": False, "maxResolution": 1024,
            "fileName": f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.png",
        }
        if camera and source == "game_view":
            params["camera"] = camera[:120]
        if target:
            params["viewTarget"] = target[:120]
        result = self._ask(editor, "manage_scene", params)
        data = result.get("data", result) if isinstance(result, dict) else {}
        full = str((data or {}).get("fullPath") or "").strip()
        project = Path(str(editor["project"])).resolve(strict=False)
        shot = Path(full).resolve(strict=False) if full else None
        # ★ 게임 화면은 유니티가 다음 프레임에 늦게 쓴다(isAsync · 11-08 밤 실기기: 요청 성공인데 파일이 없어 두 번 실패) — 잠깐 기다린다.
        if shot is not None and not shot.is_file() and (data or {}).get("isAsync"):
            deadline = time.monotonic() + self.SHOT_ASYNC_WAIT_SEC
            while time.monotonic() < deadline and not shot.is_file():
                time.sleep(0.25)
        # 원본이 돌려준 경로가 그 프로젝트의 찍기 폴더 안일 때만 연다 — 다리 응답으로 아무 파일이나 읽지 않게.
        folder = (project / self.SHOT_FOLDER).resolve(strict=False)
        if shot is None or not shot.is_file() or folder not in shot.parents:
            raise UnityBridgeError(f"unity_screenshot_missing: 찍은 파일을 못 찾았다 ({full or '경로 없음'}) — 원본 응답: {_trim(result)}")
        self._prune_shots(folder)
        return shot

    def _prune_shots(self, folder: Path) -> None:
        try:
            shots = sorted([*folder.glob("sonjari-*.png"), *folder.glob("stage-*.png")],
                           key=lambda path: path.stat().st_mtime, reverse=True)
        except OSError:
            return
        for old in shots[self.SHOT_KEEP:]:
            try:
                old.unlink()
            except OSError:
                pass

    _LOOK = ("hierarchy", "console", "selection", "find", "components", "screenshot")

    def look(self, arguments: dict[str, Any]) -> dict[str, Any]:
        what = str(arguments.get("what") or "hierarchy").strip().lower()
        if what not in self._LOOK:
            raise ValueError(f"unity_look_what: what 은 {list(self._LOOK)} 중 하나")
        editor = self._editor_for(arguments)
        if what == "screenshot":
            return self._screenshot(editor, arguments)
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
            # ★ 11-08~11 맥 4번 실패(`'instanceID' parameter is required`): 이름을 그대로 넘겼다 — 원본은 숫자만 받는다.
            params = {"instanceID": self._resolve_id(editor, target), "pageSize": 20,
                      "includeProperties": bool(arguments.get("properties", True))}
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
            # ★ 11-11 맥: 손자리가 만든 새 씬은 이름이 없다(untitled). 원본 다리는 name · path 를 주면 「다른 이름으로 저장」을
            #   하는데 우리가 action 만 보내서 「이름 없는 씬은 못 저장」으로 막혔고, 대표에게 File → Save As 를 부탁했다.
            params: dict[str, Any] = {"action": "save"}
            name = str(arguments.get("name") or "").strip()
            if name:
                params["name"] = _scene_name(name)
                # 「path」는 에디터 고르기가 프로젝트 경로로 읽는다(`_editor_for`) — 씬 폴더는 따로 이름 붙인다.
                params["path"] = _scene_folder(str(arguments.get("scene_folder") or "Scenes"))
            reply = self._ask(editor, "manage_scene", params)
            saved_to = str((reply.get("data") or reply).get("path") or "") if isinstance(reply, dict) else ""
            return {"action": "unity_editor_change", "op": op, "project": editor["project"], "saved": True,
                    "path": saved_to, "verified": True}
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
        linked: list[str] = []
        if isinstance(params.get("componentProperties"), dict):
            params["componentProperties"], linked = self._link_refs(editor, params["componentProperties"], bare=False)
        try:
            result = self._ask(editor, "manage_gameobject", params)
        except UnityBridgeError as exc:
            # ★ 11-12 맥(판 b2e846a3): 모델이 참조 칸에 「Main Camera」처럼 이름 글자를 넣었다 — 원본 다리는 글자를 에셋 경로로만 읽어
            #   「property operations failed」. 장면에 **정확히 그 이름**이 있는 칸만 번호(instanceID)로 바꿔 한 번 더 넣는다.
            retried = False
            if isinstance(params.get("componentProperties"), dict) and _PROPERTY_FAILED.search(str(exc)):
                fixed, more = self._link_refs(editor, params["componentProperties"], bare=True)
                if more:
                    params["componentProperties"], linked, retried = fixed, linked + more, True
            if retried:
                result = self._ask(editor, "manage_gameobject", params)
            elif not (params.get("componentsToAdd") and _COMPONENT_MISSING.search(str(exc))):
                raise
            else:
                result = None
        if result is None:
            # ★ 11-11 맥(판 5개 내리 멈춤): 손자리가 새 스크립트를 파일로 쓰면 유니티는 창이 앞으로 와야(포커스) 다시 읽는다.
            #   그래서 「그런 컴포넌트 없음」으로 실패했고, 대표에게 「유니티 창을 클릭해 주세요」를 다섯 번 부탁했다.
            #   원본 다리의 refresh_unity 로 창 없이 다시 읽혀 컴파일을 기다린 뒤 한 번만 다시 붙인다.
            self.refresh({"project": editor["project"]})
            editor = self._editor_for({"project": editor["project"]})
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
        out = {
            "action": "unity_editor_change", "op": op, "project": editor["project"], "result": _trim(result),
            "verified": True, "scene_saved": False,
            "note": "에디터 Undo 에 기록됐다. 씬은 아직 저장하지 않았다 — 저장은 op=save_scene 이나 사람이 Ctrl+S.",
        }
        if linked:
            out["linked"] = linked
        return out

    def _link_refs(self, editor: dict[str, Any], props: dict[str, Any], *, bare: bool) -> tuple[dict[str, Any], list[str]]:
        """참조 칸 값을 원본 다리가 읽는 꼴로 바꾼다. {"ref": 이름|경로} 는 늘, 맨 이름 글자는 `bare` 일 때만(장면에 정확히 있을 때).

        장면 오브젝트 → {"instanceID": n}(다리가 게임오브젝트에서 그 칸의 컴포넌트 · Transform 을 꺼낸다) · "Assets/…" → {"path": …}.
        돌려주는 두 번째 값은 바꾼 칸 이름들(「컴포넌트.칸 ← 이름」).
        """
        out: dict[str, Any] = {}
        linked: list[str] = []
        for component, fields in props.items():
            if not isinstance(fields, dict):
                out[component] = fields
                continue
            new_fields: dict[str, Any] = {}
            for field, value in fields.items():
                name = ""
                if isinstance(value, dict) and set(value) == {"ref"} and isinstance(value["ref"], str):
                    name = value["ref"].strip()
                    if not name:
                        raise ValueError(f"unity_ref_empty: {component}.{field} 의 ref 가 비었다")
                elif bare and isinstance(value, str) and value.strip() and not value.strip().startswith("Assets/"):
                    name = value.strip()
                if not name:
                    new_fields[field] = value
                    continue
                if name.startswith("Assets/"):
                    new_fields[field] = {"path": name}
                    linked.append(f"{component}.{field} ← {name}")
                    continue
                object_id = self._resolve_id(editor, name)
                if not object_id:
                    if isinstance(value, dict):
                        raise ValueError(f"unity_ref_missing: {component}.{field} 에 넣을 「{name}」을 장면에서 못 찾았다 — "
                                         "unity_editor_look hierarchy 로 정확한 이름을 보고 다시 줘라")
                    new_fields[field] = value
                    continue
                new_fields[field] = {"instanceID": object_id}
                linked.append(f"{component}.{field} ← {name}")
            out[component] = new_fields
        return out, linked

    # ── 파일 다시 읽기 (2026-11-11 맥: 「창을 클릭해 주세요」 다섯 번) ─────────────────────────────────────
    REFRESH_WAIT_SEC = 120

    def refresh(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """손자리가 쓴 스크립트 · 에셋을 유니티가 **창 없이** 다시 읽고 컴파일까지 끝내게 한다(원본 다리 `refresh_unity`).

        유니티는 바뀐 파일을 창이 앞으로 와야(포커스) 읽는다 — 뒤에 띄워 둔 에디터(`launch`)는 그래서 새 스크립트를 몰랐다.
        컴파일이 끝나면 유니티가 다리를 다시 띄우니(도메인 다시 불러오기) 이어질 때까지 기다린다.
        """
        editor = self._editor_for(arguments)
        project = Path(str(editor["project"]))
        started = self._monotonic()
        try:
            self.call(editor["port"], "refresh_unity", {"mode": "force", "scope": "all", "compile": "request",
                                                         "wait_for_ready": False}, timeout=60.0)
        except UnityBridgeError:
            pass  # 컴파일이 바로 시작되면 다리가 닫힐 수 있다 — 아래에서 다시 붙어 본다
        state: dict[str, Any] = {}
        while self._monotonic() - started < self.REFRESH_WAIT_SEC:
            self._sleep(2.0)
            row = self._alive_for(project)
            if row is None or row.get("reloading"):
                continue
            try:
                state = self._ask(row, "get_editor_state", {}) or {}
            except UnityBridgeError:
                continue
            if not any(_find_flag(state, key) for key in ("is_compiling", "is_updating", "is_domain_reload_pending")):
                break
        else:
            return {"action": "unity_editor_refresh", "project": str(project), "refreshed": True, "ready": False,
                    "waited_sec": round(self._monotonic() - started, 1),
                    "note": "다시 읽기는 걸었지만 컴파일이 아직 안 끝났다 — 잠시 뒤 unity_editor_status 로 보고, 콘솔 오류는 unity_editor_look console"}
        return {"action": "unity_editor_refresh", "project": str(project), "refreshed": True, "ready": True,
                "waited_sec": round(self._monotonic() - started, 1), "verified": True,
                "note": "다시 읽고 컴파일을 마쳤다 — 새 스크립트를 붙일 수 있다. 컴파일 오류는 unity_editor_look console 로 본다."}

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

    # ── 에디터 띄우기 (2026-11-11 대표: 「에디터가 안 열린다」만 세 판 · 띄우니 앞으로 튀어나옴) ──────────────────
    #
    # 맥 판 12개 중 4개가 「이어진 에디터 없음」에서 멈췄다. 손자리가 새 프로젝트를 만들며 다리 패키지를 빼먹었고, 설정의
    # 「에디터 잇기」 목록에는 그 프로젝트가 없었고, 모델에게는 에디터를 여는 도구가 없어 「사람에게 물어라」만 따랐다. 마지막
    # 판은 셸로 manifest 를 손으로 고치고 `open -a Unity` 를 두 번 불러(336초) 이었는데, `open -a` 는 앱을 맨 앞으로 끌어온다.
    # 이 도구 하나가 그 칸들을 한 번에 한다 — 다리 붙이기 · 기억하기 · 뒤에서 띄우기 · 이어질 때까지 기다리기.
    LAUNCH_WAIT_SEC = 150
    LAUNCH_POLL_SEC = 2.0

    def _alive_for(self, project: Path) -> dict[str, Any] | None:
        for row in self.live_editors():
            if row["alive"] and _norm(row["project"]) == _norm(project):
                return row
        return None

    def _wait_alive(self, project: Path, wait_sec: float) -> tuple[dict[str, Any] | None, float]:
        started = self._monotonic()
        while True:
            row = self._alive_for(project)
            waited = round(self._monotonic() - started, 1)
            if row is not None or waited >= wait_sec:
                return row, waited
            self._sleep(self.LAUNCH_POLL_SEC)

    def launch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from .unity_tools import editor_is_open, is_unity_project, project_version

        if self.unity is None:
            raise UnityBridgeError("unity_tools_missing: 유니티 도구가 없다")
        project = Path(self.unity._project(arguments, write=True)).resolve(strict=False)  # noqa: SLF001 — 허락 장부(쓰기)
        if not is_unity_project(project):
            raise ValueError(
                f"unity_project_invalid: {project} 는 유니티 프로젝트가 아니다(ProjectSettings/ProjectVersion.txt · Assets 가 있어야 한다)."
            )
        wait_sec = float(_clamp(arguments.get("wait_sec"), self.LAUNCH_WAIT_SEC, 10, 300))
        out: dict[str, Any] = {"action": "unity_editor_launch", "project": str(project), "launched": False,
                               "bridge_added": False}
        if self._alive_for(project) is not None:
            self.unity.remember_project(project)
            return {**out, "connected": True, "verified": True, "note": "이미 이어져 있다 — unity_editor_look 으로 읽어라."}
        state = self.install_state(project)
        if not state["installed"] or state["broken"]:
            installed = self.install(project)
            out["bridge_added"] = True
            out["manifest_backup"] = installed.get("backup", "")
        self.unity.remember_project(project)
        if editor_is_open(project):
            # 이미 떠 있는 에디터는 끄지 않는다 — 저장 안 한 씬이 날아간다. 다리가 막 붙었으면 유니티가 창을 한 번 받아야 읽는다.
            row, waited = self._wait_alive(project, min(wait_sec, 30.0))
            if row is not None:
                return {**out, "connected": True, "waited_sec": waited, "verified": True}
            return {**out, "connected": False, "waited_sec": waited, "editor_was_open": True, "note": (
                "유니티가 이 프로젝트를 이미 열고 있는데 아직 안 이어졌다"
                + ("(다리를 방금 붙였다 — 유니티는 창이 한 번 눌릴 때 새 패키지를 읽는다)" if out["bridge_added"] else "")
                + ". 사람에게 유니티 창을 한 번 눌러 달라고 하고 unity_editor_status 로 다시 봐라. 에디터를 끄고 다시 열지 마라.")}
        version = project_version(project)
        exe = self.unity.editor_for(version)  # 같은 판이 없으면 설치를 부탁하라는 글로 멈춘다(다른 판으로 열면 업그레이드된다)
        if self._keep_front is not None:
            self._keep_front()  # 띄우기 **전에** 지금 맨 앞 앱을 잡아 둔다
        self._spawn(Path(exe), project)
        out["launched"] = True
        out["editor_version"] = version
        row, waited = self._wait_alive(project, wait_sec)
        out["waited_sec"] = waited
        if row is not None:
            return {**out, "connected": True, "verified": True,
                    "note": "에디터를 뒤에서 띄웠고 이어졌다 — unity_editor_look 으로 계층 · 콘솔을 읽어라."}
        return {**out, "connected": False, "note": (
            f"에디터를 띄웠지만 {waited:.0f}초 안에 안 이어졌다(첫 가져오기 · 컴파일이 길 수 있다). 다시 띄우지 말고 "
            "잠시 뒤 unity_editor_status 로 봐라. 계속 안 되면 다리가 콘솔 오류로 못 떴을 수 있으니 사람에게 유니티 창을 봐 달라고 해라.")}

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
                    "selection(사람이 고른 것) · find(이름으로 찾기) · components(한 오브젝트의 컴포넌트와 값) · "
                    "screenshot(게임 · 씬 화면을 찍어 직접 보고 question 에 답한다 — 만든 것이 잘 보이는지 눈으로 확인할 때)."
                ),
                "parameters": {"type": "object", "properties": {
                    "what": {"type": "string", "enum": list(self._LOOK)},
                    "target": {"type": "string", "description": "components·hierarchy 의 기준 오브젝트(instanceID 또는 이름)"},
                    "search": {"type": "string", "description": "find 에서 찾을 이름"},
                    "question": {"type": "string", "description": "screenshot 에서 그림을 보고 답할 질문(예: 포탑이 길 위에 보이나)"},
                    "source": {"type": "string", "enum": ["game_view", "scene_view"], "description": "screenshot: 게임 화면(기본) · 씬 화면"},
                    "limit": {"type": "integer"}, "project": project,
                }, "required": ["what"]},
            }},
            {"type": "function", "function": {
                "name": "unity_editor_change",
                "description": (
                    "열린 유니티 에디터에서 게임오브젝트를 만들고·바꾸고·지우고·복제한다(op). 승인 없이 바로 하고, "
                    "바꾼 것은 에디터 Undo 에 남는다(unity_editor_undo). 씬은 저장하지 않는다 — 저장은 op=save_scene "
                    "(이름 없는 새 씬이면 name 을 준다)."
                ),
                "parameters": {"type": "object", "properties": {
                    "op": {"type": "string", "enum": [*self._CHANGE_KEYS, "save_scene"]},
                    "target": {"type": "string", "description": "바꿀 오브젝트(이름·경로·instanceID)"},
                    "name": {"type": "string", "description": "create 에서 새 이름 · save_scene 에서 이름 없는 씬의 파일 이름(확장자 없이)"},
                    "new_name": {"type": "string"},
                    "scene_folder": {"type": "string", "description": "save_scene 에서 이름 없는 새 씬을 저장할 폴더(Assets 아래 · 기본 Scenes)"},
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
                    "properties": {"type": "object", "description": (
                        "{컴포넌트: {속성: 값}}. 다른 오브젝트 · 컴포넌트를 넣는 참조 칸은 {\"ref\": \"장면의 오브젝트 이름\"}, "
                        "에셋은 {\"ref\": \"Assets/…\"} — 이름 글자만 넣으면 에셋 경로로 읽혀 실패한다.")},
                    "project": project,
                }, "required": ["op"]},
            }},
            {"type": "function", "function": {
                "name": "unity_editor_launch",
                "description": (
                    "유니티 에디터로 이 프로젝트를 열고 손자리와 잇는다 — 다리 패키지가 없으면 붙이고(manifest 백업), 에디터를 "
                    "앞으로 끌어오지 않고 뒤에서 띄운 뒤 이어질 때까지 기다린다. unity_editor_status 가 connected=false 면 "
                    "사람에게 열어 달라고 하기 전에 이것을 부른다. 셸로 유니티를 띄우지 않는다."
                ),
                "parameters": {"type": "object", "properties": {
                    "project": project,
                    "wait_sec": {"type": "integer", "description": "이어질 때까지 기다릴 초(기본 150 · 10~300)"},
                }, "required": []},
            }},
            {"type": "function", "function": {
                "name": "unity_editor_refresh",
                "description": (
                    "손자리가 쓴 스크립트 · 에셋을 열린 유니티 에디터가 창을 누르지 않아도 다시 읽고 컴파일까지 끝내게 한다. "
                    ".cs 파일을 쓰거나 고친 뒤, 붙이기 전에 부른다. 사람에게 「유니티 창을 클릭해 주세요」라고 하기 전에 이것을 부른다."
                ),
                "parameters": {"type": "object", "properties": {"project": project}, "required": []},
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
            # ★ 11-11 대표 「승인카드도 열어줘」 — 맥 게임 판에서 바꿀 때마다 사람을 불렀다. Undo · unity_editor_undo 로 되돌린다.
            "unity_editor_change": (self.change, RiskLevel.L1),
            # 되돌리기는 우리 변경을 지우는 일이고, 사람의 작업이면 스스로 되살린다 — 승인 없이.
            "unity_editor_undo": (self.undo, RiskLevel.L1),
            # 우리가 붙이는 다리 한 줄(백업 남김) + 앱 띄우기 — 되돌릴 수 있고 이 PC 안의 일이다.
            "unity_editor_launch": (self.launch, RiskLevel.L1),
            # 파일을 다시 읽고 컴파일할 뿐 — 사람이 만든 것을 바꾸지 않는다.
            "unity_editor_refresh": (self.refresh, RiskLevel.L1),
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


def _spawn_editor(exe: Path, project: Path) -> None:
    """에디터를 앞으로 끌어오지 않고 띄운다.

    맥: `open -g`(뒤에서) `-n`(다른 프로젝트로 떠 있는 유니티가 있어도 새로) — `open -a` 만 쓰면 앱이 맨 앞으로 온다(11-11 맥).
    윈도우: 최소화 · 포커스 안 뺏음(SW_SHOWMINNOACTIVE)으로 청하고, 손자리 프로세스와 떼어 둔다(손자리를 다시 켜도 에디터는 산다).
    """
    if sys.platform == "darwin":
        app = exe
        while app.suffix != ".app" and app.parent != app:
            app = app.parent
        target = app if app.suffix == ".app" else exe
        subprocess.run(["open", "-g", "-n", "-a", str(target), "--args", "-projectPath", str(project)],
                       check=True, timeout=30, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return
    startup = None
    flags = 0
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
        startup.wShowWindow = 7  # SW_SHOWMINNOACTIVE
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(  # noqa: S603 — 실행 파일은 허브가 깐 자리에서 찾은 것이다(`installed_editors`)
        [str(exe), "-projectPath", str(project)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, startupinfo=startup, creationflags=flags,
    )


# ── 맥: 유니티가 스스로 앞으로 나오는 것 되돌리기 (2026-11-11 실측) ─────────────────────────────────────
#
# 맥 미니에서 0.5초마다 맨 앞 앱을 재 보니 `open -g`(뒤에서) 로 띄워도, `open -j`(숨겨서) 로 띄워도 유니티가 짐을 다 읽고 창을
# 펴는 순간 **스스로** 맨 앞으로 나왔다(18:59:17 · 19:00:26 두 번). 띄우는 방식으로는 못 막는다. 그래서 띄우기 직전의 맨 앞 앱을
# 기억해 두고, 60초 안에 유니티가 앞으로 나오면 그 앱을 다시 앞으로 돌린다(`open -b` — 다 켜진 유니티는 그 뒤 6초 동안 뒤에 있었다).
# 사람이 그 사이 유니티를 일부러 누를 수도 있으니 되돌리기는 3번까지만. `lsappinfo` · `open` 은 맥 권한 창을 띄우지 않는다
# (System Events 를 부르는 osascript 는 「손자리가 다른 앱을 제어하려 한다」 권한 창이 뜬다 — 쓰지 않는다).
UNITY_BUNDLE_ID = "com.unity3d.UnityEditor5.x"
FRONT_KEEP_SEC = 60.0
FRONT_KEEP_MAX_RESTORES = 3


def _front_bundle_id() -> str:
    try:
        asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True, timeout=3, check=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
        if not asn:
            return ""
        info = subprocess.run(["lsappinfo", "info", "-only", "bundleid", asn], capture_output=True, text=True, timeout=3,
                              check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    marker = 'bundleID="'
    start = info.find(marker)
    if start < 0:
        return ""
    end = info.find('"', start + len(marker))
    return info[start + len(marker):end] if end > start else ""


def _activate_bundle(bundle_id: str) -> None:
    try:
        subprocess.run(["open", "-b", bundle_id], capture_output=True, timeout=5, check=False,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass


def keep_front_away_from_unity(
    *,
    front: Callable[[], str] = _front_bundle_id,
    activate: Callable[[str], None] = _activate_bundle,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    seconds: float = FRONT_KEEP_SEC,
    max_restores: int = FRONT_KEEP_MAX_RESTORES,
    initial: str | None = None,
) -> int:
    """유니티가 앞으로 나오면 **마지막으로 앞에 있던 다른 앱**으로 돌려놓는다. 돌려놓은 횟수를 돌려준다."""
    last_other = initial if initial is not None else front()
    if last_other == UNITY_BUNDLE_ID:
        last_other = ""
    restores = 0
    deadline = clock() + seconds
    while clock() < deadline and restores < max_restores:
        sleep(0.5)
        current = front()
        if not current:
            continue
        if current != UNITY_BUNDLE_ID:
            last_other = current  # 사람이 다른 앱으로 옮겨 가면 그 앱이 돌아갈 자리다
            continue
        if last_other:
            activate(last_other)
            restores += 1
    return restores


def _start_front_keeper() -> None:
    first = _front_bundle_id()  # 띄우기 전의 맨 앞 앱 — 이 줄은 띄우기 전에 돈다
    threading.Thread(target=keep_front_away_from_unity, kwargs={"initial": first},
                     name="unity-front-keeper", daemon=True).start()


#: 붙이려던 컴포넌트를 유니티가 아직 모른다(새 스크립트를 안 읽음)는 원본 다리의 말.
_COMPONENT_MISSING = __import__("re").compile(r"(not\s+found|could\s+not\s+(?:find|load)|unknown\s+(?:component|type)|no\s+type)", __import__("re").I)


#: 원본 다리가 속성 넣기에 실패했을 때의 말.
_PROPERTY_FAILED = __import__("re").compile(r"property operations failed", __import__("re").I)


def _find_flag(value: Any, key: str, depth: int = 0) -> bool:
    """에디터 상태(겹친 dict)에서 그 이름의 참/거짓 칸을 찾는다 — 원본이 판마다 칸을 옮겨서 위치를 박지 않는다."""
    if depth > 4:
        return False
    if isinstance(value, dict):
        if value.get(key) is True:
            return True
        return any(_find_flag(item, key, depth + 1) for item in value.values() if isinstance(item, (dict, list)))
    if isinstance(value, list):
        return any(_find_flag(item, key, depth + 1) for item in value)
    return False


def _scene_name(raw: str) -> str:
    """씬 파일 이름 — 글자 · 숫자 · 밑줄 · 붙임표 · 빈칸만. 경로나 확장자를 끼워 넣지 못한다."""
    import re

    name = raw.strip().removesuffix(".unity")
    if not name or not re.fullmatch(r"[\w\- ]{1,64}", name):
        raise ValueError(f"unity_scene_name: 씬 이름은 글자 · 숫자 · _ · - 만(64자까지): {raw!r}")
    return name


def _scene_folder(raw: str) -> str:
    """씬을 둘 폴더 — Assets 아래만. 「..」 · 절대 경로 · 다른 드라이브는 거절한다."""
    folder = raw.replace("\\", "/").strip().strip("/")
    if folder.lower().startswith("assets/"):
        folder = folder[len("assets/"):]
    elif folder.lower() == "assets":
        folder = ""
    parts = [part for part in folder.split("/") if part]
    if ":" in folder or any(part in (".", "..") for part in parts):
        raise ValueError(f"unity_scene_path: 씬 폴더는 Assets 아래 상대 경로만: {raw!r}")
    return "/".join(parts) or "Scenes"


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
