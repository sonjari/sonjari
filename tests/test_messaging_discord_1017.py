"""디스코드 다리(`alture_jarvis.messaging`) — 진짜 봇 토큰 없이 가짜로만 잰다 (2026-10-17).

붙드는 것:
- 기본 거부: 허용 목록이 비면 아무도, 모르는 보낸이는 답 없이 버리고 ID 는 한 번만 기록
- 대화 열쇠: DM = 사람마다 · 채널 = 멘션할 때만 + 스레드 · 우리 스레드는 멘션 없이 · /new 는 다음 번호
- 긴 답 나누기: 2000자 · 코드 칸 유지 · 8개 상한 뒤 알림
- 승인: PC 앱에서 기다린다고만 알리고, **디스코드 쪽에서 승인 문을 한 번도 부르지 않는다**
- 비밀 가리기: 봇 토큰 모양 · 연결 토큰 값 · 기록 처리기
- 본체 따라가기: 맡기기 몸통 · 진행 고쳐 쓰기 · 입력 중 · 답 · 파일(크기 확인) · 반응
- setup: 애플리케이션 ID 거절 · 초대 링크 권한 숫자 · 토큰은 자격 증명 저장소에만
- discord.py 없이 import 된다
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx
import pytest

from alture_jarvis.messaging.base import (
    AccessPolicy, BasePlatformAdapter, MessageEvent, Redactor, RedactingFilter, SendResult, SessionMap,
    detect_lang, fence_state_after, parse_command, truncate_message,
)
from alture_jarvis.messaging.bridge import ApprovalButtonBinder, SonjariBackend, TaskRunner
from alture_jarvis.messaging.credentials import TARGET, MemoryCredentialStore
from alture_jarvis.messaging.discord_adapter import DISCORD_UPLOAD_LIMIT_BYTES, Inbound, route, strip_mention
from alture_jarvis.messaging.discord_config import SETTINGS_FILE, DiscordSettings
from alture_jarvis.messaging.onboarding import INVITE_PERMISSIONS, invite_url, run_setup, token_shape_error

#: 진짜가 아닌, 모양만 봇 토큰인 값(사용자 ID base64 · 6자 · 서명 자리).
FAKE_BOT_TOKEN = ".".join(("MTEyMzQ1Njc4OTAxMjM0NTY3OA", "GaBcDe", "abcdefghijklmnopqrstuvwxyz0123456789AB"))  # 조각으로 둔다 — 한 덩어리면 깃허브 비밀 검사가 진짜 토큰으로 보고 올리기를 막는다(2026-10-18)
CONTROL_TOKEN = "control-token-for-tests-0123456789abcdef"
OWNER = "111111111111111111"
STRANGER = "999999999999999999"
BOT = "222222222222222222"


# ── 가짜 어댑터 ────────────────────────────────────────────────────────────────

class FakeAdapter(BasePlatformAdapter):
    name = "fake"

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple[str, str, Optional[str]]] = []
        self.edits: list[tuple[str, str, str]] = []
        self.typing: list[str] = []
        self.documents: list[str] = []
        self.reactions: list[tuple[str, str]] = []
        self._next = 100

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def send(self, chat_id: str, content: str, reply_to: Optional[str] = None,
                   metadata: Optional[dict[str, Any]] = None) -> SendResult:
        assert len(content) <= self.max_message_length
        self._next += 1
        self.sent.append((chat_id, content, reply_to))
        return SendResult(success=True, message_id=str(self._next))

    async def edit_message(self, chat_id: str, message_id: str, content: str) -> SendResult:
        self.edits.append((chat_id, message_id, content))
        return SendResult(success=True, message_id=message_id)

    async def send_typing(self, chat_id: str) -> None:
        self.typing.append(chat_id)

    async def send_document(self, chat_id: str, file_path: str, caption: Optional[str] = None,
                            file_name: Optional[str] = None, reply_to: Optional[str] = None) -> SendResult:
        self.documents.append(file_path)
        return SendResult(success=True, message_id="doc")

    async def add_reaction(self, chat_id: str, message_id: str, emoji: str) -> bool:
        self.reactions.append(("+", emoji))
        return True

    async def remove_reaction(self, chat_id: str, message_id: str, emoji: str) -> bool:
        self.reactions.append(("-", emoji))
        return True

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        return {"name": "fake", "type": "dm"}

    def texts(self) -> str:
        return "\n".join(content for _chat, content, _reply in self.sent)


# ── 가짜 본체 ──────────────────────────────────────────────────────────────────

class FakeBackend:
    """`/v1/*` 를 흉내 낸다. `statuses` 를 GET 마다 하나씩 넘기고, 끝 상태에서 머문다. 받은 요청을 전부 남긴다."""

    def __init__(self, statuses: list[str], *, answer: str = "끝났습니다.", files: list[str] | None = None,
                 question: str = "") -> None:
        self.statuses = list(statuses)
        self.answer = answer
        self.files = files or []
        self.question = question
        self.requests: list[httpx.Request] = []
        self.cancelled = False
        self.started = time.time()

    def _job(self) -> dict[str, Any]:
        status = "cancelled" if self.cancelled else (self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0])
        steps = [{"ok": True, "tool": "write_file", "evidence": {"output_paths": self.files}}] if self.files else [
            {"ok": True, "tool": "browser_open", "evidence": {}}]
        return {"id": "job-1", "status": status, "created_at": self.started, "started_at": self.started,
                "payload": {"prompt": "x", "origin": "mcp", "caller": "Discord"},
                "result": {"answer": self.answer, "agent_trace": {"steps": steps}} if status == "completed" else {},
                "error": "boom" if status == "failed" else ""}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/v1/chat":
            return httpx.Response(200, json={"id": "job-1", "status": "queued"})
        if request.method == "POST" and path == "/v1/jobs/job-1/cancel":
            self.cancelled = True
            return httpx.Response(200, json={"ok": True})
        if request.method == "GET" and path == "/v1/jobs/job-1":
            return httpx.Response(200, json=self._job())
        if request.method == "GET" and path == "/v1/jobs/job-1/live":
            return httpx.Response(200, json={"doing": "사람인 공고를 읽는 중", "step": 3})
        if request.method == "GET" and path == "/v1/approvals":
            rows = [{"job_id": "job-1", "tool_name": "ask_user", "target": {"question": self.question}}] if self.question else [
                {"job_id": "job-1", "tool_name": "gmail_send", "target": {}}]
            return httpx.Response(200, json=rows)
        if path == "/health":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"detail": "nope"})

    def backend(self) -> SonjariBackend:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return SonjariBackend("http://127.0.0.1:8091", CONTROL_TOKEN, client=client)

    def posts(self) -> list[str]:
        return [r.url.path for r in self.requests if r.method == "POST"]


async def _no_sleep(_sec: float) -> None:
    await asyncio.sleep(0)


def _runner(adapter: FakeAdapter, fake: FakeBackend, tmp_path: Path) -> TaskRunner:
    return TaskRunner(adapter, fake.backend(), SessionMap(tmp_path / "state.json"), poll_sec=0, typing_every=0,
                      sleep=_no_sleep)


def _event(text: str = "사람인에서 공고 3개 찾아 줘", **extra: Any) -> MessageEvent:
    values: dict[str, Any] = {"text": text, "chat_id": "500", "user_id": OWNER, "session_key": f"dm-{OWNER}",
                              "message_id": "42", "lang": detect_lang(text)}
    values.update(extra)
    return MessageEvent(**values)


# ── 기본 거부 ──────────────────────────────────────────────────────────────────

def test_an_empty_allowlist_lets_nobody_in() -> None:
    policy = AccessPolicy([])
    assert not policy.allows(OWNER)
    assert not policy.allows("")


def test_only_listed_ids_get_in_and_strangers_are_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    now = [0.0]
    policy = AccessPolicy([OWNER], log_every_sec=3600, clock=lambda: now[0])
    caplog.set_level(logging.WARNING, logger="sonjari.messaging")
    assert policy.allows(OWNER)
    for _ in range(5):
        assert not policy.allows(STRANGER)
    assert sum(STRANGER in r.getMessage() for r in caplog.records) == 1
    now[0] = 3601.0
    policy.allows(STRANGER)
    assert sum(STRANGER in r.getMessage() for r in caplog.records) == 2


def test_a_stranger_starts_no_task_only_an_access_request(tmp_path: Path) -> None:
    # ★ 2026-10-18 대표: 모르는 사람의 말은 「답 없이 버림」에서 「일은 안 하고 PC 에 허용 요청」으로 바뀌었다
    #   (`tests/test_discord_access_requests_1018.py`). 일이 되는 길(task · command)은 여전히 없다.
    sessions = SessionMap(tmp_path / "s.json")
    dm = Inbound(author_id=STRANGER, author_is_bot=False, content="hi", channel_id="7", channel_kind="dm")
    decided = route(dm, bot_id=BOT, policy=AccessPolicy([OWNER]), sessions=sessions)
    assert decided is not None and decided.action == "request"
    stop = Inbound(author_id=STRANGER, author_is_bot=False, content="/stop", channel_id="7", channel_kind="dm")
    assert route(stop, bot_id=BOT, policy=AccessPolicy([OWNER]), sessions=sessions).action == "request"
    # 봇에게 말을 걸지 않은 채널 글은 여전히 아무것도 아니다(요청도 안 남긴다).
    chatter = Inbound(author_id=STRANGER, author_is_bot=False, content="점심 뭐 먹지", channel_id="8", channel_kind="channel")
    assert route(chatter, bot_id=BOT, policy=AccessPolicy([OWNER]), sessions=sessions) is None


# ── 대화 열쇠 ──────────────────────────────────────────────────────────────────

def test_session_keys_dm_channel_thread_and_new(tmp_path: Path) -> None:
    sessions = SessionMap(tmp_path / "s.json")
    policy = AccessPolicy([OWNER])

    dm = route(Inbound(OWNER, False, "안녕", "700", "dm"), bot_id=BOT, policy=policy, sessions=sessions)
    assert dm and dm.action == "task" and not dm.needs_thread
    assert sessions.session_id(dm.session_key) == f"discord-dm-{OWNER}"

    # 채널: 멘션 없으면 무시, 멘션하면 스레드를 연다
    assert route(Inbound(OWNER, False, "안녕", "800", "channel"), bot_id=BOT, policy=policy, sessions=sessions) is None
    mentioned = route(Inbound(OWNER, False, f"<@{BOT}> 조사해 줘", "800", "channel", mentions_bot=True),
                      bot_id=BOT, policy=policy, sessions=sessions)
    assert mentioned and mentioned.needs_thread and mentioned.text == "조사해 줘"

    # 남의 스레드는 멘션해야, 우리 스레드는 멘션 없이도
    assert route(Inbound(OWNER, False, "더", "900", "thread"), bot_id=BOT, policy=policy, sessions=sessions) is None
    sessions.add_thread("900")
    inside = route(Inbound(OWNER, False, "더", "900", "thread"), bot_id=BOT, policy=policy, sessions=sessions)
    assert inside and inside.session_key == "900" and sessions.session_id("900") == "discord-900"

    # /new 는 다음 번호 — 다시 켜도 이어진다(파일)
    assert sessions.reset("900") == "discord-900-2"
    assert SessionMap(tmp_path / "s.json").session_id("900") == "discord-900-2"
    assert SessionMap(tmp_path / "s.json").is_bot_thread("900")

    # 봇 자신 · 다른 봇은 무시
    assert route(Inbound(BOT, True, "x", "700", "dm"), bot_id=BOT, policy=policy, sessions=sessions) is None


def test_commands_are_recognised_after_a_mention(tmp_path: Path) -> None:
    routed = route(Inbound(OWNER, False, f"<@!{BOT}> /stop", "800", "channel", mentions_bot=True),
                   bot_id=BOT, policy=AccessPolicy([OWNER]), sessions=SessionMap(None))
    assert routed and routed.action == "command" and not routed.needs_thread
    assert parse_command("/status please") == "status"
    assert parse_command("/approve") is None
    assert strip_mention(f"<@{BOT}>  hi", BOT) == "hi"


# ── 긴 답 나누기 ───────────────────────────────────────────────────────────────

def test_long_answers_split_under_2000_and_keep_code_fences() -> None:
    code = "```python\n" + "\n".join(f"print({i})  # {'x' * 40}" for i in range(120)) + "\n```"
    text = "앞말\n" + code + "\n뒷말"
    chunks = FakeAdapter().split_message(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 2000
        assert not fence_state_after(chunk)[0], "조각마다 코드 칸이 닫혀야 한다"
    assert chunks[1].startswith("```python"), "잘린 코드 칸은 다음 조각에서 같은 언어로 다시 연다"


def test_a_flood_is_capped_at_eight_messages_with_a_notice() -> None:
    chunks = FakeAdapter().split_message("가나다 " * 10000)
    assert len(chunks) == 8
    assert "PC 앱" in chunks[-1]
    english = FakeAdapter().split_message("word " * 10000, "en")
    assert "PC app" in english[-1]
    assert truncate_message("short") == ["short"]


# ── 승인: PC 앱에서만 ───────────────────────────────────────────────────────────

def test_waiting_approval_is_announced_and_never_approved_from_discord(tmp_path: Path) -> None:
    fake = FakeBackend(["running", "waiting_approval", "waiting_approval", "running", "completed"])
    adapter = FakeAdapter()
    asyncio.run(_runner(adapter, fake, tmp_path).run_task(_event()))
    assert "PC 앱 화면에서 승인을 기다리고 있습니다" in adapter.texts()
    assert adapter.texts().count("승인을 기다리고") == 1, "같은 기다림은 한 번만 알린다"
    assert fake.posts() == ["/v1/chat"], "디스코드 쪽은 맡기기 말고 어떤 POST 도 하지 않는다(승인 문 포함)"
    assert not any(r.url.path.startswith("/v1/approvals/") for r in fake.requests)


def test_english_sender_gets_english_wait_text_and_the_question(tmp_path: Path) -> None:
    fake = FakeBackend(["waiting_approval", "completed"], question="Which file?")
    adapter = FakeAdapter()
    asyncio.run(_runner(adapter, fake, tmp_path).run_task(_event("find three job posts")))
    assert "Waiting for approval in the PC app" in adapter.texts()
    assert "Which file?" in adapter.texts()
    assert fake.posts() == ["/v1/chat"]


def test_unwired_button_policy_still_runs_app_only(tmp_path: Path) -> None:
    fake = FakeBackend(["completed"])
    runner = TaskRunner(FakeAdapter(), fake.backend(), SessionMap(None), approvals="buttons", poll_sec=0, sleep=_no_sleep)
    assert runner.approvals == "app_only"


def test_each_approval_button_is_bound_to_its_own_approval() -> None:
    binder = ApprovalButtonBinder()
    yes_a, no_a = binder.bind("nonce-A", "job-1", OWNER)
    yes_b, _no_b = binder.bind("nonce-B", "job-2", OWNER)
    assert "nonce-A" not in yes_a, "승인 nonce 는 디스코드에 실리지 않는다"
    assert binder.resolve(yes_a, STRANGER) is None, "시킨 사람만 누른다"
    assert binder.resolve(yes_b, OWNER) == ("nonce-B", True)
    assert binder.resolve(yes_a, OWNER) == ("nonce-A", True)
    assert binder.resolve(no_a, OWNER) is None, "한 번 쓰면 짝도 무효"


# ── 비밀 가리기 ────────────────────────────────────────────────────────────────

def test_bot_token_and_control_token_are_masked() -> None:
    redactor = Redactor()
    redactor.register(CONTROL_TOKEN)
    text = f"token={FAKE_BOT_TOKEN} header=Authorization: Bot {FAKE_BOT_TOKEN} ctl={CONTROL_TOKEN}"
    clean = redactor.redact(text)
    assert FAKE_BOT_TOKEN not in clean and CONTROL_TOKEN not in clean
    assert "[가림]" in clean
    assert redactor.redact("평범한 문장 1.2.3 그대로") == "평범한 문장 1.2.3 그대로"


def test_the_log_handler_filter_masks_everything_that_passes(tmp_path: Path) -> None:
    redactor = Redactor()
    redactor.register(CONTROL_TOKEN)
    path = tmp_path / "bridge.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.addFilter(RedactingFilter(redactor))
    logger = logging.getLogger("test.messaging.redact")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        logger.warning("connect with %s and %s", FAKE_BOT_TOKEN, CONTROL_TOKEN)
        try:
            raise RuntimeError(f"bad {FAKE_BOT_TOKEN}")
        except RuntimeError:
            logger.exception("failed")
    finally:
        logger.removeHandler(handler)
        handler.close()
    body = path.read_text(encoding="utf-8")
    assert FAKE_BOT_TOKEN not in body and CONTROL_TOKEN not in body
    assert body.count("[가림]") >= 3


def test_settings_file_refuses_a_pasted_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        DiscordSettings(allowed_user_ids=[FAKE_BOT_TOKEN]).save(tmp_path / SETTINGS_FILE)
    DiscordSettings(allowed_user_ids=[OWNER]).save(tmp_path / SETTINGS_FILE)
    assert DiscordSettings.load(tmp_path / SETTINGS_FILE).allowed_user_ids == [OWNER]


# ── 본체 따라가기 ──────────────────────────────────────────────────────────────

def test_a_task_is_submitted_followed_and_delivered(tmp_path: Path) -> None:
    small = tmp_path / "공고.xlsx"
    small.write_bytes(b"x" * 1024)
    big = tmp_path / "video.mp4"
    with open(big, "wb") as fh:
        fh.truncate(DISCORD_UPLOAD_LIMIT_BYTES + 1)
    fake = FakeBackend(["queued", "running", "running", "completed"], answer="공고 셋을 엑셀로 정리했습니다.",
                       files=[str(small), str(big)])
    adapter = FakeAdapter()
    summary = asyncio.run(_runner(adapter, fake, tmp_path).run_task(_event()))

    chat = next(r for r in fake.requests if r.url.path == "/v1/chat")
    body = json.loads(chat.content)
    assert chat.headers["X-JARVIS-TOKEN"] == CONTROL_TOKEN
    assert body["origin"] == "mcp" and body["caller"] == "Discord"
    assert body["session_id"] == f"discord-dm-{OWNER}"
    assert body["open_results"] is False and body["delivery"] == "screen"
    # 일 조회는 토큰 없이(정제된 사본), 진행은 토큰과 함께
    job_reads = [r for r in fake.requests if r.url.path == "/v1/jobs/job-1"]
    assert job_reads and all("X-JARVIS-TOKEN" not in r.headers for r in job_reads)

    assert summary and summary["status"] == "done"
    assert adapter.typing, "일하는 동안 입력 중 표시"
    assert any("사람인 공고를 읽는 중" in content for _c, _m, content in adapter.edits), "진행 메시지를 지금 하는 일로 고친다"
    assert adapter.edits[-1][2].startswith("✅")
    assert "공고 셋을 엑셀로 정리했습니다." in adapter.texts()
    # 디스코드에는 하네스 경고 · 영수증을 싣지 않는다(2026-10-18 대표 — 경고는 PC 앱 옆 판에서 본다).
    assert "출처" not in adapter.texts() and "⚠" not in adapter.texts(), "하네스 줄이 실렸다"
    assert adapter.documents == [str(small)], "한도 안 파일만 올린다"
    assert "video.mp4" in adapter.texts() and "한도" in adapter.texts(), "큰 파일은 올리기 전에 알린다"
    assert adapter.reactions == [("+", "👀"), ("-", "👀"), ("+", "✅")]


def test_an_old_file_in_the_result_is_not_uploaded(tmp_path: Path) -> None:
    old = tmp_path / "secret.txt"
    old.write_text("x", encoding="utf-8")
    past = time.time() - 3600
    os.utime(old, (past, past))
    fake = FakeBackend(["completed"], files=[str(old)])
    adapter = FakeAdapter()
    asyncio.run(_runner(adapter, fake, tmp_path).run_task(_event()))
    assert adapter.documents == []


def test_a_failed_job_ends_with_a_cross(tmp_path: Path) -> None:
    fake = FakeBackend(["running", "failed"])
    adapter = FakeAdapter()
    asyncio.run(_runner(adapter, fake, tmp_path).run_task(_event()))
    assert "실패했습니다" in adapter.texts()
    assert adapter.reactions[-1] == ("+", "❌")


def test_an_offline_backend_is_reported_plainly(tmp_path: Path) -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    backend = SonjariBackend("http://127.0.0.1:1", CONTROL_TOKEN, client=httpx.AsyncClient(transport=httpx.MockTransport(down)))
    adapter = FakeAdapter()
    asyncio.run(TaskRunner(adapter, backend, SessionMap(None), poll_sec=0, sleep=_no_sleep).run_task(_event()))
    assert "연결하지 못했습니다" in adapter.texts()
    assert CONTROL_TOKEN not in adapter.texts()


def test_stop_and_status_commands(tmp_path: Path) -> None:
    fake = FakeBackend(["running"])
    adapter = FakeAdapter()
    runner = _runner(adapter, fake, tmp_path)
    event = _event("/stop")

    async def scenario() -> tuple[str, str, str, str]:
        idle = await runner.command_reply("status", event)
        runner.sessions.set_active(event.session_key, "job-1", OWNER)
        busy = await runner.command_reply("status", event)
        stopped = await runner.command_reply("stop", event)
        fresh = await runner.command_reply("new", event)
        return idle, busy, stopped, fresh

    idle, busy, stopped, fresh = asyncio.run(scenario())
    assert "진행 중인 일이 없습니다" in idle
    assert "사람인 공고를 읽는 중" in busy
    assert "멈추라고 전했습니다" in stopped and "/v1/jobs/job-1/cancel" in fake.posts()
    assert "새 대화" in fresh and runner.sessions.session_id(event.session_key).endswith("-2")


def test_a_second_message_while_busy_is_not_submitted(tmp_path: Path) -> None:
    fake = FakeBackend(["running"])
    adapter = FakeAdapter()
    runner = _runner(adapter, fake, tmp_path)
    runner.sessions.set_active(f"dm-{OWNER}", "job-1", OWNER)
    asyncio.run(runner.handle(_event("하나 더")))
    assert fake.posts() == []
    assert "진행 중" in adapter.texts()


# ── setup ──────────────────────────────────────────────────────────────────────

def test_an_application_id_is_rejected_as_a_token() -> None:
    assert token_shape_error("1234567890123456789") is not None
    assert token_shape_error("abc def") is not None
    assert token_shape_error("no-dots-here") is not None
    assert token_shape_error(FAKE_BOT_TOKEN) is None


def test_invite_url_carries_exactly_the_named_permissions() -> None:
    # View Channels · Send Messages · Embed Links · Attach Files · Read Message History · Add Reactions ·
    # Create Public Threads · Send Messages in Threads — 비트를 손으로 다시 더한 값.
    expected = (1 << 10) + (1 << 11) + (1 << 14) + (1 << 15) + (1 << 16) + (1 << 6) + (1 << 35) + (1 << 38)
    assert expected == 309237763136
    assert INVITE_PERMISSIONS == expected
    url = invite_url("123")
    assert "permissions=309237763136" in url
    assert "scope=bot+applications.commands" in url
    assert "client_id=123" in url


def test_setup_checks_the_token_and_keeps_it_out_of_files_and_output(tmp_path: Path) -> None:
    calls: list[dict[str, str]] = []

    def fake_get(url: str, headers: dict[str, str]) -> tuple[int, Any]:
        calls.append(headers)
        assert url.endswith("/applications/@me")
        flags = 0 if len(calls) == 1 else (1 << 19)   # 처음엔 꺼짐 → 켠 뒤 다시 확인
        return 200, {"id": "555", "flags": flags, "bot": {"username": "sonjari-bot"},
                     "owner": {"id": OWNER, "username": "owner"}, "approximate_guild_count": 0}

    answers = iter(["", "", "", ""])          # Intent 다시 확인(Enter) · 주인 허용(Enter=예) · 추가 ID 없음 · 홈 채널 없음
    secrets = iter(["1234567890", FAKE_BOT_TOKEN])   # 애플리케이션 ID 를 먼저 붙였다가 고친다
    printed: list[str] = []
    store = MemoryCredentialStore()
    code = run_setup(data_dir=tmp_path, store=store, ask=lambda _p: next(answers), ask_secret=lambda _p: next(secrets),
                     out=printed.append, get=fake_get)
    assert code == 0
    assert store.read(TARGET) == FAKE_BOT_TOKEN
    assert calls[0]["Authorization"] == f"Bot {FAKE_BOT_TOKEN}"
    output = "\n".join(printed)
    assert FAKE_BOT_TOKEN not in output
    assert "애플리케이션 ID" in output
    assert "Message Content Intent" in output
    assert "permissions=309237763136" in output
    saved = (tmp_path / SETTINGS_FILE).read_text(encoding="utf-8")
    assert FAKE_BOT_TOKEN not in saved
    assert json.loads(saved)["allowed_user_ids"] == [OWNER]
    assert json.loads(saved)["discord_approvals"] == "app_only"


def test_setup_saves_nothing_after_three_rejected_tokens(tmp_path: Path) -> None:
    store = MemoryCredentialStore()
    code = run_setup(data_dir=tmp_path, store=store, ask=lambda _p: "", ask_secret=lambda _p: FAKE_BOT_TOKEN,
                     out=lambda _s: None, get=lambda _u, _h: (401, {"message": "401: Unauthorized"}))
    assert code == 1
    assert store.read(TARGET) is None
    assert not (tmp_path / SETTINGS_FILE).exists()


# ── discord.py 없이 ────────────────────────────────────────────────────────────

def test_the_package_imports_without_discord_py() -> None:
    import importlib

    for name in ("base", "bridge", "discord_adapter", "onboarding", "credentials", "discord_config", "__main__"):
        importlib.import_module(f"alture_jarvis.messaging.{name}")
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "messaging").glob("*.py")
    for path in source:
        top_level = [line for line in path.read_text(encoding="utf-8").splitlines()
                     if line.startswith(("import discord", "from discord"))]
        assert not top_level, f"{path.name}: discord 는 함수 안에서만 부른다"


def test_a_bare_command_answers_in_the_language_of_the_conversation(tmp_path: Path) -> None:
    fake = FakeBackend(["completed"])
    adapter = FakeAdapter()
    runner = _runner(adapter, fake, tmp_path)
    asyncio.run(runner.handle(_event("find three job posts")))
    asyncio.run(runner.handle(_event("/status")))
    assert adapter.sent[-1][1] == "Nothing is running in this conversation."
    assert detect_lang("/stop") == "ko"


def test_a_source_install_bridge_uses_the_same_runtime_root_as_the_backend(tmp_path, monkeypatch) -> None:
    """첫 점검(2026-10-17): 소스로 깐 손자리에서 다리가 스토어판 데이터 폴더를 보고 「연결 토큰: 없음」이 됐다."""
    from pathlib import Path

    from alture_jarvis import config as config_module
    from alture_jarvis.messaging import bridge

    root = tmp_path / "alture-jarvis"
    module = root / "src" / "alture_jarvis" / "messaging" / "bridge.py"
    module.parent.mkdir(parents=True)
    module.write_text("", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "control.token").write_text("secret-for-test", encoding="utf-8")
    monkeypatch.setattr(bridge, "__file__", str(module))
    kept: dict[str, str] = {}
    monkeypatch.setattr(config_module, "keep_private", lambda name, value, override=False: kept.__setitem__(name, value))
    monkeypatch.setattr(config_module, "load_env_file", lambda _path: None)
    monkeypatch.setattr(config_module, "setting", lambda name, default="": kept.get(name, default))
    bridge.resolve_backend()
    assert Path(kept["JARVIS_RUNTIME_ROOT"]) == root


def test_the_home_channel_takes_messages_without_a_mention() -> None:
    """2026-10-18 대표 첫 시험: 혼자 쓰는 서버 #일반의 「하이」가 멘션이 없어 조용히 버려졌다."""
    from alture_jarvis.messaging.discord_adapter import Inbound, route

    policy = AccessPolicy(["42"])
    sessions = SessionMap(None)
    said = Inbound(author_id="42", author_is_bot=False, content="하이", channel_id="777", channel_kind="channel")
    assert route(said, bot_id="9", policy=policy, sessions=sessions) is None
    home = route(said, bot_id="9", policy=policy, sessions=sessions, free_channels=frozenset({"777"}))
    assert home is not None and home.text == "하이" and not home.needs_thread
    stranger = Inbound(author_id="13", author_is_bot=False, content="하이", channel_id="777", channel_kind="channel")
    # 허용 목록 밖 사람은 홈 채널에서도 일이 되지 않는다 — 2026-10-18 부터는 「허용 요청」으로만 넘어간다.
    asked = route(stranger, bot_id="9", policy=policy, sessions=sessions, free_channels=frozenset({"777"}))
    assert asked is not None and asked.action == "request"


