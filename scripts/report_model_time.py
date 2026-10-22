"""**시간이 어디로 갔나** — 판 기록에 이미 있는 숫자로 답한다 (2026-09-18).

    python scripts/report_model_time.py                 최근 판 요약
    python scripts/report_model_time.py --job <id>      판 하나를 턴별로
    python scripts/report_model_time.py --limit 300     더 많이

## 왜 있나

「자비스가 느리다」에 답하려면 프리필(맥락 읽기)·생성(사고·답)·도구를 갈라야 한다. 숫자는
호출마다 이미 오고 있었고(`_inference.telemetry`) 판 기록에도 남아 있었는데, 읽는 도구가 없어서
매번 손으로 SQL 을 썼다. 그동안 원인 추측이 세 번 바뀌었다 — 도구 탓, 프리필 탓, 사고 탓.

실제로 갈라 보니(판 153개·턴 1,366개) 프리필은 얼마 안 되고, 상한까지 사고한 소수의 턴이
생성 시간의 19% 를 먹고 있었다. 그 판을 겪은 사람에게는 질문 하나가 5분이다.

이 도구는 **판단하지 않는다.** 세고 보여 준다. 고칠지는 사람이 정한다.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any


def _runtime_db(explicit: str = "") -> Path:
    if explicit:
        return Path(explicit)
    # 편집은 E:, 실행은 C: — 기록은 도는 쪽에 쌓인다.
    for candidate in (
        Path("C:/RoboMetaFit/tools/alture-jarvis/data/jarvis.db"),
        Path(__file__).resolve().parents[1] / "data" / "jarvis.db",
    ):
        if candidate.is_file():
            return candidate
    raise SystemExit("판 기록(jarvis.db)을 못 찾았습니다 — --db 로 경로를 주세요")


def _rows(db: Path, limit: int) -> list[tuple[str, str, float, float, dict[str, Any]]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = []
    query = (
        "select id, title, started_at, finished_at, result_json from jobs "
        "where finished_at is not null and started_at is not null order by rowid desc limit ?"
    )
    for jid, title, started, finished, payload in con.execute(query, (limit,)):
        try:
            trace = (json.loads(payload or "{}").get("agent_trace") or {})
        except (TypeError, ValueError):
            continue
        verification = trace.get("verification") or {}
        if not verification.get("inference_observations"):
            # 「못 봤다」와 「0 이었다」를 가른다 — 계측이 없는 판은 분모에서 뺀다.
            continue
        out.append((jid, str(title or "")[:40], float(started), float(finished),
                    {"verification": verification, "steps": trace.get("steps") or []}))
    return out


def _split(trace: dict[str, Any], seconds: float) -> dict[str, float]:
    observations = trace["verification"].get("inference_observations") or []
    prefill = sum(float((o.get("telemetry") or {}).get("prompt_eval_duration") or 0) for o in observations) / 1e9
    generate = sum(float((o.get("telemetry") or {}).get("eval_duration") or 0) for o in observations) / 1e9
    cut = sum(float(o.get("cut_first_pass_sec") or 0) for o in observations)
    # ★ 판 기록의 관측은 **마지막 12개만** 남는다(`agent.py` 의 `inference_observations[-12:]`) — 23턴 판(1b6df02d)에서
    #   이 도구는 프리필을 113초로 셌는데 전체는 171초였다 (2026-10-19). 판이 전체 관측으로 미리 더해 둔 `model_time` 이
    #   있으면 그것을 쓴다(분모 구멍 · 사고 S). 없으면 예전처럼 남은 관측으로 센다.
    summary = trace["verification"].get("model_time") or {}
    if isinstance(summary, dict) and summary.get("turns"):
        prefill = float(summary.get("prefill_sec") or 0)
        generate = float(summary.get("generate_sec") or 0)
        cut = float(summary.get("cut_first_pass_sec") or cut)
    tools = sum(float(s.get("took_ms") or 0) for s in trace["steps"] if isinstance(s, dict)) / 1000
    capped = sum(1 for o in observations if int((o.get("telemetry") or {}).get("eval_count") or 0) >= 8000)
    capped_sec = sum(
        float((o.get("telemetry") or {}).get("eval_duration") or 0) / 1e9
        for o in observations
        if int((o.get("telemetry") or {}).get("eval_count") or 0) >= 8000
    )
    return {"total": seconds, "prefill": prefill, "generate": generate, "tools": tools, "cut": cut,
            "capped": capped, "capped_sec": capped_sec,
            "turns": int(summary.get("turns") or 0) if isinstance(summary, dict) and summary.get("turns") else len(observations)}


def _one_job(db: Path, job_id: str) -> None:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    row = con.execute(
        "select title, started_at, finished_at, result_json from jobs where id = ?", (job_id,)
    ).fetchone()
    if not row:
        raise SystemExit(f"그런 판이 없습니다: {job_id}")
    title, started, finished, payload = row
    trace = (json.loads(payload or "{}").get("agent_trace") or {})
    verification = trace.get("verification") or {}
    observations = verification.get("inference_observations") or []
    print(f"{title}\n판 전체 {float(finished) - float(started):.0f}초 · 모델 턴 {len(observations)}개\n")
    print(" 턴 | 맥락 읽기(프리필)       | 생성                    | 그중 사고")
    for index, item in enumerate(observations, 1):
        timing = item.get("telemetry") or {}
        prompt_count = int(timing.get("prompt_eval_count") or 0)
        prompt_sec = float(timing.get("prompt_eval_duration") or 0) / 1e9
        count = int(timing.get("eval_count") or 0)
        seconds = float(timing.get("eval_duration") or 0) / 1e9
        flag = "  ← 상한까지 씀" if count >= 8000 else ""
        print(f" {index:2d} | {prompt_count:7,}토큰 {prompt_sec:6.1f}초 | {count:6,}토큰 {seconds:6.1f}초 |"
              f" {int(item.get('thinking_chars_received') or 0):7,}자{flag}")
    split = _split({"verification": verification, "steps": trace.get("steps") or []},
                   float(finished) - float(started))
    rest = split['total'] - split['prefill'] - split['generate'] - split['tools'] - split['cut']
    print(f"\n프리필 {split['prefill']:.0f}초 · 생성 {split['generate']:.0f}초 · 도구 {split['tools']:.0f}초"
          f" · 끊고 버린 호출 {split['cut']:.0f}초 · 나머지(큐·대기 등) {max(0.0, rest):.0f}초")
    hits = verification.get("thinking_budget_hits") or []
    if hits:
        print(f"사고 예산에 걸려 다시 부른 턴: {len(hits)}개")


def main() -> int:
    parser = argparse.ArgumentParser(description="판 기록에서 모델 시간을 가른다")
    parser.add_argument("--db", default="")
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--job", default="")
    parser.add_argument("--slow", type=float, default=180.0, help="이 초를 넘으면 느린 판으로 본다")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):  # 빌드 콘솔이 cp949 다
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    db = _runtime_db(args.db)
    if args.job:
        _one_job(db, args.job)
        return 0

    rows = _rows(db, args.limit)
    if not rows:
        print("계측이 있는 판이 없습니다.")
        return 0
    splits = [_split(trace, finished - started) for _jid, _t, started, finished, trace in rows]
    total = sum(s["total"] for s in splits)
    share = lambda value: f"{value / total * 100:4.0f}%" if total else "   -"  # noqa: E731
    prefill = sum(s["prefill"] for s in splits)
    generate = sum(s["generate"] for s in splits)
    tools = sum(s["tools"] for s in splits)
    cut = sum(s["cut"] for s in splits)
    rest = max(0.0, total - prefill - generate - tools - cut)
    turns = sum(s["turns"] for s in splits)
    capped = sum(s["capped"] for s in splits)
    capped_sec = sum(s["capped_sec"] for s in splits)
    print(f"기록: {db}")
    print(f"판 {len(splits)}개 · 모델 턴 {turns}개 · 합계 {total / 60:.0f}분"
          f" · 판 길이 중앙 {statistics.median(s['total'] for s in splits):.0f}초\n")
    print(f"  맥락 읽기(프리필) {prefill / 60:6.1f}분 ({share(prefill)})")
    print(f"  생성(사고·답)     {generate / 60:6.1f}분 ({share(generate)})")
    print(f"  도구              {tools / 60:6.1f}분 ({share(tools)})")
    print(f"  끊고 버린 호출    {cut / 60:6.1f}분 ({share(cut)})  ← 10-19 이후 판만 적힘")
    print(f"  나머지(큐·대기)   {rest / 60:6.1f}분 ({share(rest)})")
    if turns:
        print(f"\n생성 상한(8,192토큰)까지 쓴 턴 {capped}개 ({capped / turns * 100:.1f}%)"
              f" — 그 턴들이 {capped_sec / 60:.1f}분"
              f" (생성의 {capped_sec / generate * 100:.0f}%)" if generate else "")
    slow = [(s, row) for s, row in zip(splits, rows) if s["total"] > args.slow]
    if slow:
        print(f"\n{args.slow:.0f}초 넘는 판 {len(slow)}개:")
        for split, (jid, title, _st, _fi, _tr) in sorted(slow, key=lambda pair: -pair[0]["total"])[:10]:
            print(f"  {split['total']:5.0f}초 | 생성 {split['generate']:5.0f}초"
                  f" | 상한턴 {split['capped']} | {title}")
            print(f"        자세히: python scripts/report_model_time.py --job {jid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
