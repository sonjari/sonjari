"""파이프라인 전수 진단 — 감이 아니라 최근 판을 세어서.

    라우팅 → 스킬 → 계획(요구) → 도구 선택 → 진행 → 정지 → 답
"""

from __future__ import annotations

import collections
import json
import re
import sqlite3
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

# Windows PowerShell 5.1은 stdout을 cp949로 열 수 있다. 이 파일의 표제(—, ①)를
# 출력하다 중간 종료되면 숫자를 재는 도구가 숫자를 못 내는 셈이다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from alture_jarvis.agent import named_sources  # noqa: E402
from alture_jarvis.plan import extract as extract_plan  # noqa: E402

DB = r"C:\RoboMetaFit\tools\alture-jarvis\data\jarvis.db"
LIMIT = 300

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

jobs = []
for row in conn.execute(
    "select id,title,payload_json,result_json,status,created_at,finished_at "
    "from jobs order by created_at desc limit ?",
    (LIMIT,),
):
    try:
        result = json.loads(row["result_json"] or "{}")
    except Exception:
        continue
    trace = result.get("agent_trace") or {}
    steps = trace.get("steps") or []
    if not steps:
        continue  # 도구를 안 쓴 판(짧은 대화)은 이 진단의 대상이 아니다
    jobs.append(
        {
            "id": row["id"],
            "title": row["title"] or "",
            "prompt": (json.loads(row["payload_json"] or "{}") or {}).get("prompt") or "",
            "steps": steps,
            "plan": trace.get("plan") or {},
            "verify": trace.get("verification") or {},
            "answer": result.get("answer") or "",
            "sec": (row["finished_at"] or row["created_at"]) - row["created_at"],
        }
    )

print(f"도구를 쓴 판 {len(jobs)}개 (최근 {LIMIT}개 중)")
print("=" * 76)

# ── ① 계획 층: 요구를 몇 개나 뽑았나 ──────────────────────────────────────
empty = [j for j in jobs if not (j["plan"].get("items") or [])]
print()
print("① 계획 층 — 무엇을 시켰는지 아는가")
print(f"   요구 0개로 돈 판 : {len(empty)}/{len(jobs)}  ({len(empty)*100//max(1,len(jobs))}%)")
print("     └ 요구가 없으면 미달 판정도, 되먹임도, 대조표도 없다")
met = [j for j in jobs if (j["plan"].get("items") or [])]
if met:
    full = sum(1 for j in met if j["plan"].get("met") == j["plan"].get("total"))
    print(f"   요구가 있던 판   : {len(met)}개 · 다 채운 것 {full}개 ({full*100//len(met)}%)")

# ── ② 스킬: 있는데 쓰나 ───────────────────────────────────────────────────
print()
print("② 스킬 — 있는데 쓰는가")
# ⚠ 스킬은 **도구 호출이 아니라 라우팅으로 주입**된다. 처음에 `skill_read` 호출만
#   세다가 「0건」을 보고 「스킬을 한 번도 안 쓴다」고 읽을 뻔했다 — 재는 자에도
#   같은 병이 있다(2026-09-02). 붙은 것은 `audit_log.skill_route_selected` 에 남는다.
routed = {}
for row in conn.execute(
    "select subject_id, payload_json from audit_log where event='skill_route_selected'"
):
    try:
        routed[row[0]] = json.loads(row[1] or "{}")
    except Exception:
        continue
attached = [j for j in jobs if j["id"] in routed]
print(f"   스킬이 붙은 판 : {len(attached)}/{len(jobs)}  ({len(attached)*100//max(1,len(jobs))}%)")
picked = collections.Counter(str(routed[j["id"]].get("skill") or "") for j in attached)
for name, count in picked.most_common(8):
    print(f"     {name:32} {count}")
also = sum(len(routed[j["id"]].get("also") or []) for j in attached)
print(f"     같이 딸려 간 것(복합 판) : {also}")
called = sum(
    1 for j in jobs for s in j["steps"] if str(s.get("tool") or "") == "skill_read"
)
print(f"     `skill_read` 직접 호출  : {called}회  ← 모델은 거의 안 부른다. 코드가 넣어야 한다")

# ── ③ 도구 쏠림 ───────────────────────────────────────────────────────────
print()
print("③ 무슨 도구를 쓰나 (상위 15)")
tools = collections.Counter(str(s.get("tool") or "") for j in jobs for s in j["steps"])
total_steps = sum(tools.values())
for tool, count in tools.most_common(15):
    print(f"   {tool:28} {count:5}  {count*100/total_steps:4.1f}%")