def test_our_appended_warning_and_checklist_do_not_reach_discord() -> None:
    from alture_jarvis.memory import without_our_tail

    answer = "서울은 맑고 18도입니다.\n\n⚠ **도구가 준 적 없는 숫자**가 있습니다.\n\n**시킨 것 대조**\n- ✅ 날씨 찾기"
    assert without_our_tail(answer) == "서울은 맑고 18도입니다."


def test_tables_become_lists_for_messengers() -> None:
    """2026-10-18 대표 첫 시험: 디스코드가 표를 못 그려 `| 장소 | 포인트 |` 가 글자 그대로 나왔다."""
    from alture_jarvis.messaging.markdown import tables_to_lists

    two = "| 장소 | 포인트 |\n|---|---|\n| **창포원** | 마차 타기 |"
    assert tables_to_lists(two) == "• **창포원** — 마차 타기"
    many = "| 식당 | 메뉴 | 가격대 |\n|:--|--:|---|\n| 시장추어탕 | 칼국수 | — |"
    assert tables_to_lists(many) == "• **시장추어탕** — 메뉴: 칼국수"
    code = "```\n| a | b |\n|---|---|\n| 1 | 2 |\n```"
    assert tables_to_lists(code) == code
    assert tables_to_lists("그냥 | 막대가 든 글") == "그냥 | 막대가 든 글"
