"""줄의 숫자가 그 줄의 페이지가 아니라 **다른 줄의 페이지**에서 왔으면 잡고, 맞게 썼던 줄이면 되돌린다 (2026-10-04 허깅페이스 판 5749ff16).

엑셀의 Qwen3.5-9B 줄에 LFM2.5 카드의 숫자(74.0 · 70.0 · 18.0 · 32.0 · 40.0)가 들어갔다. 두 카드를 다 읽은 판이라
「읽은 적 없는 숫자」 검사는 통과했다. 그 줄은 35걸음째 첫 쓰기에는 맞았고(`Q4_K_M 14.0%`), 13걸음 뒤 다시 쓸 때 틀려졌다 —
그 사이 Qwen 카드는 다시 읽지 않았다. 실제 판의 걸음·원문으로 돌려 확인한 것(첫 쓰기 0건 · 둘째 쓰기 그 줄만)을 줄여 시험으로 둔다.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from alture_jarvis import agent as agent_module
from alture_jarvis.agent import BrowserAgent

QWEN = "https://huggingface.co/DuoNeural/Qwen3.5-9B-TAP-DPQ-v8-GGUF"
LFM = "https://huggingface.co/DuoNeural/LFM2.5-8B-A1B-TAP-DPQ-v7-GGUF"
HEADER = ["모델 이름", "저장소 주소", "파라미터 크기", "벤치마크 이름", "벤치마크 수치", "파일 크기"]
QWEN_RIGHT = ["DuoNeural Qwen3.5-9B TAP-DPQ v8 GGUF", QWEN, "9B", "MATH-500", "Q4_K_M 14.0% / IQ2_XXS 4.0% (Champion)", "Q4_K_M 5.36 GiB"]
QWEN_MIXED = ["DuoNeural Qwen3.5-9B TAP-DPQ v8 GGUF", QWEN, "9B", "MATH-500 / LiveCodeBench / GPQA",
              "Q4_K_M: MATH-500 74.0% (BF16 70.0% 대비), LiveCodeBench 18.0%, GPQA 32.0%, Hermes 40.0%", "Q4_K_M 5.36 GiB"]
LFM_ROW = ["DuoNeural LFM2.5-8B-A1B TAP-DPQ v7 GGUF", LFM, "8B", "MATH-500 / AIME 2026",
           "Q4_K_M: MATH-500 74.0% (BF16 70.0% 대비), AIME 2026 23.33%", "Q4_K_M 4.82 GiB"]

BODIES = {
    BrowserAgent._url_key(QWEN): (
        "Qwen3.5-9B TAP-DPQ v8\nModel Tier | BPW | Disk Size | MATH-500 | LiveCodeBench | GPQA Diamond\n"
        "Vanilla FP16 Baseline | 16.0 | 17.14 GiB | 14.0% | 100.0% | 28.0%\n"
        "Q4_K_M (TAP-DPQ v8) | 4.5 | 5.36 GiB | 14.0% | 100.0% | 20.0%\nIQ2_XXS | 2.24 | 3.71 GiB | 4.0% | 66.0% | 8.0%"
    ),
    BrowserAgent._url_key(LFM): (
        "LFM2.5-8B-A1B TAP-DPQ v7\nQuantization Arm | Storage | MATH-500 | AIME 2026 | LiveCodeBench | GPQA | Hermes\n"
        "Vanilla BF16 Baseline | 16.94 GiB | 70.0% | 26.67% | 18.0% | 32.0% | 40.0%\n"
        "Q4_K_M (TAP-DPQ v7) | 4.82 GiB | 74.0% | 23.33% | 16.0% | 34.0% | 40.0%"
    ),
}


def _read(step: int, url: str, title: str) -> dict[str, Any]:
    return {"step": step, "tool": "browser_extract", "ok": True, "evidence": {"url": url, "title": title}}


def _write(step: int, *rows: list[str], header: list[str] | None = None, path: str = "models.xlsx") -> dict[str, Any]:
    return {
        "step": step, "tool": "local_write_document", "ok": True,
        "arguments": {"format": "xlsx", "path": path, "sheets": {"모델": [list(header or HEADER), *[list(row) for row in rows]]}},
    }


def _steps(*writes: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _read(1, QWEN, "DuoNeural/Qwen3.5-9B-TAP-DPQ-v8-GGUF · Hugging Face"),
        _read(2, LFM, "DuoNeural/LFM2.5-8B-A1B-TAP-DPQ-v7-GGUF · Hugging Face"),
        *writes,
    ]


def _agent(bodies: dict[str, str] = BODIES) -> BrowserAgent:
    agent = object.__new__(BrowserAgent)
    agent._page_bodies = lambda _steps, _job: bodies  # type: ignore[method-assign]
    return agent


# --- 숫자 걷기 ----------------------------------------------------------------

def test_plain_numbers_normalise_and_skip_addresses() -> None:
    found = BrowserAgent._plain_numbers("74.0% · 1,234원 · 5.36 GiB · v8 · https://example.com/item/987654")

    assert found == {"74", "1234", "5.36"}


# --- 대조 --------------------------------------------------------------------

def test_a_row_carrying_another_rows_numbers_is_named() -> None:
    notes = BrowserAgent._row_page_binding_check("", _steps(_write(3, QWEN_MIXED, LFM_ROW)), BODIES)

    assert "다른 줄의 페이지에 있습니다" in notes
    assert "DuoNeural Qwen3.5-9B TAP-DPQ v8 GGUF" in notes and "74" in notes and "70" in notes
    assert "LFM2.5" not in notes.split("다른 줄의 페이지에 있습니다")[1].split(".**")[0], "제 페이지 값을 쓴 줄은 부르지 않는다"


def test_rows_that_match_their_own_pages_are_quiet() -> None:
    assert BrowserAgent._row_page_binding_check("", _steps(_write(3, QWEN_RIGHT, LFM_ROW)), BODIES) == ""


def test_numbers_that_are_on_no_other_rows_page_are_not_blamed() -> None:
    """목록에서 온 값·계산값은 제 페이지에 없어도 「섞인 것」이 아니다 — 다른 줄의 페이지에 있어야 섞인 것이다."""
    computed = [QWEN_RIGHT[0], QWEN, "9B", "MATH-500", "Q4_K_M 14.0% · 내려받기 91,234회 · 좋아요 512 · 순위 77위", "5.76 GB"]

    assert BrowserAgent._row_page_binding_check("", _steps(_write(3, computed, LFM_ROW)), BODIES) == ""


def test_one_or_two_shared_numbers_are_let_through() -> None:
    two = [QWEN_RIGHT[0], QWEN, "9B", "MATH-500", "Q4_K_M 14.0% (다른 모델은 74.0%, 23.33%)", "5.36 GiB"]

    assert BrowserAgent._row_page_binding_check("", _steps(_write(3, two, LFM_ROW)), BODIES) == ""


def test_a_table_about_one_page_has_nothing_to_compare_with() -> None:
    only = {BrowserAgent._url_key(QWEN): BODIES[BrowserAgent._url_key(QWEN)]}

    assert BrowserAgent._rows_with_borrowed_numbers([(QWEN_MIXED, BrowserAgent._url_key(QWEN))], only) == []


# --- 되돌리기 -----------------------------------------------------------------

def test_a_row_that_was_right_is_put_back_when_the_rewrite_mixes_it(tmp_path: Path) -> None:
    steps = _steps(_write(3, QWEN_RIGHT), _write(4, QWEN_MIXED, LFM_ROW))
    out = tmp_path / "models.xlsx"

    message = _agent()._restore_grounded_rows("local_write_document", {"ok": True, "path": str(out)}, steps, "job")

    rows = steps[-1]["arguments"]["sheets"]["모델"]
    assert rows[1] == QWEN_RIGHT, "앞서 맞게 쓴 줄로 되돌린다"
    assert rows[2] == LFM_ROW, "다른 줄은 그대로"
    assert out.exists() and steps[-1]["rows_restored"] == 1
    assert message.startswith("★") and "되돌려" in message and "74" in message
    assert BrowserAgent._row_page_binding_check("", steps, BODIES) == "", "되돌린 뒤에는 대조가 조용하다"


def test_nothing_is_put_back_without_an_earlier_right_row(tmp_path: Path) -> None:
    out = {"ok": True, "path": str(tmp_path / "models.xlsx")}
    first_time = _steps(_write(3, QWEN_MIXED, LFM_ROW))
    was_mixed_before = _steps(_write(3, QWEN_MIXED, LFM_ROW), _write(4, QWEN_MIXED, LFM_ROW))
    other_columns = _steps(_write(3, QWEN_RIGHT, header=[*HEADER[:-1], "크기"]), _write(4, QWEN_MIXED, LFM_ROW))
    other_file = _steps(_write(3, QWEN_RIGHT, path="first.xlsx"), _write(4, QWEN_MIXED, LFM_ROW))

    for steps in (first_time, was_mixed_before, other_columns, other_file):
        assert _agent()._restore_grounded_rows("local_write_document", out, steps, "job") == ""
        assert steps[-1]["arguments"]["sheets"]["모델"][1] == QWEN_MIXED
    assert not (tmp_path / "models.xlsx").exists(), "손대지 않았으면 파일도 다시 쓰지 않는다"


def test_a_rewrite_that_stays_right_is_left_alone(tmp_path: Path) -> None:
    better = [*QWEN_RIGHT[:4], "Q4_K_M 14.0% / IQ2_XXS 4.0% / FP16 14.0% (GPQA 20.0%)", QWEN_RIGHT[5]]
    steps = _steps(_write(3, QWEN_RIGHT), _write(4, better, LFM_ROW))

    assert _agent()._restore_grounded_rows("local_write_document", {"ok": True, "path": str(tmp_path / "m.xlsx")}, steps, "job") == ""
    assert steps[-1]["arguments"]["sheets"]["모델"][1] == better


def test_the_restore_runs_before_the_page_check() -> None:
    source = inspect.getsource(BrowserAgent._record_observation) if hasattr(BrowserAgent, "_record_observation") else inspect.getsource(agent_module)

    assert source.index("self._restore_grounded_rows(name, observation, steps, job_id)") < source.index(
        "write_feedback = self._write_grounding_feedback(name, observation, steps, job_id)"
    )


# --- 다시 읽은 페이지 · 판 기록의 장부 ---------------------------------------------

def test_a_page_read_twice_keeps_both_readings() -> None:
    agent = object.__new__(BrowserAgent)
    ledger = [
        {"type": "body_read", "ok": True, "source_id": QWEN, "job_id": "job", "step": 1},
        {"type": "body_read", "ok": True, "source_id": QWEN + "/", "job_id": "job", "step": 5},
        {"type": "listing", "ok": True, "source_id": LFM, "job_id": "job", "step": 6},
    ]
    texts = {1: "첫머리: Q4_K_M 14.0%", 5: "아래쪽 표: IQ3_XXS 2.0%"}
    agent._evidence_view = lambda _steps, _job="": (ledger, lambda _j, step: texts.get(step, ""), None)  # type: ignore[method-assign]

    bodies = agent._page_bodies([], "job")

    assert list(bodies) == [BrowserAgent._url_key(QWEN)]
    assert bodies[BrowserAgent._url_key(QWEN)] == "첫머리: Q4_K_M 14.0%\n아래쪽 표: IQ3_XXS 2.0%", "처음 읽은 것이 앞에 온다"


def test_the_job_record_carries_every_number_that_was_read() -> None:
    """바깥 연결(MCP)의 「도구가 준 적 없는 숫자」는 판 기록의 장부만 본다 — 판 안의 대조와 같은 재료를 실어야 한다(사고 Q)."""
    source = inspect.getsource(agent_module)

    assert "tool_numbers_body=sorted(set(tool_numbers_body) | numbers_read_in(messages))," in source
