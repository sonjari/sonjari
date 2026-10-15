"""바꾸기 전 ↔ 바꾼 뒤 — 같은 모델·같은 과제를 **번갈아** 태워 브라우저 일 성공률을 잰다 (2026-09-26).

## 왜

09-24~26 에 브라우저 쪽을 크게 바꿨다(화면 밖 주차·가림 판정 끄기·무대 스트림·확인창 규칙·창 크기 맞춤). 보여 주기는 E2E 로
확인했지만 **온텔릭이 일을 더 잘/못 하게 됐는지**는 안 쟀다. 특히 가림 판정 끄기는 숨은 페이지가 그리기 시작하게 만들어
지연 로딩 목록이 달라질 수 있다 — 좋아질 수도, 달라질 수도 있다.

## 규칙 (README ①②③)

- 두 쪽 다 시험용 온텔릭(따로 데이터·크롬 프로필)으로 띄우고 **같은 Ollama 태그·num_ctx** 를 쓴다(축출 방지).
- 과제마다 전·후를 **번갈아** 돈다(한쪽을 몰아 돌리면 사이트 상태·봇 기분이 한쪽에만 실린다). 한 번에 한 판만.
- 진 판도 지우지 않는다 — results/ab_before_after/<label>.jsonl 에 한 줄씩.

채점: 「굴러갔나」(도구를 썼나·맞는 사이트에 갔나) + **시킨 개수만큼 답했나**(목록 항목 수). 답의 사실 여부는 안 잰다.

    python ab_before_after.py <label> <rounds> <before_base> <before_token_file> <after_base> <after_token_file>
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import bench_research_tasks as B  # noqa: E402

HERE = pathlib.Path(__file__).parent
OUT = HERE / "results" / "ab_before_after"
OUT.mkdir(parents=True, exist_ok=True)
BUDGET = 600  # 쿠팡 판이 493초에 성공한 적이 있다(bench_research_tasks 주석)

#: (이름, 프롬프트, 가야 할 사이트, 시킨 개수)
TASKS = [
    ("wishket", "위시켓에서 AI 에이전트 관련 프로젝트 3개의 제목과 예산을 알려줘", "wishket.com", 3),
    ("danawa", "다나와에서 무선마우스 상위 3개 제품명과 가격을 알려줘", "danawa.com", 3),
    ("kmong", "크몽에서 AI 에이전트 개발 서비스 3개의 제목과 가격을 알려줘", "kmong.com", 3),
    ("kyobo", "교보문고에서 회계 관련 책 3권의 제목과 저자를 알려줘", "kyobobook.co.kr", 3),
    ("coupang", "쿠팡에서 무선마우스 상위 3개 제품명과 가격을 알려줘", "coupang.com", 3),
    ("academyinfo", "대학알리미에서 취업률 지표를 어디서 볼 수 있는지 찾아서 알려줘", "academyinfo.go.kr", 0),
    ("saramin", "사람인에서 여수 회계 채용 공고 3개의 제목과 회사명을 알려줘", "saramin.co.kr", 3),
    ("weather", "네이버에서 오늘 부산 날씨 검색해서 최고기온을 알려줘", "naver.com", 0),
]

_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*•]|\|?\s*\d+\s*\|)\s*\S", re.M)
_TEMP = re.compile(r"-?\d{1,2}(?:\.\d)?\s*(?:°C?|℃|도)")  # 「23°」 도 기온이다(ab_0926 r1 채점기 버그)


def item_count(answer: str) -> int:
    """답의 목록 항목 수 — 번호·글머리·표 행. 표 머리줄·구분줄은 안 센다."""
    lines = [line for line in answer.splitlines() if line.strip()]
    table_rows = [line for line in lines if line.strip().startswith("|") and not set(line.strip()) <= set("|-: ")]
    listed = len(_ITEM.findall(answer))
    return max(listed, max(0, len(table_rows) - 1))


def grade(task: tuple, row: dict) -> dict:
    name, _prompt, host, wanted = task
    answer = str(row.get("answer") or "")
    tools = row.get("tools") or []
    used_browser = any(str(t).startswith(("browser_", "site_")) for t in tools)
    on_site = bool(row.get("reached_host")) or host in answer
    if name == "weather":
        complete = bool(_TEMP.search(answer))
    elif wanted:
        complete = item_count(answer) >= wanted
    else:
        complete = len(answer.strip()) > 40
    return {"used_browser": used_browser, "on_site": on_site, "complete": complete,
            "ok": bool(row.get("status") == "completed" and used_browser and on_site and complete),
            "items": item_count(answer)}


def run_arm(arm: str, base: str, token: str, task: tuple) -> dict:
    B.BASE = base
    waited = time.time()
    while B._busy_jobs(token) and time.time() - waited < 900:
        time.sleep(10)
    row = B.run_one("web", task[1], task[2], token, budget_sec=BUDGET)
    # run_one 은 답을 180자만 준다 — 개수를 세려면 잡에서 전체 답을 받는다.
    # (처음엔 /v1/jobs 목록에서 프롬프트로 찾았는데 목록에 prompt 가 없어 늘 180자로 셌다 — ab_0926 앞 판들. regrade.)
    try:
        detail = B._get(f"/v1/jobs/{row['job_id']}", token)
        row["answer"] = str((detail.get("result") or {}).get("answer") or "")
    except Exception:  # noqa: BLE001
        row["answer"] = str(row.get("answer_head") or "")
        row["answer_truncated"] = True
    return {"arm": arm, "task": task[0], **{k: row.get(k) for k in ("status", "elapsed_sec", "steps", "tools", "answer", "reached_host", "job_id")},
            **grade(task, row)}


def main() -> None:
    label, rounds = sys.argv[1], int(sys.argv[2])
    arms = [("before", sys.argv[3], pathlib.Path(sys.argv[4]).read_text(encoding="utf-8").strip()),
            ("after", sys.argv[5], pathlib.Path(sys.argv[6]).read_text(encoding="utf-8").strip())]
    only = set(sys.argv[7].split(",")) if len(sys.argv) > 7 else set()
    out = OUT / f"{label}.jsonl"
    for round_no in range(1, rounds + 1):
        for index, task in enumerate(TASKS):
            if only and task[0] not in only:
                continue
            # 번갈아 — 과제·판마다 누가 먼저 도는지도 바꾼다(먼저 도는 쪽이 사이트 캐시를 데우지 않게).
            order = arms if (round_no + index) % 2 else list(reversed(arms))
            for arm, base, token in order:
                try:
                    result = run_arm(arm, base, token, task)
                except Exception as exc:  # noqa: BLE001 — 한 판 실패가 벤치를 죽이면 안 된다
                    result = {"arm": arm, "task": task[0], "status": "bench_error", "error": str(exc)[:300], "ok": False}
                result["round"] = round_no
                result["at"] = time.strftime("%H:%M:%S")
                with out.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                print(f"r{round_no} {task[0]:12} {arm:6} ok={result.get('ok')} items={result.get('items')} "
                      f"t={result.get('elapsed_sec')} steps={result.get('steps')} status={result.get('status')}", flush=True)
    summarize(out)


def summarize(path: pathlib.Path) -> None:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print("\n요약 (ok = 완료·브라우저 사용·맞는 사이트·시킨 개수)")
    for task in TASKS:
        cells = []
        for arm in ("before", "after"):
            mine = [r for r in rows if r.get("task") == task[0] and r.get("arm") == arm]
            if not mine:
                continue
            ok = sum(1 for r in mine if r.get("ok"))
            times = sorted(float(r.get("elapsed_sec") or 0) for r in mine)
            median = times[len(times) // 2] if times else 0
            cells.append(f"{arm} {ok}/{len(mine)} 중앙 {median:.0f}초")
        print(f"  {task[0]:12} " + " · ".join(cells))
    for arm in ("before", "after"):
        mine = [r for r in rows if r.get("arm") == arm]
        print(f"  합계 {arm:6} {sum(1 for r in mine if r.get('ok'))}/{len(mine)}")


if __name__ == "__main__":
    main()
