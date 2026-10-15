"""내부 작업으로 잰다 — 파일·코드·문서·계산, 그리고 **스킬이 붙는가**.

## 왜 따로 만드나 (2026-08-23)

`bench_research_tasks.py` 는 **웹 조사**를 잰다. 그런데 그 종목은 도구가 이미 다
갖춰져 있어서, 모델에게 필요한 것이 **결단력**이지 추론이 아니다. 실측(같은 날,
처음 보는 사이트 4판):

    젬마4 26B-A4B (지수 31)   37걸음 · 중앙 124초 · 실패 0
    퀀3.8-27B    (지수 52)   73걸음 · 중앙 130초 · 실패 2

지수가 21점 아래인 모델이 이겼다. 그 종목이 지수가 재는 능력을 안 쓰기 때문이다.

**내부 작업은 다르다.** 파일 트리를 읽고 구조를 파악하거나, 코드에서 값을 찾아
그 이유를 설명하거나, 문서 여러 개를 종합하는 일은 **맥락을 쥐고 있어야** 한다.
여기서는 지수가 재는 그 능력이 실제로 값을 할 수 있다. 그래서 따로 잰다.

## 무엇을 세나

    정답      ★ 사람이 대조한다. 여기서는 **기계로 대조 가능한 것만** 낸다
              (파일 개수·상수 값·소수 개수처럼 정답이 하나뿐인 것)
    걸음·시간  조사 벤치와 같다
    도구      local_* · sandbox_run · skill_* 중 **맞는 것을 썼나**
    창작      도구 0개로 답했으면 지어낸 것이다
    스킬      맥락에 맞는 스킬이 붙었나 (`skill` 갈래로 갔나)

## 안 세는 것

글이 **좋은가**는 안 센다. 셀 수 없다. 원문을 남겨 사람이 읽게 한다.

사용:
    python scripts/bench_internal_tasks.py
    python scripts/bench_internal_tasks.py --only files
    python scripts/bench_internal_tasks.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8091"
ENV_PATH = pathlib.Path(r"C:\RoboMetaFit\tools\alture-jarvis\.env")
TOKEN_PATH = pathlib.Path(r"C:\RoboMetaFit\tools\alture-jarvis\data\control.token")

# (묶음, 과제, 기대하는 도구 조각, 정답에 반드시 들어가야 할 조각들)
#
# ★ 정답 조각은 **하나뿐인 사실**만 넣는다. "좋은 설명"을 채점하려 들면 그 순간
#   이 자가 거짓말을 시작한다(조사 벤치가 "답이 좋았는가는 안 센다"고 못 박은 것과
#   같은 규율).
TASKS: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = [
    # ── 파일 탐색 ──────────────────────────────────────────────────────
    (
        "files",
        r"C:\work\monorepo\tools\alture-jarvis\recipes 폴더 안에 파일이 몇 개 있고 이름이 뭔지 알려줘",
        ("local_list_directory", "local_search_files"),
        ("naver_blog", "saramin"),
    ),
    # ── 코드 이해 ──────────────────────────────────────────────────────
    #
    # 값만 찾으면 절반이다. **왜 그 값인지**(num_ctx 와 쌍)까지 읽어야 한다.
    (
        "code",
        r"C:\work\monorepo\tools\alture-jarvis\src\alture_jarvis\agent.py 에서 _TRANSCRIPT_BUDGET_CHARS 값이 얼마이고 왜 그 값인지 알려줘",
        ("local_read_text_file", "local_search_files"),
        ("180",),
    ),
    # ── 문서 종합 ──────────────────────────────────────────────────────
    (
        "docs",
        r"C:\work\monorepo\tools\alture-jarvis\docs\인수인계_2026-08-22.ko.md 를 읽고 「다음 사람이 할 것」에 적힌 항목을 목록으로 뽑아줘",
        ("local_read_text_file", "local_read_document"),
        ("사이트맵", "구글"),
    ),
    # ── 계산 (격리 상자) ───────────────────────────────────────────────
    #
    # 정답이 하나뿐이라 창작이 즉시 드러난다. 1~1000 소수는 **168개**.
    (
        "compute",
        "1부터 1000까지 소수가 몇 개인지 계산해서 숫자만 알려줘",
        ("sandbox_run",),
        ("168",),
    ),
    # ── 스킬 부착 ──────────────────────────────────────────────────────
    #
    # 맥락에 맞는 스킬이 붙는가. 2026-08-22 에 「사이트 이름 한 조각」 때문에
    # 조사 판에서 스킬이 통째로 안 붙던 버그를 고쳤다 — 그게 살아 있는지 본다.
    (
        "skill",
        "학원 수강료 가격 책정 전략을 세워줘",
        # ★ 스킬은 **도구 호출이 아니라 프롬프트 주입**으로 붙는다. 처음엔
        #   `skill_read` 를 기대했다가 정상 동작을 「창작」으로 찍었다(2026-08-23).
        #   재는 자가 틀리면 멀쩡한 것을 고치러 간다 — 그래서 도구는 안 본다.
        (),
        (),
    ),
]

_BUSY = {"running", "queued"}
_QUEUE_WAIT_MAX_SEC = 300


def _token() -> str:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("JARVIS_CONTROL_TOKEN="):
                return line.split("=", 1)[1].strip()
    return TOKEN_PATH.read_text(encoding="utf-8-sig").strip()


def _post(path: str, body: dict, token: str, timeout: int = 60) -> dict:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Jarvis-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get(path: str, token: str, timeout: int = 30) -> dict:
    request = urllib.request.Request(
        f"{BASE}{path}", headers={"X-Jarvis-Token": token}, method="GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_quiet(token: str) -> None:
    started = time.time()
    while time.time() - started < _QUEUE_WAIT_MAX_SEC:
        try:
            payload = _get("/v1/jobs?limit=20", token)
        except Exception:
            return
        jobs = payload if isinstance(payload, list) else (payload.get("jobs") or [])
        if not [j for j in jobs if isinstance(j, dict) and str(j.get("status")) in _BUSY]:
            return
        time.sleep(3)
    print(f"⚠ {_QUEUE_WAIT_MAX_SEC}초를 기다려도 줄이 안 비었다. 그대로 시작한다.", flush=True)


def run_one(group: str, prompt: str, want_tools: tuple[str, ...],
            want_text: tuple[str, ...], token: str, *, budget_sec: int) -> dict:
    started = time.time()
    job = _post("/v1/chat", {"prompt": prompt, "session_id": f"ibench-{int(started)}", "open_results": False}, token)
    job_id = str(job.get("id") or "")
    status, answer, steps = "unknown", "", []
    deadline = started + budget_sec
    while time.time() < deadline:
        time.sleep(3)
        try:
            row = _get(f"/v1/jobs/{job_id}", token)
        except Exception:
            continue
        status = str(row.get("status") or "")
        if status in {"completed", "failed", "cancelled", "waiting_continuation", "waiting_approval"}:
            result = row.get("result") or {}
            answer = str(result.get("answer") or "")
            steps = ((result.get("agent_trace") or {}).get("steps")) or []
            break

    used = [str(s.get("tool") or s.get("name") or "") for s in steps]
    tool_hit = any(any(w in t for w in want_tools) for t in used) if want_tools else None
    text_hit = all(frag in answer for frag in want_text) if want_text else None
    return {
        "group": group,
        "prompt": prompt,
        "job_id": job_id,
        "status": status,
        "steps": len(steps),
        "elapsed_sec": round(time.time() - started, 1),
        "tools": used,
        "expected_tool_used": tool_hit,
        "answer_has_facts": text_hit,
        # ★ 도구가 필요 없는 판은 「창작」이 아니다 (2026-08-23).
        #
        #   스킬은 **도구 호출이 아니라 프롬프트 주입**으로 붙는다. 그래서 스킬 판은
        #   정상 동작에서도 걸음이 0이다. 그걸 창작으로 찍었더니 멀쩡한 기능을
        #   고치러 갈 뻔했다 — `match_skill` 도 `skill_route_selected` 도 정상이었다.
        #
        #   재는 자가 틀리면 없는 병을 만든다. 그래서 **도구를 기대한 판에서만**
        #   창작을 센다.
        "fabricated": bool(answer) and not steps and bool(want_tools),
        "answer": answer[:1500],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="묶음(files/code/docs/compute/skill)")
    parser.add_argument("--budget-sec", type=int, default=420)
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    token = _token()
    _wait_for_quiet(token)
    tasks = [t for t in TASKS if not args.only or t[0] == args.only]
    rows = []
    for index, (group, prompt, want_tools, want_text) in enumerate(tasks, 1):
        print(f"[{index}/{len(tasks)}] ({group}) {prompt[:52]}", flush=True)
        row = run_one(group, prompt, want_tools, want_text, token, budget_sec=args.budget_sec)
        rows.append(row)
        marks = []
        if row["expected_tool_used"] is not None:
            marks.append("도구 " + ("✅" if row["expected_tool_used"] else "❌"))
        if row["answer_has_facts"] is not None:
            marks.append("사실 " + ("✅" if row["answer_has_facts"] else "❌"))
        if row["fabricated"]:
            marks.append("★창작")
        print(f"    {row['status']} · {row['steps']}걸음 · {row['elapsed_sec']}초"
              + ("  " + " · ".join(marks) if marks else ""), flush=True)
        print(f"    도구: {', '.join(dict.fromkeys(row['tools'])) or '(없음)'}", flush=True)

    done = [r for r in rows if r["status"] == "completed"]
    tool_ok = [r for r in rows if r["expected_tool_used"]]
    fact_ok = [r for r in rows if r["answer_has_facts"]]
    fact_tot = [r for r in rows if r["answer_has_facts"] is not None]
    line = "─" * 66
    print(f"\n{line}")
    print(f"  끝까지 간 판        {len(done)}/{len(rows)}")
    print(f"  도구 없이 답한 판   {sum(1 for r in rows if r['fabricated'])}   ← 창작 위험")
    print(f"  맞는 도구를 씀      {len(tool_ok)}/{sum(1 for r in rows if r['expected_tool_used'] is not None)}")
    print(f"  답에 사실이 있음    {len(fact_ok)}/{len(fact_tot)}   ← 기계로 대조 가능한 것만")
    if done:
        times = sorted(r["elapsed_sec"] for r in done)
        print(f"  소요 중앙값         {times[len(times)//2]}초  (범위 {times[0]}~{times[-1]})")
    print(line)

    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  적었다: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
