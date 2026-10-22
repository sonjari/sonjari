"""첫 글자 전 기다림을 사람에게 보인다 (2026-10-21 대표 지시 · 「기다림 표시 둘」 중 손자리 쪽).

## 왜

대표: 「처음 생각 토큰까지 너무 오래 — 제일 짜증」. 같은 날 밤 22시 예약 판(레딧 살피기)의 실측(`data/model_calls.jsonl`):

    22:06  첫 글자 51초 · 앞의 기록 5.8만 토큰
    22:12  첫 글자 33초 · 7.4만 토큰
    22:14  첫 글자 88초 · 7.1만 토큰

그동안 화면은 바로 앞 걸음 글(「결과 목록을 읽었습니다」)에 멈춰 있었다. 사람은 「멈췄다」로 읽는다.
모델은 멈춘 게 아니라 **앞의 기록을 처음부터 다시 읽고 있었다**(앞부분이 캐시에 남으면 7만 토큰도 1~3초).

## 무엇을 하나

부르기 뒤 `DELAY_SEC` 가 지나도 첫 조각이 안 오면, 그 판의 **마지막 걸음 줄**의 글을 잠깐 바꾼다:
「모델이 앞의 기록(약 7만 토큰)을 읽는 중 · 첫 글자 전 15초째」. `EVERY_SEC` 마다 초를 고친다.
첫 조각이 오거나 부르기가 끝나면 그 줄을 원래 글로 되돌린다 — 새 줄을 만들지 않아 걸음 기록에 쓰레기가 안 남는다.

## 말하지 않는 것

- **남은 시간.** 재 본 적이 없다(손자리는 남은 시간을 예측해 주지 않는다). 지난 초만 센다.
- **「압축 중」.** 손자리의 접기는 즉시 끝난다. 실제 기다림은 첫 글자 전이다.
- 토큰 수는 같은 판 · 같은 역할 · 같은 도구 목록의 **지난 부르기에서 서버가 준 값**(글자당 토큰)으로만 어림한다.
  잰 값이 없으면 수를 말하지 않는다.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

#: 이보다 빨리 오면 아무것도 안 한다 — 평소 첫 글자는 1~5초(같은 밤 기록).
DELAY_SEC = 5.0
EVERY_SEC = 5.0
#: 이보다 짧은 기록은 「긴 기록」이라 부르지 않는다(읽기가 기다림의 까닭이 아닐 수 있다).
LONG_TOKENS = 15_000


def tokens_label(tokens: int, english: bool = False) -> str:
    """71234 → 「약 7.1만 토큰」 / 「~71k tokens」."""
    tokens = max(0, int(tokens))
    if english:
        return f"~{round(tokens / 1000):,}k tokens" if tokens >= 1000 else f"~{tokens} tokens"
    if tokens >= 10_000:
        man = tokens / 10_000
        text = f"{man:.0f}" if man >= 10 or abs(man - round(man)) < 0.05 else f"{man:.1f}"
        return f"약 {text}만 토큰"
    if tokens >= 1_000:
        return f"약 {round(tokens / 1000)}천 토큰"
    return f"약 {tokens} 토큰"


def estimate_tokens(sent_chars: int, measured: tuple[int, int] | None) -> int:
    """지난 부르기의 (보낸 글자, 서버가 센 토큰)으로 이번 기록의 토큰을 어림한다. 잰 값이 없으면 0."""
    if not measured:
        return 0
    chars, tokens = measured
    if chars <= 0 or tokens <= 0:
        return 0
    return int(sent_chars * tokens / chars)


def wait_message(tokens: int, elapsed: float, english: bool = False) -> str:
    seconds = int(elapsed)
    if tokens >= LONG_TOKENS:
        if english:
            return f"The model is reading the earlier record ({tokens_label(tokens, True)}) · {seconds}s before the first word"
        return f"모델이 앞의 기록({tokens_label(tokens)})을 읽는 중 · 첫 글자 전 {seconds}초째"
    if english:
        return f"Waiting for the model's first word · {seconds}s"
    return f"모델의 첫 글자를 기다리는 중 · {seconds}초째"


class FirstTokenWatch:
    """부르기 하나를 지켜본다. `seen()` 은 첫 조각에서, `close()` 는 부르기가 끝나면(예외여도) 부른다.

    `last` 는 그 판의 마지막 걸음 알림(payload) — 없으면 아무것도 안 한다(바꿀 줄이 없다).
    `publish(payload)` 는 `agent_progress` 를 내보내는 함수. 예외는 삼킨다 — 표시 때문에 판이 죽으면 안 된다.
    """

    def __init__(self, *, last: dict[str, Any] | None, tokens: int, english: bool,
                 publish: Callable[[dict[str, Any]], None],
                 delay: float | None = None, every: float | None = None) -> None:
        self._last = dict(last) if last else None
        self._tokens = tokens
        self._english = english
        self._publish = publish
        self._delay = DELAY_SEC if delay is None else delay
        self._every = EVERY_SEC if every is None else every
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._shown = False
        self._started = time.monotonic()
        self._thread: threading.Thread | None = None
        if self._last is not None:
            self._thread = threading.Thread(target=self._run, name="first-token-wait", daemon=True)
            self._thread.start()

    @property
    def shown(self) -> bool:
        return self._shown

    def _send(self, payload: dict[str, Any]) -> None:
        try:
            self._publish(payload)
        except Exception:  # noqa: BLE001 — 진행 표시는 판을 막지 않는다
            pass

    def _run(self) -> None:
        wait = self._delay
        while not self._stop.wait(wait):
            with self._lock:
                if self._stop.is_set() or self._last is None:
                    return
                elapsed = time.monotonic() - self._started
                self._send({**self._last, "message": wait_message(self._tokens, elapsed, self._english),
                            "waiting_first_token": True})
                self._shown = True
            wait = self._every

    def seen(self) -> None:
        """첫 조각이 왔다 — 바꿔 둔 줄을 되돌린다. 두 번 불러도 한 번만."""
        with self._lock:
            if self._stop.is_set():
                return
            self._stop.set()
            if self._shown and self._last is not None:
                self._send(self._last)

    close = seen
