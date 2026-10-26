"""본체 안에서 도는 디스코드 다리 + 화면이 부르는 연결 단계 (2026-10-18).

## 왜

스토어(MSIX)로 깐 사용자는 명령 창을 못 쓴다 — `python -m alture_jarvis.messaging setup` 마법사도, 따로 띄우는 다리도 못 돌린다.
그래서 본체가 다리를 자기 안에서 돌리고(따로 도는 스레드 + 제 asyncio 루프), 화면이 부를 HTTP 문(`api.py` 의
`/v1/discord/*`)이 마법사의 단계를 하나씩 맡는다:

    토큰 넣기(클립보드) → Intent 다시 확인 → 서버에 들이기 → 마무리(홈 채널 · 다리 켜기 · 환영 DM) → (끊기)

## 지키는 것

- **토큰은 본체만 본다.** 화면은 「클립보드에서 가져오기」만 누르고, 본체가 윈도우 클립보드를 직접 읽는다. 화면 · 모델 ·
  대화 기록 · 응답 · 기록 파일 어디에도 토큰 값을 싣지 않는다(`REDACTOR`). 저장은 자격 증명 관리자에만(`credentials.py`).
  확인이 끝나면 클립보드가 **아직 그 토큰일 때만** 비운다 — 그 사이 사람이 다른 것을 복사했으면 건드리지 않는다.
- **다리는 하나만.** 따로 띄운 다리(`python -m alture_jarvis.messaging`)와 같은 잠금 파일(`_SingleInstance`)을 쓴다.
  따로 띄운 것이 이미 쥐고 있으면 본체는 띄우지 않고 status 에 `owner_process="other"` 를 낸다.
- **실패해도 본체는 뜬다.** 다리 쪽 예외는 삼키고 `last_error` · 기록에 남긴다.
- 본체 → 다리의 일 맡기기는 지금처럼 127.0.0.1 로 자기 자신을 부른다(`bridge.SonjariBackend`). 연결 토큰은 본체 설정에서
  넘겨받는다 — `resolve_backend` 를 거치지 않는다.

★ `discord` 는 다리 스레드 안에서만 부른다. discord.py 가 없는 곳에서도 이 모듈은 import 된다(`installed=False`).
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import logging.handlers
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from . import credentials
from .access_requests import AccessRequestBook, clean_user_id
from .base import REDACTOR, RedactingFilter, detect_lang, say
from .discord_config import SETTINGS_FILE, DiscordSettings
from .onboarding import (
    API_BASE, PORTAL, BotCheck, DiscordAPIError, check_bot_token, invite_url, token_shape_error,
)

log = logging.getLogger("sonjari.messaging")

#: 따로 띄운 다리(`__main__.LOCK_FILE`)와 **같은 파일** — 둘 중 하나만 돈다.
LOCK_FILE = "discord_bridge.lock"
#: 본체 안 다리의 기록. 따로 띄운 다리의 `discord_bridge.log` 와 나눈다 — 잠금에 진 쪽도 기록 처리기는 먼저 연다(`__main__.main`).
LOG_FILE = "discord_service.log"
GUILD_TEXT = 0
GUILD_CATEGORY = 4
#: 다리를 켠 뒤 디스코드에 붙을 때까지 마무리 문이 기다리는 시간.
READY_WAIT_SEC = 15.0
#: 접속이 (토큰 · Intent 말고 다른 까닭으로) 떨어지면 이만큼 쉬었다가 다시 붙는다 — 부팅 직후 인터넷이 아직 없을 때.
RETRY_DELAYS = (10.0, 30.0, 60.0, 120.0, 300.0)

#: 화면에 나가는 문장. 한국어로 만들고 영어 화면은 나가는 순간 사전(`ui_i18n_en.json`)이 바꾼다.
MESSAGES: dict[str, str] = {
    "clipboard_empty": "클립보드가 비었습니다 — 포털의 「Bot」 페이지에서 「Reset Token」을 누르고 「Copy」로 토큰을 복사한 뒤 다시 눌러 주세요.",
    "clipboard_unavailable": "클립보드를 읽지 못했습니다 — 잠시 뒤 다시 눌러 주세요.",
    "application_id": "복사하신 것은 숫자만 있습니다 — Application ID 를 복사하셨습니다. 토큰은 포털의 「Bot」 페이지에서 「Reset Token」을 눌러 나온 긴 글자입니다.",
    "has_spaces": "복사한 글에 빈칸이나 줄바꿈이 섞여 있습니다 — 「Bot」 페이지에서 토큰만 다시 복사해 주세요.",
    "not_a_token": "복사하신 것은 봇 토큰 모양이 아닙니다(점 두 개로 나뉜 긴 글자여야 합니다) — 「Bot」 페이지에서 토큰을 복사해 주세요.",
    "token_rejected": "디스코드가 이 토큰을 거절했습니다 — 「Bot」 페이지에서 「Reset Token」으로 새 토큰을 받아 복사한 뒤 다시 눌러 주세요.",
    "forbidden": "디스코드가 이 요청을 허락하지 않았습니다(권한 없음).",
    "rate_limited": "디스코드가 잠시 요청을 막았습니다 — {0}초 뒤에 다시 눌러 주세요.",
    "discord_error": "디스코드가 {0} 로 답했습니다 — 잠시 뒤 다시 해 주세요.",
    "unreachable": "디스코드에 연결하지 못했습니다 — 인터넷 연결을 확인해 주세요.",
    "store_failed": "토큰을 윈도우 자격 증명 관리자에 저장하지 못했습니다. 아무것도 저장하지 않았습니다.",
    "store_unreadable": "윈도우 자격 증명 관리자에서 봇 토큰을 읽지 못했습니다.",
    "no_token": "저장된 봇 토큰이 없습니다 — 먼저 토큰을 넣어 주세요.",
    "not_installed": "이 손자리에는 디스코드 부품(discord.py)이 들어 있지 않습니다.",
    "intent_off": "Message Content Intent 가 꺼져 있습니다 — 포털의 「Bot」 페이지에서 켜고 「Save Changes」를 누른 뒤 「다시 확인」을 눌러 주세요.",
    "not_in_server": "봇이 아직 어느 서버에도 없습니다 — 초대 링크로 내 서버에 들인 뒤 다시 눌러 주세요.",
    "other_process": "따로 띄운 디스코드 다리가 이미 돌고 있습니다 — 그 창(또는 작업 스케줄러)을 끄면 손자리가 다리를 맡습니다.",
    "disabled": "디스코드 다리가 설정에서 꺼져 있습니다.",
    "no_control_token": "손자리 연결 토큰을 찾지 못해 다리를 켜지 못했습니다.",
    "login_failed": "봇 토큰이 맞지 않습니다 — 디스코드 연결에서 토큰을 다시 넣어 주세요.",
    "bridge_failed": "디스코드 다리가 멈췄습니다: {0}",
    "dm_forbidden": "주인에게 환영 DM 을 보내지 못했습니다 — 디스코드 설정의 「서버 멤버가 보내는 다이렉트 메시지 허용」이 꺼져 있을 수 있습니다.",
    "dm_failed": "주인에게 환영 DM 을 보내지 못했습니다.",
    "no_owner": "허용 목록에 앱 주인이 없어 환영 DM 을 보내지 않았습니다.",
    "connected": "디스코드 연결을 마쳤습니다.",
    "saved": "토큰을 확인하고 저장했습니다.",
    "disconnected": "디스코드 연결을 끊고 저장된 토큰을 지웠습니다.",
    "unknown_model_alias": "그런 모델 별명이 없습니다 — 모델 별명 표에 있는 이름을 골라 주세요.",
    "user_install_maybe": "봇이 어느 서버에도 없습니다 — 사용자 설치로 쓰시는 중이면 그대로 마무리하셔도 됩니다.",
    "no_such_request": "그 허용 요청을 찾지 못했습니다 — 목록을 새로 불러와 주세요.",
    "invalid_user_id": "디스코드 사용자 ID 가 올바르지 않습니다.",
    "allowed_person": "허용했습니다 — 이제 그 사람의 말도 받습니다.",
    "allowed_dm_failed": "허용했지만 그 사람에게 알리는 DM 은 보내지 못했습니다.",
    "ignored_person": "무시했습니다 — 그 사람이 다시 말해도 카드를 띄우지 않습니다.",
}

#: 환영 DM — 화면 언어(`ui_i18n.lang()`)로 하나만 보낸다. `{home}` 은 홈 채널 문장(없으면 빈칸).
WELCOME = {
    "ko": ("연결됐습니다. 여기로 하실 일을 보내 주세요 — 예: 네이버에서 오늘 서울 날씨 찾아 줘.{home} "
           "되돌릴 수 없는 일(메일 보내기 등)은 PC 화면에서 승인합니다."),
    "en": ("Connected. Send me what you'd like done here — for example: find today's weather in Seoul on Naver.{home} "
           "Anything that can't be undone (like sending an email) is approved on the PC screen."),
}
WELCOME_HOME = {
    "ko": " <#{channel}> 에서는 @멘션 없이도 받습니다.",
    "en": " In <#{channel}> I also take messages without an @mention.",
}


def _msg(code: str, *values: Any) -> str:
    template = MESSAGES.get(code, code)
    return template.format(*values) if values else template


class DiscordStepError(Exception):
    """화면에 돌려줄 실패 — `code` 는 화면이 갈래를 고르는 열쇠, `message` 는 사람 말(토큰 없음)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.message = REDACTOR.redact(message or _msg(code))


