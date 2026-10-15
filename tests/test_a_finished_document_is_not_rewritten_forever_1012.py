"""확인까지 끝난 문서를 또 쓰고, 그것도 확인됐으면 판을 접는다 (2026-10-12 밤).

네 번 이어 묻기(4B · 창 32K)의 셋째 판이 같은 워드 파일을 열네 번 썼다. 첫 번째만 고칠 것이 있었고 둘째부터는 전부 「확인됨」
이었다 — 모델은 글을 조금씩 바꿔 계속 다시 보냈고 판은 시간 한도(197초)에서야 접혔다. 되풀이를 알리는 장치는 인자가 같은
호출만 본다.
"""
from __future__ import annotations

import inspect

from alture_jarvis import agent
from alture_jarvis.plan_nudges import _rewrote_a_finished_document, _write_came_back_clean

PATH = r"C:\Users\someone\Documents\JARVIS\가상_보고서.docx"


def _write(path: str = PATH, *, ok: bool = True, verified: object = "True", **more: object) -> dict:
    return {"tool": "local_write_document", "ok": ok, "evidence": {"output_path": path, "format": "docx", "verified": verified, **more}}


def test_two_clean_writes_of_the_same_file_in_a_row_is_the_end() -> None:
    notes = _write(verified="False", shape_notes="['표에 머리줄만 있다']")
    steps = [notes, _write(), _write()]
    assert _rewrote_a_finished_document(steps) == PATH.casefold()
    # 그날의 모양 — 첫 쓰기는 고칠 것이 있었으니, 고쳐 쓴 둘째까지는 정당하다.
    assert not _rewrote_a_finished_document(steps[:2])
    assert not _rewrote_a_finished_document(steps[:1])


def test_a_write_that_still_has_something_to_fix_is_not_finished() -> None:
    assert _write_came_back_clean(_write()) == PATH.casefold()
    for step in (
        _write(verified="False"),
        _write(verified=None),
        _write(shape_notes=["제목이 없다"]),
        _write(unreadable_blocks="블록 1개를 못 읽었습니다"),
        _write(blanked_unverified_cells=3),
        _write(ok=False),
        {"tool": "local_write_file", "ok": True, "evidence": {"output_path": PATH, "verified": "True"}},
    ):
        assert not _write_came_back_clean(step)
    assert not _rewrote_a_finished_document([_write(), _write(shape_notes=["제목이 없다"])])


def test_another_file_or_a_step_in_between_is_a_different_job() -> None:
    other = PATH.replace("보고서", "요약")
    assert not _rewrote_a_finished_document([_write(), _write(other)]), "파일이 둘이면 둘 다 만드는 중이다"
    read = {"tool": "local_read_document", "ok": True, "evidence": {}}
    assert not _rewrote_a_finished_document([_write(), read]), "쓰고 나서 읽어 본 것은 되풀이가 아니다"
    # 사이에 다른 걸음이 끼었다가 다시 쓴 것 — 무언가 보고 고친 것일 수 있다. 연달아 둘일 때만이다.
    assert not _rewrote_a_finished_document([_write(), read, _write()])
    assert _rewrote_a_finished_document([_write(), read, _write(), _write()])


def test_the_loop_ends_the_job_only_when_nothing_else_is_owed() -> None:
    source = inspect.getsource(agent)
    block = source[source.index('rewritten = "" if finish_now else _rewrote_a_finished_document(steps)'):]
    block = block[:block.index("if gate:")]
    assert "if rewritten and plan_all_met(" in block, "시킨 것이 남은 판은 접지 않는다"
    assert '"agent_document_settled"' in block and "self.store.add_audit(" in block
    assert "finish_now = True" in block and 'stop_reason = "wrapped_up:goal_met"' in block
    assert "다시 쓰지 말고" in block
