"""모델이 앞부분을 **얼마나 읽었나** — 이 기기 Ollama 서버 기록에서 실제 진행률을 읽는다 (2026-11-18 대표 「모델 올릴 때처럼 화면에」).

## 왜

맥 4B · 9B 는 처음 보는 종류의 일에서 도구 설명과 지침(2~2.6만 토큰)을 읽는 데 1~2.5분이 걸린다(초당 약 340 · 170).
그동안 화면은 「첫 글자 전 N초째」만 셌다 — 사람은 끝이 언제인지 모른다. 모델 올리기 막대(`ModelLoadLine`)는 「시간으로 채우지 않고
잰 값만 그린다」가 원칙이다. 같은 원칙으로, 시간으로 짐작하지 않고 **서버가 적은 진행률**만 쓴다.

## 어디서

Ollama 0.40+ 는 llama-server 를 `--log-verbosity 4` 로 띄워 1,024토큰(배치)마다 서버 기록에 이런 줄을 남긴다(맥 11-17 확인):

    slot print_timing: id  0 | task 0 | prompt processing, n_tokens =   4096, progress = 0.46, t =   8.03 s / ...

기록 줄에는 시각이 없다(`--no-log-timestamps`). 그래서 부르기 **직전의 파일 크기**를 적어 두고 그 뒤에 붙은 줄만 읽는다 —
다른 부르기의 진행률을 섞지 않는다.

## 말하지 않는 것

- 이 기기 Ollama 가 아니면(집 PC 모델을 빌려 씀 · Strata · 원격) 아무것도 안 돌려준다 — 화면은 예전처럼 초만 센다.
- 첫 배치(맥 4B 로 약 3초)가 끝나기 전에는 진행률이 없다.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

_LINE = re.compile(r"prompt processing, n_tokens\s*=\s*(\d+), progress\s*=\s*([0-9.]+)")
#: 한 번에 읽는 새 글의 끝 쪽 크기 — 기록이 수다스러워도(배치마다 여러 줄) 마지막 진행 줄은 여기 안에 있다.
_TAIL_BYTES = 64 * 1024


def ollama_log_path() -> Path | None:
    """이 기기 Ollama 서버 기록 파일. 없으면 None."""
    candidates: list[Path] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Ollama" / "server.log")
    candidates.append(Path.home() / ".ollama" / "logs" / "server.log")
    for path in candidates:
        if path.is_file():
            return path
    return None


def is_local_ollama(base_url: str) -> bool:
    host = (urlparse(str(base_url or "")).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


class PrefillProgress:
    """부르기 하나의 읽기 진행률. 만든 순간의 기록 끝부터 본다. `fraction()` 은 0~1 또는 None(모름)."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        try:
            self._start = path.stat().st_size if path is not None else 0
        except OSError:
            self._path = None
            self._start = 0

    @classmethod
    def for_ollama(cls, base_url: str) -> "PrefillProgress":
        return cls(ollama_log_path() if is_local_ollama(base_url) else None)

    def fraction(self) -> float | None:
        if self._path is None:
            return None
        try:
            size = self._path.stat().st_size
            if size < self._start:          # 기록이 갈렸다(Ollama 재시작 · 파일 돌림) — 처음부터 다시 센다
                self._start = 0
            if size <= self._start:
                return None
            with self._path.open("rb") as handle:
                handle.seek(max(self._start, size - _TAIL_BYTES))
                text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return None
        found = _LINE.findall(text)
        if not found:
            return None
        try:
            value = float(found[-1][1])
        except ValueError:
            return None
        return max(0.0, min(1.0, value))
