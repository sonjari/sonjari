"""찍어 둔 스택에서, 한 판이 도는 동안 잡 스레드가 **어디에 머물렀나**를 시간순으로 (2026-10-07).

`spy_tail.py` 는 사다리 판(모델 호출 기록이 있는 판)용이다. 이것은 아무 판이나 — 잡의 시작·끝 시각만 주면 된다.

    python spy_job_window.py <찍은 파일> <시작 시각(초)> <끝 시각(초)> [스레드를 가리는 낱말=_chat_job]
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BACKSLASH = chr(92)
PATH = re.compile("[(].*[/" + BACKSLASH + BACKSLASH + "]")


def short(frame: str, width: int) -> str:
    return PATH.sub("(", frame)[:width]


def main() -> None:
    dumps = [json.loads(line) for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if line.strip()]
    started, finished = float(sys.argv[2]), float(sys.argv[3])
    marker = sys.argv[4] if len(sys.argv) > 4 else "_chat_job"
    previous, first, count = None, 0.0, 0

    def flush() -> None:
        if previous is not None:
            print(f"  +{first:5.1f}초부터 {count:>3}번  {previous}")

    for dump in dumps:
        at = float(dump["at"])
        if not (started - 0.3 <= at <= finished + 0.5):
            continue
        best: list[str] = []
        for block in re.split(r"\n(?=Thread )", dump["dump"]):
            lines = [line.strip() for line in block.splitlines()[1:] if line.strip()]
            if any(marker in line for line in lines) and len(lines) > len(best):
                best = lines
        app = [short(line, 54) for line in best if "alture_jarvis" in line][:3]
        signature = (short(best[0], 46) if best else "(잡 스레드 없음)") + "  ||  " + " <- ".join(app)
        if signature != previous:
            flush()
            previous, first, count = signature, at - started, 0
        count += 1
    flush()


if __name__ == "__main__":
    main()
