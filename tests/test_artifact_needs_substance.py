"""**빈 문서를 굽지 않는다.**

## 실제로 일어난 일 (2026-09-10)

사슬 벤치의 한 판이 37KB 워드를 내고 이렇게 답했다:

> 상세 내용은 첨부된 문서(`위시켓_AI_에이전트_프로젝트_경쟁분석.docx`)에
> 구조화하여 담았습니다.

열어 보니 경쟁 분석이 아니라 **자비스 내부 배관 기록**이었다:

    | step | tool           | ok    | kind | title          | payload |
    | 2    | ui_find_target | False | note | ui_find_target | {}      |
    | 5    | ui_find_target | True  | note | ui_find_target | {…}     |
    | 6    | browser_fill   | True  | page | 프로젝트 찾기  | {…}     |

모델이 `step_ids: [2, 5, 6]` 을 줬고 그 셋은 「검색창 찾기」·「검색어 넣기」였다.
**도구는 시킨 대로 구웠고 아무도 그게 말이 되는지 안 봤다.**

옛 채점기로는 완벽한 통과였다 — 파일 있고, 형식 맞고, 숫자를 안 지어냈다.
내용 채점기(`bench/browser_agents/content_grade.py`)를 붙이고서야 0% 로 드러났다.

## 막지 않고 알려준다

이 저장소는 막기로만 고쳤다가 사람이 검토한 레시피까지 걸린 적이 있다(사고 R).
그래서 **내용이 있는 걸음 번호를 같이 돌려준다** — 모델이 번호를 바꿔 다시 부를 수
있어야 한다.
"""
from __future__ import annotations

from typing import Any


def _plumbing(step: int, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    """실제로 그 판에 들어 있던 모양 그대로."""
    import json

    return {
        "step": step, "tool": tool, "ok": True, "kind": "note", "title": tool,
        "payload": payload, "raw_result_json": json.dumps(payload, ensure_ascii=False),
    }


def test_plumbing_steps_alone_do_not_make_a_document() -> None:
    from alture_jarvis.sandbox import _artifact_step_has_substance

    assert not _artifact_step_has_substance(
        _plumbing(2, "ui_find_target", {}))
    assert not _artifact_step_has_substance(
        _plumbing(5, "ui_find_target",
                  {"goal": "검색창", "screenshot": "C:/out/a.png"}))
    assert not _artifact_step_has_substance(
        _plumbing(6, "browser_fill",
                  {"action": "filled", "url": "https://www.wishket.com/project/"}))


def test_a_read_page_is_substance() -> None:
    """본문을 받아 온 걸음은 통과해야 한다 — 이게 막히면 진짜 판이 죽는다."""
    from alture_jarvis.sandbox import _artifact_step_has_substance

    assert _artifact_step_has_substance(
        _plumbing(7, "browser_extract", {"text": "AI 에이전트 개발 프로젝트 " * 30}))


def test_a_table_of_rows_is_substance() -> None:
    """딕셔너리 목록은 상자가 표의 행으로 편다 — 글자가 짧아도 내용이다."""
    from alture_jarvis.sandbox import _artifact_step_has_substance

    assert _artifact_step_has_substance(
        _plumbing(3, "career_strategy_lookup",
                  {"rows": [{"회사": "가", "연봉": 4000},
                            {"회사": "나", "연봉": 5200}]}))


def test_the_refusal_names_the_steps_that_do_have_content() -> None:
    """막기만 하면 모델은 같은 번호로 다시 부른다. **갈 곳을 알려줘야 한다.**"""
    import pytest
    from alture_jarvis.sandbox import SandboxBox

    store = _FakeStore({
        2: _plumbing(2, "ui_find_target", {}),
        6: _plumbing(6, "browser_fill", {"action": "filled"}),
        7: _plumbing(7, "browser_extract", {"text": "프로젝트 본문 " * 40}),
    })
    box = object.__new__(SandboxBox)
    box.observations = store
    box.local_computer = _FakeLocal()

    with pytest.raises(ValueError) as caught:
        box.artifact_from_observations({
            "__job_id": "job-1", "format": "docx", "path": "경쟁분석.docx",
            "step_ids": [2, 6],
        })
    message = str(caught.value)
    assert "내용이 있는 걸음은 7" in message, message
    assert "빈 문서" in message, message


def test_a_job_with_nothing_read_yet_is_told_to_read_first() -> None:
    import pytest
    from alture_jarvis.sandbox import SandboxBox

    box = object.__new__(SandboxBox)
    box.observations = _FakeStore({2: _plumbing(2, "ui_find_target", {})})
    box.local_computer = _FakeLocal()

    with pytest.raises(ValueError) as caught:
        box.artifact_from_observations({
            "__job_id": "job-2", "format": "xlsx", "path": "a.xlsx",
            "step_ids": [2],
        })
    assert "먼저 읽어 와라" in str(caught.value)


class _FakeStore:
    def __init__(self, rows: dict[int, dict[str, Any]]) -> None:
        self._rows = rows

    def get_for_artifact(self, job_id: str, step: int) -> dict[str, Any] | None:
        return self._rows.get(step)

    def get(self, job_id: str, step: int) -> dict[str, Any] | None:
        return self._rows.get(step)

    def list_steps(self, job_id: str) -> list[dict[str, Any]]:
        return [{"step": step} for step in sorted(self._rows)]


class _FakeLocal:
    def job_workspace(self, job_id: str, create: bool = False):
        import pathlib
        import tempfile

        return pathlib.Path(tempfile.mkdtemp())
