"""경로 없이 불린 찾기 도구가 **거절 대신 허용된 자리에서 찾는다** (2026-09-20 이 PC 실측).

코워크 작업 「이 PC 의 현재 Ollama/Qwen 배치를 진단」(374초·18턴)에서 `local_glob: path_required` 가 **9번**,
다른 작업에서 `local_grep: path_required` 가 두 번 났다. 모델은 패턴만 바꿔 가며 경로 없이 또 불렀다 — 인자가
조금씩 달라 「같은 호출 되풀이」 알림에도 안 걸렸다. 한 단어짜리 거절은 걸음만 먹는다. 안내문 대신 도구가 정한다(사고 R).
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.config import JarvisConfig
from alture_jarvis.local_computer import LocalComputerTools


def _tools(tmp_path: Path) -> tuple[LocalComputerTools, Path, Path]:
    one, two = tmp_path / "Documents", tmp_path / "Desktop"
    (one / "notes").mkdir(parents=True)
    two.mkdir()
    (one / "notes" / "ollama.md").write_text("qwen3.6 128K 설정\n", encoding="utf-8")
    (two / "plan.md").write_text("다음 할 일: qwen3.6 실측\n", encoding="utf-8")
    tools = LocalComputerTools(JarvisConfig(local_file_allowed_roots=f"{one};{two}"))
    # 도구는 설정 밖의 실제 문서 폴더도 허용 자리에 붙인다 — 시험이 이 PC 의 파일을 뒤지지 않게 둘로 고정한다.
    tools.allowed_roots = [one.resolve(), two.resolve()]
    return tools, one, two


def test_glob_without_a_path_searches_every_allowed_root(tmp_path: Path) -> None:
    tools, one, two = _tools(tmp_path)
    out = tools.glob_files({"pattern": "**/*.md"})
    names = sorted(Path(row["path"]).name for row in out["items"])
    assert names == ["ollama.md", "plan.md"]
    assert set(out["searched_roots"]) == {str(one.resolve()), str(two.resolve())}
    assert "path" in out["note"], "경로를 안 줬다는 사실과 어디를 찾았는지 말해 줘야 다음엔 좁힌다"


def test_grep_without_a_path_searches_every_allowed_root(tmp_path: Path) -> None:
    tools, _one, _two = _tools(tmp_path)
    out = tools.grep_files({"pattern": "qwen3.6"})
    assert out["count"] == 2


def test_listing_without_a_path_shows_where_it_may_look(tmp_path: Path) -> None:
    tools, one, two = _tools(tmp_path)
    out = tools.list_directory({})
    assert {row["path"] for row in out["items"]} == {str(one.resolve()), str(two.resolve())}
    assert all(row["type"] == "directory" for row in out["items"])


def test_a_given_path_behaves_exactly_as_before(tmp_path: Path) -> None:
    """★ 좋은 표본 — 경로를 주면 지금과 한 글자도 다르지 않다."""
    tools, one, _two = _tools(tmp_path)
    out = tools.glob_files({"path": str(one), "pattern": "**/*.md"})
    assert [Path(row["path"]).name for row in out["items"]] == ["ollama.md"]
    assert "searched_roots" not in out


def test_an_empty_pattern_is_still_refused(tmp_path: Path) -> None:
    """찾을 것이 없으면 찾을 수 없다 — 이건 기본값으로 메울 수 없는 빈칸이다."""
    import pytest

    tools, _one, _two = _tools(tmp_path)
    with pytest.raises(ValueError, match="pattern_required"):
        tools.glob_files({})
