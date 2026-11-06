from __future__ import annotations

from . import brand as _brand

import base64
import html
import os
import subprocess
import sys
from typing import Any

from .events import EventBus


class NotificationService:
    def __init__(self, events: EventBus) -> None:
        self.events = events

    def notify(self, title: str, message: str) -> dict[str, Any]:
        title = title.strip()[:100] or _brand.NAME
        message = " ".join(message.split())[:240] or "작업이 완료되었습니다."
        self.events.publish("desktop_notification", {"title": title, "message": message})
        if sys.platform == "darwin":
            return self._notify_mac(title, message)
        if os.name != "nt":
            return {"ok": False, "reason": "windows_only"}
        title_xml = html.escape(title)
        message_xml = html.escape(message)
        script = f"""
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text>{title_xml}</text><text>{message_xml}</text></binding></visual></toast>')
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Sonjari').Show($toast)
"""
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    @staticmethod
    def _notify_mac(title: str, message: str) -> dict[str, Any]:
        """맥(2026-11-03 · 전수조사 B7): 알림 센터 한 줄(`osascript display notification`).

        ★ 윈도우와 다른 점: 알림의 보낸 이가 「스크립트 편집기」로 보이고, 누르면 결과가 열리는 동작이 없다.
          알림 허락은 맥이 처음 한 번 묻는다(대표가 누름).
        """
        def quoted(text: str) -> str:
            return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

        script = f"display notification {quoted(message)} with title {quoted(title)}"
        try:
            subprocess.Popen(["osascript", "-e", script], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # noqa: S603,S607 — 고정된 명령 · 글은 따옴표로 감쌈
            return {"ok": True, "via": "osascript"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:200]}
