from __future__ import annotations

from pathlib import Path
from typing import Any


class OperatorProfile:
    """Loads a small, trusted Markdown profile for persistent operator context."""

    def __init__(self, path: Path, *, max_chars: int = 6000) -> None:
        self.path = path
        self.max_chars = max(500, max_chars)
        self._content = ""
        self._error = ""
        self.reload()

    def reload(self) -> str:
        try:
            if not self.path.exists():
                self._content = ""
                self._error = ""
                return ""
            self._content = self.path.read_text(encoding="utf-8-sig").strip()[: self.max_chars]
            self._error = ""
        except Exception as exc:
            self._content = ""
            self._error = str(exc)[:200]
        return self._content

    @property
    def content(self) -> str:
        return self._content

    def status(self) -> dict[str, Any]:
        return {
            "loaded": bool(self._content),
            "path": str(self.path),
            "chars": len(self._content),
            "error": self._error,
        }
