"""받고도 못 읽은 PDF — 받기가 그 자리에서 읽어 본문을 싣는다 (2026-10-18 LH 청년전세임대 공고 판 760b04f4).

휴대폰으로 「1순위 자격이 이게 맞나」를 물은 판이다. 자격(나이 · 거주)은 공고의 첨부 PDF 에 있었다. 모델은 14걸음째에
`browser_download` 를 불러 `ok` 를 받았지만, 그 뒤 4분 동안 같은 HTML 화면에서 찾기 · 내리기만 하다가 읽지 않은 조건을
답에 적었다(413초 · 23걸음 · 답 스스로 「읽지 않고 적은 것」). 저장된 파일을 열어 보니 PDF 가 아니라 **공고 화면 HTML** 이었다 —
첨부 링크가 `javascript:fileDownLoad('…')` 라 모델은 받을 주소를 몰랐고, 화면 주소에 이름만 `.pdf` 로 붙여 넘겼다.
「받은 path 를 local_read_document 로 읽어라」는 안내는 있었지만 안 먹었다(사고 R).

그래서 도구가 셋을 한다: 링크 ref 로 눌러 받기 · 문서라 부른 웹 화면은 저장하지 않기 · 받은 문서는 그 자리에서 읽어 싣기.
시험 자료는 전부 여기서 만든 가짜 글이다(실제 공고 · 개인 정보 없음).
"""
from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from alture_jarvis.browser import BrowserWorker
from alture_jarvis.evidence import TYPE_BODY_READ, TYPE_PAGE_OPEN, record_for
from alture_jarvis.transcript_policy import _TOOL_RESULT_MAX_CHARS

PAGE_URL = "https://notice.example.test/board/view.do?id=7"
SECRET = "RANK1-AGE-19-39-CODE-4417"


def _pdf(text: str) -> bytes:
    """글자 층이 있는 한 쪽짜리 PDF 를 손으로 만든다(외부 라이브러리 없이)."""
    stream = b"BT /F1 12 Tf 72 720 Td (" + text.encode("ascii") + b") Tj ET"
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


class _Response:
    def __init__(self, body: bytes, content_type: str, status: int = 200, disposition: str = "") -> None:
        self._body, self.status = body, status
        self.headers = {"Content-Type": content_type, **({"Content-Disposition": disposition} if disposition else {})}

    def body(self) -> bytes:
        return self._body


class _Request:
    def __init__(self, responses: dict[str, _Response]) -> None:
        self.responses, self.asked = responses, []

    def get(self, url: str, timeout: int = 0) -> _Response:
        self.asked.append(url)
        return self.responses[url]


class _Download:
    def __init__(self, name: str, body: bytes, url: str) -> None:
        self.suggested_filename, self._body, self.url = name, body, url

    def save_as(self, path: str) -> None:
        Path(path).write_bytes(self._body)


class _Expect:
    def __init__(self, download: _Download | None) -> None:
        self._download = download

    def __enter__(self) -> "_Expect":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    @property
    def value(self) -> _Download:
        if self._download is None:
            raise TimeoutError("Timeout 60000ms exceeded while waiting for event \"download\"")
        return self._download


class _Page:
    def __init__(self, responses: dict[str, _Response] | None = None, download: _Download | None = None) -> None:
        self.url = PAGE_URL
        self.context = SimpleNamespace(request=_Request(responses or {}))
        self._download = download

    def expect_download(self, timeout: int = 0) -> _Expect:
        return _Expect(self._download)


class _Link:
    def __init__(self, text: str, href: str) -> None:
        self.text, self.href, self.clicked = text, href, 0

    def get_attribute(self, name: str) -> str | None:
        return {"href": self.href}.get(name)

    def inner_text(self, timeout: int = 0) -> str:
        return self.text

    def click(self) -> None:
        self.clicked += 1


def _worker(tmp_path: Path, link: _Link | None = None) -> BrowserWorker:
    worker = object.__new__(BrowserWorker)
    worker.config = SimpleNamespace(browser_download_dir=tmp_path / "downloads")
    worker._ref_locator = lambda page, ref: link  # type: ignore[method-assign]
    return worker


def _saved(tmp_path: Path) -> list[Path]:
    folder = tmp_path / "downloads"
    return sorted(folder.iterdir()) if folder.exists() else []


# ── 받은 문서는 그 자리에서 읽어 본문을 싣는다 ─────────────────────────────


