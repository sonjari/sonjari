"""「만든 파일에는 값이 있는데 답에는 없다」 경고는 답이 **그 파일을 이름으로 말하면** 울리지 않는다.

★ 2026-09-28 회의록 양식 판(1864f97f): 빈 양식을 제대로 만들고 파일 경로까지 적은 답에, 파일의 「14:00~15:00」 한 줄이 값 셋으로
세어져 「이미 한 일을 안 했다고 적었을 수 있습니다」가 붙었다. 과거 울린 13번 중 11번이 파일 이름을 댄 정상 답이었다.
"""

from __future__ import annotations

from pathlib import Path

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.documents import write_document


def _made(tmp_path: Path, name: str) -> list[dict]:
    path = tmp_path / name
    write_document(path, "docx", {"blocks": [
        {"type": "table", "rows": [["프로젝트", "기간", "지원자"], ["검수 에이전트", "270일", "4명"], ["챗봇", "90일", "11명"]]},
    ]})
    return [{"tool": "local_write_document", "ok": True, "evidence": {"output_path": str(path)}}]


def test_an_answer_that_names_the_file_gets_no_warning(tmp_path: Path) -> None:
    steps = _made(tmp_path, "위시켓_조사.docx")

    answer = "위시켓 프로젝트를 조사해 `위시켓_조사.docx` 에 정리했습니다. 기간과 지원자 수는 문서의 표에 있습니다."

    assert BrowserAgent._artifact_answer_divergence(answer, steps) == ""


def test_an_answer_that_says_it_failed_still_gets_the_warning(tmp_path: Path) -> None:
    """이 검사가 원래 잡으려던 것(2026-09-07 위시켓): 파일에는 값이 있는데 답은 못 했다고 한다."""
    steps = _made(tmp_path, "위시켓_조사.docx")

    answer = "검색 결과 목록이 나타나지 않았습니다. 결과를 확인하지 못했습니다."

    assert "값이 하나도 없습니다" in BrowserAgent._artifact_answer_divergence(answer, steps)
