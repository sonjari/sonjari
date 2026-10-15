"""각주는 **흉내 낼 수 있다.** 세지 않으면 흉내 낸다.

★ 2026-09-01 라이브. 「한글 파일 하나에 본문을 전부 옮기고, 고칠 만한 곳마다
각주로 수정 제안을 달아줘」에 자비스는

    * 42억 원 규모 지출 서류 검토 [수정 제안: '증빙 적정성 검토'로 변경할 것을 권장합니다.]

를 **본문에** 써 넣었다. 각주가 아니다. 게다가 워드(docx)로 만들었고, 계획 층은
`plan: {}` 이라 아무 대조도 안 했다. 원인 셋이 겹쳐 있었다:

    ① 도구에 각주 블록이 없었다        → 도구가 없으면 흉내 낸다
    ② 「옮기고」·「달아줘」가 낱말표에 없어 산출물 요구가 안 뽑혔다
    ③ `local_write_document` 가 `_ARTIFACT_TOOLS` 에 없어, 만들어도 안 보였다
"""

from __future__ import annotations

import json
import tempfile
import warnings
import zipfile
from pathlib import Path

import pytest

from alture_jarvis import plan
from alture_jarvis.document_reader import preview_of_file
from alture_jarvis.documents import edit_document, write_document

warnings.filterwarnings("ignore")

ASK = "구글 드라이브에서 이력서 읽어서 한글 파일에 본문 옮기고 각주로 수정 제안 달아줘"


def _steps(path: Path) -> list[dict]:
    return [{
        "tool": "local_write_document",
        "ok": True,
        "evidence": {"action": "local_write_document", "output_path": str(path)},
    }]


def _verdict(path: Path) -> dict[str, bool]:
    wanted = plan.extract(ASK, has_named_source=True)
    return {r.kind: ok for r, ok, _ in plan.check(wanted, sources=[], steps=_steps(path), answer="")}


def test_the_ask_is_recognised_at_all(tmp_path: Path) -> None:
    """`plan: {}` 이면 무엇을 해도 대조가 안 된다 — 라이브에서 그랬다."""
    kinds = {r.kind for r in plan.extract(ASK, has_named_source=True)}

    assert "artifact" in kinds, "「옮기고」·「달아줘」가 산출물 요구로 안 잡힌다"
    assert "footnote" in kinds
    # 자비스가 만드는 한글 문서는 hwpx 다. `.hwp` 만 요구하면 제대로 만든 것이 미달로 찍힌다.
    assert ".hwpx" in plan._artifact_extensions(ASK)


def test_writing_the_suggestion_into_the_body_does_not_pass(tmp_path: Path) -> None:
    """이게 라이브에서 통과했던 모양이다."""
    fake = tmp_path / "흉내.hwpx"
    write_document(fake, "hwpx", {"blocks": [
        {"type": "paragraph", "text": "42억 검토 [수정 제안: 증빙 적정성 검토로 변경]"},
    ]})

    assert _verdict(fake)["footnote"] is False


def test_a_real_footnote_passes_and_is_counted(tmp_path: Path) -> None:
    real = tmp_path / "진짜.hwpx"
    shape = write_document(real, "hwpx", {"blocks": [
        {"type": "paragraph", "text": "42억 검토", "footnote": "증빙 적정성 검토로"},
        {"type": "paragraph", "text": "자금 관리", "footnote": "집행 모니터링으로"},
    ]})

    assert shape["footnotes"] == 2
    assert _verdict(real)["footnote"] is True
    assert plan._footnotes_in(real) == 2


def test_an_empty_document_counts_zero_not_one(tmp_path: Path) -> None:
    """★ 빈 문서에도 각주 **설정**(`<hp:footNotePr>`)이 있다.

    경계 없이 `"<hp:footNote"` 를 세면 바닥값이 1 이 되어, 각주를 하나도 안 단
    문서가 「각주 1개」로 통과한다 — 실측에서 실제로 그랬다.
    """
    bare = tmp_path / "빈.hwpx"
    write_document(bare, "hwpx", {"blocks": [{"type": "paragraph", "text": "본문뿐"}]})

    assert plan._footnotes_in(bare) == 0


