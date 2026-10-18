"""가족 · 동료 추가 카드(ID 없이) · 주인 자동 허용 · 사용자 설치 링크 (2026-10-18). 진짜 디스코드로는 아무것도 안 보낸다.

붙드는 것:
- 모르는 사람이 봇에게 말하면 **일은 시작하지 않고** 본체에 허용 요청을 남긴다 · 그 사람에게 안내는 하루 한 번
- 요청은 이벤트(`discord_access_requested`)로 화면에 알린다 · 「허용」만 허용 목록에 넣는다(요청 없는 ID 는 거절)
  · 허용하면 그 사람에게 DM · 돌던 다리에 바로 반영 · 「무시」한 사람은 다시 말해도 카드 · 안내 없음
- 따로 띄운 다리도 설정 파일을 다시 읽어 허용을 받는다(재시작 없이)
- 명령 창 마법사는 앱 주인을 묻지 않고 넣고, `--advanced` 일 때만 묻는다
- 사용자 설치 링크 · 켜짐 여부 · 서버 0곳을 문제로 말하지 않기 · 슬래시 명령의 설치 범위
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.messaging.access_requests import AccessRequestBook
from alture_jarvis.messaging.base import AccessPolicy, MessageEvent, SessionMap, say
from alture_jarvis.messaging.bridge import TaskRunner
from alture_jarvis.messaging.credentials import TARGET, MemoryCredentialStore
from alture_jarvis.messaging.discord_config import SETTINGS_FILE, DiscordSettings
from alture_jarvis.messaging.onboarding import check_bot_token, run_setup
from test_messaging_discord_1017 import CONTROL_TOKEN, FakeAdapter, _no_sleep
from test_messaging_discord_service_1018 import (
    APP_ID, FAKE_BOT_TOKEN, OWNER, FakeClipboard, FakeDiscord, _config, _saved, _service,
)

FRIEND = "123412341234123412"


def _event(text: str = "안녕하세요, 저도 써도 되나요?", user: str = FRIEND, chat: str = "900") -> MessageEvent:
    return MessageEvent(text=text, chat_id=chat, user_id=user, session_key=f"dm-{user}", message_id="77",
                        chat_type="dm", user_name="나래", user_handle="narae", lang="ko")


# ── 보관 ───────────────────────────────────────────────────────────────────────

def test_a_request_is_kept_and_the_notice_goes_once_a_day(tmp_path: Path) -> None:
    now = [1000.0]
    book = AccessRequestBook(tmp_path, clock=lambda: now[0])
    first = book.record(FRIEND, display_name="나래", username="narae", text="가" * 200)
    assert first["new"] is True and first["notify"] is True
    assert first["request"]["first_text"] == "가" * 80 and first["request"]["username"] == "narae"
    now[0] += 3600
    again = book.record(FRIEND, text="또")
    assert again["new"] is False and again["notify"] is False and again["request"]["count"] == 2
    assert again["request"]["first_text"] == "가" * 80   # 첫 메시지를 남긴다
    now[0] += 24 * 3600
    assert book.record(FRIEND)["notify"] is True
    assert "last_notified" not in book.pending()[0]
    book.ignore(FRIEND)
    assert book.pending() == [] and book.record(FRIEND)["ignored"] is True


# ── 다리 쪽: 일은 안 하고 요청만 ─────────────────────────────────────────────────

class RequestBackend:
    def __init__(self, notify: bool | None) -> None:
        self.notify = notify
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/discord/requests" and self.notify is not None:
            return httpx.Response(200, json={"ok": True, "notify": self.notify, "new": True})
        return httpx.Response(404, json={})

    def runner(self, adapter: FakeAdapter, tmp_path: Path) -> TaskRunner:
        from alture_jarvis.messaging.bridge import SonjariBackend

        backend = SonjariBackend("http://127.0.0.1:8091", CONTROL_TOKEN,
                                 client=httpx.AsyncClient(transport=httpx.MockTransport(self.handler)))
        return TaskRunner(adapter, backend, SessionMap(tmp_path / "s.json"), poll_sec=0, sleep=_no_sleep)


def test_a_stranger_leaves_a_request_and_starts_no_task(tmp_path: Path) -> None:
    fake, adapter = RequestBackend(notify=True), FakeAdapter()
    asyncio.run(fake.runner(adapter, tmp_path).access_request(_event()))
    paths = [r.url.path for r in fake.requests]
    assert paths == ["/v1/discord/requests"] and "/v1/chat" not in paths
    body = json.loads(fake.requests[0].content)
    assert body == {"user_id": FRIEND, "display_name": "나래", "username": "narae", "text": "안녕하세요, 저도 써도 되나요?"}
    assert adapter.sent == [("900", say("access_pending", "ko"), "77")]


def test_no_notice_when_the_body_says_not_today(tmp_path: Path) -> None:
    fake, adapter = RequestBackend(notify=False), FakeAdapter()
    asyncio.run(fake.runner(adapter, tmp_path).access_request(_event()))
    assert adapter.sent == []


def test_an_offline_body_still_notices_only_once(tmp_path: Path) -> None:
    fake, adapter = RequestBackend(notify=None), FakeAdapter()
    runner = fake.runner(adapter, tmp_path)
    asyncio.run(runner.access_request(_event("hello, can I use this?")))
    asyncio.run(runner.access_request(_event("hello again")))
    assert [text for _c, text, _r in adapter.sent] == [say("access_pending", "ko")]   # 본체가 꺼져도 하루 한 번


def test_a_running_bridge_picks_up_an_allow_from_the_settings_file(tmp_path: Path) -> None:
    path = tmp_path / SETTINGS_FILE
    DiscordSettings(allowed_user_ids=[OWNER]).save(path)
    now = [0.0]
    policy = AccessPolicy([OWNER], clock=lambda: now[0], refresh=lambda: DiscordSettings.load(path).allowed_user_ids)
    assert policy.allows(FRIEND) is False
    DiscordSettings(allowed_user_ids=[OWNER, FRIEND]).save(path)   # PC 에서 「허용」
    now[0] += 2
    assert policy.allows(FRIEND) is True


# ── 본체 쪽: 요청 · 허용 · 무시 ─────────────────────────────────────────────────

def test_record_allow_and_ignore_through_the_http_doors(tmp_path: Path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis
    events: list[tuple[str, dict[str, Any]]] = []
    discord = FakeDiscord()
    service = _service(tmp_path, store=_saved(MemoryCredentialStore()), discord=discord)
    service._publish = lambda name, data: events.append((name, data))
    DiscordSettings(allowed_user_ids=[OWNER]).save(tmp_path / "data" / SETTINGS_FILE)
    runtime.discord = service
    headers = {"X-JARVIS-TOKEN": "test-token"}
    with TestClient(app) as client:
        assert client.post("/v1/discord/requests", json={"user_id": FRIEND}).status_code == 401
        body = {"user_id": FRIEND, "display_name": "나래", "username": "narae", "text": "저도 써도 되나요?"}
        first = client.post("/v1/discord/requests", headers=headers, json=body).json()
        second = client.post("/v1/discord/requests", headers=headers, json=body).json()
        assert first["notify"] is True and first["new"] is True and second["notify"] is False
        assert [name for name, _ in events] == ["discord_access_requested"]   # 처음 한 번만 카드
        assert set(events[0][1]) == {"user_id", "display_name", "username", "first_seen", "first_text", "count", "last_seen"}
        assert events[0][1]["user_id"] == FRIEND and events[0][1]["first_text"] == "저도 써도 되나요?"

        listed = client.get("/v1/discord/requests", headers=headers).json()
        assert [row["user_id"] for row in listed["requests"]] == [FRIEND] and listed["ignored_count"] == 0
        assert client.get("/v1/discord/status", headers=headers).json()["pending_requests"] == 1

        # 요청 없는 ID 는 이 문으로 못 들인다.
        stranger = client.post("/v1/discord/requests/555555555555555555/allow", headers=headers).json()
        assert stranger["ok"] is False and stranger["error"] == "no_such_request"

        allowed = client.post(f"/v1/discord/requests/{FRIEND}/allow", headers=headers).json()
        assert allowed["ok"] is True and allowed["dm_sent"] is True and allowed["requests"] == []
        assert DiscordSettings.load(tmp_path / "data" / SETTINGS_FILE).allowed_user_ids == [OWNER, FRIEND]
        dm = [b for _m, path, b in discord.calls if path == "/users/@me/channels"]
        sent = [b for _m, path, b in discord.calls if path.endswith("/messages")]
        assert dm == [{"recipient_id": FRIEND}] and sent[-1]["content"] == say("access_allowed", "ko")
        assert sent[-1]["allowed_mentions"] == {"parse": []}
        # 이미 허용된 사람이 또 말하면(다리가 아직 모를 때) 요청도 안내도 없다.
        again = client.post("/v1/discord/requests", headers=headers, json=body).json()
        assert again["allowed"] is True and again["notify"] is False

        other = "666666666666666666"
        client.post("/v1/discord/requests", headers=headers, json={**body, "user_id": other})
        ignored = client.post(f"/v1/discord/requests/{other}/ignore", headers=headers).json()
        assert ignored["ok"] is True and ignored["requests"] == [] and ignored["ignored_count"] == 1
        quiet = client.post("/v1/discord/requests", headers=headers, json={**body, "user_id": other}).json()
        assert quiet["notify"] is False and quiet["ignored"] is True
        assert len(events) == 2   # 무시한 사람은 다시 카드를 띄우지 않는다
        bad = client.post("/v1/discord/requests/not-a-number/allow", headers=headers).json()
        assert bad["ok"] is False and bad["error"] == "invalid_user_id"


def test_allowing_reaches_the_running_bridge_at_once(tmp_path: Path) -> None:
    service = _service(tmp_path, store=_saved(MemoryCredentialStore()))
    DiscordSettings(allowed_user_ids=[OWNER]).save(tmp_path / "data" / SETTINGS_FILE)
    policy = AccessPolicy([OWNER])

    class Running:
        pass

    service._adapter = Running()
    service._adapter.policy = policy   # type: ignore[attr-defined]
    service.record_access_request({"user_id": FRIEND, "text": "hi"})
    assert service.allow_request(FRIEND)["ok"] is True
    assert policy.allows(FRIEND) is True


# ── 주인 자동 허용 (마법사 · 클립보드) ───────────────────────────────────────────

def _fake_get(install_types: dict[str, Any] | None = None, servers: int = 1):
    def get(url: str, headers: dict[str, str]) -> tuple[int, Any]:
        return 200, {"id": APP_ID, "flags": 1 << 18, "bot": {"username": "bot"}, "owner": {"id": OWNER, "username": "garam"},
                     "approximate_guild_count": servers, "integration_types_config": install_types or {"0": {}}}
    return get


def test_the_setup_wizard_allows_the_owner_without_asking(tmp_path: Path) -> None:
    asked: list[str] = []
    code = run_setup(data_dir=tmp_path, store=MemoryCredentialStore(), ask=lambda p: asked.append(p) or "",
                     ask_secret=lambda _p: FAKE_BOT_TOKEN, out=lambda _s: None, get=_fake_get())
    assert code == 0 and asked == []   # 묻는 말이 하나도 없다
    assert DiscordSettings.load(tmp_path / SETTINGS_FILE).allowed_user_ids == [OWNER]


def test_the_advanced_wizard_still_asks(tmp_path: Path) -> None:
    asked: list[str] = []
    answers = iter(["n", "123456789012345678", "234567890123456789"])
    code = run_setup(data_dir=tmp_path, store=MemoryCredentialStore(), ask=lambda p: asked.append(p) or next(answers),
                     ask_secret=lambda _p: FAKE_BOT_TOKEN, out=lambda _s: None, get=_fake_get(), advanced=True)
    settings = DiscordSettings.load(tmp_path / SETTINGS_FILE)
    assert code == 0 and len(asked) == 3
    assert settings.allowed_user_ids == ["123456789012345678"] and settings.home_channel_id == "234567890123456789"


def test_the_clipboard_door_allows_the_owner_without_asking(tmp_path: Path) -> None:
    result = _service(tmp_path, clipboard=FakeClipboard(FAKE_BOT_TOKEN)).token_from_clipboard()
    assert result["ok"] is True and result["owners_added"] == 1
    assert DiscordSettings.load(tmp_path / "data" / SETTINGS_FILE).allowed_user_ids == [OWNER]


# ── 사용자 설치 ────────────────────────────────────────────────────────────────

def test_user_install_link_and_switch() -> None:
    on = check_bot_token(FAKE_BOT_TOKEN, get=_fake_get({"0": {}, "1": {}}))
    off = check_bot_token(FAKE_BOT_TOKEN, get=_fake_get({"0": {}}))
    assert on.user_install_enabled is True and off.user_install_enabled is False
    assert on.user_install_url == (f"https://discord.com/oauth2/authorize?client_id={APP_ID}"
                                   "&integration_type=1&scope=applications.commands")


class UserInstallDiscord(FakeDiscord):
    def __call__(self, method: str, url: str, headers: dict[str, str], body: Any) -> tuple[int, Any]:
        status, data = super().__call__(method, url, headers, body)
        if url.endswith("/applications/@me"):
            data = {**data, "integration_types_config": {"0": {}, "1": {}}}
        return status, data


def test_zero_servers_is_not_a_problem_with_user_install(tmp_path: Path) -> None:
    service = _service(tmp_path, store=_saved(MemoryCredentialStore()), discord=UserInstallDiscord(guilds=[]))
    try:
        checked = service.recheck()
        assert checked["ok"] is True and checked["stage"] != "need_invite"
        assert checked["servers_note"] == "user_install_possible" and checked["user_install_enabled"] is True
        assert "사용자 설치" in checked["message"] and checked["user_install_url"].endswith("scope=applications.commands")
        finished = service.finish()
        assert finished["ok"] is True and finished["home_channel_id"] == ""
    finally:
        service.stop()
    plain = _service(tmp_path / "b", store=_saved(MemoryCredentialStore()), discord=FakeDiscord(guilds=[])).recheck()
    assert plain["stage"] == "need_invite" and plain["servers_note"] == ""


def test_slash_commands_are_available_for_user_installs_and_dms() -> None:
    pytest.importorskip("discord")
    from alture_jarvis.messaging.discord_adapter import DiscordAdapter

    async def build() -> list[Any]:
        adapter = DiscordAdapter("x" * 30, policy=AccessPolicy(["1"]), sessions=SessionMap(None))
        client = adapter._build_client()
        try:
            return list(client._connection._command_tree.get_commands())
        finally:
            await client.close()

    commands = asyncio.run(build())
    assert len(commands) == 5
    for command in commands:
        assert command.allowed_installs.guild is True and command.allowed_installs.user is True
        contexts = command.allowed_contexts
        assert contexts.guild is True and contexts.dm_channel is True and contexts.private_channel is True

