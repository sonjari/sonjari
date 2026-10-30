"""막혔을 때 사람에게 하는 부탁은 **오류 종류**에 맞는다 (2026-10-28 코딩 재생 2판 f02daa26).

## 무엇이 있었나

`local_apply_edit` 이 글자 맞추기(`old_text_not_found`)를 5번 연속 못 맞춰 멈췄는데, 부탁은 도구 이름이 `local_` 로 시작한다는 이유만으로
「찾던 파일이나 폴더가 그 자리에 있는지 봐 주세요」였다. 파일은 멀쩡했다.

## 지킬 것

- 글자 맞추기 실패는 사람이 할 일이 아니다 — 부탁은 「줄 번호로 다시 해 봅니다」이고, 이어질 때 모델에게 줄 범위 모드 안내가 간다.
- 파일 · 폴더 없음류만 예전 문장을 그대로 쓴다.
- 그 밖의 `local_` 오류(권한 · 입력 오류 · 프로그램 없음 · 모르는 오류)는 파일 없음이라고 단정하지 않는다.
- 찾기 실패(`cant_find`)와 시간 초과 부탁은 그대로다.
"""

from __future__ import annotations

import pytest

from alture_jarvis import stuck_hands as sh
from alture_jarvis.stuck_hands import STUCK_FAILURES_AFTER, _local_stuck_ask, _stuck_report


def _failing(tool: str, error: str, count: int = STUCK_FAILURES_AFTER) -> list[dict]:
    return [{"tool": tool, "ok": False, "error": error} for _ in range(count)]


def test_five_failed_text_edits_do_not_ask_the_person_to_look_for_the_file() -> None:
    error = "old_text_not_found — 그 글자는 없지만 **3631번째 줄쯤이 97% 비슷하다.**\n..."
    report = _stuck_report(_failing("local_apply_edit", error))
    assert report is not None and report["kind"] == "keeps_failing"
    assert report["ask"] == "고칠 글자를 파일에서 못 맞췄습니다. 「이어서」를 누르면 줄 번호로 다시 해 봅니다."
    assert "찾던 파일이나 폴더" not in report["ask"] and "찾던 파일이나 폴더" not in report["message"]
    # 이어질 때 모델이 가는 길 — 줄 범위 모드
    assert "line_start" in report["retry_hint"] and "first_line" in report["retry_hint"] and "old 를 빼고" in report["retry_hint"]
    assert "「이어서」를 눌러 주세요" in report["message"]


@pytest.mark.parametrize("error", ["path_not_found", "folder_not_found:C:/x", "[WinError 2] 지정된 파일을 찾을 수 없습니다", "No such file or directory", "file_required"])
def test_a_missing_file_keeps_the_old_sentence(error: str) -> None:
    report = _stuck_report(_failing("local_read_text_file", error))
    assert report["ask"] == sh._ASK_FILE_MISSING
    assert "retry_hint" not in report


