"""폴더 권한 재설계 — **읽기는 넓게, 쓰기는 좁게, 비밀은 차단, 넓히려면 승인** (2026-09-20 사용자 요청).

오늘 코워크 작업들이 `C:\\Users\\user`·저장소 경로·메모 폴더에서 전부 `path_outside_allowed_roots` 로 막혔다. 코워크는
사용자 PC 를 보고 답하는 자리라 **읽을 수 있어야 보고가 된다.** 반대로 쓰기는 좁아야 하고, 비밀 파일은 읽기도 막아야 한다.

- 읽기: 허용 목록 + 사용자 폴더 전체 + 승인으로 넓힌 자리
- 쓰기: 허용 목록(작업 폴더) + **쓰기 승인**으로 넓힌 자리
- 비밀: `.env`·`.ssh`·`.claude`·`.codex`·토큰·자격증명·브라우저 프로필은 **읽기도** 차단
- 넓히기: 모델이 `local_request_path_access` 를 부르면 **L2 승인 카드**가 뜬다(사람 승인 없이는 안 열린다)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _tools(tmp_path: Path) -> tuple[LocalComputerTools, Path, Path]:
    home, work = tmp_path / "home", tmp_path / "home" / "Documents" / "Ontelic"
    # 다시 켜 보는 시험이 같은 자리를 두 번 만든다 — 그래서 `exist_ok`.
    (home / "project").mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    (home / "project" / "readme.md").write_text("프로젝트 설명\n", encoding="utf-8")
    (home / ".ssh").mkdir(exist_ok=True)
    (home / ".ssh" / "id_ed25519").write_text("비밀키\n", encoding="utf-8")
    (home / "project" / ".env").write_text("TOKEN=비밀\n", encoding="utf-8")
    config = JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data",
                          local_file_allowed_roots=str(work), local_read_roots=str(home),
                          model_roles={"chat": "qwen3.5:9b"})
    return LocalComputerTools(config), home, work


def test_reading_outside_the_work_folder_is_allowed(tmp_path: Path) -> None:
    tools, home, _work = _tools(tmp_path)
    out = tools.read_text_file({"path": str(home / "project" / "readme.md")})
    assert "프로젝트 설명" in str(out.get("text") or out.get("content") or "")


def test_writing_outside_the_work_folder_is_refused(tmp_path: Path) -> None:
    tools, home, _work = _tools(tmp_path)
    with pytest.raises(PermissionError) as blocked:
        tools.write_file({"path": str(home / "project" / "새파일.txt"), "content": "x"})
    assert "local_request_path_access" in str(blocked.value), "막기만 하면 모델은 같은 호출을 되풀이한다 — 넓히는 길을 알려 준다"


def test_read_only_folder_is_not_an_upload_source(tmp_path: Path) -> None:
    tools, home, _work = _tools(tmp_path)
    note = home / "project" / "readme.md"
    assert tools.resolve_allowed_path(str(note)) == note.resolve()
    with pytest.raises(PermissionError, match="outside"):
        tools.resolve_export_path(str(note))


def test_secrets_are_blocked_even_for_reading(tmp_path: Path) -> None:
    tools, home, _work = _tools(tmp_path)
    for secret in (home / ".ssh" / "id_ed25519", home / "project" / ".env"):
        with pytest.raises(PermissionError):
            tools.read_text_file({"path": str(secret)})


def test_app_data_is_blocked_even_when_inside_a_readable_home(tmp_path: Path) -> None:
    tools, home, _work = _tools(tmp_path)
    tools.config.data_dir = home / "app-data"
    tools.config.data_dir.mkdir()
    private = tools.config.data_dir / "jarvis.db"
    private.write_text("private", encoding="utf-8")
    with pytest.raises(PermissionError, match="sensitive"):
        tools.read_text_file({"path": str(private)})
    with pytest.raises(PermissionError, match="sensitive"):
        tools.request_path_access({"path": str(tools.config.data_dir), "mode": "read", "reason": "DB"})


def test_reading_far_outside_the_home_is_refused(tmp_path: Path) -> None:
    tools, _home, _work = _tools(tmp_path)
    outside = tmp_path / "other" / "somebody.txt"
    outside.parent.mkdir()
    outside.write_text("남의 것\n", encoding="utf-8")
    with pytest.raises(PermissionError):
        tools.read_text_file({"path": str(outside)})


def test_a_granted_folder_opens_that_place(tmp_path: Path) -> None:
    tools, _home, _work = _tools(tmp_path)
    outside = tmp_path / "other"
    outside.mkdir()
    (outside / "note.md").write_text("바깥 메모\n", encoding="utf-8")
    granted = tools.request_path_access({"path": str(outside), "mode": "read", "reason": "여기 자료를 읽어야 합니다"})
    assert granted["ok"] is True and granted["mode"] == "read"
    opened = tools.read_text_file({"path": str(outside / "note.md")})
    assert "바깥 메모" in str(opened.get("text") or opened.get("content") or "")
    # 쓰기는 여전히 막힌다 — 읽기 승인은 읽기까지만.
    with pytest.raises(PermissionError):
        tools.write_file({"path": str(outside / "x.txt"), "content": "x"})


def test_a_grant_survives_a_restart(tmp_path: Path) -> None:
    tools, _home, _work = _tools(tmp_path)
    outside = tmp_path / "other2"
    outside.mkdir()
    tools.request_path_access({"path": str(outside), "mode": "write", "reason": "결과물을 여기 둡니다"})
    saved = json.loads((tmp_path / "data" / "granted_paths.json").read_text(encoding="utf-8"))
    assert any(str(outside).lower() in str(row).lower() for row in saved.get("write", []))
    again, _home2, _work2 = _tools(tmp_path)
    again.write_file({"path": str(outside / "결과.txt"), "content": "ok"})


def test_granting_a_secret_place_is_still_refused(tmp_path: Path) -> None:
    """★ 승인으로도 비밀은 못 연다 — 사람이 실수로 눌러도 토큰은 안 나간다."""
    tools, home, _work = _tools(tmp_path)
    with pytest.raises(PermissionError):
        tools.request_path_access({"path": str(home / ".ssh"), "mode": "read", "reason": "키를 보고 싶다"})


def test_relative_path_cannot_open_the_process_working_directory(tmp_path: Path) -> None:
    tools, _home, _work = _tools(tmp_path)
    with pytest.raises(ValueError, match="path_must_be_absolute"):
        tools.request_path_access({"path": "some-project", "mode": "read", "reason": "자료"})


def test_the_grant_tool_needs_approval() -> None:
    """도구가 L2 여야 승인 카드가 뜬다. L1 이면 모델이 혼자 폴더를 열 수 있다."""
    import inspect

    from alture_jarvis.local_computer import LocalComputerTools as T

    source = inspect.getsource(T.register)
    assert '"local_request_path_access": RiskLevel.L2' in source


# ── 「바탕화면/…」은 사람의 바탕화면이다 (2026-09-23 스토어 촬영) ─────────────────────────────
# 「바탕화면에 회의 메모.txt 만들어 줘」에 모델이 `바탕화면/회의 메모.txt` 를 줬고, 작업 폴더 안에 「바탕화면」 폴더를
# 새로 만들어 거기 썼다 — 승인도 안 거쳤고 사람은 바탕화면에서 파일을 못 찾는다.


def test_a_desktop_relative_path_means_the_real_desktop_and_asks_first(tmp_path: Path, monkeypatch) -> None:
    tools, home, work = _tools(tmp_path)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    (home / "Desktop").mkdir(exist_ok=True)
    with pytest.raises(PermissionError) as blocked:
        tools.write_file({"__job_id": "job-desk", "path": "바탕화면/회의 메모.txt", "content": "10시 회의"})
    assert "local_request_path_access" in str(blocked.value), "바탕화면은 작업 폴더 밖 — 승인 길로 가야 한다"
    assert not list(work.rglob("회의 메모.txt")), "작업 폴더 안에 가짜 「바탕화면」을 만들고 쓰면 안 된다"


def test_a_real_subfolder_named_like_a_user_folder_is_still_used(tmp_path: Path, monkeypatch) -> None:
    """★ 좋은 표본 — 작업 폴더에 정말 「문서」 하위 폴더가 있으면 그것이다(사람 폴더로 튀지 않는다)."""
    tools, home, work = _tools(tmp_path)
    monkeypatch.setenv("USERPROFILE", str(home))
    workspace = tools._mutation_workspace({"__job_id": "job-doc"}, create=True)
    (workspace / "문서").mkdir(parents=True, exist_ok=True)
    out = tools.write_file({"__job_id": "job-doc", "path": "문서/초안.txt", "content": "x"})
    assert Path(str(out.get("output_path") or out.get("path"))).parent == (workspace / "문서").resolve()


def test_an_ordinary_relative_path_stays_in_the_work_folder(tmp_path: Path) -> None:
    """★ 좋은 표본 — 사용자 폴더 이름이 아니면 예전처럼 작업 폴더 안."""
    tools, _home, _work = _tools(tmp_path)
    workspace = tools._mutation_workspace({"__job_id": "job-note"}, create=True)
    out = tools.write_file({"__job_id": "job-note", "path": "notes/a.txt", "content": "x"})
    assert Path(str(out.get("output_path") or out.get("path"))).resolve().is_relative_to(workspace.resolve())
