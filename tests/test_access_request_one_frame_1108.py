"""허락 요청 한 틀 (2026-11-08 대표 「게임만 아니라 다른 분야에서도」 · 게임 시험 3단계 unity_project_required).

- 막힌 도구는 같은 문장(`access_door`)으로 같은 문(`local_request_path_access`)을 가리킨다.
- 카드에는 무엇 · 어디 · 왜 · 안에 든 것 · 생긴 때가 보인다.
- 누르면 반드시 실패할 요청(비밀 · 너무 넓음 · 쓰기를 못 넓히는 모델)은 카드 전에 돌려보낸다. 자동 허락은 없다.
- 카드로 열린 유니티 프로젝트는 게임 팩이 바로 찾는다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools
from alture_jarvis.unity_tools import UnityTools


def _tools(tmp_path: Path, measured: bool, monkeypatch) -> tuple[LocalComputerTools, Path]:
    home, work = tmp_path / "home", tmp_path / "home" / "Documents" / "Sonjari"
    work.mkdir(parents=True)
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "out",
                          local_file_allowed_roots=str(work), local_read_roots=str(home),
                          model_roles={"chat": "x"})
    tools = LocalComputerTools(config)
    monkeypatch.setattr(tools, "_model_grade", lambda: {"measured": measured, "model": "x"})
    return tools, home


def _unity_project(path: Path, version: str = "6000.6.3f1") -> Path:
    (path / "ProjectSettings").mkdir(parents=True)
    (path / "Assets").mkdir()
    (path / "ProjectSettings" / "ProjectVersion.txt").write_text(f"m_EditorVersion: {version}\n", encoding="utf-8")
    return path


def test_card_says_what_where_why_and_what_is_inside(tmp_path, monkeypatch) -> None:
    tools, home = _tools(tmp_path, True, monkeypatch)
    project = _unity_project(home / "Games" / "BugGuard")
    card = tools.describe_access_request({"path": str(project), "mode": "write", "reason": "Mirror 를 넣으려고"})
    assert card["무엇"].startswith("이 폴더를 읽고 쓰게")
    assert card["어디"] == str(project.resolve())
    assert card["왜"] == "Mirror 를 넣으려고"
    assert "유니티 프로젝트 (6000.6.3f1)" in card["안에 든 것"]
    if "생긴 때" in card:  # 생긴 시각을 주지 않는 파일 시스템도 있다
        assert "새로 생긴 폴더" in card["생긴 때"]


def test_card_for_missing_folder_and_no_reason(tmp_path, monkeypatch) -> None:
    tools, home = _tools(tmp_path, True, monkeypatch)
    card = tools.describe_access_request({"path": str(home / "없음"), "mode": "read"})
    assert card["안에 든 것"] == "아직 없는 폴더" and "까닭을 적지 않음" in card["왜"]


def test_doomed_requests_never_become_cards(tmp_path, monkeypatch) -> None:
    tools, home = _tools(tmp_path, False, monkeypatch)
    (home / ".ssh").mkdir()
    with pytest.raises(PermissionError, match="sensitive_path_blocked"):
        tools._access_request_pre_check({"path": str(home / ".ssh"), "mode": "read"})
    with pytest.raises(PermissionError, match="model_not_benchmarked"):
        tools._access_request_pre_check({"path": str(home / "Games"), "mode": "write"})
    tools._access_request_pre_check({"path": str(home / "Games"), "mode": "read"})  # 읽기는 카드로 간다


def test_door_sentence_depends_on_what_the_model_may_do(tmp_path, monkeypatch) -> None:
    measured, _ = _tools(tmp_path / "a", True, monkeypatch)
    door = measured.access_door(Path("/x/proj"), "write")
    assert "local_request_path_access" in door and str(Path("/x/proj")) in door
    unmeasured, _ = _tools(tmp_path / "b", False, monkeypatch)
    door = unmeasured.access_door(Path("/x/proj"), "write")
    assert "local_request_path_access" not in door, "누르면 실패할 카드를 권하지 않는다"
    assert "설정 › 권한·안전" in door and "Sonjari" in door, "사람 길과 이미 쓸 수 있는 자리를 같이"


def test_unity_refusal_points_at_the_door_and_granted_project_is_found(tmp_path, monkeypatch) -> None:
    local, home = _tools(tmp_path, True, monkeypatch)
    project = _unity_project(home / "Games" / "BugGuard")
    unity = UnityTools(local.config, local)
    monkeypatch.setattr(UnityTools, "_PROJECT_ROOTS", ())
    monkeypatch.setattr(UnityTools, "_DRIVE_ROOTS", ())
    with pytest.raises(PermissionError) as blocked:
        unity._project({"project": str(project)}, write=True)
    assert "unity_project_not_allowed" in str(blocked.value) and "local_request_path_access" in str(blocked.value)
    local.request_path_access({"path": str(project), "mode": "write", "reason": "게임"})  # 사람이 카드를 누른 뒤
    assert unity._project({}, write=True) == project.resolve(), "카드로 열린 프로젝트는 project 를 빼도 찾는다"


def test_project_made_inside_a_writable_place_needs_no_card(tmp_path, monkeypatch) -> None:
    local, home = _tools(tmp_path, False, monkeypatch)
    project = _unity_project(home / "Documents" / "Sonjari" / "BugGuard")
    unity = UnityTools(local.config, local)
    monkeypatch.setattr(UnityTools, "_PROJECT_ROOTS", ())
    monkeypatch.setattr(UnityTools, "_DRIVE_ROOTS", ())
    assert unity._project({}, write=True) == project.resolve()


def test_no_project_at_all_names_the_writable_place(tmp_path, monkeypatch) -> None:
    local, _home = _tools(tmp_path, False, monkeypatch)
    unity = UnityTools(local.config, local)
    monkeypatch.setattr(UnityTools, "_PROJECT_ROOTS", ())
    monkeypatch.setattr(UnityTools, "_DRIVE_ROOTS", ())
    with pytest.raises(ValueError) as blocked:
        unity._project({}, write=True)
    assert "unity_project_required" in str(blocked.value) and "Sonjari" in str(blocked.value)
