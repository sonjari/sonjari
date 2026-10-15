"""걸음이 **실제로 본 것**이 화면까지 가는가.

이 파일이 지키는 것은 하나다: **도구가 돌려준 내용이 어느 칸에도 못 들어가서
사라지는 일이 없어야 한다.**

지난 사고들이 전부 그 모양이었다 — `browser_hover` 의 증거가 목록에 없어서
버려졌고(장부), 새 도구가 분류표에 없어서 성공률 분모에서 빠졌고(눈금), 본문
23%가 잘렸는데 아무 말이 없었다(사고 Q). 셋 다 **에러가 아니라 침묵으로** 왔다.

그래서 여기서는 두 가지를 센다. 종류가 제대로 갈리는가, 그리고 **잘렸을 때
잘렸다고 적히는가.**
"""

from __future__ import annotations

import json

from alture_jarvis.observations import (
    MODEL_TRANSCRIPT_CHARS,
    ObservationStore,
    shape,
)


def test_code_file_becomes_code_with_language() -> None:
    kind, title, payload, _ = shape(
        "local_read_text_file",
        {"path": r"E:\a\ui\src\workspace\ComputerPane.tsx"},
        {"path": r"E:\a\ui\src\workspace\ComputerPane.tsx", "content": "export function A() {}\nreturn 1"},
    )
    assert kind == "code"
    assert title == "ComputerPane.tsx"
    assert payload["language"] == "tsx"
    assert payload["line_count"] == 2
    # ★ 경로가 실려야 한다. 예전 장부는 `path` 를 통째로 빼서, 파일을 읽어도
    #   화면이 **어느 파일인지 몰랐다.** 그게 이 파일이 생긴 이유다.
    assert payload["path"].endswith("ComputerPane.tsx")


def test_markdown_is_a_document_not_code() -> None:
    """`.md` 는 색칠할 코드가 아니라 읽을 문서다 — 줄번호를 붙이면 읽기 나빠진다."""
    kind, _, payload, _ = shape(
        "local_read_document", {}, {"path": "docs/handoff.md", "content": "# 제목\n본문"}
    )
    assert kind == "document"
    assert payload["format"] == "md"


def test_xlsx_text_becomes_a_table() -> None:
    """엑셀은 `[시트: 이름]` + 탭 구분 행으로 온다(`document_reader._xlsx`).

    그 모양을 화면이 아니라 **여기서** 표로 세운다 — 화면마다 다시 쪼개면
    자리마다 다르게 쪼개진다.
    """
    text = "[시트: 2026-08]\n항목\t단가\n기본 자동화\t1200000\n크롤링\t800000"
    kind, _, payload, _ = shape("local_read_document", {}, {"path": "x/단가표.xlsx", "content": text})
    assert kind == "table"
    sheet = payload["sheets"][0]
    assert sheet["name"] == "2026-08"
    assert sheet["columns"] == ["항목", "단가"]
    assert sheet["rows"] == [["기본 자동화", "1200000"], ["크롤링", "800000"]]
    assert sheet["row_count"] == 2


def test_rows_from_lookup_tools_become_a_table() -> None:
    kind, _, payload, _ = shape(
        "admission_quant_lookup",
        {},
        {"rows": [{"대학": "가", "컷": 1.8}, {"대학": "나", "컷": 2.4, "비고": "학종"}]},
    )
    assert kind == "table"
    # 열 순서는 **먼저 나온 순서**다. 정렬하면 사람이 아는 순서가 깨진다.
    assert payload["columns"] == ["대학", "컷", "비고"]
    assert payload["rows"][1] == ["나", "2.4", "학종"]


def test_any_list_of_dicts_becomes_a_table_whatever_the_key_is() -> None:
    """★ 키 이름 목록으로 고르면 새 도구가 빠진다.

    라이브에서 `windows_list_open_windows` 가 `windows` 키를 쓴다는 이유만으로 표가
    아니라 날 JSON 으로 떨어졌다(2026-08-19). 도구는 102개고 각자 제 이름을 쓴다 —
    이름이 아니라 **모양**으로 골라야 한다.
    """
    kind, _, payload, _ = shape(
        "windows_list_open_windows",
        {},
        {"action": "windows_list_open_windows", "count": 2,
         "windows": [{"title": "크롬", "minimized": False}, {"title": "메모장", "minimized": True}]},
    )
    assert kind == "table"
    assert payload["field"] == "windows"
    assert payload["columns"] == ["title", "minimized"]


def test_known_keys_win_when_a_result_carries_two_lists() -> None:
    """목록이 둘이면 판마다 다른 것이 표로 뜨면 안 된다 — 아는 이름이 먼저다."""
    _, _, payload, _ = shape(
        "some_tool",
        {},
        {"debug": [{"a": 1}], "rows": [{"b": 2}]},
    )
    assert payload["field"] == "rows"


