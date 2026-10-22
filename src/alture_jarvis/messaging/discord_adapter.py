"""디스코드 어댑터 (discord.py) — Hermes Agent `plugins/platforms/discord/adapter.py` 를 본떠 작게 다시 썼다 (2026-10-17).

## 규칙 (전부 `route` 한 함수에 모았다 — discord.py 없이 시험한다)

- **밖으로만 붙는다.** 디스코드 게이트웨이에 우리가 접속한다 — PC 에 들어오는 포트를 열지 않는다.
- **기본 거부.** 허용 목록(사용자 ID)에 없는 사람의 말은 답 없이 버린다(`AccessPolicy`).
- **DM** 은 사람마다 대화 하나. **서버 채널**에서는 @멘션했을 때만 받고, 일마다 스레드를 하나 만든다(스레드 = 대화 하나).
  우리가 만든 스레드 안에서는 멘션 없이도 받는다(Hermes 의 「참여한 스레드」 규칙).
- **@everyone · 역할 호출 금지.** 모든 보내기에 `AllowedMentions.none()` — 모델이 쓴 답에 `@everyone` 이 섞여도 아무도 안 불린다.
  (Hermes 는 사용자 호출은 열어 두지만, 우리는 주인 혼자 쓰는 봇이라 전부 닫는다.)

★ `discord` 는 함수 안에서만 부른다. 이 파일을 import 해도 discord.py 가 필요 없다.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .base import (
    REDACTOR, AccessPolicy, BasePlatformAdapter, MessageEvent, SendResult, SessionMap, detect_lang, parse_command,
    session_key_for,
)

log = logging.getLogger("sonjari.messaging")

#: ★ 일반 봇이 올릴 수 있는 파일 하나의 크기 — 디스코드 기본 한도 10MiB(2024 년 25MB 에서 줄었다). 서버 부스트로
#:   늘어나는 한도는 믿지 않는다 — DM 에는 부스트가 없다. 넘으면 올리기 전에 알린다(`bridge._attach`).
DISCORD_UPLOAD_LIMIT_BYTES = 10 * 1024 * 1024
DISCORD_MAX_MESSAGE = 2000
_THREAD_NAME_MAX = 90
#: 이 대화의 모델을 고르는 슬래시 명령 — 한국어 이름과 영어 이름이 같은 일을 한다.
MODEL_COMMANDS = ("모델", "model")
_READY_TIMEOUT_SEC = 30.0


@dataclass
class Inbound:
    """디스코드 메시지에서 규칙에 필요한 것만 뽑은 것 — 시험은 이것을 직접 만든다."""

    author_id: str
    author_is_bot: bool
    content: str
    channel_id: str
    channel_kind: str            # dm | thread | channel
    message_id: str = ""
    mentions_bot: bool = False
    author_name: str = ""
    author_username: str = ""


@dataclass
class Route:
    action: str                  # task | command | request(허용 목록 밖 사람이 봇에게 말함 — 일은 안 한다)
    text: str
    session_key: str
    needs_thread: bool = False


def strip_mention(content: str, bot_id: str) -> str:
    return re.sub(rf"<@!?{re.escape(str(bot_id))}>", "", content or "").strip() if bot_id else (content or "").strip()


def route(inbound: Inbound, *, bot_id: str, policy: AccessPolicy, sessions: SessionMap,
          free_channels: frozenset[str] = frozenset()) -> Route | None:
    """이 메시지를 받을지, 받으면 어느 대화로 · 스레드를 만들지. 받지 않으면 None(답하지 않는다).

    ★ `free_channels` — 멘션 없이 받는 채널(설정의 홈 채널). 2026-10-18 대표 첫 시험: 혼자 쓰는 서버의 #일반에 「하이」를
      보냈는데 멘션이 없어 조용히 버려졌다. 헤르메스도 「멘션 없이 받는 채널」을 따로 둔다. 그 채널에서는 스레드를 열지 않고
      채널에서 바로 답한다(대화방처럼). 허용 목록 검사는 그대로다.
    """
    if inbound.author_is_bot or (bot_id and inbound.author_id == str(bot_id)):
        return None
    free = inbound.channel_kind == "channel" and inbound.channel_id in free_channels
    if inbound.channel_kind == "channel" and not inbound.mentions_bot and not free:
        return None
    if (inbound.channel_kind == "thread" and not inbound.mentions_bot
            and not sessions.is_bot_thread(inbound.channel_id)):
        return None
    text = strip_mention(inbound.content, bot_id)
    key = session_key_for(inbound.channel_kind, inbound.author_id, inbound.channel_id)
    # 멘션 · 채널 검사가 먼저다 — 남의 대화에 끼지 않은 말까지 「모르는 보낸이」로 기록하지 않는다.
    # ★ 2026-10-18: 봇에게 말을 건 모르는 사람(DM · 홈 채널 · 멘션)은 버리지 않고 「허용 요청」으로 넘긴다 — **일은 하지 않는다.**
    #   PC 화면에 카드가 뜨고 주인이 「허용」을 눌러야 들어온다(`access_requests.py`). 명령(`/stop` 등)도 똑같이 요청일 뿐이다.
    if not policy.allows(inbound.author_id):
        return Route("request", text, key)
    command = parse_command(text)
    if command:
        return Route("command", text, key)
    if not text:
        return None
    return Route("task", text, key, needs_thread=inbound.channel_kind == "channel" and not free)


def thread_name(text: str) -> str:
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    first = re.sub(r"\s+", " ", first)
    return (first[:_THREAD_NAME_MAX] or "Sonjari").strip()


CommandHandler = Callable[[str, MessageEvent], Awaitable[str]]


class DiscordAdapter(BasePlatformAdapter):
    name = "discord"
    max_message_length = DISCORD_MAX_MESSAGE
    max_split_messages = 8
    max_upload_bytes = DISCORD_UPLOAD_LIMIT_BYTES

    def __init__(self, token: str, *, policy: AccessPolicy, sessions: SessionMap,
                 free_channels: frozenset[str] = frozenset()) -> None:
        super().__init__()
        self.free_channels = frozenset(str(item) for item in free_channels if str(item))
        self._token = token
        REDACTOR.register(token)
        self.policy = policy
        self.sessions = sessions
        self._client: Any = None
        self._ready = asyncio.Event()
        self._command_handler: CommandHandler | None = None
        self._model_runner: Any = None
        self._access_handler: Callable[[MessageEvent], Awaitable[None]] | None = None
        self._synced = False

    def set_command_handler(self, handler: CommandHandler) -> None:
        self._command_handler = handler

    def set_access_handler(self, handler: Callable[[MessageEvent], Awaitable[None]]) -> None:
        """허용 목록 밖 사람이 말을 걸었을 때(`route` 의 request) — `bridge.TaskRunner.access_request`."""
        self._access_handler = handler

    def set_model_handlers(self, runner: Any) -> None:
        """`/모델` 의 고르기 · 자동 완성을 맡을 쪽(`bridge.TaskRunner` — model_command · model_choices · backend)."""
        self._model_runner = runner

    # ── 연결 ──────────────────────────────────────────────────────────────────

    def _build_client(self) -> Any:
        import discord
        from discord import app_commands

        intents = discord.Intents.default()
        intents.message_content = True   # 포털에서 「Message Content Intent」를 켜야 한다(setup 이 확인한다)
        intents.dm_messages = True
        intents.guild_messages = True
        client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        tree = app_commands.CommandTree(client)
        adapter = self

        @client.event
        async def on_ready() -> None:
            log.info("디스코드에 붙었습니다: %s (서버 %d곳)", client.user, len(client.guilds))
            adapter._ready.set()
            if not adapter._synced:
                adapter._synced = True
                try:
                    await tree.sync()
                except Exception as exc:  # noqa: BLE001 — 슬래시 명령이 없어도 글로 /stop 은 된다
                    log.warning("슬래시 명령 등록에 실패했습니다: %s", REDACTOR.redact(exc))

        @client.event
        async def on_message(message: Any) -> None:
            await adapter._on_discord_message(message)

        for name, ko, en in (("new", "새 대화를 시작합니다", "Start a fresh conversation"),
                             ("stop", "지금 하는 일을 멈춥니다", "Stop the current task"),
                             ("status", "지금 하는 일을 봅니다", "Show the current task")):
            _everywhere(tree.command(name=name, description=f"{ko} / {en}")(self._slash_callback(name)))
        # ★ `/모델` (2026-10-18) — 이 대화의 모델을 별명 표에서 고른다. 별명 표는 바뀔 수 있어 고정 선택지가 아니라
        #   자동 완성으로 보여 준다(그때그때 본체에 묻는다). 영어 화면용으로 같은 일을 하는 `/model` 도 둔다.
        for name in MODEL_COMMANDS:
            command = app_commands.Command(name=name, description="이 대화의 모델을 고릅니다 / Pick the model for this conversation",
                                           callback=self._model_callback())
            command.autocomplete("name")(self._model_autocomplete())
            tree.add_command(_everywhere(command))
        return client

    def _model_callback(self) -> Callable[..., Awaitable[None]]:
        @app_commands_describe(name="모델 별명 / model alias")
        async def callback(interaction: Any, name: str) -> None:
            await self._on_model_slash(interaction, name)

        return callback

    def _model_autocomplete(self) -> Callable[..., Awaitable[list[Any]]]:
        async def autocomplete(interaction: Any, current: str) -> list[Any]:
            from discord import app_commands

            return [app_commands.Choice(name=label, value=value)
                    for label, value in await self._model_choices(interaction, current)]

        return autocomplete

    def _slash_callback(self, command: str) -> Callable[[Any], Awaitable[None]]:
        # ★ 클래스 밖 함수 모양이어야 discord.py 가 첫 인자를 interaction 으로 본다(`utils.is_inside_class` 가
        #   qualname 의 `<locals>` 로 가른다 — discord.py 2.7.1 소스로 확인).
        async def callback(interaction: Any) -> None:
            await self._on_slash(command, interaction)

        return callback

    async def connect(self) -> bool:
        """접속을 뒤에서 시작하고 준비될 때까지 기다린다. 끊김 · 재접속은 discord.py 가 맡는다."""
        if self._client is not None:
            await self.disconnect()
        self._client = self._build_client()
        self._ready.clear()
        task = asyncio.create_task(self._client.start(self._token))
        done, _ = await asyncio.wait({task, asyncio.create_task(self._ready.wait())},
                                     timeout=_READY_TIMEOUT_SEC, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            exc = task.exception()
            log.error("디스코드 접속 실패: %s", REDACTOR.redact(_explain(exc)))
            return False
        return self._ready.is_set()

    async def run_forever(self) -> None:
        """접속해서 끊길 때까지 돈다. 토큰이 틀렸거나 권한(Intent)이 꺼져 있으면 까닭을 남기고 예외를 그대로 올린다."""
        self._client = self._build_client()
        try:
            await self._client.start(self._token)
        except Exception as exc:
            log.error("디스코드 다리가 멈췄습니다: %s", REDACTOR.redact(_explain(exc)))
            raise

    async def disconnect(self) -> None:
        if self._client is not None and not self._client.is_closed():
            await self._client.close()

    # ── 들어오는 말 ───────────────────────────────────────────────────────────

    def _bot_id(self) -> str:
        user = getattr(self._client, "user", None)
        return str(getattr(user, "id", "") or "")

    @staticmethod
    def _kind(channel: Any) -> str:
        import discord

        if isinstance(channel, discord.DMChannel):
            return "dm"
        if isinstance(channel, discord.Thread):
            return "thread"
        return "channel"

    async def _on_discord_message(self, message: Any) -> None:
        bot_id = self._bot_id()
        content = str(getattr(message, "content", "") or "")
        inbound = Inbound(
            author_id=str(message.author.id),
            author_is_bot=bool(getattr(message.author, "bot", False)),
            content=content,
            channel_id=str(message.channel.id),
            channel_kind=self._kind(message.channel),
            message_id=str(message.id),
            mentions_bot=bool(bot_id) and (any(str(m.id) == bot_id for m in message.mentions)
                                           or f"<@{bot_id}>" in content or f"<@!{bot_id}>" in content),
            author_name=str(getattr(message.author, "display_name", "") or ""),
            author_username=str(getattr(message.author, "name", "") or ""),
        )
        decided = route(inbound, bot_id=bot_id, policy=self.policy, sessions=self.sessions,
                        free_channels=self.free_channels)
        if decided is None:
            return
        if decided.action == "request":
            await self._on_access_request(inbound, decided)
            return
        chat_id, key, kind = inbound.channel_id, decided.session_key, inbound.channel_kind
        if decided.needs_thread:
            thread = await self._open_thread(message, decided.text)
            if thread is not None:
                chat_id = key = str(thread.id)
                kind = "thread"
                self.sessions.add_thread(chat_id)
        await self.handle_message(MessageEvent(
            text=decided.text, chat_id=chat_id, user_id=inbound.author_id, session_key=key,
            message_id=inbound.message_id, origin_chat_id=inbound.channel_id, chat_type=kind,
            user_name=inbound.author_name, lang=detect_lang(decided.text), raw=message,
        ))

    async def _on_access_request(self, inbound: Inbound, decided: Route) -> None:
        if self._access_handler is None:
            return
        try:
            await self._access_handler(MessageEvent(
                text=decided.text, chat_id=inbound.channel_id, user_id=inbound.author_id, session_key=decided.session_key,
                message_id=inbound.message_id, origin_chat_id=inbound.channel_id, chat_type=inbound.channel_kind,
                user_name=inbound.author_name, user_handle=inbound.author_username, lang=detect_lang(decided.text),
            ))
        except Exception as exc:  # noqa: BLE001 — 요청 기록이 넘어져도 다리는 계속 돈다
            log.warning("허용 요청을 남기지 못했습니다: %s", REDACTOR.redact(type(exc).__name__))

    async def _open_thread(self, message: Any, text: str) -> Any:
        """멘션한 메시지에서 스레드를 연다. 못 열면(권한 · 포럼 등) 채널에서 그대로 답한다 — 일을 버리지 않는다."""
        name = thread_name(text)
        try:
            return await message.create_thread(name=name, auto_archive_duration=1440)
        except Exception as exc:  # noqa: BLE001
            log.warning("스레드를 만들지 못해 채널에서 답합니다: %s", REDACTOR.redact(exc))
            return None

    def _slash_event(self, interaction: Any, text: str) -> MessageEvent | None:
        user_id = str(interaction.user.id)
        if not self.policy.allows(user_id):
            return None  # 기본 거부 — 답하지 않는다(디스코드가 「응답 없음」을 보여 준다)
        channel = interaction.channel
        kind = self._kind(channel) if channel is not None else "dm"
        chat_id = str(getattr(channel, "id", "") or interaction.channel_id or "")
        locale = str(getattr(interaction, "locale", "") or "")
        return MessageEvent(text=text, chat_id=chat_id, user_id=user_id,
                            session_key=session_key_for(kind, user_id, chat_id), chat_type=kind,
                            lang="ko" if locale.startswith("ko") else "en")

    async def _on_slash(self, command: str, interaction: Any) -> None:
        event = self._slash_event(interaction, f"/{command}")
        if event is None:
            return
        reply = await self._command_handler(command, event) if self._command_handler else ""
        await interaction.response.send_message(reply or "-", ephemeral=True)

    async def _on_model_slash(self, interaction: Any, value: str) -> None:
        event = self._slash_event(interaction, f"/model {value}")
        if event is None or self._model_runner is None:
            return
        reply = await self._model_runner.model_command(value, event)
        await interaction.response.send_message(reply or "-", ephemeral=True)

    async def _model_choices(self, interaction: Any, current: str) -> list[tuple[str, str]]:
        event = self._slash_event(interaction, "/model")
        if event is None or self._model_runner is None:
            return []   # 허용 목록 밖 사람에게는 별명 표도 안 보인다
        table = await self._model_runner.backend.model_aliases()
        return self._model_runner.model_choices(current, list((table or {}).get("aliases") or []), event.lang)

    # ── 나가는 말 ─────────────────────────────────────────────────────────────

    async def _channel(self, chat_id: str) -> Any:
        channel = self._client.get_channel(int(chat_id))
        return channel if channel is not None else await self._client.fetch_channel(int(chat_id))

    async def send(self, chat_id: str, content: str, reply_to: Optional[str] = None,
                   metadata: Optional[dict[str, Any]] = None) -> SendResult:
        import discord

        try:
            channel = await self._channel(chat_id)
            kwargs: dict[str, Any] = {"content": REDACTOR.redact(content)[:DISCORD_MAX_MESSAGE],
                                      "allowed_mentions": discord.AllowedMentions.none()}
            if reply_to:
                kwargs["reference"] = discord.MessageReference(message_id=int(reply_to), channel_id=int(chat_id),
                                                               fail_if_not_exists=False)
                kwargs["mention_author"] = False
            try:
                sent = await channel.send(**kwargs)
            except discord.HTTPException:
                if "reference" not in kwargs:
                    raise
                # 답장 대상이 다른 자리(스레드를 열기 전 채널 메시지)면 참조 없이 다시 보낸다.
                kwargs.pop("reference")
                kwargs.pop("mention_author", None)
                sent = await channel.send(**kwargs)
            return SendResult(success=True, message_id=str(sent.id))
        except Exception as exc:  # noqa: BLE001
            log.warning("보내기 실패: %s", REDACTOR.redact(exc))
            return SendResult(success=False, error=REDACTOR.redact(exc))

    async def edit_message(self, chat_id: str, message_id: str, content: str) -> SendResult:
        try:
            channel = await self._channel(chat_id)
            await channel.get_partial_message(int(message_id)).edit(content=REDACTOR.redact(content)[:DISCORD_MAX_MESSAGE])
            return SendResult(success=True, message_id=message_id)
        except Exception as exc:  # noqa: BLE001
            return SendResult(success=False, error=REDACTOR.redact(exc))

    async def send_typing(self, chat_id: str) -> None:
        try:
            channel = await self._channel(chat_id)
            await channel.typing()   # 한 번 보내면 약 10초 간다
        except Exception:  # noqa: BLE001, S110 — 입력 중 표시는 덤이다
            pass

    async def send_document(self, chat_id: str, file_path: str, caption: Optional[str] = None,
                            file_name: Optional[str] = None, reply_to: Optional[str] = None) -> SendResult:
        import discord

        path = Path(file_path)
        try:
            size = path.stat().st_size
        except OSError as exc:
            return SendResult(success=False, error=type(exc).__name__)
        if size > self.max_upload_bytes:
            return SendResult(success=False, error="too_large")
        try:
            channel = await self._channel(chat_id)
            sent = await channel.send(content=REDACTOR.redact(caption)[:DISCORD_MAX_MESSAGE] if caption else None,
                                      file=discord.File(str(path), filename=file_name or path.name),
                                      allowed_mentions=discord.AllowedMentions.none())
            return SendResult(success=True, message_id=str(sent.id))
        except Exception as exc:  # noqa: BLE001
            log.warning("파일 올리기 실패(%s): %s", path.name, REDACTOR.redact(exc))
            return SendResult(success=False, error=REDACTOR.redact(exc))

    async def add_reaction(self, chat_id: str, message_id: str, emoji: str) -> bool:
        try:
            channel = await self._channel(chat_id)
            await channel.get_partial_message(int(message_id)).add_reaction(emoji)
            return True
        except Exception:  # noqa: BLE001
            return False

    async def remove_reaction(self, chat_id: str, message_id: str, emoji: str) -> bool:
        try:
            channel = await self._channel(chat_id)
            await channel.get_partial_message(int(message_id)).remove_reaction(emoji, self._client.user)
            return True
        except Exception:  # noqa: BLE001
            return False

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        channel = await self._channel(chat_id)
        kind = self._kind(channel)
        return {"name": str(getattr(channel, "name", "") or "DM"), "type": "dm" if kind == "dm" else "channel"}


def _everywhere(command: Any) -> Any:
    """★ 2026-10-18: 서버 설치 · 사용자 설치 둘 다, 서버 · DM · 그룹 DM 어디서나 명령이 보이게 한다.
    사용자 설치(서버 없이 내 계정에 앱 설치)로 쓰는 사람은 서버가 0곳이어도 정상이다."""
    from discord import app_commands

    command = app_commands.allowed_installs(guilds=True, users=True)(command)
    return app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)(command)


def app_commands_describe(**descriptions: str) -> Callable[[Any], Any]:
    """`app_commands.describe` — discord.py 가 없으면 아무것도 안 한다(이 파일은 discord.py 없이 import 된다)."""
    def wrap(func: Any) -> Any:
        try:
            from discord import app_commands
        except ImportError:
            return func
        return app_commands.describe(**descriptions)(func)

    return wrap


def _explain(exc: BaseException | None) -> str:
    """접속이 실패한 까닭을 사람이 할 일로 — 토큰 · Intent 는 포털에서 고친다."""
    name = type(exc).__name__ if exc else ""
    if name == "LoginFailure":
        return "봇 토큰이 틀렸습니다 — `python -m alture_jarvis.messaging setup` 을 다시 돌려 주세요."
    if name == "PrivilegedIntentsRequired":
        return ("Message Content Intent 가 꺼져 있습니다 — 디스코드 개발자 포털 → 내 앱 → Bot → "
                "Privileged Gateway Intents → Message Content Intent 를 켜고 저장해 주세요.")
    return f"{name}: {exc}" if exc else "알 수 없는 까닭"
