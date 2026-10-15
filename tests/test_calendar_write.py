from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx
import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.events import EventBus
from alture_jarvis.external_actions import ExternalActionStore
from alture_jarvis.google_workspace import GoogleWorkspace, TokenVault
from alture_jarvis.jobs import JobStore
from alture_jarvis.models import RiskLevel
from alture_jarvis.tool_gateway import ToolGateway, ToolSpec
from alture_jarvis.local_computer import LocalComputerTools


def _config(tmp_path: Path) -> JarvisConfig:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    return JarvisConfig(
        runtime_root=tmp_path,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(allowed),
        google_write_enabled=True,
        external_action_ttl_sec=300,
        # google_token_path/google_client_secret_path use a default_factory
        # that ignores runtime_root and falls back to the real production
        # path unless explicitly overridden here -- without this, tests that
        # seed a token would silently overwrite the live OAuth token cache.
        google_client_secret_path=tmp_path / "google" / "client_secret.json",
        google_token_path=tmp_path / "google" / "token.dpapi",
    )


def _seed_token(config: JarvisConfig) -> None:
    vault = TokenVault(config.google_token_path)
    vault.save(
        {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "expires_at": time.time() + 3600,
        }
    )


class Router:
    """Small in-test fake of the Calendar API surface, keyed by method+path."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.events: dict[str, dict] = {}
        self.next_event_id = 1

    def seed_event(self, event_id: str, body: dict) -> None:
        self.events[event_id] = body

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = urlparse(str(request.url)).path
        parts = [part for part in path.split("/") if part]
        # .../calendars/{calendar_id}/events[/{event_id}]
        calendar_index = parts.index("calendars")
        events_index = parts.index("events")
        event_id = parts[events_index + 1] if len(parts) > events_index + 1 else ""

        if request.method == "GET" and event_id:
            event = self.events.get(event_id)
            if event is None:
                return httpx.Response(404, json={"error": "not_found"})
            return httpx.Response(200, json=event)
        if request.method == "GET":
            time_min = parse_qs(urlparse(str(request.url)).query).get("timeMin", [""])[0]
            time_max = parse_qs(urlparse(str(request.url)).query).get("timeMax", [""])[0]
            items = [
                {**value, "id": key}
                for key, value in self.events.items()
                if self._overlaps(value, time_min, time_max)
            ]
            return httpx.Response(200, json={"items": items})
        if request.method == "POST" and not event_id:
            new_id = f"evt-{self.next_event_id}"
            self.next_event_id += 1
            import json as _json

            body = _json.loads(request.content)
            body["id"] = new_id
            body["htmlLink"] = f"https://calendar.google.com/event?eid={new_id}"
            self.events[new_id] = body
            return httpx.Response(200, json=body)
        if request.method == "PATCH" and event_id:
            import json as _json

            changes = _json.loads(request.content)
            existing = self.events.get(event_id, {})
            existing.update(changes)
            existing["id"] = event_id
            existing["htmlLink"] = f"https://calendar.google.com/event?eid={event_id}"
            self.events[event_id] = existing
            return httpx.Response(200, json=existing)
        if request.method == "DELETE" and event_id:
            self.events.pop(event_id, None)
            return httpx.Response(204)
        return httpx.Response(400, json={"error": "unhandled"})

    @staticmethod
    def _overlaps(event: dict, time_min: str, time_max: str) -> bool:
        # Conflict search is advisory; treat any seeded event as a candidate
        # unless bounds are missing.
        return bool(time_min and time_max)

    @property
    def call_count(self) -> int:
        return len(self.requests)


# Every fixture date in this file sits on 2026-08-05. Real wall-clock time
# walked past that on 2026-08-06, which would make the past-date guard reject
# them from then on. Pinning the workspace clock -- rather than pushing the
# fixtures further into the future -- is what stops the same rot next year.
PINNED_NOW = datetime(2026, 8, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))


def _workspace(
    tmp_path: Path,
    config: JarvisConfig,
    router: Router | None = None,
    *,
    now: datetime | None = None,
):
    local_computer = LocalComputerTools(config)
    actions = ExternalActionStore(tmp_path / "data" / "jarvis.db")
    workspace = GoogleWorkspace(config, EventBus(), local_computer=local_computer, actions=actions)
    if router is not None:
        workspace._transport = httpx.MockTransport(router.handler)
    pinned = now or PINNED_NOW
    workspace._now = lambda: pinned  # type: ignore[method-assign]
    return workspace, actions


def test_parse_calendar_time_all_day(tmp_path: Path) -> None:
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config)
    value = workspace._parse_calendar_time("2026-08-05", all_day=True)
    assert value == {"date": "2026-08-05"}


def test_parse_calendar_time_defaults_naive_to_configured_timezone(tmp_path: Path) -> None:
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config)
    value = workspace._parse_calendar_time("2026-08-05T14:00:00", all_day=False)
    assert value["timeZone"] == "Asia/Seoul"
    assert value["dateTime"].endswith("+09:00")


def test_parse_calendar_time_rejects_invalid_value(tmp_path: Path) -> None:
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config)
    with pytest.raises(ValueError, match="calendar_invalid_datetime"):
        workspace._parse_calendar_time("not-a-time", all_day=False)


def test_prepare_create_surfaces_conflicts(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    router.seed_event(
        "evt-existing",
        {
            "summary": "기존 회의",
            "start": {"dateTime": "2026-08-05T14:00:00+09:00", "timeZone": "Asia/Seoul"},
            "end": {"dateTime": "2026-08-05T15:00:00+09:00", "timeZone": "Asia/Seoul"},
        },
    )
    workspace, actions = _workspace(tmp_path, config, router)
    result = workspace.calendar_prepare_create(
        {
            "summary": "신규 회의",
            "start": "2026-08-05T14:30:00+09:00",
            "end": "2026-08-05T15:30:00+09:00",
        }
    )
    assert result["preview"]["conflicts"]
    action = actions.get_prepared_action(result["action_id"])
    assert action["status"] == "prepared"


def test_prepare_create_requires_summary(tmp_path: Path) -> None:
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config)
    with pytest.raises(ValueError, match="summary_required"):
        workspace.calendar_prepare_create(
            {"summary": "", "start": "2026-08-05T14:00:00+09:00", "end": "2026-08-05T15:00:00+09:00"}
        )


def test_prepare_create_rejects_invalid_send_updates(tmp_path: Path) -> None:
    config = _config(tmp_path)
    router = Router()
    workspace, _ = _workspace(tmp_path, config, router)
    with pytest.raises(ValueError, match="send_updates_invalid"):
        workspace.calendar_prepare_create(
            {
                "summary": "회의",
                "start": "2026-08-05T14:00:00+09:00",
                "end": "2026-08-05T15:00:00+09:00",
                "send_updates": "everyone",
            }
        )


def test_create_commits_exactly_once(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    workspace, actions = _workspace(tmp_path, config, router)
    prepared = workspace.calendar_prepare_create(
        {"summary": "신규 회의", "start": "2026-08-05T14:00:00+09:00", "end": "2026-08-05T15:00:00+09:00"}
    )
    write_call_count_before = sum(1 for r in router.requests if r.method in ("POST", "PATCH", "DELETE"))
    assert write_call_count_before == 0

    result = workspace.calendar_create({"action_id": prepared["action_id"]})
    assert result["event_id"]
    write_calls = [r for r in router.requests if r.method == "POST"]
    assert len(write_calls) == 1

    action = actions.get_prepared_action(prepared["action_id"])
    assert action["status"] == "committed"

    # Re-committing must not create a second event.
    second = workspace.calendar_create({"action_id": prepared["action_id"]})
    assert second["duplicate_commit"] is True
    write_calls_after = [r for r in router.requests if r.method == "POST"]
    assert len(write_calls_after) == 1


def test_prepare_update_computes_diff_for_changed_fields_only(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    router.seed_event(
        "evt-1",
        {
            "summary": "기존 제목",
            "start": {"dateTime": "2026-08-05T14:00:00+09:00", "timeZone": "Asia/Seoul"},
            "end": {"dateTime": "2026-08-05T15:00:00+09:00", "timeZone": "Asia/Seoul"},
            "location": "기존 장소",
        },
    )
    workspace, actions = _workspace(tmp_path, config, router)
    result = workspace.calendar_prepare_update({"event_id": "evt-1", "summary": "새 제목"})
    diff_fields = {item["field"] for item in result["preview"]["diff"]}
    assert diff_fields == {"summary"}
    action = actions.get_prepared_action(result["action_id"])
    assert action["payload"]["changes"] == {"summary": "새 제목"}


def test_prepare_update_no_changes_raises(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    router.seed_event(
        "evt-1",
        {
            "summary": "동일 제목",
            "start": {"dateTime": "2026-08-05T14:00:00+09:00", "timeZone": "Asia/Seoul"},
            "end": {"dateTime": "2026-08-05T15:00:00+09:00", "timeZone": "Asia/Seoul"},
        },
    )
    workspace, _ = _workspace(tmp_path, config, router)
    with pytest.raises(ValueError, match="no_changes"):
        workspace.calendar_prepare_update({"event_id": "evt-1", "summary": "동일 제목"})


def test_update_commits_exactly_once(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    router.seed_event(
        "evt-1",
        {
            "summary": "기존 제목",
            "start": {"dateTime": "2026-08-05T14:00:00+09:00", "timeZone": "Asia/Seoul"},
            "end": {"dateTime": "2026-08-05T15:00:00+09:00", "timeZone": "Asia/Seoul"},
        },
    )
    workspace, actions = _workspace(tmp_path, config, router)
    prepared = workspace.calendar_prepare_update({"event_id": "evt-1", "summary": "새 제목"})

    result = workspace.calendar_update({"action_id": prepared["action_id"]})
    assert result["event_id"] == "evt-1"
    patch_calls = [r for r in router.requests if r.method == "PATCH"]
    assert len(patch_calls) == 1

    second = workspace.calendar_update({"action_id": prepared["action_id"]})
    assert second["duplicate_commit"] is True
    patch_calls_after = [r for r in router.requests if r.method == "PATCH"]
    assert len(patch_calls_after) == 1


def test_prepare_delete_shows_real_event_details(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    router.seed_event(
        "evt-1",
        {
            "summary": "삭제될 회의",
            "start": {"dateTime": "2026-08-05T14:00:00+09:00", "timeZone": "Asia/Seoul"},
            "end": {"dateTime": "2026-08-05T15:00:00+09:00", "timeZone": "Asia/Seoul"},
        },
    )
    workspace, _ = _workspace(tmp_path, config, router)
    result = workspace.calendar_prepare_delete({"event_id": "evt-1"})
    assert result["preview"]["summary"] == "삭제될 회의"
    assert result["preview"]["start"]["dateTime"] == "2026-08-05T14:00:00+09:00"


def test_delete_commits_exactly_once(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    router.seed_event(
        "evt-1",
        {
            "summary": "삭제될 회의",
            "start": {"dateTime": "2026-08-05T14:00:00+09:00", "timeZone": "Asia/Seoul"},
            "end": {"dateTime": "2026-08-05T15:00:00+09:00", "timeZone": "Asia/Seoul"},
        },
    )
    workspace, actions = _workspace(tmp_path, config, router)
    prepared = workspace.calendar_prepare_delete({"event_id": "evt-1"})

    result = workspace.calendar_delete({"action_id": prepared["action_id"]})
    assert result["deleted"] is True
    delete_calls = [r for r in router.requests if r.method == "DELETE"]
    assert len(delete_calls) == 1

    second = workspace.calendar_delete({"action_id": prepared["action_id"]})
    assert second["duplicate_commit"] is True
    delete_calls_after = [r for r in router.requests if r.method == "DELETE"]
    assert len(delete_calls_after) == 1


def test_default_send_updates_is_none(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    workspace, _ = _workspace(tmp_path, config, router)
    prepared = workspace.calendar_prepare_create(
        {"summary": "회의", "start": "2026-08-05T14:00:00+09:00", "end": "2026-08-05T15:00:00+09:00"}
    )
    workspace.calendar_create({"action_id": prepared["action_id"]})
    write_call = next(r for r in router.requests if r.method == "POST")
    query = parse_qs(urlparse(str(write_call.url)).query)
    assert query["sendUpdates"] == ["none"]


# ---------------------------------------------------------------------------
# Past-date guard. Written from the 2026-08-20 incident: "내일 오후 3시" became
# 2025-05-21T15:00+09:00 -- a year and three months early -- and the event was
# really created. Nothing downstream could see it (upcoming looks forward only)
# and the bench auto-approved the card without reading it.
# ---------------------------------------------------------------------------


def test_prepare_create_rejects_the_wrong_year_that_actually_happened(tmp_path: Path) -> None:
    config = _config(tmp_path)
    router = Router()
    workspace, actions = _workspace(
        tmp_path,
        config,
        router,
        now=datetime(2026, 8, 20, 15, 3, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    with pytest.raises(ValueError, match="calendar_start_in_past"):
        workspace.calendar_prepare_create(
            {
                "summary": "회의",
                # What the model actually sent when told "내일 오후 3시".
                "start": "2025-05-21T15:00:00+09:00",
                "end": "2025-05-21T16:00:00+09:00",
            }
        )
    # Refusing is only half of it: nothing may be left staged for a human to
    # approve later, and no write may have gone out.
    assert actions.latest_prepared_of_kind("calendar_create") is None
    assert [r for r in router.requests if r.method == "POST"] == []


def test_past_refusal_tells_the_model_what_today_is(tmp_path: Path) -> None:
    """The error is the only channel back to a model that has the wrong date."""
    config = _config(tmp_path)
    workspace, _ = _workspace(
        tmp_path,
        config,
        Router(),
        now=datetime(2026, 8, 20, 15, 3, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    with pytest.raises(ValueError) as excinfo:
        workspace.calendar_prepare_create(
            {
                "summary": "회의",
                "start": "2025-05-21T15:00:00+09:00",
                "end": "2025-05-21T16:00:00+09:00",
            }
        )
    message = str(excinfo.value)
    assert "2026-08-20" in message
    assert "allow_past" in message


def test_allow_past_is_the_door_for_recording_what_already_happened(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    workspace, _ = _workspace(tmp_path, config, router)
    result = workspace.calendar_prepare_create(
        {
            "summary": "지난 주 상담 기록",
            "start": "2026-07-30T14:00:00+09:00",
            "end": "2026-07-30T15:00:00+09:00",
            "allow_past": True,
        }
    )
    assert result["action_id"]


def test_grace_window_allows_a_meeting_starting_right_now(tmp_path: Path) -> None:
    """The timestamp is composed a beat before the tool runs; that is not 'past'."""
    config = _config(tmp_path)
    _seed_token(config)
    now = datetime(2026, 8, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    workspace, _ = _workspace(tmp_path, config, Router(), now=now)
    just_before = now - timedelta(minutes=2)
    result = workspace.calendar_prepare_create(
        {
            "summary": "지금부터 회의",
            "start": just_before.isoformat(),
            "end": (just_before + timedelta(hours=1)).isoformat(),
        }
    )
    assert result["action_id"]


def test_prepare_create_rejects_end_before_start(tmp_path: Path) -> None:
    """No override for this one -- an event ending before it starts is never meant."""
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config, Router())
    with pytest.raises(ValueError, match="calendar_end_not_after_start"):
        workspace.calendar_prepare_create(
            {
                "summary": "회의",
                "start": "2026-08-05T15:00:00+09:00",
                "end": "2026-08-05T14:00:00+09:00",
                "allow_past": True,
            }
        )


def test_single_day_all_day_event_is_not_treated_as_zero_length(tmp_path: Path) -> None:
    """Google's all-day `end` is exclusive: one day is start=D, end=D+1."""
    config = _config(tmp_path)
    _seed_token(config)
    workspace, _ = _workspace(tmp_path, config, Router())
    result = workspace.calendar_prepare_create(
        {"summary": "휴가", "start": "2026-08-06", "end": "2026-08-07", "all_day": True}
    )
    assert result["action_id"]


