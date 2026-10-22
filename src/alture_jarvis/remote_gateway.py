"""원격 입구 — 노트북의 클로드 코드가 테일스케일로 집 PC 손자리를 부르는 문 (2026-10-21 대표 · 원격 첫 판).

설계: `docs/설계_원격연결_첫판_2026-10-21.ko.md` (ADR-원격-1).

## 무엇을 하나
- 지금의 손자리 MCP 다리(`mcp_server.build_server(JarvisMcpBridge)`)를 **그대로** streamable HTTP(`/mcp`)로 연다.
  도구 · 거르개 · 영수증 · 서기 문이 stdio 와 같은 코드를 탄다(두 벌로 갈라지면 한쪽만 고쳐진다 — 사고 Q).
- `GET /story?session=…` — 노트북의 압축 훅이 서기 카드를 가져가는 자리.
- `GET /health` — 열쇠 없이 「살아 있다」만. 다른 정보는 안 준다.

## 지키는 선
- **이 PC 의 127.0.0.1 에만 묶는다.** 테일넷에는 `tailscale serve 8093` 으로만 내보낸다(공개 인터넷 Funnel 은 쓰지 않는다).
- **원격 전용 열쇠**(`data/remote.token`) — 제어 열쇠(백엔드 전체를 여는 열쇠)는 이 PC 밖으로 나가지 않는다.
  `Authorization: Bearer <원격 열쇠>` 가 없거나 틀리면 401. 비교는 상수 시간.
- 원격 판에는 `via: "remote"` 가 붙고, 첫 판에서는 코드 일(repo · check)을 받지 않는다(`JarvisMcpBridge(via="remote")`).
- 기본은 꺼짐 — 사람이 이 프로그램을 켜야만 열린다(설정 스위치 · 예약 작업은 다음 단계).

## 켜는 법(개발자 첫 판)
    python -m alture_jarvis.remote_gateway          # 열쇠가 없으면 만들고, 붙여 넣을 명령을 보여 준다
    tailscale serve 8093                            # 다른 창에서 — 테일넷 안에만
    python -m alture_jarvis.remote_gateway --rotate # 열쇠 바꾸기(옛 열쇠 즉시 무효)
"""

from __future__ import annotations

import argparse
import contextlib
import hmac
import secrets
import sys
from pathlib import Path
from typing import Any

#: 원격 입구가 이 PC 에서 듣는 자리 — 백엔드(8091) · 음성(7788)과 겹치지 않게.
DEFAULT_PORT = 8093
TOKEN_FILE = "remote.token"


def token_path(data_dir: Path) -> Path:
    return Path(data_dir) / TOKEN_FILE


def ensure_token(data_dir: Path, *, rotate: bool = False) -> str:
    """원격 열쇠를 읽거나 만든다. `rotate` 면 새로 만들어 덮는다 — 옛 열쇠는 바로 401."""
    path = token_path(data_dir)
    if not rotate:
        try:
            existing = path.read_text(encoding="utf-8").strip()
        except OSError:
            existing = ""
        if existing:
            return existing
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(token, encoding="utf-8")
    temp.replace(path)
    return token


def _bearer(headers: Any) -> str:
    value = str(headers.get("authorization") or "")
    return value[7:].strip() if value[:7].lower() == "bearer " else ""


