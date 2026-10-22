"""「이번 주 손자리가 클로드 대신 읽은 양」 영수증 (2026-10-19 대표 결정 — 대상은 클로드 사용자, 간판은 「한도를 덜어 준다」).

## 무엇을 세나

판마다 `delegation._cost` 가 싣는 `host_context_kept_out`(바깥 AI 대화에 안 실린 본문의 **하한** 토큰)을 기간으로 모은다.
그 숫자는 여기서 새로 만들지 않는다 — 판 기록의 걸음에서 `delegation.host_context_kept_out` 을 **그대로 불러** 다시 센다
(같은 함수 · 같은 나눗수 · 같은 근거). 판 하나의 하한을 더한 것이라 합계도 하한이다.

## ★ 말하지 않는 것

- 「약」 · 「배」 · 달러 환산 · 「한도의 몇 %」 — 우리가 잰 근거가 없다. 숫자는 「최소 N 토큰」 하나와 근거(basis)뿐이다.
- 시간을 아꼈다는 말 — 로컬은 더 느릴 수 있다.

## 어떤 판을 세나 (판정은 결정론 — `counted_reason`)

「클로드 대신」은 **바깥 AI 가 MCP 문으로 맡긴 판**만이다:

1. `payload.origin == "mcp"` — 사람이 앱(`workspace` · `chat` · `voice`)에서 직접 시킨 판은 클로드 대신이 아니다.
2. `payload.caller` 가 있다 — MCP 문(`mcp_server._delegate`)은 연결을 연 호스트 이름(clientInfo)을 싣는다. 이름이 없는 판은
   그 문을 지나지 않은 것이다: 2026-10-19 운영 기록의 지난 7일 이름 없는 맡기기 판 410건은 세션 이름이
   `measure-price/chain-*`(측정 꾸러미) · `mcp-price-*`(bench/skillpack_price) · `mcp-chain-*` · `mcp-follow-*`(bench/followup)가
   408건, `mcp-ask-*` · `live-*` 가 1건씩이었다 — MCP 문은 세션을 `mcp-<12자>` 로 짓고 이름을 싣는다. 이름 없는 진짜 호스트가 있다면
   빠지는데, 빠지는 쪽은 **덜 세는 쪽**이라 하한을 깨지 않는다.
3. 디스코드 다리가 맡긴 판이 아니다(`caller == "Discord"`). 다리는 `ChatRequest.origin` 이 디스코드를 못 받아 `mcp` 를 빌려 쓴다
   (`messaging/bridge.py` 머리말) — 그 판은 **사람이 폰으로** 시킨 것이지 바깥 AI 가 맡긴 것이 아니다.
4. 우리 측정 스크립트가 스스로 붙인 이름이 아니다(`bench` · `rerun` · `measure` 가 든 caller — 운영 기록에 `bench-om2w` ·
   `honesty-bench` · `rerun-reddit-1003` 이 있다).

빠진 판은 까닭별 건수로 같이 싣는다(`excluded`) — 조용히 빠지는 것이 제일 나쁘다(사고 S).

## 끝난 판 · 멈춘 판

- 실패 · 취소된 판도 **실제로 읽었으면 센다**(읽은 것은 읽은 것이다). 판 수는 끝난 판(`completed`) · 멈춘 판(`failed` · `cancelled`)을 나눠 적는다.
- 아직 도는 판(대기 · 승인 기다림 포함)은 세지 않는다 — 숫자가 아직 움직인다. 건수만 `in_progress` 로.
- 기간은 판이 **끝난 시각**(`finished_at`, 없으면 `updated_at`)으로 가른다.

이 모듈은 HTTP 를 모른다. 운영 DB 는 읽기 전용(`mode=ro`)으로만 연다.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from .delegation import host_context_kept_out, is_claude_code

__all__ = ["DEFAULT_DAYS", "MAX_DAYS", "DISCORD_CALLER", "BASIS", "counted_reason", "host_label",
           "summarize", "collect", "headline"]

DEFAULT_DAYS = 7
MAX_DAYS = 90
TOP_N = 3
PROMPT_HEAD = 60
#: 디스코드 다리가 싣는 맡긴 쪽 이름 — `messaging.bridge.CALLER` 와 같아야 한다(시험이 대조한다).
#:   여기서 그 모듈을 가져오지 않는 까닭: 다리는 디스코드 부품(httpx · discord.py)을 끌고 온다. 영수증은 그것 없이 돈다.
DISCORD_CALLER = "Discord"
#: 우리 측정 스크립트가 스스로 붙인 caller 이름의 낱말(운영 기록 10-19: bench-om2w · honesty-bench · rerun-reddit-1003).
_MEASUREMENT_CALLER = re.compile(r"bench|rerun|measure", re.IGNORECASE)
_DONE = {"completed"}
_STOPPED = {"failed", "cancelled"}

#: 합계의 근거 — 판 하나의 근거(`delegation.host_context_kept_out` 의 basis)와 같은 셈을 기간으로 더했다는 말.
BASIS = (
    "바깥 AI 가 맡긴 일에서 이 PC 가 읽은 본문 글자 수(센 값)를 토큰당 4.5자로 나눈 하한을 판마다 더했습니다. "
    "한글 본문은 실측으로 토큰당 1.66~1.72자라 실제는 이보다 큽니다. 사람이 앱 · 디스코드에서 직접 시킨 일과 측정 판은 세지 않았습니다."
)


def counted_reason(payload: Any) -> str:
    """이 판을 「바깥 AI 가 맡긴 판」으로 세는가. 세면 빈 문자열, 아니면 빠진 까닭 코드(머리말의 1~4)."""
    if not isinstance(payload, dict) or str(payload.get("origin") or "") != "mcp":
        return "not_delegated"
    caller = str(payload.get("caller") or "").strip()
    if not caller:
        return "no_host_name"
    if caller == DISCORD_CALLER:
        return "person_via_discord"
    if _MEASUREMENT_CALLER.search(caller):
        return "measurement"
    return ""


def host_label(caller: str) -> str:
    """호스트 묶음 — `Claude Code` · `Codex` · `기타`. 클로드 코드는 `delegation.is_claude_code` 와 같은 판정."""
    if is_claude_code(caller):
        return "Claude Code"
    if "codex" in str(caller or "").lower():
        return "Codex"
    return "기타"


def _decode(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _ended_at(row: dict[str, Any]) -> float:
    for key in ("finished_at", "updated_at", "created_at"):
        try:
            value = float(row.get(key) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return 0.0


def _prompt_head(payload: dict[str, Any]) -> str:
    text = " ".join(str(payload.get("prompt") or "").split())
    return text[:PROMPT_HEAD] + ("…" if len(text) > PROMPT_HEAD else "")


def _clamp_days(days: Any) -> int:
    try:
        value = int(days)
    except (TypeError, ValueError):
        value = DEFAULT_DAYS
    return max(1, min(MAX_DAYS, value))


def summarize(rows: Iterable[dict[str, Any]], *, days: int = DEFAULT_DAYS, now: float | None = None) -> dict[str, Any]:
    """판 기록 줄들(`payload` · `result` 는 사전이나 JSON 글) → 기간 영수증. 기간 밖의 줄은 여기서도 거른다."""
    days = _clamp_days(days)
    until = time.time() if now is None else float(now)
    since = until - days * 86400
    total_tokens = 0
    text_chars = 0
    reads = 0
    done = stopped = with_reads = in_progress = 0
    excluded: dict[str, int] = {"no_host_name": 0, "person_via_discord": 0, "measurement": 0}
    hosts: dict[str, dict[str, Any]] = {}
    tops: list[dict[str, Any]] = []
    for row in rows:
        payload = _decode(row.get("payload", row.get("payload_json")), {})
        reason = counted_reason(payload)
        if reason == "not_delegated":
            continue
        status = str(row.get("status") or "")
        ended = _ended_at(row)
        if status not in _DONE and status not in _STOPPED:
            if not reason:
                in_progress += 1
            continue
        if not since <= ended <= until:
            continue
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        result = _decode(row.get("result", row.get("result_json")), {}) or {}
        steps = [s for s in ((result.get("agent_trace") or {}).get("steps") or []) if isinstance(s, dict)]
        kept = host_context_kept_out(steps) or {}
        tokens = int(kept.get("tokens_at_least") or 0)
        caller = str(payload.get("caller") or "").strip()
        label = host_label(caller)
        if status in _DONE:
            done += 1
        else:
            stopped += 1
        bucket = hosts.setdefault(label, {"host": label, "tokens_at_least": 0, "jobs": 0, "names": []})
        bucket["jobs"] += 1
        bucket["tokens_at_least"] += tokens
        if caller not in bucket["names"]:
            bucket["names"].append(caller)
        if tokens > 0:
            with_reads += 1
            total_tokens += tokens
            text_chars += int(kept.get("text_chars") or 0)
            reads += int(kept.get("reads") or 0)
            tops.append({
                "job_id": str(row.get("id") or ""),
                # 키 이름을 `prompt` 로 둔다 — 영어 화면 번역이 사용자의 글로 알고 건드리지 않는다(`ui_i18n._KEEP_KEYS`).
                "prompt": _prompt_head(payload),
                "tokens_at_least": tokens,
                "host": label,
                "status": "done" if status in _DONE else "stopped",
                "finished_at": ended,
            })
    tops.sort(key=lambda item: (-item["tokens_at_least"], -item["finished_at"]))
    order = {"Claude Code": 0, "Codex": 1, "기타": 2}
    by_host = sorted(hosts.values(), key=lambda b: (order.get(b["host"], 9), -b["tokens_at_least"]))
    jobs = done + stopped
    claude_only = jobs > 0 and all("claude" in name.lower() for b in by_host for name in b["names"])
    return {
        "kind": "floor",
        "days": days,
        "since": since,
        "until": until,
        "tokens_at_least": total_tokens,
        "text_chars": text_chars,
        "reads": reads,
        "jobs": {"total": jobs, "done": done, "stopped": stopped, "with_reads": with_reads},
        "in_progress": in_progress,
        "by_host": by_host,
        "top": tops[:TOP_N],
        "excluded": excluded,
        # 맡긴 쪽이 전부 클로드면 「클로드 대신」, 코덱스 등이 섞이면 「바깥 AI 대신」 — 화면 제목이 이 값을 따른다.
        "host_word": "claude" if claude_only else "outside_ai",
        "basis": BASIS,
    }


def collect(db_path: Path | str, *, days: int = DEFAULT_DAYS, now: float | None = None) -> dict[str, Any]:
    """DB 파일을 **읽기 전용**으로 열어 영수증을 만든다. 쓰지 않으므로 돌고 있는 본체의 DB 에도 안전하다."""
    days = _clamp_days(days)
    until = time.time() if now is None else float(now)
    since = until - days * 86400
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        # LIKE 는 값싼 앞거르기일 뿐이다 — 맡긴 판인지는 위의 `counted_reason` 이 payload 를 풀어 다시 가른다.
        rows = conn.execute(
            """SELECT id, status, payload_json, result_json, created_at, updated_at, finished_at
               FROM jobs
               WHERE kind = 'chat' AND payload_json LIKE '%mcp%'
                 AND (COALESCE(finished_at, updated_at) >= ? OR status NOT IN ('completed', 'failed', 'cancelled'))""",
            (since,),
        ).fetchall()
    finally:
        conn.close()
    return summarize((dict(row) for row in rows), days=days, now=until)


def headline(receipt: dict[str, Any]) -> str:
    """사람이 읽는 한 줄(명령 창 · 보고용). 화면은 같은 값으로 제 문장(`i18n`)을 만든다."""
    who = "클로드" if receipt.get("host_word") == "claude" else "바깥 AI"
    period = "이번 주" if int(receipt.get("days") or DEFAULT_DAYS) == 7 else f"지난 {int(receipt.get('days') or 0)}일"
    jobs = receipt.get("jobs") or {}
    return (f"{period} 손자리가 {who} 대신 읽은 양: 최소 {int(receipt.get('tokens_at_least') or 0):,} 토큰"
            f"(맡긴 일 {int(jobs.get('total') or 0)}건 · 끝난 판 {int(jobs.get('done') or 0)} · 멈춘 판 {int(jobs.get('stopped') or 0)})")


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m alture_jarvis.savings_receipt",
                                     description="바깥 AI 가 맡긴 판에서 손자리가 대신 읽은 양(하한)을 읽기 전용으로 센다")
    parser.add_argument("--db", required=True, help="jarvis.db 경로(읽기 전용으로 연다)")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001, S110
        pass
    receipt = collect(args.db, days=args.days)
    print(headline(receipt))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
