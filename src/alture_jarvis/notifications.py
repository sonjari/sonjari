from __future__ import annotations

from . import brand as _brand

import base64
import html
import os
import subprocess
from typing import Any

from .events import EventBus


class NotificationService:
    def __init__(self, events: EventBus) -> None:
        self.events = events

    def notify(self, title: str, message: str) -> dict[str, Any]:
        title = title.strip()[:100] or _brand.NAME
        message = " ".join(message.split())[:240] or "작업이 완료되었습니다."
        self.events.publish("desktop_notification", {"title": title, "message": message})
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
