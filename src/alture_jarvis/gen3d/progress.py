"""trellis-cli 로그 → 단계 · 단계 안 비율 · 정리 숫자 (2026-11-14).

실측 로그(`D:\\models\\img2_3d\\results\\*.log`)에서 확인한 것:
- 단계 줄의 분모가 섞여 찍힌다 — `[1/6] preprocess …` `[2/6]` `[3/6]` 다음에 `[4/7]` … `[7/7] write …`.
  **분모를 믿지 않고 7단계로 고정해 번호로만 맞춘다.**
- 단계 안 세부 진행 `      [flow] [####....]  5/12   9.8s  ~12s left` 는 `\\r` 로 덮어써진다 → 줄 나누기는 `\\r` · `\\n` 둘 다.
  비율(5/12)만 싣는다. 실행기가 찍는 「~12s left」(남은 시간 예측)는 손자리 규칙상 화면에 안 내보낸다 — 아예 읽지 않는다.
- 정리 숫자: `fill_holes: N boundary loops filled` · `dropped N floater comps` + `dropped N more comps` · 끝 줄 `done in 130.1s -> …`.
  실험 기록(거북 t1)의 「구멍 2,567곳 메움 · 조각 77개 지움」= fill_holes 2567 · 69+8 — 같은 셈으로 맞춘다.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from typing import Any

#: 실행기의 단계 수. 로그의 분모(6 · 7)가 섞여 나와 고정한다.
TOTAL_STAGES = 7

_STAGE = re.compile(r"^\s*\[(\d+)/\d+\]\s+(.+?)\s*$")
_FLOW = re.compile(r"^\s*\[flow\]\s+\[[#.]*\]\s+(\d+)/(\d+)\b")
_FILL = re.compile(r"fill_holes:\s+(\d+)\s+boundary loops filled")
_DROP = re.compile(r"dropped\s+(\d+)\s+(?:floater|more)\s+comps")
_DONE = re.compile(r"^\s*done in\s+([\d.]+)s\s+->")
_DECIMATE = re.compile(r"decimate_qem_gpu\(target=(\d+)\)")
# 경로가 들어간 단계 이름(`preprocess D:/…/ship.png (512)` · `write D:/…/x.glb`)은 파일 이름만 남긴다 — 화면 · 영수증에 사용자 폴더가 안 새게.
_PATHISH = re.compile(r"(?:[A-Za-z]:)?[\\/][^\s()]+")


def _short_name(text: str) -> str:
    return _PATHISH.sub(lambda m: PureWindowsPath(m.group(0)).name, text).strip()


def split_lines(buffer: str) -> tuple[list[str], str]:
    """`\\r` · `\\n` 어느 쪽으로 끝나도 한 줄. 끝나지 않은 꼬리는 돌려줘 다음 덩어리에 잇는다."""
    parts = re.split(r"\r\n|\r|\n", buffer)
    return [p for p in parts[:-1]], parts[-1]


@dataclass
class StageTracker:
    """로그 줄을 먹으며 지금 단계 · 지난 단계 시간 · 정리 숫자를 쌓는다. 시각은 `clock` 으로 받는다(시험에서 고정)."""

    clock: Any = time.time
    stage_index: int = 0
    stage_name: str = ""
    stage_started_at: float = 0.0
    sub: dict[str, int] | None = None
    stages: list[dict[str, Any]] = field(default_factory=list)
    holes_filled: int | None = None
    floaters_dropped: int | None = None
    exe_sec: float | None = None
    decimate_target: int | None = None
    tail: list[str] = field(default_factory=list)

    def feed(self, line: str) -> None:
        text = line.rstrip()
        if not text.strip():
            return
        if "[trellis:dbg]" not in text:
            self.tail.append(text)
            del self.tail[:-30]
        stage = _STAGE.match(text)
        if stage and not text.lstrip().startswith("[flow]"):
            index = int(stage.group(1))
            if 1 <= index <= TOTAL_STAGES and index > self.stage_index:
                self._close_stage()
                self.stage_index = index
                self.stage_name = _short_name(stage.group(2))
                self.stage_started_at = float(self.clock())
                self.sub = None
            return
        flow = _FLOW.match(text)
        if flow:
            self.sub = {"done": int(flow.group(1)), "total": int(flow.group(2))}
            return
        if (m := _FILL.search(text)):
            self.holes_filled = (self.holes_filled or 0) + int(m.group(1))
        if (m := _DROP.search(text)):
            self.floaters_dropped = (self.floaters_dropped or 0) + int(m.group(1))
        if (m := _DECIMATE.search(text)):
            self.decimate_target = int(m.group(1))
        if (m := _DONE.match(text)):
            self.exe_sec = float(m.group(1))

    def feed_text(self, text: str) -> None:
        lines, rest = split_lines(text)
        for line in [*lines, rest]:
            self.feed(line)

    def _close_stage(self) -> None:
        if self.stage_index:
            self.stages.append({
                "index": self.stage_index, "name": self.stage_name,
                "sec": round(max(0.0, float(self.clock()) - self.stage_started_at), 2),
            })

    def finish(self) -> None:
        """프로세스가 끝났을 때 — 마지막 단계의 시간을 닫는다."""
        if not self.stages or self.stages[-1]["index"] != self.stage_index:
            self._close_stage()

    def current(self) -> dict[str, Any] | None:
        if not self.stage_index:
            return None
        out: dict[str, Any] = {
            "index": self.stage_index, "total": TOTAL_STAGES, "name": self.stage_name,
            "started_at": self.stage_started_at,
        }
        if self.sub:
            out["sub"] = dict(self.sub)
        return out