def test_all_day_event_in_the_past_is_refused_too(tmp_path: Path) -> None:
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config, Router())
    with pytest.raises(ValueError, match="calendar_start_in_past"):
        workspace.calendar_prepare_create(
            {"summary": "휴가", "start": "2025-05-21", "end": "2025-05-22", "all_day": True}
        )


def test_preview_carries_today_so_a_human_can_compare(tmp_path: Path) -> None:
    """★ The approval card is where a wrong year is caught by eye -- but only if
    today's date is printed next to the event's."""
    config = _config(tmp_path)
    _seed_token(config)
    workspace, _ = _workspace(tmp_path, config, Router())
    result = workspace.calendar_prepare_create(
        {"summary": "회의", "start": "2026-08-06T14:00:00+09:00", "end": "2026-08-06T15:00:00+09:00"}
    )
    assert result["preview"]["today"] == "2026-08-05"
    assert result["preview"]["now_kst"].startswith("2026-08-05")


def test_renaming_a_past_event_does_not_need_allow_past(tmp_path: Path) -> None:
    """Only a moved window is guarded. Editing the title of a meeting that
    already happened is ordinary."""
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    router.seed_event(
        "evt-old",
        {
            "summary": "옛 회의",
            "start": {"dateTime": "2026-07-01T14:00:00+09:00", "timeZone": "Asia/Seoul"},
            "end": {"dateTime": "2026-07-01T15:00:00+09:00", "timeZone": "Asia/Seoul"},
        },
    )
    workspace, _ = _workspace(tmp_path, config, router)
    result = workspace.calendar_prepare_update({"event_id": "evt-old", "summary": "이름 고침"})
    assert result["action_id"]