def test_making_a_word_file_when_hangul_was_asked_is_not_enough(tmp_path: Path) -> None:
    """라이브에서 「한글 파일」이라 했는데 docx 가 나왔고, 아무도 안 잡았다."""
    wrong = tmp_path / "워드.docx"
    write_document(wrong, "docx", {"blocks": [{"type": "paragraph", "text": "42억 검토"}]})

    verdict = _verdict(wrong)
    assert verdict["artifact"] is False
    assert verdict["footnote"] is False


def test_word_refuses_footnotes_instead_of_faking_them(tmp_path: Path) -> None:
    """못 하는 것은 못 한다고 말한다. 조용히 본문에 끼워 넣지 않는다."""
    with pytest.raises(ValueError, match="docx_footnotes_unsupported"):
        write_document(tmp_path / "x.docx", "docx", {"blocks": [
            {"type": "paragraph", "text": "본문", "footnote": "제안"},
        ]})


def test_footnotes_can_be_added_to_a_document_that_already_exists(tmp_path: Path) -> None:
    """「본문 옮기고 각주 달기」의 옳은 모양 — 만든 뒤 제자리에서 단다."""
    target = tmp_path / "이력서.hwpx"
    write_document(target, "hwpx", {"blocks": [
        {"type": "paragraph", "text": "42억 원 규모 지출 서류 검토"},
        {"type": "paragraph", "text": "사업비 자금 현황 관리"},
    ]})

    result = edit_document(target, [
        {"paragraph": 0, "footnote": "증빙 적정성 검토 및 정산 프로세스 수행으로"},
        {"paragraph": 1, "footnote": "예산 집행 모니터링 및 자금 운용 계획 수립으로"},
    ])

    assert result["footnotes"] == 2
    # ★ 본문이 살아 있어야 한다. `paragraph` 갈래가 먼저 걸리면 본문이 지워진다 —
    #   순서를 뒤로 뒀다가 실제로 그랬다.
    with zipfile.ZipFile(target) as bundle:
        xml = "".join(
            bundle.read(name).decode("utf-8", "ignore")
            for name in bundle.namelist()
            if name.startswith("Contents/section")
        )
    assert "42억 원 규모 지출 서류 검토" in xml
    assert "예산 집행 모니터링" in xml


def test_the_ledger_carries_the_path_of_what_it_made() -> None:
    """★ **열두 번째 등록 자리** (2026-09-01 저녁).

    `path` 는 `_EVIDENCE_TOO_BIG` 이라 일반 규칙으로는 장부에서 빠진다. 생산
    도구만 예외로 살리는데, 문서 도구 셋이 그 목록에 없었다. 라이브에서:

        step 4  local_write_document  format=hwpx  footnotes=1  verified=true
        대조    ❌ 산출물 없음 · ❌ 각주 없음

    파일도 각주도 **실제로 있었다.** 경로가 장부에 없어 못 찾은 것뿐이다.
    한 자리가 비어서 산출물 대조·각주 대조·「만든 것」 서랍 셋이 같이 틀렸다.
    """
    from alture_jarvis.agent import _step_evidence

    made = str(Path.home() / "Documents" / "JARVIS" / "x.hwpx")
    for action in ("local_write_document", "local_edit_document", "local_edit_spreadsheet"):
        out = _step_evidence({"action": action, "path": made})
        assert out.get("output_path") == made, f"{action} 이 만든 경로가 장부에서 사라진다"


def test_one_footnote_is_not_everywhere() -> None:
    """「곳마다」인데 하나 달고 「완벽히 반영했다」고 답했다 (2026-09-01 라이브)."""
    everywhere = plan.extract(
        "이력서 한글 파일로 옮기고 고칠 만한 곳마다 각주로 수정 제안 달아줘",
        has_named_source=True,
    )
    once = plan.extract("이력서 한글 파일로 옮기고 각주 하나 달아줘", has_named_source=True)

    assert next(r.target for r in everywhere if r.kind == "footnote") == 3
    assert next(r.target for r in once if r.kind == "footnote") == 1


