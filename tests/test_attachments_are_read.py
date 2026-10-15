"""첨부한 문서가 **정말 모델에게 읽히는가** — 형식마다 (2026-09-17).

사람의 걱정: 「독스를 올렸는데 읽고 답을 안 할 수도 있다」. 읽는 자(`document_reader`)의 시험은 있었지만,
대화 판이 실제로 쓰는 길(`runtime._attachments` → 모델 지시문)은 형식별로 재 본 적이 없었다.

각 파일에 **그 파일에만 있는 사실**(암호 같은 숫자)을 심고, 모델에게 가는 글에 그 사실이 들어가는지 본다.
못 읽는 형식(.hwp)은 판을 죽이지 않고, 무엇으로 바꾸면 되는지가 모델에게 전해져야 한다.
"""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

import pytest

from alture_jarvis.config import JarvisConfig
from alture_jarvis.runtime import JarvisRuntime


def _runtime(tmp_path: Path) -> JarvisRuntime:
    return JarvisRuntime(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs",
                                      camera_enabled=False, vision_enabled=False, voice_enabled=False, tts_enabled=False))


def _docx() -> bytes:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("여수 지점 9월 회의록")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "항목", "값"
    table.cell(1, 0).text, table.cell(1, 1).text = "확정 예산", "DOCX-7731만원"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _xlsx() -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "반별성적"
    sheet.append(["반", "평균"])
    sheet.append(["중2-A", "XLSX-88.4"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _pptx() -> bytes:
    pptx = pytest.importorskip("pptx")
    deck = pptx.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "분기 목표"
    slide.placeholders[1].text = "신규 등록 PPTX-4412명"
    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def _hwpx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml",
                         '<hs:sec xmlns:hs="h" xmlns:hp="p"><hp:p><hp:run><hp:t>계약 금액 HWPX-5150원</hp:t></hp:run></hp:p></hs:sec>')
    return buffer.getvalue()


def _pdf() -> bytes:
    # 글자 레이어가 있는 가장 작은 PDF — ASCII 만(기본 글꼴).
    stream = b"BT /F1 18 Tf 72 720 Td (Invoice total PDF-6620 USD) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


CASES = [
    ("회의록.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", _docx, "DOCX-7731"),
    ("성적.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _xlsx, "XLSX-88.4"),
    ("목표.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", _pptx, "PPTX-4412"),
    ("계약.hwpx", "application/hwp+zip", _hwpx, "HWPX-5150"),
    ("invoice.pdf", "application/pdf", _pdf, "PDF-6620"),
    ("명단.csv", "text/csv", lambda: "이름,코드\n김가온,CSV-3090\n".encode("cp949"), "CSV-3090"),
    ("메모.txt", "text/plain", lambda: "다음 주 휴강: TXT-1204".encode("utf-8"), "TXT-1204"),
]


@pytest.mark.parametrize(("name", "mime", "make", "secret"), CASES, ids=[case[0] for case in CASES])
def test_each_attached_format_reaches_the_model_as_text(tmp_path: Path, name, mime, make, secret) -> None:
    runtime = _runtime(tmp_path)
    payload = {"attachments": [{"name": name, "mime_type": mime, "data_base64": base64.b64encode(make()).decode()}]}
    context, images, metadata = runtime._attachments(payload, "이 파일 요약해줘")
    assert secret in context, f"{name} 의 내용이 모델에게 안 간다:\n{context[:400]}"
    assert images == [] and metadata[0]["name"] == name


def test_an_unreadable_old_hwp_does_not_kill_the_turn_and_says_what_to_do(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    payload = {"attachments": [
        {"name": "옛날계약서.hwp", "mime_type": "application/x-hwp", "data_base64": base64.b64encode(b"\xd0\xcf\x11\xe0junk").decode()},
        {"name": "메모.txt", "mime_type": "text/plain", "data_base64": base64.b64encode("TXT-1204".encode()).decode()},
    ]}
    context, _images, metadata = runtime._attachments(payload, "둘 다 읽어줘")
    assert "옛날계약서.hwp" in context and "HWPX" in context, context
    assert "TXT-1204" in context, "못 읽는 파일 하나가 나머지까지 막으면 안 된다"
    assert len(metadata) == 2


def test_a_document_only_turn_never_offers_the_camera(monkeypatch, tmp_path: Path) -> None:
    """문서만 붙이고 「이 문서 지금 보여?」 — 카메라 지름길·카메라 도구 둘 다 닫혀야 한다."""
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(runtime, "_vision_answer", lambda **_kw: (_ for _ in ()).throw(AssertionError("camera")))
    seen: dict = {}

    def fake_chat(prompt, **kwargs):
        seen.update(kwargs)
        return {"content": "문서에는 DOCX-7731 이 적혀 있습니다.", "tool_calls": []}

    monkeypatch.setattr(runtime.ollama, "chat_message", fake_chat)
    answer, _obs = runtime._contextual_answer("지금 이 문서 보여?", "s", images=[], attached=True)
    assert "DOCX-7731" in answer and seen["tools"] == []
