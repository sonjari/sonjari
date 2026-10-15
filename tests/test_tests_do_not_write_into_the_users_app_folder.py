"""검사는 사용자의 진짜 앱 폴더(`%LOCALAPPDATA%\\Sonjari`)에 쓰지 않는다 (2026-10-10).

10-09 03:52 부터 손자리가 저장소의 사본에서 돌린 검사가 기본 뿌리에 백업 · 색인 · DB 를 쌓았다. 10-10 에 스토어 판을
굽다가 관문이 그 폴더 때문에 막혔다(포장한 앱이 제 전용 자리 대신 그것을 썼다). `conftest.py` 가 검사 동안 그 자리를
임시 폴더로 돌린다 — 이 파일은 그 돌림이 실제로 서 있는지를 본다.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from alture_jarvis.config import JarvisConfig, _default_runtime_root

_TEMP = Path(tempfile.gettempdir()).resolve()


def _inside_temp(path: Path) -> bool:
    resolved = Path(path).resolve()
    return resolved == _TEMP or _TEMP in resolved.parents


def test_the_default_root_is_a_temp_folder_while_tests_run() -> None:
    assert _inside_temp(_default_runtime_root()), f"기본 뿌리가 임시 폴더 밖이다: {_default_runtime_root()}"


def test_a_config_built_with_no_arguments_points_at_the_temp_folder() -> None:
    config = JarvisConfig()
    for name in ("runtime_root", "data_dir", "output_dir"):
        assert _inside_temp(getattr(config, name)), f"{name} 이 임시 폴더 밖이다: {getattr(config, name)}"
    assert _inside_temp(config.database_path)


def test_the_environment_the_tests_hand_to_child_commands_points_there_too() -> None:
    """검사가 띄운 자식 프로세스(`python -c …`)도 같은 값을 물려받는다 — 거기서 만든 기본 설정도 임시 폴더로 간다."""
    assert _inside_temp(Path(os.environ["LOCALAPPDATA"]))


def test_playwright_still_finds_the_browsers_it_downloaded() -> None:
    """돌린 것은 우리 기본 뿌리뿐이다. Playwright 가 받아 둔 브라우저 자리는 진짜 자리를 가리킨다."""
    where = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    assert where and not _inside_temp(Path(where)), where
