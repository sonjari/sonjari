"""판 종류마다 앞부분을 기억하고 쉬는 동안 차례로 데운다 (2026-11-17).

맥 새 계정 시험(4B · M4 16GB · 읽기 초당 약 340): 워드(도구 28) · 파일(81) · 코드(20) 판은 도구 목록이 달라, 하나만 기억하던
데우기로는 판 종류가 바뀔 때마다 첫 부르기가 처음부터 읽었다(26.6 · 70.5 · 36.8초). 맥 Ollama 에서 잰 것: 세 모양을 차례로
데운 뒤 셋 다 진짜 요청을 보내니 읽기 0.18 · 0.21 · 0.18초 — 서버가 셋을 한꺼번에 들고 있다(B 를 데워도 A 가 안 지워짐).

눈금 주의: 이 시험은 **무엇을 언제 보내는가**만 본다. 빨라지는지는 맥 실측(설계 문서 7절)으로 쟀다.
"""
from __future__ import annotations

import copy
import json

from test_front_prime_1010 import MODEL, SYSTEM, TOOLS, _big, _quiet, _send, rig  # noqa: F401 — 픽스처 재사용


def _tools(prefix: str, count: int) -> list[dict]:
    return [{"type": "function", "function": {"name": f"{prefix}_{i}", "description": "d", "parameters": {}}} for i in range(count)]


WORD, FILES, CODE, EXTRA = _tools("word", 28), _tools("file", 81), _tools("code", 20), _tools("extra", 22)


def _jobs(rig, *kinds: list[dict]) -> None:
    """지난번 켰을 때 이 종류의 판을 이 순서로 했다."""
    client = rig.started()
    for tools in kinds:
        _send(rig, client, _big(tools=tools))


def _warm_all(client) -> list[int]:
    done = []
    while client.front_prime_due():
        row = client.prime_front()
        assert row["ok"], row
        done.append(len(client._fronts_or_load()) and row["tools"])
    return done


def test_each_kind_is_remembered_and_warmed_once_oldest_first(rig) -> None:
    _jobs(rig, WORD, FILES, CODE)
    client = rig.started()

    assert _warm_all(client) == [28, 81, 20], "오래 안 쓴 것부터 — 가장 최근(코드)이 마지막에 데워져 서버 칸에 남는다"
    assert not client.front_prime_due(), "모양마다 한 번만"
    sent = len(rig.server.posts)
    _quiet(client)
    assert client.prime_front()["skipped"] == "all_warm" and len(rig.server.posts) == sent


def test_only_the_most_recent_kinds_are_kept(rig) -> None:
    _jobs(rig, WORD, FILES, CODE, EXTRA)
    client = rig.started()
    assert [len(front["tools"]) for front in client._fronts_or_load()] == [22, 20, 81]
    assert _warm_all(client) == [81, 20, 22]


def test_a_kind_a_job_already_read_is_not_warmed_but_the_others_are(rig) -> None:
    """큰 일이 제 앞부분을 직접 읽으면 그 대화가 서버에 있다 — 그 모양을 데우면 그 대화를 지운다. 다른 모양은 데워도 그 대화가 남는다(맥 실측)."""
    _jobs(rig, WORD, FILES, CODE)
    client = rig.started()
    _send(rig, client, _big(tools=FILES))
    _quiet(client)

    assert _warm_all(client) == [28, 20]
    assert all(len(post["tools"]) != 81 for post in rig.server.posts[-2:])


def test_the_same_kind_with_a_changed_description_replaces_the_old_one(rig) -> None:
    changed = copy.deepcopy(WORD)
    changed[3]["function"]["description"] = "설명이 바뀜"
    _jobs(rig, WORD, CODE, changed)
    fronts = rig.started()._fronts_or_load()
    assert [len(front["tools"]) for front in fronts] == [28, 20]
    assert fronts[0]["tools"][3]["function"]["description"] == "설명이 바뀜"


def test_the_old_single_front_file_still_loads(rig) -> None:
    old = {"model": MODEL, "tools": WORD, "system": SYSTEM, "think": "medium",
           "options": {"num_ctx": 65536, "temperature": 0.1}, "key": "oldkey"}
    rig.config.data_dir.mkdir(parents=True, exist_ok=True)
    (rig.config.data_dir / "front_prime.json").write_text(json.dumps(old), encoding="utf-8")
    client = rig.started()
    assert client.prime_front()["ok"] and len(rig.server.posts[-1]["tools"]) == 28


