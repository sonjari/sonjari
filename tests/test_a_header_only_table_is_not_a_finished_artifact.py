"""몇 개를 찾아 채우라고 한 판에서, 머리줄만 있는 표는 다 된 산출물이 아니다 (2026-10-06 국내 조사 첫 판).

8쪽을 읽고 머리줄만 든 엑셀을 써 둔 순간 「실제 산출물 파일 만들기」가 ✅ 가 됐다. 세 칸이 다 차 「그만 찾고 답해라」가
나갔고, 판은 글로만 쓰는 마무리로 접혀 「다시 읽겠습니다」로 끝났다 — 빈 표를 남긴 채. 「있고 열린다」만 보던 눈금이
빈 그릇을 다 된 일로 셌다.

거꾸로도 지킨다: 개수 요구가 없는 판(빈 양식을 만들어 달라는 요청)에서는 머리줄만이 곧 시킨 것이다.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from alture_jarvis import plan
from alture_jarvis.plan import Requirement

HEAD = ["제품명", "만든 곳", "가격", "근거 주소"]


def _xlsx(path: Path, rows: list[list[str]]) -> Path:
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


def _wrote(path: Path) -> list[dict]:
    return [{"tool": "local_write_document", "ok": True, "arguments": {"path": str(path)},
             "evidence": {"path": str(path)}, "output_paths": [str(path)]}]


def _artifact_line(requirements: list[Requirement], steps: list[dict]) -> tuple[bool, str]:
    for req, met, saw in plan.check(requirements, sources=[], steps=steps, answer=""):
        if req.kind == "artifact":
            return met, saw
    raise AssertionError("no artifact requirement")


ARTIFACT = Requirement("artifact", "실제 산출물 파일 만들기", [".xlsx"])
FIVE = Requirement("count", "5개 이상 직접 열어 읽기", 5)


def test_the_helper_sees_the_file_the_step_wrote(tmp_path: Path) -> None:
    """이 시험의 걸음 모양이 실제로 「만든 파일」로 읽히는지 먼저 본다 — 아니면 아래 시험이 엉뚱한 이유로 통과한다."""
    path = _xlsx(tmp_path / "a.xlsx", [HEAD, ["가나 에이전트", "가나소프트", "무료", "https://example.com"]])
    assert plan._open_artifacts(_wrote(path), (".xlsx",)) == [path]


def test_a_header_only_table_does_not_finish_a_find_and_fill_task(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "조사.xlsx", [HEAD])

    met, saw = _artifact_line([FIVE, ARTIFACT], _wrote(path))

    assert met is False
    assert "값 줄이 없음" in saw


def test_one_filled_row_is_an_artifact(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "조사.xlsx", [HEAD, ["가나 에이전트", "가나소프트", "무료", "https://example.com"]])

    met, _saw = _artifact_line([FIVE, ARTIFACT], _wrote(path))

    assert met is True


def test_an_empty_form_is_what_was_asked_when_nothing_was_to_be_counted(tmp_path: Path) -> None:
    """「이 열로 빈 양식을 만들어 줘」 — 개수 요구가 없으면 머리줄만 있는 표가 곧 산출물이다."""
    path = _xlsx(tmp_path / "양식.xlsx", [HEAD])

    met, _saw = _artifact_line([ARTIFACT], _wrote(path))

    assert met is True


def test_a_filled_file_beside_a_hollow_one_still_counts(tmp_path: Path) -> None:
    hollow = _xlsx(tmp_path / "a.xlsx", [HEAD])
    filled = _xlsx(tmp_path / "b.xlsx", [HEAD, ["x", "y", "z", "w"]])

    met, _saw = _artifact_line([FIVE, ARTIFACT], _wrote(hollow) + _wrote(filled))

    assert met is True
