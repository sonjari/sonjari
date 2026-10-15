"""모델을 그래픽카드에 올리는 동안의 **실측** 진행률 (2026-10-01 제품 요청).

## 왜

헤르메스와 같은 AWS 에서 나란히 설치해 보니, 헤르메스는 「Loading … into memory 34%」 막대를 보여 줬고 손자리는
「모델을 그래픽카드에 올리는 중입니다 — 1분쯤 걸립니다」 문구 한 줄이었다. 콜드 적재는 70~90초다(09-29 실측).
그동안 사람은 멈춘 건지 도는 건지 모른다.

## 막대를 지어내지 않는다

Ollama 는 올리는 진행률을 알려 주지 않는다 — 다 올라가기 전까지 `/api/ps` 에 안 나온다. 시간 따라 차는 막대는
거짓이다. 그래서 **카드 메모리를 잰다**:

    올라간 양  = 지금 카드 사용량 − 올리기 전 사용량(지금까지 본 가장 낮은 값)
    다 올라갈 양 = 이 PC 에서 지난번 이 모델·이 창 크기를 올렸을 때 잰 같은 차이   (없으면 받은 파일 크기로 추정)

두 값 모두 nvidia-smi 의 같은 칸(카드 전체 사용량)에서 나온다 — 윈도우는 프로세스별 메모리가 `[N/A]` 라서
`size_vram` 과 섞으면 Ollama 작업 버퍼만큼 어긋난다(context_watch 머리말 실측).

못 재면(NVIDIA 밖의 카드·nvidia-smi 없음) 막대 없이 「지난번 N초 걸림 · 지금 M초째」만 준다. 그것도 실측이다.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

#: 이만큼 안 물어 오면 앞 판의 시작 시각·바닥값을 버린다 — 다음 콜드 적재는 새 판이다.
STALE_S = 120.0
#: 다 올라가기 전에는 100% 를 안 보인다. 「다 됐다」는 `/api/ps` 가 말한다.
MAX_FRACTION = 0.97
#: 받은 파일 크기 → 카드에 올라가는 양 추정(창·작업 버퍼 몫). 첫 회에만 쓰고, 화면은 「추정」이라고 적는다.
FILE_TO_CARD = 1.15


def gpu_used_gb(run: Callable[..., Any] | None = None) -> float | None:
    """모든 NVIDIA 카드 사용량 합(GB). 모델이 여러 장에 나뉘어 올라가도 차이는 합에서 잡힌다. 못 읽으면 None."""
    try:
        done = (run or subprocess.run)(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
    except Exception:  # noqa: BLE001 — 없거나 멈추면 「모름」
        return None
    if getattr(done, "returncode", 1) != 0:
        return None
    total = 0.0
    seen = False
    for line in str(done.stdout or "").splitlines():
        try:
            total += float(line.strip()) / 1024
            seen = True
        except ValueError:
            continue
    return round(total, 2) if seen else None


class LoadWatch:
    """화면이 콜드 적재 중일 때만 2초마다 묻는다. 값은 프로세스 안에만 두고, 다 올라간 순간의 실측만 파일로 남긴다."""

    def __init__(
        self,
        data_dir: Path,
        *,
        gpu_used: Callable[[], float | None] = gpu_used_gb,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._path = Path(data_dir) / "model_load_measured.json"
        self._gpu_used = gpu_used
        self._clock = clock
        self._lock = threading.Lock()
        self._key = ""
        self._started = 0.0
        self._seen = 0.0
        self._floor: float | None = None

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001 — 처음이거나 깨졌으면 빈 기록
            return {}

    def _save(self, key: str, record: dict[str, Any]) -> None:
        data = self._load()
        data[key] = record
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def observe(self, *, model: str, num_ctx: int, resident: bool, model_bytes: int = 0) -> dict[str, Any]:
        key = f"{model}@{int(num_ctx)}"
        now = self._clock()
        with self._lock:
            if key != self._key or now - self._seen > STALE_S:
                self._key, self._started, self._floor = key, now, None
            self._seen = now
            past = self._load().get(key) or {}
            last_seconds = past.get("seconds")
            if resident:
                # 다 올라간 순간 — 이 판을 지켜봤으면 실측을 남긴다(다음 막대의 분모).
                if self._floor is not None:
                    used = self._gpu_used()
                    loaded = round(used - self._floor, 2) if used is not None else None
                    record = {"seconds": round(now - self._started, 1)}
                    # 첫 질문이 적재 시작보다 늦게 들어오면 바닥값이 높게 잡혀 덜 잰다 — 그래서 **큰 쪽을 남긴다**.
                    #   덜 잰 값이 분모가 되면 다음 막대가 실제보다 빨리 차서 「거의 다 됐다」고 거짓말한다.
                    if loaded is not None and loaded > 0.3:
                        previous = past.get("gb")
                        record["gb"] = max(loaded, float(previous)) if isinstance(previous, (int, float)) else loaded
                    self._save(key, {**past, **record})
                    self._floor = None
                return {"loading": False, "resident": True}
            used = self._gpu_used()
            if used is not None:
                self._floor = used if self._floor is None else min(self._floor, used)
            elapsed = round(now - self._started, 1)
            out: dict[str, Any] = {
                "loading": True, "resident": False, "elapsed_s": elapsed,
                "last_seconds": last_seconds if isinstance(last_seconds, (int, float)) else None,
            }
            if used is None or self._floor is None:
                out.update(fraction=None, basis="unmeasured")
                return out
            measured = past.get("gb")
            if isinstance(measured, (int, float)) and measured > 0:
                expected, basis = float(measured), "measured"
            elif model_bytes > 0:
                expected, basis = model_bytes / 2**30 * FILE_TO_CARD, "estimated"
            else:
                out.update(fraction=None, basis="unmeasured", loaded_gb=round(used - self._floor, 2))
                return out
            loaded = max(0.0, used - self._floor)
            out.update(
                loaded_gb=round(loaded, 2), expected_gb=round(expected, 2), basis=basis,
                fraction=round(min(MAX_FRACTION, loaded / expected), 3),
            )
            return out
