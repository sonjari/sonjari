"""**관찰 초소** — 자비스가 먼저 말을 거는 자리 (B).

## 무엇이 없었나

자비스는 시킨 일은 잘한다. 정해진 시각에 시켜 둘 수도 있다(`scheduler.py`).
없는 것은 **스스로 보다가 달라지면 먼저 말하는 것**이다. 사용자가 물어보기 전에
"이런 게 바뀌었는데 볼까요?" 하는 자리가 통째로 비어 있었다.

## 판정 규칙 셋 — 이게 이 파일의 전부다

### 1. 모델에게 "달라졌나?"를 묻지 않는다

물으면 매번 다르게 답한다. 산문은 같은 사실을 봐도 문장이 달라지므로, 답을 비교하면
**아무것도 안 바뀐 날에도 바뀌었다고 한다.** 그래서 비교하는 것은 답이 아니라
**근거**다 — 도구가 실제로 가져온 것(주소·제목·행 수).

### 2. 사라진 것도 달라진 것이다

새로 생긴 것만 보면 "공고가 내려갔다"를 놓친다. 들어온 것과 나간 것을 **둘 다** 센다.

### 3. 거짓 알림 비율을 처음부터 잰다

알림은 두 주면 무시당한다. 그러니 처음부터 **알린 횟수와 사용자가 실제로 반응한
횟수**를 같이 적는다. 이 비율이 나쁘면 초소를 끄는 게 맞고, 그 판단도 숫자로 한다.
(이 저장소 규율: 눈금 없이 만든 기능은 언젠가 조용히 쓰레기가 된다.)
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# 한 초소가 기억하는 항목 수. 이보다 많으면 오래된 것부터 잊는다 — 지문은 "지난번과
# 같은가"만 답하면 되므로 전부 들고 있을 이유가 없다.
_MAX_ITEMS = 200

# 너무 자주 보면 사이트가 막고, 너무 뜸하면 놓친다. 최소 10분.
MIN_INTERVAL_SEC = 600


def items_of(steps: list[dict[str, Any]]) -> list[str]:
    """걸음들이 **실제로 가져온 것**을 한 줄씩. 이것이 비교 대상이다.

    답(산문)이 아니라 근거를 본다. 주소는 추적 인자를 떼고, 제목은 앞부분만 —
    같은 것이 매번 다른 문자열로 보이면 지문이 매번 달라진다.
    """
    found: list[str] = []
    for step in steps:
        evidence = step.get("evidence")
        if not isinstance(evidence, dict):
            continue
        url = str(evidence.get("url") or "").split("?")[0].rstrip("/")
        title = " ".join(str(evidence.get("title") or "").split())[:80]
        if url or title:
            found.append(f"{url}|{title}")
    # 순서는 판마다 다를 수 있다. 무엇을 봤는지가 요점이므로 정렬해서 센다.
    return sorted(set(found))[:_MAX_ITEMS]


def observed(job_status: str, steps: list[dict[str, Any]]) -> bool:
    """이 판이 **실제로 보기는 했는가.**

    빈손에는 두 종류가 있고, 둘을 섞으면 초소가 눈을 감는다:

      "봤는데 0건"   — 도구가 돌았고 목록이 비어 있었다. 이건 관측이다.
      "못 봤다"      — 판이 취소·실패했거나 도구를 한 번도 안 불렀다. 관측이 아니다.

    2026-08-20 실측: 위시켓 초소의 판이 **cancelled** 였는데(걸음 0개) 그 빈손이
    기준선으로 적혔다. `watching 0` 이 그 자국이다. 그대로 뒀으면 다음 관찰에서
    위시켓에 뭐가 있든 전부 "새로 N건"으로 알렸을 것이다 — 첫 알림부터 거짓이고,
    알림은 두 번 헛치면 무시당한다.

    ★ 이 저장소가 같은 모양의 버그를 고친 적이 있다: 안 끝난 판을 실패로 적던 것.
    끝나지 않은 것을 **아무 값으로도** 적지 않는 것이 규칙이다.

    걸음이 하나라도 있으면 관측으로 친다 — 검색 결과가 진짜 0건인 사이트를
    "못 봤다"로 몰면 그 초소는 영원히 기준선을 못 잡는다.
    """
    return job_status == "completed" and bool(steps)


def fingerprint(items: list[str]) -> str:
    """이 관찰의 지문. 같은 것을 봤으면 같은 값."""
    blob = "\n".join(items)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class Change:
    """지난번과 무엇이 달라졌나."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    # 이 관측이 **첫 판**인가. 첫 판은 전부 "새로 생긴 것"이라 알릴 것이 아니다.
    # ★ 판정을 초소(watch)가 아니라 **관측**이 들고 있어야 한다 — `record_run` 이
    #   기준선 표시를 켠 뒤에 물어보면 첫 판도 "알려야 한다"가 나온다(실제로 그랬다).
    baseline: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)

    def note(self) -> str:
        """사람에게 보여 줄 한 줄. **숫자를 먼저** 말한다."""
        parts: list[str] = []
        if self.added:
            parts.append(f"새로 {len(self.added)}건")
        if self.removed:
            parts.append(f"사라진 것 {len(self.removed)}건")
        return " · ".join(parts) if parts else "달라진 것 없음"


