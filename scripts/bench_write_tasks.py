"""L3(실행)를 **정직하게** 잰다 — 커밋이 요구된 판 중 몇 판이 실제로 나갔는가.

## 왜 이 자가 필요한가 (2026-08-20)

지금 있는 L3 숫자 둘 다 분모가 틀렸다.

    쓰기 도구 성공률 89.2%   ← 대부분 칸에 글자 넣기·누르기다. 밖으로 나간 게 아니다
    준비→커밋 전환율 9.3%    ← 그 준비들이 커밋되어야 마땅했는지를 모른다

`bench_research_tasks.py` 는 **읽기 전용**이라 커밋을 한 번도 안 시킨다. 그래서
"자비스가 일을 끝까지 해내는가"는 지금까지 한 번도 재본 적이 없다.

이 자는 **커밋을 명시적으로 시키는 과제**만 돌리고, 각 판이 어디까지 갔는지를
갈래로 센다:

    준비도 못 함 → 준비까지 → 승인 요청까지 → 커밋 성공 → 되돌릴 길까지

## 안전 규칙 — 밖으로 나가는 것은 되돌릴 수 있는 것만

이 자는 사용자님 계정에 **실제로 무언가를 만든다.** 그래서 되돌릴 수 있는 것만 시킨다:

    O  네이버 블로그 **임시저장**   (자비스가 지울 수 있다)
    O  캘린더 일정 (벤치 전용 제목)  (자비스가 지울 수 있다)
    X  메일 발송                    되돌릴 수 없다 — 이 자는 안 시킨다
    X  블로그 발행                  밖에 공개된다 — 이 자는 안 시킨다

승인은 `--auto-approve` 를 줄 때만 자동으로 누른다. 그 옵션이 없으면 사람이 화면에서
누를 때까지 기다린다(그게 기본이다).

★ 자동 승인은 **아래 목록의 도구에만** 걸린다. 목록에 없는 도구가 승인을 요청하면
  이 자는 누르지 않고 그 사실을 적는다 — 벤치가 예상 밖의 것을 실행하면 안 된다.

사용:
    python scripts/bench_write_tasks.py --dry-run          # 무엇을 시킬지만 보여준다
    python scripts/bench_write_tasks.py --auto-approve
    python scripts/bench_write_tasks.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8091"
TOKEN_PATH = Path("C:/RoboMetaFit/tools/alture-jarvis/data/control.token")

# 벤치가 만든 것을 나중에 사람이 알아볼 수 있게 제목에 이 표시를 넣는다.
MARK = "[벤치]"

# (묶음, 시킬 말, 여기까지 가면 성공인 커밋 도구)
TASKS: list[tuple[str, str, str]] = [
    (
        "blog",
        f"네이버 블로그에 '{MARK} 자동화 점검' 이라는 제목으로 세 줄짜리 글을 쓰고 "
        "**임시저장까지** 해줘. 발행은 하지 마.",
        "naver_blog_save_draft",
    ),
    (
        "calendar",
        f"내일 오후 3시에 '{MARK} 자비스 실행 점검' 일정을 30분짜리로 만들어줘.",
        "google_calendar_create",
    ),
    (
        "blog",
        f"네이버 블로그에 '{MARK} 이번 주 메모' 제목으로 오늘 한 일 두 줄 적고 "
        "임시저장해줘. 발행하지 말고 저장까지만.",
        "naver_blog_save_draft",
    ),
    (
        "drive",
        f"'{MARK} 자비스 점검 메모'라는 이름으로 오늘 점검한 것 세 줄 적어서 "
        "구글 드라이브에 올려줘.",
        "google_drive_write",
    ),
]

# 자동 승인해도 되는 도구 — **되돌릴 수 있는 것만.**
AUTO_APPROVABLE = frozenset({
    "naver_blog_save_draft",
    "google_calendar_create",
    "site_promote_draft",
    # 올린 것은 휴지통으로 되돌아간다(`_undo_drive_write`). 원본은 안 건드린다.
    "google_drive_write",
})


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8-sig").strip()


def call(path: str, method: str = "GET", body: dict | None = None, tok: str = "") -> dict:
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if tok:
        req.add_header("X-JARVIS-TOKEN", tok)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8", "replace") or "{}")


def pending_approvals(tok: str) -> list[dict]:
    try:
        found = call("/v1/approvals", tok=tok)
    except Exception:
        return []
    items = found.get("items") if isinstance(found, dict) else found
    return [row for row in (items or []) if str(row.get("status") or "pending") == "pending"]


# 끝난 것으로 치는 상태. `waiting_continuation` 은 **여기 없다** — 그건 자비스가
# "더 갈까요?" 하고 사람을 기다리는 상태지 끝난 게 아니다.
TERMINAL = {"completed", "failed", "cancelled"}


def run_one(group: str, prompt: str, commit_tool: str, tok: str, *, auto: bool, budget: int) -> dict:
    posted = time.time()
    job = call("/v1/chat", "POST", {"prompt": prompt, "session_id": f"wbench-{int(posted)}", "open_results": False}, tok)
    job_id = str(job.get("id") or "")
    row: dict = {
        "group": group, "prompt": prompt, "commit_tool": commit_tool, "job_id": job_id,
        "approved": [], "skipped_approvals": [], "continued": 0, "reached": "요청만",
    }

    # ★ 예산은 **일한 시간**에 건다. POST 한 시각부터 재면 큐에서 기다린 시간까지
    #   태우게 되고, 시작도 못 한 판이 "420초·0걸음"으로 찍혀 고장처럼 보인다.
    #   (2026-08-20 실측: 판 하나가 큐에서 993초 기다렸다. 벤치는 그걸 실패로 적었지만
    #    실제로는 시작 뒤 35초 만에 커밋까지 마쳤다. 같은 함정을 이 저장소가 두 번째로 만났다.)
    while True:
        time.sleep(4)
        detail = call(f"/v1/jobs/{job_id}", tok=tok)
        status = str(detail.get("status") or "")
        started_at = detail.get("started_at") or 0
        working = (time.time() - started_at) if started_at else 0
        if auto:
            for approval in pending_approvals(tok):
                name = str(approval.get("tool_name") or "")
                nonce = str(approval.get("nonce") or "")
                if name in AUTO_APPROVABLE:
                    try:
                        call(f"/v1/approvals/{nonce}", "POST", {"approve": True}, tok)
                        row["approved"].append(name)
                    except Exception as exc:
                        row.setdefault("errors", []).append(f"approve:{name}:{exc}")
                else:
                    # 목록에 없는 것은 **누르지 않는다.** 벤치가 예상 밖의 것을 실행하면 안 된다.
                    if name not in row["skipped_approvals"]:
                        row["skipped_approvals"].append(name)
            # "더 갈까요?" 도 사람이 눌러야 넘어간다. 안 눌러 주면 판이 거기서 굳는다
            # (실측: 906초째 도구 0개로 갇혀 있었다). 자동 모드에서는 이어서 가게 한다.
            if status == "waiting_continuation":
                try:
                    call(f"/v1/agents/{job_id}/continue", "POST", {"action": "continue_task"}, tok)
                    row["continued"] += 1
                except Exception as exc:
                    row.setdefault("errors", []).append(f"continue:{exc}")
        if status in TERMINAL:
            break
        if started_at and working > budget:
            row["timed_out"] = True
            break
        if not started_at and time.time() - posted > budget * 3:
            row["never_started"] = True
            break

    detail = call(f"/v1/jobs/{job_id}", tok=tok)
    result = detail.get("result") or {}
    trace = result.get("agent_trace") or {}
    steps = trace.get("steps") or []
    tools = [str(s.get("tool") or "") for s in steps]

    prepared = any(t.endswith(("_prepare_send", "_prepare_post", "_prepare_save_draft",
                               "_prepare_publish", "_prepare_create")) for t in tools)
    committed = any(t == commit_tool and s.get("ok") for t, s in zip(tools, steps))

    if committed:
        row["reached"] = "커밋"
    elif row["approved"]:
        row["reached"] = "승인까지"
    elif prepared:
        row["reached"] = "준비까지"
    elif steps:
        row["reached"] = "걸음만"

    undo = []
    try:
        undo = [u for u in (call("/v1/undo", tok=tok).get("items") or []) if u.get("job_id") == job_id]
    except Exception:
        pass

    row.update({
        "status": detail.get("status"),
        "steps": len(steps),
        "tools": tools,
        # 두 시간을 **나눠서** 적는다. 하나로 합치면 큐에서 기다린 시간이
        # 자비스가 일한 시간처럼 보인다.
        "queued_sec": round(max(0.0, (detail.get("started_at") or posted) - posted), 1),
        "seconds": round(max(0.0, (detail.get("finished_at") or time.time()) - (detail.get("started_at") or posted)), 1),
        "prepared": prepared,
        "committed": committed,
        "undoable": bool(undo),
        "plan": (trace.get("plan") or {}),
        "answer_head": (result.get("answer") or "")[:120],
    })
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto-approve", action="store_true", help="되돌릴 수 있는 커밋만 자동 승인")
    parser.add_argument("--budget-sec", type=int, default=420)
    parser.add_argument("--json", default="")
    parser.add_argument("--dry-run", action="store_true", help="무엇을 시킬지만 보여준다")
    args = parser.parse_args()

    if args.dry_run:
        print("이 자가 시킬 것 (되돌릴 수 있는 것만):")
        for group, prompt, tool in TASKS:
            print(f"  [{group}] {prompt[:70]}…  → {tool}")
        print(f"\n자동 승인 대상: {', '.join(sorted(AUTO_APPROVABLE))}")
        return 0

    tok = token()
    rows = []
    for index, (group, prompt, tool) in enumerate(TASKS, 1):
        print(f"[{index}/{len(TASKS)}] {prompt[:52]}", flush=True)
        row = run_one(group, prompt, tool, tok, auto=args.auto_approve, budget=args.budget_sec)
        rows.append(row)
        print(f"      → {row['reached']} · {row['steps']}걸음 · 일한 {row['seconds']}초 (큐 {row['queued_sec']}초)", flush=True)

    total = len(rows)
    committed = sum(1 for r in rows if r["committed"])
    prepared = sum(1 for r in rows if r["prepared"])
    undoable = sum(1 for r in rows if r["undoable"])
    # ★ **안 끝난 판을 실패로 적지 않는다.** 예산에서 끊긴 것은 "못 했다"가 아니라
    #   "아직 모른다"이다. 2026-08-20 에 그 둘을 섞어 2/3 을 1/3 으로 적었다.
    unfinished = sum(1 for r in rows if r.get("timed_out") or r.get("never_started"))
    judged = max(1, total - unfinished)

    print(chr(10) + "  L3 실행 — 커밋이 요구된 판만")
    print("  " + "─" * 56)
    if unfinished:
        print(f"  판정한 판            {total - unfinished}/{total}   (예산에서 끊김 {unfinished})")
    print(f"  준비까지 간 판       {prepared}/{judged}")
    print(f"  커밋까지 간 판       {committed}/{judged}   ← 이것이 L3 다")
    print(f"  되돌릴 길이 남은 판   {undoable}/{judged}")
    if judged < 10:
        # `measure_autonomy.py` 와 같은 규율: 표본이 적으면 비율로 말하지 않는다.
        print("  ⚠ 표본이 적다 — 비율 말고 개수로 본다")
    skipped = sorted({name for r in rows for name in r["skipped_approvals"]})
    if skipped:
        print(f"\n  ★ 목록에 없어 **안 누른** 승인: {', '.join(skipped)}")
    for row in rows:
        print(f"\n  [{row['reached']}] {row['prompt'][:48]}")
        print(f"      도구: {' → '.join(row['tools'][:8]) or '없음'}")
        if row["plan"]:
            print(f"      시킨 것: {row['plan'].get('met')}/{row['plan'].get('total')}")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  기록: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
