from __future__ import annotations

import base64
import ctypes
import hashlib
import html
import json
import mimetypes
import os
import re
import secrets
import threading
import time
import uuid
import webbrowser
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse
from zoneinfo import ZoneInfo

import httpx

from .config import JarvisConfig
from .document_reader import preview_of_file
from .events import EventBus
from .external_actions import SETTLED_STATUSES, ExternalActionStore
from .local_computer import LocalComputerTools
from .models import RiskLevel
from .tool_gateway import InverseSpec, ToolGateway, ToolSpec


GOOGLE_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events.owned",
    # ★ 드라이브 쓰기 (2026-09-01). **`drive` 가 아니라 `drive.file` 이다.**
    #
    #   `drive` 는 사용자 드라이브 전체를 고칠 수 있다. `drive.file` 은 **자비스가
    #   만든 파일만** — 남의 원본은 손댈 수 없다. 「이력서 고쳐놔」의 옳은 모양은
    #   원본 덮어쓰기가 아니라 **수정본을 옆에 만드는 것**이고, 그건 이 좁은 권한으로
    #   된다. 넓은 권한이 필요해 보이면 그건 대개 설계가 틀린 것이다.
    "https://www.googleapis.com/auth/drive.file",
)

# Tokens issued before the write scopes above were added carry only the
# read-only set. status()/send/create/etc. must not assume a stored token can
# already write just because the code now requests it.
_READ_ONLY_SCOPES = GOOGLE_SCOPES[:6]
_WRITE_SCOPES = GOOGLE_SCOPES[6:]

# ★ Google 이 제한(restricted)으로 분류한 권한 — 공개 앱이면 검증 + CASA 연례 평가 (2026-09-16, 인수인계 H4).
#   https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification
RESTRICTED_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
)
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
# 드라이브 검색은 공개판에서도 그대로 돈다 — `drive.file` 토큰으로 부르면 Google 이 **고른 파일·온텔릭이 만든
# 파일만** 돌려준다(권한이 곧 거름망). 지메일 읽기는 권한이 없으니, 도구를 빼는 대신(프롬프트가 이름을 부르므로
# 유령 도구가 된다) 부르면 브라우저 길을 알려 준다.
PICKED_FILES_NAME = "google_picked_files.json"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HEADER_INJECTION_RE = re.compile(r"[\r\n]")


