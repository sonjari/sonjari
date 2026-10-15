"""드라이브 문서는 **찾는 것**과 **읽는 것**이 다른 일이다.

2026-08-12 실측. "구글 드라이브의 이력서를 읽고 공고를 찾아라"를 시켰더니 이력서를
한 줄도 못 읽고 끝났다. 원인은 모델이 아니라 **연장이 없던 것**이었다:

    google_drive_search   파일을 찾는다  ✅ 있었다
    (본문을 읽는 도구)                   ❌ 없었다

없으니 자비스는 ① 로컬 파일 도구에 구글 문서 주소를 넣어 보고(`path_outside_allowed_roots`)
② 브라우저로 docs.google.com 을 열었다 — 자비스 크롬은 구글에 로그인돼 있지 않아
**로그인 화면**만 나왔다. 그런데 그 로그인 화면 2개가 "2개 읽었다"로 세어졌다.

여기서 지키는 것 넷:

  1. 구글 문서(Docs·Sheets)는 내려받기가 아니라 **내보내기**로 읽는다
  2. 못 읽는 형식은 빈 본문이 아니라 **에러**다 (빈 본문은 "내용 없는 문서"로 읽힌다)
  3. 이름이 여러 개 맞으면 고르지 않고 후보를 돌려준다 — 비슷한 걸 읽고 맞다고 하는 게 제일 나쁘다
  4. 읽기 도구는 `_CONTENT_TOOLS` 에 있어야 "실제로 읽었다" 장부에 잡힌다
"""

from __future__ import annotations

from typing import Any

import pytest

from alture_jarvis.agent import _READ_TOOLS
from alture_jarvis.google_workspace import GoogleWorkspace


class _Workspace:
    """`GoogleWorkspace` 의 읽기 부분만 떼어 쓰는 대역.

    실제 클래스는 설정·토큰·이벤트버스를 다 요구하므로, 여기서는 API 왕복 두 개
    (`_get`, `_get_text`)만 갈아 끼워 **분기 판단**을 시험한다.
    """

    def __init__(self, meta: dict[str, Any], body: str = "") -> None:
        self._meta = meta
        self._body = body
        self.exported: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.found: list[dict[str, Any]] = []

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del url, params
        return self._meta

    def _get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        self.exported.append({"url": url, "params": dict(params or {})})
        return self._body

    def drive_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.search_calls.append(arguments)
        return {"files": list(self.found), "count": len(self.found)}

    drive_read = GoogleWorkspace.drive_read
    _DRIVE_EXPORT = GoogleWorkspace._DRIVE_EXPORT


def test_a_google_doc_is_exported_as_text() -> None:
    workspace = _Workspace(
        {
            "id": "abc",
            "name": "최나래 이력서",
            "mimeType": "application/vnd.google-apps.document",
            "webViewLink": "https://docs.google.com/document/d/abc/edit",
        },
        body="최나래\n회계팀 지원\n경력 3년\n",
    )

    result = workspace.drive_read({"file_id": "abc"})

    assert result["read"] is True
    assert "회계팀 지원" in result["text"], "본문을 못 가져왔다"
    assert workspace.exported[0]["url"].endswith("/export"), "내려받기로 열려고 했다"
    assert workspace.exported[0]["params"]["mimeType"] == "text/plain"


def test_a_plain_text_file_is_downloaded_directly() -> None:
    workspace = _Workspace(
        {"id": "t1", "name": "메모.txt", "mimeType": "text/plain"}, body="한 줄"
    )

    result = workspace.drive_read({"file_id": "t1"})

    assert result["read"] is True
    assert workspace.exported[0]["params"] == {"alt": "media"}


def test_an_unreadable_type_raises_instead_of_returning_nothing() -> None:
    """빈 본문을 돌려주면 '내용이 없는 문서'로 읽힌다 — 못 읽은 것과 다르다."""
    workspace = _Workspace({"id": "p1", "name": "이력서.pdf", "mimeType": "application/pdf"})

    with pytest.raises(RuntimeError) as error:
        workspace.drive_read({"file_id": "p1"})

    assert "drive_unsupported_type" in str(error.value)
    assert "application/pdf" in str(error.value), "무슨 형식인지 안 알려 준다"


def test_an_ambiguous_name_returns_candidates_instead_of_guessing() -> None:
    workspace = _Workspace({})
    workspace.found = [
        {"id": "a", "name": "이력서"},
        {"id": "b", "name": "이력서"},
    ]

    result = workspace.drive_read({"name": "이력서"})

    assert result["read"] is False
    assert len(result["candidates"]) == 2
    assert workspace.exported == [], "아무거나 하나 골라서 읽어 버렸다"


def test_a_single_name_match_is_read() -> None:
    workspace = _Workspace(
        {"id": "only", "name": "이력서", "mimeType": "application/vnd.google-apps.document"},
        body="본문",
    )
    workspace.found = [{"id": "only", "name": "이력서"}]

    result = workspace.drive_read({"name": "이력서"})

    assert result["read"] is True
    assert result["text"] == "본문"


def test_reading_drive_counts_as_actually_reading_a_source() -> None:
    """이게 빠져 있으면 '읽었다'는 장부에 안 잡혀 근거 없는 답을 걸러내지 못한다."""
    assert "google_drive_read" in _READ_TOOLS
