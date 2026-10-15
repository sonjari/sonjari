"""리그 고장으로 죽은 두 칸만 다시. 날짜 오탐 수정 뒤라 대칭으로 재진다."""
import json, pathlib, subprocess, sys, time, urllib.request
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"E:\evidence-ledger\src")
from evidence_ledger import numbers_claimed_in
HERE = pathlib.Path(__file__).parent
TOKEN = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data/control.token").read_text().strip()
CELLS = [("wishket", "wishket.com", "위시켓에서 AI 에이전트 관련 프로젝트 2개의 예상 기간을 알려줘"),
         ("yes24", "yes24.com", "YES24에서 파이썬 책 2권의 쪽수와 ISBN을 알려줘")]
out_rows = []
for name, host, prompt in CELLS:
    out = HERE / f"rerun_{name}.json"
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
    row["unsupported"] = sorted(numbers_claimed_in(ans) - seen)[:10]
    row["task"] = name
    out_rows.append(row)
    print(f"{name:9} 걸음 {row.get('steps'):>3} · {row.get('elapsed_sec')}s · "
          f"도달 {row.get('reached_host')} · ★근거없음 {len(row['unsupported'])} {row['unsupported'][:4]}",
          flush=True)
(HERE / "results" / "repeat_qwen9b_rerun.json").write_text(
    json.dumps(out_rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("완료")
