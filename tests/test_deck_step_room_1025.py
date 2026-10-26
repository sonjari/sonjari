"""장표 판은 남은 장 수만큼 걸음 자리를 둔다 (2026-10-25 밤 grove 판 de242e91 — 15걸음 중 8걸음이 돌려받기, 5장에서 끝)."""

import inspect

from alture_jarvis import agent
from alture_jarvis.plan_nudges import _deck_in_progress, _deck_steps_owed


def _slide(index, total=7, title="t", ok=True, baked=False):
    evidence = {"title": title, "index": index, "total": total, "saved": True}
    if baked:
        evidence["output_path"] = "x.pptx"
    return {"tool": "local_make_slide", "ok": ok, "evidence": evidence}


def test_room_is_slides_left_plus_two() -> None:
    assert _deck_steps_owed([]) == 0
    assert _deck_steps_owed([{"tool": "local_make_slide", "ok": True, "evidence": {"theme": "grove"}}]) == 0  # 장 수를 아직 모른다
    steps = [_slide(1), _slide(2), _slide(2), _slide(3, ok=False)]
    assert _deck_steps_owed(steps) == 7 - 2 + 2


def test_a_baked_deck_needs_no_more_room() -> None:
    steps = [_slide(i) for i in range(1, 7)] + [_slide(7, baked=True)]
    assert _deck_steps_owed(steps) == 0


def test_the_loop_keeps_the_room_under_the_cap() -> None:
    source = inspect.getsource(agent)
    assert "step_limit = max(step_limit, len(steps) + min(deck_owed, max(0, cap_room(self.config, steps))))" in source


def test_the_loop_keeps_time_for_the_deck_under_the_lease() -> None:
    """daisy-days 판 ac529631: 긴 모델 호출 중 시간 한도를 넘겨 「남았다」 되받기가 막혔다 — 장표 판은 한 구간씩 시간을 남긴다."""
    source = inspect.getsource(agent)
    block = source[source.index("deck_owed = _deck_steps_owed(steps)"):][:1200]
    assert "time.monotonic() - segment_started < max(1, self.config.agent_autonomous_lease_sec)" in block
    assert "deadline = max(deadline, time.monotonic() + max(1, self.config.browser_task_timeout_sec))" in block


def test_a_deck_counts_as_in_progress_from_the_theme_pick() -> None:
    """daisy-days 둘째 판 7d298ae0: 결 안내만 두 번 읽고 시간이 끝났다 — 결을 고른 순간부터 장표 판이다."""
    pick = {"tool": "local_make_slide", "ok": True, "evidence": {"theme": "daisy-days"}}
    assert _deck_in_progress([pick]) and not _deck_in_progress([])
    assert not _deck_in_progress([pick, _slide(1, baked=True)])
    assert "if deck_owed or _deck_in_progress(steps):" in inspect.getsource(agent)
