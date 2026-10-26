"""장표 같이 만들기의 받은 편지함 — 사람이 컴퓨터 칸에서 고른 것 · 고친 것 · 남긴 말 (2026-10-25 대표 2차 시안).

## 흐름 (대표가 고른 2차 시안 그대로)

    결 고르기     모델이 첫 부름에 결 셋(표지 미리보기)을 보이면 사람이 하나를 누른다. 안 누르면 권한 결로 간다.
    이야기판      모델이 장마다 「틀 · 한 줄 주장」을 내면 사람이 끌어 순서를 바꾸고 · 빼고 · 문장을 고친다.
    만들기        장이 한 장씩 그려진다. 다 된 장에 사람이 「한마디」를 남기면 다음 부름의 결과에 실려 모델이 그 장을 고친다.
    잠깐 멈춤     사람이 멈추면 다음 장을 넣기 전에 기다린다.

## 지키는 것

- 기다림은 **앱에서 시킨 판(origin=workspace)만** 한다 — 클로드가 맡긴 판 · 디스코드 판은 보는 사람이 없어 곧바로 넘어간다.
- 기다리는 동안 사람이 만지고 있으면(`touch`) 조금씩 늘리되 상한이 있다 — 사람이 자리를 떠도 판이 영영 서지 않게.
- 판이 취소되면 기다림을 바로 끝낸다(`stop` 함수).
- 화면에서 오는 값은 자료다 — 길이 · 개수를 자르고, 결 이름은 아는 것만 받는다.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

#: 기다림 길이(초) — 시안의 9초 · 14초. 사람이 만지면 한 번에 `TOUCH_GRACE` 씩, 처음부터 `HARD_CAP` 까지 늘린다.
THEME_WAIT = 9.0
OUTLINE_WAIT = 14.0
TOUCH_GRACE = 30.0
HARD_CAP = 180.0
PAUSE_CAP = 600.0
MAX_OUTLINE = 40
MAX_CLAIM = 200
MAX_NOTE = 300

KINDS = ("theme", "outline", "note", "pause", "resume", "touch")


def _key(job_id: str, title: str) -> tuple[str, str]:
    return (str(job_id or "nojob"), str(title or ""))


def clean_outline(value: Any) -> list[dict[str, str]]:
    """이야기판 카드 목록을 안전한 모양으로 — 「틀 · 주장」 둘만, 길이를 자른다."""
    out: list[dict[str, str]] = []
    if not isinstance(value, list):
        return out
    for item in value[:MAX_OUTLINE]:
        if not isinstance(item, dict):
            continue
        claim = " ".join(str(item.get("claim") or "").split())[:MAX_CLAIM]
        layout = str(item.get("layout") or "").strip()[:60]
        if claim or layout:
            out.append({"layout": layout, "claim": claim})
    return out


class DeckInbox:
    """판 · 장표 제목마다 사람의 답을 담는다. 모델 쪽(`local_make_slide`)은 기다리고, 화면 쪽(API)은 넣는다."""

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._answers: dict[tuple[str, str, str], Any] = {}
        self._touched: dict[tuple[str, str], float] = {}
        self._paused: set[tuple[str, str]] = set()
        #: 장 번호 → 사람의 한마디. 「pending」은 아직 모델에게 안 건넨 것, 「given」은 건넸는데 그 장을 아직 다시 안 넣은 것.
        self._pending: dict[tuple[str, str], dict[int, str]] = {}
        self._given: dict[tuple[str, str], dict[int, str]] = {}

    # ── 화면 쪽 ────────────────────────────────────────────────────────────
    def post(self, job_id: str, title: str, kind: str, value: Any = None) -> dict[str, Any]:
        if kind not in KINDS:
            raise ValueError(f"kind_unknown: {kind}")
        key = _key(job_id, title)
        with self._cv:
            if kind == "touch":
                self._touched[key] = time.monotonic()
            elif kind == "pause":
                self._paused.add(key)
            elif kind == "resume":
                self._paused.discard(key)
            elif kind == "note":
                if not isinstance(value, dict):
                    raise ValueError("note_needs_index_and_text")
                try:
                    index = int(value.get("index") or 0)
                except (TypeError, ValueError):
                    raise ValueError("note_index_must_be_number")
                text = " ".join(str(value.get("text") or "").split())[:MAX_NOTE]
                if index < 1 or not text:
                    raise ValueError("note_needs_index_and_text")
                self._pending.setdefault(key, {})[index] = text
            elif kind == "outline":
                cards = clean_outline(value)
                if not cards:
                    raise ValueError("outline_empty")
                self._answers[(*key, kind)] = cards
            else:  # theme
                self._answers[(*key, kind)] = str(value or "").strip()[:80]
            self._cv.notify_all()
        return {"ok": True, "kind": kind}

    # ── 모델 쪽 ────────────────────────────────────────────────────────────
    def expect(self, job_id: str, title: str, kind: str) -> None:
        """이번에 물을 것의 지난 답을 비운다 — 화면에 묻기(알림) **전에** 부른다(알림 직후 누른 답을 잃지 않게)."""
        with self._cv:
            self._answers.pop((*_key(job_id, title), kind), None)

    def wait(self, job_id: str, title: str, kind: str, seconds: float, *,
             stop: Callable[[], bool] | None = None) -> Any:
        """사람의 답(`theme` · `outline`)을 `seconds` 초까지 기다린다. 사람이 만지는 중이면 늘린다. 없으면 None."""
        key = _key(job_id, title)
        slot = (*key, kind)
        start = time.monotonic()
        deadline = start + max(0.0, seconds)
        with self._cv:
            while True:
                if slot in self._answers:
                    return self._answers.pop(slot)
                now = time.monotonic()
                touched = self._touched.get(key, 0.0)
                if touched > start:
                    deadline = min(max(deadline, touched + TOUCH_GRACE), start + HARD_CAP)
                if now >= deadline or (stop is not None and stop()):
                    return None
                self._cv.wait(timeout=min(0.5, deadline - now))

    def hold_while_paused(self, job_id: str, title: str, *, stop: Callable[[], bool] | None = None,
                          cap: float = PAUSE_CAP) -> float:
        """사람이 「잠깐 멈춤」을 눌렀으면 풀릴 때까지(상한 `cap`) 기다린다. 기다린 초를 돌려준다."""
        key = _key(job_id, title)
        start = time.monotonic()
        with self._cv:
            while key in self._paused:
                now = time.monotonic()
                if now - start >= cap or (stop is not None and stop()):
                    self._paused.discard(key)
                    break
                self._cv.wait(timeout=0.5)
        return round(time.monotonic() - start, 1)

    def take_notes(self, job_id: str, title: str) -> dict[int, str]:
        """아직 건네지 않은 한마디를 꺼낸다(건넨 것으로 옮긴다)."""
        key = _key(job_id, title)
        with self._cv:
            notes = self._pending.pop(key, {})
            if notes:
                self._given.setdefault(key, {}).update(notes)
            return dict(sorted(notes.items()))

    def resolve(self, job_id: str, title: str, index: int) -> bool:
        """모델이 그 장을 다시 넣었다 — 그 장의 한마디는 처리됐다. 처리한 말이 있었으면 참."""
        key = _key(job_id, title)
        with self._cv:
            return self._given.get(key, {}).pop(int(index), None) is not None

    def unresolved(self, job_id: str, title: str) -> dict[int, str]:
        """건넸는데 아직 고친 장이 안 온 한마디 + 아직 안 건넨 한마디."""
        key = _key(job_id, title)
        with self._cv:
            merged = {**self._given.get(key, {}), **self._pending.get(key, {})}
            return dict(sorted(merged.items()))

    def forget(self, job_id: str, title: str) -> None:
        key = _key(job_id, title)
        with self._cv:
            for store in (self._touched, self._pending, self._given):
                store.pop(key, None)
            self._paused.discard(key)
            for slot in [slot for slot in self._answers if slot[:2] == key]:
                self._answers.pop(slot, None)
