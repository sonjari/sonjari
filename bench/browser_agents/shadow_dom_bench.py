"""섀도 DOM 사이트 벤치 — 고치기 **전과 후**를 같은 자로 잰다 (2026-09-17).

## 왜

MS 스토어에서 「AI 검색해서 앱 몇 개인지」를 시켰더니 16걸음·253초를 헤매고 「확인 못 했다」로 끝났다.
실측: apps.microsoft.com 은 누를 것·글자가 **전부 섀도 DOM 안**이다(일반 DOM 상호작용 요소 0개, 검색 결과 페이지
`body.innerText` 0자, 섀도 안 앱 링크 40개). 우리 수집기는 `document.querySelectorAll` 뿐이라 아무것도 못 봤다.

## 무엇을 재나 (과제마다 n 판)

    ms_search   MS 스토어에서 AI 검색 → 맨 위 앱 5개 이름         정답: 헤드리스로 섀도 안 링크 이름 5개, 3개 이상 맞으면 정답
    ms_detail   MS 스토어에서 ChatGPT 찾기 → 게시자·별점            정답: 상세 페이지 섀도 안 글자에서 게시자·별점
    wa_search   webawesome.com 검색창(섀도 안)으로 rating 문서 찾기 정답: rating 컴포넌트 문서 주소에 실제로 갔는가
    yes24_ctrl  대조군(일반 DOM) — 고친 뒤 **느려지거나 깨지지 않았나**  정답: ISBN 두 개

정답은 **매 실행 시작에** 헤드리스(임시 프로필)로 새로 뽑는다 — 스토어 순위·별점은 날마다 바뀐다.
진 결과도 지우지 않는다(전략안 §12): results/shadow_dom/<label>_<task>_<n>.json

    python shadow_dom_bench.py before 3
    python shadow_dom_bench.py after 3
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import tempfile
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\work\monorepo\tools\alture-jarvis\scripts")
import bench_research_tasks as B  # noqa: E402

HERE = pathlib.Path(__file__).parent
OUT = HERE / "results" / "shadow_dom"
LABEL = sys.argv[1] if len(sys.argv) > 1 else "run"
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
ONLY = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else set()
BUDGET = 420

TASKS = [
    ("ms_search", "apps.microsoft.com",
     "마이크로소프트 스토어(apps.microsoft.com)에서 AI 를 검색해서 결과 목록 맨 위에 나오는 앱 5개의 이름을 알려줘"),
    ("ms_detail", "apps.microsoft.com",
     "마이크로소프트 스토어(apps.microsoft.com)에서 ChatGPT 앱을 찾아서 게시자와 별점을 알려줘"),
    ("wa_search", "webawesome.com",
     "webawesome.com 사이트의 검색 기능으로 rating 을 검색해서 나오는 컴포넌트 문서를 열고, 그 문서 첫 문단을 한 줄로 요약해줘"),
    ("yes24_ctrl", "yes24.com", "YES24에서 파이썬 책 2권의 쪽수와 ISBN을 알려줘"),
]

DEEP_LINKS = r"""() => { const out = []; const walk = (root) => { for (const el of root.querySelectorAll('*')) {
  if (el.tagName === 'A' && el.href) out.push([el.href, (el.getAttribute('aria-label') || el.innerText || '').trim()]);
  if (el.shadowRoot) walk(el.shadowRoot); } }; walk(document); return out; }"""
DEEP_TEXT = r"""() => { const out = []; const skip = new Set(['SCRIPT','STYLE','NOSCRIPT','TEMPLATE']);
  const walk = (node) => { for (const ch of node.childNodes) {
    if (ch.nodeType === 3) { const t = ch.textContent.replace(/\s+/g, ' ').trim(); if (t) out.push(t); }
    else if (ch.nodeType === 1 && !skip.has(ch.tagName)) { if (ch.shadowRoot) walk(ch.shadowRoot); if (ch.tagName !== 'SLOT') walk(ch); } } };
  walk(document.body); return out; }"""


def ground_truth() -> dict:
    """스토어의 지금 정답. 실패하면 빈 값 — 채점이 「정답 모름」으로 적는다(지어내지 않는다)."""
    from playwright.sync_api import sync_playwright

    truth: dict = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(tempfile.mkdtemp(prefix="shadow-truth-"), headless=True,
                                                   locale="ko-KR", viewport={"width": 1600, "height": 900})
        page = ctx.new_page()
        try:
            page.goto("https://apps.microsoft.com/search?query=AI&hl=ko-KR&gl=KR", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(7000)
            names: list[str] = []
            for href, label in page.evaluate(DEEP_LINKS):
                if "/detail/" in href:
                    name = label.split("\n")[0].strip()
                    if name and name not in names:
                        names.append(name)
            truth["ms_search_top5"] = names[:5]
        except Exception as exc:  # noqa: BLE001
            truth["ms_search_error"] = str(exc)[:200]
        try:
            page.goto("https://apps.microsoft.com/search?query=ChatGPT&hl=ko-KR&gl=KR", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)
            first = next(((h, l) for h, l in page.evaluate(DEEP_LINKS) if "/detail/" in h and l.split("\n")[0].strip() == "ChatGPT"), None)
            if first:
                page.goto(first[0], wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)
                lines = page.evaluate(DEEP_TEXT)
                at = lines.index("ChatGPT") if "ChatGPT" in lines else -1
                truth["ms_detail"] = {"url": first[0], "publisher": lines[at + 1] if at >= 0 else "",
                                      "rating": next((x for x in lines[at + 1: at + 6] if re.fullmatch(r"\d\.\d", x)), "")}
        except Exception as exc:  # noqa: BLE001
            truth["ms_detail_error"] = str(exc)[:200]
        ctx.close()
    return truth


def _job_urls(job_id: str, token: str) -> list[str]:
    detail = B._get(f"/v1/jobs/{job_id}", token)
    steps = (((detail.get("result") or {}).get("agent_trace") or {}).get("steps")) or []
    urls: list[str] = []
    for step in steps:
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        for key in ("url", "final_url", "page_url"):
            value = str((evidence or {}).get(key) or "")
            if value.startswith("http"):
                urls.append(value)
    return urls


def grade(task: str, row: dict, answer: str, urls: list[str], truth: dict) -> dict:
    squashed = answer.replace(",", "")
    if task == "ms_search":
        names = truth.get("ms_search_top5") or []
        hits = [n for n in names if n.lower() in answer.lower()]
        return {"correct": len(hits) >= 3 if names else None, "hits": hits, "truth": names}
    if task == "ms_detail":
        want = truth.get("ms_detail") or {}
        if not want.get("publisher"):
            return {"correct": None, "truth": want}
        ok = want["publisher"].lower() in answer.lower() and (not want.get("rating") or want["rating"] in squashed)
        return {"correct": ok, "truth": want}
    if task == "wa_search":
        reached = any("webawesome.com" in u and "rating" in u.lower() for u in urls)
        return {"correct": reached, "urls_tail": urls[-4:]}
    if task == "yes24_ctrl":
        isbns = set(re.findall(r"97[89]\d{10}", re.sub(r"[-\s]", "", answer)))
        return {"correct": len(isbns) >= 2, "isbns": sorted(isbns)}
    return {"correct": None}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    token = B._token()
    stamp = time.strftime("%Y%m%d_%H%M")
    print(f"[{LABEL}] 정답 뽑는 중(헤드리스)…", flush=True)
    truth = ground_truth()
    (OUT / f"{LABEL}_truth_{stamp}.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  truth:", json.dumps(truth, ensure_ascii=False)[:400], flush=True)
    summary: list[dict] = []
    for round_no in range(1, ROUNDS + 1):
        for task, host, prompt in TASKS:
            if ONLY and task not in ONLY:
                continue
            while B._busy_jobs(token):
                time.sleep(10)
            row = B.run_one("web", prompt, host, token, budget_sec=BUDGET)
            job_id = ""
            try:
                jobs = B._get("/v1/jobs?limit=5&view=summary", token)
                items = jobs.get("items") if isinstance(jobs, dict) else jobs
                job_id = next((str(j.get("id")) for j in items or [] if str(j.get("title") or "").startswith(prompt[:30])), "")
            except Exception:  # noqa: BLE001
                pass
            urls = _job_urls(job_id, token) if job_id else []
            detail = B._get(f"/v1/jobs/{job_id}", token) if job_id else {}
            answer = str(((detail.get("result") or {}).get("answer")) or row.get("answer_head") or "")
            completion = str(((detail.get("result") or {}).get("completion_state")) or "")
            verdict = grade(task, row, answer, urls, truth)
            record = {**row, "task": task, "round": round_no, "label": LABEL, "job_id": job_id,
                      "completion_state": completion, "answer": answer[:1500], "urls": urls[-12:], **verdict}
            (OUT / f"{LABEL}_{task}_{round_no}_run{stamp}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            line = {k: record.get(k) for k in ("task", "round", "correct", "status", "completion_state", "elapsed_sec", "steps")}
            summary.append(line)
            print("  ", json.dumps(line, ensure_ascii=False), flush=True)
    (OUT / f"{LABEL}_summary_{stamp}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    by_task: dict[str, list[dict]] = {}
    for line in summary:
        by_task.setdefault(line["task"], []).append(line)
    print(f"\n[{LABEL}] 요약")
    for task, lines in by_task.items():
        ok = sum(1 for x in lines if x["correct"])
        secs = [x["elapsed_sec"] for x in lines]
        steps = [x["steps"] for x in lines]
        print(f"  {task:<11} 정답 {ok}/{len(lines)} · 시간 {secs} · 걸음 {steps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
