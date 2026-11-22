"""모델 서버가 다시 떠 보관함이 비면 한 번 더 데운다 · 켤 때 앞부분은 도구 설명까지 견준다 (2026-11-16).

★ 맥 03:43 첫 걸음 29.8초: 02:34 에 데웠는데 02:41 에 PC Ollama 가 다시 떴다(Strata → 27B). 데우기는 「켠 뒤 한 번만」이라 몰랐다.
★ 맥 03:49 첫 걸음 32초: 03:45 반영(도구 설명만 바뀜 · attach 인자) 직후 켤 때 맞추기가 이름만 견줘 옛 앞부분을 데웠다.
머리말 ★(일마다 데우면 살아 있는 대화를 잘라 손해)는 그대로 — 그래서 「우리가 올린 것」 · 「모르는 것」은 바뀜으로 치지 않는다.
"""
from __future__ import annotations

import copy

from test_front_prime_1010 import MODEL, TOOLS, _big, _quiet, _send, _used_once, rig  # noqa: F401 — 픽스처 재사용


def _poll(client) -> str:
    client.__dict__["_front_engine_poll_at"] = 0.0
    return client.watch_front_engine()


def _primed_and_quiet(rig):
    _used_once(rig)
    client = rig.started()
    assert client.prime_front()["ok"]
    _quiet(client)
    return client


def test_the_engine_coming_back_on_its_own_primes_once_more(rig) -> None:
    client = _primed_and_quiet(rig)
    assert _poll(client) == "present" and not client.front_prime_due()

    rig.server.resident = {}                       # PC Ollama 를 다시 띄움 — 우리 모델이 내려감
    assert _poll(client) == "absent" and not client.front_prime_due()
    rig.server.resident = {MODEL: 65536}           # 감시 · 다른 것이 다시 올림 — 보관함은 비었다
    assert _poll(client) == "came_back"
    assert client.front_prime_due()
    assert client.prime_front()["ok"]
    assert _poll(client) == "present" and not client.front_prime_due(), "한 번만"


def test_our_own_request_loading_the_model_is_not_a_comeback(rig) -> None:
    """반례: 우리 일이 모델을 올렸으면 그 대화가 살아 있다 — 데우면 그 대화를 자른다."""
    client = _primed_and_quiet(rig)
    _poll(client)
    rig.server.resident = {}
    assert _poll(client) == "absent"
    rig.server.resident = {MODEL: 65536}
    _send(rig, client, _big())                     # 우리 요청이 올렸다
    _quiet(client)
    assert _poll(client) == "present"
    assert not client.front_prime_due()


def test_another_devices_request_loading_the_model_is_not_a_comeback(rig) -> None:
    """반례: 짝지은 맥이 PC 모델을 불러 올린 것도 살아 있는 대화다(PC 쪽 `note_outside_call`)."""
    client = _primed_and_quiet(rig)
    _poll(client)
    rig.server.resident = {}
    _poll(client)
    rig.server.resident = {MODEL: 65536}
    client.note_outside_call()
    _quiet(client)
    assert _poll(client) == "present" and not client.front_prime_due()


def test_not_being_able_to_ask_is_not_absent(rig) -> None:
    """반례: 연결이 끊겨 못 물어본 것을 「내려감」으로 읽으면 다음에 헛데우기를 한다."""
    client = _primed_and_quiet(rig)
    _poll(client)
    real = client._front_resident_or_none
    client._front_resident_or_none = lambda _m: None
    assert _poll(client) == "unknown"
    client._front_resident_or_none = real
    assert _poll(client) == "present" and not client.front_prime_due()


def test_it_asks_at_most_every_poll_interval(rig) -> None:
    client = _primed_and_quiet(rig)
    assert _poll(client) == "present"
    assert client.watch_front_engine() == "wait"


def test_the_switch_turns_the_watch_off(rig) -> None:
    client = _primed_and_quiet(rig)
    rig.config.front_prime_enabled = False
    assert _poll(client) == "off"


def test_a_tool_whose_description_changed_replaces_the_remembered_front(rig) -> None:
    """이름은 그대로 · 설명(인자)만 바뀐 도구도 바뀐 앞부분이다."""
    _used_once(rig)
    client = rig.started()
    changed = copy.deepcopy(TOOLS)
    changed[3]["function"]["parameters"] = {"type": "object", "properties": {"attach": {"type": "array"}}}
    assert client.refresh_front(changed) == "tools_updated"
    assert client.prime_front()["ok"]
    assert rig.server.posts[-1]["tools"] == changed


def test_the_same_tools_still_count_as_the_same(rig) -> None:
    _used_once(rig)
    client = rig.started()
    assert client.refresh_front(copy.deepcopy(TOOLS)) == "same"