# ── ④ 검색엔진 경유 vs 사이트 직행 ────────────────────────────────────────
print()
print("④ 검색엔진을 거치나, 사이트로 바로 가나")
via_engine = sum(1 for j in jobs if any(str(s.get("tool")) == "browser_search" for s in j["steps"]))
direct = sum(1 for j in jobs if any(str(s.get("tool")) == "browser_site_search" for s in j["steps"]))
print(f"   browser_search(엔진 경유) 쓴 판 : {via_engine}")
print(f"   browser_site_search(직행) 쓴 판 : {direct}")

# ── ⑤ 어떻게 멈추나 ───────────────────────────────────────────────────────
print()
print("⑤ 어떻게 끝나나")
stops = collections.Counter(str(j["verify"].get("stop_reason") or "(없음)") for j in jobs)
for reason, count in stops.most_common():
    print(f"   {reason:28} {count:4}  {count*100//max(1,len(jobs))}%")
states = collections.Counter(str(j["verify"].get("completion_state") or "(없음)") for j in jobs)
print("   완료 상태:", dict(states))

# ── ⑥ 되풀이 — 같은 도구를 같은 인자로 ───────────────────────────────────
print()
print("⑥ 헛걸음 — 같은 도구를 연달아")
repeat_jobs = 0
for job in jobs:
    seen = [str(s.get("tool") or "") for s in job["steps"]]
    runs = 0
    for i in range(1, len(seen)):
        if seen[i] == seen[i - 1]:
            runs += 1
    if runs >= 3:
        repeat_jobs += 1
print(f"   같은 도구가 3번 이상 연달아 나온 판 : {repeat_jobs}/{len(jobs)}")


def _arguments_key(step):
    return json.dumps(step.get("arguments") or {}, ensure_ascii=False, sort_keys=True)


def _failure_key(step):
    if step.get("ok"):
        return ""
    evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
    return "|".join(
        str(value or "").strip()
        for value in (
            step.get("error"),
            evidence.get("failure_kind"),
            evidence.get("error"),
            evidence.get("code"),
        )
        if str(value or "").strip()
    ) or "unknown_failure"


# 전체 3연속은 정상 작업(local_read_text_file x N)까지 섞는다. P3가 줄이려는 것은
# 같은 도구·같은 인자·같은 실패다. 호출 사이에 진단이 끼었으면 새 가설일 수 있으므로
# 연속 실패만 센다.
waste_jobs = 0
waste_runs = collections.Counter()
for job in jobs:
    run_key = None
    run_length = 0
    wasted = False
    for step in job["steps"]:
        failure = _failure_key(step)
        key = (
            str(step.get("tool") or ""),
            _arguments_key(step),
            failure,
        ) if failure else None
        if key is not None and key == run_key:
            run_length += 1
        elif key is not None:
            run_key, run_length = key, 1
        else:
            run_key, run_length = None, 0
        if run_length >= 3:
            wasted = True
            waste_runs[key[0]] += 1
    waste_jobs += int(wasted)
print(
    "   동일 도구·인자·실패가 3번 연속인 판 : "
    f"{waste_jobs}/{len(jobs)} ({waste_jobs*100//max(1,len(jobs))}%)"
)
if waste_runs:
    print("   헛돌기 상위 도구:", ", ".join(f"{k} {v}" for k, v in waste_runs.most_common(8)))

# ── ⑦ 걸음·시간 ───────────────────────────────────────────────────────────
print()
print("⑦ 길이")
lengths = sorted(len(j["steps"]) for j in jobs)
secs = sorted(j["sec"] for j in jobs)


def pct(values, p):
    return values[min(len(values) - 1, int(len(values) * p))] if values else 0


print(f"   걸음  중앙 {pct(lengths,0.5)}  ·  90% {pct(lengths,0.9)}  ·  최대 {lengths[-1] if lengths else 0}")
print(f"   초    중앙 {pct(secs,0.5):.0f}  ·  90% {pct(secs,0.9):.0f}  ·  최대 {secs[-1] if secs else 0:.0f}")

