"""작은 폴더는 색인 결과를 따로 붙이지 않는다 (2026-10-07 코딩 사다리 L6).

파일 셋짜리 폴더에서 코드 판은 저장소 지도를 받고, 곧이어 색인 결과(같은 파일들 + 줄 범위, 약 2,500토큰)를 또 받았다.
폴더 전체가 읽기 한 번의 기본 상한보다 작으면 「어느 줄부터 읽어라」가 줄 것이 없다. 그런 폴더는 지도가 파일을 전부 적고
머리말로 그렇다고 말한다 — 부르는 쪽은 그 머리말을 보고 색인 걸음을 건너뛴다.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from alture_jarvis import agent as agent_module
from alture_jarvis import code_index, local_computer
from alture_jarvis.code_index import SMALL_FOLDER_CARD_HEAD, CodeIndex


def _small_project(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pager.py").write_text('def page_count(total_items, page_size):\n    """쪽 수."""\n    return total_items // page_size\n', encoding="utf-8")
    (root / "slicer.py").write_text("from pager import page_count\n\n\ndef page_items(items, page, page_size):\n    return items[:page_size]\n", encoding="utf-8")
    (root / "test_pager.py").write_text("from pager import page_count\n\n\ndef test_count_exact():\n    assert page_count(10, 5) == 2\n", encoding="utf-8")
    (root / "README.md").write_text("쪽 나누기 연습\n", encoding="utf-8")


def test_a_small_folders_map_lists_every_file_and_says_so(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _small_project(project)
    index = CodeIndex(tmp_path / "indexes")
    index.refresh(project)

    card = index.repo_card(project, "test_pager.py 가 실패한다")

    assert card.startswith(SMALL_FOLDER_CARD_HEAD)
    for name in ("pager.py", "slicer.py", "test_pager.py", "README.md"):
        assert f"  {name}" in card, f"{name} 이 지도에 없다 — 「전부」라고 말하려면 빠진 파일이 없어야 한다"
    assert "page_count" in card, "요약이 있는 파일은 예전처럼 요약과 함께 적는다"


def test_a_folder_bigger_than_one_read_keeps_the_old_map_and_the_index_step(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _small_project(project)
    (project / "big.py").write_text("def filler():\n    return 0\n\n" + "# 채우는 줄\n" * 4000, encoding="utf-8")
    index = CodeIndex(tmp_path / "indexes")
    index.refresh(project)

    card = index.repo_card(project, "test_pager.py 가 실패한다")

    assert card.startswith("[저장소 지도] 참조가 많은 순.")
    assert "README.md" not in card, "큰 폴더의 지도는 예전 그대로다 — 요약 없는 파일을 끼워 넣지 않는다"


def test_small_means_smaller_than_one_default_read() -> None:
    """두 값이 갈리면 「통째로 읽으면 된다」가 거짓이 된다."""
    assert code_index.WHOLE_FOLDER_READ_CHARS == local_computer.SURVEY_READ_CHARS


def test_the_agent_skips_the_index_step_only_on_that_headline() -> None:
    source = inspect.getsource(agent_module.BrowserAgent.run)
    assert "repo_card.startswith(SMALL_FOLDER_CARD_HEAD)" in source
    assert "if required_local_root and not checkpoint and not steps and not index_is_redundant:" in source
    assert 'self.code_scout is not None and bool(getattr(self.code_scout, "enabled", False))' in source, (
        "정찰기는 색인 결과를 받아 일한다 — 켜져 있으면 건너뛰지 않는다"
    )