def diff(before: list[str], after: list[str]) -> Change:
    """들어온 것과 나간 것을 **둘 다** 센다.

    새로 생긴 것만 보면 "공고가 내려갔다"·"재고가 빠졌다"를 놓친다.
    """
    old, new = set(before), set(after)
    return Change(added=sorted(new - old), removed=sorted(old - new))


@dataclass
class Watch:
    """초소 하나."""

    id: str
    name: str
    prompt: str
    every_sec: int
    enabled: bool = True
    created_at: float = 0.0
    last_run_at: float = 0.0
    last_items: list[str] = field(default_factory=list)
    last_fingerprint: str = ""
    # 눈금 — 알린 횟수와 그중 사용자가 실제로 움직인 횟수.
    notices: int = 0
    acted: int = 0
    # 처음 한 판은 **기준선**이다. 그때는 알리지 않는다 — 처음 본 것은 전부
    # "새로 생긴 것"이라 알림이 무의미하게 커진다.
    baseline_done: bool = False
    # 보지도 못하고 끝난 판의 수. 0 이 아닌데 `baseline_done` 이 False 면 그
    # 초소는 **눈을 감고 있다** — 조용히 그러고 있지 않도록 세어서 내보낸다.
    missed: int = 0

    def due(self, now: float) -> bool:
        if not self.enabled:
            return False
        return (now - self.last_run_at) >= max(MIN_INTERVAL_SEC, self.every_sec)

    def noise_ratio(self) -> float | None:
        """알림 중 헛것의 비율. 표본이 적으면 `None` — 3건으로 비율을 말하지 않는다."""
        if self.notices < 5:
            return None
        return round(1 - (self.acted / self.notices), 2)


def should_notify(watch: Watch, change: Change) -> bool:
    """알릴 것인가.

    - 기준선을 아직 안 잡았으면 **안 알린다**(처음 본 것은 전부 새것이다)
    - 달라진 것이 없으면 안 알린다
    """
    if change.baseline or not watch.baseline_done:
        return False
    return change.changed


class WatchStore:
    """초소 목록. 파일 하나에 담는다 — 몇 개 되지 않고, 사람이 열어 볼 수 있어야 한다."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._watches: dict[str, Watch] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for row in raw.get("watches", []):
            try:
                self._watches[str(row["id"])] = Watch(**row)
            except (TypeError, KeyError):
                continue

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"watches": [asdict(w) for w in self._watches.values()]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, watch: Watch) -> Watch:
        with self._lock:
            watch.created_at = watch.created_at or time.time()
            self._watches[watch.id] = watch
            self._save()
        return watch

    def get(self, watch_id: str) -> Watch | None:
        return self._watches.get(watch_id)

    def all(self) -> list[Watch]:
        return list(self._watches.values())

    def due(self, now: float | None = None) -> list[Watch]:
        moment = now if now is not None else time.time()
        return [w for w in self._watches.values() if w.due(moment)]

    def update(self, watch: Watch) -> None:
        with self._lock:
            self._watches[watch.id] = watch
            self._save()

    def remove(self, watch_id: str) -> bool:
        with self._lock:
            gone = self._watches.pop(watch_id, None) is not None
            if gone:
                self._save()
        return gone

    def record_run(self, watch: Watch, items: list[str]) -> Change:
        """한 판 돌고 난 뒤. 달라진 것을 돌려주고 기준선을 갱신한다."""
        change = diff(watch.last_items, items)
        change.baseline = not watch.baseline_done
        watch.last_items = items
        watch.last_fingerprint = fingerprint(items)
        watch.last_run_at = time.time()
        if not watch.baseline_done:
            # 첫 판은 기준선을 잡는 것으로 끝난다.
            watch.baseline_done = True
        self.update(watch)
        return change

    def record_missed(self, watch: Watch) -> None:
        """못 본 판. **지문을 건드리지 않는다** — 그게 이 메서드의 전부다.

        다음 판을 위해 시각만 앞으로 민다. 기준선은 그대로 남으므로, 첫 판을
        놓친 초소는 기준선이 없는 상태로 남고(다음 성공한 판이 기준선이 된다),
        이미 기준선이 있는 초소는 그것을 잃지 않는다.
        """
        watch.missed += 1
        watch.last_run_at = time.time()
        self.update(watch)

    def record_notice(self, watch: Watch) -> None:
        watch.notices += 1
        self.update(watch)

    def record_acted(self, watch_id: str) -> None:
        """사용자가 그 알림을 보고 실제로 무언가 했다. 헛알림 비율의 분자다."""
        watch = self._watches.get(watch_id)
        if watch:
            watch.acted += 1
            self.update(watch)
