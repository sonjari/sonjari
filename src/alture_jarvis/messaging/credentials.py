"""디스코드 봇 토큰은 **윈도우 자격 증명 관리자**에만 둔다 — 평문 파일에 두지 않는다 (2026-10-17).

## 왜

봇 토큰을 가진 사람은 그 봇으로 무엇이든 말할 수 있고, 허용 목록에 있는 주인에게 DM 을 보낼 수도 있다.
`.env` · 설정 JSON 에 두면 백업 · 동기화 폴더 · 진단 묶음(`problem_report`)으로 새어 나간다 — 이 저장소의 CLAUDE.md 에
운영 키가 평문으로 적혀 있던 것과 같은 모양이다(`secret_scrub.py` 머리글). 자격 증명 관리자는 이 윈도우 사용자로만 열린다.

설정 파일(`discord_config.py`)에는 비밀이 아닌 것(허용 목록 · 홈 채널 · 승인 정책)만 둔다.

★ win32cred 는 함수 안에서만 부른다 — 윈도우가 아닌 곳 · pywin32 가 없는 곳에서도 이 모듈을 import 할 수 있게.
"""

from __future__ import annotations

from typing import Protocol

TARGET = "Sonjari/discord-bot-token"
_USER = "discord-bot"
_ERROR_NOT_FOUND = 1168


class CredentialStore(Protocol):
    def read(self, target: str) -> str | None: ...

    def write(self, target: str, secret: str) -> None: ...

    def delete(self, target: str) -> bool: ...


class WindowsCredentialStore:
    """일반(Generic) 자격 증명 하나. 「제어판 → 자격 증명 관리자 → Windows 자격 증명」에 `Sonjari/discord-bot-token` 으로 보인다."""

    def read(self, target: str) -> str | None:
        import win32cred

        try:
            credential = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception as exc:  # pywintypes.error — 「없음」만 None, 나머지는 올린다
            if getattr(exc, "winerror", None) == _ERROR_NOT_FOUND:
                return None
            raise
        blob = credential.get("CredentialBlob")
        if blob is None:
            return None
        if isinstance(blob, bytes):
            # 문자열로 쓰면 pywin32 는 UTF-16LE 로 저장한다. 다른 도구가 UTF-8 로 넣은 것도 읽는다.
            try:
                text = blob.decode("utf-16-le")
            except UnicodeDecodeError:
                text = blob.decode("utf-8", errors="replace")
            if "\x00" in text:
                text = blob.decode("utf-8", errors="replace")
            return text.strip() or None
        return str(blob).strip() or None

    def write(self, target: str, secret: str) -> None:
        import win32cred

        win32cred.CredWrite({
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": target,
            "UserName": _USER,
            "CredentialBlob": secret,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            "Comment": "Sonjari Discord bridge bot token",
        }, 0)

    def delete(self, target: str) -> bool:
        import win32cred

        try:
            win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception as exc:  # pywintypes.error
            if getattr(exc, "winerror", None) == _ERROR_NOT_FOUND:
                return False
            raise
        return True


class MemoryCredentialStore:
    """시험용 — 프로세스 안에만 둔다."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    def read(self, target: str) -> str | None:
        return self.items.get(target)

    def write(self, target: str, secret: str) -> None:
        self.items[target] = secret

    def delete(self, target: str) -> bool:
        return self.items.pop(target, None) is not None


def default_store() -> CredentialStore:
    return WindowsCredentialStore()


def load_bot_token(store: CredentialStore | None = None) -> str:
    """저장된 봇 토큰. 없으면 빈 문자열. 읽은 토큰은 기록 가리개에 등록한다."""
    from .base import REDACTOR

    token = ((store or default_store()).read(TARGET) or "").strip()
    REDACTOR.register(token)
    return token


def save_bot_token(token: str, store: CredentialStore | None = None) -> None:
    from .base import REDACTOR

    REDACTOR.register(token)
    (store or default_store()).write(TARGET, token.strip())
