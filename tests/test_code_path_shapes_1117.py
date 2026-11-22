"""코드 판의 경로 칸 두 가지 (2026-11-17 맥 새 계정 · 4B 코드 판).

1. `path` 칸에 원소 하나짜리 목록 글자(`["sample.py"]`)가 왔다 — 목록을 받는 칸과 헷갈린 것. 풀어 준다(둘 이상이면 그대로).
2. 작업 폴더가 `~/Documents` 인데 파일이 `~/Documents/Documents/…` 에 생겼다. 쓰기 길은 9-22부터 「작업 폴더 이름으로 시작하는
   상대 경로」에서 그 이름을 떼는데, 저장소 기준으로 푸는 읽기 · 실행 길은 안 떼어 같은 글자가 두 자리를 가리켰다. 규칙을 맞춘다.
   (그날 겹침의 정확한 걸음은 기록이 사라져 확인 못 함 — 셸이 먼저 폴더를 만들었을 가능성. 이 시험은 코드로 보이는 빈틈만 막는다.)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _tools(tmp_path: Path) -> tuple[LocalComputerTools, Path]:
    work = tmp_path / "Documents"
    work.mkdir()
    (work / "sample.py").write_text("x = 1\n", encoding="utf-8")
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          local_file_allowed_roots=str(work), local_read_roots=str(tmp_path))
    tools = LocalComputerTools(config)
    tools.authorize_code_workspace("code-job", str(work))
    return tools, work


@pytest.mark.parametrize("given", ['["sample.py"]', ["sample.py"], ' ["sample.py"] '])
def test_a_one_item_list_in_the_path_field_is_the_path(tmp_path: Path, given) -> None:
    tools, work = _tools(tmp_path)
    assert tools._resolve_workspace_path({"__job_id": "code-job", "path": given}) == (work / "sample.py").resolve()
    assert tools._resolve_mutation_path({"__job_id": "code-job", "path": given}, must_exist=True) == (work / "sample.py").resolve()


def test_two_items_are_not_guessed(tmp_path: Path) -> None:
    tools, _work = _tools(tmp_path)
    with pytest.raises(Exception):
        tools._resolve_workspace_path({"__job_id": "code-job", "path": '["sample.py", "other.py"]'})


def test_a_path_starting_with_the_workspace_name_means_inside_it(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    (work / "t").mkdir()
    (work / "t" / "primes.py").write_text("print(2)\n", encoding="utf-8")
    args = {"__job_id": "code-job", "path": "Documents/t/primes.py"}
    assert tools._resolve_workspace_path(args) == (work / "t" / "primes.py").resolve()
    assert tools._resolve_mutation_path(args, must_exist=True) == (work / "t" / "primes.py").resolve(), "읽기 · 실행과 쓰기가 같은 자리"


def test_a_real_subfolder_with_that_name_is_left_alone(tmp_path: Path) -> None:
    tools, work = _tools(tmp_path)
    (work / "Documents").mkdir()
    (work / "Documents" / "a.py").write_text("x\n", encoding="utf-8")
    assert tools._resolve_workspace_path({"__job_id": "code-job", "path": "Documents/a.py"}) == (work / "Documents" / "a.py").resolve()


# ── 11-18: 읽기 · 목록도 첫 칸이 사용자 폴더 이름이면 사람의 진짜 폴더(쓰기 9-23 규칙과 같게) ──────────────────
def _cowork(tmp_path: Path, monkeypatch) -> tuple[LocalComputerTools, Path]:
    home = tmp_path / "home"
    (home / "Documents" / "Sonjari").mkdir(parents=True)
    (home / "Documents" / "Sonjari" / "a.docx").write_text("x", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          local_file_allowed_roots=str(tmp_path / "out"), local_read_roots=str(home))
    return LocalComputerTools(config), home


@pytest.mark.parametrize("given", ["documents/Sonjari", "Documents/Sonjari", "문서/Sonjari", "documents"])
def test_reading_a_user_folder_name_means_the_real_folder(tmp_path: Path, monkeypatch, given: str) -> None:
    tools, home = _cowork(tmp_path, monkeypatch)
    want = home / "Documents" / ("Sonjari" if "/" in given else "")
    assert tools._resolve_workspace_path({"__job_id": "cowork-job", "path": given}) == want.resolve()


def test_a_real_subfolder_on_the_desk_wins(tmp_path: Path, monkeypatch) -> None:
    tools, _home = _cowork(tmp_path, monkeypatch)
    desk = tools.job_workspace("cowork-job")
    (desk / "documents").mkdir(parents=True, exist_ok=True)
    assert tools._resolve_workspace_path({"__job_id": "cowork-job", "path": "documents"}) == (desk / "documents").resolve()


def test_listing_it_shows_the_files(tmp_path: Path, monkeypatch) -> None:
    tools, _home = _cowork(tmp_path, monkeypatch)
    listed = tools.list_directory({"__job_id": "cowork-job", "path": "documents/Sonjari"})
    assert [item["name"] for item in listed["items"]] == ["a.docx"]


# ── 11-18 버그 9: 「최근 바뀐 파일」은 목록에 바뀐 시각이 있어야 고른다 ──────────────────────────
def test_newest_first_with_times_only_when_asked(tmp_path: Path, monkeypatch) -> None:
    import os
    tools, home = _cowork(tmp_path, monkeypatch)
    folder = home / "Documents" / "Sonjari"
    for index, name in enumerate(("old.docx", "mid.xlsx", "new.md")):
        (folder / name).write_text("x", encoding="utf-8")
        os.utime(folder / name, (1_700_000_000 + index * 1000, 1_700_000_000 + index * 1000))
    os.utime(folder / "a.docx", (1_600_000_000, 1_600_000_000))
    plain = tools.list_directory({"__job_id": "cowork-job", "path": "documents/Sonjari"})
    assert "modified" not in plain["items"][0], "평소 목록은 짧게 그대로"
    newest = tools.list_directory({"__job_id": "cowork-job", "path": "documents/Sonjari", "sort": "newest"})
    assert [item["name"] for item in newest["items"]][:3] == ["new.md", "mid.xlsx", "old.docx"]
    assert all(len(item["modified"]) == 16 for item in newest["items"])
