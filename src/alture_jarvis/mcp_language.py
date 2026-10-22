"""바깥 AI 연결(MCP)의 언어 — 사용자가 앱에서 고른 화면 언어를 따른다 (2026-10-19).

## 왜

연결의 안내문 · 도구 설명 · 결과 안내가 한국어로만 나갔다. 영어로 시킨 클로드 코드가 손자리에게 과제를 **한국어로**
넘겼다(10-19 사진 찍던 판 `029fae29`). 과제 칸의 설명이 「한국어 권장」이었고, 모델은 안내문의 언어를 따라간다.
영어 사용자가 클로드 코드에 손자리를 붙이면 똑같이 된다.

## 어떻게 고르나

1. `JARVIS_MCP_LANG`(ko · en) — 측정 · 시험용으로 손으로 정할 때.
2. 돌고 있는 손자리의 화면 언어(`GET /v1/ui-language`) — 사용자가 앱에서 고른 것.
3. 손자리가 아직 안 떴으면 윈도우 표시 언어 — 한국어면 ko, 아니면 en.

연결은 클라이언트가 켤 때 한 번 정한다. 앱에서 언어를 바꾸면 클라이언트를 다시 켤 때 따라간다.
"""

from __future__ import annotations

import locale
import os
import sys
from typing import Any

LANGS = ("ko", "en")


def os_language() -> str:
    """운영체제 표시 언어 — 한국어면 ko, 아니면 en."""
    if sys.platform == "win32":
        try:
            import ctypes

            primary = int(ctypes.windll.kernel32.GetUserDefaultUILanguage()) & 0x3FF
            return "ko" if primary == 0x12 else "en"
        except Exception:  # noqa: BLE001 — 못 읽으면 아래 로캘로
            pass
    try:
        name = (locale.getlocale()[0] or "").lower()
    except Exception:  # noqa: BLE001
        name = ""
    return "ko" if name.startswith(("ko", "korean")) else "en"


def pick_language(base_url: str, token: str, *, env: dict[str, str] | None = None, client: Any = None) -> str:
    """이 연결이 쓸 언어. 위 순서대로 — 앞의 것이 답하면 거기서 끝난다."""
    source = env if env is not None else os.environ
    forced = str(source.get("JARVIS_MCP_LANG") or "").strip().lower()
    if forced in LANGS:
        return forced
    try:
        import httpx

        getter = client.get if client is not None else httpx.get
        response = getter(f"{base_url.rstrip('/')}/v1/ui-language", headers={"X-JARVIS-TOKEN": token}, timeout=2.0)
        if response.status_code == 200:
            value = str((response.json() or {}).get("lang") or "")
            if value in LANGS:
                return value
    except Exception:  # noqa: BLE001 — 손자리가 아직 안 떴다
        pass
    return os_language()
