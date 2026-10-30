"""편집 도구에 「줄 번호로 바꾸기」 길 (2026-10-28 코딩 재생 2판 f02daa26 사건).

## 무엇이 있었나

Swift 2판이 plan.py 3629줄 근처의 정규식 줄(역슬래시 · 곧은 따옴표 · 굽은 따옴표가 섞임)을 `old_text_not_found` 로
**5번 연속** 못 맞춰 멈췄다. 도구는 「97% 비슷한 원문은 이렇다」를 보여 줬는데도 못 맞췄다 — 그 줄은 글자로 옮기다 어긋난다.
읽기는 `line_start`/`line_end` 가 되는데 편집은 글자 맞추기뿐이었다.

## 지킬 것

- 글자 모드가 실패한 그 줄을, 줄 범위 모드(`old` 없이 line_start · line_end · first_line · new)로 고칠 수 있다.
- **짐작으로 고치지 않는다**: first_line 이 없거나 파일의 그 줄과 다르면 거절(파일은 그대로) · 범위가 파일 밖이면 거절.
- 줄바꿈 방식(CRLF/LF)은 파일의 것을 따른다.
- 실패 메시지에 그 자리의 줄 번호와 줄 범위 모드 안내가 있고, 같은 파일 둘째 실패부터는 더 분명하다. 앞머리는 `old_text_not_found` 그대로.
- 멀쩡한 글자 편집은 안 깨진다(`old` 가 있으면 먼저 글자로 — 덤으로 온 line_start 가 방해하지 않는다).
- 새 도구를 만들지 않고 기존 도구의 선택 칸으로 더한다(도구 목록 수가 그대로여야 같은-목록 캐시가 안 꺼진다).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools, _replace_line_range

# 2판이 5번 못 맞춘 줄 — plan.py 3631줄 그대로(역슬래시 · 곧은 따옴표 · 굽은 따옴표).
INCIDENT_LINE = r'''    r"\s*[」』\"'”’)\]]?\s*(?:(?:한글|워드|엑셀|파워\s*포인트|텍스트)\s*)?(?:파일|문서|그림|사진|이미지|표)?\s*(?:을|를)\s*"'''
INCIDENT_NEW = r'''    r"\s*[」』\"'”’)\]]?\s*(?:(?:한글|워드|엑셀|파워\s*포인트|텍스트)\s*)?(?:파일|문서|그림|사진|이미지|표|목록)?\s*(?:을|를)\s*"'''
# 모델이 옮기다 어긋난 모양 — 역슬래시가 한 겹 덜 / 따옴표가 곧은 따옴표로.
MISCOPIED_LINE = INCIDENT_LINE.replace('\\"', '"').replace("”’", "\"'")

_BODY = (
    "import re\n\n"
    "_ENDINGS = (\n"
    f"{INCIDENT_LINE}\n"
    '    r"끝"\n'
    ")\n"
)


def _tools(tmp_path: Path) -> tuple[LocalComputerTools, Path]:
    work = tmp_path / "ws"
    work.mkdir()
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                          local_file_allowed_roots=str(work), local_read_roots=str(tmp_path))
    tools = LocalComputerTools(config)
    tools.authorize_code_workspace("code-job", str(work))
    return tools, work


def _call(tools: LocalComputerTools, path: Path, **args) -> dict:
    return tools.apply_edit({"path": str(path), "__job_id": "code-job", **args})


def _write(path: Path, text: str, newline: str = "\n") -> None:
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


# --- ① 글자 모드 실패 → ② 줄 범위 모드 성공 -----------------------------------------

def test_the_incident_line_fails_by_text_then_succeeds_by_line_range(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "plan.py"
    _write(path, _BODY)

    # 글자 모드: 모델이 옮기다 어긋난 줄 → 실패하고, 메시지가 그 자리 줄 번호와 줄 범위 모드를 댄다.
    with pytest.raises(ValueError) as caught:
        _call(tools, path, old=MISCOPIED_LINE, new=INCIDENT_NEW)
    message = str(caught.value)
    assert message.startswith("old_text_not_found")
    assert "4번째 줄쯤" in message                       # 그 자리의 줄 번호
    assert "line_start=4" in message and "line_end=4" in message and "first_line" in message
    assert path.read_text(encoding="utf-8") == _BODY      # 실패는 아무것도 안 바꾼다

    # 줄 범위 모드: old 없이. first_line 은 곧은 따옴표로 어긋나게 되적어도(loose) 같은 줄이면 받는다.
    result = _call(tools, path, line_start=4, line_end=4, first_line=MISCOPIED_LINE, new=INCIDENT_NEW)
    assert path.read_text(encoding="utf-8") == _BODY.replace(INCIDENT_LINE, INCIDENT_NEW)
    assert result["healed"] == "line_range"
    assert result["line_range"]["first_line_match"] == "loose"
    assert result["edit_preview"]["start_line"] == 4
    assert result["edit_preview"]["removed"] == [INCIDENT_LINE]
    assert result["edit_preview"]["added"] == [INCIDENT_NEW]


def test_exact_first_line_is_reported_as_exact(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "a.py"
    _write(path, "a = 1\nb = 2\nc = 3\n")
    result = _call(tools, path, line_start=2, first_line="b = 2", new="b = 20")
    assert path.read_text(encoding="utf-8") == "a = 1\nb = 20\nc = 3\n"
    assert result["line_range"]["first_line_match"] == "exact"


def test_a_range_of_several_lines_is_replaced_whole(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "a.py"
    _write(path, "a = 1\nb = 2\nc = 3\nd = 4\n")
    _call(tools, path, line_start=2, line_end=3, first_line="b = 2", new="x = 9\ny = 8\nz = 7\n")
    assert path.read_text(encoding="utf-8") == "a = 1\nx = 9\ny = 8\nz = 7\nd = 4\n"


# --- ③ 첫 줄이 다르면 거절 ------------------------------------------------------------

def test_a_first_line_that_is_not_there_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "a.py"
    _write(path, "a = 1\nb = 2\nc = 3\n")
    with pytest.raises(ValueError) as caught:
        _call(tools, path, line_start=3, first_line="b = 2", new="c = 30")   # 파일이 밀렸다: 3줄은 c
    message = str(caught.value)
    assert message.startswith("line_text_changed")
    assert "3: c = 3" in message and "2: b = 2" in message      # 다시 읽지 않고 번호를 바로잡게 앞뒤를 보여 준다
    assert path.read_text(encoding="utf-8") == "a = 1\nb = 2\nc = 3\n"


def test_a_missing_first_line_is_refused(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "a.py"
    _write(path, "a = 1\nb = 2\n")
    with pytest.raises(ValueError, match="first_line_required"):
        _call(tools, path, line_start=2, new="b = 3")
    assert path.read_text(encoding="utf-8") == "a = 1\nb = 2\n"


@pytest.mark.parametrize("actual,claimed", [
    ("    }", "    )"),                    # 낱말이 없는 줄은 뼈대로 못 견준다 — 글자 그대로만
    ("    return x", "    return y"),
    ("def f(a):", "def g(a):"),
])
def test_different_lines_never_pass_the_check(actual: str, claimed: str) -> None:
    text = f"top\n{actual}\nbottom\n"
    with pytest.raises(ValueError, match="line_text_changed"):
        _replace_line_range(text, 2, 2, claimed, "x")


# --- ④ CRLF 파일 ----------------------------------------------------------------------

def test_a_crlf_file_stays_crlf(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "win.py"
    _write(path, "a = 1\nb = 2\nc = 3\nd = 4\n", newline="\r\n")
    _call(tools, path, line_start=2, line_end=3, first_line="b = 2", new="x = 1\ny = 2\nz = 3")
    raw = path.read_bytes()
    assert raw == b"a = 1\r\nx = 1\r\ny = 2\r\nz = 3\r\nd = 4\r\n"
    assert raw.count(b"\n") == raw.count(b"\r\n")           # 홑 LF 가 섞이지 않았다


def test_a_new_that_arrives_with_crlf_does_not_double_the_endings(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "win.py"
    _write(path, "a = 1\nb = 2\nc = 3\n", newline="\r\n")
    _call(tools, path, line_start=2, first_line="b = 2", new="x = 1\r\ny = 2\r\n")
    assert path.read_bytes() == b"a = 1\r\nx = 1\r\ny = 2\r\nc = 3\r\n"


def test_the_last_line_without_a_final_newline_keeps_having_none(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "a.py"
    path.write_bytes(b"a = 1\nb = 2")
    _call(tools, path, line_start=2, first_line="b = 2", new="b = 3")
    assert path.read_bytes() == b"a = 1\nb = 3"


def test_a_utf8_bom_is_kept(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "bom.py"
    path.write_bytes(b"\xef\xbb\xbf" + "a = '가'\nb = 2\n".encode("utf-8"))
    _call(tools, path, line_start=2, first_line="b = 2", new="b = 3")
    assert path.read_bytes() == b"\xef\xbb\xbf" + "a = '가'\nb = 3\n".encode("utf-8")


# --- ⑤ 범위가 파일 밖이면 거절 ----------------------------------------------------------

@pytest.mark.parametrize("start,end", [(4, 4), (2, 9), (0, 1), (3, 2), (-1, 1)])
def test_a_range_outside_the_file_is_refused_not_clamped(tmp_path: Path, start: int, end: int) -> None:
    tools, work = _tools(tmp_path)
    path = work / "a.py"
    _write(path, "a = 1\nb = 2\nc = 3\n")
    with pytest.raises(ValueError, match="line_range_(out_of_file|invalid)"):
        _call(tools, path, line_start=start, line_end=end, first_line="a = 1", new="x")
    assert path.read_text(encoding="utf-8") == "a = 1\nb = 2\nc = 3\n"


def test_a_line_number_that_is_not_a_number_is_refused(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "a.py"
    _write(path, "a = 1\n")
    with pytest.raises(ValueError, match="line_range_invalid"):
        _call(tools, path, line_start="앞쪽", first_line="a = 1", new="x")


# --- 지우기 · 빈 줄 · 들여쓰기 알림 -----------------------------------------------------------

def test_an_empty_new_deletes_the_lines_and_a_newline_makes_a_blank_line(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "a.py"
    _write(path, "a = 1\nb = 2\nc = 3\n")
    _call(tools, path, line_start=2, first_line="b = 2", new="")
    assert path.read_text(encoding="utf-8") == "a = 1\nc = 3\n"
    _write(path, "a = 1\nb = 2\nc = 3\n")
    _call(tools, path, line_start=2, first_line="b = 2", new="\n")
    assert path.read_text(encoding="utf-8") == "a = 1\n\nc = 3\n"


def test_a_changed_indentation_is_noted_not_fixed(tmp_path: Path) -> None:
    # ★ 2026-10-29: .py 에서 들여쓰기가 빠져 문법이 깨지는 편집은 이제 쓰지 않고 거절한다(`syntax_broken`,
    #   test_apply_edit_refuses_syntax_break_1029). 「들여쓰기를 우리가 만들지 않고 알림만」은 문법 검사가 없는 글 파일로 지킨다.
    tools, work = _tools(tmp_path)
    path = work / "a.txt"
    _write(path, "def f():\n        return 1\n")
    result = _call(tools, path, line_start=2, first_line="return 1", new="return 2")
    assert path.read_text(encoding="utf-8") == "def f():\nreturn 2\n"       # 우리가 들여쓰기를 만들지 않는다
    assert "들여쓰기" in result["indent_note"]
    py = work / "a.py"
    _write(py, "def f():\n        return 1\n")
    with pytest.raises(ValueError, match="^syntax_broken"):
        _call(tools, py, line_start=2, first_line="return 1", new="return 2")
    assert py.read_text(encoding="utf-8") == "def f():\n        return 1\n"


# --- 글자 모드와의 관계 -------------------------------------------------------------------

def test_a_good_text_edit_is_not_hindered_by_stray_line_numbers(tmp_path: Path) -> None:
    """읽기 도구의 버릇으로 line_start 를 덤으로 끼워 보내도 old 가 맞으면 글자로 간다(first_line 없이도)."""
    tools, work = _tools(tmp_path)
    path = work / "a.py"
    _write(path, "a = 1\nb = 2\nc = 3\n")
    result = _call(tools, path, old="b = 2", new="b = 20", line_start=99, line_end=120)
    assert path.read_text(encoding="utf-8") == "a = 1\nb = 20\nc = 3\n"
    assert "healed" not in result


def test_a_text_miss_with_good_line_numbers_falls_through_to_the_line_mode(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "plan.py"
    _write(path, _BODY)
    result = _call(tools, path, old=MISCOPIED_LINE, new=INCIDENT_NEW, line_start=4, first_line=INCIDENT_LINE)
    assert path.read_text(encoding="utf-8") == _BODY.replace(INCIDENT_LINE, INCIDENT_NEW)
    assert result["healed"] == "line_range"


def test_a_text_miss_with_wrong_line_numbers_says_both_reasons_and_writes_nothing(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "plan.py"
    _write(path, _BODY)
    with pytest.raises(ValueError) as caught:
        _call(tools, path, old=MISCOPIED_LINE, new=INCIDENT_NEW, line_start=2, first_line=INCIDENT_LINE)
    message = str(caught.value)
    assert message.startswith("old_text_not_found")          # 앞머리는 그대로 — 관문 · 되풀이 판정이 이 낱말로 가른다
    assert "줄 범위 모드도 안 됐다" in message and "line_text_changed" in message
    assert path.read_text(encoding="utf-8") == _BODY


def test_no_old_and_no_line_start_still_says_old_required_and_points_to_the_line_mode(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "a.py"
    _write(path, "a = 1\n")
    with pytest.raises(ValueError) as caught:
        _call(tools, path, new="x")
    assert str(caught.value).startswith("old_required") and "line_start" in str(caught.value)


# --- 같은 파일에서 둘째 실패부터 더 분명하게 -----------------------------------------------------

def test_the_second_miss_on_the_same_file_is_more_insistent_and_a_success_resets_it(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "plan.py"
    other = work / "other.py"
    _write(path, _BODY)
    _write(other, "zz = 1\n")

    with pytest.raises(ValueError) as first:
        _call(tools, path, old=MISCOPIED_LINE, new="x")
    assert "★" not in str(first.value)
    with pytest.raises(ValueError) as second:
        _call(tools, path, old=MISCOPIED_LINE, new="x")
    assert "★ 같은 파일에서 글자 맞추기가 2번째 실패다" in str(second.value)
    assert "지금 줄 범위 모드로 해라" in str(second.value) and "line_start=4" in str(second.value)

    # 다른 파일의 실패는 따로 센다.
    with pytest.raises(ValueError) as elsewhere:
        _call(tools, other, old="qq = 9", new="x")
    assert "★" not in str(elsewhere.value)

    # 맞는 편집이 한 번 되면 센 것을 지운다.
    _call(tools, path, old="import re", new="import re  # ok")
    with pytest.raises(ValueError) as again:
        _call(tools, path, old=MISCOPIED_LINE, new="x")
    assert "★" not in str(again.value)


def test_a_second_miss_with_nothing_similar_still_names_the_line_mode(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "a.py"
    _write(path, "alpha = 1\n")
    for _ in range(2):
        with pytest.raises(ValueError) as caught:
            _call(tools, path, old="전혀 다른 내용이다\n이 파일에는 없다", new="x")
    assert "줄 범위 모드" in str(caught.value) and "line_start=(읽은 줄 번호)" in str(caught.value)


# --- 도구 정의: 새 도구 없이 기존 도구의 선택 칸으로 ------------------------------------------------

def test_the_tool_definition_gained_optional_fields_not_a_new_tool(tmp_path: Path) -> None:
    tools, _work = _tools(tmp_path)
    definitions = tools._build_definitions()
    names = [item["function"]["name"] for item in definitions]
    assert names.count("local_apply_edit") == 1
    edit = next(item["function"] for item in definitions if item["function"]["name"] == "local_apply_edit")
    properties = edit["parameters"]["properties"]
    assert {"path", "old", "new", "line_start", "line_end", "first_line"} <= set(properties)
    assert edit["parameters"]["required"] == ["path", "new"]       # old 는 줄 모드에서 빠진다
    assert not any(name.startswith("local_apply_edit_") or name == "local_apply_line_edit" for name in names)


def test_the_slim_code_tool_list_keeps_the_new_fields_and_mentions_the_line_mode() -> None:
    from alture_jarvis.code_runtime import qwen_code_tools

    full = [{"type": "function", "function": {"name": "local_apply_edit", "description": "x", "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "d"}, "old": {"type": "string", "description": "d"},
            "new": {"type": "string", "description": "d"},
            "line_start": {"type": "integer", "description": "keep"}, "line_end": {"type": "integer", "description": "keep"},
            "first_line": {"type": "string", "description": "d"},
        },
        "required": ["path", "new"],
    }}}]
    slim = qwen_code_tools(full, {"local_apply_edit"})[0]["function"]
    assert {"line_start", "line_end", "first_line"} <= set(slim["parameters"]["properties"])
    assert "first_line" in slim["description"] and "line_start" in slim["description"]