def test_a_downloaded_pdf_comes_back_with_its_text_and_path(tmp_path: Path) -> None:
    url = "https://notice.example.test/files/notice.pdf"
    page = _Page({url: _Response(_pdf(f"Eligibility {SECRET}"), "application/pdf")})
    result = _worker(tmp_path)._download(page, {"url": url})

    assert result["ok"] is True
    assert Path(result["path"]).is_file() and Path(result["path"]).parent == tmp_path / "downloads"
    # 읽는 걸음을 모델에게 맡기지 않는다 — 같은 걸음에 본문이 있다.
    assert SECRET in result["content"]
    assert result["format"] == "pdf" and result["pages"] == 1
    assert result["char_count"] == result["total_chars"] == len(result["content"])
    assert result["truncated"] is False
    assert "content" in result["instruction"]


def test_a_downloaded_text_document_is_read_too(tmp_path: Path) -> None:
    url = "https://notice.example.test/files/qna.txt"
    page = _Page({url: _Response(f"질문과 답 {SECRET}".encode("utf-8"), "text/plain")})
    result = _worker(tmp_path)._download(page, {"url": url})
    assert result["ok"] is True and SECRET in result["content"]


# ── 문서라 부른 것이 웹 화면이면 저장하지 않는다 (760b04f4 의 바로 그 모양) ──────


def test_the_page_itself_saved_as_pdf_is_refused(tmp_path: Path) -> None:
    html = b"\r\n\r\n\r\n<!DOCTYPE html>\r\n<html lang=\"ko\"><head><meta charset=\"utf-8\"></head><body>notice</body></html>"
    page = _Page({PAGE_URL: _Response(html, "text/html")})
    result = _worker(tmp_path)._download(page, {"url": PAGE_URL, "name": "notice2026.pdf"})

    assert result["ok"] is False
    assert result["got"] == "web_page"
    assert "ref" in result["instruction"]
    # 화면을 `.pdf` 이름으로 남기면 다음 읽기가 엉뚱한 글을 읽는다 — 아예 안 남긴다.
    assert _saved(tmp_path) == []


def test_an_html_page_asked_for_without_a_document_name_is_still_saved(tmp_path: Path) -> None:
    # 문서를 받겠다고 한 것이 아니면(이름에 문서 확장자 없음) 예전처럼 저장한다 — 거절은 「문서라 부른 화면」에만.
    url = "https://notice.example.test/page"
    page = _Page({url: _Response(b"<html><body>hi</body></html>", "text/html")})
    result = _worker(tmp_path)._download(page, {"url": url})
    assert result["ok"] is True and "content" not in result


# ── 주소가 없는 첨부는 ref 로 눌러 받는다 ──────────────────────────────────


def test_a_javascript_attachment_is_clicked_and_the_file_is_caught(tmp_path: Path) -> None:
    link = _Link("[공고문]모집공고.pdf", "javascript:fileDownLoad('123');")
    download = _Download("공고문.pdf", _pdf(f"Rank one {SECRET}"), "https://notice.example.test/file.do?fileid=123")
    page = _Page(download=download)
    result = _worker(tmp_path, link)._download(page, {"ref": "j44"})

    assert link.clicked == 1
    assert page.context.request.asked == []  # 화면 주소를 다시 받지 않았다
    assert result["ok"] is True
    assert result["url"].endswith("fileid=123")
    assert result["path"].endswith("공고문.pdf")
    assert SECRET in result["content"]


def test_a_link_with_a_real_address_is_fetched_by_address(tmp_path: Path) -> None:
    link = _Link("안내.pdf", "/files/guide.pdf")
    url = "https://notice.example.test/files/guide.pdf"
    page = _Page({url: _Response(_pdf(SECRET), "application/pdf")})
    result = _worker(tmp_path, link)._download(page, {"ref": "j3"})
    assert link.clicked == 0 and page.context.request.asked == [url]
    assert SECRET in result["content"]


def test_a_click_that_brings_no_file_says_so(tmp_path: Path) -> None:
    link = _Link("바로보기", "javascript:void(0);")
    result = _worker(tmp_path, link)._download(_Page(download=None), {"ref": "j5"})
    assert result["ok"] is False and "내려오지 않았다" in result["instruction"]
    assert _saved(tmp_path) == []


def test_a_clicked_download_that_is_a_page_is_not_kept(tmp_path: Path) -> None:
    link = _Link("공고문.pdf", "javascript:fileDownLoad('9');")
    download = _Download("공고문.pdf", b"<!DOCTYPE html><html><body>login</body></html>", "https://notice.example.test/x")
    result = _worker(tmp_path, link)._download(_Page(download=download), {"ref": "j9"})
    assert result["ok"] is False and result["got"] == "web_page"
    assert _saved(tmp_path) == []


