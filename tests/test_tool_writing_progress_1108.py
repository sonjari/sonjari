"""도구 호출 글 쓰는 동안 진행 줄이 「파일을 쓰는 중 · N자」로 (2026-11-08 대표 「파일 쓰는 것도 보이게」)."""
from __future__ import annotations

from alture_jarvis.agent import BrowserAgent


class _Fake:
    _TOOL_WRITING_PROGRESS_SEC = BrowserAgent._TOOL_WRITING_PROGRESS_SEC
    _TOOL_WRITING_LABEL = BrowserAgent._TOOL_WRITING_LABEL
    _tool_writing_progress = BrowserAgent._tool_writing_progress

    def __init__(self) -> None:
        self.said: list[tuple[str, str]] = []

    def _progress(self, job_id: str, stage: str, text: str) -> None:
        self.said.append((stage, text))


def test_progress_line_names_the_file_and_counts_chars() -> None:
    fake = _Fake()
    fake._tool_writing_progress("j1", {"name": "local_write_document", "chars": 3210})
    assert fake.said == [("tool", "파일을(를) 쓰는 중 · 3,210자")]
    fake._tool_writing_progress("j1", {"name": "local_write_document", "chars": 3300})
    assert len(fake.said) == 1, "2초 안에 또 오면 줄을 다시 그리지 않는다(깜박임)"
    fake._tool_writing_progress("j2", {"name": "browser_open", "chars": 40})
    assert fake.said[-1] == ("tool", "도구에 넘길 내용을(를) 쓰는 중 · 40자")


def test_zero_chars_is_not_shown() -> None:
    fake = _Fake()
    fake._tool_writing_progress("j3", {"name": "", "chars": 0})
    assert fake.said == []
    fake._tool_writing_progress("j3", {"name": "local_write_document", "chars": 12})
    assert fake.said == [("tool", "파일을(를) 쓰는 중 · 12자")], "0자를 건너뛴 뒤 첫 글자는 바로 보인다"
