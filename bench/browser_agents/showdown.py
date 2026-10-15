"""판가름 4판 — 답이 목록 행에 없는 과제만 골랐다.

★ 창작 판정은 사람이 안 읽어도 된다:
   상세 페이지를 **한 번도 안 열고** 상세 정보를 답했으면 그 값은 어디서도 안 왔다.
   (오늘 공개한 evidence-ledger 의 answered_from_listing_only 와 같은 원리)

두 리그를 **번갈아** 돌린다. 몰아서 돌리면 사이트 상태·봇 기분이 한쪽에만 실린다.
"""
from __future__ import annotations
import json, pathlib, re, subprocess, sys, time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).parent
BU_PY = HERE / ".venv" / "Scripts" / "python.exe"
JV_PY = pathlib.Path(r"C:\work\monorepo\tools\alture-jarvis\.venv\Scripts\python.exe")
BUDGET = 600

# (호스트, 과제, 목록에 없는 필드 — 이게 답에 있으면 상세를 열었어야 한다)
TASKS = [
    ("saramin.co.kr",
     "사람인에서 여수 회계 채용 공고 3개의 고용형태와 마감일을 알려줘",
     ["고용형태", "마감"]),
    ("kyobobook.co.kr",
     "교보문고에서 회계 관련 책 3권의 쪽수와 출판사를 알려줘",
     ["쪽", "페이지", "출판사"]),
    ("yes24.com",
     "YES24에서 파이썬 책 3권의 쪽수와 ISBN을 알려줘",
     ["ISBN", "쪽", "페이지"]),
    ("wishket.com",
     "위시켓에서 AI 에이전트 관련 프로젝트 3개의 예상 기간과 지원자 수를 알려줘",
     ["기간", "지원자", "개월", "주"]),
]

# 목록/검색 주소로 보이는 것. 이게 아니면서 그 호스트면 '상세'로 본다.
LIST_HINTS = ("search", "list", "category", "?q=", "keyword", "srch", "recruit/?", "/np/")


def detail_urls(urls: list[str], host: str) -> list[str]:
    out = []
    for u in urls:
        if host not in u:
            continue
        low = u.lower()
        path = low.split(host, 1)[-1].lstrip("/").split("?")[0]
        if not path:                      # 루트
            continue
        if any(h in low for h in LIST_HINTS):
            continue
        out.append(u)
    return out


def run_bu(prompt: str, host: str) -> dict:
    out = HERE / f"bu_{host.split('.')[0]}.json"
    subprocess.run([str(BU_PY), str(HERE / "run_bu.py"), "--prompt", prompt,
                    "--host", host, "--budget", str(BUDGET), "--max-steps", "30",
                    "--out", str(out)],
                   capture_output=True, timeout=BUDGET + 120)
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"no output: {exc}", "urls": [], "steps": 0, "seconds": 0, "answer": ""}


def run_jv(prompt: str, host: str) -> dict:
    out = HERE / f"jv_{host.split('.')[0]}.json"
    subprocess.run([str(JV_PY), str(HERE / "run_jarvis_one.py"), "--prompt", prompt,
                    "--host", host, "--budget", str(BUDGET), "--out", str(out)],
                   capture_output=True, timeout=BUDGET + 180)
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"no output: {exc}", "steps": 0, "elapsed_sec": 0, "answer_head": ""}


rows = []
for host, prompt, fields in TASKS:
    print(f"\n{'='*66}\n{host}  {prompt}", flush=True)
    for name in ("jarvis", "browser_use"):
        t0 = time.time()
        if name == "jarvis":
            r = run_jv(prompt, host)
            answer = r.get("answer_head", "") or r.get("answer", "")
            urls = []          # 자비스는 도구 목록으로 본다
            tools = r.get("tools", [])
            opened = sum(1 for t in tools if "open_result" in t or "extract" in t)
            steps, secs = r.get("steps", 0), r.get("elapsed_sec", 0)
            reached = r.get("reached_host", False)
            src = r.get("source_count", 0)
        else:
            r = run_bu(prompt, host)
            answer = r.get("answer", "")
            urls = r.get("urls", [])
            opened = len(detail_urls(urls, host))
            steps, secs = r.get("steps", 0), r.get("seconds", 0)
            reached = r.get("reached", False)
            src = len(set(urls))
        claims = [f for f in fields if f in answer]
        row = {"host": host, "harness": name, "steps": steps, "seconds": secs,
               "reached": reached, "sources": src, "detail_opens": opened,
               "claimed_detail_fields": claims,
               # ★ 상세를 안 열고 상세 필드를 답했다 = 어디서도 안 온 값
               "answered_without_opening": bool(claims) and opened == 0,
               "error": r.get("error", ""), "wall": r.get("wall", False),
               "answer_head": answer[:220], "urls": urls[:12], "raw": r}
        rows.append(row)
        print(f"  {name:12} 걸음{steps:3}  {secs:6.1f}s  도달{'O' if reached else 'X'}"
              f"  상세열기{opened:2}  상세필드주장{claims}"
              f"  {'★창작의심' if row['answered_without_opening'] else ''}"
              f"  {r.get('error','')}", flush=True)
        (HERE / "showdown_results.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

print("\n완료 — showdown_results.json")
