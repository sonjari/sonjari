from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from typing import Any, Protocol

from .config import JarvisConfig
from .events import EventBus


class MediaBackend(Protocol):
    def pause_playing(self, excluded_apps: tuple[str, ...]) -> list[str]: ...

    def resume(self, source_ids: list[str]) -> list[str]: ...


class WindowsMediaBackend:
    @staticmethod
    async def _pause(excluded_apps: tuple[str, ...]) -> list[str]:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus,
        )

        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        paused: list[str] = []
        for session in manager.get_sessions():
            source_id = str(session.source_app_user_model_id)
            lowered = source_id.lower()
            if any(excluded in lowered for excluded in excluded_apps):
                continue
            info = session.get_playback_info()
            if (
                info.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
                and info.controls.is_pause_enabled
                and await session.try_pause_async()
            ):
                paused.append(source_id)
        return paused

    @staticmethod
    async def _resume(source_ids: list[str]) -> list[str]:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager,
            GlobalSystemMediaTransportControlsSessionPlaybackStatus,
        )

        wanted = set(source_ids)
        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        resumed: list[str] = []
        for session in manager.get_sessions():
            source_id = str(session.source_app_user_model_id)
            if source_id not in wanted:
                continue
            info = session.get_playback_info()
            if (
                info.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PAUSED
                and info.controls.is_play_enabled
                and await session.try_play_async()
            ):
                resumed.append(source_id)
        return resumed

    def pause_playing(self, excluded_apps: tuple[str, ...]) -> list[str]:
        return asyncio.run(self._pause(excluded_apps))

    def resume(self, source_ids: list[str]) -> list[str]:
        return asyncio.run(self._resume(source_ids))


class MediaSessionController:
    """Pauses only media that JARVIS observed playing, then selectively restores it."""

    def __init__(
        self,
        config: JarvisConfig,
        events: EventBus,
        backend: MediaBackend | None = None,
    ) -> None:
        self.config = config
        self.events = events
        self.backend = backend or WindowsMediaBackend()
        self._lock = threading.Lock()
        self._active = False
        self._paused_source_ids: list[str] = []
        self._state_path = self.config.data_dir / "paused-media.json"

    def _save_recovery_state(self, source_ids: list[str]) -> None:
        if not source_ids:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps({"source_ids": source_ids, "paused_at": time.time()}),
            encoding="utf-8",
        )

    def _clear_recovery_state(self) -> None:
        self._state_path.unlink(missing_ok=True)

    def recover_after_restart(self) -> dict[str, Any]:
        if not self._state_path.exists() or not self.config.media_pause_enabled:
            return {"recovered": [], "pending": False}
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            source_ids = [str(item) for item in payload.get("source_ids") or []]
            resumed = self.backend.resume(source_ids) if source_ids else []
            self._clear_recovery_state()
            result = {"recovered": resumed, "requested": source_ids, "pending": False}
            self.events.publish("media_recovered_after_restart", result)
            return result
        except Exception as exc:
            result = {"recovered": [], "pending": True, "error": str(exc)}
            self.events.publish("media_recovery_failed", result)
            return result

    def dependency_status(self) -> dict[str, Any]:
        if not self.config.media_pause_enabled:
            return {"ok": False, "enabled": False}
        if os.name != "nt":
            return {"ok": False, "enabled": True, "error": "windows_only"}
        try:
            import winrt.windows.foundation  # noqa: F401
            import winrt.windows.foundation.collections  # noqa: F401
            import winrt.windows.media.control  # noqa: F401

            return {"ok": True, "enabled": True, "active": self._active}
        except ImportError as exc:
            return {"ok": False, "enabled": True, "error": f"dependency_missing:{exc.name}"}

    def pause_for_interaction(self) -> dict[str, Any]:
        if not self.config.media_pause_enabled or os.name != "nt":
            return {"enabled": False, "paused": []}
        with self._lock:
            if self._active:
                return {"enabled": True, "already_active": True, "paused": list(self._paused_source_ids)}
            self._active = True
        try:
            excluded = tuple(
                item.strip().lower()
                for item in self.config.media_excluded_apps.split(",")
                if item.strip()
            )
            paused = self.backend.pause_playing(excluded)
            with self._lock:
                self._paused_source_ids = list(dict.fromkeys(paused))
            self._save_recovery_state(self._paused_source_ids)
            result = {"enabled": True, "paused": list(self._paused_source_ids)}
            self.events.publish("media_paused", result)
            return result
        except Exception as exc:
            with self._lock:
                self._active = False
                self._paused_source_ids = []
            result = {"enabled": True, "paused": [], "error": str(exc)}
            self.events.publish("media_pause_failed", result)
            return result

    def resume_after_interaction(self) -> dict[str, Any]:
        with self._lock:
            if not self._active:
                return {"enabled": self.config.media_pause_enabled, "resumed": [], "active": False}
            source_ids = list(self._paused_source_ids)
            self._active = False
            self._paused_source_ids = []
        if not source_ids:
            self._clear_recovery_state()
            result = {"enabled": True, "resumed": [], "active": False}
            self.events.publish("media_resumed", result)
            return result
        try:
            if self.config.media_resume_delay_sec > 0:
                time.sleep(self.config.media_resume_delay_sec)
            resumed = self.backend.resume(source_ids)
            self._clear_recovery_state()
            result = {"enabled": True, "resumed": resumed, "requested": source_ids, "active": False}
            self.events.publish("media_resumed", result)
            return result
        except Exception as exc:
            result = {
                "enabled": True,
                "resumed": [],
                "requested": source_ids,
                "active": False,
                "error": str(exc),
            }
            self.events.publish("media_resume_failed", result)
            return result
