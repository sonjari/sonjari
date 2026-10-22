"""메신저 다리의 **플랫폼 중립** 부분 — 어댑터 틀 · 들어온 말 · 허용 목록 · 대화 열쇠 · 긴 글 나누기 · 비밀 가리기.

## 왜 플랫폼 중립으로 나눴나 (2026-10-17)

지금은 디스코드 하나지만, 텔레그램 · 슬랙이 붙어도 **규칙은 같아야 한다**: 모르는 사람은 조용히 버리고,
비밀은 기록에 안 남기고, 승인은 PC 앱에서만. 규칙을 어댑터마다 다시 쓰면 한 곳에서 샌다(사고 Q 와 같은 모양).
그래서 규칙은 여기, 플랫폼의 손발(보내기 · 고치기 · 반응)만 어댑터에 둔다.

## 출처 (MIT)

어댑터 틀(`BasePlatformAdapter` 의 connect · send · edit_message · send_typing · send_document ·
on_processing_start/complete · handle_message)과 `truncate_message` · `fence_state_after` 는
Hermes Agent 의 `gateway/platforms/base.py` · `gateway/platforms/helpers.py` 를 줄여 옮겼다.

    Copyright (c) 2025 Nous Research — MIT License
    https://github.com/NousResearch/hermes-agent

    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
    associated documentation files (the "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the
    following conditions: The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
    KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
    PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
    CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF
    OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional

from ..brand import NAME, NAME_KO

log = logging.getLogger("sonjari.messaging")

__all__ = [
    "SendResult", "MessageEvent", "BasePlatformAdapter", "AccessPolicy", "SessionMap", "Redactor", "REDACTOR",
    "RedactingFilter", "truncate_message", "fence_state_after", "cap_chunks", "detect_lang", "say",
    "parse_command", "EYES", "DONE", "FAILED",
]

EYES, DONE, FAILED = "👀", "✅", "❌"


# ── 비밀 가리기 ────────────────────────────────────────────────────────────────

#: 디스코드 봇 토큰 모양 — 「사용자 ID 의 base64 . 6자 안팎 . 27자 넘는 서명」. JWT 같은 a.b.c 도 같이 걸리지만
#: 기록에서는 지나치게 가리는 쪽이 낫다(새는 것보다).
_DISCORD_TOKEN = re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{20,30}\.[A-Za-z0-9_\-]{5,8}\.[A-Za-z0-9_\-]{25,45}(?![A-Za-z0-9_\-])")
#: `Authorization: Bot …` 머리 — 라이브러리가 요청을 기록에 찍을 때 이 모양으로 나온다.
_AUTH_HEADER = re.compile(r"(?i)\b(Bot|Bearer)\s+[A-Za-z0-9_\-.]{20,}")
_MASK = "[가림]"


class Redactor:
    """글에서 봇 토큰 · 연결 토큰을 가린다.

    ★ 2026-10-17: 토큰은 **값으로도, 모양으로도** 가린다. 값만 보면 사용자가 다른 봇 토큰을 실수로 붙여 넣은 글이
    새고, 모양만 보면 우리 연결 토큰(무작위 43자, 점 없음)이 샌다. 둘 다 한다.
    """

    def __init__(self) -> None:
        self._secrets: set[str] = set()

    def register(self, secret: str) -> None:
        value = str(secret or "").strip()
        if len(value) >= 8:  # 짧은 값은 평범한 낱말까지 지운다
            self._secrets.add(value)

    def redact(self, text: Any) -> str:
        out = str(text if text is not None else "")
        for secret in sorted(self._secrets, key=len, reverse=True):
            out = out.replace(secret, _MASK)
        out = _AUTH_HEADER.sub(lambda m: f"{m.group(1)} {_MASK}", out)
        return _DISCORD_TOKEN.sub(_MASK, out)


#: 프로세스 하나에 하나 — 토큰을 읽는 자리가 여기에 등록한다.
REDACTOR = Redactor()


class RedactingFilter(logging.Filter):
    """기록 처리기(handler)에 붙여 **모든** 기록(우리 것 · discord.py 것)에서 비밀을 가린다."""

    def __init__(self, redactor: Redactor | None = None) -> None:
        super().__init__()
        self.redactor = redactor or REDACTOR

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — 형식이 깨진 기록도 내보내되 원문 인자는 버린다
            message = str(record.msg)
        clean = self.redactor.redact(message)
        if clean != message or record.args:
            record.msg, record.args = clean, ()
        if record.exc_info and not record.exc_text:
            # 예외 문장에도 토큰이 실릴 수 있다(요청 머리를 찍는 라이브러리) — 미리 형식을 만들어 가린다.
            record.exc_text = self.redactor.redact(logging.Formatter().formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = self.redactor.redact(record.exc_text)
        return True


# ── 말(한국어 · 영어) ──────────────────────────────────────────────────────────

def detect_lang(text: str) -> str:
    """보낸 말에 한글이 하나라도 있으면 한국어, 한글 없이 로마자만 있으면 영어.

    명령(`/stop`)만 있으면 말이 없으니 한국어 — 그 대화의 앞선 말 언어는 `TaskRunner` 가 기억해 쓴다.
    """
    if parse_command(text):
        text = text.strip().split(maxsplit=1)[1] if len(text.strip().split(maxsplit=1)) > 1 else ""
    hangul = sum(1 for ch in text if "가" <= ch <= "힣" or "ㄱ" <= ch <= "ㆎ")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return "en" if latin and not hangul else "ko"


_TEXTS: dict[str, dict[str, str]] = {
    "ko": {
        "accepted": f"맡았습니다 — PC 의 {NAME_KO}가 일을 시작합니다.",
        "queued": "차례를 기다리는 중입니다(PC 에서 하던 일이 먼저 끝나야 합니다).",
        "working": "일하는 중",
        "step": "{n}걸음",
        "waiting_approval": f"⏸ PC 앱 화면에서 승인을 기다리고 있습니다. 디스코드에서는 승인할 수 없습니다 — PC 앞에서 {NAME_KO} 창의 승인 카드를 눌러 주세요.",
        "waiting_question": "{NAME_KO}가 묻는 말: 「{question}」 — PC 앱의 질문 카드에서 골라 주세요.",
        "waiting_person": f"⏸ PC 앞에서 사람이 할 일이 있어 멈췄습니다(로그인 · 확인 등). PC 의 {NAME_KO} 창을 봐 주세요.",
        "waiting_short": "PC 앱에서 기다리는 중",
        "done_label": "끝났습니다",
        "failed_label": "실패했습니다",
        "cancelled_label": "멈췄습니다",
        "empty_answer": "(답이 비어 있습니다 — PC 앱에서 결과를 확인해 주세요.)",
        "failed": "실패했습니다: {error}",
        "cancelled": "일을 멈췄습니다.",
        "busy": "이 대화에서 앞의 일이 아직 진행 중입니다. 끝난 뒤 다시 보내거나 /stop 으로 멈춰 주세요.",
        "offline": f"PC 의 {NAME_KO}에 연결하지 못했습니다 — PC 에서 {NAME_KO}가 켜져 있는지 확인해 주세요.",
        "unauthorized": f"PC 의 {NAME_KO}가 이 연결을 받지 않았습니다(연결 토큰이 맞지 않습니다). PC 에서 다리를 다시 켜 주세요.",
        "rejected": f"{NAME_KO}가 이 일을 받지 못했습니다: {{error}}",
        "lost": f"작업 도중 PC 의 {NAME_KO}와 연결이 끊겼습니다. 결과는 PC 앱에서 확인해 주세요.",
        "new": "새 대화를 시작합니다. 앞의 대화 내용은 이어지지 않습니다.",
        "stop_none": "지금 멈출 일이 없습니다.",
        "stop_ok": "멈추라고 전했습니다.",
        "stop_failed": "멈추지 못했습니다(이미 끝났을 수 있습니다).",
        "status_idle": "지금 이 대화에서 진행 중인 일이 없습니다.",
        "status_running": "진행 중: {label} · {minutes}분째",
        "truncated": "…답이 길어 {kept}개까지만 보냈습니다(남은 {dropped}자는 PC 앱에서 보세요).",
        "showcase_caption": "📸 답이 기댄 페이지 — {title}\n<{url}>",
        "file_too_big": "파일이 커서 올리지 못했습니다: {name} ({size_mb:.1f}MB, 한도 {limit_mb:.0f}MB) — PC 에 있습니다.",
        "file_missing": "만든 파일을 찾지 못했습니다: {name}",
        "file_failed": "파일을 올리지 못했습니다: {name}",
        "review_numbers": "⚠ 도구가 준 적 없는 숫자 {n}개가 답에 있습니다 — 사실로 쓰기 전에 확인해 주세요.",
        "review_no_tools": "⚠ 이번 답은 도구를 쓰지 않고 쓴 답입니다 — 화면 · 파일을 실제로 확인한 답이 아닙니다.",
        "receipt": "출처 {sources}곳 · {line}",
        "model_loading": "{alias} 모델을 올리는 중(처음 한 번 20초쯤)",
        "model_set": "이 대화는 이제 「{alias}」 모델({tag})로 합니다. 판 하나만 바꾸려면 글 앞에 @별명 을 붙이세요.",
        "model_pc": "이 대화는 이제 PC 와 같은 모델로 합니다.",
        "model_unknown": "「{alias}」라는 모델 별명이 없습니다. 있는 것: {names}",
        "model_none": f"모델 별명 표를 가져오지 못했습니다 — PC 의 {NAME_KO}가 켜져 있는지 봐 주세요.",
        "model_pc_choice": "PC 와 같음",
        "model_prefix_empty": "「@{alias} 할 일」처럼 별명 뒤에 할 일을 적어 주세요.",
        "access_pending": "이 봇의 주인이 PC 에서 허용하면 답합니다.",
        "access_allowed": "허용됐습니다. 이제 말씀하시면 됩니다.",
    },
    "en": {
        "accepted": f"Got it — {NAME} on your PC is starting.",
        "queued": "Waiting for its turn (the PC finishes its current task first).",
        "working": "Working",
        "step": "step {n}",
        "waiting_approval": f"⏸ Waiting for approval in the PC app. Approvals can't be given from Discord — please use the approval card in the {NAME} window on the PC.",
        "waiting_question": "{NAME} is asking: \"{question}\" — please answer on the question card in the PC app.",
        "waiting_person": f"⏸ Paused for something only a person at the PC can do (sign-in, a check). Please look at the {NAME} window on the PC.",
        "waiting_short": "Waiting in the PC app",
        "done_label": "Done",
        "failed_label": "Failed",
        "cancelled_label": "Stopped",
        "empty_answer": "(The answer is empty — please check the result in the PC app.)",
        "failed": "Failed: {error}",
        "cancelled": "Stopped the task.",
        "busy": "The previous task in this conversation is still running. Send again when it ends, or /stop it.",
        "offline": f"Couldn't reach {NAME} on your PC — please check that {NAME} is running there.",
        "unauthorized": f"{NAME} on your PC refused this connection (the control token doesn't match). Please restart the bridge on the PC.",
        "rejected": f"{NAME} couldn't take this task: {{error}}",
        "lost": f"Lost the connection to {NAME} on your PC mid-task. Please check the result in the PC app.",
        "new": "Starting a fresh conversation. The earlier messages won't carry over.",
        "stop_none": "Nothing is running to stop.",
        "stop_ok": "Asked it to stop.",
        "stop_failed": "Couldn't stop it (it may have already finished).",
        "status_idle": "Nothing is running in this conversation.",
        "status_running": "Running: {label} · {minutes} min so far",
        "truncated": "…The answer was long, so only {kept} messages were sent ({dropped} more characters are in the PC app).",
        "showcase_caption": "📸 The page this answer leaned on — {title}\n<{url}>",
        "file_too_big": "Couldn't upload a file that is too large: {name} ({size_mb:.1f} MB, limit {limit_mb:.0f} MB) — it is on the PC.",
        "file_missing": "Couldn't find the file it made: {name}",
        "file_failed": "Couldn't upload the file: {name}",
        "review_numbers": "⚠ The answer has {n} numbers no tool gave — please check them before relying on them.",
        "review_no_tools": "⚠ This answer was written without using any tool — it didn't actually check a screen or a file.",
        "receipt": "{sources} sources · {refined} redacted",
        "model_loading": "Loading the {alias} model (about 20 seconds the first time)",
        "model_set": "This conversation now uses the “{alias}” model ({tag}). To switch for one task only, start the message with @alias.",
        "model_pc": "This conversation now uses the same model as the PC.",
        "model_unknown": "There is no model alias “{alias}”. Available: {names}",
        "model_none": f"Couldn't get the model alias list — please check that {NAME} is running on the PC.",
        "model_pc_choice": "Same as PC",
        "model_prefix_empty": "Please put the task after the alias, like “@{alias} your task”.",
        "access_pending": "This bot will answer once its owner allows you on their PC.",
        "access_allowed": "You've been allowed. Go ahead and tell me what you need.",
    },
}


def say(key: str, lang: str = "ko", **values: Any) -> str:
    table = _TEXTS.get(lang) or _TEXTS["ko"]
    template = table.get(key) or _TEXTS["ko"][key]
    return template.format(NAME=NAME, NAME_KO=NAME_KO, **values)


# ── 명령 ───────────────────────────────────────────────────────────────────────

COMMANDS = ("new", "stop", "status")
#: `/모델` 에서 「PC 와 같음」을 고른 대화 — 디스코드 기본 모델이 있어도 PC 모델로 돈다.
PC_SAME = "-"


def parse_command(text: str) -> str | None:
    """`/new` · `/stop` · `/status` (뒤에 붙은 말은 무시). 다른 글은 None — 그대로 일로 맡긴다."""
    head = str(text or "").strip().split(maxsplit=1)
    if not head or not head[0].startswith("/"):
        return None
    name = head[0][1:].lower()
    return name if name in COMMANDS else None


# ── 들어온 말 · 보낸 결과 · 어댑터 틀 (Hermes `BasePlatformAdapter` 를 줄여 옮김) ───────────────

@dataclass
class SendResult:
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    retryable: bool = False


@dataclass
class MessageEvent:
    """플랫폼이 무엇이든 같은 모양의 「들어온 말」."""

    text: str
    chat_id: str                 # 답을 보낼 자리(채널에서 스레드를 만들었으면 그 스레드)
    user_id: str
    session_key: str             # 우리 대화(session_id)를 가르는 열쇠 — `SessionMap.session_id`
    message_id: str = ""         # 👀 · ✅ 를 달 원래 메시지
    origin_chat_id: str = ""     # 원래 메시지가 있는 자리(스레드를 만들었으면 바깥 채널)
    chat_type: str = "dm"        # dm | thread | channel
    user_name: str = ""
    lang: str = "ko"
    user_handle: str = ""        # 디스코드 사용자명(@이름) — 허용 요청 카드에 보인다
    raw: Any = None

    @property
    def reaction_chat_id(self) -> str:
        return self.origin_chat_id or self.chat_id


MessageHandler = Callable[[MessageEvent], Awaitable[None]]


class BasePlatformAdapter(ABC):
    """플랫폼 어댑터의 틀. 필수는 connect · disconnect · send · get_chat_info, 나머지는 못 하면 조용히 넘긴다."""

    name = "base"
    max_message_length = 2000
    #: 답 하나를 몇 개의 메시지까지 나눠 보내나. Hermes #86581: 6만 자 답이 31개 메시지로 채널을 덮었다.
    max_split_messages = 8
    max_upload_bytes = 10 * 1024 * 1024

    def __init__(self) -> None:
        self._handler: MessageHandler | None = None
        self._tasks: set[asyncio.Task] = set()

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def handle_message(self, event: MessageEvent) -> asyncio.Task | None:
        """받은 말을 **뒤에서** 처리한다 — 일 하나가 몇 분 걸려도 다음 말(/stop)이 들어올 수 있게."""
        if self._handler is None:
            log.error("[%s] 처리기가 없어 들어온 말을 버렸습니다", self.name)
            return None
        task = asyncio.create_task(self._run_handler(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _run_handler(self, event: MessageEvent) -> None:
        try:
            assert self._handler is not None
            await self._handler(event)
        except Exception:  # noqa: BLE001 — 한 판의 실패가 다리를 꺾지 않게
            log.exception("[%s] 들어온 말을 처리하다 실패했습니다", self.name)

    @abstractmethod
    async def connect(self) -> bool: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def send(self, chat_id: str, content: str, reply_to: Optional[str] = None,
                   metadata: Optional[dict[str, Any]] = None) -> SendResult: ...

    @abstractmethod
    async def get_chat_info(self, chat_id: str) -> dict[str, Any]: ...

    async def edit_message(self, chat_id: str, message_id: str, content: str) -> SendResult:
        return SendResult(success=False, error="not_supported")

    async def send_typing(self, chat_id: str) -> None:
        return None

    async def send_document(self, chat_id: str, file_path: str, caption: Optional[str] = None,
                            file_name: Optional[str] = None, reply_to: Optional[str] = None) -> SendResult:
        return SendResult(success=False, error="not_supported")

    async def add_reaction(self, chat_id: str, message_id: str, emoji: str) -> bool:
        return False

    async def remove_reaction(self, chat_id: str, message_id: str, emoji: str) -> bool:
        return False

    async def on_processing_start(self, event: MessageEvent) -> None:
        if event.message_id:
            await self.add_reaction(event.reaction_chat_id, event.message_id, EYES)

    async def on_processing_complete(self, event: MessageEvent, ok: bool | None) -> None:
        """끝: 👀 를 떼고 ✅/❌. 사람이 멈춘 판(ok=None)은 떼기만 한다 — 실패가 아니다(Hermes 와 같은 규칙)."""
        if not event.message_id:
            return
        await self.remove_reaction(event.reaction_chat_id, event.message_id, EYES)
        if ok is not None:
            await self.add_reaction(event.reaction_chat_id, event.message_id, DONE if ok else FAILED)

    def render(self, content: str) -> str:
        """이 메신저가 못 그리는 마크다운을 바꾼다. 기본은 표 → 목록(`markdown.tables_to_lists` — 표를 그리는 메신저는 덮어쓴다)."""
        from .markdown import tables_to_lists

        return tables_to_lists(content)

    def split_message(self, content: str, lang: str = "ko") -> list[str]:
        return cap_chunks(truncate_message(self.render(content), self.max_message_length), self.max_split_messages,
                          lang=lang, max_length=self.max_message_length)


# ── 긴 글 나누기 (Hermes `truncate_message` · `fence_state_after`, MIT) ────────────────────────

def fence_state_after(text: str, in_code: bool = False, lang: str = "") -> tuple[bool, str]:
    """줄마다 ``` 를 세어 끝난 뒤 코드 칸 안인지와 그 언어 표시를 돌려준다."""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            tag = stripped[3:].split()
            in_code, lang = (False, "") if in_code else (True, tag[0] if tag else "")
    return in_code, lang


def truncate_message(content: str, max_length: int = 2000) -> list[str]:
    """긴 글을 `max_length` 이하 조각으로. 코드 칸 한가운데서 자르면 그 조각 끝에서 닫고 다음 조각에서 같은 언어로 다시 연다.
    여러 조각이면 끝에 ` (1/3)` 을 붙인다."""
    if len(content) <= max_length:
        return [content]
    indicator_reserve = 10   # " (XX/XX)"
    fence_close = "\n```"
    chunks: list[str] = []
    remaining = content
    carry_lang: Optional[str] = None
    while remaining:
        prefix = f"```{carry_lang}\n" if carry_lang is not None else ""
        headroom = max_length - indicator_reserve - len(prefix) - len(fence_close)
        if headroom < 1:
            headroom = max(1, max_length // 2)
        if len(prefix) + len(remaining) <= max_length - indicator_reserve:
            final_chunk = prefix + remaining
            if carry_lang is not None and fence_state_after(remaining, True, carry_lang)[0]:
                final_chunk += fence_close
            chunks.append(final_chunk)
            break
        region = remaining[:headroom]
        split_at = region.rfind("\n")
        if split_at < headroom // 2:
            split_at = region.rfind(" ")
        if split_at < 1:
            split_at = max(1, headroom)
        candidate = remaining[:split_at]
        # 인라인 코드(`…`) 가운데서 자르지 않는다 — 짝 없는 백틱이 남은 글을 통째로 코드로 만든다.
        if (candidate.count("`") - candidate.count("\\`")) % 2 == 1:
            last_bt = candidate.rfind("`")
            if last_bt > 0:
                safe_split = max(candidate.rfind(" ", 0, last_bt), candidate.rfind("\n", 0, last_bt))
                if safe_split > headroom // 4:
                    split_at = safe_split
        chunk_body = remaining[:split_at]
        remaining = remaining[split_at:].lstrip()
        in_code, lang = fence_state_after(chunk_body, carry_lang is not None, carry_lang or "")
        carry_lang = lang if in_code else None
        chunks.append(prefix + chunk_body + (fence_close if in_code else ""))
    if len(chunks) > 1:
        chunks = [f"{chunk} ({i + 1}/{len(chunks)})" for i, chunk in enumerate(chunks)]
    return chunks


def cap_chunks(chunks: list[str], max_messages: int, *, lang: str = "ko", max_length: int = 2000) -> list[str]:
    """조각이 너무 많으면 앞의 `max_messages - 1` 개와 알림 하나만. 전문은 PC 앱(대화 기록)에 남아 있다."""
    if len(chunks) <= max_messages:
        return chunks
    kept = chunks[: max_messages - 1]
    dropped = sum(len(c) for c in chunks[max_messages - 1:])
    return kept + [say("truncated", lang, kept=len(kept), dropped=dropped)[:max_length]]


# ── 허용 목록 (기본은 거부) ────────────────────────────────────────────────────

class AccessPolicy:
    """허용 목록에 있는 사용자 ID 만 받는다. **비어 있으면 아무도 안 받는다**(기본 거부).

    ★ 2026-10-17: 모르는 보낸이는 답 없이 버린다 — 「권한이 없습니다」라고 답하면 봇이 살아 있고 무엇을 하는지 알려 준다.
      대신 PC 쪽 기록에 그 ID 를 남겨 주인이 들일 수 있게 한다. 같은 ID 는 `log_every_sec` 에 한 번만(스팸이 기록을 덮지 않게).
    """

    _MEMORY_CAP = 1000

    def __init__(self, allowed_user_ids: Iterable[str], *, log_every_sec: float = 3600.0,
                 clock: Callable[[], float] = time.monotonic,
                 refresh: Callable[[], Iterable[str]] | None = None, refresh_every_sec: float = 1.0) -> None:
        self.allowed = {str(uid).strip() for uid in allowed_user_ids if str(uid).strip()}
        self._log_every = log_every_sec
        self._clock = clock
        self._last_logged: dict[str, float] = {}
        #: ★ 2026-10-18: PC 의 「허용」 버튼이 설정 파일에 넣은 사람을 다리를 다시 켜지 않고 받는다. 모르는 보낸이가 올 때만
        #:   파일을 다시 읽는다(따로 띄운 다리도 같은 파일을 보니 같은 길로 반영된다). 넣기만 한다 — 빼기는 다리를 다시 켤 때.
        self._refresh = refresh
        self._refresh_every = refresh_every_sec
        self._refreshed_at = float("-inf")

    def allow(self, user_id: str) -> None:
        """PC 에서 허용한 사람을 바로 받는다(본체 안 다리 — `service.allow_request`)."""
        uid = str(user_id or "").strip()
        if uid:
            self.allowed.add(uid)

    def allows(self, user_id: str) -> bool:
        uid = str(user_id or "").strip()
        if uid and uid in self.allowed:
            return True
        if uid and self._refresh is not None and self._clock() - self._refreshed_at >= self._refresh_every:
            self._refreshed_at = self._clock()
            try:
                self.allowed |= {str(item).strip() for item in self._refresh() or () if str(item).strip()}
            except Exception:  # noqa: BLE001 — 설정 파일을 못 읽으면 있던 목록으로
                pass
            if uid in self.allowed:
                return True
        self._note_unknown(uid)
        return False

    def _note_unknown(self, uid: str) -> None:
        now = self._clock()
        last = self._last_logged.get(uid)
        if last is not None and now - last < self._log_every:
            return
        if len(self._last_logged) >= self._MEMORY_CAP:
            self._last_logged.clear()
        self._last_logged[uid] = now
        log.warning("허용 목록에 없는 보낸이(%s)의 메시지를 버렸습니다. 들이려면 setup 을 다시 돌리거나 "
                    "설정 파일의 allowed_user_ids 에 넣으세요.", uid or "?")


# ── 대화 열쇠 → 우리 session_id ─────────────────────────────────────────────────

def session_key_for(chat_type: str, user_id: str, chat_id: str) -> str:
    """DM 은 사람마다 하나, 서버에서는 스레드(또는 스레드를 못 만든 채널)마다 하나."""
    return f"dm-{user_id}" if chat_type == "dm" else str(chat_id)


class SessionMap:
    """대화 열쇠 → 손자리 `session_id`, 우리가 만든 스레드 목록, 지금 도는 일.

    ★ 2026-10-17: `/new` 는 열쇠의 「몇 번째 대화」만 올린다(`discord-<열쇠>` → `discord-<열쇠>-2`). 앞 대화는 PC 앱에
      그대로 남는다 — 지우지 않는다. 몇 번째인지와 스레드 목록은 파일에 남겨 다리를 다시 켜도 이어진다(비밀 없음).
    """

    def __init__(self, path: Path | None = None, *, prefix: str = "discord") -> None:
        self.path = path
        self.prefix = prefix
        self._generation: dict[str, int] = {}
        self._threads: set[str] = set()
        self._active: dict[str, dict[str, Any]] = {}
        #: 대화 열쇠 → `/모델` 로 고른 별명(`PC_SAME` = PC 와 같음). `/new` 로도 지우지 않는다 — 대화방의 버릇이다.
        self._models: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("대화 상태 파일을 읽지 못해 새로 시작합니다: %s", self.path)
            return
        self._generation = {str(k): int(v) for k, v in (data.get("generations") or {}).items()}
        self._threads = {str(t) for t in data.get("bot_threads") or []}
        self._models = {str(k): str(v) for k, v in (data.get("models") or {}).items() if str(v).strip()}

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # 스레드 목록은 끝없이 늘지 않게 최근 500개만.
            threads = sorted(self._threads, key=lambda t: int(t) if t.isdigit() else 0)[-500:]
            self.path.write_text(json.dumps({"generations": self._generation, "bot_threads": threads,
                                             "models": self._models}, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            log.warning("대화 상태 파일을 쓰지 못했습니다: %s", self.path)

    def session_id(self, key: str) -> str:
        generation = self._generation.get(key, 1)
        base = f"{self.prefix}-{key}"
        return (base if generation <= 1 else f"{base}-{generation}")[:80]

    def reset(self, key: str) -> str:
        self._generation[key] = self._generation.get(key, 1) + 1
        self._save()
        return self.session_id(key)

    def model(self, key: str) -> str:
        return self._models.get(str(key), "")

    def set_model(self, key: str, alias: str) -> None:
        if alias:
            self._models[str(key)] = alias
        else:
            self._models.pop(str(key), None)
        self._save()

    def add_thread(self, thread_id: str) -> None:
        self._threads.add(str(thread_id))
        self._save()

    def is_bot_thread(self, thread_id: str) -> bool:
        return str(thread_id) in self._threads

    def set_active(self, key: str, job_id: str, user_id: str) -> None:
        self._active[key] = {"job_id": job_id, "user_id": str(user_id), "since": time.time()}

    def clear_active(self, key: str, job_id: str) -> None:
        if (self._active.get(key) or {}).get("job_id") == job_id:
            self._active.pop(key, None)

    def active(self, key: str) -> dict[str, Any] | None:
        return self._active.get(key)

    def active_for_user(self, user_id: str) -> tuple[str, dict[str, Any]] | None:
        """서버 채널에서 `/stop` 을 치면 그 사람이 시킨 가장 최근 일을 가리킨다(일은 스레드에서 돈다)."""
        mine = [(k, v) for k, v in self._active.items() if v.get("user_id") == str(user_id)]
        return max(mine, key=lambda kv: kv[1].get("since", 0)) if mine else None
