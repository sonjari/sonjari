"""짝짓기 전용 문 — 집 PC 가 같은 와이파이 · 테일넷에 내놓는 **유일한** 문 (2026-11-04 대표 「그렇게 가자」).

왜 따로 두나(11-04 보안 점검 · 테일스케일 §6 실측):
- 본 백엔드(8091)는 손님 PC 기본값이 127.0.0.1 이다(`scripts/task_entry.py`). 그대로면 맥이 같은 와이파이에서 집 PC 를
  찾지도 짝을 청하지도 못한다 — 우리 PC 는 `.env` 의 JARVIS_HOST=0.0.0.0 덕에 됐을 뿐이다.
- `tailscale serve` 로 들어온 요청을 백엔드는 127.0.0.1(이 PC 안)로 본다 — 8091 에 serve 를 걸면 테일넷의 모든 기기가
  「이 PC 안」 대우를 받아 「이 PC 에서만」 잠금들이 뚫린다(실측: /v1/home-llm 이 403 대신 409).

그래서: 본 백엔드는 127.0.0.1 에 그대로 두고, 같은 백엔드 앱을 **짝짓기 세 길과 /v1/llm/ 만** 통과시키는 얇은 층으로
감싸 8092 에 따로 연다. 이 문으로 온 요청은 출처(127.0.0.1 이든 같은 와이파이든)와 상관없이 그 길들 밖으로 못 간다.
테일스케일은 serve 를 이 문(8092)에 건다. 모델 빌리기는 기기 열쇠(X-Sonjari-Device)가, 짝짓기는 집 PC 화면의 숫자가 지킨다.
"""

from __future__ import annotations

import json
import sys
import threading
from typing import Any, Callable

DOOR_PORT = 8092
# 문지기(peer_guard)가 같은 와이파이에 여는 길과 **같은 목록**을 쓴다 — 두 벌이면 한쪽만 고쳐진다(사고 Q · 11-04 /v1/pair/outside).
from .peer_guard import PAIRING_PATHS as DOOR_PATHS  # noqa: E402
from .peer_guard import PAIRING_PREFIXES as DOOR_PREFIXES  # noqa: E402


def allowed(path: str) -> bool:
    """이 문으로 지나갈 수 있는 길인가."""
    path = str(path or "")
    return path in DOOR_PATHS or path.startswith(DOOR_PREFIXES)


def door_app(main_app: Callable[..., Any]) -> Callable[..., Any]:
    """본 앱(ASGI)을 감싼 짝짓기 문. 허락한 길만 본 앱에 넘기고 나머지는 404 · 웹소켓은 닫는다."""

    async def app(scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        kind = scope.get("type")
        if kind == "lifespan":
            # 본 앱의 수명(런타임 켜고 끄기)은 본 서버가 맡는다 — 이 문은 받기만 하고 아무것도 켜지 않는다.
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 4404})
            return
        if kind != "http" or not allowed(scope.get("path", "")):
            body = json.dumps({"detail": "not_on_pair_door"}).encode()
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await main_app({**scope, "sonjari_door": True}, receive, send)

    return app


def should_open(config: Any) -> bool:
    """이 손자리가 짝짓기 문을 여는가 — 윈도우 집 PC 만. 맥은 빌리는 쪽이고, 맥에서 열면 「들어오는 연결 허용」 창이 뜬다."""
    if sys.platform != "win32":
        return False
    return str(getattr(config, "pair_door", "1")).strip().lower() not in {"0", "false", "off", "no"}


class PairDoor:
    """짝짓기 문 서버 — 따로 된 스레드에서 돈다(메인 서버의 신호 처리 · 이벤트 고리를 건드리지 않는다)."""

    def __init__(self, main_app: Callable[..., Any], *, host: str = "0.0.0.0", port: int = DOOR_PORT) -> None:
        import uvicorn

        self.host, self.port = host, port
        self._server = uvicorn.Server(uvicorn.Config(door_app(main_app), host=host, port=port, lifespan="off",
                                                     log_level="warning", access_log=False))
        self._thread: threading.Thread | None = None
        self.error = ""

    def start(self) -> None:
        def run() -> None:
            try:
                self._server.run()
            except BaseException as exc:  # noqa: BLE001 — 문이 못 열려도 본 백엔드는 산다(짝짓기만 안 된다)
                self.error = f"{type(exc).__name__}: {exc}"

        self._thread = threading.Thread(target=run, name="sonjari-pair-door", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.should_exit = True

    @property
    def started(self) -> bool:
        return bool(getattr(self._server, "started", False))