# ── 디스코드 REST ───────────────────────────────────────────────────────────────

HttpCall = Callable[[str, str, dict[str, str], Optional[dict[str, Any]]], tuple[int, Any]]


def _http_call(method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None) -> tuple[int, Any]:
    import httpx

    try:
        response = httpx.request(method, url, headers=headers, json=body, timeout=10)
    except httpx.RequestError as exc:
        raise OSError(type(exc).__name__) from exc   # 예외 문구에 요청 머리(토큰)가 실리지 않게 이름만
    try:
        data = response.json()
    except ValueError:
        data = None
    return response.status_code, data


def _rest_error(status: int, body: Any, *, forbidden: str = "forbidden") -> DiscordStepError:
    if status == 401:
        return DiscordStepError("token_rejected")
    if status == 403:
        return DiscordStepError(forbidden)
    if status == 429:
        wait = body.get("retry_after") if isinstance(body, dict) else None
        seconds = max(1, int(round(float(wait)))) if isinstance(wait, (int, float)) else 5
        return DiscordStepError("rate_limited", _msg("rate_limited", seconds))
    return DiscordStepError("discord_error", _msg("discord_error", status))


#: 디스코드가 「이만큼 기다려라」(429 의 retry_after)라고 할 때 사람에게 다시 누르라 하지 않고 손자리가 기다려 주는 상한(초).
#: ★ 2026-10-23 팀 노트북 실사용: `/users/@me/guilds` 는 봇마다 **1초에 한 번**이다(`x-ratelimit-limit: 1` 실측).
#:   마무리가 그 목록을 곧바로 두 번 물어 누를 때마다 「1초 뒤에 다시」만 떴다.
RATE_LIMIT_WAIT_MAX_SEC = 5.0


