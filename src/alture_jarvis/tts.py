from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time
from typing import Any

import httpx

from .config import JarvisConfig


class SupertonicTTS:
    def __init__(self, config: JarvisConfig) -> None:
        self.config = config
        self.cache_dir = config.output_dir / "speech"
        self.last_metrics: dict[str, Any] = {}

    @property
    def steps(self) -> int:
        return max(1, min(100, self.config.tts_steps))

    @property
    def speed(self) -> float:
        return max(0.7, min(2.0, self.config.tts_speed))

    def health(self) -> dict[str, Any]:
        if not self.config.tts_enabled:
            return {"ok": False, "enabled": False, "voice": self.config.supertonic_voice}
        try:
            with httpx.Client(timeout=3.0) as client:
                response = client.get(f"{self.config.supertonic_base_url}/v1/health")
                if response.status_code >= 400:
                    response = client.get(f"{self.config.supertonic_base_url}/v1/styles")
                response.raise_for_status()
            return {
                "ok": True,
                "enabled": True,
                "voice": self.config.supertonic_voice,
                "steps": self.steps,
                "speed": self.speed,
            }
        except Exception as exc:
            return {
                "ok": False,
                "enabled": True,
                "voice": self.config.supertonic_voice,
                "error": str(exc),
            }

    def _request_audio(self, text: str) -> bytes:
        body = {
            "text": text,
            "voice": self.config.supertonic_voice,
            "lang": self.config.supertonic_language,
            "steps": self.steps,
            "speed": self.speed,
            "response_format": "wav",
        }
        started = time.perf_counter()
        with httpx.Client(timeout=120.0) as client:
            response = client.post(f"{self.config.supertonic_base_url}/v1/tts", json=body)
            response.raise_for_status()
        self.last_metrics = {
            "cached": False,
            "synthesis_ms": round((time.perf_counter() - started) * 1000),
            "audio_duration_sec": float(response.headers.get("X-Audio-Duration") or 0),
            "steps": self.steps,
            "speed": self.speed,
        }
        return response.content

    def warmup(self) -> dict[str, Any]:
        if not self.config.tts_enabled or not self.config.tts_warmup_enabled:
            return {"status": "disabled"}
        # Always execute inference. Reusing the disk cache would not warm a freshly
        # restarted Supertonic process or its ONNX sessions.
        self._request_audio("준비됐어요.")
        return dict(self.last_metrics)

    def synthesize(self, text: str, *, play: bool = False) -> Path:
        if not self.config.tts_enabled:
            raise RuntimeError("tts_disabled")
        clean = text.strip()
        if not clean:
            raise ValueError("empty_tts_text")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(
            (
                f"v2|{self.config.supertonic_voice}|{self.config.supertonic_language}|"
                f"{self.steps}|{self.speed:.3f}|{clean}"
            ).encode("utf-8")
        ).hexdigest()[:24]
        output = self.cache_dir / f"{key}.wav"
        if not output.exists():
            output.write_bytes(self._request_audio(clean))
        else:
            self.last_metrics = {
                "cached": True,
                "synthesis_ms": 0,
                "steps": self.steps,
                "speed": self.speed,
            }
        if play:
            self.play(output)
        return output

    @staticmethod
    def play(path: Path) -> None:
        if os.name != "nt":
            return
        import winsound

        # Blocking playback keeps the SPEAKING state and media-resume timing accurate.
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_NODEFAULT)