def test_a_kind_for_a_model_that_is_not_loaded_is_skipped_not_forced(rig) -> None:
    previous = rig.started()
    _send(rig, previous, _big(tools=WORD))
    _send(rig, previous, _big(tools=CODE, model="other-model:4b"))
    client = rig.started()
    before = len(rig.server.posts)
    rig.server.resident = {MODEL: 65536}

    assert client.prime_front()["ok"] and len(rig.server.posts[-1]["tools"]) == 28
    assert client.prime_front()["skipped"] == "not_resident", "남의 모델을 올리지 않는다"
    assert len(rig.server.posts) == before + 1


def test_the_engine_coming_back_warms_every_kind_again(rig) -> None:
    _jobs(rig, WORD, CODE)
    client = rig.started()
    assert _warm_all(client) == [28, 20]
    client.__dict__["_front_engine_poll_at"] = 0.0
    rig.server.resident = {}
    assert client.watch_front_engine() == "absent"
    rig.server.resident = {MODEL: 65536}
    client.__dict__["_front_engine_poll_at"] = 0.0
    assert client.watch_front_engine() == "came_back"
    assert _warm_all(client) == [28, 20]


def test_refresh_updates_narrow_kinds_by_name_and_drops_ones_with_a_missing_hand(rig) -> None:
    _jobs(rig, WORD[:25], CODE)
    client = rig.started()
    now = copy.deepcopy(WORD + CODE[:19])          # 코드 판의 손 하나(code_19)가 사라졌다
    now[2]["function"]["description"] = "새 설명"

    assert client.refresh_front(now) == "tools_updated"
    [word] = client._fronts_or_load()
    assert [tool["function"]["name"] for tool in word["tools"]] == [f"word_{i}" for i in range(25)], "제 고른 도구와 순서는 그대로"
    assert word["tools"][2]["function"]["description"] == "새 설명"
    assert client.prime_front()["ok"] and rig.server.posts[-1]["tools"][2]["function"]["description"] == "새 설명"


def test_refresh_replaces_a_wide_front_wholesale_and_does_not_keep_duplicates(rig) -> None:
    _jobs(rig, TOOLS, [*TOOLS, *_tools("new", 1)])
    client = rig.started()
    now = [*TOOLS, *_tools("new", 1)]
    client.refresh_front(now)
    assert [len(front["tools"]) for front in client._fronts_or_load()] == [31], "넓은 판 둘이 같은 지금 목록이 됐다 — 하나만"


def test_a_real_request_stops_the_round_and_the_rest_waits_for_the_next_quiet(rig) -> None:
    _jobs(rig, WORD, FILES, CODE)
    client = rig.started()
    assert client.prime_front()["ok"]
    _send(rig, client, _big(tools=CODE))
    assert not client.front_prime_due(), "방금 요청이 나갔다"
    _quiet(client)
    assert _warm_all(client) == [81], "코드는 그 일이 직접 읽었다 — 남은 파일만"


def test_after_background_work_only_the_most_recent_kind_is_warmed_again(rig) -> None:
    """서기가 보관함을 밀었어도 다시 데우는 것은 예전처럼 하나 — 셋 다 다시 데우면 살아 있는 대화를 더 자른다."""
    _jobs(rig, WORD, FILES, CODE)
    client = rig.started()
    assert _warm_all(client) == [28, 81, 20]
    client.background_chat("정리", "x", model=MODEL, options={"num_ctx": 65536})
    _quiet(client)
    assert _warm_all(client) == [20]


def test_after_a_job_the_rest_waits_for_a_longer_quiet(rig) -> None:
    """맥 4B 에선 모양 하나가 37~92초 — 일 사이 짧은 틈마다 데우기 시작하면 사람 요청과 부딪힌다."""
    import time

    _jobs(rig, WORD, FILES)
    client = rig.started()
    client.__dict__["_last_send_at"] = time.monotonic() - 10
    assert client.front_prime_due(), "켠 직후 일 전에는 짧은 틈이면 된다"
    _send(rig, client, _big(tools=FILES))
    client.__dict__["_last_send_at"] = time.monotonic() - 10
    assert not client.front_prime_due(), "일을 한 뒤 10초 조용한 것으로는 아직"
    client.__dict__["_last_send_at"] = time.monotonic() - 60
    assert client.front_prime_due()
