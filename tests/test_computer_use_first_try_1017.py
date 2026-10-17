"""화면 자동화(컴퓨터 유즈) 첫 시험에서 나온 넷 (2026-10-17 새벽 · 클로드 → MCP 로 「메모장 열고 한 줄 쓰고 저장」).

1. 「파일을 바로 **쓰는** 도구는 **쓰지** 말고」를 판 전체 쓰기 금지로 읽었다(d079f8b8) — 금지 꼬리 바로 앞 동사까지 사이를 본다.
2. 메모장을 `C:\\Windows\\System32\\notepad.exe` 로 열려다 막혀 두 걸음을 버렸다 — 정해 둔 프로그램은 이름으로 연다.
3. 글을 치고 Ctrl+S 까지 한 판이 「새 출처 없음」으로 제자리 판정 → 연장 없이 12걸음에서 멈췄다 — 창에서 실행한 동작은 진척이다.
4. 창 구조를 읽고 창 내용을 복사해 확인한 판에 「무엇도 열어 보지 않고 쓴 것」 헛경고 — 창 읽기도 「본 것」이다.
"""

from __future__ import annotations

import os

import pytest

from alture_jarvis import plan
from alture_jarvis.agent import BrowserAgent
from alture_jarvis.local_computer import launchable_app


def test_dont_use_the_tool_is_not_a_write_ban() -> None:
    prompt = ("메모장을 열어서 한 줄을 입력하고 저장 기능으로 「시험.txt」 이름으로 저장해 줘. "
              "파일을 바로 쓰는 도구는 쓰지 말고 반드시 메모장 창을 조작해서 해 줘.")
    assert plan.write_prohibition_scope(prompt) != "job"


def test_real_write_bans_still_hold() -> None:
    assert plan.write_prohibition_scope("조사만 해줘. 파일은 만들지 마") == "job"
    assert plan.write_prohibition_scope("파일을 수정하거나 외부 서비스에 쓰지 말고 정리만 해 줘") == "job"
    # 10-02 의 「기존 행은 지우지 말고」는 그대로 지목 금지
    assert plan.write_prohibition_scope("결과를 기록.xlsx 에 적어 줘. 파일이 이미 있으면 기존 행은 지우지 말고 아래에 덧붙여") == "clause"


@pytest.mark.skipif(os.name != "nt", reason="윈도우 프로그램 자리")
def test_known_apps_open_by_name_and_nothing_else() -> None:
    assert launchable_app("메모장", ) and launchable_app("메모장").lower().endswith("notepad.exe")
    assert launchable_app(r"C:\Windows\System32\notepad.exe")
    assert launchable_app("taskmgr") and launchable_app("작업 관리자")
    assert launchable_app(r"D:\somewhere\notepad.exe") is None  # 다른 자리의 같은 이름은 안 받는다
    for name in ("cmd", "powershell", r"C:\Windows\System32\cmd.exe", "regedit", ""):
        assert launchable_app(name) is None


def test_executed_window_actions_count_as_progress() -> None:
    step = {"tool": "windows_execute_preview", "ok": True,
            "evidence": {"action": "windows_execute_preview", "executed_action": "key"}}
    steps = [{"tool": "windows_list_open_windows", "ok": True, "evidence": {}}] * 5 + [step]
    assert BrowserAgent._is_stuck(steps) is False


def test_window_reads_are_not_called_nothing_opened() -> None:
    answer = "메모장 창을 확인한 결과, 「시험 1017」 18자가 입력돼 있습니다."
    steps = [{"tool": "windows_uia_snapshot", "ok": True}, {"tool": "windows_copy_from_window", "ok": True}]
    assert "무엇도 열어 보지 않고" not in BrowserAgent._sourced_claim_check(answer, steps)
    # 정말 아무것도 안 봤으면 예전처럼 경고 — 반대 방향
    nothing = BrowserAgent._sourced_claim_check(answer, [{"tool": "local_run_shell", "ok": True}])
    assert nothing == "" or "무엇도 열어 보지 않고" in nothing


# ── 측정 첫 바퀴(04:00~04:11)에서 나온 셋 ─────────────────────────────────────
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from alture_jarvis.config import JarvisConfig  # noqa: E402
from alture_jarvis.windows_automation import WindowsAutomationTools  # noqa: E402