def test_an_irreversible_looking_link_is_not_clicked_through_this_door(tmp_path: Path) -> None:
    link = _Link("결제하기", "javascript:pay();")
    with pytest.raises(RuntimeError, match="irreversible_click_needs_approval"):
        _worker(tmp_path, link)._download(_Page(), {"ref": "j1"})
    assert link.clicked == 0


# ── 문서가 아닌 것은 읽으려 하지 않는다 ────────────────────────────────────


@pytest.mark.parametrize("name, content_type", [("bundle.zip", "application/zip"), ("setup.exe", "application/octet-stream")])
def test_non_documents_are_saved_but_not_read(tmp_path: Path, monkeypatch, name: str, content_type: str) -> None:
    from alture_jarvis import document_reader

    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("문서가 아닌 파일을 읽으려 했다")

    monkeypatch.setattr(document_reader.DocumentReader, "read_path", boom)
    url = f"https://notice.example.test/files/{name}"
    page = _Page({url: _Response(b"PK\x03\x04binary", content_type)})
    result = _worker(tmp_path)._download(page, {"url": url})
    assert result["ok"] is True and Path(result["path"]).is_file()
    assert "content" not in result and "char_count" not in result


def test_old_hwp_points_to_the_converter(tmp_path: Path) -> None:
    url = "https://notice.example.test/files/form.hwp"
    page = _Page({url: _Response(b"\xd0\xcf\x11\xe0hwp", "application/x-hwp")})
    result = _worker(tmp_path)._download(page, {"url": url})
    assert result["ok"] is True and "content" not in result
    assert "hwp_export_pdf" in result["instruction"]


# ── 크기 상한 — 도구 결과 한 건의 상한을 넘겨 싣지 않는다(사고 Q) ─────────────


def test_the_text_is_capped_and_says_where_it_was_cut(tmp_path: Path) -> None:
    body = ("가" * 49_990 + SECRET).encode("utf-8")
    url = "https://notice.example.test/files/long.txt"
    page = _Page({url: _Response(body, "text/plain")})

    default = _worker(tmp_path)._download(page, {"url": url})
    assert len(default["content"]) == 20_000 and default["total_chars"] == 50_015
    assert default["truncated"] is True and "local_read_document" in default["instruction"]

    greedy = _worker(tmp_path)._download(page, {"url": url, "max_chars": 999_999})
    assert len(greedy["content"]) == _TOOL_RESULT_MAX_CHARS


# ── 받아 읽은 것은 읽은 것으로 센다 ─────────────────────────────────────────


def test_a_download_with_text_is_a_body_read_and_without_is_only_opened(tmp_path: Path) -> None:
    path = str(tmp_path / "a.pdf")
    read = record_for("browser_download", {"path": path, "url": "https://x.test/a", "content": "본문"}, ok=True, step=3)
    kept = record_for("browser_download", {"path": path, "url": "https://x.test/a"}, ok=True, step=4)
    failed = record_for("browser_download", {"url": "https://x.test/a", "ok": False}, ok=False, step=5,
                        arguments={"url": "https://x.test/a"})
    assert read is not None and read.type == TYPE_BODY_READ and read.content_hash
    assert kept is not None and kept.type == TYPE_PAGE_OPEN
    assert failed is None


def test_the_plan_counts_a_read_download_as_a_source() -> None:
    from alture_jarvis.agent import BrowserAgent

    steps = [
        {"tool": "browser_open", "ok": True, "evidence": {"url": PAGE_URL}},
        {"tool": "browser_download", "ok": True, "evidence": {"url": "https://x.test/f?id=1", "char_count": 5_000}},
        {"tool": "browser_download", "ok": True, "evidence": {"url": "https://x.test/f?id=2"}},
    ]
    assert BrowserAgent._sources_actually_read(steps) == ["https://x.test/f?id=1"]


def test_the_read_text_reaches_the_grounding_store() -> None:
    from alture_jarvis.observations import shape

    kind, _title, payload, _cut = shape(
        "browser_download", {"ref": "j44"},
        {"action": "browser_download", "path": r"C:\x\notice.pdf", "url": "https://x.test/f", "content": SECRET, "format": "pdf"},
    )
    assert kind == "document" and payload["text"] == SECRET


def test_the_tool_offers_a_ref() -> None:
    from alture_jarvis.browser import BrowserTools

    tools = object.__new__(BrowserTools)
    definitions = {d["function"]["name"]: d["function"] for d in BrowserTools._build_definitions(tools)}
    spec = definitions["browser_download"]["parameters"]
    assert "ref" in spec["properties"] and spec["required"] == []
