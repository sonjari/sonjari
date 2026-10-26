"""되받기의 「진전 없음」은 새로 저장된 장도 본다 (2026-10-25 밤 grove 장표 판 6cda73c3 — 1장에서 접혔다)."""

import inspect

from alture_jarvis import agent
from alture_jarvis.plan_nudges import _read_more_since, _slides_saved


def _slide(index, saved=True, title="t", ok=True):
    return {"tool": "local_make_slide", "ok": ok, "evidence": {"title": title, "index": index, "saved": saved}}


def test_each_new_slide_counts_once() -> None:
    steps = [{"tool": "local_make_slide", "ok": True, "evidence": {"theme": "grove"}}, _slide(1)]
    before = _slides_saved(steps)
    steps += [_slide(2), _slide(2), _slide(3, ok=False), {"tool": "local_write_file", "ok": True, "evidence": {"path": "a"}}]
    assert before == 1 and _slides_saved(steps) == 2
    assert _read_more_since(_slides_saved(steps), before)


def test_redoing_the_same_slide_is_not_progress() -> None:
    steps = [_slide(1)]
    before = _slides_saved(steps)
    steps += [_slide(1), _slide(1)]
    assert not _read_more_since(_slides_saved(steps), before)


def test_the_loop_adds_saved_slides_to_reads() -> None:
    source = inspect.getsource(agent)
    assert "reads_now = len(self._sources_actually_read(steps)) + _slides_saved(steps)" in source
