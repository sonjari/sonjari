"""찾기 실패는 **도구가 달라도** 같은 벽이다 (2026-09-17).

MS 스토어 판: ui_find_target(search box) → snapshot(0개) → find(0건) → wait → snapshot → ui_find_target(search input)
→ site_search(검색칸 없음) … 16걸음. 반복 경보는 같은 도구·같은 인자에만 걸려 한 번도 안 울렸다.
"""

from __future__ import annotations

from alture_jarvis import agent as agent_module
from alture_jarvis.agent import (
    LOCATE_WALL_AFTER,
    _is_locate_miss,
    _locate_wall_notice,
    _repeat_notice,
    _trailing_locate_misses,
)


def _obs(ok: bool, **result) -> dict:
    return {"ok": ok, "result": result, "error": result.pop("_error", "")}


def test_the_ms_store_sequence_is_read_as_one_wall() -> None:
    sequence = [
        ("ui_find_target", _obs(False, _error="ui_target_not_found:search box — 화면을 3번 봤는데")),
        ("browser_snapshot", _obs(True, element_count=0, empty_reason="absent")),
        ("browser_find", _obs(True, match_count=0, matches=[])),
        ("browser_wait", _obs(True)),
        ("browser_site_search", _obs(False, _error="site_search_box_not_found:apps.microsoft.com")),
    ]
    steps: list[dict] = []
    walls = []
    for name, observation in sequence:
        miss = _is_locate_miss(name, observation)
        if miss and 1 + _trailing_locate_misses(steps) >= LOCATE_WALL_AFTER:
            walls.append((name, 1 + _trailing_locate_misses(steps)))
        steps.append({"tool": name, "ok": observation["ok"], **({"locate_miss": True} if miss else {})})
    assert walls == [("browser_find", 3), ("browser_site_search", 4)], "세 번째부터 알리고, 기다리기는 셈을 끊지 않는다"


def test_a_real_success_breaks_the_count() -> None:
    steps = [
        {"tool": "ui_find_target", "locate_miss": True},
        {"tool": "browser_snapshot", "locate_miss": True},
        {"tool": "browser_click", "ok": True},
        {"tool": "browser_find", "locate_miss": True},
    ]
    assert _trailing_locate_misses(steps) == 1


def test_ordinary_results_are_not_misses() -> None:
    assert not _is_locate_miss("browser_snapshot", _obs(True, element_count=40))
    assert not _is_locate_miss("browser_find", _obs(True, match_count=2))
    assert not _is_locate_miss("local_read_text_file", _obs(False, _error="element_not_found"))
    assert not _is_locate_miss("browser_open", _obs(False, _error="net::ERR_NAME_NOT_RESOLVED"))


def test_the_notice_is_labelled_as_a_tool_message_and_does_not_block() -> None:
    noticed = _locate_wall_notice(_obs(False, _error="ui_target_not_found:x", instruction="원래 안내"), 3)
    text = noticed["result"]["instruction"]
    assert "도구가 보낸 안내" in text and "사용자 말이 아니다" in text
    assert "browser_click_at" in text and text.endswith("원래 안내")
    assert noticed["ok"] is False and noticed["result"]["locate_wall"] == 3


def test_the_same_failure_twice_is_now_actually_announced() -> None:
    """`_repeat_notice` 문서는 「같은 실패는 두 번째에」인데 부르는 문이 `>= 3` 뿐이라 안 울렸다."""
    source = open(agent_module.__file__, encoding="utf-8").read()
    assert "if repeat_count >= 3 or same_failure_count >= 2:" in source
    noticed = _repeat_notice(_obs(False, _error="x"), tool="site_run", repeat_count=2, same_failure_count=2)
    assert "같은 실패가 2번" in noticed["result"]["instruction"]
