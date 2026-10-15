"""초소를 **돌리는** 자리 — 판정은 `watch.py`, 여기는 언제 돌고 무엇을 하는가.

`gate_watcher.py` 와 같은 모양이다: 별도 스레드가 값싸게 들여다보고, 할 일이 생기면
잡을 큐에 넣는다. 잡이 끝나면 그 잡의 근거로 지문을 만들어 지난번과 대조하고,
달라졌을 때만 사람을 부른다.

## 왜 잡을 큐에 넣나

초소가 직접 브라우저를 몰면 사용자가 시킨 일과 자원을 다툰다. 잡으로 넣으면 기존
순서·승인·되돌리기·관측 보관소를 **그대로** 탄다 — 초소만을 위한 두 번째 길을
만들지 않는다(두 벌을 두면 갈리고, 갈린 쪽이 조용히 틀린다).
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec
from .watch import MIN_INTERVAL_SEC, Watch, WatchStore, items_of, observed, should_notify

EnqueueCallback = Callable[[str, str, dict[str, Any], RiskLevel], dict[str, Any]]

# 몇 초마다 "돌 때가 됐나" 보는가. 초소 자체 주기는 분·시간 단위라 이 값은 작아도 된다.
_TICK_SEC = 30


class WatchService:
    """초소를 돌리고, 달라졌을 때만 말을 건다."""

    def __init__(
        self,
        path: Path,
        events: Any,
        enqueue: EnqueueCallback,
        *,
        job_lookup: Callable[[str], dict[str, Any] | None] | None = None,
        attention: Any = None,
        enabled: bool = True,
    ) -> None:
        # 꺼져 있으면 **세우는 것부터 거절한다.** 목록만 비워 두면, 새로 하나
        # 세우는 순간 「세웠습니다」라고 답해 놓고 영영 안 도는 초소가 생긴다 —
        # 이 저장소가 여러 번 물린 「조용한 무동작」이다.
        self.enabled = bool(enabled)
        self.store = WatchStore(path)
        self.events = events
        self.enqueue = enqueue
        self.job_lookup = job_lookup
        self.attention = attention
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # 돌린 잡 -> 초소. 잡이 끝나면 어느 초소의 것인지 알아야 대조할 수 있다.
        self._pending: dict[str, str] = {}
        self._definitions = self._build_definitions()

    # ── 도구 ────────────────────────────────────────────────────────────
    @staticmethod
    def _function(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required or []},
            },
        }

    def _build_definitions(self) -> list[dict[str, Any]]:
        return [
            self._function(
                "watch_list",
                "지금 세워 둔 관찰 초소 목록. 무엇을 얼마나 자주 보고 있는지, 알림이 얼마나 나갔는지 보여준다.",
                {},
            ),
            self._function(
                "watch_create",
                (
                    "무언가를 주기적으로 보다가 **달라졌을 때만** 먼저 알리도록 초소를 세운다. "
                    "예: '크몽에서 AI 자동화 공고를 하루 두 번 보다가 새 공고가 뜨면 알려줘'. "
                    "달라졌는지는 손자리가 실제로 읽은 것(주소·제목)으로 판정한다 — 답이 아니라 근거로 본다."
                ),
                {
                    "name": {"type": "string", "description": "무엇을 보는 초소인지 짧은 이름"},
                    "prompt": {"type": "string", "description": "매번 돌릴 조사 요청. 평소 시키던 말 그대로"},
                    "every_hours": {"type": "number", "description": "몇 시간마다 볼지. 최소 0.2시간(12분)"},
                },
                ["name", "prompt"],
            ),
            self._function(
                "watch_cancel", "초소를 없앤다.", {"watch_id": {"type": "string"}}, ["watch_id"]
            ),
        ]

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self._definitions}

    def register(self, gateway: ToolGateway) -> None:
        handlers = {
            "watch_list": self.tool_list,
            "watch_create": self.tool_create,
            "watch_cancel": self.tool_cancel,
        }
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["function"]["description"]),
                    # 초소는 **되돌릴 수 있다**(끄면 그만). 다만 세우면 앞으로 자비스가
                    # 스스로 도는 일이 생기므로 읽기(L0)는 아니다.
                    risk_level=RiskLevel.L0 if name == "watch_list" else RiskLevel.L1,
                    handler=handlers[name],
                    enabled=True,
                    parameters=dict(definition["function"].get("parameters") or {}),
                )
            )

    def tool_list(self, arguments: dict[str, Any]) -> dict[str, Any]:
        rows = []
        for watch in self.store.all():
            rows.append({
                "watch_id": watch.id,
                "name": watch.name,
                "every_hours": round(watch.every_sec / 3600, 2),
                "enabled": watch.enabled,
                "last_run_at": watch.last_run_at,
                "watching": len(watch.last_items),
                # `watching: 0` 하나로는 "봤는데 0건"과 "한 번도 못 봤다"가
                # 똑같이 보인다. 위시켓이 눈을 감고 있었는데 목록만 봐서는
                # 알 수 없었던 이유다 — 눈금이 고장을 가리면 없느니만 못하다.
                "baseline_done": watch.baseline_done,
                "missed": watch.missed,
                "blind": bool(not watch.baseline_done),
                "notices": watch.notices,
                "acted": watch.acted,
                "noise_ratio": watch.noise_ratio(),
            })
        return {"action": "watch_list", "count": len(rows), "watches": rows}

    def tool_create(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError(
                "watches_disabled — 이 PC 에서는 관찰 초소가 꺼져 있다"
                "(JARVIS_WATCHES_ENABLED=false). 세워도 돌지 않으니 세우지 마라."
                " 사용자에게 '관찰은 지금 꺼져 있다'고 말하고, 필요하면 켜 달라고 해라."
            )
        name = str(arguments.get("name") or "").strip()
        prompt = str(arguments.get("prompt") or "").strip()
        if not name or not prompt:
            raise ValueError("watch_needs_name_and_prompt")
        hours = float(arguments.get("every_hours") or 6)
        every = max(MIN_INTERVAL_SEC, int(hours * 3600))
        watch = self.store.add(
            Watch(id=uuid.uuid4().hex[:12], name=name, prompt=prompt, every_sec=every)
        )
        return {
            "action": "watch_create",
            "watch_id": watch.id,
            "name": watch.name,
            "every_hours": round(every / 3600, 2),
            # 첫 판은 기준선이라 알림이 안 간다는 사실을 **모델에게도** 알려 준다 —
            # 안 알려 주면 "곧 알려드리겠습니다"라고 답하고 사람은 첫 알림을 기다린다.
            "instruction": (
                "★ 첫 관찰은 기준선을 잡는 것이라 알림이 가지 않는다. "
                "두 번째 관찰부터 달라진 것이 있을 때만 알린다 — 사용자에게 그렇게 말해라."
            ),
        }

    def tool_cancel(self, arguments: dict[str, Any]) -> dict[str, Any]:
        watch_id = str(arguments.get("watch_id") or "")
        gone = self.store.remove(watch_id)
        return {"action": "watch_cancel", "watch_id": watch_id, "removed": gone}

    # ── 도는 부분 ────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="watch-service", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:  # noqa: BLE001 — 초소가 죽어도 자비스는 살아야 한다
                pass
            self._stop.wait(_TICK_SEC)

    def _tick(self) -> None:
        self._collect_finished()
        for watch in self.store.due():
            if watch.id in self._pending.values():
                continue  # 아직 앞 판이 안 끝났다. 겹쳐 돌리지 않는다.
            job = self.enqueue(
                "chat",
                f"[관찰] {watch.name}",
                {"prompt": watch.prompt, "session_id": f"watch-{watch.id}", "origin": "watch"},
                RiskLevel.L0,
            )
            job_id = str(job.get("id") or "")
            if job_id:
                self._pending[job_id] = watch.id
                # 돌린 시각을 **바로** 적는다. 잡이 오래 걸려도 그동안 또 돌리지 않게.
                watch.last_run_at = time.time()
                self.store.update(watch)

    def _collect_finished(self) -> None:
        if not self.job_lookup:
            return
        for job_id, watch_id in list(self._pending.items()):
            job = self.job_lookup(job_id)
            if not job or str(job.get("status")) not in {"completed", "failed", "cancelled"}:
                continue
            self._pending.pop(job_id, None)
            watch = self.store.get(watch_id)
            if not watch:
                continue
            steps = (((job.get("result") or {}).get("agent_trace") or {}).get("steps")) or []
            if not observed(str(job.get("status") or ""), steps):
                # 취소·실패했거나 도구를 한 번도 안 부른 판이다. 이 빈손을
                # "봤는데 0건"으로 적으면 초소가 눈을 감는다 — 실제로 위시켓이
                # 그렇게 됐다(watching 0). 시각만 밀고 지문은 그대로 둔다.
                self.store.record_missed(watch)
                continue
            change = self.store.record_run(watch, items_of(steps))
            if not should_notify(watch, change):
                continue
            self.store.record_notice(watch)
            self.events.publish(
                "watch_changed",
                {
                    "watch_id": watch.id,
                    "name": watch.name,
                    "job_id": job_id,
                    "note": change.note(),
                    "added": change.added[:10],
                    "removed": change.removed[:10],
                },
            )
            if self.attention is not None:
                # 사람을 부르는 길은 하나다(`attention.py`) — 화면·알림·음성이 같은 판정에서.
                try:
                    self.attention.announce(
                        job_id=job_id,
                        code="watch_changed",
                        tool=f"watch:{watch.id}",
                        title=f"{watch.name} — {change.note()}",
                        message=(
                            f"지켜보던 '{watch.name}' 에서 달라진 것이 있습니다: {change.note()}. "
                            "지금 확인하시겠습니까?"
                        ),
                        speech=f"{watch.name}에 {change.note()} 있습니다.",
                    )
                except Exception:  # noqa: BLE001 — 못 부르면 이벤트만 남는다
                    pass
