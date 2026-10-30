"""증상 시험 두 묶음 (2026-10-27) — 원인은 이 시험이 정하지 않는다. 겉으로 보인 증상만 막는다.

#1 산출물 헛실패
   운영 판 d72ca482 · f52e0d50: 마지막 걸음 `local_write_document` 가 ok=True ·
   evidence.verified=True · output_path 에 실제 xlsx 를 남겼는데, 대조표는
   「❌ 실제 산출물 파일 만들기 — 열 수 있는 산출물 없음」으로 판을 partial 로 끝냈다.
   같은 도구 · 같은 근거 모양인 871ed607 은 「1개 존재·열기 확인」으로 통과했다.
   재료: tests/fixtures/artifact_false_negative_1027.json (두 판의 요청 · 답 · 걸음 그대로,
   사용자 폴더만 {OUT} 으로 바꿈).

#2 웹 조사를 「로컬 자료」로 읽음
   운영 판 871ed607: 「레딧 … 과 깃허브에서 … 사례 10개 이상을 엑셀 한 장으로」에서
   「로컬 자료 10개 이상 직접 열어 읽기」(source_scope=local)가 세워졌다.
   대조표가 「요청을 「로컬」로 읽었지만 웹에서 읽은 것을 셈」이라고 스스로 적을 만큼 틀린 읽기다.
   지킴: 정말 이 PC 의 파일을 읽으라는 요청은 그대로 local 이어야 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from alture_jarvis import plan

FIXTURE = Path(__file__).parent / "fixtures" / "artifact_false_negative_1027.json"


def _load_case(job: str, out_dir: Path) -> dict:
    """재료의 {OUT} 을 시험 폴더로 바꾸고, 걸음이 남긴 산출물 파일을 실제로 만든다."""
    raw = FIXTURE.read_text(encoding="utf-8")
    raw = raw.replace("{OUT}", str(out_dir).replace("\\", "\\\\"))
    case = json.loads(raw)[job]
    openpyxl = pytest.importorskip("openpyxl")
    for step in case["steps"]:
        if step.get("tool") != "local_write_document" or not step.get("ok"):
            continue
        path = Path(str((step.get("evidence") or {}).get("output_path") or ""))
        assert path.parent == out_dir, path
        book = openpyxl.Workbook()
        sheet = book.active
        for name, rows in (step.get("arguments") or {}).get("sheets", {}).items():
            sheet.title = str(name)[:31]
            for row in rows:
                sheet.append([str(cell) for cell in row])
            break
        book.save(path)
    return case


def _artifact_rows(case: dict) -> list[tuple[bool, str]]:
    requirements = plan.extract(case["prompt"], own_from=case["prompt"], has_named_source=True)
    checked = plan.check(requirements, sources=[], steps=case["steps"], answer=case["answer"])
    return [(ok, saw) for requirement, ok, saw in checked if requirement.kind == "artifact"]


# ── #1 산출물 헛실패 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("job", ["d72ca482", "f52e0d50"])
def test_written_and_verified_xlsx_counts_as_artifact(job, tmp_path):
    case = _load_case(job, tmp_path)
    written = [s for s in case["steps"] if s.get("tool") == "local_write_document" and s.get("ok")]
    assert written, "재료에 성공한 쓰기 걸음이 있어야 한다"
    assert all(Path(s["evidence"]["output_path"]).is_file() for s in written)

    rows = _artifact_rows(case)
    assert rows, "산출물 요구가 세워져야 한다(엑셀 한 장을 시켰다)"
    for ok, saw in rows:
        assert ok, f"파일이 있고 열리는데 산출물 없음으로 판정: {saw!r}"
        assert "열 수 있는 산출물 없음" not in saw


def test_missing_file_still_fails(tmp_path):
    """지킴: 걸음은 ok 라고 했어도 파일이 정말 없으면 여전히 ❌ 여야 한다."""
    case = _load_case("d72ca482", tmp_path)
    for step in case["steps"]:
        if step.get("tool") == "local_write_document" and step.get("ok"):
            Path(step["evidence"]["output_path"]).unlink()
    rows = _artifact_rows(case)
    assert rows and not any(ok for ok, _ in rows)


# ── #2 웹 조사를 「로컬 자료」로 읽음 ─────────────────────────────────────────────

WEB_RESEARCH_ASKS = [
    # 871ed607 원문(돌려받을 항목 줄 포함)
    "레딧(r/3dsmax, r/gamedev, r/Unity3D, r/blender, r/animation, r/ClaudeAI, r/ClaudeCode)과 깃허브에서, "
    "게임 애니메이터·테크니컬 아티스트가 Claude 같은 AI를 실제 업무에 어떻게 쓰는지 사례를 찾아 주세요. "
    "대상 업무는 3ds Max 스크립트(MAXScript·pymxs) 짜기, 리깅·스킨 웨이트·애니메이션 클립 정리, 에셋 이름·폴더 점검, "
    "유니티 임포트 점검처럼 애니메이션 작업 주변의 반복 일입니다. 사례 10개 이상을 엑셀 한 장으로 정리해 주세요. "
    "칸은 제목, 주소, 누가(직군은 글에 적힌 그대로), 무엇에 썼나, 효과나 한계(글에 나온 그대로), "
    "토큰·한도 이야기(글에 있으면 그 문장 한 줄)입니다. 글에서 찾지 못한 칸은 비워 두고 지어내지 마세요. "
    "글을 쓴 사람의 닉네임은 적지 않습니다. 읽기만 하고 댓글·글 쓰기는 하지 않습니다.\n\n"
    "(돌려받을 항목 — 표 머리 · 소제목 · 「이름: 값」 어디에 쓰든 이 이름을 그대로 붙여 주세요: "
    "제목 · 주소 · 누가 · 무엇에 썼나 · 효과나 한계 · 토큰·한도 이야기)",
    # 같은 모양의 짧은 판
    "레딧과 깃허브에서 유니티 에디터 확장 사례 10개 이상을 찾아 엑셀 한 장으로 정리해 주세요.",
]


@pytest.mark.parametrize("ask", WEB_RESEARCH_ASKS, ids=["871ed607", "short"])
def test_web_research_count_is_not_local(ask):
    requirements = plan.extract(ask, own_from=ask, has_named_source=True)
    local = [(r.kind, r.label) for r in requirements if r.source_scope == "local"]
    assert not local, f"웹 조사 요청에 로컬 요구가 섰다: {local}"
    kinds = {r.kind for r in requirements}
    assert "artifact" in kinds and "site" in kinds, "사이트 · 산출물 요구는 그대로 남아야 한다"


LOCAL_ASKS = [
    # 경로만 대고 「파일 · 읽어」 말이 없는 판 — 「폴더」 앞 경로 갈래만 잡는다(10-27 백슬래시 하나 빠진 것을 이 줄이 못 잡았다).
    "깃허브 사례 3개와 D:\\자료 폴더의 문서 5개를 비교해 줘.",
    "D:\\자료 폴더에 있는 계약서 파일 5개를 읽고 비교해서 워드로 정리해 줘.",
    "바탕화면의 엑셀 파일 3개를 열어 합쳐 주세요.",
    "내 문서 폴더의 PDF 10개 이상을 직접 열어 읽고 엑셀 한 장으로 정리해 주세요.",
]


@pytest.mark.parametrize("ask", LOCAL_ASKS, ids=["web_and_drive_path", "d_drive", "desktop", "my_documents"])
def test_real_local_reading_stays_local(ask):
    """지킴: 이 PC 의 파일을 읽으라는 요청은 local 개수 요구가 그대로 서야 한다."""
    requirements = plan.extract(ask, own_from=ask, has_named_source=True)
    assert any(r.kind == "count" and r.source_scope == "local" for r in requirements), (
        [(r.kind, r.label, r.source_scope) for r in requirements]
    )


# ── #1 지킴: 만들 파일 이름을 직접 댄 요청은 그 형식을 지킨다 ─────────────────────
# (2026-10-27 첫 고침이 「요청 어디든 형식 낱말이 있으면 이름의 확장자를 버린다」여서 아래 둘이 깨졌다.)

NAMED_OUTPUT_ASKS = [
    ("합계.xlsx 로 저장해 줘", ".xlsx"),
    ("보고서.docx 로 만들어 줘. 숫자는 엑셀 표에서 가져와", ".docx"),
    ("엑셀 자료 세 개를 읽고 결과를 요약.md 로 저장해 줘", ".md"),
    ("CLAUDE.md 를 읽고 워드로 정리해 줘", ".docx"),
]


@pytest.mark.parametrize("ask,extension", NAMED_OUTPUT_ASKS, ids=["xlsx_named", "docx_named_excel_source", "md_named_excel_source", "md_source_word_output"])
def test_named_output_file_keeps_its_format(ask, extension):
    assert extension in plan.artifact_extensions(ask), plan.artifact_extensions(ask)
