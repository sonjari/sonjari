"""백엔드 충돌 4번(11-01~11-03)의 뿌리 — 덤프 장치가 모든 스레드를 읽다가 죽였다.

윈도우 faulthandler 는 처리되는 COM 예외(0x80010108)에도 덤프를 쓴다. all_threads=True 면 도는 중인 남의 스레드 스택을 읽다
access violation 으로 백엔드를 통째로 죽인다(로그: 4번 모두 남의 스레드 `File "…` 줄 한가운데서 끊김). 다시 켜지 않게 막는다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_entry_point_dumps_every_thread() -> None:
    hits = []
    for p in [*ROOT.joinpath("scripts").rglob("*.py"), *ROOT.joinpath("src").rglob("*.py")]:
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"faulthandler\.(enable|dump_traceback_later|dump_traceback)\(([^)]*)\)", text):
            if "all_threads=False" not in m.group(2):
                hits.append(f"{p.relative_to(ROOT)}: {m.group(0)}")
    assert hits == [], "faulthandler 는 all_threads=False 로만 — 윈도우에선 무해한 COM 예외에도 덤프하다 죽는다:\n" + "\n".join(hits)


def test_the_backend_entry_still_turns_it_on() -> None:
    text = ROOT.joinpath("scripts", "task_entry.py").read_text(encoding="utf-8")
    assert "faulthandler.enable(file=stream, all_threads=False)" in text   # 끄는 게 아니라 좁힌다 — 진짜 충돌 자리는 남긴다
