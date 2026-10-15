from __future__ import annotations

import csv
import html
import io
import json
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree


MODERN_OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx"}
PLAIN_TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".log", ".py", ".js",
    ".jsx", ".ts", ".tsx", ".html", ".htm", ".css", ".scss", ".yaml", ".yml",
    ".xml", ".toml", ".ini", ".cfg", ".ps1", ".bat", ".cmd", ".sql", ".java",
    ".c", ".h", ".cpp", ".hpp", ".rs", ".rtf",
}
SUPPORTED_EXTENSIONS = PLAIN_TEXT_EXTENSIONS | MODERN_OFFICE_EXTENSIONS | {
    ".pdf", ".odt", ".ods", ".odp", ".epub",
    # ★ 한글(HWPX). **만들 수는 있는데 되읽지 못했다** (2026-09-01 실측).
    #
    #   `local_write_document` 로 hwpx 를 만들어 놓고 `local_read_document` 로
    #   열면 `unsupported_document_format` 이었다. 그러면 「방금 만든 한글 파일에서
    #   3번 문단 고쳐줘」가 끊긴다 — 만들고도 못 읽는 자리다.
    #
    #   더 나쁜 것은 **읽는 자가 두 벌이었다는 것**이다. `preview_of_file` 은
    #   hwpx 를 읽는데 이쪽은 못 읽었다. 이제 여기 한 곳에서만 읽는다.
    ".hwpx",
}


@dataclass(slots=True)
class DocumentContent:
    text: str
    format: str
    encoding: str = ""
    pages: int = 0
    sheets: int = 0
    slides: int = 0
    truncated: bool = False
    warnings: tuple[str, ...] = ()

    def public_metadata(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "encoding": self.encoding,
            "pages": self.pages,
            "sheets": self.sheets,
            "slides": self.slides,
            "truncated": self.truncated,
            "warnings": list(self.warnings),
            "char_count": len(self.text),
        }


class _VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript", "svg"}:
            self._hidden += 1
        elif tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._hidden:
            self._hidden -= 1
        elif tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden and data.strip():
            self.parts.append(data)