def token_ok(given: str, expected: str) -> bool:
    return bool(given) and bool(expected) and hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def build_app(bridge: Any, *, remote_token: str | Any, story: Any = None) -> Any:
    """원격 입구 ASGI 앱. `remote_token` 은 열쇠 글이나, 부를 때마다 열쇠를 돌려주는 함수(바꾸기를 재시작 없이 반영).
    `story(session, limit)` 는 서기 카드를 돌려주는 비동기 함수(없으면 /story 는 404)."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    from .mcp_server import build_server

    def expected() -> str:
        return str(remote_token() if callable(remote_token) else remote_token or "")

    manager = StreamableHTTPSessionManager(app=build_server(bridge), session_idle_timeout=1800)

    async def health(request: Any) -> Any:
        del request
        return JSONResponse({"ok": True})

    async def story_route(request: Any) -> Any:
        if story is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        session = str(request.query_params.get("session") or "")[:80]
        try:
            limit = max(1, min(int(request.query_params.get("limit") or 40), 120))
        except ValueError:
            limit = 40
        return JSONResponse(await story(session, limit))

    class Guard:
        """열쇠 문지기 — /health 만 열쇠 없이. 나머지(/mcp · /story)는 원격 열쇠."""

        def __init__(self, app: Any) -> None:
            self.app = app

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            if scope.get("type") == "http" and scope.get("path") != "/health":
                headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers") or []}
                if not token_ok(_bearer(headers), expected()):
                    response = JSONResponse({"error": "unauthorized"}, status_code=401,
                                            headers={"WWW-Authenticate": "Bearer"})
                    await response(scope, receive, send)
                    return
            await self.app(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(app: Any):
        del app
        async with manager.run():
            yield

    # /mcp 는 Mount 가 아니라 Route 로 — Mount 는 「/mcp」를 「/mcp/」로 돌려보내(307) POST 가 다리에서 깨질 수 있다.
    app = Starlette(routes=[Route("/health", health), Route("/story", story_route),
                            Route("/mcp", manager.asgi_app, methods=["GET", "POST", "DELETE"])],
                    lifespan=lifespan)
    return Guard(app)


#: 원격으로는 내보내지 않는 도구 머리 — 집 PC 의 유니티 프로젝트를 바꾸는 게임 팩 도구(스크립트 시험 · 레시피 실행).
#: 10-21 첫 실행에서 목록에 7개가 같이 나왔다. 원격 첫 판은 맡기기 넷(task · status · guide · story)만.
REMOTE_EXCLUDE_PREFIXES = ("unity_",)


def remote_filter(env: dict[str, str] | None = None) -> Any:
    """원격 입구의 도구 거르개 — 이 PC 연결의 거르개에 원격 전용 제외를 더한다(목록과 부르기 둘 다 막힌다)."""
    from .mcp_server import ToolFilter

    base = ToolFilter.from_env(env)
    base.exclude_prefixes = tuple(base.exclude_prefixes) + tuple(p for p in REMOTE_EXCLUDE_PREFIXES if p not in base.exclude_prefixes)
    return base


def _story_fetcher(base_url: str, control_token: str) -> Any:
    async def fetch(session: str, limit: int) -> dict[str, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url.rstrip('/')}/v1/scribe/story", params={"session": session, "limit": limit},
                                        headers={"X-JARVIS-TOKEN": control_token})
        data = response.json() if response.status_code == 200 else {}
        # 노트북에 보낼 것만 — 카드 글과 개수. 서기가 읽는 폴더 경로(사람 이름이 든 집 경로)는 빼고 보낸다.
        return {"enabled": bool(data.get("enabled")), "count": int(data.get("count") or 0), "card": str(data.get("card") or "")}

    return fetch


def connect_command(token: str, host: str = "<집PC이름>.<테일넷>.ts.net", scheme: str = "https") -> str:
    """노트북의 클로드 코드에 붙여 넣을 한 줄(code.claude.com/docs/en/mcp 의 HTTP 추가 형식)."""
    return f'claude mcp add --transport http sonjari {scheme}://{host}/mcp --header "Authorization: Bearer {token}"'


def bind_host_ok(host: str) -> bool:
    """입구를 묶어도 되는 자리 — 이 PC 안(127.0.0.1) 또는 테일스케일 주소대(100.64.0.0/10)만.

    ★ 10-21: 테일넷에 serve 가 꺼져 있었다(켜려면 계정 관리 화면에서 승인). 그래서 대안으로 이 PC 의 테일스케일 주소에 직접 묶는다.
      0.0.0.0 이나 집 공유기 주소(192.168.x)에 묶으면 같은 와이파이의 아무나 닿는다 — 그 길은 열지 않는다.
    """
    import ipaddress

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address in ipaddress.ip_network("100.64.0.0/10")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="손자리 원격 입구(테일스케일 · 클로드 코드)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1",
                        help="묶을 자리 — 127.0.0.1(기본 · tailscale serve 로 내보냄) 또는 이 PC 의 테일스케일 주소(100.x)만")
    parser.add_argument("--rotate", action="store_true", help="원격 열쇠를 새로 만든다(옛 열쇠 즉시 무효)")
    args = parser.parse_args(argv)
    if not bind_host_ok(args.host):
        parser.error(f"--host {args.host} 는 열 수 없습니다 — 127.0.0.1 이나 테일스케일 주소(100.64.0.0/10)만 됩니다.")

    import uvicorn

    from . import config as config_module
    from .config import JarvisConfig, setting
    from .mcp_language import pick_language
    from .mcp_server import JarvisMcpBridge, resolve_token

    # 백엔드(`scripts/task_entry.py`)와 **같은 순서로** 설정을 싣는다 — 안 그러면 다른 데이터 폴더를 보고 열쇠를 엉뚱한 데 만든다
    # (10-21 첫 실행: `%LOCALAPPDATA%\AltureJarvis\data` 에 만들었다). 개발 런타임(그 폴더에 data 가 있는 곳)일 때만.
    # 스토어판은 코드 폴더에 data 가 없으니 건드리지 않고 기본 자리(앱 데이터)를 쓴다 — 백엔드와 같은 자리다.
    project_root = Path(__file__).resolve().parents[2]
    if (project_root / "data").is_dir():
        config_module.absorb_environment()
        config_module.keep_private("JARVIS_RUNTIME_ROOT", str(project_root), override=True)
        try:
            config_module.load_env_file(project_root / ".env")
        except Exception:  # noqa: BLE001 — .env 를 못 읽어도 기본값으로 뜬다(백엔드와 같다)
            pass
    config = JarvisConfig.from_env()
    data_dir = Path(config.data_dir)
    token = ensure_token(data_dir, rotate=args.rotate)
    # 백엔드는 같은 PC — 설정의 자리를 쓴다(환경은 `config.setting` 으로만 읽는다 · 10-09 규칙).
    base_url = setting("JARVIS_BASE_URL") or f"http://127.0.0.1:{int(config.port)}"
    control = resolve_token() or str(getattr(config, "control_token", "") or "")
    bridge = JarvisMcpBridge(base_url=base_url, token=control, tool_filter=remote_filter(),
                             lang=pick_language(base_url, control), via="remote")
    if args.host == "127.0.0.1":
        print("손자리 원격 입구 — 127.0.0.1:%d (테일넷에는 `tailscale serve --bg %d` 로만)" % (args.port, args.port), file=sys.stderr)
        line = connect_command(token)
    else:
        print("손자리 원격 입구 — 테일스케일 주소 %s:%d 에만" % (args.host, args.port), file=sys.stderr)
        line = connect_command(token, f"{args.host}:{args.port}", scheme="http")
    print("노트북 클로드 코드에 붙여 넣을 명령:\n  " + line, file=sys.stderr)
    app = build_app(bridge, remote_token=lambda: ensure_token(data_dir), story=_story_fetcher(base_url, control))
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