def test_a_shortfall_in_footnotes_says_how_many(tmp_path: Path) -> None:
    target = tmp_path / "하나만.hwpx"
    write_document(target, "hwpx", {"blocks": [
        {"type": "paragraph", "text": "42억 검토", "footnote": "증빙 적정성 검토로"},
        {"type": "paragraph", "text": "자금 관리"},
    ]})
    wanted = plan.extract(
        "이력서 한글 파일로 옮기고 고칠 만한 곳마다 각주로 수정 제안 달아줘",
        has_named_source=True,
    )

    results = plan.check(wanted, sources=[], steps=_steps(target), answer="")
    saw = {r.kind: (ok, note) for r, ok, note in results}

    assert saw["footnote"][0] is False
    assert "1개" in saw["footnote"][1] and "3개 이상" in saw["footnote"][1]


def test_a_document_tool_is_seen_by_the_plan_layer() -> None:
    """★ 여기 없어서 만든 문서가 계획 층에 **안 보였다.**"""
    for tool in ("local_write_document", "local_edit_document", "local_edit_spreadsheet"):
        assert tool in plan._ARTIFACT_TOOLS, f"{tool} 산출물이 계획 대조에서 사라진다"


def test_one_paragraph_can_carry_a_footnote_per_company(tmp_path: Path) -> None:
    """★ 2026-09-02 라이브. 담을 칸이 없어 **셋을 하나로 이어 붙였다.**

    사고에는 이렇게 적혀 있었다:

        For "42억 원 규모 … 지출 서류 검토":
          [늘봄마루소프트 제안] … [새솔바이오 제안] … [한빛넥스 제안] …

    한 문단에 각주 셋을 달려던 것인데 `footnote` 가 문자열 하나만 받아서
    이어 붙였고, 각주 1개로 세어져 미달이 났다. **모델이 게으른 게 아니라
    칸이 없었다.**
    """
    target = tmp_path / "회사별.hwpx"

    shape = write_document(target, "hwpx", {"blocks": [
        {"type": "paragraph", "text": "42억 원 규모 지출 서류 검토", "footnote": [
            {"label": "늘봄마루소프트", "text": "IRIS·RCMS 운영 경험을 명시하세요"},
            {"label": "새솔바이오", "text": "연구행정·연구비 정산 역량을 강조하세요"},
            {"label": "한빛넥스", "text": "국책과제 관리·회계 실무를 전면에"},
        ]},
    ]})

    assert shape["footnotes"] == 3
    assert plan._footnotes_in(target) == 3
    text = preview_of_file(target, chars=600)
    assert "늘봄마루소프트" in text and "한빛넥스" in text


def test_a_plain_string_footnote_still_works(tmp_path: Path) -> None:
    """목록을 받게 했다고 문자열이 깨지면 안 된다."""
    target = tmp_path / "하나.hwpx"

    shape = write_document(target, "hwpx", {"blocks": [
        {"type": "paragraph", "text": "본문", "footnote": "제안 하나"},
    ]})

    assert shape["footnotes"] == 1


def test_footnotes_can_be_piled_on_afterwards(tmp_path: Path) -> None:
    """만든 뒤에 회사별로 더 다는 길도 있어야 한다."""
    target = tmp_path / "나중에.hwpx"
    write_document(target, "hwpx", {"blocks": [{"type": "paragraph", "text": "본문"}]})

    result = edit_document(target, [{"paragraph": 0, "footnote": ["A사 제안", "B사 제안"]}])

    assert result["footnotes"] == 2
    assert plan._footnotes_in(target) == 2


def test_the_contract_tells_the_model_about_the_list(tmp_path: Path) -> None:
    """칸이 있어도 **있다고 말 안 하면** 모델은 이어 붙인다."""
    from alture_jarvis.config import JarvisConfig
    from alture_jarvis.local_computer import LocalComputerTools

    config = JarvisConfig(
        runtime_root=tmp_path, data_dir=tmp_path / "d", output_dir=tmp_path / "o",
        documents_dir=tmp_path / "docs", local_computer_enabled=True,
    )
    schema = {
        item["function"]["name"]: json.dumps(item["function"], ensure_ascii=False)
        for item in LocalComputerTools(config).ollama_tools
    }

    assert "여러 개" in schema["local_write_document"]
    assert "label" in schema["local_write_document"]
