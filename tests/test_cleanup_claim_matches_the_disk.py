"""「임시 스크립트를 지웠다」는 말은 디스크와 맞아야 한다 (2026-09-30 질문 카드 촬영 판 4d4c44aa).

답은 「검증용으로 생성한 임시 스크립트들을 삭제하여 작업 폴더를 깨끗하게 유지했습니다」였는데
`final_check.py`·`final_check_v2.py`·`final_check_v3.py` 가 그대로 남았다. 정직 약속에 걸리는 거짓 주장이다.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from alture_jarvis.agent import BrowserAgent, cleanup_claim_left_files

CLAIM = "3.  **정리**: 검증용으로 생성한 임시 스크립트들을 삭제하여 작업 폴더를 깨끗하게 유지했습니다."


def _files(tmp_path: Path, *names: str) -> list[Path]:
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_text("x", encoding="utf-8")
        paths.append(path)
    return paths


def test_the_scripts_it_said_it_deleted_are_named(tmp_path: Path) -> None:
    paths = _files(tmp_path, "index.html", "final_check.py", "final_check_v2.py")

    note = cleanup_claim_left_files(CLAIM, paths)

    assert "final_check.py" in note and "final_check_v2.py" in note
    assert "index.html" not in note, "산출물은 임시 파일이 아니다"


def test_quiet_when_they_really_are_gone(tmp_path: Path) -> None:
    paths = _files(tmp_path, "index.html", "final_check.py")
    paths[1].unlink()

    assert cleanup_claim_left_files(CLAIM, paths) == ""


def test_quiet_without_the_claim(tmp_path: Path) -> None:
    paths = _files(tmp_path, "test_memo.py")

    assert cleanup_claim_left_files("테스트 스크립트 test_memo.py 로 검증했습니다.", paths) == ""


def test_it_is_on_the_final_answer() -> None:
    assert "cleanup_claim_left_files(answer, self._written_paths(steps))" in inspect.getsource(BrowserAgent.run)
