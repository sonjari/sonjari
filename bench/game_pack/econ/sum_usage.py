"""게임 팩 경제성 벤치 — Claude Code 대화 기록에서 판마다 토큰·도구·에셋 읽기를 센다 (인수인계 2026-09-27).

    python bench/game_pack/econ/sum_usage.py runs.csv > usage.csv

runs.csv 칸: arm,task,run,session_file   (session_file = ~/.claude/projects/<프로젝트>/<세션>.jsonl)

세는 것 (대화 기록 한 줄 = 메시지 하나):
- assistant 메시지의 `message.usage` — input·output·cache_creation·cache_read 토큰 합
- tool_use 개수, 그중 온텔릭 도구(`mcp__ontelic__*`) 개수
- 에셋을 **직접** 읽은 횟수와 받은 바이트 — Read/Grep/Glob/Bash 인자에 `Assets/` 가 든 호출의 tool_result 길이
  (= 회사 에셋 내용이 대화로 끌려 들어간 양)
- 첫 사용자 메시지 → 마지막 assistant 메시지 시각 차(초)

비밀은 안 뽑는다 — usage 숫자와 도구 이름·경로 여부만 본다. 본문은 읽어도 출력하지 않는다.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_ASSET_TOOLS = {"Read", "Grep", "Glob", "Bash", "PowerShell"}


def _time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def summarize(session: Path) -> dict[str, Any]:
    totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "tool_calls": 0, "ontelic_calls": 0,
              "asset_reads": 0, "asset_bytes": 0}
    asset_calls: set[str] = set()
    first_user: datetime | None = None
    last_reply: datetime | None = None
    for line in session.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        stamp = _time(row.get("timestamp"))
        role = message.get("role") or row.get("type")
        if role == "user" and first_user is None and stamp and isinstance(message.get("content"), str):
            first_user = stamp
        if role == "assistant":
            usage = message.get("usage") or {}
            totals["input"] += int(usage.get("input_tokens") or 0)
            totals["output"] += int(usage.get("output_tokens") or 0)
            totals["cache_write"] += int(usage.get("cache_creation_input_tokens") or 0)
            totals["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
            if stamp:
                last_reply = stamp
        blocks = message.get("content") if isinstance(message.get("content"), list) else []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                totals["tool_calls"] += 1
                name = str(block.get("name") or "")
                if name.startswith("mcp__ontelic"):
                    totals["ontelic_calls"] += 1
                arguments = json.dumps(block.get("input") or {}, ensure_ascii=False).replace("\\\\", "/")
                if name in _ASSET_TOOLS and "Assets/" in arguments:
                    totals["asset_reads"] += 1
                    asset_calls.add(str(block.get("id")))
            elif block.get("type") == "tool_result" and str(block.get("tool_use_id")) in asset_calls:
                content = block.get("content")
                text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                totals["asset_bytes"] += len(text.encode("utf-8"))
    totals["seconds"] = round((last_reply - first_user).total_seconds(), 1) if first_user and last_reply else ""
    return totals


def main(runs_csv: str) -> None:
    writer = None
    with open(runs_csv, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            totals = summarize(Path(row["session_file"]).expanduser())
            out = {"arm": row["arm"], "task": row["task"], "run": row["run"], **totals}
            if writer is None:
                writer = csv.DictWriter(sys.stdout, fieldnames=list(out))
                writer.writeheader()
            writer.writerow(out)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