def _retry_after(body: Any) -> float | None:
    wait = body.get("retry_after") if isinstance(body, dict) else None
    return float(wait) if isinstance(wait, (int, float)) else None


class DiscordRest:
    """봇 토큰으로 부르는 REST 몇 개. 토큰은 머리에만 싣고, 오류는 `DiscordStepError`(사람 말)로 바꾼다.

    짧은 429(5초 이하)는 그만큼 기다렸다가 **한 번만** 다시 묻는다. 길면 예전처럼 사람 말로 돌려준다.
    """

    def __init__(self, token: str, http: HttpCall | None = None, *, sleep: Callable[[float], None] | None = None) -> None:
        self._token = token.strip()
        REDACTOR.register(self._token)
        raw = http or _http_call
        pause = sleep or time.sleep

        def http_with_wait(method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None) -> tuple[int, Any]:
            status, data = raw(method, url, headers, body)
            wait = _retry_after(data) if status == 429 else None
            if wait is not None and wait <= RATE_LIMIT_WAIT_MAX_SEC:
                pause(wait + 0.05)
                status, data = raw(method, url, headers, body)
            return status, data

        self._http = http_with_wait

    def _headers(self) -> dict[str, str]:
        from ..brand import NAME

        return {"Authorization": f"Bot {self._token}",
                "User-Agent": f"DiscordBot (https://discord.com/developers/docs, 1.0) {NAME}"}

    def call(self, method: str, path: str, body: dict[str, Any] | None = None, *,
             forbidden: str = "forbidden") -> Any:
        try:
            status, data = self._http(method, f"{API_BASE}{path}", self._headers(), body)
        except OSError as exc:
            raise DiscordStepError("unreachable") from exc
        if status >= 400:
            raise _rest_error(status, data, forbidden=forbidden)
        return data

    def check(self) -> BotCheck:
        seen: dict[str, Any] = {}

        def get(url: str, headers: dict[str, str]) -> tuple[int, Any]:
            status, data = self._http("GET", url, headers, None)
            seen["body"] = data   # 429 의 retry_after 를 `check_bot_token` 이 버리지 않게 붙들어 둔다
            return status, data

        try:
            return check_bot_token(self._token, get=get)
        except DiscordAPIError as exc:
            raise _rest_error(exc.status, seen.get("body")) from exc
        except OSError as exc:
            raise DiscordStepError("unreachable") from exc

    def guilds(self) -> list[dict[str, Any]]:
        data = self.call("GET", "/users/@me/guilds")
        return [g for g in data or [] if isinstance(g, dict) and g.get("id")]

    def guild_owner(self, guild_id: str) -> str:
        data = self.call("GET", f"/guilds/{guild_id}") or {}
        return str(data.get("owner_id") or "")

    def channels(self, guild_id: str) -> list[dict[str, Any]]:
        data = self.call("GET", f"/guilds/{guild_id}/channels")
        return [c for c in data or [] if isinstance(c, dict) and c.get("id")]

    def send_dm(self, user_id: str, content: str) -> None:
        channel = self.call("POST", "/users/@me/channels", {"recipient_id": str(user_id)}, forbidden="dm_forbidden") or {}
        if not channel.get("id"):
            raise DiscordStepError("dm_failed")
        # 우리가 쓴 글이지만 같은 원칙 — 아무도 부르지 않는다.
        self.call("POST", f"/channels/{channel['id']}/messages",
                  {"content": content[:2000], "allowed_mentions": {"parse": []}}, forbidden="dm_forbidden")


def first_text_channel(channels: list[dict[str, Any]]) -> dict[str, Any] | None:
    """디스코드 왼쪽 목록에서 맨 위에 보이는 글 채널 — 분류 없는 것 먼저, 그다음 분류 순서 · 채널 순서."""
    categories = {str(c["id"]): int(c.get("position") or 0) for c in channels if c.get("type") == GUILD_CATEGORY}
    texts = [c for c in channels if c.get("type") == GUILD_TEXT]
    if not texts:
        return None

    def order(channel: dict[str, Any]) -> tuple[int, int, int, int]:
        parent = str(channel.get("parent_id") or "")
        in_category = 1 if parent else 0
        return (in_category, categories.get(parent, 0), int(channel.get("position") or 0), int(channel["id"]))

    return sorted(texts, key=order)[0]


def pick_home_channel(rest: DiscordRest, allowed: list[str],
                      guilds: list[dict[str, Any]] | None = None) -> tuple[str, str]:
    """봇이 든 서버 가운데 **주인이 허용 목록 사람인 서버**의 첫 글 채널 (id, 이름). 없으면 ("", "").

    남의 서버(친구 서버에 봇을 들인 경우)는 건너뛴다 — 거기 채널을 멘션 없이 받는 자리로 만들면 남의 대화에 낀다.
    """
    allowed_set = {str(uid) for uid in allowed}
    # 부른 쪽이 이미 받은 목록을 넘기면 다시 묻지 않는다 — 이 물음은 1초에 한 번이다.
    for guild in (rest.guilds() if guilds is None else guilds):
        if rest.guild_owner(str(guild["id"])) not in allowed_set:
            continue
        channel = first_text_channel(rest.channels(str(guild["id"])))
        if channel is not None:
            return str(channel["id"]), str(channel.get("name") or "")
    return "", ""