def test_reading_a_task_manager_is_not_a_web_read_count() -> None:
    """「작업 관리자를 열어서 … 프로그램 다섯 개」가 「웹 자료 5개 읽기」가 되어 판 전체가 웹 조사 갈래로 묶였다(5f7d4d63)."""
    prompt = ("작업 관리자를 열어서, 지금 메모리를 가장 많이 쓰는 프로그램 다섯 개와 그래픽카드 메모리 사용량을 "
              "작업 관리자 화면에서 읽어서 알려 줘.")
    assert [req for req in plan.extract(prompt) if req.kind == "count"] == []
    # 웹 출처를 댄 개수는 그대로 센다
    assert [req.target for req in plan.extract("네이버에서 오늘 뉴스 다섯 개를 찾아 제목을 알려 줘") if req.kind == "count"] == [5]


class _Control:
    def __init__(self, name: str, control_type: str, value: str = "") -> None:
        rect = SimpleNamespace(left=0, top=0, right=10, bottom=10)
        self.element_info = SimpleNamespace(name=name, control_type=control_type, automation_id="", class_name="", rectangle=rect)
        self._value = value

    def get_properties(self) -> dict:
        return {"is_enabled": True, "is_visible": True}

    def get_value(self) -> str:
        return self._value


class _Window(_Control):
    def __init__(self, children: list) -> None:
        super().__init__("다른 이름으로 저장", "Window")
        self._children = children

    def descendants(self) -> list:
        return self._children

    def window_text(self) -> str:
        return "다른 이름으로 저장"


