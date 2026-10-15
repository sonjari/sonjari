"""시간을 **도구와 모델로 가른다.** 총합만 보면 무엇을 고칠지 모른다.

## 왜 이제야 되나

`Observation.took_ms` 칸은 처음부터 있었는데 **아무도 안 채웠다.** 그래서 판이
456초 걸렸을 때 도구가 느린지 모델이 느린지 가를 수가 없었고, 편차를 고치려는데
무엇을 고칠지 모르는 상태였다. 2026-09-09 에 게이트웨이 길목에서 재도록 고쳤다.

    총 시간 - 도구 시간 합 = 모델 생각 + 큐 대기
"""
from __future__ import annotations
import json, pathlib, subprocess, sys, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).parent
TOKEN = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data/control.token").read_text().strip()
LABEL = sys.argv[1] if len(sys.argv) > 1 else "run"
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 1

TASKS = [
    ("wishket", "wishket.com", "위시켓에서 AI 에이전트 관련 프로젝트 2개의 예상 기간을 알려줘"),
    ("yes24", "yes24.com", "YES24에서 파이썬 책 2권의 쪽수와 ISBN을 알려줘"),
    ("saramin", "saramin.co.kr", "사람인에서 여수 회계 채용 공고 2개의 회사명과 고용형태를 알려줘"),
]


def get(path: str):
    req = urllib.request.Request("http://127.0.0.1:8091" + path,
                                 headers={"X-Jarvis-Token": TOKEN})
    return json.load(urllib.request.urlopen(req, timeout=25))


rows = []
for rnd in range(1, ROUNDS + 1):
    for name, host, prompt in TASKS:
        out = HERE / f"split_{LABEL}_{name}_{rnd}.json"
        subprocess.run([str(HERE / ".venv/Scripts/python.exe"), str(HERE / "run_jarvis_one.py"),
                        "--prompt", prompt, "--host", host, "--budget", "600", "--out", str(out)],
                       capture_output=True, timeout=900)
        row = json.loads(out.read_text(encoding="utf-8"))
        job = (get("/v1/jobs?limit=1") or [{}])[0]
        items = get(f"/v1/jobs/{job['id']}/steps").get("items") or []
        tool = sum(int(s.get("took_ms") or 0) for s in items) / 1000
        total = float(row.get("elapsed_sec") or 0)
        rows.append({"label": LABEL, "round": rnd, "task": name, "steps": len(items),
                     "total": round(total, 1), "tool": round(tool, 1),
                     "model": round(total - tool, 1),
                     "tool_pct": round(tool / max(total, 1) * 100),
                     "slowest": sorted(
                         ((s["tool"], int(s.get("took_ms") or 0)) for s in items),
                         key=lambda x: -x[1])[:2]})
        r = rows[-1]
        print(f"[{LABEL} r{rnd}] {name:9} 총 {r['total']:6.1f}s = 도구 {r['tool']:5.1f}s "
              f"({r['tool_pct']:>2}%) + 모델 {r['model']:6.1f}s   걸음 {r['steps']}", flush=True)
        (HERE / "results" / f"time_split_{LABEL}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("완료")