# ── 클립보드 ────────────────────────────────────────────────────────────────────

class SystemClipboard:
    """윈도우 클립보드의 글. 화면 · 모델을 거치지 않고 본체가 직접 읽는다."""

    def read(self) -> str:
        if os.name != "nt":
            raise RuntimeError("windows_only")
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            try:
                value = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            except Exception:  # noqa: BLE001 — 글이 아닌 것(그림 등)이 들어 있다
                return ""
        finally:
            win32clipboard.CloseClipboard()
        return str(value or "")[:4000]

    def clear(self) -> None:
        if os.name != "nt":
            return
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
        finally:
            win32clipboard.CloseClipboard()


def system_clipboard() -> SystemClipboard:
    """시험(`tests/conftest.py`)이 가짜로 바꾸는 자리 — 회귀가 사람의 진짜 클립보드를 읽거나 비우지 않게."""
    return SystemClipboard()


# ── 기록 ────────────────────────────────────────────────────────────────────────

_LOG_READY = False


def _setup_logging(data_dir: Path) -> None:
    """본체에는 기록 처리기가 따로 없다(uvicorn 것뿐). discord.py 기록을 가리개 달린 파일로만 보낸다."""
    global _LOG_READY
    if _LOG_READY:
        return
    _LOG_READY = True
    try:
        folder = data_dir / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(folder / LOG_FILE, maxBytes=2_000_000, backupCount=3,
                                                       encoding="utf-8")
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter(REDACTOR))
    discord_log = logging.getLogger("discord")
    discord_log.setLevel(logging.WARNING)
    discord_log.addHandler(handler)
    discord_log.propagate = False   # 가리개 없는 처리기(콘솔 · lastResort)로 새지 않게
    ours = logging.getLogger("sonjari.messaging")
    ours.addHandler(handler)
    if ours.level == logging.NOTSET:
        ours.setLevel(logging.INFO)


# ── 서비스 ──────────────────────────────────────────────────────────────────────

@dataclass
class _Known:
    """마지막으로 디스코드에서 확인한 것 — status 가 부를 때마다 디스코드에 묻지 않는다."""

    check: BotCheck | None = None
    servers: int | None = None
    checked_at: float = 0.0


def discord_installed() -> bool:
    return importlib.util.find_spec("discord") is not None


