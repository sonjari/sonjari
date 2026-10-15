"""아틀라스에 **없는** 사이트로 첫 판. 천장을 재는 제일 싼 방법.

지금까지 잰 3사이트(위시켓·YES24·사람인)는 전부 아틀라스가 아는 곳이었다.
2/3 은 레시피도 없이 됐지만, **이름조차 처음 보는 곳**은 아직 안 재 봤다.

되면 「처음 보는 사이트도 된다」가 생기고, 안 되면 **천장이 어디인지** 보인다.
둘 다 값지다. 조건은 가장 불리하게 — 2등급(qwen3.5:9b · 8.9GB).
"""
import json, pathlib, subprocess, sys, time, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"E:\evidence-ledger\src")
from evidence_ledger import numbers_claimed_in
HERE = pathlib.Path(__file__).parent
TOKEN = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data/control.token").read_text().strip()

TASKS = [
    ("aladin", "aladin.co.kr",
     "알라딘에서 파이썬 책 2권의 쪽수와 정가를 알려줘"),
    ("oliveyoung", "oliveyoung.co.kr",
     "올리브영에서 선크림 2개의 상품명과 판매가를 알려줘"),
    ("enuri", "enuri.com",
     "에누리에서 무선마우스 2개의 상품명과 최저가를 알려줘"),
]

rows = []
for name, host, prompt in TASKS:
    out = HERE / f"unknown_{name}.json"
    subprocess.run([str(HERE / ".venv/Scripts/python.exe"), str(HERE / "run_jarvis_one.py"),
                    "--prompt", prompt, "--host", host, "--budget", "600", "--out", str(out)],
                   capture_output=True, timeout=900)
    row = json.loads(out.read_text(encoding="utf-8"))
    req = urllib.request.Request("http://127.0.0.1:8091/v1/jobs?limit=1",
                                 headers={"X-Jarvis-Token": TOKEN})
    job = (json.load(urllib.request.urlopen(req, timeout=25)) or [{}])[0]
    tr = ((job.get("result") or {}).get("agent_trace") or {})
    seen = set(tr.get("tool_numbers") or []) | set(tr.get("tool_numbers_body") or [])
    ans = str((job.get("result") or {}).get("answer") or "")
    row.update({"task": name, "job": str(job.get("id") or "")[:8], "answer_full": ans[:600],
                "unsupported": sorted(numbers_claimed_in(ans) - seen)[:10]})
    rows.append(row)
    print(f"{name:11} 걸음 {str(row.get('steps')):>3} · {row.get('elapsed_sec')}s · "
          f"도달 {row.get('reached_host')} · ★근거없음 {len(row['unsupported'])} {row['unsupported'][:4]}",
          flush=True)
    (HERE / "results" / "unknown_sites.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("완료")
