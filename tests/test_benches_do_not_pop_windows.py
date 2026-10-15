"""벤치는 **창을 띄우지 않는다** — 파일이 만들어졌는지는 코드가 본다.

## 왜 (2026-09-13 사용자님)

벤치 한 번에 워드·엑셀 창이 열다섯 개씩 떴다. 사람이 쓰는 PC 에서 그러면 일을
못 한다. 벤치가 알아야 하는 것은 「만들었나 · 안이 맞나」이고, 그건 결과의 경로와
채움 채점기가 이미 확인한다. 창은 아무것도 증명하지 않는다.

사람이 시킨 일은 지금처럼 띄운다(`open_results` 기본 참). 벤치가 끄고 들어온다.

## 왜 시험으로 묶나

`/v1/chat` 을 부르는 벤치가 **열 곳**이다. 한 곳씩 넣으면 새 벤치를 만들 때 반드시
하나를 잊는다 — 이 저장소가 「같은 일을 여러 곳에서 하면 한 곳은 잊는다」로 여러 번
데였다. 그래서 빠뜨리면 여기가 깨진다.
"""

from __future__ import annotations

import re
from pathlib import Path

from alture_jarvis.api import ChatRequest
from alture_jarvis.local_computer import LocalComputerTools

ROOT = Path(__file__).resolve().parents[1]
BENCH_FILES = sorted(
    list((ROOT / "scripts").glob("bench_*.py"))
    + list((ROOT / "bench" / "browser_agents").glob("*.py"))
)


def _chat_calls(text: str) -> list[str]:
    """`"/v1/chat"` 뒤로 요청 몸통이 닫힐 때까지를 잘라 온다."""
    calls = []
    for match in re.finditer(r'"/v1/chat"', text):
        calls.append(text[match.start(): match.start() + 600])
    return calls


def test_every_bench_that_posts_a_chat_turns_windows_off() -> None:
    missing = []
    for path in BENCH_FILES:
        text = path.read_text(encoding="utf-8", errors="replace")
        for call in _chat_calls(text):
            if '"open_results": False' not in call:
                missing.append(path.name)
    assert not missing, (
        "창을 끄지 않고 /v1/chat 을 부르는 벤치: "
        + ", ".join(sorted(set(missing)))
        + ' — 요청에 "open_results": False 를 넣어라.'
    )


def test_people_still_get_their_file_opened_by_default() -> None:
    """사람이 시킨 일은 지금처럼 띄운다."""
    assert ChatRequest(prompt="보고서 만들어줘").open_results is True


def test_discarding_forgets_without_opening(tmp_path: Path, monkeypatch) -> None:
    """끄고 들어온 판은 적어 둔 것을 비운다 — 안 비우면 다음 판이 남의 파일을 띄운다."""
    opened: list[str] = []
    monkeypatch.setattr("os.startfile", lambda path: opened.append(path), raising=False)
    computer = LocalComputerTools.__new__(LocalComputerTools)
    computer._pending_opens = {}
    computer.remember_to_open("job-1", tmp_path / "a.docx")

    computer.discard_pending("job-1")

    assert opened == []
    assert computer.open_pending("job-1") == ""
