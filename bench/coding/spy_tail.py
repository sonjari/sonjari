# -*- coding: utf-8 -*-
"""찍어 둔 스택에서, 판의 「마지막 모델 호출 뒤 ~ 판 끝」 구간에 잡 스레드가 무엇을 하고 있었나.

쓰기: python spy_tail.py <찍은 파일> <잡 JSON> [구간=tail|gaps|all]
"""
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
dumps = [json.loads(line) for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if line.strip()]
job = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
mode = sys.argv[3] if len(sys.argv) > 3 else "tail"
started, finished = float(job["started_at"]), float(job["finished_at"])
observations = job["result"]["agent_trace"]["verification"]["inference_observations"]
calls = [(float(o["ended_at"]) - float(o["wall_sec"]), float(o["ended_at"])) for o in observations if o.get("ended_at")]
last_end = calls[-1][1] if calls else started
print(f"판 {finished - started:.1f}초 · 모델 호출 {len(calls)}번 · 마지막 호출 끝 +{last_end - started:.1f}초 · 찍은 것 {len(dumps)}개")


def in_window(at: float) -> bool:
    if mode == "all":
        return started <= at <= finished
    if mode == "tail":
        return last_end <= at <= finished + 0.3
    return started <= at <= finished and not any(a <= at <= b for a, b in calls)      # 모델 호출 밖


def job_thread(dump: str) -> list[str]:
    """에이전트 판을 도는 스레드의 프레임(안쪽부터). 없으면 빈 목록."""
    best: list[str] = []
    for block in re.split(r"\n(?=Thread )", dump):
        lines = [line.strip() for line in block.splitlines()[1:] if line.strip()]
        if any("_run_job" in line or "agent.py" in line and " run " in f" {line} " for line in lines) or any(
            re.search(r"\b(run|_execute_job|_process_job|_handle_job)\b.*runtime\.py", line) for line in lines
        ):
            if len(lines) > len(best):
                best = lines
    return best


picked = [(d["at"], job_thread(d["dump"])) for d in dumps if in_window(float(d["at"]))]
print(f"window({mode}) samples {len(picked)}")
PATH = re.compile(r"[(].*[/" + chr(92) + chr(92) + "]")


def short(frame: str, width: int = 66) -> str:
    return PATH.sub("(", frame)[:width]


signatures: Counter[str] = Counter()
for at, frames in picked:
    if not frames:
        signatures["(no job thread)"] += 1
        continue
    app = [f for f in frames if "alture_jarvis" in f or "alture-jarvis" in f]
    chain = " <- ".join(short(f, 58) for f in app[:4])
    signatures[short(frames[0], 70) + "  ||  " + chain] += 1
for signature, count in signatures.most_common(14):
    print(f"  {count:>3}  {signature}")
if mode == "tail" and picked:
    print("--- in time order")
    for at, frames in picked:
        app = [f for f in frames if "alture_jarvis" in f]
        print(f"  +{at - started:5.1f}  {short(frames[0], 58) if frames else '-':<58}  {short(app[0], 70) if app else ''}")