def test_browser_result_becomes_a_page_with_url() -> None:
    kind, title, payload, _ = shape(
        "browser_extract",
        {},
        {"url": "https://kmong.com/gig/1", "title": "업무 자동화", "text": "본문"},
    )
    assert kind == "page"
    assert title == "업무 자동화"
    assert payload["url"] == "https://kmong.com/gig/1"
    assert payload["text"] == "본문"


def test_prepare_tools_become_a_draft_carrying_action_id() -> None:
    """초안은 내용이 `external_actions` 에 따로 있다. 화면이 그 자리에서 승인하려면
    `action_id` 를 쥐고 있어야 한다."""
    kind, _, payload, _ = shape(
        "google_gmail_prepare_send", {}, {"action_id": "act-1", "summary": "메일 초안"}
    )
    assert kind == "draft"
    assert payload["action_id"] == "act-1"


def test_search_results_become_a_file_list() -> None:
    kind, title, payload, _ = shape(
        "local_search_files",
        {"path": r"E:\docs"},
        {"matches": [{"name": "a.md", "size": 10}, {"name": "b.md", "size": 20}]},
    )
    assert kind == "files"
    assert "2개" in title
    assert payload["columns"] == ["name", "size"]


def test_unknown_tool_is_kept_not_dropped() -> None:
    """★ 어느 칸에도 안 떨어지는 도구는 **버리지 않는다.**

    도구는 102개고 계속 는다. 새 도구가 조용히 사라지는 것이 제일 나쁜 결말이고,
    우리는 같은 구멍으로 눈금이 두 번 샜다.
    """
    kind, title, payload, _ = shape("gpu_status", {}, {"name": "3090", "temp_c": 61})
    assert kind == "note"
    assert title == "gpu_status"
    assert json.loads(payload["text"])["temp_c"] == 61


def test_truncation_is_written_down_not_hidden() -> None:
    """잘렸는데 안 적으면 「없던 내용」과 구별이 안 된다 — 사고 Q 그대로다."""
    long_text = "가" * 200_000
    _, _, payload, cut = shape("browser_extract", {}, {"url": "u", "text": long_text})
    assert len(payload["text"]) < len(long_text)
    assert cut["store"] is True
    assert cut["char_count"] == 200_000


def test_tool_truncation_flag_is_carried_through() -> None:
    _, _, _, cut = shape(
        "local_read_document",
        {},
        {"path": "a.txt", "content": "짧다", "truncated": True, "char_count": 90_000},
    )
    assert cut["tool"] is True
    assert cut["char_count"] == 90_000


def test_store_records_what_the_model_saw() -> None:
    """화면이 「모델이 본 것」과 「실제로 있던 것」을 나란히 놓을 수 있어야 한다."""
    store = ObservationStore()
    item = store.record(
        job_id="j1",
        step=1,
        tool="browser_extract",
        arguments={"url": "u"},
        observation={"ok": True, "result": {"url": "u", "text": "가" * 40_000}},
    )
    assert item.truncation["to_model"] == MODEL_TRANSCRIPT_CHARS
    assert item.truncation["model_cut"] is True


def test_store_caps_steps_and_jobs() -> None:
    """상한이 셋이다 — 잡 수·걸음 수·글자 수. 여기서 두 개를 확인한다."""
    store = ObservationStore(max_jobs=2, max_steps=3)
    for step in range(5):
        store.record(job_id="j1", step=step, tool="t", arguments={}, observation={"ok": True, "result": {}})
    assert [row["step"] for row in store.list_steps("j1")] == [2, 3, 4]

    for job in ("j2", "j3"):
        store.record(job_id=job, step=0, tool="t", arguments={}, observation={"ok": True, "result": {}})
    assert store.stats()["jobs"] == 2
    assert store.list_steps("j1") == []


def test_store_round_trips_one_step() -> None:
    store = ObservationStore()
    store.record(
        job_id="j1",
        step=7,
        tool="local_read_text_file",
        arguments={"path": "a.py"},
        observation={"ok": True, "status": "completed", "result": {"path": "a.py", "content": "x = 1"}},
    )
    found = store.get("j1", 7)
    assert found is not None
    assert found["kind"] == "code"
    assert found["payload"]["text"] == "x = 1"
    assert found["ok"] is True
    assert store.get("j1", 99) is None


def test_failed_step_is_kept_with_its_error() -> None:
    """실패한 걸음이야말로 열어 봐야 한다. 성공만 보관하면 고장이 안 보인다."""
    store = ObservationStore()
    store.record(
        job_id="j1",
        step=2,
        tool="browser_open",
        arguments={"url": "u"},
        observation={"ok": False, "status": "failed", "error": "timeout", "result": {}},
    )
    row = store.list_steps("j1")[0]
    assert row["ok"] is False
    assert row["error"] == "timeout"
