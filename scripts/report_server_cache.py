"""**판 하나의 읽기가 어디서 새나** — 서버(llama-server) 기록과 판 기록을 맞대 호출마다 가른다 (2026-10-19).

    python scripts/report_server_cache.py --job 1b6df02d            판 하나를 호출별로
    python scripts/report_server_cache.py --job 1b6df02d,fa031a4c   여럿을 한 줄씩

## 왜 있나

판 기록(`model_time`)은 호출마다 「읽기 몇 초 · 쓰기 몇 초」만 안다. **왜** 읽었는지(새 글만 읽었나 · 처음부터 다시 읽었나 ·
중간 자리로 되돌아가 뒤를 다 읽었나)와 **끊고 버린 호출**은 서버 기록에만 있다. 긱뉴스 판(1b6df02d · 699초)에서 판 기록으로는
196초가 「나머지」였는데, 서버 기록을 맞대니 끊고 버린 생성 두 번(약 137초)과 처음부터 다시 읽기 두 번(31 · 76초)이 보였다.

## 맞대는 법

서버 기록(`C:\\RoboMetaFit\\logs\\ollama_server.log` — 워치독이 띄운 서버의 표준 오류, 시각이 없다)을 요청(task) 단위로 자르고,
판 기록의 프롬프트 토큰 수(창 맞춤 감사 기록 + 관측)를 차례로 찾아 그 판의 요청 구간을 정한다. 시각이 없어서 **토큰 수로** 맞춘다 —
`hit/known` 이 작으면 맞대기가 틀린 것이니 그 줄을 믿지 않는다. 판 기록과 서버 기록의 읽기 · 쓰기 합이 같은지(양쪽 표본)로 맞대기를 확인했다
(1b6df02d: 서버 171초 · 판 171초 / 304초 · 304초).

이 도구는 **판단하지 않는다.** 세고 보여 준다. 읽기 전용이다(판 기록은 `?mode=ro`).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

_DB = Path("C:/RoboMetaFit/tools/alture-jarvis/data/jarvis.db")
_LOG = Path("C:/RoboMetaFit/logs/ollama_server.log")
#: 끊긴 요청은 서버가 쓰기 시간을 안 적는다 — 쓴 토큰을 이 속도(이 PC · 27B · 3090 의 초당 토큰 중앙 근처)로 나눠 어림한다.
_GEN_TOKENS_PER_SEC = 62.0


def parse_tasks(lines: Any) -> list[dict[str, Any]]:
    """서버 기록 줄들을 요청 단위로 묶는다. 요청마다 프롬프트 크기 · 되살린 자리 · 다시 읽었나 · 읽기 · 쓰기 · 끊겼나."""
    tasks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    pending: dict[str, Any] = {}
    for line in lines:
        found = re.search(r"prompt with length\s+(\d+), lcp =\s+(\d+)", line)
        if found:
            pending["best_lcp"] = max(int(pending.get("best_lcp") or 0), int(found.group(2)))
            continue
        if "found better prompt" in line:
            pending["cache_loaded"] = True
        found = re.search(r"task (\d+) \| new prompt.*task.n_tokens = (\d+)", line)
        if found:
            current = {"task": int(found.group(1)), "n": int(found.group(2)), **pending}
            pending = {}
            tasks.append(current)
            continue
        if current is None:
            continue
        found = re.search(r"restored context checkpoint .*n_past = (\d+)", line)
        if found:
            current["restored"] = int(found.group(1))
        if "forcing full prompt re-processing" in line:
            current["full"] = True
        found = re.search(r"prompt eval time =\s+([\d.]+) ms /\s+(\d+) tokens", line)
        if found:
            current["read_sec"], current["read_tokens"] = float(found.group(1)) / 1000, int(found.group(2))
        found = re.search(r"\s eval time =\s+([\d.]+) ms /\s+(\d+) tokens", line)
        if found:
            current["gen_sec"], current["gen_tokens"] = float(found.group(1)) / 1000, int(found.group(2))
        found = re.search(r"stop processing: n_tokens = (\d+)", line)
        if found:
            current["stop_n"] = int(found.group(1))
        if "cancel" in line.lower() and "task" in line:
            current["cancelled"] = True
    return tasks


def classify(task: dict[str, Any], previous_n: int) -> str:
    """요청 하나의 읽기 종류. full = 처음부터 · rewind = 앞 대화보다 한참 앞 자리로 되돌아가 뒤를 다 읽음 · append = 새 글만."""
    if task.get("full"):
        return "full"
    restored = task.get("restored")
    if previous_n and restored is not None and restored < previous_n - 1500 and int(task.get("read_tokens") or 0) > 3000:
        return "rewind"
    return "append"


def job_tasks(con: sqlite3.Connection, tasks: list[dict[str, Any]], job_prefix: str) -> tuple[dict[str, Any], list[dict[str, Any]], int, int]:
    row = con.execute("select * from jobs where id like ?", (job_prefix + "%",)).fetchone()
    if row is None:
        raise SystemExit(f"그런 판이 없습니다: {job_prefix}")
    verification = (json.loads(row["result_json"] or "{}").get("agent_trace") or {}).get("verification") or {}
    fitted = [
        int(json.loads(payload)["prompt_tokens"])
        for (payload,) in con.execute(
            "select payload_json from audit_log where subject_id=? and event like 'agent_transcript_%_to_window' order by id",
            (row["id"],),
        )
    ]
    observed = [int((o.get("telemetry") or {}).get("prompt_eval_count") or 0) for o in verification.get("inference_observations") or []]
    known = {value for value in fitted + observed if value}
    if not known:
        return dict(row), [], 0, 0
    first = fitted[0] if fitted else observed[0]
    last = next((value for value in reversed(observed) if value), fitted[-1] if fitted else first)
    best: tuple[int, int, int] | None = None
    for end, task in enumerate(tasks):
        if task["n"] != last:
            continue
        starts = [i for i in range(max(0, end - 400), end + 1) if tasks[i]["n"] == first]
        if not starts:
            continue
        start = starts[-1]
        hits = sum(1 for item in tasks[start:end + 1] if item["n"] in known)
        if best is None or (hits, start - end) > (best[2], best[0] - best[1]):
            best = (start, end, hits)
    if best is None:
        return dict(row), [], 0, len(known)
    return dict(row), tasks[best[0]:best[1] + 1], best[2], len(known)


def summarize(row: dict[str, Any], picked: list[dict[str, Any]]) -> dict[str, Any]:
    out = {"full_sec": 0.0, "full_n": 0, "rewind_sec": 0.0, "rewind_n": 0, "append_sec": 0.0, "gen_sec": 0.0, "gen_tokens": 0,
           "cut_n": 0, "cut_tokens": 0}
    previous = 0
    for task in picked:
        if task["n"] < 1000:  # 곁가지 짧은 호출(분류기 등)
            continue
        if task.get("cancelled"):
            out["cut_n"] += 1
            out["cut_tokens"] += max(0, int(task.get("stop_n") or task["n"]) - task["n"])
        kind = classify(task, previous)
        out[f"{kind}_sec"] += float(task.get("read_sec") or 0)
        if kind != "append":
            out[f"{kind}_n"] += 1
        out["gen_sec"] += float(task.get("gen_sec") or 0)
        out["gen_tokens"] += int(task.get("gen_tokens") or 0)
        previous = task["n"]
    out["cut_sec_est"] = out["cut_tokens"] / _GEN_TOKENS_PER_SEC
    out["elapsed"] = float(row["finished_at"] or 0) - float(row["started_at"] or 0)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="서버 기록과 판 기록을 맞대 읽기 종류를 가른다")
    parser.add_argument("--job", required=True, help="판 id 앞부분(쉼표로 여럿)")
    parser.add_argument("--db", default=str(_DB))
    parser.add_argument("--log", default=str(_LOG))
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with open(args.log, encoding="utf-8", errors="replace") as handle:
        tasks = parse_tasks(handle)
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    ids = [part.strip() for part in args.job.split(",") if part.strip()]
    for job in ids:
        row, picked, hits, known = job_tasks(con, tasks, job)
        if not picked:
            print(f"{job}: 서버 기록에서 못 찾음(기록이 넘어갔거나 맞대기 실패)")
            continue
        s = summarize(row, picked)
        print(f"{job} | 판 {s['elapsed']:.0f}초 | 처음부터 다시 읽기 {s['full_n']}번 {s['full_sec']:.0f}초"
              f" | 중간 자리로 되돌아가 읽기 {s['rewind_n']}번 {s['rewind_sec']:.0f}초 | 새 글만 읽기 {s['append_sec']:.0f}초"
              f" | 쓰기 {s['gen_tokens']:,}토큰 {s['gen_sec']:.0f}초 | 끊고 버린 쓰기 {s['cut_n']}번 {s['cut_tokens']:,}토큰(약 {s['cut_sec_est']:.0f}초)"
              f" | 맞대기 {hits}/{known}")
        if len(ids) == 1:
            previous = 0
            for task in picked:
                kind = classify(task, previous) if task["n"] >= 1000 else "곁가지"
                print(f"   프롬프트 {task['n']:7,} | 되살린 자리 {str(task.get('restored', '-')):>7} | {kind:6} 읽기 {int(task.get('read_tokens') or 0):6,}토큰"
                      f" {float(task.get('read_sec') or 0):5.1f}초 | 쓰기 {int(task.get('gen_tokens') or 0):5,}토큰 {float(task.get('gen_sec') or 0):5.1f}초"
                      f"{' | 끊김 ' + format(int(task.get('stop_n') or 0) - task['n'], ',') + '토큰' if task.get('cancelled') else ''}")
                if task["n"] >= 1000:
                    previous = task["n"]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
