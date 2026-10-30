"""`scripts/plan_request_diff.py` — plan.py 를 고치기 전 · 후로 운영 요청에 돌려 뜻밖에 바뀐 요청을 내는 도구 (2026-10-28).

가짜 작은 프로젝트(git 저장소 + `src/alture_jarvis/plan.py`)와 가짜 DB 로 확인한다: 기준은 커밋에서 풀어 돌고, 지금 쪽은 작업 트리 그대로이며,
작업 트리는 건드리지 않고, DB 는 읽기 전용이고, 출력에 요청 전문이 나가지 않는다.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location("plan_request_diff", Path(__file__).resolve().parent.parent / "scripts" / "plan_request_diff.py")
tool = importlib.util.module_from_spec(_SPEC)
sys.modules["plan_request_diff"] = tool
_SPEC.loader.exec_module(tool)

_PLAN_BEFORE = '''
from types import SimpleNamespace


def artifact_extensions(prompt):
    return [".md"] if "README" in prompt else [".xlsx"] if "엑셀" in prompt else []


def extract(prompt, own_from="", has_named_source=False):
    return [SimpleNamespace(kind="artifact", source_scope="")]
'''
# 지금 작업 트리의 plan.py: README 가 있어도 엑셀을 말했으면 엑셀로 간다(고침), 그리고 「폴더」 낱말은 local 로 읽는다(뜻밖의 변화).
_PLAN_AFTER = '''
from types import SimpleNamespace


def artifact_extensions(prompt):
    return [".xlsx"] if "엑셀" in prompt else [".md"] if "README" in prompt else []


def extract(prompt, own_from="", has_named_source=False):
    found = [SimpleNamespace(kind="artifact", source_scope="")]
    if "폴더" in prompt:
        found.append(SimpleNamespace(kind="count", source_scope="local"))
    return found
'''

_PROMPTS = [
    "README.md 를 읽고 엑셀로 정리해 줘. 개인정보가 들어 있을 수도 있는 아주 긴 문장이라서 앞 예순 자만 보이고 나머지는 어디에도 찍히면 안 된다 비밀꼬리",
    "엑셀 한 장으로 분기별 매출을 정리해 줘.",
    "README 만 읽어 줘.",
    "안녕",
    "D 폴더의 문서를 읽어 줘.",
]


def _git(folder: Path, *args: str) -> None:
    done = subprocess.run(["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@t", *args], capture_output=True)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    package = root / "src" / "alture_jarvis"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "plan.py").write_text(_PLAN_BEFORE, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "before")
    (package / "plan.py").write_text(_PLAN_AFTER, encoding="utf-8")        # 커밋하지 않은 작업 트리의 고침
    return root


@pytest.fixture()
def database(tmp_path: Path) -> Path:
    path = tmp_path / "jarvis.db"
    connection = sqlite3.connect(path)
    connection.execute("create table jobs (id integer primary key, payload_json text)")
    for prompt in [*_PROMPTS, _PROMPTS[1]]:                                  # 같은 요청이 두 번 와도 한 번으로 센다
        connection.execute("insert into jobs (payload_json) values (?)", (json.dumps({"prompt": prompt}, ensure_ascii=False),))
    connection.execute("insert into jobs (payload_json) values (?)", ("깨진 json",))
    connection.commit()
    connection.close()
    return path


def test_prompts_are_distinct_and_the_database_is_opened_read_only(database: Path) -> None:
    prompts = tool.read_prompts(database)
    assert prompts == _PROMPTS
    assert tool.read_prompts(database, limit=2) == _PROMPTS[:2]
    before = database.read_bytes()
    with pytest.raises(sqlite3.OperationalError):
        connection = sqlite3.connect("file:" + database.as_posix() + "?mode=ro", uri=True)
        connection.execute("insert into jobs (payload_json) values ('{}')")
    assert database.read_bytes() == before


def test_only_the_requests_whose_reading_changed_are_listed(project: Path, database: Path) -> None:
    rows, total, table = tool.run(project, "HEAD", database)

    assert total == len(_PROMPTS)
    by_prompt = {row["prompt"]: row for row in rows}
    assert set(by_prompt) == {_PROMPTS[0], _PROMPTS[4]}, "README+엑셀 요청(형식이 바뀜)과 「폴더」 요청(범위가 바뀜)만"
    assert by_prompt[_PROMPTS[0]]["before"]["ext"] == [".md"] and by_prompt[_PROMPTS[0]]["after"]["ext"] == [".xlsx"]
    assert by_prompt[_PROMPTS[4]]["before"]["scope"] == [] and by_prompt[_PROMPTS[4]]["after"]["scope"] == [["count", "local"]]
    assert "바뀐 요청 2개" in table and "서로 다른 요청 5개" in table


def test_the_output_never_carries_the_whole_request(project: Path, database: Path) -> None:
    _rows, _total, table = tool.run(project, "HEAD", database)
    assert "비밀꼬리" not in table
    assert tool.short(_PROMPTS[0]) in table and len(tool.short(_PROMPTS[0])) <= tool.SHOW_CHARS + 1
    assert tool.key_of(_PROMPTS[0])[:8] in table, "전문 대신 해시가 나간다"


def test_the_working_tree_is_left_exactly_as_it_was(project: Path, database: Path) -> None:
    plan_file = project / "src" / "alture_jarvis" / "plan.py"
    before_bytes = plan_file.read_bytes()
    status_before = subprocess.run(["git", "-C", str(project), "status", "--porcelain"], capture_output=True).stdout
    tool.run(project, "HEAD", database)
    assert plan_file.read_bytes() == before_bytes
    assert subprocess.run(["git", "-C", str(project), "status", "--porcelain"], capture_output=True).stdout == status_before
    assert not list(project.glob("**/*.zip")) and not list(project.glob("**/__pycache__"))
    assert subprocess.run(["git", "-C", str(project), "worktree", "list"], capture_output=True).stdout.decode().count("\n") == 1


def test_the_same_code_on_both_sides_changes_nothing(project: Path, database: Path) -> None:
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "now")
    rows, total, table = tool.run(project, "HEAD", database)
    assert rows == [] and total == len(_PROMPTS)
    assert "바뀐 요청 0개" in table and "바뀐 요청 없음" in table


def test_strict_mode_and_a_missing_commit(project: Path, database: Path, capsys: pytest.CaptureFixture) -> None:
    assert tool.main(["HEAD", "--db", str(database), "--project", str(project)]) == 0
    assert tool.main(["HEAD", "--db", str(database), "--project", str(project), "--strict"]) == 1
    capsys.readouterr()
    with pytest.raises(SystemExit):
        tool.main(["no-such-commit", "--db", str(database), "--project", str(project)])
