from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
import time
from typing import Any

import httpx

from . import english as _english
from . import mac_voice
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

    @property
    def engine(self) -> str:
        """`macos`(맥 `say`) 또는 `supertonic`. auto 면 맥은 macos · 그 밖은 supertonic(윈도우 그대로)."""
        return mac_voice.tts_engine(self.config)

    @property
    def voice_label(self) -> str:
        if self.engine == "macos":
            return f"macOS {mac_voice.pick_voice(self.config, 'ko') or 'default'}"
        return f"Supertonic {self.config.supertonic_voice}"

    def _where(self) -> str:
        """Supertonic 이 **어디서** 만드나 — 이 PC(127.0.0.1) 또는 다른 기기 주소(11-16: 맥이 집 PC 에 글을 보내 만들고 있었다)."""
        from urllib.parse import urlparse

        host = urlparse(str(self.config.supertonic_base_url or "")).hostname or ""
        return "this_device" if host in {"127.0.0.1", "localhost", "::1", ""} else f"remote:{host}"

    def health(self) -> dict[str, Any]:
        if not self.config.tts_enabled:
            return {"ok": False, "enabled": False, "voice": self.config.supertonic_voice, "engine": self.engine}
        if self.engine == "macos":
            return {"enabled": True, **mac_voice.say_health(self.config)}
        try:
            # ★ 2026-11-11: 상태 물음 시간의 30% 가 이 줄의 Client() 만들기였다(py-spy) — 만들 때마다 인증서 묶음을 새로 읽는다.
            #   음성 서버는 이 PC 의 http:// 라 인증서가 쓰일 일이 없다 → http 면 인증서를 읽지 않는다.
            plain = str(self.config.supertonic_base_url or "").startswith("http://")
            with httpx.Client(timeout=3.0, verify=not plain) as client:
                response = client.get(f"{self.config.supertonic_base_url}/v1/health")
                if response.status_code >= 400:
                    response = client.get(f"{self.config.supertonic_base_url}/v1/styles")
                response.raise_for_status()
            return {
                "ok": True,
                "enabled": True,
                "engine": "supertonic",
                "where": self._where(),
                "voice": self.config.supertonic_voice,
                "steps": self.steps,
                "speed": self.speed,
            }
        except Exception as exc:
            return {
                "ok": False,
                "enabled": True,
                "engine": "supertonic",
                "where": self._where(),
                "voice": self.config.supertonic_voice,
                "error": str(exc),
            }

    def _lang_for(self, text: str) -> str:
        """읽을 글의 언어 — **영어 글은 en 으로** 읽힌다 (2026-10-17 영어판 점검).

        설정값(`supertonic_language`, 기본 ko)만 보냈더니 영어 화면 · 영어 질문의 영어 답도 한국어 규칙으로 읽었다 — 화면 글은
        나가는 순간 번역되는데(`ui_i18n`) 음성만 언어를 몰랐다. 음성 서버는 en 을 받는다(이 PC 에서 확인). 그 밖은 설정값 그대로.
        """
        return "en" if _english.english_dominant(" ".join(str(text or "").split())) else self.config.supertonic_language

    def _say_audio(self, text: str, output: Path) -> None:
        """맥 `say` 로 이 기기 안에서 만든다 — 글이 밖으로 나가지 않는다."""
        lang = self._lang_for(text)
        started = time.perf_counter()
        mac_voice.say_to_wav(text, output, voice=mac_voice.pick_voice(self.config, lang),
                             rate=int(getattr(self.config, "mac_tts_rate", 0) or 0))
        self.last_metrics = {"cached": False, "engine": "macos",
                             "synthesis_ms": round((time.perf_counter() - started) * 1000)}

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
        if self.engine == "macos":
            # 맥 `say` 는 데울 서버가 없다 — 실제로 한 번 만들어 되는지만 본다(재생은 안 한다).
            probe = self.cache_dir / "_warmup_macos.wav"
            self._say_audio("준비됐어요.", probe)
            probe.unlink(missing_ok=True)
            return dict(self.last_metrics)
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
        if self.engine == "macos":
            # 엔진 · 목소리가 다르면 다른 소리다 — 같은 캐시 자리를 나눠 쓰지 않는다.
            lang = self._lang_for(clean)
            identity = (f"macos|{mac_voice.pick_voice(self.config, lang)}|{lang}|"
                        f"{int(getattr(self.config, 'mac_tts_rate', 0) or 0)}|{clean}")
        else:
            identity = (
                f"v2|{self.config.supertonic_voice}|{self._lang_for(clean)}|"
                f"{self.steps}|{self.speed:.3f}|{clean}"
            )
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        output = self.cache_dir / f"{key}.wav"
        if not output.exists():
            if self.engine == "macos":
                self._say_audio(clean, output)
            else:
                output.write_bytes(self._request_audio(clean))
        elif self.engine == "macos":
            self.last_metrics = {"cached": True, "engine": "macos", "synthesis_ms": 0}
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
        if sys.platform == "darwin":
            # 맥(2026-11-03 · 전수조사 B8): 기본으로 깔린 `afplay` 로 끝날 때까지 튼다(윈도우 winsound 처럼 막고 기다림).
            subprocess.run(["afplay", str(path)], check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # noqa: S603,S607 — 우리가 만든 WAV 하나
            return
        if os.name != "nt":
            return
        import winsound

        # Blocking playback keeps the SPEAKING state and media-resume timing accurate.
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_NODEFAULT)
