"""편차를 **원인별로** 가른다. 총합만 보면 무엇을 고칠지 모른다.

## 왜 필요한가

2026-09-09 밤. 「같은 실패 3번 반복」을 고쳤는데 첫 판이 오히려 느렸다(442초).
열어 보니 실패 종류가 달랐다 — 주소 오타(`wisekeet.com`), 검색칸 못 찾음,
레시피 없는 클릭. **편차는 한 가지 원인이 아니었다.**

그래서 판마다 「실패한 걸음이 무엇이었나」를 세어 분류표를 만든다. 총 시간만
보면 고칠 자리를 못 고르고, 고친 뒤에도 효과를 못 가린다.
"""
from __future__ import annotations
import json, pathlib, sys, urllib.request
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).parent
TOKEN = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data/control.token").read_text().strip()


def jobs(limit=40):
    req = urllib.request.Request(f"http://127.0.0.1:8091/v1/jobs?limit={limit}",
                                 headers={"X-Jarvis-Token": TOKEN})
    rows = json.load(urllib.request.urlopen(req, timeout=30))
    return rows if isinstance(rows, list) else (rows.get("items") or [])


def classify(error: str) -> str:
    """실패 걸음 하나를 한 낱말로. 분류가 없으면 원문 앞머리를 그대로 쓴다 —
    **분류표에 없는 것이 조용히 사라지면** 그게 제일 나쁘다."""
    text = str(error or "")
    if not text:
        return ""
    head = text.split(":")[0].strip()
    return head or text[:40]


def report(path: pathlib.Path, label: str) -> None:
    rows = json.load(open(path, encoding="utf-8"))
    by_id = {j["id"][:8]: j for j in jobs()}
    kinds: Counter = Counter()
    lines = []
    for r in rows:
        job = by_id.get(str(r.get("job") or ""))
        steps = (((job or {}).get("result") or {}).get("agent_trace") or {}).get("steps") or []
        bad = [classify(s.get("error")) for s in steps if not s.get("ok")]
        bad = [b for b in bad if b]
        kinds.update(bad)
        lines.append((r["round"], r["task"], r.get("steps"), r.get("elapsed_sec"),
                      len(bad), " ".join(bad[:3])))
    print(f"\n=== {label} ({len(rows)}판)")
    print(f"{'판':4}{'과제':10}{'걸음':>5}{'초':>8}{'실패':>5}  실패 종류")
    for rnd, task, st, sec, nbad, kind in lines:
        print(f"r{rnd:<3}{task:10}{str(st):>5}{str(sec):>8}{nbad:>5}  {kind}")
    secs = [r.get("elapsed_sec") or 0 for r in rows if r.get("steps")]
    if secs:
        secs.sort()
        print(f"  시간 최소 {secs[0]:.0f} · 중앙 {secs[len(secs)//2]:.0f} · 최대 {secs[-1]:.0f}"
              f"  (최대/최소 {secs[-1]/max(secs[0],1):.1f}배)")
    print("  실패 종류 합계:", dict(kinds.most_common()))


if __name__ == "__main__":
    for name, label in (("repeat_qwen9b_before_fix.json", "수정 전"),
                        ("repeat_qwen9b_after.json", "수정 후")):
        p = HERE / "results" / name
        if p.exists():
            report(p, label)
