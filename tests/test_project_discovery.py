from __future__ import annotations

from pathlib import Path

from alture_jarvis.project_discovery import ProjectDiscovery


def _project(root: Path, relative: str, *markers: str) -> Path:
    folder = root / relative
    folder.mkdir(parents=True)
    for marker in markers:
        target = folder / marker
        if marker == ".git":
            target.mkdir()
        else:
            target.write_text("fixture", encoding="utf-8")
    return folder.resolve()


def test_korean_conversation_name_resolves_nested_jarvis_repo(tmp_path: Path) -> None:
    root = tmp_path / "academy"
    root.mkdir()
    jarvis = _project(root, "tools/alture-jarvis", ".git", "pyproject.toml", "CLAUDE.md")
    _project(root, "tools/other-service", ".git", "pyproject.toml")
    discovery = ProjectDiscovery([root], tmp_path / "state.json", cache_ttl_sec=0)

    result = discovery.discover("\uc790\ube44\uc2a4 \uc790\uae30 \uc790\uc2e0\uc744 \uace0\ub3c4\ud654\ud574\uc11c \ubc84\uadf8\ub97c \uace0\uccd0\uc918")

    assert result.status == "resolved"
    assert Path(result.workspace) == jarvis
    assert result.source == "conversation"
    assert result.confidence >= 0.7
    assert any("jarvis" in reason for reason in result.candidates[0].reasons)


def test_named_repo_beats_nested_packages_that_only_inherit_its_path_token(tmp_path: Path) -> None:
    root = tmp_path / "academy"
    root.mkdir()
    jarvis = _project(root, "tools/alture-jarvis", "pyproject.toml")
    _project(jarvis, "ui", "package.json")
    _project(jarvis, "ui/src-tauri", "Cargo.toml")
    discovery = ProjectDiscovery([root], tmp_path / "state.json", cache_ttl_sec=0)

    result = discovery.discover("\uc790\ube44\uc2a4 \uc790\uae30 \uc790신을 \uace0\ub3c4\ud654\ud574\uc918")

    assert result.status == "resolved"
    assert Path(result.workspace) == jarvis
    assert result.candidates[0].confidence - result.candidates[1].confidence >= 0.12
    assert "\ud504\ub85c\uc81d\ud2b8 \uc774\ub984 \uc9c1\uc811 \uc77c\uce58" in result.candidates[0].reasons[0]


def test_recent_workspace_continues_without_requiring_folder_again(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    chosen = _project(root, "alpha", ".git", "pyproject.toml")
    _project(root, "beta", ".git", "package.json")
    discovery = ProjectDiscovery([root], tmp_path / "state.json", cache_ttl_sec=0)
    discovery.remember("code-one", str(chosen))

    result = discovery.discover("\uc544\uae4c \uc2e4\ud328 \ud14c\uc2a4\ud2b8 \uc774\uc5b4\uc11c \uace0\uccd0\uc918", session_id="code-one")

    assert result.status == "resolved"
    assert Path(result.workspace) == chosen
    assert result.source == "recent"


def test_ambiguous_projects_do_not_receive_automatic_write_scope(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    _project(root, "service-one", ".git", "pyproject.toml")
    _project(root, "service-two", ".git", "pyproject.toml")
    discovery = ProjectDiscovery([root], tmp_path / "state.json", cache_ttl_sec=0)

    result = discovery.discover("버그 고쳐줘")

    assert result.status == "ambiguous"
    assert result.workspace == ""
    assert len(result.candidates) == 2


def test_stale_recent_workspace_is_ignored(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    discovery = ProjectDiscovery([root], tmp_path / "state.json", cache_ttl_sec=0)
    old = _project(root, "deleted", ".git")
    discovery.remember("code-one", str(old))
    (old / ".git").rmdir()
    old.rmdir()

    result = discovery.discover("계속해줘", session_id="code-one")

    assert result.status == "not_found"
