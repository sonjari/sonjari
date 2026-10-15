"""지금 이 작업이 **무엇을 하는 중인지**를 바깥(MCP 호스트)에게 전하려고 최신 진행 상태만 들고 있는 작은 저장소 (2026-09-22).

## 왜 (사장님 스크린샷, 2026-09-22)

온텔릭 화면은 기다림을 지루하지 않게 한다 — 걸음 표시, 실제 화면, 「시킨 것 2/3」, 근거를 몇 곳에서 읽었는지. 그런데 큰 플랫폼이
우리를 MCP 로 부르면 사용자는 **그 화면이 아니라 호스트 채팅만** 본다. 거기서는 「일하는 중, 0걸음」만 나왔다 — 우리가 만든 기다림 UX 가
호스트 안으로 이어지지 않았다.

그 정보는 이미 있다. 에이전트가 `agent_progress`·`agent_plan` **이벤트로 흘려보낼 뿐**, 어디에도 저장되지 않아 HTTP 로 조회할 수
없었다(화면은 웹소켓으로 받는다). 여기서는 그 두 이벤트의 **최신 값만** 작업별로 들고 있다가 `/v1/jobs/{id}/live` 로 내준다.

## 지킬 것

- **남은 시간 예측은 싣지 않는다.** 화면에는 「3분 남음」이 뜨지만 그 예측이 얼마나 맞는지 재 본 적이 없다(작업 시간이 3배씩 흔들린다).
  틀린 예측을 호스트가 사용자에게 전하면 신뢰를 깎는다 — 재 보기 전에는 넘기지 않는다.
- 최신 값만, 작업당 하나. 작업 수는 상한이 있다(오래된 것부터 버린다).
- 이 저장소는 **어떤 이유로도 발행을 막으면 안 된다** — 이벤트 청취 실패는 삼킨다.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from typing import Any

from .models import EventRecord

#: 화면용 안내문 끝에 붙는 「· 3분 남음」·「· 1분 미만 남음」 — 호스트에게는 넘기지 않는다(위 「지킬 것」).
_ETA = re.compile(r"\s*[·•]\s*(?:\d+\s*분|1분 미만)\s*남음\s*$")

_MAX_JOBS = 64
_ITEMS_MAX = 8
_LABEL_MAX = 60
_SAW_MAX = 80


def without_eta(message: str) -> str:
    """안내문 끝의 남은 시간 표시를 뗀다."""
    return _ETA.sub("", str(message or "")).strip()


class LiveProgress:
    """`agent_progress`·`agent_plan` 이벤트의 작업별 최신 값."""

    def __init__(self, max_jobs: int = _MAX_JOBS) -> None:
        self._max_jobs = max(1, int(max_jobs))
        self._jobs: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._lock = threading.Lock()

    def on_event(self, record: EventRecord) -> None:
        """`EventBus` 청취자. **절대 예외를 던지지 않는다** — 진행 표시 때문에 작업이 죽으면 안 된다."""
        try:
            payload = record.payload or {}
            job_id = str(payload.get("job_id") or "")
            if not job_id or record.event not in ("agent_progress", "agent_plan"):
                return
            with self._lock:
                entry = self._jobs.get(job_id)
                if entry is None:
                    entry = {"job_id": job_id}
                    self._jobs[job_id] = entry
                self._jobs.move_to_end(job_id)
                entry["updated_at"] = float(record.timestamp or time.time())
                if record.event == "agent_progress":
                    entry["phase"] = str(payload.get("phase") or "")
                    entry["doing"] = without_eta(str(payload.get("message") or ""))
                    entry["tool"] = str(payload.get("tool") or "")
                    step = int(payload.get("step") or 0)
                    if step:
                        entry["step"] = max(int(entry.get("step") or 0), step)
                else:
                    items = []
                    for item in (payload.get("items") or [])[:_ITEMS_MAX]:
                        if not isinstance(item, dict):
                            continue
                        items.append({
                            "label": str(item.get("label") or "")[:_LABEL_MAX],
                            "met": bool(item.get("met")),
                            "saw": str(item.get("saw") or "")[:_SAW_MAX],
                        })
                    entry["requested"] = {
                        "met": int(payload.get("met") or 0),
                        "total": int(payload.get("total") or len(items)),
                        "items": items,
                    }
                while len(self._jobs) > self._max_jobs:
                    self._jobs.popitem(last=False)
        except Exception:  # noqa: BLE001 — 청취자는 발행을 막지 않는다
            return

    def snapshot(self, job_id: str) -> dict[str, Any]:
        """이 작업의 최신 진행. 아무것도 못 받았으면 빈 사전."""
        with self._lock:
            entry = self._jobs.get(str(job_id or ""))
            if not entry:
                return {}
            out = dict(entry)
            if isinstance(out.get("requested"), dict):
                out["requested"] = {**out["requested"], "items": [dict(i) for i in out["requested"].get("items", [])]}
            return out