class GoogleScopeInsufficientError(RuntimeError):
    """Raised when the Google API rejects a write call for lack of scope.

    The stored OAuth token may predate the write scopes being added, so the
    only reliable signal is a 403 at call time (see _post()).
    """


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class TokenVault:
    """Current-user protected token storage on Windows (DPAPI)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _blob(data: bytes) -> tuple[_DataBlob, Any]:
        buffer = ctypes.create_string_buffer(data)
        blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        return blob, buffer

    @staticmethod
    def _protect(data: bytes) -> bytes:
        if os.name != "nt":
            return data
        source, source_buffer = TokenVault._blob(data)
        output = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        _ = source_buffer
        if not crypt32.CryptProtectData(
            ctypes.byref(source),
            "Sonjari Google OAuth",
            None,
            None,
            None,
            0,
            ctypes.byref(output),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    @staticmethod
    def _unprotect(data: bytes) -> bytes:
        if os.name != "nt":
            return data
        source, source_buffer = TokenVault._blob(data)
        output = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        _ = source_buffer
        if not crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> dict[str, Any]:
        raw = self._unprotect(self.path.read_bytes())
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid_google_token")
        return value

    def save(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        protected = self._protect(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(protected)
        temporary.replace(self.path)
        if os.name != "nt":
            os.chmod(self.path, 0o600)


def resolve_oauth_client(config: Any) -> dict[str, str]:
    """Resolve the app-owned desktop OAuth client.

    Public builds place their published client JSON in ``resources`` or
    inject the same values at packaging time. The historical per-user file
    is read only as a compatibility fallback for existing installations;
    new users are never instructed to create a Cloud Console project.
    """
    configured_id = str(config.google_oauth_client_id or "").strip()
    if configured_id:
        return {
            "client_id": configured_id,
            "client_secret": str(config.google_oauth_client_secret or "").strip(),
            "project_id": str(config.google_project_id or "").strip(),
            "source": "packaged_env",
        }

    candidates = (
        (Path(config.google_oauth_bundle_path), "packaged_file"),
        (Path(config.google_client_secret_path), "legacy_file"),
    )
    value: dict[str, Any] | None = None
    source = ""
    for path, candidate_source in candidates:
        if not path.is_file():
            continue
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            value = loaded
            source = candidate_source
            break
    if value is None:
        raise RuntimeError("google_oauth_client_not_packaged")
    installed = value.get("installed") if isinstance(value, dict) else None
    if not isinstance(installed, dict):
        raise RuntimeError("google_desktop_client_required")
    project_id = str(installed.get("project_id") or "")
    if config.google_project_id and project_id != config.google_project_id:
        raise RuntimeError("google_project_mismatch")
    client_id = str(installed.get("client_id") or "")
    client_secret = str(installed.get("client_secret") or "")
    if not client_id:
        raise RuntimeError("google_client_credentials_invalid")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "project_id": project_id,
        "source": source,
    }


def oauth_client_present(config: Any) -> bool:
    """이 빌드·이 PC 에서 구글 연결을 시작할 수 있는가.

    공개판 패키지엔 OAuth 클라이언트가 없다(2026-10-01 실측: msix 29,976개 파일 중 0개). 그 판에선
    구글 도구가 처음부터 꺼지고, 화면도 구글 카드·도구 묶음·「Google 쓰기」 설정을 진열하지 않는다.
    도구 등록과 화면이 같은 판정을 쓰도록 여기 하나에 둔다.
    """
    if not getattr(config, "google_enabled", False):
        return False
    try:
        resolve_oauth_client(config)
        return True
    except Exception:
        return False


class GoogleWorkspace:
    AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URI = "https://oauth2.googleapis.com/token"

    def __init__(
        self,
        config: JarvisConfig,
        events: EventBus,
        *,
        local_computer: LocalComputerTools,
        actions: ExternalActionStore,
    ) -> None:
        self.config = config
        self.events = events
        self.local_computer = local_computer
        self.actions = actions
        self.vault = TokenVault(config.google_token_path)
        #: 꺼내 쓴 토큰 값을 알려 줄 곳(값, 이름) — 런타임이 `known_secrets.learn` 을 건다. 도구 결과에 그 값이 찍히면 가려진다.
        self.secret_sink: Any = None
        self._lock = threading.RLock()
        self._server: ThreadingHTTPServer | None = None
        self._flow: dict[str, Any] = {}
        self._last_error = ""
        self._profile: dict[str, Any] = {}
        # Injectable so tests can pass httpx.MockTransport instead of hitting
        # the real network.
        self._transport: httpx.BaseTransport | None = None
        self._definitions = self._build_definitions()

    @staticmethod
    def _function(
        name: str,
        description: str,
        properties: dict[str, Any],
        required: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required or [],
                },
            },
        }

    def _build_definitions(self) -> list[dict[str, Any]]:
        return [
            self._function(
                "google_drive_search",
                "연결된 사용자의 Google Drive에서 파일과 폴더를 읽기 전용으로 검색한다.",
                {
                    "query": {"type": "string", "description": "파일명 또는 본문 검색어. 비우면 최근 파일"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                },
            ),
            self._function(
                "google_drive_read",
                "Google Drive 문서의 **본문을 읽는다**. google_drive_search 로 찾은 뒤 이걸로 열어라. "
                "브라우저로 docs.google.com 을 여는 것은 소용없다 — 손자리 크롬은 구글에 로그인돼 있지 않아 "
                "로그인 화면만 나온다. 이 도구는 API 로 직접 가져오므로 로그인이 필요 없다.",
                {
                    "file_id": {"type": "string", "description": "google_drive_search 가 준 id. 이걸 쓰는 게 정확하다"},
                    "name": {"type": "string", "description": "파일명. id 를 모를 때만. 여러 개면 후보를 돌려준다"},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 60000},
                },
            ),
            self._function(
                "google_drive_prepare_write",
                "Google Drive에 **새 파일로 올리는 것을 준비한다.** 실제로 올리지 않고 이름·형식·크기를 검증해 "
                "승인용 미리보기와 action_id를 만든다. 로컬 파일을 올리려면 source_path, 글을 바로 문서로 만들려면 text. "
                "사용자 드라이브의 기존 파일은 **덮어쓰지 않는다** — 언제나 새 파일이다.",
                {
                    "source_path": {"type": "string", "description": "올릴 로컬 파일의 절대경로. 만든 문서를 그대로 올릴 때"},
                    "text": {"type": "string", "description": "글 내용. source_path 대신 쓴다. 구글 문서로 만들어진다"},
                    "name": {"type": "string", "description": "드라이브에 저장될 이름. 비우면 파일명 그대로"},
                    "convert": {"type": "boolean", "description": "구글 문서/시트/슬라이드로 변환할지. 기본 true"},
                    "folder_id": {"type": "string", "description": "넣을 폴더 id. 비우면 내 드라이브 루트"},
                },
            ),
            self._function(
                "google_drive_write",
                "google_drive_prepare_write가 만든 action_id로 실제 업로드를 커밋한다. 화면 승인이 필요하다.",
                {"action_id": {"type": "string"}},
                ["action_id"],
            ),
            self._function(
                "google_gmail_search",
                "연결된 사용자의 Gmail에서 메일을 읽기 전용으로 검색하고 제목·보낸 사람·날짜·요약을 가져온다.",
                {
                    "query": {"type": "string", "description": "Gmail 검색 문법. 비우면 최근 받은 메일"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                },
            ),
            self._function(
                "google_calendar_upcoming",
                "연결된 사용자의 기본 Google Calendar에서 앞으로의 일정을 읽기 전용으로 확인한다.",
                {
                    "days": {"type": "integer", "minimum": 1, "maximum": 90},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                    "query": {"type": "string", "description": "일정 제목 검색어"},
                },
            ),
            self._function(
                "google_gmail_prepare_send",
                "Gmail 발송을 준비한다. 실제로 보내지 않고 수신자·제목·본문·첨부를 검증해 승인용 미리보기와 action_id를 만든다. "
                "실제 발송은 이 결과의 action_id를 그대로 google_gmail_send에 넘겨 화면 승인을 받은 뒤에만 이뤄진다.",
                {
                    "to": {"type": "array", "items": {"type": "string"}, "description": "받는 사람 이메일 주소 목록"},
                    "cc": {"type": "array", "items": {"type": "string"}},
                    "bcc": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "body_text": {"type": "string"},
                    "body_html": {"type": "string", "description": "선택. 있으면 멀티파트로 함께 발송"},
                    "attachments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "허용된 로컬 폴더 안의 첨부파일 절대경로 목록",
                    },
                },
                ["to", "subject"],
            ),
            self._function(
                "google_gmail_send",
                "google_gmail_prepare_send가 만든 action_id로 실제 Gmail 발송을 커밋한다. "
                "화면에서 사람이 직접 승인해야만 실행된다.",
                {"action_id": {"type": "string"}},
                ["action_id"],
            ),
            self._function(
                "google_calendar_prepare_create",
                "Google Calendar 일정 생성을 준비한다. 실제로 만들지 않고 시간·충돌을 검증해 승인용 미리보기와 action_id를 만든다.",
                {
                    "summary": {"type": "string"},
                    "start": {
                        "type": "string",
                        "description": "RFC3339 Asia/Seoul, 예: 2026-08-05T14:00:00+09:00. all_day가 true면 YYYY-MM-DD",
                    },
                    "end": {
                        "type": "string",
                        "description": "RFC3339 Asia/Seoul. all_day가 true면 YYYY-MM-DD",
                    },
                    "all_day": {"type": "boolean"},
                    "location": {"type": "string"},
                    "description": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}, "description": "참석자 이메일 목록"},
                    "send_updates": {
                        "type": "string",
                        "enum": ["none", "all"],
                        "description": "참석자에게 초대 메일을 보낼지. 기본 none",
                    },
                    "calendar_id": {"type": "string", "description": "비우면 primary"},
                    "allow_past": {
                        "type": "boolean",
                        "description": "과거 시각에 만들 때만 true. 기본 false — 지난 시각이면 거절하고 오늘 날짜를 돌려준다",
                    },
                },
                ["summary", "start", "end"],
            ),
            self._function(
                "google_calendar_create",
                "google_calendar_prepare_create가 만든 action_id로 실제 일정 생성을 커밋한다. 화면 승인이 필요하다.",
                {"action_id": {"type": "string"}},
                ["action_id"],
            ),
            self._function(
                "google_calendar_prepare_update",
                "기존 일정 수정을 준비한다. 바꿀 필드만 넘기면 되고, 실제 변경 전후 값을 승인 화면에 보여준다.",
                {
                    "event_id": {"type": "string"},
                    "calendar_id": {"type": "string", "description": "비우면 primary"},
                    "summary": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "all_day": {"type": "boolean"},
                    "location": {"type": "string"},
                    "description": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "send_updates": {"type": "string", "enum": ["none", "all"]},
                    "allow_past": {
                        "type": "boolean",
                        "description": "과거 시각으로 옮길 때만 true. 기본 false",
                    },
                },
                ["event_id"],
            ),
            self._function(
                "google_calendar_update",
                "google_calendar_prepare_update가 만든 action_id로 실제 일정 수정을 커밋한다. 화면 승인이 필요하다.",
                {"action_id": {"type": "string"}},
                ["action_id"],
            ),
            self._function(
                "google_calendar_prepare_delete",
                "기존 일정 삭제를 준비한다. 실제 삭제 전에 제목·시각을 조회해 승인 화면에 보여준다.",
                {
                    "event_id": {"type": "string"},
                    "calendar_id": {"type": "string", "description": "비우면 primary"},
                    "send_updates": {"type": "string", "enum": ["none", "all"]},
                },
                ["event_id"],
            ),
            self._function(
                "google_calendar_delete",
                "google_calendar_prepare_delete가 만든 action_id로 실제 일정 삭제를 커밋한다. 화면 승인이 필요하다.",
                {"action_id": {"type": "string"}},
                ["action_id"],
            ),
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def active_ollama_tools(self) -> list[dict[str, Any]]:
        if not self._is_configured():
            return []
        return [
            definition
            for definition in self._definitions
            if self.config.google_write_enabled
            or str(definition["function"]["name"]) not in self._WRITE_TOOL_NAMES
        ]

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self.active_ollama_tools}

    _WRITE_TOOL_NAMES = {
        "google_drive_prepare_write",
        "google_drive_write",
        "google_gmail_prepare_send",
        "google_gmail_send",
        "google_calendar_prepare_create",
        "google_calendar_create",
        "google_calendar_prepare_update",
        "google_calendar_update",
        "google_calendar_prepare_delete",
        "google_calendar_delete",
    }

    def register(self, gateway: ToolGateway) -> None:
        handlers = {
            "google_drive_search": self.drive_search,
            "google_drive_read": self.drive_read,
            "google_drive_prepare_write": self.drive_prepare_write,
            "google_drive_write": self.drive_write,
            "google_gmail_search": self.gmail_search,
            "google_calendar_upcoming": self.calendar_upcoming,
            "google_gmail_prepare_send": self.gmail_prepare_send,
            "google_gmail_send": self.gmail_send,
            "google_calendar_prepare_create": self.calendar_prepare_create,
            "google_calendar_create": self.calendar_create,
            "google_calendar_prepare_update": self.calendar_prepare_update,
            "google_calendar_update": self.calendar_update,
            "google_calendar_prepare_delete": self.calendar_prepare_delete,
            "google_calendar_delete": self.calendar_delete,
        }
        risks: dict[str, RiskLevel] = {
            "google_drive_search": RiskLevel.L1,
            "google_drive_read": RiskLevel.L1,
            "google_drive_prepare_write": RiskLevel.L1,
            "google_drive_write": RiskLevel.L2,
            "google_gmail_search": RiskLevel.L1,
            "google_calendar_upcoming": RiskLevel.L1,
            "google_gmail_prepare_send": RiskLevel.L1,
            "google_gmail_send": RiskLevel.L2,
            "google_calendar_prepare_create": RiskLevel.L1,
            "google_calendar_create": RiskLevel.L2,
            "google_calendar_prepare_update": RiskLevel.L1,
            "google_calendar_update": RiskLevel.L2,
            "google_calendar_prepare_delete": RiskLevel.L1,
            "google_calendar_delete": RiskLevel.L2,
        }
        configured = self._is_configured()
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            enabled = configured and (
                self.config.google_write_enabled if name in self._WRITE_TOOL_NAMES else True
            )
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["function"]["description"]),
                    parameters=dict(definition["function"].get("parameters") or {}),
                    risk_level=risks[name],
                    handler=handlers[name],
                    enabled=enabled,
                    inverse=self._inverses().get(name),
                    dynamic_risk=self._dynamic_risks().get(name),
                )
            )

    def _inverses(self) -> dict[str, InverseSpec]:
        """되돌릴 수 있는 캘린더 동작들.

        일정 만들기는 event_id 를 돌려주고, 지우기는 그 id 하나로 끝난다 —
        셀렉터도 화면도 필요 없는 순수 API 라서 **역동작이 확실하다.**

        여기 없는 것들은 일부러 없다:
          google_gmail_send      보낸 메일은 못 되돌린다. 명세를 달지 않는다.
          google_calendar_delete 이미 지운 것을 되살리려면 원본이 필요한데
                                 삭제 커밋은 그걸 안 남긴다. 지금은 못 한다.
        """
        return {
            "google_drive_write": InverseSpec(
                label="방금 올린 드라이브 파일 휴지통으로",
                handle_from=self._drive_write_handle,
                undo=self._undo_drive_write,
            ),
            "google_calendar_create": InverseSpec(
                label="방금 만든 일정 삭제",
                handle_from=self._calendar_create_handle,
                undo=self._undo_calendar_create,
            ),
        }

    def _dynamic_risks(self) -> dict[str, Any]:
        """호출마다 등급이 달라지는 도구들.

        ★ 이 함수들은 **등급을 올리기만 한다**(`tool_gateway.ToolSpec.effective_risk`).
        내릴 수 있게 만들면 그것이 곧 승인 우회로다.
        """
        return {"google_calendar_create": self._calendar_create_risk}

    def _calendar_create_risk(self, arguments: dict[str, Any]) -> RiskLevel:
        """이 일정이 **사용자 캘린더 밖으로 나가는가.**

        `google_calendar_create` 를 L1 으로 내리자는 이야기가 나오는 근거는 하나다 —
        되돌리기가 실제로 돈다(`event_id` 하나로 지우는 순수 API). 그런데 그 전제는
        **참석자가 붙는 순간 깨진다:**

          send_updates="all"  초대 메일이 실제로 나간다. 일정을 지워도 **나간 메일은
                              못 되돌린다.**
          attendees 있음      메일을 안 보내도 남의 캘린더에 그 일정이 뜬다. 지우는
                              것으로 "아무 일도 없던 것"이 되지 않는다.

        그래서 밖으로 나가는 일정은 등급이 내려가도 **사람 앞에 선다.** 오늘까지
        커밋된 캘린더 일정 3건이 전부 `attendees=[]` 라, 이 경로는 라이브에서 한
        번도 밟힌 적이 없다 — 처음 밟을 때 승인 없이 밟게 두지 않는다.

        인자에는 `action_id` 밖에 없다. 무엇을 만드는지는 준비 단계의 payload 에
        있으므로 거기까지 가서 본다. 못 찾으면 **모르는 것이고, 모르면 사람 앞에
        세운다** — 등급 판단이 실패했을 때 `effective_risk` 가 하는 것과 같다.
        """
        action_id = str(arguments.get("action_id") or "")
        if not action_id:
            return RiskLevel.L2
        action = self.actions.get_prepared_action(action_id)
        if action is None:
            return RiskLevel.L2
        payload = action.get("payload") or {}
        if payload.get("attendees"):
            return RiskLevel.L2
        if str(payload.get("send_updates") or "none") != "none":
            return RiskLevel.L2
        # 나 혼자 보는 일정. 지우면 정말로 없던 일이 된다.
        return RiskLevel.L1

    @staticmethod
    def _calendar_create_handle(result: dict[str, Any]) -> dict[str, Any] | None:
        event_id = str(result.get("event_id") or "")
        if not event_id:
            # 무엇을 지워야 할지 모른다. 되돌리기를 내주지 않는 편이 낫다 —
            # 눌렀는데 아무 일도 안 일어나는 버튼이 제일 나쁘다.
            return None
        return {
            "event_id": event_id,
            "calendar_id": str(result.get("calendar_id") or "primary"),
            "summary": str(result.get("summary") or ""),
        }

    def _undo_calendar_create(self, handle: dict[str, Any]) -> dict[str, Any]:
        calendar_id = str(handle.get("calendar_id") or "primary")
        event_id = str(handle["event_id"])
        url = (
            f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}"
            f"/events/{quote(event_id, safe='')}?{urlencode({'sendUpdates': 'none'})}"
        )
        self._delete(url)
        return {"action": "undo_calendar_create", "event_id": event_id, "deleted": True}

    def _is_configured(self) -> bool:
        return oauth_client_present(self.config)

    def _credentials(self) -> dict[str, str]:
        return resolve_oauth_client(self.config)

    @staticmethod
    def _token_form(credentials: dict[str, str], **values: str) -> dict[str, str]:
        form = {"client_id": credentials["client_id"], **values}
        if credentials.get("client_secret"):
            form["client_secret"] = credentials["client_secret"]
        return form

    def status(self, *, verify: bool = False) -> dict[str, Any]:
        configured = False
        project_id = ""
        credential_source = ""
        try:
            credentials = self._credentials()
            configured = bool(credentials["client_id"])
            project_id = credentials.get("project_id", "")
            credential_source = credentials.get("source", "")
        except Exception:
            pass
        connected = self.vault.exists()
        profile = dict(self._profile)
        granted_scopes: list[str] = []
        scope_mismatch = False
        if verify and connected:
            try:
                profile = self.profile()
            except Exception as exc:
                self._last_error = str(exc)[:300]
            if self.config.google_write_enabled:
                try:
                    granted_scopes = self._granted_scopes()
                    scope_mismatch = not set(_WRITE_SCOPES).issubset(set(granted_scopes))
                except Exception:
                    pass
        with self._lock:
            pending = bool(self._flow and not self._flow.get("completed"))
            error = self._last_error
            started_at = float(self._flow.get("started_at") or 0)
        return {
            "enabled": self.config.google_enabled,
            "configured": configured,
            "connected": connected,
            "pending": pending,
            "pending_expires_at": (
                started_at + self.config.google_oauth_timeout_sec if pending else 0
            ),
            "project_id": project_id,
            "credential_source": credential_source,
            "email": str(profile.get("email") or ""),
            "name": str(profile.get("name") or ""),
            "scopes": list(self._requested_scopes()),
            "mode": "read_write" if self.config.google_write_enabled else "read_only",
            "granted_scopes": granted_scopes,
            "scope_mismatch": scope_mismatch,
            "restricted_scopes": self._restricted_enabled(),
            "picked_files": len(self.picked_files()),
            "last_error": error,
        }

    def _granted_scopes(self) -> list[str]:
        """Only called from the existing verify=True opt-in status path."""
        token = self._access_token()
        with httpx.Client(timeout=15.0, transport=self._transport) as client:
            response = client.get(
                "https://oauth2.googleapis.com/tokeninfo", params={"access_token": token}
            )
            response.raise_for_status()
            value = response.json()
        return str(value.get("scope") or "").split()

    def start_oauth(self, *, picker: bool = False) -> dict[str, Any]:
        if not self.config.google_enabled:
            raise RuntimeError("google_workspace_disabled")
        credentials = self._credentials()
        with self._lock:
            active_url = str(self._flow.get("authorization_url") or "")
            active_started = float(self._flow.get("started_at") or 0)
            active = bool(
                self._server is not None
                and active_url
                and not self._flow.get("completed")
                and bool(self._flow.get("picker")) == picker
                and time.time() - active_started < self.config.google_oauth_timeout_sec
            )
        if active:
            opened = webbrowser.open(active_url, new=1, autoraise=True)
            return {
                "ok": True,
                "reused": True,
                "opened_browser": bool(opened),
                "authorization_url": active_url,
                "expires_in_sec": max(
                    1,
                    int(
                        self.config.google_oauth_timeout_sec
                        - (time.time() - active_started)
                    ),
                ),
            }
        with self._lock:
            if self._server is not None:
                try:
                    self._server.shutdown()
                    self._server.server_close()
                except Exception:
                    pass
                self._server = None

            verifier = secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest()
            ).rstrip(b"=").decode("ascii")
            state = secrets.token_urlsafe(32)
            service = self

            class CallbackHandler(BaseHTTPRequestHandler):
                def do_GET(self) -> None:  # noqa: N802
                    result = service._oauth_callback(self.path)
                    ok = bool(result.get("ok"))
                    title = "Google 연결 완료" if ok else "Google 연결 실패"
                    detail = html.escape(
                        "이 창을 닫고 손자리로 돌아가세요."
                        if ok
                        else str(result.get("error") or "다시 시도해 주세요.")
                    )
                    body = (
                        "<!doctype html><html lang='ko'><meta charset='utf-8'>"
                        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                        "<title>Sonjari</title>"
                        "<body style='margin:0;background:#0b1020;color:#eef2ff;font-family:system-ui;display:grid;place-items:center;height:100vh'>"
                        f"<main style='max-width:560px;padding:42px;border:1px solid #55448b;border-radius:28px;background:#141a2c'><h1>{title}</h1><p>{detail}</p></main>"
                        "</body></html>"
                    ).encode("utf-8")
                    self.send_response(200 if ok else 400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, format: str, *args: Any) -> None:
                    del format, args

            server = ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
            port = int(server.server_address[1])
            redirect_uri = f"http://127.0.0.1:{port}/oauth2/callback"
            self._flow = {
                "state": state,
                "verifier": verifier,
                "redirect_uri": redirect_uri,
                "started_at": time.time(),
                "completed": False,
                "picker": picker,
            }
            self._last_error = ""
            self._server = server
            thread = threading.Thread(target=server.serve_forever, name="jarvis-google-oauth", daemon=True)
            thread.start()
            threading.Thread(
                target=self._expire_flow,
                args=(state,),
                name="jarvis-google-oauth-timeout",
                daemon=True,
            ).start()

        params = {
            "client_id": credentials["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._requested_scopes()),
            "access_type": "offline",
            "prompt": "select_account consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if picker:
            # Picker 는 `drive.file` 단독 · `prompt=consent` · `trigger_onepick=true` 가 필수(공식 문서).
            params.update({"scope": DRIVE_FILE_SCOPE, "prompt": "consent", "trigger_onepick": "true",
                           "allow_multiple": "true"})
        query = urlencode(params)
        authorization_url = f"{self.AUTH_URI}?{query}"
        with self._lock:
            if str(self._flow.get("state") or "") == state:
                self._flow["authorization_url"] = authorization_url
        opened = webbrowser.open(authorization_url, new=1, autoraise=True)
        self.events.publish("google_oauth_started", {"opened_browser": bool(opened), "picker": picker})
        return {
            "ok": True,
            "opened_browser": bool(opened),
            "authorization_url": authorization_url,
            "expires_in_sec": self.config.google_oauth_timeout_sec,
        }

    def _expire_flow(self, state: str) -> None:
        time.sleep(max(30, self.config.google_oauth_timeout_sec))
        with self._lock:
            if str(self._flow.get("state") or "") != state or self._flow.get("completed"):
                return
        self._finish_flow(False, "oauth_timeout")

    def _oauth_callback(self, raw_path: str) -> dict[str, Any]:
        query = parse_qs(urlparse(raw_path).query)
        with self._lock:
            flow = dict(self._flow)
        if not flow:
            return {"ok": False, "error": "oauth_flow_not_started"}
        if str(query.get("state", [""])[0]) != str(flow.get("state") or ""):
            return {"ok": False, "error": "oauth_state_mismatch"}
        if query.get("error"):
            error = str(query["error"][0])[:200]
            self._finish_flow(False, error)
            return {"ok": False, "error": error}
        code = str(query.get("code", [""])[0])
        if not code:
            self._finish_flow(False, "oauth_code_missing")
            return {"ok": False, "error": "oauth_code_missing"}
        try:
            credentials = self._credentials()
            with httpx.Client(timeout=30.0, transport=self._transport) as client:
                response = client.post(
                    self.TOKEN_URI,
                    data=self._token_form(
                        credentials,
                        code=code,
                        code_verifier=str(flow["verifier"]),
                        grant_type="authorization_code",
                        redirect_uri=str(flow["redirect_uri"]),
                    ),
                )
                response.raise_for_status()
                token = response.json()
            token["expires_at"] = time.time() + int(token.get("expires_in") or 3600)
            token["saved_at"] = time.time()
            if flow.get("picker"):
                picked = [part for part in str(query.get("picked_file_ids", [""])[0]).split(",") if part.strip()]
                self._remember_picked(picked)
                # 고른 파일 권한은 **앱(클라이언트)** 에 붙는다 — 이미 이어 둔 토큰이 있으면 그것을 그대로 쓰고,
                # 처음이면 이 `drive.file` 토큰이 연결이 된다. ★ 회사 프로젝트로 실제 확인 전(인수인계 H4 잴 것).
                if not self.vault.exists():
                    token["scopes_requested"] = [DRIVE_FILE_SCOPE]
                    self.vault.save(token)
                self._finish_flow(True, "")
                self.events.publish("google_drive_picked", {"count": len(picked)})
                return {"ok": True, "picked": len(picked)}
            token["scopes_requested"] = list(self._requested_scopes())
            self.vault.save(token)
            try:
                self._profile = self.profile()
            except Exception:
                self._profile = {}
            self._finish_flow(True, "")
            self.events.publish(
                "google_oauth_connected",
                {"email": str(self._profile.get("email") or ""), "mode": "read_only"},
            )
            return {"ok": True}
        except Exception as exc:
            error = f"oauth_exchange_failed:{str(exc)[:220]}"
            self._finish_flow(False, error)
            return {"ok": False, "error": error}

    def _finish_flow(self, ok: bool, error: str) -> None:
        with self._lock:
            self._flow["completed"] = True
            self._flow["ok"] = ok
            self._last_error = error
            server = self._server
            self._server = None
        if server is not None:
            def stop_server() -> None:
                time.sleep(0.2)
                server.shutdown()
                server.server_close()

            threading.Thread(target=stop_server, name="jarvis-google-oauth-stop", daemon=True).start()

    def _access_token(self) -> str:
        if not self.vault.exists():
            raise RuntimeError("google_not_connected")
        token = self.vault.load()
        self._tell_secrets(token)
        if str(token.get("access_token") or "") and float(token.get("expires_at") or 0) > time.time() + 90:
            return str(token["access_token"])
        refresh_token = str(token.get("refresh_token") or "")
        if not refresh_token:
            raise RuntimeError("google_refresh_token_missing_reconnect_required")
        credentials = self._credentials()
        with httpx.Client(timeout=30.0, transport=self._transport) as client:
            response = client.post(
                self.TOKEN_URI,
                data=self._token_form(
                    credentials,
                    refresh_token=refresh_token,
                    grant_type="refresh_token",
                ),
            )
            response.raise_for_status()
            refreshed = response.json()
        token.update(refreshed)
        token["refresh_token"] = refresh_token
        token["expires_at"] = time.time() + int(refreshed.get("expires_in") or 3600)
        token["saved_at"] = time.time()
        self.vault.save(token)
        self._tell_secrets(token)
        return str(token["access_token"])

    def _tell_secrets(self, token: dict[str, Any]) -> None:
        """꺼내 쓴 토큰 값을 「아는 비밀」에 알린다 — 오류 글 같은 데 찍혀 도구 결과로 나가면 가려지게. 실패해도 아무 일 없다."""
        sink = getattr(self, "secret_sink", None)
        if sink is None:
            return
        for name in ("access_token", "refresh_token", "id_token"):
            try:
                sink(str(token.get(name) or ""), "구글 토큰")
            except Exception:  # noqa: BLE001
                pass

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        with httpx.Client(timeout=30.0, transport=self._transport) as client:
            response = client.get(url, params=params, headers=headers)
            if response.status_code == 401:
                token = self.vault.load()
                token["expires_at"] = 0
                self.vault.save(token)
                headers = {"Authorization": f"Bearer {self._access_token()}"}
                response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError("google_api_invalid_response")
        return value

    def _post(self, url: str, json_body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        with httpx.Client(timeout=30.0, transport=self._transport) as client:
            response = client.post(url, json=json_body, headers=headers)
            if response.status_code == 401:
                token = self.vault.load()
                token["expires_at"] = 0
                self.vault.save(token)
                headers = {"Authorization": f"Bearer {self._access_token()}"}
                response = client.post(url, json=json_body, headers=headers)
            if response.status_code == 403:
                raise GoogleScopeInsufficientError("google_scope_insufficient_reconnect_required")
            response.raise_for_status()
            value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError("google_api_invalid_response")
        return value

    def _patch(self, url: str, json_body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        with httpx.Client(timeout=30.0, transport=self._transport) as client:
            response = client.patch(url, json=json_body, headers=headers)
            if response.status_code == 401:
                token = self.vault.load()
                token["expires_at"] = 0
                self.vault.save(token)
                headers = {"Authorization": f"Bearer {self._access_token()}"}
                response = client.patch(url, json=json_body, headers=headers)
            if response.status_code == 403:
                raise GoogleScopeInsufficientError("google_scope_insufficient_reconnect_required")
            response.raise_for_status()
            value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError("google_api_invalid_response")
        return value

    def _upload(
        self,
        url: str,
        *,
        method: str,
        metadata: dict[str, Any],
        body: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        """드라이브 **멀티파트 업로드**. `_post` 는 JSON 전용이라 못 쓴다.

        메타데이터(JSON)와 본문(파일)을 한 요청에 같이 올린다. 경계 문자열은
        본문에 절대 안 나올 값으로 뽑는다 — 겹치면 구글이 본문을 잘못 자른다.
        """
        boundary = f"jarvis{uuid.uuid4().hex}"
        head = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            + json.dumps(metadata, ensure_ascii=False)
            + f"\r\n--{boundary}\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        payload = head + body + f"\r\n--{boundary}--\r\n".encode("ascii")
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        }
        with httpx.Client(timeout=120.0, transport=self._transport) as client:
            response = client.request(method, url, content=payload, headers=headers)
            if response.status_code == 401:
                token = self.vault.load()
                token["expires_at"] = 0
                self.vault.save(token)
                headers["Authorization"] = f"Bearer {self._access_token()}"
                response = client.request(method, url, content=payload, headers=headers)
            if response.status_code == 403:
                # 예전 토큰은 `drive.file` 이 없다. 이 말이 화면까지 그대로 올라간다.
                raise GoogleScopeInsufficientError("google_scope_insufficient_reconnect_required")
            response.raise_for_status()
            value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError("google_api_invalid_response")
        return value

    def _delete(self, url: str) -> None:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        with httpx.Client(timeout=30.0, transport=self._transport) as client:
            response = client.delete(url, headers=headers)
            if response.status_code == 401:
                token = self.vault.load()
                token["expires_at"] = 0
                self.vault.save(token)
                headers = {"Authorization": f"Bearer {self._access_token()}"}
                response = client.delete(url, headers=headers)
            if response.status_code == 403:
                raise GoogleScopeInsufficientError("google_scope_insufficient_reconnect_required")
            if response.status_code not in (200, 204):
                response.raise_for_status()

    def profile(self) -> dict[str, Any]:
        value = self._get("https://openidconnect.googleapis.com/v1/userinfo")
        self._profile = {
            "email": str(value.get("email") or ""),
            "name": str(value.get("name") or ""),
            "picture": str(value.get("picture") or ""),
        }
        return dict(self._profile)

    @staticmethod
    def _limit(arguments: dict[str, Any], default: int, maximum: int) -> int:
        return max(1, min(int(arguments.get("max_results") or default), maximum))

    def drive_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        maximum = self._limit(arguments, 10, 20)
        filters = ["trashed = false"]
        if query:
            escaped = query.replace("\\", "\\\\").replace("'", "\\'")
            filters.append(f"(name contains '{escaped}' or fullText contains '{escaped}')")
        value = self._get(
            "https://www.googleapis.com/drive/v3/files",
            {
                "q": " and ".join(filters),
                "pageSize": maximum,
                "orderBy": "modifiedTime desc",
                "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink,owners(displayName,emailAddress)),incompleteSearch",
            },
        )
        files = []
        for item in value.get("files") or []:
            owners = item.get("owners") or []
            files.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "mime_type": item.get("mimeType"),
                    "modified_time": item.get("modifiedTime"),
                    "size": item.get("size"),
                    "url": item.get("webViewLink"),
                    "owner": (owners[0].get("displayName") if owners else ""),
                }
            )
        result = {"action": "google_drive_search", "query": query, "count": len(files), "files": files, "read_only": True}
        if not self._restricted_enabled():
            # 권한이 곧 거름망이다 — 0건이 「없다」가 아니라 「못 본다」일 수 있다는 것을 말한다(빈 값이 두 뜻인 고장).
            result["scope_note"] = (
                "이 설치는 드라이브 전체가 아니라 사용자가 고른 파일과 손자리가 만든 파일만 봅니다. 찾는 파일이 없으면 "
                "사용자에게 손자리 설정의 「드라이브에서 파일 고르기」로 골라 달라고 하세요."
            )
        return result

    # 구글 문서(Docs·Sheets·Slides)는 파일이 아니라 서비스라 내려받기가 아니라
    # **내보내기**로 읽는다. 여기 없는 형식은 못 읽는 것이고, 그럼 못 읽는다고 말한다.
    _DRIVE_EXPORT = {
        "application/vnd.google-apps.document": "text/plain",
        "application/vnd.google-apps.presentation": "text/plain",
        "application/vnd.google-apps.spreadsheet": "text/csv",
        "application/vnd.google-apps.script": "application/vnd.google-apps.script+json",
    }

    def drive_read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """드라이브 문서의 **본문**을 가져온다.

        ★ 왜 만들었나 (2026-08-12 실측). 검색 도구는 있는데 읽는 도구가 없었다.
        그래서 자비스는 이력서를 읽으라는 말에 ① 로컬 파일 도구로 열려다 실패하고
        ② 브라우저로 docs.google.com 을 열었다가 **구글 로그인 화면**을 만났다.
        자비스 크롬은 구글에 로그인돼 있지 않기 때문이다. 결국 이력서 0줄로 끝났다.

        이건 브라우저로 풀 문제가 아니었다. `drive.readonly` 권한이 이미 있으므로
        API 로 가져오면 로그인 자체가 필요 없다. **연장이 없어서 못 한 일을
        모델 탓으로 읽으면 안 된다** — 후보에 정답이 없으면 무엇을 골라도 틀린다.
        """
        file_id = str(arguments.get("file_id") or "").strip()
        name = str(arguments.get("name") or "").strip()
        limit = max(500, min(int(arguments.get("max_chars") or 20000), 60000))

        if not file_id and not name:
            raise ValueError("file_id_or_name_required")
        if not file_id:
            found = self.drive_search({"query": name, "max_results": 10})
            matches = [
                item for item in found["files"]
                if str(item.get("name") or "").strip().lower() == name.lower()
            ] or found["files"]
            if not matches:
                raise RuntimeError(f"drive_file_not_found:{name}")
            if len(matches) > 1:
                # 비슷한 것을 골라 읽고 그게 맞다고 말하는 것이 제일 나쁘다.
                return {
                    "action": "google_drive_read",
                    "read": False,
                    "reason": "여러 파일이 이름에 맞습니다. 어느 것인지 file_id 로 다시 부르세요.",
                    "candidates": matches[:10],
                }
            file_id = str(matches[0].get("id") or "")

        meta = self._get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            {"fields": "id,name,mimeType,modifiedTime,size,webViewLink"},
        )
        mime = str(meta.get("mimeType") or "")
        export_as = self._DRIVE_EXPORT.get(mime)
        if export_as:
            text = self._get_text(
                f"https://www.googleapis.com/drive/v3/files/{file_id}/export",
                {"mimeType": export_as},
            )
        elif mime.startswith("text/") or mime in {
            "application/json", "application/xml", "application/rtf",
        }:
            text = self._get_text(
                f"https://www.googleapis.com/drive/v3/files/{file_id}", {"alt": "media"}
            )
        else:
            # 못 읽는 형식을 빈 본문으로 돌려주면 "내용이 없는 문서"로 읽힌다.
            raise RuntimeError(
                f"drive_unsupported_type:{mime} — 이 형식은 아직 못 읽습니다."
                " 구글 문서로 열어 저장하거나, 파일을 PC 에 내려받아 local_read_document 로 읽으세요."
            )

        body = text.replace("\r\n", "\n").strip()
        truncated = len(body) > limit
        return {
            "action": "google_drive_read",
            "read": True,
            "file_id": file_id,
            "name": meta.get("name"),
            "mime_type": mime,
            "modified_time": meta.get("modifiedTime"),
            "url": meta.get("webViewLink"),
            "chars": len(body),
            "truncated": truncated,
            "text": body[:limit],
            "read_only": True,
        }

    def _get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        """본문을 **글자 그대로** 받아 온다(`_get` 은 JSON 전용이다)."""
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        with httpx.Client(timeout=60.0, transport=self._transport) as client:
            response = client.get(url, params=params, headers=headers)
            if response.status_code == 401:
                token = self.vault.load()
                token["expires_at"] = 0
                self.vault.save(token)
                headers = {"Authorization": f"Bearer {self._access_token()}"}
                response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.text

    def gmail_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not self._restricted_enabled():
            # 공개판은 지메일 읽기 권한(제한 권한)을 요청하지 않는다(인수인계 H4). 실패로 끝내면 모델이 지어낸다 —
            # 갈 길을 말한다.
            return {
                "action": "google_gmail_search",
                "query": query,
                "available": False,
                "reason": "gmail_read_not_granted",
                "next": (
                    "이 설치는 지메일 읽기 권한을 쓰지 않습니다. 사용자의 크롬에서 browser_open 으로 "
                    "https://mail.google.com/mail/u/0/#search/" + quote(query) + " 을 열어 읽으세요. "
                    "로그인 화면이 나오면 사용자에게 로그인을 부탁하세요."
                ),
            }
        maximum = self._limit(arguments, 5, 10)
        listed = self._get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            {"q": query, "maxResults": maximum},
        )
        messages = []
        for row in listed.get("messages") or []:
            message_id = str(row.get("id") or "")
            if not message_id:
                continue
            detail = self._get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                {
                    "format": "metadata",
                    "metadataHeaders": ["Subject", "From", "Date", "To"],
                },
            )
            headers = {
                str(item.get("name") or "").lower(): str(item.get("value") or "")
                for item in (detail.get("payload") or {}).get("headers") or []
            }
            messages.append(
                {
                    "id": message_id,
                    "thread_id": detail.get("threadId"),
                    "subject": headers.get("subject", "(제목 없음)"),
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "date": headers.get("date", ""),
                    "snippet": str(detail.get("snippet") or "")[:500],
                    "labels": detail.get("labelIds") or [],
                }
            )
        return {"action": "google_gmail_search", "query": query, "count": len(messages), "messages": messages, "read_only": True}

    def _list_events(
        self,
        calendar_id: str,
        time_min: str,
        time_max: str,
        *,
        query: str = "",
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max_results,
        }
        if query:
            params["q"] = query
        value = self._get(
            f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events",
            params,
        )
        events = []
        for item in value.get("items") or []:
            events.append(
                {
                    "id": item.get("id"),
                    "summary": item.get("summary") or "(제목 없음)",
                    "start": (item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date"),
                    "end": (item.get("end") or {}).get("dateTime") or (item.get("end") or {}).get("date"),
                    "location": item.get("location") or "",
                    "status": item.get("status") or "",
                    "url": item.get("htmlLink") or "",
                }
            )
        return events

    def calendar_upcoming(self, arguments: dict[str, Any]) -> dict[str, Any]:
        days = max(1, min(int(arguments.get("days") or 14), 90))
        maximum = self._limit(arguments, 10, 20)
        query = str(arguments.get("query") or "").strip()
        now = datetime.now(timezone.utc)
        time_max = datetime.fromtimestamp(now.timestamp() + days * 86400, timezone.utc)
        events = self._list_events(
            "primary",
            now.isoformat().replace("+00:00", "Z"),
            time_max.isoformat().replace("+00:00", "Z"),
            query=query,
            max_results=maximum,
        )
        return {"action": "google_calendar_upcoming", "days": days, "query": query, "count": len(events), "events": events, "read_only": True}

    def _get_event(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        return self._get(
            f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}"
            f"/events/{quote(event_id, safe='')}"
        )

    def _find_conflicts(
        self,
        calendar_id: str,
        start: dict[str, str],
        end: dict[str, str],
        *,
        exclude_event_id: str = "",
    ) -> list[dict[str, Any]]:
        time_min = start.get("dateTime") or f"{start.get('date')}T00:00:00Z"
        time_max = end.get("dateTime") or f"{end.get('date')}T23:59:59Z"
        candidates = self._list_events(calendar_id, time_min, time_max, max_results=10)
        return [event for event in candidates if event["id"] != exclude_event_id]

    # ---- Gmail send: prepare (L1, no side effects) -> commit (L2) ----

    @staticmethod
    def _normalize_recipients(raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            raw = [raw]
        normalized: list[str] = []
        seen_lower: set[str] = set()
        for item in raw:
            address = str(item or "").strip()
            if not address:
                continue
            if _HEADER_INJECTION_RE.search(address):
                raise ValueError("gmail_recipient_header_injection_blocked")
            if not _EMAIL_RE.match(address):
                raise ValueError(f"gmail_invalid_email_address:{address}")
            lowered = address.lower()
            if lowered not in seen_lower:
                seen_lower.add(lowered)
                normalized.append(address)
        return normalized

    def gmail_prepare_send(self, arguments: dict[str, Any]) -> dict[str, Any]:
        to = self._normalize_recipients(arguments.get("to"))
        cc = self._normalize_recipients(arguments.get("cc"))
        bcc = self._normalize_recipients(arguments.get("bcc"))
        if not to:
            raise ValueError("gmail_recipient_required")

        subject = str(arguments.get("subject") or "").strip()
        if _HEADER_INJECTION_RE.search(subject):
            raise ValueError("gmail_subject_header_injection_blocked")
        if len(subject) > 300:
            raise ValueError("gmail_subject_too_long")

        body_text = str(arguments.get("body_text") or "")[:40_000]
        body_html_raw = arguments.get("body_html")
        body_html = str(body_html_raw)[:80_000] if body_html_raw else ""

        max_count = self.config.gmail_attachment_max_count
        max_bytes = self.config.gmail_attachment_max_bytes
        raw_attachments = list(arguments.get("attachments") or [])
        if len(raw_attachments) > max_count:
            raise ValueError("gmail_attachment_count_exceeded")
        attachments: list[dict[str, Any]] = []
        total_bytes = 0
        for raw_path in raw_attachments:
            path = self.local_computer.resolve_export_path(str(raw_path))
            if not path.is_file():
                raise ValueError(f"gmail_attachment_not_a_file:{path.name}")
            size = path.stat().st_size
            if size > max_bytes:
                raise ValueError(f"gmail_attachment_too_large:{path.name}")
            total_bytes += size
            if total_bytes > max_bytes * max_count:
                raise ValueError("gmail_attachments_total_too_large")
            attachments.append({"path": str(path), "name": path.name, "size": size})

        payload = {
            "to": to,
            "cc": cc,
            "bcc": bcc,
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "attachments": attachments,
        }
        preview = {
            "to": to,
            "cc": cc,
            "bcc": bcc,
            "subject": subject,
            "body_preview": body_text[:500] or "(본문 없음)",
            "html": bool(body_html),
            "attachments": [{"name": item["name"], "size": item["size"]} for item in attachments],
        }
        action = self.actions.create_prepared_action(
            kind="gmail_send",
            payload=payload,
            preview=preview,
            ttl_sec=self.config.external_action_ttl_sec,
        )
        return {
            "action": "google_gmail_prepare_send",
            "action_id": action["action_id"],
            "preview": preview,
            "expires_at": action["expires_at"],
            "requires_approval": True,
        }

    @staticmethod
    def _build_gmail_mime(payload: dict[str, Any]) -> bytes:
        body_html = str(payload.get("body_html") or "")
        body_text = str(payload.get("body_text") or "")
        attachments = payload.get("attachments") or []
        if body_html or attachments:
            message: Any = MIMEMultipart("mixed")
            text_part = MIMEText(body_text, "plain", "utf-8")
            if body_html:
                alternative = MIMEMultipart("alternative")
                alternative.attach(text_part)
                alternative.attach(MIMEText(body_html, "html", "utf-8"))
                message.attach(alternative)
            else:
                message.attach(text_part)
            for item in attachments:
                path = Path(str(item["path"]))
                guessed, _ = mimetypes.guess_type(path.name)
                _, _, sub_type = (guessed or "application/octet-stream").partition("/")
                part = MIMEApplication(path.read_bytes(), _subtype=sub_type or "octet-stream")
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=str(Header(path.name, "utf-8")),
                )
                message.attach(part)
        else:
            message = MIMEText(body_text, "plain", "utf-8")
        message["To"] = ", ".join(payload["to"])
        if payload.get("cc"):
            message["Cc"] = ", ".join(payload["cc"])
        if payload.get("bcc"):
            message["Bcc"] = ", ".join(payload["bcc"])
        message["Subject"] = str(Header(payload["subject"], "utf-8"))
        return message.as_bytes()

    def gmail_send(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action_id = str(arguments.get("action_id") or "")
        if not action_id:
            raise ValueError("action_id_required")
        action = self.actions.claim_for_commit(action_id)
        if action is None:
            raise RuntimeError("external_action_not_found_or_expired")
        if action["kind"] != "gmail_send":
            raise RuntimeError("external_action_kind_mismatch")
        if action["status"] in SETTLED_STATUSES:
            cached = dict(action["result"] or {})
            return {"action": "google_gmail_send", "action_id": action_id, "duplicate_commit": True, **cached}
        if not action["claimed"]:
            raise RuntimeError(f"external_action_not_claimable:{action['status']}")

        payload = action["payload"]
        raw = base64.urlsafe_b64encode(self._build_gmail_mime(payload)).decode("ascii")
        try:
            response = self._post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                {"raw": raw},
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self.actions.mark_unknown(action_id, str(exc)[:500])
            raise RuntimeError("gmail_send_unknown_outcome_check_sent_mail_before_retrying") from exc
        except Exception as exc:
            self.actions.mark_failed(action_id, str(exc)[:500])
            raise

        result = {
            "message_id": response.get("id"),
            "thread_id": response.get("threadId"),
            "to": payload["to"],
            "subject": payload["subject"],
        }
        self.actions.mark_committed(action_id, result)
        return {"action": "google_gmail_send", "action_id": action_id, **result}

    # ---- Drive write: prepare (L1, no side effects) -> commit (L2) ----
    #
    # ★ 왜 만들었나 (2026-09-01). 읽기만 있어서 **폐루프가 안 닫혔다.** 자비스는
    #   사용자 드라이브를 읽고, 고친 결과를 이 PC 어딘가에 새 파일로 뱉을 뿐이었다.
    #   「드라이브 이력서 다듬어 놔」가 원천적으로 불가능했다.
    #
    #   권한은 `drive.file` 이다 — 자비스가 만든 파일만 건드린다. 그래서 이 도구는
    #   **원본을 덮어쓰지 않는다.** 수정본을 옆에 만든다. 그게 옳은 모양이기도 하다:
    #   이력서 원본을 조용히 덮어쓰는 비서는 아무도 원하지 않는다.

    #: 드라이브에 올릴 수 있는 것. 구글 문서로 변환할지 파일 그대로 둘지도 여기서 갈린다.
    _DRIVE_UPLOAD_TYPES: dict[str, tuple[str, str]] = {
        # 확장자: (올릴 때의 Content-Type, 변환 목표 mimeType 또는 "")
        ".txt": ("text/plain", "application/vnd.google-apps.document"),
        ".md": ("text/plain", "application/vnd.google-apps.document"),
        ".csv": ("text/csv", "application/vnd.google-apps.spreadsheet"),
        ".docx": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.google-apps.document",
        ),
        ".xlsx": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.google-apps.spreadsheet",
        ),
        ".pptx": (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.google-apps.presentation",
        ),
        ".pdf": ("application/pdf", ""),
        ".hwpx": ("application/octet-stream", ""),
        ".hwp": ("application/octet-stream", ""),
    }

    def drive_prepare_write(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """드라이브에 올릴 것을 **검증만** 한다. 아직 아무것도 안 올라간다."""
        name = str(arguments.get("name") or "").strip()
        source_raw = str(arguments.get("source_path") or "").strip()
        text = arguments.get("text")
        convert = bool(arguments.get("convert", True))
        folder_id = str(arguments.get("folder_id") or "").strip()

        if source_raw and text is not None:
            raise ValueError("drive_write_source_path_or_text_not_both")
        if not source_raw and text is None:
            raise ValueError("drive_write_source_path_or_text_required")

        if source_raw:
            path = self.local_computer.resolve_export_path(source_raw)
            if not path.is_file():
                raise ValueError(f"drive_write_not_a_file:{path.name}")
            size = path.stat().st_size
            limit = int(getattr(self.config, "drive_upload_max_bytes", 25_000_000))
            if size > limit:
                raise ValueError(f"drive_write_too_large:{size}")
            suffix = path.suffix.lower()
            if suffix not in self._DRIVE_UPLOAD_TYPES:
                raise ValueError(f"drive_write_unsupported_type:{suffix or '(확장자 없음)'}")
            name = name or path.name
            preview_body = preview_of_file(path, chars=400)
            payload_source = str(path)
        else:
            body = str(text)
            if not body.strip():
                raise ValueError("drive_write_empty_text")
            if len(body) > 400_000:
                raise ValueError("drive_write_text_too_long")
            name = name or "손자리 문서"
            suffix = Path(name).suffix.lower() or ".txt"
            if suffix not in self._DRIVE_UPLOAD_TYPES:
                suffix = ".txt"
            size = len(body.encode("utf-8"))
            preview_body = body[:400]
            payload_source = ""

        content_type, convert_to = self._DRIVE_UPLOAD_TYPES[suffix]
        target_mime = convert_to if (convert and convert_to) else ""

        payload = {
            "name": name,
            "source_path": payload_source,
            "text": None if payload_source else str(text),
            "suffix": suffix,
            "content_type": content_type,
            "target_mime": target_mime,
            "folder_id": folder_id,
        }
        preview = {
            "무엇을": name,
            "어디에": "구글 드라이브" + (f" (폴더 {folder_id})" if folder_id else " (내 드라이브)"),
            "어떻게": "구글 문서로 변환해서" if target_mime else "파일 그대로",
            "크기": f"{size:,} 바이트",
            "내용 앞부분": preview_body or "(미리보기 없음)",
            # 덮어쓰기가 아니라는 것을 **승인 화면에서** 말한다.
            "원본": "건드리지 않습니다 — 새 파일로 올라갑니다",
        }
        action = self.actions.create_prepared_action(
            kind="drive_write",
            payload=payload,
            preview=preview,
            ttl_sec=self.config.external_action_ttl_sec,
        )
        return {
            "action": "google_drive_prepare_write",
            "action_id": action["action_id"],
            "preview": preview,
            "expires_at": action["expires_at"],
            "requires_approval": True,
        }

    def drive_write(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action_id = str(arguments.get("action_id") or "")
        if not action_id:
            raise ValueError("action_id_required")
        action = self.actions.claim_for_commit(action_id)
        if action is None:
            raise RuntimeError("external_action_not_found_or_expired")
        if action["kind"] != "drive_write":
            raise RuntimeError("external_action_kind_mismatch")
        if action["status"] in SETTLED_STATUSES:
            cached = dict(action["result"] or {})
            return {"action": "google_drive_write", "action_id": action_id, "duplicate_commit": True, **cached}
        if not action["claimed"]:
            raise RuntimeError(f"external_action_not_claimable:{action['status']}")

        payload = action["payload"]
        source_path = str(payload.get("source_path") or "")
        if source_path:
            body = Path(source_path).read_bytes()
        else:
            body = str(payload.get("text") or "").encode("utf-8")

        metadata: dict[str, Any] = {"name": payload["name"]}
        if payload.get("target_mime"):
            metadata["mimeType"] = payload["target_mime"]
        if payload.get("folder_id"):
            metadata["parents"] = [payload["folder_id"]]

        try:
            response = self._upload(
                "https://www.googleapis.com/upload/drive/v3/files"
                "?uploadType=multipart&fields=id,name,mimeType,webViewLink",
                method="POST",
                metadata=metadata,
                body=body,
                content_type=str(payload["content_type"]),
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # 올라갔는지 아닌지 모르는 상태. **모른다고 말한다** — 다시 눌러
            # 같은 파일이 둘이 되는 것보다 낫다.
            self.actions.mark_unknown(action_id, str(exc)[:500])
            raise RuntimeError("drive_write_unknown_outcome_check_drive_before_retrying") from exc
        except Exception as exc:
            self.actions.mark_failed(action_id, str(exc)[:500])
            raise

        result = {
            "file_id": response.get("id"),
            "name": response.get("name"),
            "mime_type": response.get("mimeType"),
            "url": response.get("webViewLink"),
        }
        self.actions.mark_committed(action_id, result)
        return {"action": "google_drive_write", "action_id": action_id, **result}

    def _drive_write_handle(self, result: dict[str, Any]) -> dict[str, Any] | None:
        file_id = str((result or {}).get("file_id") or "")
        return {"file_id": file_id} if file_id else None

    def _undo_drive_write(self, handle: dict[str, Any]) -> dict[str, Any]:
        """방금 올린 것을 **휴지통으로** 보낸다.

        영구 삭제가 아니다 — 되돌리기가 지우기가 되면 그건 되돌리기가 아니다.
        """
        file_id = str((handle or {}).get("file_id") or "")
        if not file_id:
            return {"verified": False, "error": "file_id_missing"}
        self._patch(
            f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=id,trashed",
            {"trashed": True},
        )
        meta = self._get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}", {"fields": "id,trashed"}
        )
        return {"file_id": file_id, "verified": bool(meta.get("trashed"))}

    # ---- Calendar write: prepare (L1, no side effects) -> commit (L2) ----

    def _parse_calendar_time(self, value: Any, *, all_day: bool) -> dict[str, str]:
        """Interpretation of natural language stays with the model (the tool
        schema's description tells it to already send RFC3339/Asia-Seoul).
        Python only validates/normalizes the structured value it receives."""
        text = str(value or "").strip()
        if not text:
            raise ValueError("calendar_time_required")
        if all_day:
            try:
                datetime.strptime(text, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(f"calendar_invalid_all_day_date:{text}") from exc
            return {"date": text}
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"calendar_invalid_datetime:{text}") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(self.config.calendar_default_timezone))
        return {"dateTime": parsed.isoformat(), "timeZone": self.config.calendar_default_timezone}

    @staticmethod
    def _validate_send_updates(value: Any) -> str:
        text = str(value or "none")
        if text not in {"none", "all"}:
            raise ValueError("calendar_send_updates_invalid")
        return text

    def _now(self) -> datetime:
        """The wall clock the calendar guard compares against.

        A method rather than a bare `datetime.now()` call so tests can pin it.
        The default zone is the calendar's, not the host's -- same reasoning as
        `clock.KST`: a machine that travels must not silently move "today".
        """
        return datetime.now(ZoneInfo(self.config.calendar_default_timezone))

    def _as_instant(self, slot: dict[str, str], *, end: bool) -> datetime:
        """One comparable instant for either shape `_parse_calendar_time` returns.

        All-day slots carry only a date. Google treats the all-day `end` as
        exclusive, so an event on a single day is start=D, end=D+1; comparing
        the bare dates would call that zero-length. Anchoring start at 00:00 and
        end at 00:00 of its own date keeps `end > start` true for exactly the
        spans Google considers non-empty.
        """
        zone = ZoneInfo(self.config.calendar_default_timezone)
        if "date" in slot:
            return datetime.strptime(slot["date"], "%Y-%m-%d").replace(tzinfo=zone)
        parsed = datetime.fromisoformat(slot["dateTime"])
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=zone)
        return parsed

    def _guard_calendar_window(
        self,
        start: dict[str, str],
        end: dict[str, str],
        *,
        allow_past: bool,
    ) -> dict[str, str]:
        """Refuse a window the caller cannot have meant, and say what today is.

        Written after 2026-08-20, when "내일 오후 3시" became
        `2025-05-21T15:00+09:00` -- a year and three months early -- and was
        created for real. The system prompt carried the correct date in labelled
        fields (`clock.now_line_ko`); the model used its own "today" anyway. The
        day-of-month 21 was right, so the arithmetic happened; only the year the
        arithmetic started from was invented.

        Nothing downstream could catch it: `google_calendar_upcoming` looks
        forward only, so the wrong-year event was invisible there, and the
        approval card was auto-approved by the bench without reading it.

        So the check lives here, in code, rather than in another sentence of
        prompt. `allow_past` is the deliberate door for the real minority case
        (writing down a meeting that already happened) -- it has to be asked for.

        Returns the clock fields to hand back to the caller, so a model that
        trips this reads today's date out of its own tool result.
        """
        now = self._now()
        today = {
            "today": now.strftime("%Y-%m-%d"),
            "now_kst": now.strftime("%Y-%m-%d %H:%M"),
            "timezone": self.config.calendar_default_timezone,
        }
        started = self._as_instant(start, end=False)
        ended = self._as_instant(end, end=True)

        if ended <= started:
            raise ValueError(
                f"calendar_end_not_after_start:start={started.isoformat()},end={ended.isoformat()}"
            )

        if not allow_past:
            # A few minutes of slack: "지금부터 회의" is legitimate, and the model
            # composes the timestamp a beat before the tool runs.
            floor = now - timedelta(minutes=self.config.calendar_past_grace_minutes)
            if started < floor:
                raise ValueError(
                    f"calendar_start_in_past:{started.isoformat()} "
                    f"(오늘은 {today['today']} · 지금 {today['now_kst']} "
                    f"{self.config.calendar_default_timezone}. "
                    "의도한 것이면 allow_past=true 를 넘겨라)"
                )
        return today

    def calendar_prepare_create(self, arguments: dict[str, Any]) -> dict[str, Any]:
        summary = str(arguments.get("summary") or "").strip()
        if not summary:
            raise ValueError("calendar_summary_required")
        all_day = bool(arguments.get("all_day"))
        start = self._parse_calendar_time(arguments.get("start"), all_day=all_day)
        end = self._parse_calendar_time(arguments.get("end"), all_day=all_day)
        calendar_id = str(arguments.get("calendar_id") or "primary")
        location = str(arguments.get("location") or "")[:500]
        description = str(arguments.get("description") or "")[:5000]
        attendees = self._normalize_recipients(arguments.get("attendees"))
        send_updates = self._validate_send_updates(arguments.get("send_updates"))
        clock_fields = self._guard_calendar_window(
            start, end, allow_past=bool(arguments.get("allow_past"))
        )

        conflicts = self._find_conflicts(calendar_id, start, end)

        payload = {
            "calendar_id": calendar_id,
            "summary": summary,
            "start": start,
            "end": end,
            "all_day": all_day,
            "location": location,
            "description": description,
            "attendees": attendees,
            "send_updates": send_updates,
        }
        preview = {
            "calendar_id": calendar_id,
            "summary": summary,
            "start": start,
            "end": end,
            "location": location,
            "attendees": attendees,
            "send_updates": send_updates,
            "conflicts": conflicts,
            # On the approval card so a human reads the event's date next to
            # today's, which is the one comparison that catches a wrong year.
            **clock_fields,
        }
        action = self.actions.create_prepared_action(
            kind="calendar_create",
            payload=payload,
            preview=preview,
            ttl_sec=self.config.external_action_ttl_sec,
        )
        return {
            "action": "google_calendar_prepare_create",
            "action_id": action["action_id"],
            "preview": preview,
            "expires_at": action["expires_at"],
            "requires_approval": True,
        }

    def calendar_create(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action_id = str(arguments.get("action_id") or "")
        if not action_id:
            raise ValueError("action_id_required")
        action = self.actions.claim_for_commit(action_id)
        if action is None:
            raise RuntimeError("external_action_not_found_or_expired")
        if action["kind"] != "calendar_create":
            raise RuntimeError("external_action_kind_mismatch")
        if action["status"] in SETTLED_STATUSES:
            cached = dict(action["result"] or {})
            return {"action": "google_calendar_create", "action_id": action_id, "duplicate_commit": True, **cached}
        if not action["claimed"]:
            raise RuntimeError(f"external_action_not_claimable:{action['status']}")

        payload = action["payload"]
        body: dict[str, Any] = {
            "summary": payload["summary"],
            "start": payload["start"],
            "end": payload["end"],
        }
        if payload.get("location"):
            body["location"] = payload["location"]
        if payload.get("description"):
            body["description"] = payload["description"]
        if payload.get("attendees"):
            body["attendees"] = [{"email": address} for address in payload["attendees"]]
        calendar_id = payload["calendar_id"]
        query = urlencode({"sendUpdates": payload.get("send_updates", "none")})
        url = (
            f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}"
            f"/events?{query}"
        )
        try:
            response = self._post(url, body)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self.actions.mark_unknown(action_id, str(exc)[:500])
            raise RuntimeError("calendar_create_unknown_outcome_check_calendar_before_retrying") from exc
        except Exception as exc:
            self.actions.mark_failed(action_id, str(exc)[:500])
            raise

        result = {
            "event_id": response.get("id"),
            "html_link": response.get("htmlLink"),
            "summary": payload["summary"],
        }
        self.actions.mark_committed(action_id, result)
        return {"action": "google_calendar_create", "action_id": action_id, **result}

    def calendar_prepare_update(self, arguments: dict[str, Any]) -> dict[str, Any]:
        calendar_id = str(arguments.get("calendar_id") or "primary")
        event_id = str(arguments.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("calendar_event_id_required")
        existing = self._get_event(calendar_id, event_id)
        all_day = (
            bool(arguments.get("all_day"))
            if "all_day" in arguments
            else "date" in (existing.get("start") or {})
        )

        diff: list[dict[str, Any]] = []
        changes: dict[str, Any] = {}

        if "summary" in arguments:
            new_summary = str(arguments["summary"] or "").strip()
            if new_summary and new_summary != existing.get("summary"):
                diff.append({"field": "summary", "before": existing.get("summary"), "after": new_summary})
                changes["summary"] = new_summary
        if "start" in arguments:
            new_start = self._parse_calendar_time(arguments["start"], all_day=all_day)
            if new_start != (existing.get("start") or {}):
                diff.append({"field": "start", "before": existing.get("start"), "after": new_start})
                changes["start"] = new_start
        if "end" in arguments:
            new_end = self._parse_calendar_time(arguments["end"], all_day=all_day)
            if new_end != (existing.get("end") or {}):
                diff.append({"field": "end", "before": existing.get("end"), "after": new_end})
                changes["end"] = new_end
        if "location" in arguments:
            new_location = str(arguments["location"] or "")[:500]
            if new_location != (existing.get("location") or ""):
                diff.append({"field": "location", "before": existing.get("location") or "", "after": new_location})
                changes["location"] = new_location
        if "description" in arguments:
            new_description = str(arguments["description"] or "")[:5000]
            if new_description != (existing.get("description") or ""):
                diff.append(
                    {"field": "description", "before": existing.get("description") or "", "after": new_description}
                )
                changes["description"] = new_description
        if "attendees" in arguments:
            new_attendees = self._normalize_recipients(arguments["attendees"])
            existing_attendees = sorted(str(item.get("email") or "") for item in existing.get("attendees") or [])
            if sorted(new_attendees) != existing_attendees:
                diff.append({"field": "attendees", "before": existing_attendees, "after": new_attendees})
                changes["attendees"] = [{"email": address} for address in new_attendees]

        if not changes:
            raise ValueError("calendar_update_no_changes")

        send_updates = self._validate_send_updates(arguments.get("send_updates"))

        conflicts: list[dict[str, Any]] = []
        clock_fields: dict[str, str] = {}
        if "start" in changes or "end" in changes:
            # Only when the window actually moves. Renaming a meeting that
            # already happened is ordinary and must not need `allow_past`.
            effective_start = changes.get("start", existing.get("start") or {})
            effective_end = changes.get("end", existing.get("end") or {})
            clock_fields = self._guard_calendar_window(
                effective_start,
                effective_end,
                allow_past=bool(arguments.get("allow_past")),
            )
            conflicts = self._find_conflicts(
                calendar_id,
                effective_start,
                effective_end,
                exclude_event_id=event_id,
            )

        payload = {
            "calendar_id": calendar_id,
            "event_id": event_id,
            "changes": changes,
            "send_updates": send_updates,
        }
        preview = {
            "calendar_id": calendar_id,
            "event_id": event_id,
            "summary": existing.get("summary") or "(제목 없음)",
            "diff": diff,
            "send_updates": send_updates,
            "conflicts": conflicts,
            **clock_fields,
        }
        action = self.actions.create_prepared_action(
            kind="calendar_update",
            payload=payload,
            preview=preview,
            ttl_sec=self.config.external_action_ttl_sec,
        )
        return {
            "action": "google_calendar_prepare_update",
            "action_id": action["action_id"],
            "preview": preview,
            "expires_at": action["expires_at"],
            "requires_approval": True,
        }

    def calendar_update(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action_id = str(arguments.get("action_id") or "")
        if not action_id:
            raise ValueError("action_id_required")
        action = self.actions.claim_for_commit(action_id)
        if action is None:
            raise RuntimeError("external_action_not_found_or_expired")
        if action["kind"] != "calendar_update":
            raise RuntimeError("external_action_kind_mismatch")
        if action["status"] in SETTLED_STATUSES:
            cached = dict(action["result"] or {})
            return {"action": "google_calendar_update", "action_id": action_id, "duplicate_commit": True, **cached}
        if not action["claimed"]:
            raise RuntimeError(f"external_action_not_claimable:{action['status']}")

        payload = action["payload"]
        calendar_id = payload["calendar_id"]
        event_id = payload["event_id"]
        query = urlencode({"sendUpdates": payload.get("send_updates", "none")})
        url = (
            f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}"
            f"/events/{quote(event_id, safe='')}?{query}"
        )
        try:
            response = self._patch(url, payload["changes"])
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self.actions.mark_unknown(action_id, str(exc)[:500])
            raise RuntimeError("calendar_update_unknown_outcome_check_calendar_before_retrying") from exc
        except Exception as exc:
            self.actions.mark_failed(action_id, str(exc)[:500])
            raise

        result = {"event_id": response.get("id"), "html_link": response.get("htmlLink")}
        self.actions.mark_committed(action_id, result)
        return {"action": "google_calendar_update", "action_id": action_id, **result}

    def calendar_prepare_delete(self, arguments: dict[str, Any]) -> dict[str, Any]:
        calendar_id = str(arguments.get("calendar_id") or "primary")
        event_id = str(arguments.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("calendar_event_id_required")
        existing = self._get_event(calendar_id, event_id)
        send_updates = self._validate_send_updates(arguments.get("send_updates"))

        payload = {"calendar_id": calendar_id, "event_id": event_id, "send_updates": send_updates}
        preview = {
            "calendar_id": calendar_id,
            "event_id": event_id,
            "summary": existing.get("summary") or "(제목 없음)",
            "start": existing.get("start"),
            "end": existing.get("end"),
            "send_updates": send_updates,
        }
        action = self.actions.create_prepared_action(
            kind="calendar_delete",
            payload=payload,
            preview=preview,
            ttl_sec=self.config.external_action_ttl_sec,
        )
        return {
            "action": "google_calendar_prepare_delete",
            "action_id": action["action_id"],
            "preview": preview,
            "expires_at": action["expires_at"],
            "requires_approval": True,
        }

    def calendar_delete(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action_id = str(arguments.get("action_id") or "")
        if not action_id:
            raise ValueError("action_id_required")
        action = self.actions.claim_for_commit(action_id)
        if action is None:
            raise RuntimeError("external_action_not_found_or_expired")
        if action["kind"] != "calendar_delete":
            raise RuntimeError("external_action_kind_mismatch")
        if action["status"] in SETTLED_STATUSES:
            cached = dict(action["result"] or {})
            return {"action": "google_calendar_delete", "action_id": action_id, "duplicate_commit": True, **cached}
        if not action["claimed"]:
            raise RuntimeError(f"external_action_not_claimable:{action['status']}")

        payload = action["payload"]
        calendar_id = payload["calendar_id"]
        event_id = payload["event_id"]
        query = urlencode({"sendUpdates": payload.get("send_updates", "none")})
        url = (
            f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}"
            f"/events/{quote(event_id, safe='')}?{query}"
        )
        try:
            self._delete(url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self.actions.mark_unknown(action_id, str(exc)[:500])
            raise RuntimeError("calendar_delete_unknown_outcome_check_calendar_before_retrying") from exc
        except Exception as exc:
            self.actions.mark_failed(action_id, str(exc)[:500])
            raise

        result = {"event_id": event_id, "deleted": True}
        self.actions.mark_committed(action_id, result)
        return {"action": "google_calendar_delete", "action_id": action_id, **result}

    def _restricted_enabled(self) -> bool:
        return bool(getattr(self.config, "google_restricted_scopes_enabled", False))

    def _requested_scopes(self) -> tuple[str, ...]:
        scopes = GOOGLE_SCOPES if self.config.google_write_enabled else _READ_ONLY_SCOPES
        if self._restricted_enabled():
            return scopes
        # 공개판: 제한 권한을 빼고, 고른 파일을 읽을 `drive.file` 은 읽기 전용에서도 둔다.
        kept = tuple(scope for scope in scopes if scope not in RESTRICTED_SCOPES)
        return kept if DRIVE_FILE_SCOPE in kept else kept + (DRIVE_FILE_SCOPE,)

    # ---- 드라이브 파일 고르기 (Google Picker 데스크톱 흐름) ------------------------------
    #   https://developers.google.com/workspace/drive/picker/guides/desktop-mobile-picker (2026-09-16 확인)
    #   인증 주소에 `prompt=consent` + `trigger_onepick=true`, 권한은 `drive.file` **단독**. 고른 파일은 돌아오는
    #   주소의 `picked_file_ids`(쉼표)로 온다. API 키는 필요 없고, 콘솔에서 Google Picker API 를 켜야 한다(프로젝트 소유자 몫).
    def picked_files_path(self) -> Path:
        return Path(self.config.data_dir) / PICKED_FILES_NAME

    def picked_files(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.picked_files_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict) and item.get("id")]

    def _remember_picked(self, file_ids: list[str]) -> list[dict[str, Any]]:
        known = {str(item["id"]): item for item in self.picked_files()}
        for file_id in file_ids:
            known.setdefault(file_id, {"id": file_id, "picked_at": time.time()})
        rows = sorted(known.values(), key=lambda item: -float(item.get("picked_at") or 0))[:200]
        path = self.picked_files_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        return rows

    def start_picker(self) -> dict[str, Any]:
        return self.start_oauth(picker=True)
