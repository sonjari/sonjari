"""「이어서 해줘」는 덜 끝난 앞 판을 잇는다 · 파일 찾기는 얕은 곳부터 보고 다 못 봤으면 그렇게 말한다 (2026-10-05 실사용).

대표가 「E 폴더에서 자비스 전략안 파일을 찾아 읽고 …」를 맡겼다(판 568ca034 · 259초 · 걸음 상한).

1. 파일 찾기를 다섯 번 불러 한 번에 18~49초씩 **매번 처음부터** 같은 2만 개를 긁었고 다섯 번 0건이었다. 파일은 있었다 —
   깊이 우선으로는 앞쪽 폴더의 깊은 속에서 상한을 다 썼고, 넓이 우선으로는 22,566번째였다.
2. 답 끝에 손자리가 「『이어서 해줘』라고 하시면 이어갑니다」라고 적었는데, 그대로 보내자 다음 판(75dc2329)은 **도구 0번 ·
   기억으로 답함**으로 「(손자리가 다음 일을 진행했습니다.) … 열어보겠습니다」를 냈다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.runtime import JarvisRuntime

ASKED = "자비스 전략안 로컬 파일을 e폴더에서 찾아서 보고 우리가 가진 혜자가 뭔지 말해주라"
PROMISE = (
    "E:\\에서 JARVIS(자비스) 전략안 파일을 찾았습니다. 발견된 전략안 파일들을 열어보겠습니다.\n\n"
    "(손자리가 다음 할 일을 예고만 하고 멈췄습니다 — 그 일은 실행되지 않았습니다. 「이어서 해줘」라고 하시면 이어갑니다.)"
)


# --- 1. 이어서 해줘 -------------------------------------------------------------

class _Memory:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def recent(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        return list(self.rows)


def _runtime(rows: list[dict[str, Any]]) -> JarvisRuntime:
    runtime = object.__new__(JarvisRuntime)
    runtime.memory = _Memory(rows)  # type: ignore[attr-defined]
    return runtime


def _row(role: str, content: str, **metadata: Any) -> dict[str, Any]:
    return {"role": role, "content": content, "metadata": metadata}


def test_continue_after_sonjaris_own_invitation_inherits_the_request() -> None:
    runtime = _runtime([_row("user", ASKED), _row("assistant", PROMISE)])

    assert runtime._unfinished_turn_base("s", "이어서 해줘") == ASKED
    assert runtime._last_turn_promised("s") is True, "「열어보겠습니다」가 낱말표에 없어도 손자리가 적은 초대가 있으면 예고로 끝난 판이다"


def test_continue_after_a_partial_turn_inherits_the_request() -> None:
    rows = [_row("user", ASKED), _row("assistant", "공고 3개 중 2개를 정리했습니다.", agent_verification={"completion_state": "partial"})]

    assert _runtime(rows)._unfinished_turn_base("s", "계속 진행해줘") == ASKED


def test_continue_after_a_failed_turn_inherits_the_request() -> None:
    rows = [_row("user", ASKED), _row("assistant", "시간이 다 돼 멈췄습니다.", unfinished="failed")]

    assert _runtime(rows)._unfinished_turn_base("s", "마저 해줘") == ASKED


def test_a_second_continue_reaches_back_to_the_real_request() -> None:
    """앞 말도 「이어서 해줘」였으면 한 칸 더 거슬러 올라간다 — 그날 대화가 꼭 이 모양이었다."""
    rows = [
        _row("user", ASKED), _row("assistant", PROMISE),
        _row("user", "이어서 해줘"), _row("assistant", PROMISE),
    ]

    assert _runtime(rows)._unfinished_turn_base("s", "이어서 해줘") == ASKED


def test_a_finished_turn_is_not_continued() -> None:
    rows = [_row("user", ASKED), _row("assistant", "전략안의 혜자는 세 가지입니다.", agent_verification={"completion_state": "complete"})]

    assert _runtime(rows)._unfinished_turn_base("s", "이어서 해줘") == ""


def test_a_new_request_is_not_a_continuation() -> None:
    runtime = _runtime([_row("user", ASKED), _row("assistant", PROMISE)])

    assert runtime._unfinished_turn_base("s", "사람인에서 대전 정규직 공고 5개를 찾아 엑셀로 만들어 줘") == ""


def test_memory_that_cannot_be_read_falls_back_to_the_old_route() -> None:
    runtime = object.__new__(JarvisRuntime)

    class _Broken:
        def recent(self, *_args: Any, **_kw: Any) -> list[dict[str, Any]]:
            raise RuntimeError("db locked")

    runtime.memory = _Broken()  # type: ignore[attr-defined]

    assert runtime._unfinished_turn_base("s", "이어서 해줘") == ""


# --- 2. 파일 찾기 ---------------------------------------------------------------

def _tools(tmp_path: Path, **overrides: Any) -> tuple[LocalComputerTools, Path]:
    allowed = tmp_path / "drive"
    allowed.mkdir()
    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
        local_file_allowed_roots=str(allowed), local_read_roots=str(allowed), **overrides,
    )
    return LocalComputerTools(config), allowed


def _deep_tree(root: Path, files: int) -> None:
    """앞쪽 폴더의 깊은 속에 파일이 잔뜩 — 깊이 우선이면 여기서 상한을 다 쓴다."""
    deep = root / "aaa_first" / "x" / "y" / "z"
    deep.mkdir(parents=True)
    for index in range(files):
        (deep / f"junk_{index:05d}.txt").write_text("", encoding="utf-8")


def test_a_shallow_file_is_found_before_a_deep_folder_uses_up_the_limit(tmp_path: Path, monkeypatch: Any) -> None:
    tools, root = _tools(tmp_path, local_file_scan_limit=1000)
    monkeypatch.setattr(LocalComputerTools, "_NAME_SCAN_GRACE_SEC", 0.0)  # 찾은 뒤 더 훑는 덤을 끈다 — 순서만 본다
    _deep_tree(root, 1500)
    (root / "zzz_last" / "docs").mkdir(parents=True)
    (root / "zzz_last" / "docs" / "JARVIS_전략안_20260907.md").write_text("전략", encoding="utf-8")

    found = tools.search_files({"query": "jarvis_전략안", "root": str(root)})

    assert found["count"] == 1 and found["items"][0]["name"] == "JARVIS_전략안_20260907.md"
    assert found["scanned"] < 1000, "얕은 폴더부터 보면 깊은 속의 1,500개를 긁기 전에 나온다"


def test_a_search_that_did_not_finish_says_so_instead_of_none(tmp_path: Path) -> None:
    tools, root = _tools(tmp_path, local_file_scan_limit=1000)
    _deep_tree(root, 1500)
    (root / "bbb" / "p" / "q" / "r" / "s").mkdir(parents=True)

    found = tools.search_files({"query": "없는이름", "root": str(root)})

    assert found["count"] == 0 and found["complete"] is False and found["truncated"] is True
    assert found["unscanned_folders"] >= 1
    assert found["instruction"].startswith("★") and "「없다」가 아니다" in found["instruction"]


def test_a_search_that_saw_everything_reports_complete(tmp_path: Path) -> None:
    tools, root = _tools(tmp_path)
    (root / "a").mkdir()
    (root / "a" / "memo.txt").write_text("", encoding="utf-8")

    found = tools.search_files({"query": "없는이름", "root": str(root)})

    assert found["count"] == 0 and found["complete"] is True and "instruction" not in found


def test_the_same_job_does_not_walk_the_disk_twice(tmp_path: Path, monkeypatch: Any) -> None:
    tools, root = _tools(tmp_path)
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "report_2026.xlsx").write_text("", encoding="utf-8")
    (root / "a" / "notes.md").write_text("", encoding="utf-8")
    first = tools.search_files({"query": "없는이름", "root": str(root), "__job_id": "job1"})
    assert first["complete"] is True

    import alture_jarvis.local_computer as module

    def no_disk(_path: str) -> Any:
        raise AssertionError("이미 훑은 자리를 다시 긁었다")

    monkeypatch.setattr(module.os, "scandir", no_disk)
    second = tools.search_files({"query": "report", "root": str(root), "__job_id": "job1"})

    assert second["count"] == 1 and second["from_memory"] is True


def test_another_job_starts_fresh(tmp_path: Path) -> None:
    """판이 바뀌면 다시 훑는다 — 그사이 생긴 파일을 놓치지 않게."""
    tools, root = _tools(tmp_path)
    tools.search_files({"query": "new", "root": str(root), "__job_id": "job1"})
    (root / "new_file.txt").write_text("", encoding="utf-8")

    assert tools.search_files({"query": "new", "root": str(root), "__job_id": "job2"})["count"] == 1


def test_skipped_and_sensitive_places_stay_out(tmp_path: Path) -> None:
    tools, root = _tools(tmp_path)
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "target_inside.js").write_text("", encoding="utf-8")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "target_hidden.txt").write_text("", encoding="utf-8")
    (root / "ok").mkdir()
    (root / "ok" / "target_ok.txt").write_text("", encoding="utf-8")

    names = {item["name"] for item in tools.search_files({"query": "target", "root": str(root)})["items"]}

    assert names == {"target_ok.txt"}


def test_a_long_walk_tells_the_screen_where_it_is(tmp_path: Path, monkeypatch: Any) -> None:
    tools, root = _tools(tmp_path)
    for index in range(6):
        (root / f"folder_{index}").mkdir()
        (root / f"folder_{index}" / "file.txt").write_text("", encoding="utf-8")
    said: list[tuple[str, str]] = []
    tools.progress_sink = lambda job_id, message: said.append((job_id, message))
    monkeypatch.setattr(LocalComputerTools, "_NAME_SCAN_NOTE_SEC", 0.0)

    tools.search_files({"query": "없는이름", "root": str(root), "__job_id": "job1"})

    assert said and said[0][0] == "job1"
    assert "파일을 찾는 중" in said[-1][1] and "훑음" in said[-1][1]


# --- 3. 읽지 말라고 한 파일 찾기 (판 b4b71589) -----------------------------------

def test_finding_a_file_without_reading_it_does_not_demand_a_read() -> None:
    from alture_jarvis import plan

    ask = "E 드라이브에서 이름에 JARVIS_전략안이 든 파일을 찾아서 경로만 알려줘. 파일을 열어 읽지는 말고 새 파일도 만들지 마."

    assert [r.kind for r in plan.extract(ask, must_observe=True, observe_from={"local"})] == []


def test_reading_is_still_demanded_when_it_was_asked() -> None:
    from alture_jarvis import plan

    kinds = [r.kind for r in plan.extract("E 폴더에서 전략안 파일을 찾아서 읽고 요약해줘", must_observe=True, observe_from={"local"})]

    assert "observe" in kinds


def test_a_partial_dont_open_in_web_research_keeps_the_read() -> None:
    """「다른 페이지는 열지 마」는 일부만 막는 말이다 — 나머지는 읽어야 한다."""
    from alture_jarvis import plan

    ask = "이 사이트 첫 화면의 위젯에 적힌 소요 시간을 그대로 옮겨 줘. 다른 페이지는 열지 마."

    assert "observe" in [r.kind for r in plan.extract(ask, must_observe=True, observe_from={"web"})]


def test_once_found_the_tool_does_not_ask_to_be_called_again(tmp_path: Path, monkeypatch: Any) -> None:
    tools, root = _tools(tmp_path, local_file_scan_limit=1000)
    monkeypatch.setattr(LocalComputerTools, "_NAME_SCAN_GRACE_SEC", 0.0)
    _deep_tree(root, 1500)
    (root / "zzz_last").mkdir()
    (root / "zzz_last" / "target.md").write_text("", encoding="utf-8")

    found = tools.search_files({"query": "target", "root": str(root)})

    assert found["count"] == 1 and found["complete"] is False
    assert "여기서 멈추고" in found["instruction"] and "다시 부르지 마라" in found["instruction"]


def test_continue_after_an_untagged_answer_that_ended_on_a_promise() -> None:
    """그날 그 방의 실제 모양 — 마지막 답이 기억으로 낸 「…열어보겠습니다」(꼬리표 없음)."""
    rows = [
        _row("user", ASKED), _row("assistant", PROMISE),
        _row("user", "이어서 해줘"),
        _row("assistant", "(손자리가 다음 일을 진행했습니다.)\n\nE:\에서 JARVIS 전략안 파일을 찾았습니다. 발견된 전략안 파일들을 열어보겠습니다."),
    ]

    assert _runtime(rows)._unfinished_turn_base("s", "이어서 해줘") == ASKED


def test_an_answer_that_reported_a_result_is_not_continued_without_a_tag() -> None:
    rows = [_row("user", ASKED), _row("assistant", "전략안의 혜자는 세 가지입니다. 무료, 미터기 없음, 검증입니다.")]

    assert _runtime(rows)._unfinished_turn_base("s", "이어서 해줘") == ""


# --- 4. 「E 드라이브」는 이 PC 의 디스크다 (판 b4b71589) ----------------------------

def test_a_drive_letter_is_this_pcs_disk_not_an_outside_source() -> None:
    from alture_jarvis.agent import named_sources

    assert named_sources("E 드라이브에서 보고서.xlsx 파일을 찾아서 경로를 알려줘") == []
    assert named_sources("이 PC의 E 드라이브에서 이름에 「JARVIS_전략안」이 들어간 파일을 찾아서 경로만 알려줘") == []
    assert named_sources("C드라이브에서 큰 파일 찾아줘") == []
    assert named_sources("외장 드라이브에서 사진 폴더 찾아줘") == []


def test_google_drive_is_still_an_outside_source() -> None:
    from alture_jarvis.agent import named_sources

    assert named_sources("구글 드라이브에서 계약서 파일을 찾아서 내용을 알려줘") == ["드라이브"]
    assert named_sources("E 드라이브 말고 구글 드라이브에서 찾아줘") == ["드라이브"]


# --- 5. 답이 말한 읽은 개수 ↔ 걸음 기록 (판 9cbe4dde) -------------------------------

def _read_step(n: int, url: str) -> dict[str, Any]:
    return {"step": n, "tool": "browser_extract", "ok": True, "error": "", "arguments": {},
            "evidence": {"url": url, "title": "t"}, "evidence_record": {"source_id": url, "type": "body_read", "ok": True}}


def test_a_claim_of_more_reads_than_the_record_is_stated_as_a_fact() -> None:
    from alture_jarvis.agent import claimed_reads_note

    steps = [_read_step(n, f"https://www.saramin.co.kr/zf_user/jobs/view?rec_idx={n}") for n in range(1, 7)]
    note = claimed_reads_note("사람인에서 검색하고 검색 결과 9건을 직접 열어 지역을 확인했습니다.", steps)

    assert "9건을 직접 열어" in note and "6곳" in note


def test_plans_failures_and_matching_counts_are_left_alone() -> None:
    from alture_jarvis.agent import claimed_reads_note

    steps = [_read_step(n, f"https://example.com/p/{n}") for n in range(1, 4)]
    for answer in (
        "로그인이 풀리면 프로젝트 5개를 직접 열어 읽고 예산을 확인하겠습니다.",
        "지시하신 5개의 프로젝트를 모두 열어보려 시도했으나 본문을 읽지 못했습니다.",
        "나머지 5개의 프로젝트를 읽을 수 있도록 화면을 넘겨 주세요.",
        "총 3개의 자료를 직접 읽었습니다.",
        "공고는 모두 12건입니다.",
    ):
        assert claimed_reads_note(answer, steps) == "", answer


# --- 6. 상자 코드의 서식 숫자는 쓴 내용이 아니다 (판 e055235f) ------------------------

def test_layout_numbers_in_sandbox_code_are_not_written_facts() -> None:
    from alture_jarvis.agent import ungrounded_write_numbers

    code = (
        'rows = [["(주)데이터나루터", "면접 후 결정", "2026.10.14 23:59"], ["누리젠(주)", "월급 220만원", "채용시"]]\n'
        "widths = [18, 32, 16, 55, 45]\n"
        "for r in range(2, len(rows) + 2):\n"
        "    ws.row_dimensions[r].height = 120\n"
    )
    seen = {"2026", "10", "14", "23", "59"}

    assert ungrounded_write_numbers({"code": code}, seen) == ["220"], "따옴표 안의 값(220)만 본다 — 120·32·45·55 는 서식이다"


def test_plain_write_arguments_are_checked_as_before() -> None:
    from alture_jarvis.agent import ungrounded_write_numbers

    assert ungrounded_write_numbers({"path": "a.xlsx", "rows": [["회사", "연봉"], ["가", "3,000만원"]]}, set()) != []
