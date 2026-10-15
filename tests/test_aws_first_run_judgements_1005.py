"""된 판을 「못 했다」고 말한 자리 셋 (2026-10-05 AWS 영어 윈도우 · Tesla T4 · qwen3.5:9b).

둘째 과제 「Read the 3 newest arXiv cs.CL papers and make a comparison table document」(d547bb35).
16걸음 전부 성공, `Documents\\Sonjari\\comparison_table.docx` 37,257바이트가 실제로 있었다. 화면은 이랬다:

    Requested 0/2
    ✗ Use the site's own sort / filters — 최신순 정렬 안 걸림      ← `arxiv.org/list/cs.CL/recent` 를 읽었다
    ✗ Make the actual file — No output that can be opened          ← 파일은 있고 열린다
    카드: Pressed, but couldn't confirm it took effect … pressing again could process it twice   ← 파일 쓰기였다

9B 가 문서 내용을 글자열로 보내 블록 일부가 깨졌고(`unreadable_blocks`), 도구가 `verified=false` 를 돌려준 것이 뿌리다.
요구가 미달인 것은 맞다(시킨 것이 빠졌다) — 그러나 **본 것**은 사실대로 말해야 한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis import plan
from alture_jarvis.attention import AttentionService
from alture_jarvis.events import EventBus

ARXIV = "Read the 3 newest arXiv cs.CL papers and make a comparison table document"


def _wrote(path: Path, *, verified: bool) -> dict[str, Any]:
    return {
        "step": 16, "tool": "local_write_document", "ok": True,
        "status": "" if verified else "executed_unverified",
        "arguments": {"path": path.name},
        "evidence": {"action": "local_write_document", "path": str(path), "verified": verified},
    }


def _artifact(steps: list[dict[str, Any]]) -> tuple[bool, str]:
    reqs = [req for req in plan.extract(ARXIV, must_observe=True) if req.kind == "artifact"]
    (_, ok, saw), = plan.check(reqs, sources=[], steps=steps, answer="")
    return ok, saw


# ── 1. 산출물 ────────────────────────────────────────────────────────────────


def test_a_file_made_with_parts_left_out_is_not_called_missing(tmp_path: Path) -> None:
    made = tmp_path / "comparison_table.docx"
    made.write_bytes(b"PK" + b"x" * 400)

    ok, saw = _artifact([_wrote(made, verified=False)])

    assert not ok, "빠진 것이 있으면 요구는 여전히 미달이다"
    assert saw == "1개 만들었지만 내용 일부가 빠짐"
    assert plan.display_saw(saw, "en") == "1 made, but part of the content was left out"


def test_a_verified_file_is_still_confirmed(tmp_path: Path) -> None:
    made = tmp_path / "comparison_table.docx"
    made.write_bytes(b"PK" + b"x" * 400)

    assert _artifact([_wrote(made, verified=True)]) == (True, "1개 존재·열기 확인")


def test_nothing_made_is_still_nothing(tmp_path: Path) -> None:
    assert _artifact([_wrote(tmp_path / "never_written.docx", verified=False)]) == (False, "열 수 있는 산출물 없음")
    assert _artifact([]) == (False, "열 수 있는 산출물 없음")


# ── 2. 「최신」 목록 주소 ────────────────────────────────────────────────────


def test_a_recent_listing_address_counts_as_newest_first() -> None:
    assert "sort:newest" in plan.url_filter_kinds("https://arxiv.org/list/cs.CL/recent")
    assert "sort:newest" in plan.url_filter_kinds("https://arxiv.org/list/cs.CL/recent?skip=104&show=50")
    assert "sort:newest" in plan.url_filter_kinds("https://example.com/blog/latest")


def test_an_ordinary_address_is_not_a_sort() -> None:
    assert plan.url_filter_kinds("https://arxiv.org/abs/2610.02206") == set()
    assert plan.url_filter_kinds("https://example.com/news/recently-added-things") == set()


def test_the_arxiv_run_meets_the_newest_requirement() -> None:
    reqs = [req for req in plan.extract(ARXIV, must_observe=True) if req.kind == "filter"]
    steps = [{"tool": "browser_open", "ok": True, "arguments": {"url": "https://arxiv.org/list/cs.CL/recent"},
              "evidence": {"url": "https://arxiv.org/list/cs.CL/recent"}}]
    (_, ok, saw), = plan.check(reqs, sources=["https://arxiv.org/list/cs.CL/recent"], steps=steps, answer="")
    assert ok, saw


# ── 3. 알림 카드 ─────────────────────────────────────────────────────────────


def _service() -> tuple[AttentionService, EventBus]:
    events = EventBus()
    return AttentionService(events, None, None), events


def test_an_unverified_file_write_does_not_raise_the_pressed_card() -> None:
    service, _ = _service()
    observation = {"ok": True, "status": "executed_unverified",
                   "result": {"action": "local_write_document", "verified": False, "unreadable_blocks": "블록 2개를 …"}}

    assert service.check(job_id="j1", tool="local_write_document", arguments={}, observation=observation) is None


def test_an_unverified_click_still_calls_a_person() -> None:
    service, _ = _service()
    observation = {"ok": True, "result": {"action": "clicked", "verified": False}}

    notice = service.check(job_id="j1", tool="browser_click", arguments={}, observation=observation)

    assert notice is not None and notice["code"] == "change_not_verified"
