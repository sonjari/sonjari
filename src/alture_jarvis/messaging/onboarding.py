"""디스코드 봇 연결 마법사 — `python -m alture_jarvis.messaging setup` (2026-10-17).

Hermes Agent `plugins/platforms/discord/onboarding.py`(MIT, Copyright (c) 2025 Nous Research)를 본떴다.

## 왜 이 순서인가 (Hermes 머리글의 관찰을 그대로 받는다)

디스코드 설정은 개발자 포털에서 틀린다: 다른 페이지의 값(애플리케이션 ID)을 토큰 자리에 붙이고, Message Content
Intent 를 안 켜고(그러면 디스코드가 봇 접속을 거절한다), 초대 링크를 손으로 만들고, 자기 사용자 ID 를 알려고
개발자 모드를 켠다. `GET /applications/@me` 한 번이 그걸 다 답한다 — 토큰이 맞는지 · Intent 가 켜졌는지 · 봇이 몇
서버에 있는지 · 앱 주인이 누구인지. 그래서 사람에게 확인시키지 않고 이 응답을 읽는다.

★ 토큰은 화면에 다시 찍지 않는다(입력도 가린다). 저장은 자격 증명 관리자에만(`credentials.py`).
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from ..brand import NAME, NAME_KO
from .base import REDACTOR
from .credentials import CredentialStore, save_bot_token
from .discord_config import SETTINGS_FILE, DiscordSettings

API_BASE = "https://discord.com/api/v10"
PORTAL = "https://discord.com/developers/applications"

#: 다리가 실제로 쓰는 권한만 — 이름으로 적어 두고 숫자는 **계산**한다(초대 링크 숫자를 믿지 말고 다시 셀 수 있게).
#: Hermes 목록에서 음성(Connect · Speak)은 뺐다 — 우리는 글만 주고받는다.
INVITE_PERMISSION_BITS = {
    "Add Reactions": 6,
    "View Channels": 10,
    "Send Messages": 11,
    "Embed Links": 14,
    "Attach Files": 15,
    "Read Message History": 16,
    "Create Public Threads": 35,
    "Send Messages in Threads": 38,
}
INVITE_PERMISSIONS = sum(1 << bit for bit in INVITE_PERMISSION_BITS.values())
#: 앱 flags 의 Message Content Intent 두 칸(켜짐 · 100서버 미만 제한 켜짐). 둘 중 하나면 켜진 것이다.
FLAGS_MESSAGE_CONTENT = (1 << 18) | (1 << 19)
_TEAM_MEMBER_ACCEPTED = 2


class DiscordAPIError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"discord_api_{status}")
        self.status = status


def invite_url(app_id: str) -> str:
    # integration_type=0 — 서버 설치. 「서버에 추가 / 내 앱에 추가」를 묻지 않게 한다(Hermes 와 같다).
    query = urlencode({"client_id": app_id, "scope": "bot applications.commands",
                       "permissions": INVITE_PERMISSIONS, "integration_type": 0})
    return f"https://discord.com/oauth2/authorize?{query}"


def user_install_url(app_id: str) -> str:
    """서버 없이 **내 계정**에 앱을 설치하는 링크(integration_type=1). 슬래시 명령만 담는다."""
    query = urlencode({"client_id": app_id, "integration_type": 1, "scope": "applications.commands"})
    return f"https://discord.com/oauth2/authorize?{query}"


@dataclass(frozen=True)
class BotCheck:
    app_id: str
    bot_name: str
    owners: tuple[tuple[str, str], ...]   # (사용자 ID, 이름) — 앱 주인, 또는 팀이면 수락한 팀원 전부
    message_content: bool
    server_count: Optional[int]
    #: 앱 설정에서 「사용자 설치(User Install)」가 켜져 있나 — 켜져 있으면 서버 0곳도 정상일 수 있다 (2026-10-18).
    user_install_enabled: bool = False

    @property
    def invite_url(self) -> str:
        return invite_url(self.app_id)

    @property
    def user_install_url(self) -> str:
        return user_install_url(self.app_id)

    @property
    def bot_settings_url(self) -> str:
        return f"{PORTAL}/{self.app_id}/bot"


def token_shape_error(token: str) -> str | None:
    """봇 토큰이 아닌 것을 붙였으면 까닭. 맞는 모양이면 None.

    가장 흔한 실수: 포털 「General Information」의 **애플리케이션 ID(숫자)**를 붙인다. 봇 토큰은 「Bot」 페이지에 있고
    점(.)으로 나뉜 긴 글자다 — 숫자만으로 된 토큰은 없다.
    """
    value = str(token or "").strip()
    if not value:
        return "비어 있습니다."
    if value.isdigit():
        return ("숫자만 있습니다 — 애플리케이션 ID 를 붙여 넣으신 것 같습니다. 토큰은 포털의 「Bot」 페이지에서 "
                "「Reset Token」을 눌러 나온 긴 글자입니다(「General Information」의 숫자가 아닙니다).")
    if any(ch.isspace() for ch in value):
        return "중간에 빈칸이나 줄바꿈이 섞여 있습니다 — 「Bot」 페이지에서 토큰을 다시 복사해 주세요."
    if value.count(".") != 2:
        return "봇 토큰 모양이 아닙니다(점 두 개로 나뉜 긴 글자여야 합니다). 「Bot」 페이지의 토큰을 붙여 넣어 주세요."
    return None


def _owners(app: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    team = app.get("team")
    if isinstance(team, dict):
        return tuple(
            (str(m["user"]["id"]), str(m["user"].get("username") or m["user"]["id"]))
            for m in team.get("members") or []
            if m.get("membership_state") == _TEAM_MEMBER_ACCEPTED and (m.get("user") or {}).get("id")
        )
    owner = app.get("owner") or {}
    return ((str(owner["id"]), str(owner.get("username") or owner["id"])),) if owner.get("id") else ()


HttpGet = Callable[[str, dict[str, str]], tuple[int, Any]]


def _http_get(url: str, headers: dict[str, str]) -> tuple[int, Any]:
    import httpx

    try:
        response = httpx.get(url, headers=headers, timeout=10)
    except httpx.RequestError as exc:
        raise OSError(type(exc).__name__) from exc
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body


def check_bot_token(token: str, *, get: HttpGet | None = None) -> BotCheck:
    """토큰으로 그 앱을 읽는다. 401 이면 `DiscordAPIError(401)`, 연결이 안 되면 `OSError`."""
    REDACTOR.register(token)
    status, app = (get or _http_get)(f"{API_BASE}/applications/@me",
                                      {"Authorization": f"Bot {token.strip()}",
                                       "User-Agent": f"DiscordBot (https://discord.com/developers/docs, 1.0) {NAME}"})
    if status != 200 or not isinstance(app, dict):
        raise DiscordAPIError(status)
    flags = int(app.get("flags") or 0)
    bot = app.get("bot") or {}
    count = app.get("approximate_guild_count")
    install_types = app.get("integration_types_config")
    return BotCheck(
        app_id=str(app["id"]),
        bot_name=str(bot.get("username") or app.get("name") or app["id"]),
        owners=_owners(app),
        message_content=bool(flags & FLAGS_MESSAGE_CONTENT),
        server_count=count if isinstance(count, int) else None,
        # 키가 문자열 "0"(서버 설치) · "1"(사용자 설치)이다.
        user_install_enabled=isinstance(install_types, dict) and "1" in {str(key) for key in install_types},
    )


def clean_user_ids(raw: str) -> list[str]:
    """`<@123>` · `user:123` · 빈칸을 걷고 숫자 ID 만. 이름은 받지 않는다(이름으로 찾으려면 Server Members Intent 가 필요하다)."""
    out: list[str] = []
    for part in str(raw or "").replace(" ", "").split(","):
        uid = part.strip()
        if uid.startswith("<@") and uid.endswith(">"):
            uid = uid.lstrip("<@!").rstrip(">")
        if uid.lower().startswith("user:"):
            uid = uid[5:]
        if uid.isdigit() and uid not in out:
            out.append(uid)
    return out


def run_setup(*, data_dir: Path, store: CredentialStore | None = None, ask: Callable[[str], str] = input,
              ask_secret: Callable[[str], str] = getpass.getpass, out: Callable[[str], None] = print,
              get: HttpGet | None = None, advanced: bool = False) -> int:
    """대화형 설정. 0 = 저장함, 1 = 아무것도 저장하지 않음.

    ★ 2026-10-18 대표: 앱 주인은 묻지 않고 허용한다(봇을 만든 사람이 쓰는 봇이다). 다른 사람 ID · 홈 채널도 기본은 묻지 않는다 —
      다른 사람은 그 사람이 봇에게 말을 걸면 PC 화면에 「허용 요청」 카드가 뜬다(`access_requests.py`). `advanced` 일 때만 묻는다.
    """
    out(f"── {NAME_KO}({NAME}) 디스코드 연결 ──")
    out(f"1. {PORTAL} 에서 「New Application」으로 앱을 만듭니다.")
    out("2. 왼쪽 「Bot」 → 「Reset Token」 → 나온 토큰을 복사합니다(한 번만 보입니다).")
    out("   토큰 · Intent · 초대 링크는 이 마법사가 이어서 확인합니다. 토큰은 화면에 보이지 않게 입력됩니다.")

    token, check = _ask_checked_token(ask=ask, ask_secret=ask_secret, out=out, get=get)
    if not token:
        out("아무것도 저장하지 않았습니다.")
        return 1
    if check is not None:
        check = _ensure_message_content(token, check, ask=ask, out=out, get=get)
        out("")
        out("📨 봇을 서버에 들이는 링크(다리가 쓰는 권한만 담았습니다):" if check.server_count != 0
            else "📨 봇이 아직 어느 서버에도 없습니다. 이 링크로 내 서버에 들여 주세요:")
        out(f"   {check.invite_url}")
        out("   봇과 같은 서버에 있으면 봇에게 DM 도 보낼 수 있습니다.")
        if check.user_install_enabled:
            out("   서버 없이 내 계정에 설치하려면(사용자 설치): " + check.user_install_url)
    else:
        out("확인을 못 했으니 포털 「Bot」 → Privileged Gateway Intents → Message Content Intent 가 켜졌는지 직접 봐 주세요.")

    path = data_dir / SETTINGS_FILE
    settings = DiscordSettings.load(path)
    _ask_allowlist(settings, check, ask=ask, out=out, advanced=advanced)
    if advanced:
        out("   홈 채널에서는 @멘션 없이 말해도 받습니다(채널 이름 오른쪽 클릭 → 「채널 ID 복사」, 개발자 모드 필요).")
        home = ask("홈 채널 ID (없으면 Enter): ").strip()
        if home.isdigit():
            settings.home_channel_id = home
    try:
        save_bot_token(token, store)
    except Exception as exc:  # noqa: BLE001 — 자격 증명 관리자를 못 열면 설정도 저장하지 않는다(반쪽 상태 금지)
        out(f"토큰을 윈도우 자격 증명 관리자에 저장하지 못했습니다({type(exc).__name__}). 아무것도 저장하지 않았습니다.")
        return 1
    settings.save(path)
    out("")
    out("✅ 저장했습니다 — 토큰은 윈도우 자격 증명 관리자(Sonjari/discord-bot-token)에, 나머지는 " + str(path) + " 에.")
    if not settings.allowed_user_ids:
        out("⚠ 허용 목록이 비어 있습니다 — 다리는 **아무의 말도 받지 않습니다.** setup 을 다시 돌려 사용자 ID 를 넣어 주세요.")
    out("이제 `python -m alture_jarvis.messaging` 으로 다리를 켜고, 디스코드에서 봇에게 DM 을 보내 보세요.")
    return 0


def _ask_checked_token(*, ask: Callable[[str], str], ask_secret: Callable[[str], str],
                       out: Callable[[str], None], get: HttpGet | None) -> tuple[str, BotCheck | None]:
    for _attempt in range(3):
        token = ask_secret("디스코드 봇 토큰: ").strip()
        if not token:
            return "", None
        problem = token_shape_error(token)
        if problem:
            out("✗ " + problem)
            continue
        try:
            check = check_bot_token(token, get=get)
        except DiscordAPIError as exc:
            if exc.status == 401:
                out("✗ 디스코드가 이 토큰을 거절했습니다. 「Bot」 페이지에서 「Reset Token」으로 새 토큰을 받아 붙여 주세요.")
                continue
            out(f"디스코드가 {exc.status} 로 답해 토큰을 확인하지 못했습니다.")
            return (token, None) if ask("그래도 저장할까요? (y/N): ").strip().lower() == "y" else ("", None)
        except OSError:
            out("디스코드에 연결하지 못해 토큰을 확인하지 못했습니다(인터넷 연결을 봐 주세요).")
            return (token, None) if ask("그래도 저장할까요? (y/N): ").strip().lower() == "y" else ("", None)
        out(f"✓ 토큰이 맞습니다 — 봇 「{check.bot_name}」")
        return token, check
    out("세 번 연달아 맞지 않아 저장하지 않습니다.")
    return "", None


def _ensure_message_content(token: str, check: BotCheck, *, ask: Callable[[str], str], out: Callable[[str], None],
                            get: HttpGet | None) -> BotCheck:
    for _attempt in range(5):
        if check.message_content:
            out("✓ Message Content Intent 가 켜져 있습니다.")
            return check
        out("✗ Message Content Intent 가 꺼져 있습니다 — 켜기 전에는 디스코드가 봇 접속을 거절합니다.")
        out(f"   여기서 켜 주세요: {check.bot_settings_url}")
        out("   (Privileged Gateway Intents → Message Content Intent → Save Changes)")
        if ask("저장했으면 Enter(다시 확인), 건너뛰려면 skip: ").strip().lower() == "skip":
            return check
        try:
            check = check_bot_token(token, get=get)
        except (DiscordAPIError, OSError):
            return check
    return check


def _ask_allowlist(settings: DiscordSettings, check: BotCheck | None, *, ask: Callable[[str], str],
                   out: Callable[[str], None], advanced: bool = False) -> None:
    out("")
    out("🔒 허용 목록에 있는 디스코드 사용자의 말만 받습니다(다른 사람이 말을 걸면 PC 화면에 허용 요청이 뜹니다).")
    allowed = list(settings.allowed_user_ids)
    if allowed:
        out("   이미 허용: " + ", ".join(allowed))
    owners = [(uid, name) for uid, name in (check.owners if check else ()) if uid not in allowed]
    if owners:
        who = ", ".join(f"@{name}" for _uid, name in owners)
        if not advanced:
            out(f"   앱 주인({who})을 허용했습니다.")
            allowed += [uid for uid, _name in owners]
        elif ask(f"앱 주인({who})을 허용할까요? (Y/n): ").strip().lower() not in {"n", "no"}:
            allowed += [uid for uid, _name in owners]
    if not advanced:
        settings.allowed_user_ids = allowed
        return
    out("   다른 사람은 사용자 ID 가 필요합니다: 디스코드 설정 → 고급 → 개발자 모드 켜기 → 이름 오른쪽 클릭 → 「사용자 ID 복사」.")
    extra = clean_user_ids(ask("더 허용할 사용자 ID (쉼표로 구분, 없으면 Enter): "))
    allowed += [uid for uid in extra if uid not in allowed]
    settings.allowed_user_ids = allowed
