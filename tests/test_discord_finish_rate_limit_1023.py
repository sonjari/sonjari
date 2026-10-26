"""디스코드 「연결 마치기」가 누를 때마다 「1초 뒤에 다시 눌러 주세요」만 뜨던 일 (2026-10-23 팀 노트북 실사용).

뿌리: 디스코드는 봇의 `/users/@me/guilds` 를 **1초에 한 번**만 받는다(이 PC 봇으로 연달아 두 번 물어 `x-ratelimit-limit: 1` ·
두 번째 429 · retry_after 0.51 을 확인). 홈 채널이 비어 있으면 마무리가 그 목록을 곧바로 두 번 물었다(`_finish` 한 번 +
`pick_home_channel` 한 번). 홈 채널이 이미 있던 PC 는 두 번째를 건너뛰어 멀쩡했다 — 처음 연결하는 사람만 걸린다.

고침: ① 받아 둔 목록을 넘겨 다시 묻지 않는다. ② 그래도 짧은 429(5초 이하)는 기다렸다가 한 번만 다시 묻는다.
옛 가짜 디스코드에는 이 규칙이 없어서 시험이 통과했다 — 여기 가짜는 갈래(bucket)마다 1초에 한 번을 흉내 낸다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from test_messaging_discord_service_1018 import FAKE_BOT_TOKEN, HOME, FakeDiscord, _saved, _service

from alture_jarvis.messaging.credentials import MemoryCredentialStore
from alture_jarvis.messaging.discord_config import SETTINGS_FILE, DiscordSettings
from alture_jarvis.messaging.service import DiscordRest, RATE_LIMIT_WAIT_MAX_SEC


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class RateLimitedDiscord(FakeDiscord):
    """`/users/@me/guilds` 는 1초에 한 번 — 진짜 디스코드처럼(그 사이 시계가 1초 안 갔으면 429)."""

    def __init__(self, clock: Clock, *, retry_after: float = 0.51, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.clock = clock
        self.retry_after = retry_after
        self.last_guilds_at: float | None = None
        self.limited = 0

    def __call__(self, method: str, url: str, headers: dict[str, str], body: Any) -> tuple[int, Any]:
        if url.endswith("/users/@me/guilds"):
            if self.last_guilds_at is not None and self.clock.now - self.last_guilds_at < 1.0:
                self.limited += 1
                # 진짜처럼 남은 시간을 준다(이 PC 실측: 연달아 물으면 0.51). 긴 값을 시험할 때는 그 값을 그대로.
                left = 1.0 - (self.clock.now - self.last_guilds_at)
                return 429, {"retry_after": self.retry_after if self.retry_after > 1 else round(left, 3), "global": False}
            self.last_guilds_at = self.clock.now
        return super().__call__(method, url, headers, body)


def _service_with(tmp_path: Path, discord: RateLimitedDiscord, clock: Clock):  # noqa: ANN202
    service = _service(tmp_path, store=_saved(MemoryCredentialStore()), discord=discord)
    service._sleep = clock.sleep  # noqa: SLF001
    return service


def test_finish_with_an_empty_home_channel_asks_for_the_server_list_once(tmp_path: Path) -> None:
    clock = Clock()
    discord = RateLimitedDiscord(clock)
    service = _service_with(tmp_path, discord, clock)
    try:
        result = service.finish()
    finally:
        service.stop()
    assert result["ok"] is True, result
    guild_calls = [c for c in discord.calls if c[1] == "/users/@me/guilds"]
    assert len(guild_calls) == 1 and discord.limited == 0
    assert DiscordSettings.load(tmp_path / "data" / SETTINGS_FILE).home_channel_id == HOME


def test_a_short_rate_limit_is_waited_out_once_instead_of_asking_the_person(tmp_path: Path) -> None:
    clock = Clock()
    discord = RateLimitedDiscord(clock)
    rest = DiscordRest(FAKE_BOT_TOKEN, discord, sleep=clock.sleep)
    rest.guilds()
    assert rest.guilds()   # 두 번째는 막히지만 남은 만큼(여기선 시계가 안 가서 1초) 기다렸다가 다시 묻는다
    assert discord.limited == 1 and len(clock.slept) == 1 and 1.0 <= clock.slept[0] <= 1.1


def test_a_long_rate_limit_still_comes_back_in_plain_words(tmp_path: Path) -> None:
    clock = Clock()
    discord = RateLimitedDiscord(clock, retry_after=RATE_LIMIT_WAIT_MAX_SEC + 25)
    service = _service_with(tmp_path, discord, clock)
    rest = service._rest(FAKE_BOT_TOKEN)  # noqa: SLF001
    rest.guilds()
    result = service.recheck()   # 곧바로 또 — 30초 기다리라는 말은 기다리지 않는다
    assert result["ok"] is False and result["error"] == "rate_limited" and "30초" in result["message"]
    assert clock.slept == []
