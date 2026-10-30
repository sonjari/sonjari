"""그래픽카드가 **모자라서** 모델이 느려지는 때를 알아본다 (2026-10-27 그룹장 실사용 — 16GB 카드 · Swift 27B · 3ds Max/유니티).

## 왜 `/api/ps` 만으로는 모자란가

윈도우(WDDM)에서는 다른 프로그램(3ds Max · 유니티)이 쥔 그래픽카드 메모리를 llama-server 가 못 본다(실측 2026-10-23 · 짐 프로그램이
쥐고 있어도 free 22.8GiB 로 읽음). 그래서 Ollama 는 **다 올렸다고 보고한다**(`size_vram == size`). 모자란 몫은 윈도우 드라이버가
조용히 시스템 메모리로 밀어, 오류 없이 아주 느려진다. `/api/ps` 의 올라간 비율이 100% 여도 느릴 수 있다.

## 그래서 카드 전체 사용량을 본다

`nvidia-smi` 의 `memory.used / memory.total`(카드 전체 — 남의 프로그램 몫이 들어 있다)에서 **남은 메모리**를 본다.

- 남은 메모리가 `FREE_FLOOR_GB` 보다 작으면 「가득 찼다」. 값의 근거: llama-server 는 기본으로 1GiB 를 비워 두고 올린다(10-23 실측,
  `LLAMA_ARG_FIT_TARGET` 의 기본 여유). 손자리 모델만 있으면 남은 메모리는 1GiB 안팎이다. 그 절반(0.5GiB)보다 작으면 다른 프로그램이
  그 여유를 먹었거나 모델이 카드를 넘친 것이다. **16GB 카드에서 실제로 재 본 값이 아니다** — 이 PC 에서는 GPU 판을 못 돌렸다.
- 「남의 몫 = 사용량 − 모델 몫(`size_vram`)」으로는 **셈하지 않는다.** 그 차이의 대부분이 Ollama 자신의 작업 버퍼라 남의 몫을 부풀린다
  (`context_watch.assess` 머리말의 역검증).

## 결과로도 본다

첫 글자까지가 이 PC 평소 값(`data/model_calls.jsonl` 의 같은 모델 앞부분 읽기 속도)보다 크게 늦으면, `nvidia-smi` 가 없거나 실패해도
「느려진 것 같다」고 말한다 — 확정이 아니라 「같습니다」다.
"""

from __future__ import annotations

import json
import statistics
import subprocess
from pathlib import Path
from typing import Any, Callable

#: 카드의 남은 메모리가 이보다 작으면 「가득 찼다」(GiB). 근거는 머리말.
FREE_FLOOR_GB = 0.5
#: 평소 값이 없을 때(첫 설치 · 기록이 모자람) 첫 글자를 이만큼(초) 기다렸으면 늦은 것으로 본다. 평소 첫 글자는 1~5초(`first_token_wait`).
UNKNOWN_LATE_SEC = 60.0
#: 평소 값이 있을 때: 어림한 읽기 시간의 몇 배를 넘으면 늦은 것으로 보는가, 그리고 그래도 이보다는 오래 기다려야 한다(초).
#: 어림은 캐시를 안 쓴 **전체** 토큰으로 한 것이라 실제보다 크다 — 3배면 헛경고가 거의 없다.
LATE_FACTOR = 3.0
LATE_MIN_SEC = 30.0
#: 평소 값을 세는 데 필요한 기록 수 · 읽을 마지막 줄 수.
BASELINE_MIN_ROWS = 5
_TAIL_LINES = 3000


def read_card(run: Callable[..., Any] | None = None) -> dict[str, Any] | None:
    """모델이 올라가는 카드(가장 큰 카드)의 `{used_gb, total_gb, free_gb}`. `nvidia-smi` 가 없거나 실패하면 None.

    기존 `setup_profile._run_nvidia_smi` 를 쓴다(새로 묻는 함수를 만들지 않는다). 제한 시간만 4초로 줄인다 — 카드가 바쁠 때
    이 호출이 길어져도 판의 첫 걸음을 오래 붙잡지 않게.
    """
    from . import setup_profile

    def bounded(args: list[str], **kwargs: Any) -> Any:
        kwargs["timeout"] = 4
        return (run or subprocess.run)(args, **kwargs)

    try:
        cards, _failure = setup_profile._run_nvidia_smi(bounded)
    except Exception:  # noqa: BLE001 — 못 읽으면 「모름」이다
        return None
    cards = [card for card in cards if float(card.get("vram_total_gb") or 0) > 0]
    if not cards:
        return None
    card = max(cards, key=lambda item: (float(item.get("vram_total_gb") or 0), float(item.get("vram_used_gb") or 0)))
    total, used = float(card["vram_total_gb"]), float(card.get("vram_used_gb") or 0)
    return {"used_gb": round(used, 2), "total_gb": round(total, 2), "free_gb": round(total - used, 2),
            "index": card.get("index")}


def card_is_full(card: dict[str, Any] | None) -> bool | None:
    """카드가 가득 찼나. 모르면 None."""
    if not card:
        return None
    return float(card.get("free_gb", 0.0)) < FREE_FLOOR_GB


def usual_prefill_rate(data_dir: Path | str, model: str) -> float | None:
    """이 PC 에서 **같은 모델**이 앞부분을 읽는 평소 속도(토큰/초, 중앙값). 기록이 모자라면 None.

    `model_calls.jsonl` 에서 앞부분이 어느 정도 긴 부르기(2천 토큰 이상)만, 모델을 새로 올린 부르기(`load_sec` 5초 이상)와
    우리가 끊은 부르기(`cut`)는 뺀다. 이 기록은 **끝난 부르기**만 남는다 — 지금 느린 부르기는 아직 안 들어 있다.
    """
    path = Path(data_dir) / "model_calls.jsonl"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-_TAIL_LINES:]
    except OSError:
        return None
    wanted = str(model or "")[-40:]
    rates: list[float] = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or str(row.get("model") or "") != wanted or row.get("cut"):
            continue
        try:
            tokens, seconds, load = int(row.get("prompt_tokens") or 0), float(row.get("prefill_sec") or 0), float(row.get("load_sec") or 0)
        except (TypeError, ValueError):
            continue
        if tokens >= 2000 and seconds >= 0.5 and load < 5.0:
            rates.append(tokens / seconds)
    return statistics.median(rates) if len(rates) >= BASELINE_MIN_ROWS else None


def late_after_sec(tokens: int, rate: float | None) -> float:
    """첫 글자를 이만큼(초) 기다렸으면 「평소보다 크게 늦다」. 평소 값을 모르면 `UNKNOWN_LATE_SEC`."""
    if rate and tokens > 0:
        return max(LATE_MIN_SEC, LATE_FACTOR * tokens / rate)
    return UNKNOWN_LATE_SEC
