"""본체 안의 디스코드 다리 · 연결 단계 문(`messaging/service.py`) — 클립보드 · 디스코드 REST · 자격 증명 관리자는 전부 가짜 (2026-10-18).

붙드는 것:
- 클립보드: 숫자만(Application ID) · 빈 클립보드 거절 · 맞는 토큰은 저장 뒤 비움 · 그 사이 다른 글로 바뀌었으면 안 비움
- 어떤 응답에도 토큰 값이 없다(HTTP 문까지)
- 마무리: 홈 채널 자동 선택(주인 서버의 첫 글 채널, 남의 서버는 건너뜀) · 환영 DM 은 아무도 부르지 않는다
- 다리 하나만: 다른 프로세스가 잠금을 쥐면 본체는 안 띄우고 owner_process="other"
- 다리 시작이 넘어져도 본체 기동에는 예외가 안 올라간다
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from alture_jarvis.api import create_app
from alture_jarvis.config import JarvisConfig
from alture_jarvis.messaging.__main__ import _SingleInstance
from alture_jarvis.messaging.credentials import TARGET, MemoryCredentialStore
from alture_jarvis.messaging.discord_config import SETTINGS_FILE, DiscordSettings
from alture_jarvis.messaging.service import LOCK_FILE, DiscordService, first_text_channel

FAKE_BOT_TOKEN = ".".join(("MTEyMzQ1Njc4OTAxMjM0NTY3OA", "GaBcDe", "abcdefghijklmnopqrstuvwxyz0123456789AB"))  # 조각으로 둔다 — 한 덩어리면 깃허브 비밀 검사가 진짜 토큰으로 보고 올리기를 막는다(2026-10-18)
APP_ID = "333333333333333333"
OWNER = "111111111111111111"
STRANGER = "999999999999999999"
MY_GUILD, OTHER_GUILD = "444444444444444444", "555555555555555555"
HOME, NEWS, CATEGORY, VOICE = "600000000000000001", "600000000000000002", "600000000000000003", "600000000000000004"
OTHER_TEXT = "700000000000000001"
DM_CHANNEL = "800000000000000001"


class FakeClipboard:
    def __init__(self, *values: str) -> None:
        self.values = list(values)   # 읽을 때마다 하나씩 — 마지막 값은 계속
        self.cleared = 0

    def read(self) -> str:
        return self.values.pop(0) if len(self.values) > 1 else (self.values[0] if self.values else "")

    def clear(self) -> None:
        self.cleared += 1
        self.values = [""]


class FakeDiscord:
    """디스코드 REST 가짜 — 부른 것을 다 적는다. 진짜 디스코드로는 아무것도 안 나간다."""

    def __init__(self, *, intent: bool = True, guilds: list[str] | None = None, status: int = 200) -> None:
        self.intent = intent
        self.guilds = [MY_GUILD] if guilds is None else guilds
        self.status = status
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], body: Any) -> tuple[int, Any]:
        assert headers["Authorization"] == f"Bot {FAKE_BOT_TOKEN}"
        path = url.split("/api/v10", 1)[1]
        self.calls.append((method, path, body))
        if self.status != 200:
            return self.status, {"retry_after": 2.4} if self.status == 429 else {"message": "no"}
        if path == "/applications/@me":
            return 200, {"id": APP_ID, "flags": (1 << 18) if self.intent else 0, "bot": {"username": "내 손자리"},
                         "owner": {"id": OWNER, "username": "garam"}, "approximate_guild_count": len(self.guilds)}
        if path == "/users/@me/guilds":
            return 200, [{"id": gid, "name": gid} for gid in self.guilds]
        if path == f"/guilds/{OTHER_GUILD}":
            return 200, {"id": OTHER_GUILD, "owner_id": STRANGER}
        if path == f"/guilds/{MY_GUILD}":
            return 200, {"id": MY_GUILD, "owner_id": OWNER}
        if path == f"/guilds/{OTHER_GUILD}/channels":
            return 200, [{"id": OTHER_TEXT, "type": 0, "name": "친구방", "position": 0}]
        if path == f"/guilds/{MY_GUILD}/channels":
            return 200, [
                {"id": CATEGORY, "type": 4, "name": "채팅", "position": 0},
                {"id": NEWS, "type": 0, "name": "공지", "position": 0, "parent_id": CATEGORY},
                {"id": VOICE, "type": 2, "name": "음성", "position": 0},
                {"id": HOME, "type": 0, "name": "일반", "position": 3},
            ]
        if path == "/users/@me/channels":
            return 200, {"id": DM_CHANNEL}
        if path == f"/channels/{DM_CHANNEL}/messages":
            return 200, {"id": "1"}
        return 404, None


class FakeAdapter:
    def __init__(self) -> None:
        self._ready = asyncio.Event()
        self._closed: asyncio.Event | None = None

    async def run_forever(self) -> None:
        self._closed = asyncio.Event()
        self._ready.set()
        await self._closed.wait()

    async def disconnect(self) -> None:
        if self._closed is not None:
            self._closed.set()


class FakeBackend:
    async def aclose(self) -> None:
        return None


def _config(tmp_path: Path) -> JarvisConfig:
    return JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                        control_token="test-token", camera_enabled=False, vision_enabled=False,
                        voice_enabled=False, tts_enabled=False)


def _service(tmp_path: Path, *, store: MemoryCredentialStore | None = None, discord: FakeDiscord | None = None,
             clipboard: FakeClipboard | None = None, compose: Any = None) -> DiscordService:
    composed: list[FakeAdapter] = []

    def fake_compose(data_dir: Path, base_url: str, control_token: str, token: str) -> tuple[Any, Any]:
        assert base_url == "http://127.0.0.1:8091" and control_token == "test-token" and token == FAKE_BOT_TOKEN
        adapter = FakeAdapter()
        composed.append(adapter)
        return adapter, FakeBackend()

    service = DiscordService(_config(tmp_path), store=store or MemoryCredentialStore(), http=discord or FakeDiscord(),
                             clipboard=clipboard or FakeClipboard(""), compose=compose or fake_compose,
                             installed=lambda: True, lang=lambda: "ko", retry_delays=(0.01,))
    service.composed = composed  # type: ignore[attr-defined]
    return service


def _saved(store: MemoryCredentialStore) -> MemoryCredentialStore:
    store.write(TARGET, FAKE_BOT_TOKEN)
    return store


# ── 클립보드 ────────────────────────────────────────────────────────────────────

def test_an_application_id_on_the_clipboard_is_refused_without_calling_discord(tmp_path: Path) -> None:
    discord, store = FakeDiscord(), MemoryCredentialStore()
    result = _service(tmp_path, store=store, discord=discord, clipboard=FakeClipboard(APP_ID)).token_from_clipboard()
    assert result["ok"] is False and result["error"] == "application_id"
    assert "Application ID" in result["message"]
    assert APP_ID not in json.dumps(result, ensure_ascii=False)   # 복사한 것을 되풀이하지 않는다
    assert discord.calls == [] and store.items == {}


def test_an_empty_clipboard_says_so(tmp_path: Path) -> None:
    result = _service(tmp_path, clipboard=FakeClipboard("   ")).token_from_clipboard()
    assert result["ok"] is False and result["error"] == "clipboard_empty"


def test_a_good_token_is_saved_the_owner_allowed_and_the_clipboard_emptied(tmp_path: Path) -> None:
    store, clipboard = MemoryCredentialStore(), FakeClipboard(FAKE_BOT_TOKEN)
    service = _service(tmp_path, store=store, clipboard=clipboard)
    result = service.token_from_clipboard()
    assert result["ok"] is True, result
    assert store.items == {TARGET: FAKE_BOT_TOKEN}
    assert clipboard.cleared == 1 and result["clipboard_cleared"] is True
    assert DiscordSettings.load(tmp_path / "data" / SETTINGS_FILE).allowed_user_ids == [OWNER]
    assert result["bot_name"] == "내 손자리" and result["app_id"] == APP_ID and result["message_content"] is True
    assert result["portal_bot_url"] == f"https://discord.com/developers/applications/{APP_ID}/bot"
    assert f"client_id={APP_ID}" in result["invite_url"]
    assert FAKE_BOT_TOKEN not in json.dumps(result, ensure_ascii=False)


def test_a_clipboard_that_changed_meanwhile_is_left_alone(tmp_path: Path) -> None:
    store, clipboard = MemoryCredentialStore(), FakeClipboard(FAKE_BOT_TOKEN, "사람이 그 사이 복사한 다른 글")
    result = _service(tmp_path, store=store, clipboard=clipboard).token_from_clipboard()
    assert result["ok"] is True and store.items == {TARGET: FAKE_BOT_TOKEN}
    assert clipboard.cleared == 0 and result["clipboard_cleared"] is False


def test_a_rejected_token_is_not_saved_and_is_explained(tmp_path: Path) -> None:
    store = MemoryCredentialStore()
    result = _service(tmp_path, store=store, discord=FakeDiscord(status=401),
                      clipboard=FakeClipboard(FAKE_BOT_TOKEN)).token_from_clipboard()
    assert result["ok"] is False and result["error"] == "token_rejected" and store.items == {}
    assert FAKE_BOT_TOKEN not in json.dumps(result, ensure_ascii=False)


def test_rate_limits_are_put_in_plain_words(tmp_path: Path) -> None:
    result = _service(tmp_path, store=_saved(MemoryCredentialStore()), discord=FakeDiscord(status=429)).recheck()
    assert result["ok"] is False and result["error"] == "rate_limited" and "2초" in result["message"]


# ── 다시 확인 · 마무리 ──────────────────────────────────────────────────────────

def test_recheck_reports_the_intent_and_the_invite_stage(tmp_path: Path) -> None:
    store = _saved(MemoryCredentialStore())
    off = _service(tmp_path, store=store, discord=FakeDiscord(intent=False)).recheck()
    assert off["ok"] is True and off["stage"] == "need_intent" and off["message_content"] is False
    empty = _service(tmp_path, store=store, discord=FakeDiscord(guilds=[])).recheck()
    assert empty["stage"] == "need_invite" and empty["servers"] == 0


def test_the_first_text_channel_is_the_one_shown_on_top() -> None:
    channels = [
        {"id": CATEGORY, "type": 4, "position": 0},
        {"id": NEWS, "type": 0, "position": 0, "parent_id": CATEGORY},
        {"id": VOICE, "type": 2, "position": 0},
        {"id": HOME, "type": 0, "position": 3},
    ]
    assert first_text_channel(channels)["id"] == HOME   # 분류 없는 채널이 목록 맨 위에 보인다
    assert first_text_channel([{"id": VOICE, "type": 2}]) is None


def test_finish_picks_the_owners_server_skips_others_and_welcomes_the_owner(tmp_path: Path) -> None:
    discord = FakeDiscord(guilds=[OTHER_GUILD, MY_GUILD])
    service = _service(tmp_path, store=_saved(MemoryCredentialStore()), discord=discord)
    try:
        result = service.finish()
        assert result["ok"] is True, result
        assert result["home_channel_auto"] is True and result["welcome_sent"] is True
        settings = DiscordSettings.load(tmp_path / "data" / SETTINGS_FILE)
        assert (settings.home_channel_id, settings.home_channel_name) == (HOME, "일반")
        assert settings.allowed_user_ids == [OWNER]
        assert ("GET", f"/guilds/{OTHER_GUILD}/channels", None) not in discord.calls   # 남의 서버 채널은 보지도 않는다
        assert result["running"] is True and result["owner_process"] == "self" and result["stage"] == "connected"
        dm = [body for method, path, body in discord.calls if path == "/users/@me/channels"]
        assert dm == [{"recipient_id": OWNER}]
        message = next(body for method, path, body in discord.calls if path == f"/channels/{DM_CHANNEL}/messages")
        assert message["allowed_mentions"] == {"parse": []}
        assert f"<#{HOME}>" in message["content"] and "PC 화면에서 승인" in message["content"]
    finally:
        service.stop()


def test_finish_keeps_a_home_channel_the_person_already_chose(tmp_path: Path) -> None:
    DiscordSettings(allowed_user_ids=[OWNER], home_channel_id="123456789012345678").save(tmp_path / "data" / SETTINGS_FILE)
    discord = FakeDiscord()
    service = _service(tmp_path, store=_saved(MemoryCredentialStore()), discord=discord)
    try:
        result = service.finish()
        assert result["ok"] is True and result["home_channel_auto"] is False
        assert result["home_channel_id"] == "123456789012345678"
        assert not any(path.endswith("/channels") and path.startswith("/guilds") for _m, path, _b in discord.calls)
    finally:
        service.stop()


def test_finish_without_a_server_asks_for_the_invite(tmp_path: Path) -> None:
    service = _service(tmp_path, store=_saved(MemoryCredentialStore()), discord=FakeDiscord(guilds=[]))
    result = service.finish()
    assert result["ok"] is False and result["error"] == "not_in_server" and service.running() is False


def test_disconnect_stops_the_bridge_and_forgets_the_token_but_keeps_the_allowlist(tmp_path: Path) -> None:
    store = _saved(MemoryCredentialStore())
    service = _service(tmp_path, store=store)
    assert service.finish()["ok"] is True
    result = service.disconnect()
    assert result["ok"] is True and store.items == {} and service.running() is False
    assert result["token_saved"] is False and result["stage"] == "no_token"
    assert DiscordSettings.load(tmp_path / "data" / SETTINGS_FILE).allowed_user_ids == [OWNER]
    # 잠금도 놓았다 — 따로 띄우는 다리가 이제 뜰 수 있다.
    other = _SingleInstance(tmp_path / "data" / LOCK_FILE)
    assert other.acquire() is True
    other.release()


# ── 다리 하나만 · 실패해도 본체는 뜬다 ─────────────────────────────────────────

def test_the_body_does_not_start_a_second_bridge_when_another_process_holds_the_lock(tmp_path: Path) -> None:
    other = _SingleInstance(tmp_path / "data" / LOCK_FILE)
    assert other.acquire() is True   # 따로 띄운 다리(다른 파일 손잡이 = 다른 프로세스와 같은 충돌)
    try:
        service = _service(tmp_path, store=_saved(MemoryCredentialStore()))
        assert service.start() == {"started": False, "reason": "other_process"}
        status = service.status()
        assert status["owner_process"] == "other" and status["running"] is True and status["stage"] == "other_process"
        assert service.composed == []   # type: ignore[attr-defined]
    finally:
        other.release()


def test_a_bridge_that_fails_to_start_does_not_raise_and_records_why(tmp_path: Path) -> None:
    def broken(*_args: Any) -> tuple[Any, Any]:
        raise RuntimeError("조립 실패")

    service = _service(tmp_path, store=_saved(MemoryCredentialStore()), compose=broken)
    service._retry_delays = (0.05,)
    assert service.start()["started"] is True   # 예외가 올라오지 않는다
    deadline = time.monotonic() + 5
    while not service.last_error and time.monotonic() < deadline:
        time.sleep(0.02)
    service.stop()
    assert "RuntimeError" in service.status()["last_error"]
    # 자격 증명 관리자가 터져도 마찬가지.
    class Exploding(MemoryCredentialStore):
        def read(self, target: str) -> str | None:
            raise OSError("cred")

    exploding = _service(tmp_path, store=Exploding())
    assert exploding.start()["started"] is False
    assert exploding.status()["token_saved"] is False


def test_no_saved_token_means_no_bridge(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert service.start() == {"started": False, "reason": "no_token"}
    assert service.status()["stage"] == "no_token"


def test_the_switch_turns_the_in_body_bridge_off(tmp_path: Path) -> None:
    service = _service(tmp_path, store=_saved(MemoryCredentialStore()))
    service.config.discord_bridge_enabled = False
    assert service.start() == {"started": False, "reason": "disabled"}


def test_a_rejected_token_at_boot_stops_before_connecting(tmp_path: Path) -> None:
    service = _service(tmp_path, store=_saved(MemoryCredentialStore()), discord=FakeDiscord(status=401))
    service.start()
    service._thread.join(5)   # type: ignore[union-attr]
    assert service.composed == []   # type: ignore[attr-defined]
    assert "토큰" in service.status()["last_error"]


def test_runtime_start_survives_a_discord_service_that_raises(tmp_path: Path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    runtime = app.state.jarvis

    class Raising:
        def start(self) -> None:
            raise RuntimeError("boom")

    runtime.discord = Raising()
    runtime._start_discord()   # 예외가 올라오지 않는다


# ── HTTP 문 ───────────────────────────────────────────────────────────────────

def test_the_http_doors_need_the_token_and_never_carry_the_bot_token(tmp_path: Path) -> None:
    app = create_app(_config(tmp_path), start_services=False)
    store = MemoryCredentialStore()
    service = _service(tmp_path, store=store, clipboard=FakeClipboard(FAKE_BOT_TOKEN))
    app.state.jarvis.discord = service
    headers = {"X-JARVIS-TOKEN": "test-token"}
    try:
        with TestClient(app) as client:
            assert client.get("/v1/discord/status").status_code == 401
            assert client.post("/v1/discord/token/from-clipboard").status_code == 401
            before = client.get("/v1/discord/status", headers=headers).json()
            assert before["token_saved"] is False and before["stage"] == "no_token"
            assert before["portal_url"] == "https://discord.com/developers/applications"
            saved = client.post("/v1/discord/token/from-clipboard", headers=headers)
            assert saved.status_code == 200 and saved.json()["ok"] is True
            checked = client.post("/v1/discord/recheck", headers=headers).json()
            finished = client.post("/v1/discord/finish", headers=headers).json()
            assert finished["ok"] is True and finished["stage"] == "connected"
            gone = client.post("/v1/discord/disconnect", headers=headers).json()
            assert gone["ok"] is True and gone["token_saved"] is False
            for body in (before, saved.json(), checked, finished, gone):
                assert FAKE_BOT_TOKEN not in json.dumps(body, ensure_ascii=False)
            assert set(before) >= {"installed", "token_saved", "running", "owner_process", "bot_name", "app_id",
                                   "message_content", "servers", "home_channel_id", "allowed_user_ids",
                                   "invite_url", "portal_url", "portal_bot_url", "last_error"}
    finally:
        service.stop()
