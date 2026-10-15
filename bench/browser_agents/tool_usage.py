"""**실제로 쓰인 도구**를 센다. 추리기는 감이 아니라 이 분포로 정한다.

## 왜

에이전트 카탈로그는 갈래별로 안 줄어든다 — 조사 과제에도 진로DB·일정·카메라·한글이
전부 손에 들어간다(133개 · 스키마 13,926토큰, 매 걸음 다시 실림).

2026-09-09 실측: 「YES24에서 파이썬 책 쪽수」 판이 `career_strategy_lookup`
(job="데이터 사이언티스트", region="부산")을 **6번**, `schedule_list` 를 **4번**
불렀다. 25걸음 중 13걸음(52%)이 과제와 무관했고, 그래서 3권 중 1권만 읽고 파일도
못 만들었다.

**도구 추리기는 토큰 절감이 아니라 정확도 문제였다.**

다만 빼기 전에 세야 한다 — 도구를 빼면 「없어서 못 하는」 판이 생기고, 그건 이
저장소가 여러 번 겪은 자리다(도구는 순서에 없으면 안 쓰인다).
"""
from __future__ import annotations
import json, pathlib, sqlite3, shutil, sys
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")

DATA = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data")
TMP = pathlib.Path("C:/Users/user/AppData/Local/Temp/claude/toolusage.sqlite")


def db() -> sqlite3.Connection:
    TMP.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):     # WAL 도 같이. 본체만 뜨면 최근 것이 안 보인다.
        one = DATA / ("jarvis.db" + suffix)
        if one.exists():
            shutil.copy(one, str(TMP) + suffix)
    return sqlite3.connect(TMP)


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    conn = db()
    rows = conn.execute(
        "SELECT payload_json, result_json FROM jobs"
        " WHERE result_json IS NOT NULL ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    used: Counter = Counter()
    per_job: Counter = Counter()
    jobs = 0
    for payload_raw, result_raw in rows:
        try:
            steps = ((json.loads(result_raw or "{}").get("agent_trace") or {})
                     .get("steps") or [])
        except ValueError:
            continue
        if not steps:
            continue
        jobs += 1
        names = [str(s.get("tool") or "") for s in steps]
        used.update(names)
        per_job.update(set(names))

    catalog = json.loads(
        (pathlib.Path(__file__).parent / "results" / "catalog_names.json").read_text(
            encoding="utf-8")) if (pathlib.Path(__file__).parent / "results"
                                   / "catalog_names.json").exists() else []
    print(f"판 {jobs}개에서 쓰인 도구 {len(used)}종 (호출 {sum(used.values())}회)\n")
    print(f"{'도구':30}{'호출':>6}{'몇 판에서':>9}")
    for name, count in used.most_common():
        print(f"{name:30}{count:>6}{per_job[name]:>9}")
    if catalog:
        never = sorted(set(catalog) - set(used))
        print(f"\n★ 한 번도 안 쓰인 도구 {len(never)}/{len(catalog)}종:")
        for i in range(0, len(never), 4):
            print("   " + " · ".join(never[i:i + 4]))


if __name__ == "__main__":
    main()