def _tools(tmp_path: Path) -> WindowsAutomationTools:
    return WindowsAutomationTools(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs"))


def test_inputs_come_first_and_show_their_current_value(tmp_path: Path) -> None:
    """저장 창의 긴 폴더 목록 뒤에 있던 「파일 이름」 칸이 밀렸고, 그 칸에 미리 든 이름이 안 보였다."""
    rows = [_Control(f"폴더 {i}", "TreeItem") for i in range(200)]
    children = [*rows, _Control("파일 이름:", "ComboBox", value="손자리 측정 1da1c.txt"), _Control("저장(S)", "Button")]
    tools = _tools(tmp_path)
    tools._window = lambda window_id: _Window(children)  # type: ignore[method-assign]
    snap = tools.uia_snapshot({"window_id": 7})
    names = [element["name"] for element in snap["elements"]]
    assert "파일 이름:" in names[:5] and "저장(S)" in names[:5]
    box = next(element for element in snap["elements"] if element["name"] == "파일 이름:")
    assert box["value"] == "손자리 측정 1da1c.txt"


def test_the_end_task_button_is_never_pressed(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    preview = tools._save_preview(source="uia", action="invoke", window_id=7, target={"name": "작업 끝내기"})
    with pytest.raises(PermissionError, match="end_task_blocked"):
        tools.execute_preview({"preview_id": preview.preview_id})


def test_a_desktop_program_job_is_not_routed_as_web_research() -> None:
    """한글 파일을 프로그램으로 열어 메뉴로 PDF 저장 — 「내 PC 를 봐야 함」 읽기 요구가 붙자 웹 갈래가 되어 창 도구가 막혔다(dab5bddc)."""
    from alture_jarvis.tool_roster import _is_web_research_job

    prompt = (r"「C:\Users\me\Documents\시험.hwp」 파일을 한글 프로그램으로 열어서, 한글의 메뉴로 같은 폴더에 PDF로 저장해 줘. "
              "한글 창을 직접 조작해서 해 줘.")
    observed = plan.extract(prompt, must_observe=True, observe_from=frozenset({"local"}))
    assert "observe" in {req.kind for req in observed}
    assert _is_web_research_job(observed, prompt) is False
    # 경로만 댄 문서 요약은 그대로 웹 갈래(작은 목록 · 근거 검사) — 운영 요청 대조에서 그쪽은 안 바꿨다
    summary = r"E:\docs\메모.md 파일을 읽고 핵심 3개를 채팅으로 정리해줘."
    assert _is_web_research_job(plan.extract(summary, must_observe=True, observe_from=frozenset({"local"})), summary) is True


def test_a_file_saved_through_a_program_window_counts_as_the_artifact(tmp_path: Path) -> None:
    """한글 메뉴로 PDF 를 저장하고 그 PDF 를 열어 확인한 판에 「산출물 없음」이 붙었다 — 창으로 만든 파일도 센다(조건 셋)."""
    import time as _time

    from alture_jarvis.plan import _gui_made_paths

    started = _time.time()
    pdf = tmp_path / "welcome.pdf"
    pdf.write_bytes(b"%PDF-1.7 test")
    gui = {"tool": "windows_execute_preview", "ok": True, "evidence": {"executed_at": started}}
    read = {"tool": "local_read_document", "ok": True, "arguments": {"path": str(pdf)}}
    assert _gui_made_paths([gui, read]) == [pdf]
    # 창 동작이 없었으면 읽은 파일은 산출물이 아니다(읽은 파일이 산출물로 둔갑하지 않게)
    assert _gui_made_paths([read]) == []
    # 창 동작보다 먼저 있던 파일도 아니다
    old = tmp_path / "old.pdf"
    old.write_bytes(b"%PDF old")
    import os as _os

    _os.utime(old, (started - 3600, started - 3600))
    assert _gui_made_paths([gui, {"tool": "local_read_document", "ok": True, "arguments": {"path": str(old)}}]) == []


def test_the_saved_file_is_reported_only_when_it_really_exists(tmp_path: Path) -> None:
    """저장을 끝내고도 자리를 찾느라 폴더를 열 걸음 뒤졌다(cad4f57a) — 저장 창이 닫힌 뒤 그 파일이 실제로 있을 때만 적는다."""
    saved = tmp_path / "화면측정_1.txt"
    saved.write_text("손자리", encoding="utf-8")
    assert WindowsAutomationTools._saved_file(str(saved)) == {"saved_file": str(saved)}
    assert WindowsAutomationTools._saved_file(str(tmp_path / "없는파일.txt")) == {}
    # 확장자를 안 적은 이름은 방금 생긴 같은 이름의 파일
    assert WindowsAutomationTools._saved_file(str(tmp_path / "화면측정_1")) == {"saved_file": str(saved)}
    assert WindowsAutomationTools._saved_file("") == {}


def test_the_model_gets_short_rows_but_clicks_still_find_the_control(tmp_path: Path) -> None:
    """창을 한 번 읽을 때마다 모델 입력이 7,500~11,000토큰씩 늘었다(23d8ce63) — 좌표 · 내부 이름은 모델에게 안 보내고 손자리 안에 둔다."""
    children = [_Control("파일 이름:", "ComboBox", value="보고서.pdf"), _Control("저장(S)", "Button")]
    tools = _tools(tmp_path)
    tools._window = lambda window_id: _Window(children)  # type: ignore[method-assign]
    snap = tools.uia_snapshot({"window_id": 7})
    for row in snap["elements"]:
        assert set(row) <= {"ref", "name", "control_type", "value", "automation_id", "enabled", "visible"}, row
    button = next(row for row in snap["elements"] if row["name"] == "저장(S)")
    assert button == {"ref": button["ref"], "name": "저장(S)", "control_type": "Button"}
    kept = tools._refs[(7, button["ref"])]
    assert kept["rectangle"] and "class_name" in kept, "누를 때 다시 찾는 전체 정보는 그대로 둔다"


def test_task_manager_values_are_summed_by_app_on_one_basis() -> None:
    """관리자 권한 창이라 모델이 명령으로 대신 읽었는데 판마다 기준이 달라 llama-server 가 8.1 · 19.1 · 13.0GB 로 흔들렸다."""
    from alture_jarvis.windows_automation import _task_manager_values

    mb = 1048576
    rows = [(0, "", 0), (10, "Memory Compression", 9000 * mb), (11, "chrome.exe", 300 * mb), (12, "chrome.exe", 200 * mb),
            (13, "llama-server.exe", 6000 * mb), (14, "notepad.exe", 50 * mb)]
    values = _task_manager_values(rows, "NVIDIA GeForce RTX 3090, 19392, 24576\n")
    assert [row["name"] for row in values["memory_top"]] == ["llama-server", "chrome", "notepad"]
    assert values["memory_top"][1] == {"name": "chrome", "mb": 500, "processes": 2}
    assert values["gpus"] == [{"name": "NVIDIA GeForce RTX 3090", "used_mib": 19392, "total_mib": 24576}]
    assert _task_manager_values(rows, "")["memory_top"], "그래픽카드를 못 읽어도 메모리 순위는 준다"


def test_the_pdf_saved_from_a_named_hwp_is_the_artifact() -> None:
    """원본 이름(「…welcome.hwp」 파일을 열어서)을 만들 형식으로 읽어, PDF 를 만들어 열어 읽은 세 판 모두 「❌ 산출물 없음」이 붙었다.

    운영 요청 2,198개 대조: 바뀐 18개 — 이 측정 10개(.hwp → .pdf) · 「파일을 열어서 알려줘」 읽기 6개(형식 제한 빠짐) · 읽을 .ts 가 빠진 2개.
    """
    prompt = (r"「C:\Users\me\Documents\시험.hwp」 파일을 한글 프로그램으로 열어서, 한글의 메뉴(파일 > PDF로 저장하기)를 써서 "
              "같은 폴더에 같은 이름의 PDF로 저장해 줘. 한글 창을 직접 조작해서 해 줘.")
    assert plan.artifact_extensions(prompt) == (".pdf",)
    assert plan.artifact_extensions("Open report.hwp in Hangul and save it as PDF in the same folder") == (".pdf",)
    # PDF 를 읽을 재료로 쓴 판은 그대로
    assert plan.artifact_extensions("이 PDF 요약해서 워드로 저장해줘") == (".docx",)
    assert plan.artifact_extensions("보고서.pdf 파일을 읽고 엑셀로 정리해줘") == (".xlsx",)
    # 만들고 나서 여는 파일은 만들 파일이다
    assert plan.artifact_extensions("결과.md 를 만들어서 열어 줘") == (".md",)


class _Pressable(_Control):
    def __init__(self, name: str, control_type: str) -> None:
        super().__init__(name, control_type)
        self.calls: list[str] = []

    def invoke(self) -> None:
        self.calls.append("invoke")

    def click_input(self) -> None:
        self.calls.append("click")


def test_a_menu_item_is_clicked_not_invoked(tmp_path: Path) -> None:
    """한글 메뉴를 invoke 로 누르면 아무 일도 안 일어났다 — 모델이 다섯 번 되풀이하다 41걸음째 click 으로 바꿨다(7412255c)."""
    tools = _tools(tmp_path)
    for control_type, expected in (("MenuItem", ["click"]), ("Button", ["invoke"])):
        control = _Pressable("PDF로 저장하기", control_type)
        tools._window = lambda window_id, _c=control: _Window([_c])  # type: ignore[method-assign]
        tools._find_control = lambda window_id, target, _c=control: _c  # type: ignore[method-assign]
        preview = tools._save_preview(source="uia", action="invoke", window_id=7, target={"name": "PDF로 저장하기"})
        tools.execute_preview({"preview_id": preview.preview_id})
        assert control.calls == expected, control_type


def test_a_small_element_cap_is_raised_so_open_menus_are_not_cut(tmp_path: Path) -> None:
    """모델이 50 · 80 개만 달라고 해 열린 메뉴의 「PDF로 저장하기」가 잘렸다(f885ea48 2판째, 48걸음 상한)."""
    children = [_Control(f"항목 {i}", "MenuItem") for i in range(200)]
    tools = _tools(tmp_path)
    tools._window = lambda window_id: _Window(children)  # type: ignore[method-assign]
    assert tools.uia_snapshot({"window_id": 7, "max_elements": 50})["count"] == 150
    assert tools.uia_snapshot({"window_id": 7, "max_elements": 300})["count"] == 201


def test_a_percent_computed_from_the_same_named_row_is_not_flagged() -> None:
    """「RTX 3090은 VRAM의 약 79%」에 「읽은 자료에 없는 비율」 — 두 수는 위 표 줄(19,392 / 24,576 = 78.9%)에 있었다(ac57f00e).

    운영 기록에서 이 경고가 붙은 답 28개 대조: 바뀐 5개가 전부 이 79% 였다.
    """
    from alture_jarvis.number_checks import ungrounded_percents

    answer = ("| GPU | 사용량 | 전체 |\n|---|---|---|\n| NVIDIA GeForce RTX 3090 | 19,392 MiB | 24,576 MiB |\n\n"
              "RTX 3090은 VRAM의 약 79%를 쓰고 있습니다.")
    assert ungrounded_percents(answer, set()) == []
    # 이름이 안 겹치는 줄의 숫자로는 못 만든다 — 아무 쌍이나 받지 않는다
    other = "| 항목 | 값 |\n|---|---|\n| 사과 | 19,392 |\n| 배 | 24,576 |\n\n전체의 약 79%가 남았습니다."
    assert ungrounded_percents(other, set()) == ["79"]