def _normalize(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    compact: list[str] = []
    blank = False
    for line in lines:
        if line:
            compact.append(line)
            blank = False
        elif compact and not blank:
            compact.append("")
            blank = True
    return "\n".join(compact).strip()


def _xml_text(raw: bytes) -> str:
    try:
        root = ElementTree.fromstring(raw)
        values: list[str] = []
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag in {"p", "tr", "row"} and values and values[-1] != "\n":
                values.append("\n")
            if element.text and element.text.strip():
                values.append(element.text)
            if tag in {"tab"}:
                values.append("\t")
            if tag in {"br"}:
                values.append("\n")
        return _normalize(" ".join(values).replace(" \n ", "\n"))
    except ElementTree.ParseError:
        decoded = raw.decode("utf-8", errors="replace")
        return _normalize(html.unescape(re.sub(r"<[^>]+>", " ", decoded)))


def decode_text(raw: bytes) -> tuple[str, str]:
    if not raw:
        return "", "empty"
    bom_candidates = (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe\x00\x00", "utf-32-le"),
        (b"\x00\x00\xfe\xff", "utf-32-be"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    )
    for marker, encoding in bom_candidates:
        if raw.startswith(marker):
            return _normalize(raw.decode(encoding, errors="strict")), encoding
    for encoding in ("utf-8", "cp949", "euc-kr"):
        try:
            return _normalize(raw.decode(encoding, errors="strict")), encoding
        except UnicodeDecodeError:
            continue
    try:
        from charset_normalizer import from_bytes

        match = from_bytes(raw).best()
        if match is not None:
            encoding = str(match.encoding or "detected")
            return _normalize(str(match)), encoding
    except Exception:
        pass
    return _normalize(raw.decode("utf-8", errors="replace")), "utf-8-replacement"


PDFOCR = Callable[[bytes, int], tuple[str, int]]


class DocumentReader:
    def __init__(
        self,
        *,
        max_chars: int = 160_000,
        max_pages: int = 160,
        pdf_ocr: PDFOCR | None = None,
    ) -> None:
        self.max_chars = max(1_000, max_chars)
        self.max_pages = max(1, max_pages)
        self.pdf_ocr = pdf_ocr

    def read_path(self, path: Path, *, max_chars: int | None = None) -> DocumentContent:
        return self.read_bytes(path.name, path.read_bytes(), max_chars=max_chars)

    def read_bytes(
        self,
        name: str,
        raw: bytes,
        *,
        mime_type: str = "application/octet-stream",
        max_chars: int | None = None,
    ) -> DocumentContent:
        suffix = Path(name).suffix.lower()
        budget = max(1_000, min(int(max_chars or self.max_chars), self.max_chars))
        if suffix not in SUPPORTED_EXTENSIONS and not mime_type.startswith("text/"):
            raise ValueError(f"unsupported_document_format:{suffix or mime_type}")

        if suffix == ".pdf" or mime_type == "application/pdf":
            result = self._pdf(raw)
        elif suffix == ".docx":
            result = self._docx(raw)
        elif suffix == ".xlsx":
            result = self._xlsx(raw)
        elif suffix == ".pptx":
            result = self._pptx(raw)
        elif suffix == ".hwpx":
            result = self._hwpx(raw)
        elif suffix in {".odt", ".ods", ".odp"}:
            result = self._open_document(raw, suffix)
        elif suffix == ".epub":
            result = self._epub(raw)
        else:
            text, encoding = decode_text(raw)
            if suffix in {".html", ".htm"}:
                parser = _VisibleHTML()
                parser.feed(text)
                text = _normalize("".join(parser.parts))
            elif suffix == ".rtf":
                text = self._rtf(text)
            elif suffix in {".json", ".jsonl"}:
                text = self._pretty_json(text)
            result = DocumentContent(text=text, format=suffix.lstrip(".") or "text", encoding=encoding)

        if len(result.text) > budget:
            result.text = result.text[:budget]
            result.truncated = True
        result.text = _normalize(result.text)
        return result

    def _pdf(self, raw: bytes) -> DocumentContent:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        total = len(reader.pages)
        parts = []
        warnings: list[str] = []
        for index, page in enumerate(reader.pages[: self.max_pages]):
            text = page.extract_text() or ""
            if text.strip():
                parts.append(f"[PDF {index + 1}쪽]\n{text}")
        if total and not parts and self.pdf_ocr is not None:
            try:
                ocr_text, processed = self.pdf_ocr(raw, min(total, self.max_pages))
                if ocr_text.strip():
                    parts.append(ocr_text)
                    warnings.append(f"텍스트 레이어가 없어 Gemma 비전 OCR로 {processed}쪽을 판독했습니다.")
                    if processed < total:
                        warnings.append(f"OCR은 앞 {processed}쪽까지만 판독했습니다.")
                else:
                    warnings.append("텍스트 레이어가 없고 OCR에서도 읽을 문자를 찾지 못했습니다.")
            except Exception as exc:
                warnings.append(f"스캔 PDF OCR 실패: {str(exc)[:160]}")
        elif total and not parts:
            warnings.append("텍스트 레이어가 없는 스캔 PDF일 수 있습니다. OCR이 필요합니다.")
        if total > self.max_pages:
            warnings.append(f"앞 {self.max_pages}쪽까지만 판독했습니다.")
        return DocumentContent(
            text="\n\n".join(parts), format="pdf", pages=total,
            truncated=total > self.max_pages, warnings=tuple(warnings),
        )

    @staticmethod
    def _docx(raw: bytes) -> DocumentContent:
        try:
            from docx import Document

            document = Document(io.BytesIO(raw))
            parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
            for table_index, table in enumerate(document.tables, 1):
                parts.append(f"[표 {table_index}]")
                for row in table.rows:
                    parts.append(" | ".join(cell.text.strip() for cell in row.cells))
            return DocumentContent(text="\n".join(parts), format="docx")
        except ImportError:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                return DocumentContent(text=_xml_text(archive.read("word/document.xml")), format="docx")

    @staticmethod
    def _xlsx(raw: bytes) -> DocumentContent:
        try:
            from openpyxl import load_workbook

            workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            parts: list[str] = []
            for sheet in workbook.worksheets[:50]:
                parts.append(f"[시트: {sheet.title}]")
                for row_index, row in enumerate(sheet.iter_rows(values_only=True), 1):
                    values = ["" if value is None else str(value) for value in row]
                    if any(values):
                        parts.append("\t".join(values))
                    if row_index >= 10_000:
                        parts.append("[행 제한으로 이후 내용 생략]")
                        break
            return DocumentContent(text="\n".join(parts), format="xlsx", sheets=len(workbook.sheetnames))
        except ImportError:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = [name for name in archive.namelist() if name.startswith("xl/worksheets/sheet")]
                parts = [_xml_text(archive.read(name)) for name in names]
                return DocumentContent(text="\n".join(parts), format="xlsx", sheets=len(names))

    @staticmethod
    def _pptx(raw: bytes) -> DocumentContent:
        try:
            from pptx import Presentation

            presentation = Presentation(io.BytesIO(raw))
            parts: list[str] = []
            for index, slide in enumerate(presentation.slides, 1):
                values = []
                for shape in slide.shapes:
                    if hasattr(shape, "text") and str(shape.text).strip():
                        values.append(str(shape.text).strip())
                    if getattr(shape, "has_table", False):
                        for row in shape.table.rows:
                            values.append(" | ".join(cell.text.strip() for cell in row.cells))
                parts.append(f"[슬라이드 {index}]\n" + "\n".join(values))
            return DocumentContent(text="\n\n".join(parts), format="pptx", slides=len(presentation.slides))
        except ImportError:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = sorted(name for name in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name))
                return DocumentContent(
                    text="\n\n".join(f"[슬라이드 {i}]\n{_xml_text(archive.read(name))}" for i, name in enumerate(names, 1)),
                    format="pptx", slides=len(names),
                )

    @staticmethod
    def _open_document(raw: bytes, suffix: str) -> DocumentContent:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            text = _xml_text(archive.read("content.xml"))
        return DocumentContent(text=text, format=suffix.lstrip("."))

    @staticmethod
    def _hwpx(raw: bytes) -> DocumentContent:
        """한글 문서. ZIP+XML(OWPML) 이라 한글 없이 순수 파이썬으로 읽는다.

        본문은 `Contents/section*.xml` 에 있다. 각주도 같은 파일 안에 들어 있어
        본문과 함께 나온다 — 사람이 문서를 열었을 때 보는 것과 같은 순서다.
        """
        parts: list[str] = []
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("Contents/section") and name.endswith(".xml")
            )
            for name in names:
                visible = _xml_text(archive.read(name))
                if visible:
                    parts.append(visible)
        return DocumentContent(text=chr(10).join(parts), format="hwpx")

    @staticmethod
    def _epub(raw: bytes) -> DocumentContent:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith((".xhtml", ".html", ".htm"))]
            parts: list[str] = []
            for name in names[:200]:
                decoded, _ = decode_text(archive.read(name))
                parser = _VisibleHTML()
                parser.feed(decoded)
                visible = _normalize("".join(parser.parts))
                if visible:
                    parts.append(visible)
        return DocumentContent(text="\n\n".join(parts), format="epub")

    @staticmethod
    def _rtf(text: str) -> str:
        text = re.sub(r"\\par[d]?\s?", "\n", text)
        text = re.sub(r"\\'[0-9a-fA-F]{2}", "", text)
        text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
        return _normalize(text.replace("{", "").replace("}", ""))

    @staticmethod
    def _pretty_json(text: str) -> str:
        try:
            value = json.loads(text)
            return json.dumps(value, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return text


#: 미리보기로 실을 글자 수.
PREVIEW_CHARS = 700


def preview_of_file(path: Path, *, chars: int = PREVIEW_CHARS) -> str:
    """만든 문서의 **속을 글로** 보여 준다.

    ★ 2026-09-01 라이브. 자비스가 이력서 docx 를 제대로 만들어 놓고 답에는 파일
    경로만 적었다. 사용자는 "미리보기도 안되고 아무것도 안되는데"를 봤다. hwpx·xlsx·
    docx 는 브라우저가 못 그리므로, 「만들었습니다」와 경로만으로는 **열기 전까지
    제대로 들어갔는지 알 수 없다.** 읽어서 앞부분을 실어 준다.

    HWPX 는 ZIP+XML(OWPML) 이라 `DocumentReader` 의 표에 없다. 그런데 국내에서
    제일 자주 나올 형식이 이것이라 여기서 따로 읽는다.

    못 읽으면 빈 문자열이다. **미리보기 실패를 만들기 실패로 바꾸지 않는다.**
    """
    budget = max(100, int(chars))
    try:
        # ★ hwpx 갈래를 여기서 없앴다 (2026-09-01). `DocumentReader` 가 직접 읽는다 —
        #   읽는 자가 두 벌이면 한쪽만 아는 형식이 생긴다. 실제로 그랬다:
        #   미리보기는 한글을 읽는데 `local_read_document` 는 못 읽었다.
        text = DocumentReader(max_chars=budget * 4).read_path(path).text
    except Exception:
        return ""
    text = text.strip()
    if len(text) > budget:
        # 잘림은 침묵으로 오면 안 된다 — 이 저장소가 아는 규율이다.
        text = text[:budget].rstrip() + "\n…(이 뒤로 더 있음)"
    return text