# ── ⑧ 조사 판만 따로 ──────────────────────────────────────────────────────
print()
print("⑧ 「찾아줘」류 조사 판만")
# ★ 이 줄이 오래 거짓말을 했다(2026-09-03에 잡음).
#   본문 읽기를 `browser_extract` 로만 셌는데 분모에는 **파일을 읽는 코드 판**까지
#   들어 있었다 — 로컬 판은 전부 「0회 읽음」으로 찍혀 「조사 판 중앙 0」이 나왔다.
#   실제로는 웹 조사 판의 중앙이 3~5 다. **분모와 세는 자를 짝지어야 한다.**
_WEB_BODY = {"browser_extract"}
_LOCAL_BODY = {"local_read_text_file", "local_read_document"}
research = [
    j for j in jobs
    if any(w in j["prompt"] for w in ("찾아", "조사", "알아봐", "추천", "알려줘", "검색"))
]


def _median(values):
    return sorted(values)[len(values) // 2] if values else 0


if research:
    web = [j for j in research if any(str(s.get("tool", "")).startswith("browser_") for s in j["steps"])]
    local = [j for j in research if j not in web]
    web_reads = [sum(1 for s in j["steps"] if str(s.get("tool")) in _WEB_BODY and s.get("ok")) for j in web]
    local_reads = [sum(1 for s in j["steps"] if str(s.get("tool")) in _LOCAL_BODY and s.get("ok")) for j in local]
    print(f"   웹으로 간 판   {len(web):3}판 · 본문 읽기 중앙 {_median(web_reads)}"
          f" · 0회인 판 {sum(1 for n in web_reads if n == 0)}")
    print(f"   로컬만 본 판   {len(local):3}판 · 본문 읽기 중앙 {_median(local_reads)}"
          f" · 0회인 판 {sum(1 for n in local_reads if n == 0)}")
    short = sum(1 for j in research if str(j["verify"].get("stop_reason")) == "model_stopped_early")
    print(f"   스스로 일찍 멈춘 판 : {short}/{len(research)}")


# ── ⑨ 빈 계획 프롬프트 군집 ────────────────────────────────────────────────
def _empty_cluster(prompt):
    compact = " ".join((prompt or "").split()).lower()
    rules = (
        ("후속 지시", r"제안한\s*대로|말한\s*대로|그대로|이어서|계속|전부\s*다|진행해"),
        ("코드·저장소", r"pytest|unittest|테스트|저장소|\.py\b|\.tsx?\b|구현|버그|코드"),
        ("조사·추천", r"찾아|조사|알아봐|추천|트렌드|이슈|시장|브라우저"),
        ("문서·산출물", r"파일|문서|엑셀|워드|한글|ppt|보고서|초안|만들|작성|수정"),
        ("외부 행위", r"저장|발행|보내|예약|등록|삭제|업로드|스크랩|지원"),
    )
    for label, pattern in rules:
        if re.search(pattern, compact, re.I):
            return label
    return "그 밖"


print()
print("⑨ 요구 0개 프롬프트 — 무엇이 안 잡히나")
clusters = collections.defaultdict(list)
for job in empty:
    clusters[_empty_cluster(job["prompt"])].append(job["prompt"])
for label, prompts in sorted(clusters.items(), key=lambda item: (-len(item[1]), item[0])):
    print(f"   {label:14} {len(prompts):3}")
    for prompt in prompts[:5]:
        print("      ·", " ".join(prompt.split())[:180])

# 저장된 plan은 그 판 당시 코드의 결과다. 지금 파서로 같은 문장을 다시 돌려
# "새로 걸리는 것"을 따로 센다. must_observe는 런타임 라우터가 넘기는 값이라
# 저장된 trace에 없으므로, parser-only와 명백한 관측 갈래를 함께 보인다.
reparsed = []
reparsed_with_route = []
for job in jobs:
    prompt = job["prompt"]
    base = extract_plan(prompt, has_named_source=bool(named_sources(prompt)))
    routed = extract_plan(
        prompt,
        has_named_source=bool(named_sources(prompt)),
        must_observe=_empty_cluster(prompt) in {"코드·저장소", "조사·추천", "문서·산출물"},
    )
    if not base:
        reparsed.append(job)
    if not routed:
        reparsed_with_route.append(job)
print()
print("   현재 파서 백테스트")
print(
    f"      parser-only 요구 0개: {len(reparsed)}/{len(jobs)} "
    f"({len(reparsed)*100//max(1,len(jobs))}%)"
)
print(
    f"      명백한 관측 갈래 포함: {len(reparsed_with_route)}/{len(jobs)} "
    f"({len(reparsed_with_route)*100//max(1,len(jobs))}%)"
)
