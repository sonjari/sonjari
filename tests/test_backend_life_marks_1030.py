"""백엔드가 언제 떴고 어떻게 끝났는지 로그에 남는다 (2026-10-30 · 10-29 07:16 판 도중 말없이 꺼짐 — 시각 · 끝 줄이 없어 원인을 못 가림)."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
from pathlib import Path

ENTRY = Path(__file__).resolve().parents[1] / "scripts" / "task_entry.py"


def _load():
    spec = importlib.util.spec_from_file_location("task_entry_for_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_start_is_stamped_with_time_and_pid() -> None:
    import faulthandler

    stream = io.StringIO()
    stream.fileno = lambda: sys.__stderr__.fileno()  # faulthandler 는 진짜 파일 번호가 있어야 켜진다 — 시험에선 표준 오류로
    _load()._mark_life(stream)
    faulthandler.disable()
    line = stream.getvalue()
    assert line.startswith("[life] 20") and "pid=" in line and "시작" in line


def test_a_normal_exit_leaves_its_line_and_a_kill_does_not(tmp_path: Path) -> None:
    """정상으로 끝나면 「정상 종료」가 남고, 밖에서 죽이면(os._exit 흉내) 안 남는다 — 그 차이로 가른다."""
    code = (
        "import importlib.util,sys,os;"
        f"spec=importlib.util.spec_from_file_location('t', r'{ENTRY}');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
        f"f=open(r'{tmp_path / 'log.txt'}','a',encoding='utf-8');m._mark_life(f);"
        "os._exit(1) if len(sys.argv)>1 else None"
    )
    subprocess.run([sys.executable, "-c", code], check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    normal = (tmp_path / "log.txt").read_text(encoding="utf-8")
    assert "시작" in normal and "정상 종료" in normal
    (tmp_path / "log.txt").unlink()
    subprocess.run([sys.executable, "-c", code, "kill"], check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    killed = (tmp_path / "log.txt").read_text(encoding="utf-8")
    assert "시작" in killed and "정상 종료" not in killed
