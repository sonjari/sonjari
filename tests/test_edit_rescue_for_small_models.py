"""작은 모델의 흔한 글자 어긋남 둘을 편집 도구가 구제한다 (2026-09-22, 노트북 4B 사다리 `fin2` 실측).

## 무엇이 있었나

`local_apply_edit` 56 번 중 12 번(21%)이 `old_text_not_found` 였고 그것 때문에 진 작업이 둘이었다.
유사도 95% 이상인 4 번의 어긋난 모양은 둘이다:

    1. 들여쓰기를 빼먹음      `def f():\\nreturn 1`      (도구는 「100% 비슷」이라 말하고도 거절)
    2. 따옴표 이중 이스케이프  `\\"\\"\\"docstring\\"\\"\\"`  (인자에 백슬래시가 한 겹 더)

나머지 8 번(72~90% 비슷)은 모델이 파일 내용을 **실제로 잘못 기억**한 것이라 구제하면 안 된다.

## 이전 결정과 안 부딪히는 이유

앞 결정(`test_apply_edit_says_where_it_is_close`)은 「들여쓰기를 **짐작해서** 고치면 파이썬에서는 다른 코드」였다.
이 구제는 짐작하지 않는다 — **`old` 를 찾는 기준만** 느슨하게 하고, 후보가 **하나일 때만** 받아들이며, `new` 는 **모델이 쓴 그대로**다.

## 지킬 것

- 구제되는 두 모양은 실제로 고쳐지고, 결과에 `healed` 가 적힌다(조용히 고치지 않는다).
- **후보가 둘이면 안 고친다.**  · **닮았을 뿐 내용이 다르면 안 고친다.**  · `new` 가 파이썬을 깨는 모양이면 안 고친다.
- 완전일치는 그대로다(`healed` 없음).
- 쓰기 경로가 작업 폴더 자기 이름으로 시작하면 이름을 뗀다(진짜 하위 폴더가 있으면 안 뗀다).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools, _rescue_edit


def _tools(tmp_path: Path, name: str = "ws") -> tuple[LocalComputerTools, Path]:
    work = tmp_path / name
    work.mkdir()
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                          local_file_allowed_roots=str(work), local_read_roots=str(tmp_path))
    tools = LocalComputerTools(config)
    tools.authorize_code_workspace("code-job", str(work))
    return tools, work


def _edit(tools: LocalComputerTools, path: Path, old: str, new: str) -> dict:
    return tools.apply_edit({"path": str(path), "old": old, "new": new, "__job_id": "code-job"})


_DB = "USERS = {1: 'a'}\n\n\ndef get_user(user_id):\n    return USERS.get(user_id)\n"


# --- 구제되는 것 ---------------------------------------------------------------

def test_a_dropped_indentation_in_old_is_rescued_and_reported(tmp_path: Path) -> None:
    """노트북 L5 1회차의 모양 — 둘째 줄 들여쓰기가 없다. `new` 는 제대로 왔다."""
    tools, work = _tools(tmp_path)
    path = work / "db.py"
    path.write_text(_DB, encoding="utf-8")

    result = _edit(tools, path, "def get_user(user_id):\nreturn USERS.get(user_id)",
                   "def fetch_user(user_id):\n    return USERS.get(user_id)")

    assert path.read_text(encoding="utf-8") == _DB.replace("def get_user", "def fetch_user")
    assert result["healed"] == "indentation"  # 조용히 고치지 않는다


def test_a_different_number_of_blank_lines_is_rescued(tmp_path: Path) -> None:
    """노트북 L5 의 둘째 모양 — 빈 줄이 하나뿐이다(파일에는 둘)."""
    tools, work = _tools(tmp_path)
    path = work / "api.py"
    path.write_text("from db import get_user\nfrom service import greeting\n\n\ndef handle(user_id):\n"
                    "    exists = get_user(user_id) is not None\n    return {\"exists\": exists}\n", encoding="utf-8")

    _edit(tools, path,
          "from service import greeting\n\ndef handle(user_id):\nexists = get_user(user_id) is not None",
          "from service import greeting\n\n\ndef handle(user_id):\n    exists = fetch_user(user_id) is not None")

    assert "fetch_user(user_id) is not None" in path.read_text(encoding="utf-8")
    assert "get_user(user_id)" not in path.read_text(encoding="utf-8").split("def handle")[1]


def test_doubly_escaped_quotes_are_rescued(tmp_path: Path) -> None:
    """노트북 L4 3회차의 모양 — `\\\"\\\"\\\"` 로 백슬래시가 한 겹 더 붙어 왔다. `new` 도 같은 방식으로 푼다."""
    tools, work = _tools(tmp_path)
    path = work / "textutil.py"
    path.write_text('def slugify(text):\n    """Hello -> hello"""\n    return text.lower()\n', encoding="utf-8")

    result = _edit(
        tools, path,
        'def slugify(text):\n    \\"\\"\\"Hello -> hello\\"\\"\\"\n    return text.lower()',
        'def slugify(text):\n    \\"\\"\\"Hello -> hello\\"\\"\\"\n    return text.lower().strip()',
    )

    assert path.read_text(encoding="utf-8") == 'def slugify(text):\n    """Hello -> hello"""\n    return text.lower().strip()\n'
    assert result["healed"] == "escaped_quotes"


# --- 구제하면 안 되는 것 -------------------------------------------------------

def test_two_candidates_are_not_guessed(tmp_path: Path) -> None:
    """같은 줄 묶음이 둘이면 어느 쪽인지 모른다 — 모르는 채 고치는 것이 못 고치는 것보다 나쁘다."""
    tools, work = _tools(tmp_path)
    path = work / "dup.py"
    body = "def a():\n    return 1\n\n\ndef b():\n    return 1\n"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ValueError, match="old_text_not_found"):
        _edit(tools, path, "return 1", "return 2") if False else _edit(tools, path, "def a():\nreturn 1\n\ndef b():\nreturn 9", "x")
    assert path.read_text(encoding="utf-8") == body


def test_similar_but_different_content_is_not_rescued(tmp_path: Path) -> None:
    """72~90% 비슷한 것은 모델이 파일 내용을 잘못 기억한 것이다 — 그대로 실패해야 한다."""
    tools, work = _tools(tmp_path)
    path = work / "db.py"
    path.write_text(_DB, encoding="utf-8")

    with pytest.raises(ValueError, match="old_text_not_found"):
        _edit(tools, path, "def get_user(uid):\n    return USERS[uid]", "def fetch_user(uid):\n    return USERS[uid]")
    assert path.read_text(encoding="utf-8") == _DB


def test_a_new_that_flattens_the_indentation_the_old_still_had_is_refused(tmp_path: Path) -> None:
    """`old` 는 들여쓰기가 있는데(다만 파일과 칸 수가 다르다) `new` 만 납작하면 모델이 뭘 하려는지 모른다 — 구제하지 않는다.

    (`old` 와 `new` 가 **똑같이** 들여쓰기를 잃은 경우는 아래에서 파일의 들여쓰기로 되살린다 — 그건 들여쓰기를 바꿀 뜻이 없다는 증거가 있다.)
    """
    tools, work = _tools(tmp_path)
    path = work / "db.py"
    path.write_text(_DB, encoding="utf-8")

    with pytest.raises(ValueError, match="old_text_not_found"):
        _edit(tools, path, "def get_user(user_id):\n  return USERS.get(user_id)",   # 2칸 (파일은 4칸)
              "def fetch_user(user_id):\nreturn USERS.get(user_id)")               # new 만 0칸
    assert path.read_text(encoding="utf-8") == _DB


def test_an_exact_match_is_untouched_and_not_reported_as_healed(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "db.py"
    path.write_text(_DB, encoding="utf-8")

    result = _edit(tools, path, "    return USERS.get(user_id)", "    return USERS.get(user_id) or {}")

    assert "healed" not in result
    assert "or {}" in path.read_text(encoding="utf-8")


def test_the_rescue_itself_is_pure_and_returns_nothing_for_junk() -> None:
    assert _rescue_edit("", "x", "y") == ("", "", "")
    assert _rescue_edit("abc\n", "   \n", "y") == ("", "", "")
    assert _rescue_edit("abc\n", "zzz", "y") == ("", "", "")


# --- 쓰기 경로 ------------------------------------------------------------------

def test_a_relative_path_starting_with_the_workspace_name_is_not_nested(tmp_path: Path) -> None:
    """노트북 L1 2회차 — `L1_hello_page-r2/index.html` 로 써서 작업 폴더 안에 같은 이름의 하위 폴더가 생겼다."""
    tools, work = _tools(tmp_path, name="L1_hello_page-r2")

    result = tools.write_file({"path": "L1_hello_page-r2/index.html", "content": "<h1>x</h1>", "__job_id": "code-job"})

    assert (work / "index.html").exists()
    assert not (work / "L1_hello_page-r2").exists()
    assert Path(result["path"]).resolve() == (work / "index.html").resolve()


def test_a_real_subfolder_with_that_name_is_respected(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path, name="proj")
    (work / "proj").mkdir()  # 진짜 하위 폴더가 이미 있다

    tools.write_file({"path": "proj/a.txt", "content": "x", "__job_id": "code-job"})

    assert (work / "proj" / "a.txt").exists()


def test_an_ordinary_relative_path_is_unchanged(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)

    tools.write_file({"path": "index.html", "content": "x", "__job_id": "code-job"})

    assert (work / "index.html").exists()


def test_a_crlf_file_keeps_one_line_ending_style_after_a_rescue(tmp_path: Path) -> None:
    """윈도우 파일(CRLF)에 LF 로 온 `new` 를 그대로 끼우면 한 파일에 줄바꿈이 섞인다."""
    tools, work = _tools(tmp_path)
    path = work / "db.py"
    path.write_bytes(_DB.replace("\n", "\r\n").encode("utf-8"))

    _edit(tools, path, "def get_user(user_id):\nreturn USERS.get(user_id)",
          "def fetch_user(user_id):\n    return USERS.get(user_id)")

    raw = path.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n"), "줄바꿈이 섞였다"
    assert b"fetch_user" in raw


def test_the_first_lines_indentation_always_comes_from_the_file(tmp_path: Path) -> None:
    """중첩된 코드에서 `old`·`new` 첫 줄의 들여쓰기가 빠져도 파일의 들여쓰기가 남는다 — 안 그러면 블록에서 튀어나간다."""
    tools, work = _tools(tmp_path)
    path = work / "svc.py"
    path.write_text("class S:\n    def run(self):\n        x = 1\n        return x\n", encoding="utf-8")

    _edit(tools, path, "x = 1\nreturn x", "x = 2\n        return x")  # 첫 줄 들여쓰기 없음, 둘째 줄은 있음

    assert path.read_text(encoding="utf-8") == "class S:\n    def run(self):\n        x = 2\n        return x\n"


def test_a_new_first_line_with_extra_leading_space_is_not_double_indented(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "svc.py"
    path.write_text("class S:\n    def run(self):\n        x = 1\n        return x\n", encoding="utf-8")

    _edit(tools, path, "x = 1\nreturn x", "        x = 3\n        return x")  # `new` 첫 줄에는 이미 8칸

    assert path.read_text(encoding="utf-8") == "class S:\n    def run(self):\n        x = 3\n        return x\n"


# --- old 와 new 가 똑같이 들여쓰기를 잃은 경우 (2026-09-22, 노트북 4B fin3 실측) ------------------
#
# 이름만 바꾸는 편집에서 4B 는 둘 다 둘째 줄부터 들여쓰기를 뺐다. 도구는 「100% 비슷」이라 말하고도 거절했다.
# 모델이 들여쓰기를 바꾸려던 게 아니므로 **파일의 들여쓰기**를 그대로 되살린다 — 우리가 만드는 값은 없다.

def test_a_rename_where_both_old_and_new_lost_the_indentation_is_rescued_from_the_file(tmp_path: Path) -> None:
    """노트북 L5 3회차의 모양 그대로."""
    tools, work = _tools(tmp_path)
    path = work / "db.py"
    path.write_text(_DB, encoding="utf-8")

    result = _edit(tools, path, "def get_user(user_id):\nreturn USERS.get(user_id)",
                   "def fetch_user(user_id):\nreturn USERS.get(user_id)")

    assert path.read_text(encoding="utf-8") == _DB.replace("def get_user", "def fetch_user")
    assert result["healed"] == "indentation_from_file"


def test_the_file_indentation_is_restored_line_by_line_even_when_nested(tmp_path: Path) -> None:
    """노트북 L5 2회차 — 함수 안의 두 줄, 둘 다 들여쓰기가 없다."""
    tools, work = _tools(tmp_path)
    path = work / "test_users.py"
    path.write_text('def test_a():\n    assert get_user(1) == "kim"\n    assert get_user(99) is None\n', encoding="utf-8")

    _edit(tools, path, 'assert get_user(1) == "kim"\nassert get_user(99) is None',
          'assert fetch_user(1) == "kim"\nassert fetch_user(99) is None')

    assert path.read_text(encoding="utf-8") == (
        'def test_a():\n    assert fetch_user(1) == "kim"\n    assert fetch_user(99) is None\n'
    )


def test_a_structure_changing_edit_is_never_reindented(tmp_path: Path) -> None:
    """줄 수가 다르면 모델이 구조를 바꾸려는 것이다 — 파일의 들여쓰기를 끼워 맞추지 않는다."""
    tools, work = _tools(tmp_path)
    path = work / "db.py"
    path.write_text(_DB, encoding="utf-8")

    with pytest.raises(ValueError, match="old_text_not_found"):
        _edit(tools, path, "def get_user(user_id):\nreturn USERS.get(user_id)",
              "def get_user(user_id):\nuser = USERS.get(user_id)\nreturn user")
    assert path.read_text(encoding="utf-8") == _DB


def test_an_edit_that_meant_to_change_the_indentation_is_left_to_the_older_path(tmp_path: Path) -> None:
    """`new` 의 들여쓰기가 `old` 와 다르면 모델이 들여쓰기를 바꾸려던 것이다 — 파일 것으로 덮어쓰지 않는다."""
    tools, work = _tools(tmp_path)
    path = work / "db.py"
    path.write_text(_DB, encoding="utf-8")

    # old 는 들여쓰기 없이, new 는 제대로 온 앞의 구제 사례 — 그대로 `new` 를 따른다(예전 동작)
    _edit(tools, path, "def get_user(user_id):\nreturn USERS.get(user_id)",
          "def fetch_user(user_id):\n    return USERS.get(user_id)")

    assert path.read_text(encoding="utf-8") == _DB.replace("def get_user", "def fetch_user")


def test_when_the_indentation_already_matches_the_file_nothing_is_reindented(tmp_path: Path) -> None:
    """고칠 게 없다 — 빈 줄 수만 다른 경우는 `new` 를 그대로 쓴다."""
    tools, work = _tools(tmp_path)
    path = work / "api.py"
    path.write_text("import a\n\n\ndef f():\n    return 1\n", encoding="utf-8")

    result = _edit(tools, path, "import a\n\ndef f():\n    return 1", "import a\n\n\ndef f():\n    return 2")

    assert path.read_text(encoding="utf-8") == "import a\n\n\ndef f():\n    return 2\n"
    assert result["healed"] == "indentation"


def test_reindenting_uses_tabs_when_the_file_uses_tabs(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    path = work / "t.py"
    path.write_bytes(b"def f():\n\treturn 1\n")

    _edit(tools, path, "def f():\nreturn 1", "def g():\nreturn 1")

    assert path.read_bytes() == b"def g():\n\treturn 1\n"  # 공백으로 바꾸지 않는다 — 파일의 것이다
