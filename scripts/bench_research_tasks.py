"""같은 과제를 같은 순서로 다시 돌려, 판이 달라졌을 때 무엇이 달라졌는지 잰다.

2026-08-13 아침에 10 판을 손으로 돌렸다. 그 결과가 그날 하루의 근거가 됐는데
(3/10 → 10/10), **손으로 돌린 것이라 다시 못 잰다.** 판을 고칠 때마다 같은 과제를
같은 순서로 다시 돌릴 수 있어야 "좋아졌다"는 말에 근거가 생긴다.

    python scripts/bench_research_tasks.py                # 전체
    python scripts/bench_research_tasks.py --only inhouse # 묶음 하나만
    python scripts/bench_research_tasks.py --json out.json

## 무엇을 재나 (그리고 안 재나)

재는 것   갔는가 · 무엇을 썼는가 · 몇 걸음 · 몇 초 · 시킨 개수를 채웠는가 ·
          **못 했으면 못 했다고 말했는가**(정직성 경고가 붙었는가)
안 재는 것 답이 **좋았는가**. 그건 사람이 읽어야 한다. 이 자는 "굴러갔는가"만 잰다
          (`measure_autonomy.py` 와 같은 규율).

★ 창작을 잡는 유일한 신호는 **도구를 하나도 안 쓴 판**이다. 아침의 7 건이 전부
그 모양이었다 — 걸음 0, 그럴듯한 표. 그래서 `tools=0` 을 따로 세운다.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
import os

# ★ 콘솔이 cp949 라 표식 하나(⚠)에 스크립트가 통째로 죽는다. 첫 판을 다 돌리고
# **결과를 찍는 자리에서** 죽으므로, 몇 분을 쓰고 아무것도 못 건진다. 이 저장소가
# 인코딩으로 여러 번 데인 자리라(사고 J·F) 들어오자마자 못 박는다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 시험 백엔드(예: 8097)로 돌릴 때만 바꾼다(2026-10-01 16GB 밤 측정). 기본은 운영 그대로.
BASE = os.environ.get("JARVIS_BENCH_BASE", "http://127.0.0.1:8091")
ENV_PATH = pathlib.Path(r"C:\RoboMetaFit\tools\alture-jarvis\.env")
TOKEN_PATH = pathlib.Path(os.environ.get("JARVIS_BENCH_TOKEN_FILE", r"C:\RoboMetaFit\tools\alture-jarvis\data\control.token"))

# 아침 판에서 **실제로 창작으로 끝난 여섯 건**을 글자 하나 안 바꾸고 가져왔다.
# 여기에 그날 못 푼 것(사람인)과, 새로 붙인 자사 데이터를 더한다.
TASKS: list[tuple[str, str, str]] = [
    # (묶음, 과제, 이 판이 닿아야 하는 곳 — 없으면 "")
    ("web", "위시켓에서 AI 에이전트 관련 프로젝트 3개의 제목과 예산을 알려줘", "wishket.com"),
    ("web", "다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘", "danawa.com"),
    ("web", "크몽에서 AI 에이전트 개발 서비스 3개의 제목과 가격을 알려줘", "kmong.com"),
    ("web", "교보문고에서 회계 관련 책 3권의 제목과 저자를 알려줘", "kyobobook.co.kr"),
    ("web", "쿠팡에서 무선마우스 상위 3개 제품명과 가격을 알려줘", "coupang.com"),
    ("web", "대학알리미에서 취업률 지표를 어디서 볼 수 있는지 찾아서 알려줘", "academyinfo.go.kr"),
    ("web", "사람인에서 여수 회계 채용 공고 3개의 제목과 회사명을 알려줘", "saramin.co.kr"),
    # 자사 데이터 — 웹에 가면 안 되는 것들이다(우리가 원천을 갖고 있다).
    ("inhouse", "중앙대 소프트웨어학부 최근 경쟁률이 어떻게 되나요?", ""),
    ("inhouse", "경희대학교 컴퓨터공학과 합격선이 어떻게 돼?", ""),
    ("inhouse", "간호학과 취업률이랑 졸업 후 진로 알려줘", ""),
    # ── 카테고리 탐색 (2026-08-14 신설) ──────────────────────────────────
    #
    # 왜 따로 두나: 위 일곱 개는 전부 **검색** 과제다(검색칸 → 결과 → 상세). 그래서
    # `browser_hover` 가 한 번도 안 불렸고, 도구가 나쁜 건지 잴 자리가 없는 건지
    # 구별이 안 됐다. 국내 쇼핑의 다른 절반은 **카테고리를 타고 들어가는 것**이다.
    #
    # ★ 문장에 "3개" 같은 개수를 **일부러 안 넣었다.** 넣으면 계획 층이 "본문 3개를
    # 열어 읽어라"로 읽는데(`plan._COUNT`), 이 과제는 상세를 열 일이 없다 —
    # 제대로 해도 미달로 찍힌다. 재는 자가 과제를 왜곡하면 안 된다.
    #
    # ⚠ 문구도 골라야 했다. 처음 쓴 "쿠팡 카테고리 **메뉴에서** … 하위 분류가 있는지"는
    #   라우터가 **에이전트로 안 보냈다** — `named_sources` 가 "메뉴"를 출처로 읽고
    #   "분류"는 구체값 목록에 없어서다. 그대로 뒀으면 호버가 아니라 라우팅을 쟀을 것이다.
    #   (이 라우팅 구멍 자체는 따로 적어 뒀다 — 카테고리 탐색 요청이 안 걸린다.)
    ("nav", "쿠팡에서 가전디지털 카테고리 안에 어떤 하위 분류가 있는지 목록으로 알려줘", "coupang.com"),
    ("nav", "다나와에서 마우스가 어느 카테고리 분류에 들어 있는지 경로를 알려줘", "danawa.com"),
    # ── 처음 보는 사이트 (2026-08-23 신설) ────────────────────────────────
    #
    # 왜 필요한가: 위 판들은 전부 **우리가 이미 아는 사이트**다. 레시피가 있거나
    # (`recipes/saramin.json`), 코드에 이름이 박혀 있다(kmong 9곳·danawa 8곳·
    # kyobo 6곳). 그 위에서 낸 성적은 **모델의 실력이 아니라 우리 사전지식**을
    # 상당 부분 재고 있다.
    #
    # 여기 넷은 레시피 0 · 코드 언급 0 인 인기 사이트다. 그리고 둘은 **위 과제와
    # 같은 모양**으로 짝지었다 — 그래야 레시피의 기여분이 분리된다:
    #     yes24    ↔ 교보문고(코드 지식 6곳)
    #     잡코리아  ↔ 사람인(레시피 있음)
    ("fresh", "무신사에서 남성 반팔티 상위 3개의 제품명과 가격을 알려줘", "musinsa.com"),
    ("fresh", "YES24에서 파이썬 관련 책 3권의 제목과 저자를 알려줘", "yes24.com"),
    ("fresh", "잡코리아에서 여수 회계 채용 공고 3개의 제목과 회사명을 알려줘", "jobkorea.co.kr"),
    ("fresh", "오늘의집에서 조명 인기 상품 3개의 제품명과 가격을 알려줘", "ohou.se"),
]

_INHOUSE_PREFIXES = ("admission_", "career_", "official_exam", "question_bank_")


def _token() -> str:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("JARVIS_CONTROL_TOKEN="):
                # .env 가 파일보다 이긴다(config.load 가 그렇게 읽는다). 여기서 파일을
                # 먼저 보면 살아 있는 자비스와 다른 토큰을 쥐고 401 을 맞는다.
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


# ★ **줄을 실제로 막는 것만** 센다.
#
# 처음엔 `waiting_continuation`·`waiting_approval` 도 넣었는데, 그건 **사람을
# 기다리는 상태**라 일꾼을 붙들고 있지 않다. 실측(2026-08-14): 3.5일 전 잡 두 건이
# 그 상태로 남아 있어서, 이 목록대로면 벤치가 **영영 기다렸을** 것이다.
#
# 기다림의 조건은 "누가 일꾼을 쥐고 있나"이지 "안 끝난 잡이 있나"가 아니다.
_BUSY = {"running", "queued"}

# 줄이 빌 때까지 기다리는 최대 시간. 넘으면 말하고 그냥 시작한다.
_QUEUE_WAIT_MAX_SEC = 600


def _busy_jobs(token: str) -> list[dict]:
    """아직 도는 잡들. `/v1/jobs` 는 **리스트**를 돌려준다(dict 아님)."""
    try:
        payload = _get("/v1/jobs?limit=20", token)
    except Exception:
        return []
    jobs = payload if isinstance(payload, list) else (payload.get("jobs") or [])
    return [job for job in jobs if isinstance(job, dict) and str(job.get("status")) in _BUSY]


def run_one(group: str, prompt: str, host: str, token: str, *, budget_sec: int) -> dict:
    started = time.time()
    job = _post("/v1/chat", {"prompt": prompt, "session_id": f"bench-{int(started)}", "open_results": False}, token)
    job_id = str(job.get("id") or "")
    build = str(job.get("build") or "")
    status = "unknown"
    detail: dict = {}
    # ★ **줄 서 있는 시간을 일한 시간으로 세지 않는다** (2026-08-13).
    #
    # 자비스는 잡을 하나씩 돈다. 그래서 앞 잡이 안 끝났으면 새 잡은 큐에서 기다린다.
    # 예산을 POST 시각부터 재면 그 대기가 통째로 예산을 먹고, 시작도 못 한 판이
    # "421초 · 0걸음"으로 찍힌다 — 멈춘 것처럼 보이지만 실은 **차례가 안 온 것**이다.
    #
    # 실제로 그렇게 한 번 속았다: 앞 벤치를 죽였는데 그게 큐에 넣어 둔 잡은 서버에서
    # 계속 돌고 있었고(327초), 새 벤치의 첫 판이 311초를 기다렸다. 그 판은 149초에
    # 멀쩡히 끝났는데 벤치는 이미 포기한 뒤였다.
    #
    # 오늘 하루 내내 잡던 병이 재는 자에게도 있었던 셈이다.
    deadline = started + budget_sec
    while time.time() < deadline:
        time.sleep(6)
        try:
            detail = _get(f"/v1/jobs/{job_id}", token)
        except urllib.error.URLError:
            continue
        status = str(detail.get("status") or "")
        if status in {"completed", "failed", "cancelled"}:
            break
        # 아직 시작도 안 했으면 예산 시계를 시작 시각으로 미룬다.
        began = detail.get("started_at")
        if began:
            deadline = max(deadline, float(began) + budget_sec)

    result = detail.get("result") or {}
    trace = result.get("agent_trace") or {}
    steps = trace.get("steps") or []
    verification = trace.get("verification") or {}
    answer = str(result.get("answer") or "")
    tools = [str(s.get("tool") or "") for s in steps]
    sources = [str(u) for u in (verification.get("urls") or [])]
    began = float(detail.get("started_at") or 0) or None
    ended = float(detail.get("finished_at") or 0) or None
    return {
        "job_id": job_id,
        "group": group,
        "prompt": prompt,
        "expect_host": host,
        "build": build,
        "status": status,
        # 일한 시간. 이것이 성능이다.
        "elapsed_sec": round((ended - began) if (began and ended) else (time.time() - started), 1),
        # 줄 서 있던 시간. 성능이 아니라 **내가 겹쳐 돌렸다는 뜻**이라 따로 적는다.
        "queued_sec": round(began - started, 1) if began else None,
        "steps": len(steps),
        "tools": tools,
        "tools_ok": sum(1 for s in steps if s.get("ok")),
        # 도구를 하나도 안 썼다 = 기억에서 답했다. 아침의 창작 7 건이 전부 이것이다.
        "no_tools": not tools,
        "used_inhouse": any(t.startswith(_INHOUSE_PREFIXES) for t in tools),
        # 카테고리 메뉴는 **누르는 것이 아니라 올려놓는 것**이다. 올렸는지, 그리고
        # 올려서 **실제로 뭔가 나타났는지**를 따로 센다 — 부르기만 하고 아무것도
        # 안 나타났으면 그건 호버 메뉴가 아니었던 것이고, 도구 탓이 아니다.
        "used_hover": "browser_hover" in tools,
        "hover_revealed": sum(
            len((s.get("evidence") or {}).get("appeared") or [])
            for s in steps
            if s.get("tool") == "browser_hover" and s.get("ok")
        ),
        "reached_host": bool(host) and any(host in u for u in sources),
        "source_count": len(sources),
        # 못 했으면 못 했다고 말했는가. 정직성 검사가 답 끝에 붙이는 표식이다.
        "flagged_shortfall": "⚠" in answer,
        "answer_chars": len(answer),
        "answer_head": answer[:180],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="묶음 이름(web/inhouse)")
    # 판을 고를 때 쓴다. 쉼표로 여러 개 — 과제 문장에 그 조각이 있으면 고른다.
    # 왜 필요한가: `--only` 는 묶음 단위라 "31B 를 죽인 세 판만" 같은 조합이 안 된다.
    # 모델을 비교할 때는 **어려운 판만 골라 짧게 돌리는** 것이 실용적이다.
    parser.add_argument("--match", default="", help="과제 문장 부분일치(쉼표로 여러 개)")
    # 420 → 600. 쿠팡 판이 **493초에 성공**했는데 예산이 먼저 끝나서 "0걸음"으로
    # 찍혔다(2026-08-14). 재는 자가 성공을 실패로 적는 것이 제일 나쁘다.
    # 자비스 자체 상한(agent_autonomous_lease_sec=900)보다는 낮게 둔다.
    parser.add_argument("--budget-sec", type=int, default=600, help="한 판 최대 대기(실행 시간 기준)")
    parser.add_argument("--json", default="", help="결과를 적을 파일")
    args = parser.parse_args()

    token = _token()

    # ★ 줄이 비었는지 보고 시작한다.
    #
    # 자비스는 잡을 하나씩 돈다. 앞 벤치를 죽여도 **그것이 큐에 넣어 둔 잡은 서버에서
    # 계속 돈다** — 스크립트를 죽이는 것과 일을 멈추는 것은 다른 일이다.
    # 그걸 모르고 겹쳐 돌렸다가 첫 판이 311초를 기다렸고, 그게 "421초·0걸음"으로
    # 찍혀 고장으로 보였다. 재는 자가 거짓말을 한 셈이다.
    busy = _busy_jobs(token)
    if busy:
        print(f"⚠ 자비스가 아직 {len(busy)}건을 돌고 있다 — 끝날 때까지 기다린다.", flush=True)
        for job in busy[:3]:
            print(f"    {str(job.get('id'))[:8]} {str(job.get('status')):<12} {str(job.get('title'))[:36]}")
        waited = 0
        while busy and waited < _QUEUE_WAIT_MAX_SEC:
            time.sleep(10)
            waited += 10
            busy = _busy_jobs(token)
        if busy:
            # 무한히 기다리지 않는다. 못 비면 **그 사실을 말하고** 그냥 시작한다 —
            # 조용히 매달려 있으면 벤치가 멈춘 것과 구별이 안 된다.
            print(f"⚠ {_QUEUE_WAIT_MAX_SEC}초를 기다려도 안 비었다. 그대로 시작한다"
                  f"(대기 시간은 queued_sec 에 적힌다).\n", flush=True)
        else:
            print("  줄이 비었다. 시작한다.\n", flush=True)

    tasks = [t for t in TASKS if not args.only or t[0] == args.only]
    if args.match:
        needles = [x.strip() for x in args.match.split(",") if x.strip()]
        tasks = [t for t in tasks if any(n in t[1] for n in needles)]
        if not tasks:
            print(f"고른 판이 없다: --match {args.match}", flush=True)
            return 1
    rows: list[dict] = []
    for index, (group, prompt, host) in enumerate(tasks, 1):
        print(f"[{index}/{len(tasks)}] {prompt[:48]}", flush=True)
        row = run_one(group, prompt, host, token, budget_sec=args.budget_sec)
        rows.append(row)
        queued = row.get("queued_sec") or 0
        print(
            f"    {row['status']} · {row['steps']}걸음 · {row['elapsed_sec']}초"
            + (f" (+대기 {queued:.0f}초)" if queued >= 10 else "")
            + f" · 출처 {row['source_count']}"
            + (" · 도구 0" if row["no_tools"] else "")
            + (" · 자사데이터" if row["used_inhouse"] else "")
            + (f" · 호버 {row['hover_revealed']}개 나타남" if row["used_hover"] else "")
            + (" · ⚠못했다고 말함" if row["flagged_shortfall"] else ""),
            flush=True,
        )

    done = [r for r in rows if r["status"] == "completed"]
    print("\n" + "─" * 66)
    print(f"  끝까지 간 판           {len(done)}/{len(rows)}")
    print(f"  도구 없이 답한 판      {sum(1 for r in rows if r['no_tools'])}   ← 창작 위험")
    web = [r for r in rows if r["group"] == "web" and r["expect_host"]]
    print(f"  지목한 사이트에서 읽음  {sum(1 for r in web if r['reached_host'])}/{len(web)}")
    inhouse = [r for r in rows if r["group"] == "inhouse"]
    if inhouse:
        print(f"  자사 데이터로 답함      {sum(1 for r in inhouse if r['used_inhouse'])}/{len(inhouse)}")
    nav = [r for r in rows if r["group"] == "nav"]
    if nav:
        used = sum(1 for r in nav if r["used_hover"])
        revealed = sum(1 for r in nav if r["hover_revealed"] > 0)
        print(f"  카테고리에 마우스 올림   {used}/{len(nav)}  (올려서 뭔가 나타난 판 {revealed})")
        if not used:
            print("     ← 도구는 있는데 안 불렸다. 프롬프트 순서를 볼 것.")
    if done:
        times = sorted(r["elapsed_sec"] for r in done)
        print(f"  소요 중앙값            {times[len(times) // 2]}초  (범위 {times[0]}~{times[-1]})")
    print("─" * 66)

    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  적었다: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
