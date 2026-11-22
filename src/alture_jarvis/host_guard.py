"""**요청의 주소 이름(Host)으로 한 번 더 거른다** — DNS 리바인딩 막기 (2026-11-13).

## 왜 생겼나

r/Python 댓글(AleDev99)이 짚었다: 「127.0.0.1 에서만 받는다」는 브라우저 앞에서는 벽이 아니다. 이 PC 에서 열린
아무 웹 페이지(evil.example)나 자기 이름의 DNS 답을 127.0.0.1 로 바꿔 치우면(리바인딩), 브라우저는 그 페이지를
**같은 출처**로 여기고 우리 백엔드에 요청을 보내 **답까지 읽는다**. 코드를 다시 보니 Host 검사는 0곳이었다.

- 열쇠가 필요한 길은 이미 안전하다 — 열쇠는 쿠키가 아니라 머리글(`X-JARVIS-TOKEN` · api.py `require_token`)이고
  그 페이지는 열쇠 값을 모른다.
- 열쇠 없이 열리는 길(/ · /health · 공개 글꼴 · 짝짓기 · 정제한 일 답 · 도구 목록)은 읽혔다.

## 어떻게 가르나

리바인딩은 **공격자가 DNS 를 쥔 이름**이 있어야 된다. 그래서 그런 이름일 수 없는 것만 받는다.

- IP 글자 그대로(127.0.0.1 · 192.168.x · 100.x · [::1]) — 이름이 아니라 리바인딩이 안 된다
- 점 없는 한 낱말(내 PC 이름 · 테일스케일 짧은 이름 · TestClient 의 `testserver`) — 공개 DNS 에 살 수 없다
- `localhost` 와 `*.localhost` — 브라우저가 스스로 이 PC 로 묶는다
- 집 · 사내 전용 끝말(`.local` 맥 봉쥬르 · `.lan` · `.home` · `.internal` · `.localdomain` · `.home.arpa`) — 공개 등록이 안 된다
- `*.ts.net` — 테일스케일이 DNS 를 쥔다(맥 · 폰이 테일넷 이름으로 부른다)
- 더 필요하면 `JARVIS_ALLOWED_HOSTS`(쉼표로) — 이름 그대로 또는 `.끝말`

Host 머리글이 아예 없으면 받는다 — 브라우저는 늘 붙이므로 리바인딩 길이 아니고, 옛 도구가 빼먹을 수 있다.

★ 인증이 아니다. 인증은 열쇠가 한다. 이건 **브라우저가 남의 이름으로 들어오는 길**만 닫는다(peer_guard 와 같은 결).
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from typing import Any, Callable, Iterable

PRIVATE_SUFFIXES = (".localhost", ".local", ".lan", ".home", ".internal", ".localdomain", ".home.arpa", ".ts.net")
ENV_EXTRA = "JARVIS_ALLOWED_HOSTS"
_NAME = re.compile(r"^[a-z0-9_.-]+$")


def host_name(header: str) -> str:
    """`이름:포트` · `[v6]:포트` 에서 이름만 · 소문자 · 끝 점 뗌."""
    value = str(header or "").strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else ""   # 닫는 ] 가 없으면 이름이 아니다
    if value.count(":") == 1:
        value = value.split(":", 1)[0]
    return value.rstrip(".")


def extra_from_env() -> tuple[str, ...]:
    return tuple(part.strip().lower().rstrip(".") for part in os.environ.get(ENV_EXTRA, "").split(",") if part.strip())


def host_ok(header: str, extra: Iterable[str] = ()) -> bool:
    """이 Host 로 온 요청을 받아도 되나 — 공격자가 DNS 를 쥘 수 없는 이름만."""
    if not str(header or "").strip():
        return True
    name = host_name(header)
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    if not _NAME.match(name):
        return False   # 이름에 쓸 수 없는 글자 — 받지 않는다
    if "." not in name:
        return True
    for item in extra:
        if name == item or (item.startswith(".") and name.endswith(item)):
            return True
    return name.endswith(PRIVATE_SUFFIXES)


class HostGuard:
    """HTTP 와 웹소켓 둘 다 거른다 — `@app.middleware("http")` 는 소켓을 비켜 간다(api.py /v1/ws 주석과 같은 함정)."""

    def __init__(self, app: Callable[..., Any], extra: Iterable[str] | None = None) -> None:
        self.app = app
        self.extra = tuple(extra) if extra is not None else extra_from_env()

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        kind = scope.get("type")
        if kind in ("http", "websocket"):
            header = ""
            for key, value in scope.get("headers") or []:
                if key == b"host":
                    header = value.decode("latin-1")
                    break
            if not host_ok(header, self.extra):
                if kind == "websocket":
                    await receive()   # websocket.connect 를 받은 뒤 닫아야 서버가 403 으로 돌려준다
                    await send({"type": "websocket.close", "code": 4403})
                    return
                body = json.dumps({"detail": "host_not_allowed"}).encode()
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
