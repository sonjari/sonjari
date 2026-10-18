from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

# ★ 2026-10-18 「나에 대한 지침」: 파일 안의 HTML 주석(`<!-- … -->`)은 **모델에게 보내지 않는다.**
#   카드가 쓰는 칸의 경계 표시 · 가져온 줄의 출처 메모가 주석으로 들어가는데, 그것까지 매 턴 실으면 작은 창에서
#   일할 자리만 먹는다. 개발자가 파일에 남기는 메모도 같은 규칙을 따른다(사람에겐 보이고 모델에겐 안 간다).
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_BLANKS = re.compile(r"\n{3,}")


#: 대화 판 시스템 글에 실리는 모양 — `runtime._system_prompt` 와 「나에 대한 지침」 길이 자(`about_me.meter`)가
#: **같은 글**을 재도록 한 곳에 둔다(두 벌이면 자가 실제와 갈린다).
PROFILE_INTRO = (
    "다음은 사용자가 직접 관리하는 신뢰 가능한 상시 프로필이다. "
    "질문과 관련될 때만 자연스럽게 활용하고, 프로필에 없는 최신 사실은 추정하지 마라.\n"
)


def profile_block(content: str) -> str:
    """`<jarvis-profile>` 블록. 비었으면 빈 글 — 빈 블록을 붙이면 모델이 「프로필이 없다」를 사실로 읽는다."""
    return f"{PROFILE_INTRO}<jarvis-profile>\n{content}\n</jarvis-profile>" if content else ""


def strip_comments(text: str) -> str:
    """주석을 걷고 빈 줄이 셋 이상 이어지면 둘로 줄인다. 닫히지 않은 `<!--` 는 손대지 않는다(사람이 쓴 글이다)."""
    return _BLANKS.sub("\n\n", _COMMENT.sub("", text)).strip()


class OperatorProfile:
    """Loads a small, trusted Markdown profile for persistent operator context.

    ★ 2026-10-18: 이 파일이 화면의 「나에 대한 지침」이다(이름 · 자리는 그대로 — 이미 쓰는 PC 와 맞추려고).
      예전엔 기동할 때 한 번만 읽어서, 파일을 고쳐도 다시 켜기 전까지 옛 글이 실렸다. 지금은 `content` 를 읽을 때마다
      파일의 수정 시각 · 크기를 보고 바뀌었으면 다시 읽는다 — 화면에서 저장하든 메모장으로 고치든 **다음 턴부터** 쓰인다.
      stat 한 번이라 매 턴 불러도 싸다.
    """

    def __init__(self, path: Path, *, max_chars: int = 6000) -> None:
        self.path = path
        self.max_chars = max(500, max_chars)
        self._content = ""
        self._error = ""
        self._truncated = False
        self._stamp: tuple[float, int] | None = None
        self._lock = threading.Lock()
        self.reload()

    def _file_stamp(self) -> tuple[float, int] | None:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return (stat.st_mtime, stat.st_size)

    def reload(self) -> str:
        with self._lock:
            stamp = self._file_stamp()
            try:
                if stamp is None or not self.path.exists():
                    self._content = ""
                    self._error = ""
                    self._truncated = False
                    self._stamp = stamp
                    return ""
                raw = self.path.read_text(encoding="utf-8-sig").strip()
                # 상한을 넘은 파일은 자르되 **잘렸다고 남긴다**(사고 Q — 조용히 자르면 사람은 다 실린 줄 안다).
                self._truncated = len(raw) > self.max_chars
                kept = raw[: self.max_chars]
                # 주석이 없는 파일은 예전과 한 글자도 다르지 않게 둔다(프리필 캐시 · 옛 시험).
                self._content = strip_comments(kept) if "<!--" in kept else kept
                self._error = ""
            except Exception as exc:
                self._content = ""
                self._error = str(exc)[:200]
                self._truncated = False
            self._stamp = stamp
            return self._content

    def _refresh_if_changed(self) -> None:
        if self._file_stamp() != self._stamp:
            self.reload()

    @property
    def content(self) -> str:
        self._refresh_if_changed()
        return self._content

    @property
    def truncated(self) -> bool:
        self._refresh_if_changed()
        return self._truncated

    def status(self) -> dict[str, Any]:
        self._refresh_if_changed()
        return {
            "loaded": bool(self._content),
            "path": str(self.path),
            "chars": len(self._content),
            "truncated": self._truncated,
            "error": self._error,
        }
