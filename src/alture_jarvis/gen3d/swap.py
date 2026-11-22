"""3D 를 굽기 전에 이 기기의 글 모델을 내린다 — 맥(통합 메모리)만 (2026-11-14 대표 지시).

## 왜
맥 미니는 그래픽 메모리가 일반 메모리(16GB)와 같다. 이 기기 Ollama 에 글 모델이 올라와 있으면 3D 모델(TRELLIS.2 · 8비트)과
같은 16GB 를 나눠 써서 둘 다 느려지거나 3D 가 메모리 부족으로 죽는다. 그래서 굽기 직전에 **실제로 올라가 있는 것**
(`/api/ps`)만 `keep_alive: 0` 으로 내리고, 목록에서 사라질 때까지 기다린다.

- **위성(글 모델이 집 PC)** 이면 이 기기 Ollama 의 `/api/ps` 가 비어 있다 — 내릴 것이 없으니 그대로 간다(묻지 않고 센다).
- **윈도우는 내리지 않는다** — 3D 는 다른 그래픽카드에서 돌고, Strata · 다리 같은 운영 동작은 건드리지 않는다(알림만).
- 다 구운 뒤 다시 올리지 않는다: 다음 질문이 오면 Ollama 가 그 모델을 저절로 올린다(`/api/chat` 이 부르는 그때).
"""
from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable
from typing import Any

LOCAL_OLLAMA = "http://127.0.0.1:11434"


def _get(url: str, timeout: float) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 — 이 기기 Ollama 주소만
        return json.loads(response.read().decode("utf-8"))


def _post(url: str, body: dict[str, Any], timeout: float) -> Any:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — 이 기기 Ollama 주소만
        return json.loads(response.read().decode("utf-8") or "{}")


class LocalTextModels:
    """이 기기 Ollama 에 올라간 모델을 읽고 내린다. 못 읽으면 「없다」로 본다(지어내지 않고, 3D 는 그대로 간다)."""

    def __init__(self, base_url: str = LOCAL_OLLAMA, *, get: Callable[[str, float], Any] = _get,
                 post: Callable[[str, dict[str, Any], float], Any] = _post, sleep: Callable[[float], None] = time.sleep) -> None:
        self.base_url = base_url.rstrip("/")
        self._get, self._post, self._sleep = get, post, sleep

    def loaded(self) -> list[dict[str, Any]]:
        """[{"name", "mib"}] — `/api/ps` 의 size(바이트)를 MiB 로. 비었거나 못 읽으면 빈 목록."""
        try:
            rows = (self._get(f"{self.base_url}/api/ps", 3.0) or {}).get("models") or []
        except Exception:  # noqa: BLE001 — Ollama 가 꺼져 있으면 내릴 것도 없다
            return []
        out = []
        for row in rows:
            name = str(row.get("name") or row.get("model") or "")
            if name:
                out.append({"name": name, "mib": int(int(row.get("size") or 0) / 1048576)})
        return out

    def unload(self, names: list[str], *, timeout_sec: float = 60.0) -> list[str]:
        """내린다. 기다린 뒤에도 **남은 이름** 을 돌려준다(빈 목록이면 다 내려갔다)."""
        for name in names:
            try:
                self._post(f"{self.base_url}/api/generate", {"model": name, "keep_alive": 0, "prompt": ""}, 60.0)
            except Exception:  # noqa: BLE001, S110 — 이미 내려갔으면 실패해도 된다. 남았는지는 아래에서 다시 센다
                pass
        deadline = time.monotonic() + timeout_sec
        while True:
            left = [row["name"] for row in self.loaded() if row["name"] in set(names)]
            if not left or time.monotonic() >= deadline:
                return left
            self._sleep(0.5)