class DiscordService:
    """본체 안의 디스코드 다리 하나 + 연결 단계 문들. 스레드 안전(문들은 FastAPI 의 일꾼 스레드에서 온다)."""

    def __init__(self, config: Any, *, store: credentials.CredentialStore | None = None,
                 http: HttpCall | None = None, clipboard: Any = None,
                 compose: Callable[..., tuple[Any, Any]] | None = None,
                 publish: Callable[[str, dict[str, Any]], Any] | None = None,
                 installed: Callable[[], bool] = discord_installed,
                 lang: Callable[[], str] | None = None,
                 retry_delays: tuple[float, ...] = RETRY_DELAYS,
                 aliases: Any = None,
                 sleep: Callable[[float], None] | None = None) -> None:
        self.config = config
        #: 모델 별명 표(`model_aliases.ModelAliasBook`) — status 에 같이 싣고, 기본 모델을 고를 때 검사한다.
        self._aliases = aliases
        self._store = store
        self._http = http
        self._clipboard = clipboard
        self._compose = compose
        self._publish = publish
        self._installed = installed
        self._lang = lang
        self._retry_delays = retry_delays
        self._sleep = sleep   # 짧은 429 를 기다리는 자리(시험은 가짜 시계)
        self._mutex = threading.RLock()      # 시작 · 멈춤 · 단계 문을 한 줄로
        self._lock_mutex = threading.Lock()  # 잠금 파일 쥐기 · 놓기만(다리 스레드도 쓴다)
        self._instance: Any = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._adapter: Any = None
        self._stopping = threading.Event()
        self._known = _Known()
        self._other_process = False
        self.last_error = ""
        self._requests_book: AccessRequestBook | None = None

    # ── 바깥에서 갈아 끼우는 자리 ──────────────────────────────────────────────

    @property
    def data_dir(self) -> Path:
        return Path(self.config.data_dir)

    def _store_now(self) -> credentials.CredentialStore:
        return self._store or credentials.default_store()

    def _clipboard_now(self) -> Any:
        return self._clipboard or system_clipboard()

    def _rest(self, token: str) -> DiscordRest:
        return DiscordRest(token, self._http, sleep=self._sleep)

    def _ui_lang(self) -> str:
        if self._lang is not None:
            return self._lang()
        try:
            from .. import ui_i18n

            return ui_i18n.lang()
        except Exception:  # noqa: BLE001
            return "ko"

    def _base_url(self) -> str:
        host = str(getattr(self.config, "host", "127.0.0.1") or "127.0.0.1")
        host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host  # noqa: S104 — 받는 주소가 아니라 부르는 주소다
        return f"http://{host}:{int(getattr(self.config, 'port', 8091))}"

    def _enabled(self) -> bool:
        return bool(getattr(self.config, "discord_bridge_enabled", True))

    def _note(self, event: str, **data: Any) -> None:
        if self._publish is None:
            return
        try:
            self._publish("discord_bridge", {"event": event, **data})
        except Exception:  # noqa: BLE001, S110 — 알림은 덤이다
            pass

    def _fail(self, message: str) -> None:
        self.last_error = REDACTOR.redact(message)[:500]
        log.warning("디스코드 다리: %s", self.last_error)
        self._note("error", error=self.last_error)

    def _load_token(self) -> str:
        try:
            return credentials.load_bot_token(self._store_now())
        except Exception as exc:  # noqa: BLE001 — 자격 증명 관리자를 못 열었다
            raise DiscordStepError("store_unreadable") from exc

    @property
    def requests(self) -> AccessRequestBook:
        if self._requests_book is None or self._requests_book.path.parent != self.data_dir:
            self._requests_book = AccessRequestBook(self.data_dir)
        return self._requests_book

    def _settings(self) -> DiscordSettings:
        return DiscordSettings.load(self.data_dir / SETTINGS_FILE)

    # ── 잠금 ──────────────────────────────────────────────────────────────────

    def _acquire_lock(self) -> bool:
        from .__main__ import _SingleInstance

        with self._lock_mutex:
            if self._instance is not None and self._instance.held:
                return True
            instance = _SingleInstance(self.data_dir / LOCK_FILE)
            if not instance.acquire():
                return False
            self._instance = instance
            return True

    def _release_lock(self) -> None:
        with self._lock_mutex:
            instance, self._instance = self._instance, None
        if instance is not None:
            instance.release()

    def _held_by_other(self) -> bool:
        """우리가 안 쥐고 있을 때 잠금이 잡혀 있으면 따로 띄운 다리가 돈다. 잠깐 쥐어 보고 바로 놓는다."""
        from .__main__ import _SingleInstance

        with self._lock_mutex:
            if self._instance is not None and self._instance.held:
                return False
            probe = _SingleInstance(self.data_dir / LOCK_FILE)
            try:
                if probe.acquire():
                    probe.release()
                    return False
            except OSError:
                return False
            return True

    # ── 켜기 · 끄기 ───────────────────────────────────────────────────────────

    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> dict[str, Any]:
        """본체가 뜰 때 · 마무리 문이 부른다. 예외를 올리지 않는다 — 못 켜면 까닭을 `last_error` 에 남긴다."""
        try:
            with self._mutex:
                return self._start_locked()
        except Exception as exc:  # noqa: BLE001 — 다리 때문에 본체가 못 뜨면 안 된다
            self._fail(_msg("bridge_failed", type(exc).__name__))
            return {"started": False, "reason": "error"}

    def _start_locked(self) -> dict[str, Any]:
        if self.running():
            return {"started": True, "reason": "already"}
        self._other_process = False
        if not self._enabled():
            return {"started": False, "reason": "disabled"}
        if not self._installed():
            return {"started": False, "reason": "not_installed"}
        try:
            token = self._load_token()
        except DiscordStepError as exc:
            self._fail(exc.message)
            return {"started": False, "reason": exc.code}
        if not token:
            return {"started": False, "reason": "no_token"}
        control_token = str(getattr(self.config, "control_token", "") or "")
        if not control_token:
            self._fail(_msg("no_control_token"))
            return {"started": False, "reason": "no_control_token"}
        if not self._acquire_lock():
            self._other_process = True
            log.info("따로 띄운 디스코드 다리가 이미 돌고 있어 본체는 다리를 띄우지 않습니다.")
            self._note("other_process")
            return {"started": False, "reason": "other_process"}
        self.last_error = ""
        self._stopping.clear()
        _setup_logging(self.data_dir)
        thread = threading.Thread(target=self._thread_main, args=(token, control_token),
                                  name="sonjari-discord-bridge", daemon=True)
        self._thread = thread
        thread.start()
        self._note("started")
        return {"started": True, "reason": "started"}

    def stop(self, timeout: float = 15.0) -> None:
        with self._mutex:
            self._stopping.set()
            loop, adapter, thread = self._loop, self._adapter, self._thread
            if loop is not None and adapter is not None and not loop.is_closed():
                try:
                    asyncio.run_coroutine_threadsafe(adapter.disconnect(), loop).result(timeout=timeout)
                except Exception as exc:  # noqa: BLE001 — 끊기가 늦어도 아래에서 스레드를 기다린다
                    log.warning("디스코드 다리 끊기: %s", REDACTOR.redact(type(exc).__name__))
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout)
            self._thread = None
            self._release_lock()
            self._note("stopped")

    def restart(self) -> dict[str, Any]:
        with self._mutex:
            self.stop()
            return self.start()

    def _thread_main(self, token: str, control_token: str) -> None:
        try:
            # 붙기 전에 한 번 묻는다 — 틀린 토큰 · 꺼진 Intent 로 게이트웨이에 붙었다 끊기는 것을 되풀이하지 않는다.
            try:
                check = self._rest(token).check()
            except DiscordStepError as exc:
                if exc.code == "token_rejected":
                    self._fail(_msg("login_failed"))
                    return
                check = None   # 인터넷이 아직 없으면 그냥 붙어 본다(아래에서 다시 시도한다)
            if check is not None:
                self._remember(check)
                if not check.message_content:
                    self._fail(_msg("intent_off"))
                    return
            asyncio.run(self._serve(token, control_token))
        except Exception as exc:  # noqa: BLE001 — 스레드 밖으로 올리지 않는다
            self._fail(_msg("bridge_failed", type(exc).__name__))
        finally:
            self._loop = None
            self._adapter = None
            self._release_lock()

    async def _serve(self, token: str, control_token: str) -> None:
        compose = self._compose
        if compose is None:
            from .__main__ import compose_bridge as compose
        self._loop = asyncio.get_running_loop()
        attempt = 0
        while not self._stopping.is_set():
            adapter, backend = compose(self.data_dir, self._base_url(), control_token, token)
            self._adapter = adapter
            try:
                await adapter.run_forever()
                return   # 우리가 끊었다(stop)
            except Exception as exc:  # noqa: BLE001
                name = type(exc).__name__
                if name == "LoginFailure":
                    self._fail(_msg("login_failed"))
                    return
                if name == "PrivilegedIntentsRequired":
                    self._fail(_msg("intent_off"))
                    return
                self._fail(_msg("bridge_failed", name))
            finally:
                try:
                    await backend.aclose()
                except Exception:  # noqa: BLE001, S110
                    pass
            delay = self._retry_delays[min(attempt, len(self._retry_delays) - 1)] if self._retry_delays else 0
            attempt += 1
            if await asyncio.to_thread(self._stopping.wait, delay):
                return

    def connected(self) -> bool:
        adapter = self._adapter
        ready = getattr(adapter, "_ready", None)
        return bool(self.running() and ready is not None and ready.is_set())

    def _live_servers(self) -> int | None:
        """붙어 있으면 디스코드 접속이 실제로 받은 서버 수. 모르면 None.

        ★ 2026-10-18 첫 운영: 「손자리」 서버에 들어가 있는데 status 가 서버 0곳(→ need_invite)을 냈다. 토큰 확인 때 읽은
          `/applications/@me` 의 대략치(approximate_guild_count)는 늦게 바뀐다 — 붙어 있으면 접속이 가진 목록이 진짜다.
        """
        if not self.connected():
            return None
        client = getattr(self._adapter, "_client", None)
        guilds = getattr(client, "guilds", None)
        try:
            return len(guilds) if guilds is not None else None
        except TypeError:
            return None

    def wait_ready(self, timeout: float = READY_WAIT_SEC) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.connected():
                return True
            if not self.running():
                return False
            time.sleep(0.2)
        return self.connected()

    # ── 보기 ──────────────────────────────────────────────────────────────────

    def _remember(self, check: BotCheck, servers: int | None = None) -> None:
        self._known = _Known(check=check, servers=servers if servers is not None else check.server_count,
                             checked_at=time.time())

    def status(self) -> dict[str, Any]:
        installed = self._installed()
        try:
            token_saved = bool(self._load_token())
            store_error = ""
        except DiscordStepError as exc:
            token_saved, store_error = False, exc.message
        settings = self._settings()
        running = self.running()
        if running:
            owner = "self"
        elif self._other_process or self._held_by_other():
            owner = "other"
        else:
            owner = ""
        known = self._known if token_saved else _Known()
        live = self._live_servers() if token_saved else None
        if live is not None and live != known.servers:
            known = _Known(check=known.check, servers=live, checked_at=known.checked_at)
            self._known = known
        check = known.check
        app_id = check.app_id if check else ""
        connected = self.connected()
        if not installed:
            stage = "not_installed"
        elif not token_saved:
            stage = "no_token"
        elif owner == "other":
            stage = "other_process"
        elif check is not None and not check.message_content:
            stage = "need_intent"
        elif known.servers == 0 and not (check is not None and check.user_install_enabled):
            stage = "need_invite"
        elif connected:
            stage = "connected"
        elif running:
            stage = "connecting"
        else:
            stage = "ready_to_finish"
        return {
            "enabled": self._enabled(),
            "installed": installed,
            "token_saved": token_saved,
            "running": running or owner == "other",
            "connected": connected,
            "owner_process": owner,
            "stage": stage,
            "bot_name": check.bot_name if check else "",
            "app_id": app_id,
            "message_content": check.message_content if check else None,
            "servers": known.servers,
            "checked_at": known.checked_at or None,
            "home_channel_id": settings.home_channel_id,
            "home_channel_name": settings.home_channel_name,
            "allowed_user_ids": len(settings.allowed_user_ids),
            "invite_url": invite_url(app_id) if app_id else "",
            "portal_url": PORTAL,
            "portal_bot_url": f"{PORTAL}/{app_id}/bot" if app_id else "",
            "last_error": store_error or self.last_error,
            "default_model_alias": settings.default_model_alias,
            "aliases": self._alias_items(),
            # 사용자 설치(서버 없이 내 계정에) — 켜져 있으면 서버 0곳은 문제가 아니다(2026-10-18).
            "user_install_url": check.user_install_url if check else "",
            "user_install_enabled": bool(check.user_install_enabled) if check else False,
            "servers_note": ("user_install_possible" if check is not None and check.user_install_enabled
                             and known.servers == 0 else ""),
            "pending_requests": len(self._pending_safe()),
        }

    def _pending_safe(self) -> list[dict[str, Any]]:
        try:
            return self.requests.pending()
        except Exception:  # noqa: BLE001
            return []

    # ── 허용 요청(가족 · 동료 추가 카드, 2026-10-18) ──────────────────────────────

    def record_access_request(self, body: dict[str, Any]) -> dict[str, Any]:
        """다리가 부른다 — 허용 목록 밖 사람이 봇에게 말을 걸었다. 일은 시작하지 않는다(그 문은 `allow_request` 하나뿐)."""
        uid = clean_user_id(body.get("user_id"))
        if not uid:
            return {"ok": False, "error": "invalid_user_id", "notify": False}
        if uid in self._settings().allowed_user_ids:
            # 방금 허용됐는데 다리가 아직 모른다 — 안내도 카드도 필요 없다.
            return {"ok": True, "notify": False, "new": False, "ignored": False, "allowed": True}
        result = self.requests.record(uid, display_name=str(body.get("display_name") or ""),
                                      username=str(body.get("username") or ""), text=str(body.get("text") or ""))
        if result["new"] and result["request"] and self._publish is not None:
            try:
                self._publish("discord_access_requested", dict(result["request"]))
            except Exception:  # noqa: BLE001, S110 — 카드는 GET 으로도 본다
                pass
        return {"ok": True, "notify": result["notify"], "new": result["new"], "ignored": result["ignored"],
                "allowed": False}

    def access_requests(self) -> dict[str, Any]:
        return {"requests": self.requests.pending(), "ignored_count": self.requests.ignored_count()}

    def allow_request(self, user_id: str) -> dict[str, Any]:
        return self._step(lambda: self._allow_request(user_id))

    def _allow_request(self, user_id: str) -> dict[str, Any]:
        uid = clean_user_id(user_id)
        if not uid:
            raise DiscordStepError("invalid_user_id")
        entry = self.requests.get(uid)
        if entry is None:
            # ★ 요청이 있던 사람만 — 아무 ID 나 이 문으로 들이지 않는다(주인 말고 들어오는 문은 「요청 → 허용」 하나).
            raise DiscordStepError("no_such_request")
        path = self.data_dir / SETTINGS_FILE
        settings = DiscordSettings.load(path)
        if uid not in settings.allowed_user_ids:
            settings.allowed_user_ids.append(uid)
            settings.save(path)
        policy = getattr(self._adapter, "policy", None)
        if policy is not None and hasattr(policy, "allow"):
            policy.allow(uid)   # 본체 안 다리는 바로. 따로 띄운 다리는 다음 말이 올 때 파일을 다시 읽는다.
        self.requests.pop(uid)
        dm_sent = False
        try:
            token = self._load_token()
            if token:
                self._rest(token).send_dm(uid, say("access_allowed", detect_lang(str(entry.get("first_text") or ""))))
                dm_sent = True
        except DiscordStepError:
            dm_sent = False
        message = _msg("allowed_person") + ("" if dm_sent else "\n" + _msg("allowed_dm_failed"))
        log.info("디스코드 허용 요청을 받아들였습니다: %s", uid)
        return self._result(True, message=message, dm_sent=dm_sent, user_id=uid, **self.access_requests())

    def ignore_request(self, user_id: str) -> dict[str, Any]:
        return self._step(lambda: self._ignore_request(user_id))

    def _ignore_request(self, user_id: str) -> dict[str, Any]:
        uid = clean_user_id(user_id)
        if not uid:
            raise DiscordStepError("invalid_user_id")
        self.requests.ignore(uid)
        return self._result(True, message=_msg("ignored_person"), user_id=uid, **self.access_requests())

    def _alias_items(self) -> list[dict[str, str]]:
        if self._aliases is None:
            return []
        try:
            return list(self._aliases.items())
        except Exception:  # noqa: BLE001 — 별명 표가 깨져도 연결 화면은 그린다
            return []

    def update_settings(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._step(lambda: self._update_settings(body))

    def _update_settings(self, body: dict[str, Any]) -> dict[str, Any]:
        path = self.data_dir / SETTINGS_FILE
        settings = DiscordSettings.load(path)
        if "default_model_alias" in body:
            alias = str(body.get("default_model_alias") or "").strip()
            if alias:
                from ..model_aliases import find

                found = find(self._alias_items(), alias)
                if found is None:
                    raise DiscordStepError("unknown_model_alias")
                alias = found["alias"]
            settings.default_model_alias = alias
        settings.save(path)
        # 다리는 판마다 설정 파일을 다시 읽는다(`bridge.TaskRunner._default_model`) — 다시 켤 필요가 없다.
        return self._result(True)

    def _result(self, ok: bool, *, error: str = "", message: str = "", **extra: Any) -> dict[str, Any]:
        body = self.status()
        body.update({"ok": ok, "error": error, "message": REDACTOR.redact(message), **extra})
        return body

    def _step(self, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            with self._mutex:
                return fn()
        except DiscordStepError as exc:
            return self._result(False, error=exc.code, message=exc.message)
        except Exception as exc:  # noqa: BLE001 — 문이 500 으로 죽지 않게. 예외 문장은 싣지 않는다(토큰이 섞일 수 있다)
            log.warning("디스코드 연결 단계 실패: %s", type(exc).__name__)
            return self._result(False, error="internal", message=_msg("bridge_failed", type(exc).__name__))

    # ── 단계 문 ────────────────────────────────────────────────────────────────

    def token_from_clipboard(self) -> dict[str, Any]:
        return self._step(self._token_from_clipboard)

    def _token_from_clipboard(self) -> dict[str, Any]:
        if not self._installed():
            raise DiscordStepError("not_installed")
        clipboard = self._clipboard_now()
        try:
            raw = clipboard.read()
        except Exception as exc:  # noqa: BLE001 — 다른 프로그램이 클립보드를 쥐고 있다
            raise DiscordStepError("clipboard_unavailable") from exc
        token = str(raw or "").strip()
        if not token:
            raise DiscordStepError("clipboard_empty")
        # ★ 모양이 틀린 글은 **무엇이 들어 있었는지 되풀이하지 않는다** — 사람이 실수로 복사한 다른 글(비밀번호 등)일 수 있다.
        if token_shape_error(token):
            code = "application_id" if token.isdigit() else "has_spaces" if any(ch.isspace() for ch in token) else "not_a_token"
            raise DiscordStepError(code)
        REDACTOR.register(token)
        check = self._rest(token).check()
        try:
            credentials.save_bot_token(token, self._store_now())
        except Exception as exc:  # noqa: BLE001
            raise DiscordStepError("store_failed") from exc
        self._remember(check)
        cleared = False
        try:
            if str(clipboard.read() or "").strip() == token:
                clipboard.clear()
                cleared = True
        except Exception:  # noqa: BLE001 — 못 비웠으면 화면이 「클립보드를 비워 주세요」라고 말할 수 있게 cleared=False
            cleared = False
        path = self.data_dir / SETTINGS_FILE
        settings = DiscordSettings.load(path)
        added = [uid for uid, _name in check.owners if uid not in settings.allowed_user_ids]
        if added:
            settings.allowed_user_ids = [*settings.allowed_user_ids, *added]
            settings.save(path)
        if self.running():
            # 토큰이 바뀌었다 — 돌던 다리는 옛 토큰을 쥐고 있다.
            self.restart()
        log.info("디스코드 봇 토큰을 확인하고 저장했습니다(봇 %s).", check.bot_name)
        return self._result(True, message=_msg("saved"), clipboard_cleared=cleared,
                            owners_added=len(added))

    def recheck(self) -> dict[str, Any]:
        return self._step(self._recheck)

    def _recheck(self) -> dict[str, Any]:
        token = self._load_token()
        if not token:
            raise DiscordStepError("no_token")
        rest = self._rest(token)
        check = rest.check()
        servers = len(rest.guilds())
        self._remember(check, servers)
        if not check.message_content:
            return self._result(True, message=_msg("intent_off"))
        if servers == 0:
            # 사용자 설치면 서버 0곳은 문제가 아니다 — 「문제」로 말하지 않는다.
            return self._result(True, message=_msg("user_install_maybe" if check.user_install_enabled else "not_in_server"))
        return self._result(True)

    def finish(self) -> dict[str, Any]:
        return self._step(self._finish)

    def _finish(self) -> dict[str, Any]:
        if not self._installed():
            raise DiscordStepError("not_installed")
        token = self._load_token()
        if not token:
            raise DiscordStepError("no_token")
        rest = self._rest(token)
        check = rest.check()
        guilds = rest.guilds()
        self._remember(check, len(guilds))
        if not check.message_content:
            raise DiscordStepError("intent_off")
        if not guilds and not check.user_install_enabled:
            raise DiscordStepError("not_in_server")
        path = self.data_dir / SETTINGS_FILE
        settings = DiscordSettings.load(path)
        for uid, _name in check.owners:
            if uid not in settings.allowed_user_ids:
                settings.allowed_user_ids.append(uid)
        home_auto = False
        if not settings.home_channel_id:
            channel_id, channel_name = pick_home_channel(rest, settings.allowed_user_ids, guilds)
            if channel_id:
                settings.home_channel_id, settings.home_channel_name = channel_id, channel_name
                home_auto = True
        settings.save(path)
        # 다리를 (다시) 켠다 — 홈 채널 · 허용 목록은 다리를 만들 때 읽는다.
        if self.running():
            self.stop()
        started = self.start()
        if started.get("reason") == "other_process":
            message = _msg("other_process")
        else:
            self.wait_ready()
            message = _msg("connected")
        welcome_sent, welcome_error = self._send_welcome(rest, check, settings)
        if welcome_error:
            message = f"{message}\n{welcome_error}"   # 줄로 나눠야 영어 사전이 문장마다 바꾼다(`ui_i18n`)
        return self._result(True, message=message, home_channel_auto=home_auto,
                            welcome_sent=welcome_sent, welcome_error=welcome_error)

    def _send_welcome(self, rest: DiscordRest, check: BotCheck, settings: DiscordSettings) -> tuple[bool, str]:
        owners = [uid for uid, _name in check.owners if uid in settings.allowed_user_ids]
        if not owners:
            return False, _msg("no_owner")
        lang = "en" if self._ui_lang() == "en" else "ko"
        home = WELCOME_HOME[lang].format(channel=settings.home_channel_id) if settings.home_channel_id else ""
        text = WELCOME[lang].format(home=home)
        sent, error = False, ""
        for uid in owners:
            try:
                rest.send_dm(uid, text)
                sent = True
            except DiscordStepError as exc:
                error = exc.message if exc.code == "dm_forbidden" else _msg("dm_failed")
        return sent, "" if sent else error

    def disconnect(self) -> dict[str, Any]:
        return self._step(self._disconnect)

    def _disconnect(self) -> dict[str, Any]:
        self.stop()
        try:
            self._store_now().delete(credentials.TARGET)
        except Exception as exc:  # noqa: BLE001
            raise DiscordStepError("store_unreadable") from exc
        self._known = _Known()
        self.last_error = ""
        log.info("디스코드 연결을 끊고 봇 토큰을 지웠습니다(허용 목록은 남김).")
        return self._result(True, message=_msg("disconnected"))
