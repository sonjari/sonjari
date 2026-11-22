"""`sd-cli` 로그 → 단계 · 그리기 비율 · 단계 초 (2026-11-16).

실측 로그(`D:\\models\\video\\out_1116\\night\\p1_fast.log` · `ltx\\p1_ltx.log`)에서 확인한 줄:
- `[I] loading diffusion model from '…'`                       → 1 올리기
- `[I] get_learned_condition completed, taking 40.69s`          → 2 글 읽기 끝(초)
- `  |====>   | 1/3 -   8.08s/it - ETA 00:16` (`\\r` 덮어쓰기)   → 3 그리기 · 비율 1/3 (ETA 는 읽지 않는다 — 손자리 규칙)
- `[I] sampling completed, taking 15.08s`                        → 그리기 끝(초)
- `[I] decode_first_stage completed, taking 1.13s`               → 4 풀기 끝(초)
- `[I] generate_video completed in 57.14s`                       → 실행기가 센 전체(초)
- `[I] save result video to '…'`                                 → 5 저장
- `[E] …` 줄은 마지막 오류로 남긴다.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

STAGES = ("올리기", "글 읽기", "그리기", "풀기", "저장")
TOTAL_STAGES = len(STAGES)

_LOAD = re.compile(r"\[I\]\s+loading (?:diffusion model|t5xxl|llm)\b")
_COND = re.compile(r"get_learned_condition completed, taking\s+([\d.]+)s")
_BAR = re.compile(r"\|[=>\s.-]*\|\s*(\d+)/(\d+)\b")
_SAMPLE = re.compile(r"\[I\]\s+sampling completed, taking\s+([\d.]+)s")
_DECODE = re.compile(r"decode_first_stage completed, taking\s+([\d.]+)s")
_TOTAL = re.compile(r"generate_video completed in\s+([\d.]+)s")
_SAVE = re.compile(r"save result video to")
_ERROR = re.compile(r"^\s*\[E\]\s*(.+?)(?:\s+---\s+\S+)?\s*$")


def split_lines(buffer: str) -> tuple[list[str], str]:
    parts = re.split(r"\r\n|\r|\n", buffer)
    return parts[:-1], parts[-1]


@dataclass
class VideoTracker:
    clock: Any = time.time
    stage_index: int = 0
    stage_started_at: float = 0.0
    sub: dict[str, int] | None = None
    text_sec: float | None = None
    sample_sec: float | None = None
    decode_sec: float | None = None
    exe_sec: float | None = None
    saved: bool = False
    last_error: str | None = None
    #: 모든 `[E]` 줄(최대 20). 마지막 줄은 대개 「ggml: err」 같은 꼬리라 뜻이 없다 — `error_summary` 가 뜻 있는 줄을 고른다.
    errors: list[str] = field(default_factory=list)
    stages: list[dict[str, Any]] = field(default_factory=list)
    tail: list[str] = field(default_factory=list)

    def _to(self, index: int) -> None:
        if index <= self.stage_index:
            return
        if self.stage_index:
            self.stages.append({"index": self.stage_index, "name": STAGES[self.stage_index - 1],
                                "sec": round(max(0.0, float(self.clock()) - self.stage_started_at), 2)})
        self.stage_index = index
        self.stage_started_at = float(self.clock())
        self.sub = None

    def feed(self, line: str) -> None:
        text = line.rstrip()
        if not text.strip():
            return
        if not text.lstrip().startswith("[V]"):
            self.tail.append(text[:300])
            del self.tail[:-20]
        if _LOAD.search(text):
            self._to(1)
            return
        if (m := _COND.search(text)):
            self.text_sec = float(m.group(1))
            self._to(3)
            return
        bar = _BAR.search(text)
        if bar and ("s/it" in text or "it/s" in text):
            m = bar
            self._to(3)
            self.sub = {"done": int(m.group(1)), "total": int(m.group(2))}
            return
        if (m := _SAMPLE.search(text)):
            self.sample_sec = float(m.group(1))
            self._to(4)
            return
        if (m := _DECODE.search(text)):
            self.decode_sec = float(m.group(1))
            return
        if (m := _TOTAL.search(text)):
            self.exe_sec = float(m.group(1))
            self._to(5)
            return
        if _SAVE.search(text):
            self.saved = True
            self._to(5)
            return
        if (m := _ERROR.match(text)):
            self.last_error = m.group(1)[:300]
            self.errors.append(self.last_error)
            del self.errors[:-20]

    def begin_text(self) -> None:
        """글 읽기 시작은 로그에 뚜렷한 줄이 없어 첫 모델 올리기가 끝난 뒤(`loading tensors completed`) 2로 본다."""
        if self.stage_index == 1:
            self._to(2)

    def feed_text(self, text: str) -> None:
        lines, rest = split_lines(text)
        for line in [*lines, rest]:
            self.feed(line)
            if "loading tensors completed" in line:
                self.begin_text()

    def finish(self) -> None:
        if self.stage_index and (not self.stages or self.stages[-1]["index"] != self.stage_index):
            self.stages.append({"index": self.stage_index, "name": STAGES[self.stage_index - 1],
                                "sec": round(max(0.0, float(self.clock()) - self.stage_started_at), 2)})

    def current(self) -> dict[str, Any] | None:
        if not self.stage_index:
            return None
        out: dict[str, Any] = {"index": self.stage_index, "total": TOTAL_STAGES, "name": STAGES[self.stage_index - 1]}
        if self.sub:
            out["sub"] = dict(self.sub)
        return out

    @property
    def out_of_memory(self) -> bool:
        return any("out of memory" in line.lower() for line in self.errors)

    def error_summary(self) -> str | None:
        """뜻 있는 오류 한 줄: 메모리 부족 > 「failed」 줄 > 첫 [E] 줄(11-16: 마지막 줄 「ggml:   err」만 영수증에 실렸다)."""
        for key in ("out of memory", "failed", "error"):
            for line in self.errors:
                if key in line.lower():
                    return line
        return self.errors[0] if self.errors else None

    def numbers(self) -> dict[str, Any]:
        """실행기가 찍은 단계 초(그대로 옮김 · 없으면 None)."""
        return {"text_sec": self.text_sec, "sample_sec": self.sample_sec, "decode_sec": self.decode_sec, "exe_sec": self.exe_sec}
