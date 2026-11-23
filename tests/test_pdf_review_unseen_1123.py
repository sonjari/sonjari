"""PDF 서류 검토에서 **보지 못한 것을 사실처럼 말한** 문제들 (2026-11-23 지원사업 수행계획서 판 f38ebeb4 · 14b52081).

실제 판(개인 정보가 든 신청서라 여기 싣지 않는다)과 같은 짜임의 PDF 를 시험 안에서 만든다:
- Marlett 글자 g f e d c (b) 를 한자리에 겹쳐 그린 체크 상자 — pypdf 는 「gfedcb」로 뽑았다(화면은 ☑).
- 「(Seal)」 글자 **뒤에** 그린 그림 — 직인 · 서명 도장. 글자 읽기에는 흔적이 없었다.

고친 자리: `pdf_marks`(읽기) · `doc_facts`(사업자번호 계산) · `picture_claims` + `BrowserAgent._unseen_claims_check`(답 검사) ·
`BrowserAgent._quote_vs_page_check`(원문 대조 — 따옴표 조각만) · `stuck_hands._sensitive_report`(비밀 자리 막힘).
"""
from __future__ import annotations

import io
from typing import Any

from pypdf import PdfReader

from alture_jarvis.agent import BrowserAgent
from alture_jarvis.doc_facts import business_number_ok, facts_block
from alture_jarvis.document_reader import DocumentReader
from alture_jarvis.number_checks import percent_warning
from alture_jarvis.pdf_marks import read_page
from alture_jarvis.picture_claims import absent_claims_on_pictures, picture_anchors, unsupported_hedges
from alture_jarvis.stuck_hands import _stuck_report


# --- 시험용 PDF 만들기 -------------------------------------------------------------