def test_prepare_update_refuses_moving_an_event_into_the_past(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    router.seed_event(
        "evt-future",
        {
            "summary": "회의",
            "start": {"dateTime": "2026-08-10T14:00:00+09:00", "timeZone": "Asia/Seoul"},
            "end": {"dateTime": "2026-08-10T15:00:00+09:00", "timeZone": "Asia/Seoul"},
        },
    )
    workspace, _ = _workspace(tmp_path, config, router)
    with pytest.raises(ValueError, match="calendar_start_in_past"):
        workspace.calendar_prepare_update(
            {
                "event_id": "evt-future",
                "start": "2025-05-21T14:00:00+09:00",
                "end": "2025-05-21T15:00:00+09:00",
            }
        )


def test_grace_minutes_come_from_config_not_a_hard_constant(tmp_path: Path) -> None:
    """★ Caps that live in three places (dataclass default, env loader, a
    constant buried in a function) let the lowest one silently win. This one has
    to read from config."""
    config = _config(tmp_path)
    config.calendar_past_grace_minutes = 120
    _seed_token(config)
    now = datetime(2026, 8, 5, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    workspace, _ = _workspace(tmp_path, config, Router(), now=now)
    an_hour_ago = now - timedelta(hours=1)
    result = workspace.calendar_prepare_create(
        {
            "summary": "회의",
            "start": an_hour_ago.isoformat(),
            "end": now.isoformat(),
        }
    )
    assert result["action_id"]


# ---------------------------------------------------------------------------
# Double-commit guard. 2026-08-20: one instruction produced two events 69
# seconds apart with an identical payload_hash, both committed. The approval
# polling pressed prepare twice -- but a human pressing the card twice does the
# same thing, so this is not a bench-only defect.
# ---------------------------------------------------------------------------


def test_one_instruction_prepared_twice_creates_only_one_event(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    workspace, actions = _workspace(tmp_path, config, router)
    booking = {
        "summary": "회의",
        "start": "2026-08-06T15:00:00+09:00",
        "end": "2026-08-06T16:00:00+09:00",
    }

    first = workspace.calendar_prepare_create(dict(booking))
    second = workspace.calendar_prepare_create(dict(booking))
    assert first["action_id"] != second["action_id"]

    created = workspace.calendar_create({"action_id": first["action_id"]})
    repeated = workspace.calendar_create({"action_id": second["action_id"]})

    posts = [r for r in router.requests if r.method == "POST"]
    assert len(posts) == 1, "두 번째 커밋이 캘린더에 또 썼다"
    assert repeated["duplicate_commit"] is True
    assert repeated["event_id"] == created["event_id"]
    assert actions.get_prepared_action(second["action_id"])["status"] == "duplicate"


def test_the_ledger_names_which_action_actually_did_the_work(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    workspace, actions = _workspace(tmp_path, config, router)
    booking = {
        "summary": "회의",
        "start": "2026-08-06T15:00:00+09:00",
        "end": "2026-08-06T16:00:00+09:00",
    }
    first = workspace.calendar_prepare_create(dict(booking))
    second = workspace.calendar_prepare_create(dict(booking))
    workspace.calendar_create({"action_id": first["action_id"]})
    workspace.calendar_create({"action_id": second["action_id"]})

    twin = actions.get_prepared_action(second["action_id"])
    assert twin["error"] == f"duplicate_of:{first['action_id']}"


def test_a_genuinely_different_booking_is_not_deduped(tmp_path: Path) -> None:
    """Same title, different hour -- two real events, two real writes."""
    config = _config(tmp_path)
    _seed_token(config)
    router = Router()
    workspace, _ = _workspace(tmp_path, config, router)
    first = workspace.calendar_prepare_create(
        {"summary": "회의", "start": "2026-08-06T15:00:00+09:00", "end": "2026-08-06T16:00:00+09:00"}
    )
    second = workspace.calendar_prepare_create(
        {"summary": "회의", "start": "2026-08-06T17:00:00+09:00", "end": "2026-08-06T18:00:00+09:00"}
    )
    workspace.calendar_create({"action_id": first["action_id"]})
    workspace.calendar_create({"action_id": second["action_id"]})
    assert len([r for r in router.requests if r.method == "POST"]) == 2


# ---------------------------------------------------------------------------
# 밖으로 나가는 일정은 등급이 내려가도 사람 앞에 선다.
#
# `google_calendar_create` 를 L1 으로 내리자는 근거는 "되돌리기가 실제로 돈다"
# 하나다. 참석자가 붙는 순간 그 전제가 깨진다 -- 초대 메일은 일정을 지워도 돌아오지
# 않고, 메일을 안 보내도 남의 캘린더에는 이미 떠 있다.
#
# 오늘까지 커밋된 캘린더 일정 3건이 전부 attendees=[] 라, 이 경로는 라이브에서 한
# 번도 밟힌 적이 없다. 처음 밟을 때 승인 없이 밟게 두지 않는다.
# ---------------------------------------------------------------------------


def _risk_of(workspace, action_id: str):
    return workspace._calendar_create_risk({"action_id": action_id})


def test_an_event_only_i_can_see_is_the_low_risk_case(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_token(config)
    workspace, _ = _workspace(tmp_path, config, Router())
    prepared = workspace.calendar_prepare_create(
        {"summary": "혼자 볼 일정", "start": "2026-08-06T14:00:00+09:00", "end": "2026-08-06T15:00:00+09:00"}
    )
    assert _risk_of(workspace, prepared["action_id"]) == RiskLevel.L1


def test_attendees_keep_it_in_front_of_a_person(tmp_path: Path) -> None:
    """메일을 안 보내도 남의 캘린더에는 뜬다. 지우는 것으로 없던 일이 되지 않는다."""
    config = _config(tmp_path)
    _seed_token(config)
    workspace, _ = _workspace(tmp_path, config, Router())
    prepared = workspace.calendar_prepare_create(
        {
            "summary": "면담",
            "start": "2026-08-06T14:00:00+09:00",
            "end": "2026-08-06T15:00:00+09:00",
            "attendees": ["someone@example.com"],
        }
    )
    assert _risk_of(workspace, prepared["action_id"]) == RiskLevel.L2


def test_sending_invitations_keeps_it_in_front_of_a_person(tmp_path: Path) -> None:
    """★ 나간 메일은 되돌리기가 없다."""
    config = _config(tmp_path)
    _seed_token(config)
    workspace, _ = _workspace(tmp_path, config, Router())
    prepared = workspace.calendar_prepare_create(
        {
            "summary": "면담",
            "start": "2026-08-06T14:00:00+09:00",
            "end": "2026-08-06T15:00:00+09:00",
            "attendees": ["someone@example.com"],
            "send_updates": "all",
        }
    )
    assert _risk_of(workspace, prepared["action_id"]) == RiskLevel.L2


def test_an_unknown_action_is_not_assumed_safe(tmp_path: Path) -> None:
    """모르면 사람 앞에 세운다 -- 등급 판단이 실패했을 때의 규칙과 같다."""
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config, Router())
    assert _risk_of(workspace, "그런-거-없음") == RiskLevel.L2
    assert _risk_of(workspace, "") == RiskLevel.L2


def test_dynamic_risk_can_only_raise_never_lower(tmp_path: Path) -> None:
    """★ 이 파일이 지키는 가장 중요한 것.

    등급을 내릴 수 있게 만들면 그것이 곧 승인 우회로가 된다 -- `_approved` 인자가
    정확히 그렇게 뚫려 있었다. 지금 base 는 L2 이므로, 혼자 볼 일정에 L1 을
    돌려줘도 **실제 등급은 L2 그대로여야 한다.**
    """
    config = _config(tmp_path)
    _seed_token(config)
    workspace, _ = _workspace(tmp_path, config, Router())
    prepared = workspace.calendar_prepare_create(
        {"summary": "혼자 볼 일정", "start": "2026-08-06T14:00:00+09:00", "end": "2026-08-06T15:00:00+09:00"}
    )
    spec = ToolSpec(
        name="google_calendar_create",
        description="",
        parameters={},
        risk_level=RiskLevel.L2,
        handler=lambda a: {},
        dynamic_risk=workspace._calendar_create_risk,
    )
    assert spec.effective_risk({"action_id": prepared["action_id"]}) == RiskLevel.L2


def test_the_guard_is_actually_registered_on_the_tool(tmp_path: Path) -> None:
    """★ 명세를 만들어 놓고 도구에 안 달면 아무 일도 안 일어난다 --
    이 저장소에서 실제로 있었던 일이다(risk_of 가 죽어 있었다)."""
    config = _config(tmp_path)
    workspace, _ = _workspace(tmp_path, config, Router())
    gateway = ToolGateway(JobStore(tmp_path / "jobs.db"), EventBus())
    workspace.register(gateway)
    spec = gateway._tools.get("google_calendar_create")
    assert spec is not None
    assert spec.dynamic_risk is not None, "가드를 만들어 놓고 도구에 안 달았다"
