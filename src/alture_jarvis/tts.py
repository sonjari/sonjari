from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time
from typing import Any

import httpx

from . import english as _english
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

    def _lang_for(self, text: str) -> str:
        """읽을 글의 언어 — **영어 글은 en 으로** 읽힌다 (2026-10-17 영어판 점검).

        설정값(`supertonic_language`, 기본 ko)만 보냈더니 영어 화면 · 영어 질문의 영어 답도 한국어 규칙으로 읽었다 — 화면 글은
        나가는 순간 번역되는데(`ui_i18n`) 음성만 언어를 몰랐다. 음성 서버는 en 을 받는다(이 PC 에서 확인). 그 밖은 설정값 그대로.
        """
        return "en" if _english.english_dominant(" ".join(str(text or "").split())) else self.config.supertonic_language

    def _request_audio(self, text: str) -> bytes:
        body = {
            "text": text,
            "voice": self.config.supertonic_voice,
            "lang": self._lang_for(text),
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
                f"v2|{self.config.supertonic_voice}|{self._lang_for(clean)}|"
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