def _pdf(content: str, *, fonts: dict[str, str], image: bool = True) -> bytes:
    """글꼴(이름 → BaseFont)과 1x1 그림 하나를 가진 한 쪽 PDF. 글꼴은 심지 않는다(pypdf 가 글자 코드를 그대로 영문자로 뽑는다)."""
    objects: list[bytes] = []
    font_refs = []
    for index, (name, base) in enumerate(fonts.items()):
        font_refs.append(f"/{name} {5 + index} 0 R")
    resources = "<< /Font << " + " ".join(font_refs) + " >>" + (" /XObject << /Im1 4 0 R >>" if image else "") + " >>"
    stream = content.encode("latin-1")
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources {resources} /Contents {5 + len(fonts)} 0 R >>".encode()
    )
    objects.append(b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 /Length 1 >>\nstream\n\x00\nendstream")
    for base in fonts.values():
        objects.append(f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} >>".encode())
    objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def _text(x: int, y: int, font: str, text: str) -> str:
    return f"BT /{font} 12 Tf {x} {y} Td ({text}) Tj ET\n"


def _box(x: int, y: int, checked: bool) -> str:
    """Marlett 체크 상자 — 겹 글자를 **한자리에** 하나씩(한글 양식에서 나온 그대로)."""
    return "".join(_text(x, y, "F2", glyph) for glyph in ("gfedcb" if checked else "gfedc"))


FORM = (
    _text(50, 760, "F1", "Business No 123-45-67800 Type")
    + _box(260, 760, True) + _text(275, 760, "F1", "San")
    + _box(310, 760, False) + _text(325, 760, "F1", "Hak")
    + _text(50, 700, "F1", "Company: ExampleCo (Seal)   Head: Kim (Sign)")
    # 도장 그림 둘 — 글자를 그린 **뒤에** 그 글자 위로(실제 판 순서: 글자 877번 → 그림 892 · 896번).
    + "q 40 0 0 40 160 690 cm /Im1 Do Q\n"
    + "q 40 0 0 40 280 690 cm /Im1 Do Q\n"
)


def _page(content: str, **fonts: str) -> Any:
    return PdfReader(io.BytesIO(_pdf(content, fonts=fonts or {"F1": "Helvetica", "F2": "Marlett"}))).pages[0]


# --- 1. 기호 글꼴은 글자가 아니다 ---------------------------------------------------

def test_marlett_checkbox_glyphs_become_box_shapes_not_letters() -> None:
    before = _page(FORM).extract_text()
    assert "gfedcbSan" in before.replace(" ", ""), "시험 PDF 가 실제 판과 같은 병을 재현해야 한다(옛 읽기)"

    marks = read_page(_page(FORM))
    assert "☑" in marks.text and "□" in marks.text
    assert "gfedc" not in marks.text
    assert marks.symbols_replaced == 2 and marks.symbols_unplaced == 0


def test_same_letters_in_a_normal_font_stay_letters() -> None:
    """반례: 보통 글꼴의 「gfedcb」는 그대로 — 글자 모양이 아니라 **글꼴**로 가른다."""
    marks = read_page(_page(_text(50, 760, "F1", "code gfedcb and gfedc stay")))
    assert "gfedcb" in marks.text and "☑" not in marks.text and "□" not in marks.text


def test_a_normal_v_before_a_wingdings_bullet_is_not_replaced() -> None:
    """반례: 보통 글의 「v」(앞에 있음)는 두고, Wingdings 「v」 글머리만 ❖ 로."""
    content = _text(50, 760, "F1", "version v2 notes") + _text(50, 740, "F3", "v") + _text(65, 740, "F1", "Item one")
    marks = read_page(_page(content, F1="Helvetica", F3="Wingdings"))
    assert "version v2 notes" in marks.text
    assert "❖" in marks.text and marks.text.count("v") == marks.text.replace("❖", "").count("v")


def test_unknown_symbol_glyph_is_marked_not_guessed() -> None:
    """화면으로 확인 안 한 기호는 짐작해 바꾸지 않는다 — 「⟦기호⟧」."""
    content = _text(50, 760, "F3", "q") + _text(65, 760, "F1", "Item") + _text(50, 740, "F2", "x")
    marks = read_page(_page(content, F1="Helvetica", F2="Marlett", F3="Wingdings"))
    assert marks.text.count("⟦기호⟧") == 2


# --- 2. 그림은 「없음」이 아니라 「안 읽음」 ------------------------------------------

def test_pictures_stamped_over_text_are_named_by_that_text() -> None:
    marks = read_page(_page(FORM))
    assert len(marks.pictures) == 2
    assert marks.picture_note.startswith("⟦그림 2개")
    assert "「(Seal)" in marks.picture_note or "Seal" in marks.picture_note
    assert all(label.endswith("글자 위") for label in marks.pictures)


def test_a_background_picture_drawn_before_the_text_is_not_over_it() -> None:
    """반례: 글자보다 **먼저** 그린 그림은 바탕이다(글상자 배경 · 로고 판) — 「글자 위」가 아니다."""
    content = "q 200 0 0 40 40 690 cm /Im1 Do Q\n" + _text(50, 700, "F1", "Company: ExampleCo (Seal)")
    marks = read_page(_page(content))
    assert marks.pictures == ["글자 밑 바탕"]
    assert picture_anchors(marks.picture_note) == []


def test_reader_puts_the_picture_line_into_the_document_text() -> None:
    content = DocumentReader().read_bytes("form.pdf", _pdf(FORM, fonts={"F1": "Helvetica", "F2": "Marlett"}))
    assert "⟦그림 2개" in content.text
    assert any("그림" in warning for warning in content.warnings)
    assert any("기호 글꼴" in warning for warning in content.warnings)


def test_a_text_less_scan_still_goes_to_ocr() -> None:
    """반례: 글자가 한 쪽에도 없으면(그림만) 예전대로 OCR 로 간다 — 그림 표시 줄이 OCR 을 막으면 안 된다."""
    called: list[int] = []

    def ocr(raw: bytes, pages: int) -> tuple[str, int]:
        called.append(pages)
        return "스캔에서 읽은 글", pages

    scan = _pdf("q 595 0 0 842 0 0 cm /Im1 Do Q\n", fonts={"F1": "Helvetica"})
    content = DocumentReader(pdf_ocr=ocr).read_bytes("scan.pdf", scan)
    assert called == [1]
    assert "스캔에서 읽은 글" in content.text


# --- 3. 계산되는 상식은 계산한다 ------------------------------------------------------

def test_business_number_checksum() -> None:
    assert business_number_ok("1234567800")  # 3-2-5 가 정상이고 검증 숫자도 맞는 가짜 번호
    assert not business_number_ok("1234567801")


def test_business_number_note_needs_its_label() -> None:
    assert "검증 숫자 맞음" in facts_block("사업자등록번호\n(고유번호) 123-45-67800")
    assert "안 맞음" in facts_block("사업자등록번호 123-45-67801")
    assert facts_block("주문번호 123-45-67800") == ""  # 반례: 이름표가 없으면 사업자번호라 부르지 않는다
    assert facts_block("전화 010-0000-0000") == ""


def test_reader_attaches_the_business_number_fact() -> None:
    content = DocumentReader().read_bytes("form.txt", "사업자등록번호\n(고유번호) 123-45-67800\n".encode("utf-8"))
    assert "⟦손자리 계산 확인⟧" in content.text and "검증 숫자 맞음" in content.text
    english = DocumentReader().read_bytes("form.pdf", _pdf(FORM, fonts={"F1": "Helvetica", "F2": "Marlett"}))
    assert "⟦손자리 계산 확인⟧" not in english.text  # 한국어 이름표가 없으면 붙이지 않는다


# --- 4. 답 검사: 그림 자리를 「없다」 · 물음표 짐작 -------------------------------------

PICTURE_LINE = "⟦그림 2개 · 그림 속은 안 읽음⟧ 1) 「인」 · 「서명」 글자 위 · 2) 「직인」 글자 위"
GRANT_ROW = "| 1 | `총괄책임자: 홍길동 (인/서명)` | **서명/인감 미기재.** 제출 전 서명 또는 인감 날인 필요 |"


def test_absent_claim_on_a_stamped_place_is_caught() -> None:
    anchors = picture_anchors(PICTURE_LINE)
    assert anchors == ["서명", "직인"], "한 글자 이름표(「인」)는 모든 줄에 걸리므로 쓰지 않는다"
    assert absent_claims_on_pictures(GRANT_ROW, anchors) == ["서명"]


def test_honest_not_checked_line_is_not_caught() -> None:
    honest = "| 1 | `총괄책임자: 홍길동 (인/서명)` | 서명 칸에 그림이 있어 손자리가 확인할 수 없음 — 원본에서 확인 |"
    assert absent_claims_on_pictures(honest, picture_anchors(PICTURE_LINE)) == []


def test_absent_claim_elsewhere_is_not_caught() -> None:
    other = "| 2 | `1. 신청과제명` | **빈칸.** 과제명이 비어 있음 |"
    assert absent_claims_on_pictures(other, picture_anchors(PICTURE_LINE)) == []


def test_hedged_guess_not_in_material_is_caught() -> None:
    answer = "예시회사의 제품(로봇 메타버스 피팅?)과 GPU가 어떤 성과로 연결되는지"
    assert unsupported_hedges(answer, "기업명 예시회사(ExampleCo)") == ["로봇 메타버스 피팅?"]
    assert unsupported_hedges(answer, "제품: 로봇 메타버스 피팅") == []  # 반례: 읽은 글에 있으면 짐작이 아니다
    assert unsupported_hedges("이게 맞나(?) 모르겠다 (왜?)", "") == []  # 반례: 말버릇


def _agent_with(body: str) -> BrowserAgent:
    agent = object.__new__(BrowserAgent)
    agent._page_bodies = lambda _steps, _job: {"e:\\form.pdf": body}  # type: ignore[method-assign]
    return agent


def test_unseen_claims_check_writes_one_warning_each() -> None:
    body = "기업(관)명 : 예시회사 (직인) 총괄책임자: 홍길동 (인/서명)\n" + PICTURE_LINE
    answer = GRANT_ROW + "\n예시회사의 제품(로봇 메타버스 피팅?)"
    notes = _agent_with(body)._unseen_claims_check("PDF 검토", answer, [{"ok": True}], "job")
    assert "확인 못 함" in notes and "「서명」" in notes
    assert "물음표" in notes and "로봇 메타버스 피팅?" in notes


# --- 5. 원문 대조: 따옴표 조각만 · 경고에 걸린 인용을 보인다 ---------------------------

PDF_BODY = (
    "[PDF 1쪽]\n사업자등록번호\n(고유번호) 123-45-67800 유 형 ☑산 □학 □연\nE-mail x 국가연구자번호 -\n"
    "과제정보\n연구/개발분야\n(중복 가능)\n■ 언어모델 □ 음성/오디오\n\n[PDF 2쪽]\n3. 과제 개요\n* 본 사업수행을 통해\n4. 과제 주요 내용\n"
)
GRANT_TABLE = "\n".join([
    "| 쪽 번호 | 원문 문장 | 고칠 점 |",
    "|---|---|---|",
    "| 1 | `국가연구자번호 -` (총괄·실무 모두) | 빈칸 |",
    "| 2 | `3. 과제 개요` / `4. 과제 주요 내용` | 전부 빈칸 |",
    "| 1 | `연구/개발분야 ■ 언어모델` | 기타 칸 |",
])


def test_quote_check_reads_only_the_quoted_pieces_and_names_the_quote() -> None:
    notes = _agent_with(PDF_BODY)._quote_vs_page_check("PDF 검토", GRANT_TABLE, [{"ok": True}], "job")
    # 따옴표 밖에 설명을 붙인 두 줄은 원문이 맞다 — 걸리지 않는다.
    assert "국가연구자번호" not in notes and "과제 개요" not in notes
    # 가운데 「(중복 가능)」을 뺀 인용은 원문과 다르다 — 걸리고, 쪽 번호가 아니라 **그 인용**이 보인다.
    assert "「연구/개발분야 ■ 언어모델」" in notes
    assert "「1」 ·" not in notes and not notes.rstrip().endswith("「1」")


def test_quote_check_still_reads_a_whole_sentence_with_an_inner_quote() -> None:
    """반례: 칸이 따옴표로 **시작하지 않으면** 칸 전체가 원문이다 — 속의 짧은 따옴표만 보고 지어낸 문장을 놓치지 않는다."""
    table = "\n".join([
        "| 쪽 | 원문 문장 | 고칠 점 |", "|---|---|---|",
        "| 1 | 본 사업은 \"AI\" 산업 육성을 위해 매출을 늘린다 | 확인 |",
    ])
    notes = _agent_with(PDF_BODY)._quote_vs_page_check("PDF 검토", table, [{"ok": True}], "job")
    assert "원문과 다름" in notes


# --- 6. 비밀 자리 막힘은 되풀이하지 않는다 --------------------------------------------

UPLOAD = r"C:\Users\someone\.claude\uploads\abc\form.pdf"


def _blocked(tool: str, path: str) -> dict[str, Any]:
    return {"tool": tool, "ok": False, "arguments": {"path": path}, "error": "sensitive_path_blocked"}


def test_blocked_named_target_stops_at_the_first_step() -> None:
    report = _stuck_report([_blocked("local_read_document", UPLOAD)], f"이 PC 의 PDF 「{UPLOAD}」를 읽고 정리해 줘")
    assert report is not None and report["kind"] == "sensitive_wall" and report["named"]
    assert "승인으로도" in report["ask"] and "이어서" not in report["message"]


def test_listing_the_parent_of_the_named_file_also_counts() -> None:
    parent = UPLOAD.rsplit("\\", 1)[0]
    report = _stuck_report([_blocked("local_list_directory", parent)], f"「{UPLOAD}」 읽어 줘")
    assert report is not None and report["kind"] == "sensitive_wall"


def test_a_blocked_place_the_model_chose_is_left_to_the_old_rule() -> None:
    """반례(운영 기록 역검증): 사람이 적지 않은 자리 · 적은 폴더 **아래**의 다른 파일이 막혀도 판을 끊지 않는다.

    운영 판 75aaa296 은 `bench/…/token_showdown.py`(보통 코드 파일)가 이름 때문에 두 번 막혔지만 그 뒤에 일을 마쳤다."""
    prompt = r"E:\work 폴더에서 plan.pdf 를 읽고 정리해 줘"
    steps = [_blocked("local_read_text_file", r"E:\work\bench\token_showdown.py"), {"tool": "local_run_shell", "ok": True},
             _blocked("local_read_text_file", r"E:\work\bench\token_showdown.py")]
    assert _stuck_report(steps[:1], prompt) is None
    assert _stuck_report(steps, prompt) is None
    assert _stuck_report([_blocked("local_list_directory", r"C:\Users\someone\.ssh")], prompt) is None


def test_mac_paths_are_matched_too() -> None:
    path = "/Users/someone/.claude/uploads/abc/form.pdf"
    report = _stuck_report([_blocked("local_read_document", path)], f"이 PDF {path} 읽어 줘")
    assert report is not None and report["kind"] == "sensitive_wall"


def test_other_failures_still_wait_for_five() -> None:
    """반례: 비밀 자리가 아닌 실패는 예전대로 5번 연속까지 기다린다."""
    steps = [{"tool": "local_read_document", "ok": False, "arguments": {"path": r"E:\x.pdf"}, "error": "path_not_found"}]
    assert _stuck_report(steps * 4, r"E:\x.pdf 읽어") is None
    assert _stuck_report(steps * 5, r"E:\x.pdf 읽어")["kind"] == "keeps_failing"


def test_the_agent_loop_finishes_on_a_sensitive_wall() -> None:
    import inspect

    from alture_jarvis import agent

    source = inspect.getsource(agent)
    assert "_stuck_report(steps, prompt)" in source
    assert 'stop_reason = "wrapped_up:sensitive_wall"' in source


# --- 7. 이미 잘 하던 것: 지어낸 「진척율 30%」는 계속 잡힌다 -----------------------------

def test_made_up_percent_example_is_still_flagged() -> None:
    answer = "| 1 | `진척율 ( )` | **빈칸.** 진척율 숫자가 비어 있음. 예: \"30%\" |"
    read = {"245", "45", "01092", "2026", "11", "23"}
    assert "30%" in percent_warning(answer, read)