# 분류표 — 오류 종류 → 부탁. 파일 없음이 아닌 것에 파일 없음 부탁이 나가지 않는다.
@pytest.mark.parametrize("tool,error,expected", [
    ("local_apply_edit", "old_text_not_found", sh._ASK_EDIT_TEXT_MISS),
    ("local_apply_edit", "old_text_not_found — ...\n줄 범위 모드도 안 됐다: line_text_changed — ...", sh._ASK_EDIT_TEXT_MISS),
    ("hwp_edit_text", "hwp_old_text_not_found", sh._ASK_DOCUMENT_TEXT_MISS),
    ("local_apply_edit", "old_text_not_unique:3", sh._ASK_EDIT_NOT_UNIQUE),
    ("local_apply_edit", "line_text_changed — 3번째 줄이 first_line 과 다르다", sh._ASK_EDIT_LINES),
    ("local_apply_edit", "line_range_out_of_file — 이 파일은 10줄인데", sh._ASK_EDIT_LINES),
    ("local_apply_edit", "first_line_required — first_line 에", sh._ASK_EDIT_LINES),
    ("local_apply_edit", "old_required — `old` 에", sh._ASK_EDIT_LINES),
    ("local_write_file", "path_outside_allowed_roots: 「x」은 C:/x 로 풀렸습니다.", sh._ASK_BLOCKED),
    ("local_write_file", "sensitive_path_blocked", sh._ASK_BLOCKED),
    ("local_run_project_command", "project_command_not_allowed", sh._ASK_BLOCKED),
    ("local_run_project_command", "git_force_not_allowed", sh._ASK_BLOCKED),
    ("local_delete_file", "folder_existed_before_this_job:node_modules — 이 작업이 만든 폴더가 아니다", sh._ASK_BLOCKED),
    ("local_write_file", "[WinError 5] Access is denied", sh._ASK_BLOCKED),
    ("local_write_file", "path_required — 어디에 쓸지(path)가 없다", sh._ASK_BAD_INPUT),
    ("local_grep", "bad_pattern:(", sh._ASK_BAD_INPUT),
    ("local_run_project_command", "command_array_required", sh._ASK_BAD_INPUT),
    ("local_run_project_command", "command_not_found:pytest", sh._ASK_NO_PROGRAM),
    ("local_run_project_command", "project_venv_missing", sh._ASK_NO_PROGRAM),
    ("local_read_text_file", "text_encoding_not_supported", sh._ASK_LOCAL_OTHER),
    ("local_read_text_file", "뭔가 처음 보는 오류", sh._ASK_LOCAL_OTHER),
])
def test_the_ask_follows_the_error_kind(tool: str, error: str, expected: str) -> None:
    ask, _hint = _local_stuck_ask(tool, error)
    assert ask == expected
    if expected != sh._ASK_FILE_MISSING:
        assert ask != sh._ASK_FILE_MISSING


def test_only_a_line_editing_tool_is_pointed_at_the_line_mode() -> None:
    assert _local_stuck_ask("local_apply_edit", "old_text_not_found")[1] == sh._RETRY_EDIT_BY_LINES
    assert _local_stuck_ask("hwp_edit_text", "hwp_old_text_not_found")[1] == ""      # 문서 편집에는 줄 범위 모드가 없다
    assert _local_stuck_ask("local_read_text_file", "path_not_found")[1] == ""


def test_timeout_and_screen_asks_are_unchanged() -> None:
    timeout = _stuck_report(_failing("local_run_project_command", "timeout after 300s"))
    assert timeout["ask"] == "작업이 제한 시간 안에 안 끝났습니다. 잠시 뒤 「이어서」를 눌러 주세요."
    browser = _stuck_report(_failing("browser_click", "element_not_visible"))
    assert browser["ask"].startswith("크롬 창에서 이 화면을")
    unity = _stuck_report(_failing("unity_run_recipe", "boom"))
    assert unity["ask"].startswith("유니티 에디터가")


def test_the_new_asks_have_english_translations(tmp_path) -> None:
    from alture_jarvis import ui_i18n

    ui_i18n.configure(tmp_path / "lang.json")
    ui_i18n.set_lang("en")
    try:
        for ask in (sh._ASK_EDIT_TEXT_MISS, sh._ASK_EDIT_NOT_UNIQUE, sh._ASK_EDIT_LINES, sh._ASK_DOCUMENT_TEXT_MISS,
                    sh._ASK_BLOCKED, sh._ASK_BAD_INPUT, sh._ASK_NO_PROGRAM, sh._ASK_LOCAL_OTHER, sh._ASK_FILE_MISSING):
            translated = ui_i18n.translate_text(ask)
            assert translated != ask and not any("\uac00" <= ch <= "\ud7a3" for ch in translated), ask
    finally:
        ui_i18n.set_lang("ko")


def test_the_agent_hands_the_retry_hint_to_the_model_when_it_resumes() -> None:
    import inspect

    from alture_jarvis import agent

    source = inspect.getsource(agent)
    assert 'stuck.get("retry_hint")' in source
