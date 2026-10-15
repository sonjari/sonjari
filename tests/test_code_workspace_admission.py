"""코드 탭에서 **사람이 고른 폴더**가 받아들여지는가 (2026-09-16 밤, 사용자님 스크린샷).

찾아보기로 `C:\\work\\monorepo` 를 고르고 보내자 요청 전체가 400 으로 거절됐다 — 허용 목록
(바탕화면·문서·다운로드) 밖이라서. 폴더 고르기는 되게 해 놓고 고른 것을 거절하는 모순이었다.
거절 문구도 절대 경로에 「상대 경로는…절대 경로를 주세요」라고 틀리게 말했다.

**양방향**으로 본다: 고른 저장소는 받고, 너무 넓은 자리는 여전히 막는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _tools(tmp_path: Path) -> LocalComputerTools:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    return LocalComputerTools(
        JarvisConfig(local_file_allowed_roots=str(allowed), data_dir=tmp_path / "ontelic-data")
    )


def test_a_repo_the_person_picked_outside_the_allowed_roots_is_admitted(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    repo = tmp_path / "elsewhere" / "my-repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")

    # 읽기는 사용자 폴더까지 열려도, 코드 잡의 무승인 쓰기 루트는 받기 전에는 거절된다.
    # 그리고 절대 경로에 「상대 경로」 안내를 하지 않는다.
    with pytest.raises(PermissionError) as before:
        tools.authorize_code_workspace("before", str(repo))
    assert "상대 경로" not in str(before.value)

    tools.admit_code_workspace(str(repo))
    assert tools.authorize_code_workspace("after", str(repo)) == repo.resolve()
    assert tools.resolve_allowed_path(str(repo / "src" / "app.py")) == (repo / "src" / "app.py").resolve()


@pytest.mark.parametrize("pick", ["drive_root", "home", "appdata", "ontelic_data"])
def test_too_broad_places_are_still_refused(tmp_path: Path, pick: str) -> None:
    tools = _tools(tmp_path)
    (tmp_path / "ontelic-data").mkdir()
    target = {
        "drive_root": Path(Path.home().anchor),
        "home": Path.home(),
        "appdata": Path.home() / "AppData",
        # 온텔릭 데이터가 든 폴더(그 위)를 고르면 대화·토큰까지 열린다.
        "ontelic_data": tmp_path,
    }[pick]
    if not target.is_dir():
        pytest.skip(f"{target} 가 이 PC 에 없다")
    with pytest.raises(PermissionError, match="code_workspace_too_broad"):
        tools.admit_code_workspace(str(target))


def test_relative_or_missing_workspace_is_refused(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    with pytest.raises(ValueError, match="must_be_absolute"):
        tools.admit_code_workspace("my-repo")
    with pytest.raises(FileNotFoundError):
        tools.admit_code_workspace(str(tmp_path / "does-not-exist"))


def test_sensitive_files_inside_an_admitted_repo_stay_blocked(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    tools.admit_code_workspace(str(repo))
    with pytest.raises(PermissionError, match="sensitive"):
        tools.resolve_allowed_path(str(repo / ".env"))


def test_the_chat_api_admits_a_picked_repo_but_not_one_passed_by_an_outside_ai() -> None:
    """API 층의 갈래를 소스에서 붙잡는다 — MCP 가 넘긴 경로로 폴더를 넓히면 안 된다."""
    source = (Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "api.py").read_text(
        encoding="utf-8"
    )
    assert 'elif request.origin != "mcp":' in source
    assert "admit_code_workspace(workspace)" in source
