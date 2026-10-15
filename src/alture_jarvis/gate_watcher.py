"""사람이 문을 열었는지 지켜보다가, 열리면 작업을 스스로 이어 붙인다.

`human_gate.py` 가 "무엇이 막혔고 어떻게 판정하는가"라면 여기는 "언제 보고 무엇을
할 것인가"다.

왜 별도 스레드인가: 잡은 직렬로 돈다(JobRunner 스레드 하나). 막힌 잡이 워커를 쥔 채
기다리면 그동안 다른 요청이 전부 멈춘다. 그래서 막히는 순간 체크포인트를 남기고
워커를 **놓고**, 지켜보는 일은 여기서 따로 한다.

값싸게 본다: 20초에 한 번, 페이지에 말을 걸지 않고 이미 있는 것만 읽는다
(`BrowserWorker.gate_state`). 브라우저가 바쁘면 그냥 모른다고 답하고 다음 차례에
다시 본다 — 확인하려고 줄을 서면 그 자체가 작업을 늦춘다.

기다림에는 끝이 있다. 사용자가 자리를 비우셨을 수도 있고, 그 문을 오늘 안 여실
수도 있다. 그때는 지금까지 확인한 것으로 답을 내고 끝낸다 — 영영 매달려 있는
작업이 제일 나쁘다.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .human_gate import is_cleared
from .models import JobStatus


class HumanGateWatcher:
    def __init__(
        self,
        store: Any,
        browser: Any,
        agent: Any,
        events: Any,
        *,
        poll_sec: float = 20.0,
        give_up_sec: float = 900.0,
    ) -> None:
        self.store = store
        self.browser = browser
        self.agent = agent
        self.events = events
        self.poll_sec = poll_sec
        self.give_up_sec = give_up_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._claimed: set[tuple[str, str]] = set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="jarvis-gate-watcher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                # 지켜보다 넘어져도 자비스가 멈추면 안 된다. 다음 차례에 다시 본다.
                pass
            self._stop.wait(self.poll_sec)

    def waiting_gates(self) -> list[dict[str, Any]]:
        """사람을 기다리는 중인 잡들. `reason` 에 문 종류가 실려 있다."""
        rows: list[dict[str, Any]] = []
        for job in self.store.list_jobs(limit=50):
            if str(job.get("status") or "") != JobStatus.WAITING_CONTINUATION.value:
                continue
            checkpoint = self.store.get_agent_checkpoint(str(job["id"]))
            if not checkpoint:
                continue
            code = str(checkpoint.get("gate_code") or "")
            if not code:
                continue
            details = dict(checkpoint.get("gate_evidence") or {})
            rows.append(
                {
                    "job_id": str(job["id"]),
                    "code": code,
                    "url": str(checkpoint.get("gate_url") or ""),
                    "since": float(checkpoint.get("gate_since") or job.get("updated_at") or 0),
                    **details,
                }
            )
        return rows

    def tick(self) -> int:
        """한 바퀴. 이어 붙인 잡 수를 돌려준다."""
        gates = self.waiting_gates()
        if not gates:
            return 0
        resumed = 0
        now = time.time()
        for gate in gates:
            key = (
                gate["job_id"],
                str(gate.get("fingerprint") or gate.get("since") or "legacy"),
            )
            if key in self._claimed:
                continue
            # 체크포인트가 가리킨 탭을 읽는다. 프로세스 재기동이나 사람이 다른 탭을
            # 본 뒤에도 임의의 현재 탭 하나로 모든 대기 작업을 판정하면 안 된다.
            state = self.browser.gate_state(gate)
            if is_cleared(gate, state):
                if self._resume(gate, "gate_cleared", "continue_task"):
                    self._claimed.add(key)
                    resumed += 1
            elif gate["since"] and now - gate["since"] >= self.give_up_sec:
                # 영영 매달려 있는 작업이 제일 나쁘다. 가진 것으로 답하고 끝낸다.
                if self._resume(gate, "gate_timeout", "finish"):
                    self._claimed.add(key)
        return resumed

    def _resume(self, gate: dict[str, Any], why: str, action: str) -> bool:
        if why == "gate_cleared":
            self._hand_back_the_stage()
        try:
            self.agent.continue_job(gate["job_id"], action, reason=why)
        except Exception:
            return False
        self.events.publish(
            "agent_gate_resumed",
            {"job_id": gate["job_id"], "code": gate["code"], "reason": why, "action": action},
        )
        return True

    def _hand_back_the_stage(self) -> None:
        """사람이 무대에서 문을 열었으면 **쥔 손을 놓아 준다** (2026-09-26).

        안 놓으면 이어 붙인 잡의 첫 브라우저 걸음이 「사람이 쥐고 있음」에 걸려, 로그인을 끝낸 사람이
        「돌려주기」를 따로 누르거나 2분 무입력까지 멈춰 보인다. 다시 만지면 그 순간 다시 넘겨받는다.
        """
        view = getattr(self.browser, "live_view", None)
        try:
            if view is not None and view.human_in_control():
                view.release_control("gate_cleared")
        except Exception:  # noqa: BLE001 — 돌려주기 실패가 이어 붙이기를 막으면 안 된다
            pass
