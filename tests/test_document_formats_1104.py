"""정말 비어 있던 문서 형식 셋 — 주피터 노트북 · 저장한 메일 · 옛 엑셀 (2026-11-04).

MarkItDown 을 넣으려다 세어 보니 pdf · docx · xlsx · pptx · hwpx · odt · epub · html · rtf 는 이미 읽었다.
읽는 자를 두 벌 두지 않고(document_reader.py hwpx 교훈) 빈칸만 여기서 채운다.
"""
from __future__ import annotations

import json
from email.message import EmailMessage

from alture_jarvis.document_reader import SUPPORTED_EXTENSIONS, DocumentReader


def test_the_three_formats_are_supported() -> None:
    assert {".ipynb", ".eml", ".xls"} <= SUPPORTED_EXTENSIONS


def test_notebook_keeps_cell_order_code_outputs_and_errors() -> None:
    notebook = {
        "cells": [
            {"cell_type": "markdown", "source": ["# 매출 분석\n", "월별로 본다"]},
            {"cell_type": "code", "source": "df.groupby('월').sum()",
             "outputs": [{"output_type": "execute_result", "data": {"text/plain": ["   매출\n1월  120"]}}]},
            {"cell_type": "code", "source": "plot()",
             "outputs": [{"output_type": "display_data", "data": {"image/png": "iVBOR"}}]},
            {"cell_type": "code", "source": "1/0",
             "outputs": [{"output_type": "error", "ename": "ZeroDivisionError", "evalue": "division by zero"}]},
        ]
    }
    doc = DocumentReader().read_bytes("분석.ipynb", json.dumps(notebook, ensure_ascii=False).encode("utf-8"))
    assert doc.format == "ipynb"
    text = doc.text
    assert text.index("매출 분석") < text.index("groupby") < text.index("1월 120")
    assert "[셀 3 출력: 그림]" in text
    assert "ZeroDivisionError" in text
    assert "iVBOR" not in text  # 그림 바이트는 글로 넣지 않는다


def test_saved_mail_gives_header_body_and_attachment_names() -> None:
    message = EmailMessage()
    message["From"] = "팀장 <lead@example.com>"
    message["To"] = "me@example.com"
    message["Subject"] = "3분기 보고서 검토 부탁"
    message.set_content("금요일까지 표 2번 숫자 확인 부탁해요.")
    message.add_attachment(b"%PDF-1.4", maintype="application", subtype="pdf", filename="보고서.pdf")
    doc = DocumentReader().read_bytes("메일.eml", message.as_bytes())
    assert doc.format == "eml"
    assert "Subject: 3분기 보고서 검토 부탁" in doc.text
    assert "표 2번 숫자 확인" in doc.text
    assert "보고서.pdf" in doc.text and "읽지 않았다" in doc.text


def test_html_only_mail_is_read_as_visible_text() -> None:
    message = EmailMessage()
    message["Subject"] = "알림"
    message.set_content("<html><body><p>회의는 <b>3시</b></p><script>x()</script></body></html>", subtype="html")
    doc = DocumentReader().read_bytes("알림.eml", message.as_bytes())
    assert "회의는" in doc.text and "3시" in doc.text
    assert "x()" not in doc.text
