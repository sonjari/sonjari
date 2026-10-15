"""자비스 한 판 — 우리 벤치의 run_one 을 그대로 재사용한다(측정 경로를 같게 하려고)."""
import argparse, json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(r"C:\work\monorepo\tools\alture-jarvis\scripts")))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import bench_research_tasks as B

ap = argparse.ArgumentParser()
ap.add_argument("--prompt", required=True)
ap.add_argument("--host", default="")
ap.add_argument("--budget", type=int, default=600)
ap.add_argument("--out", default="")
a = ap.parse_args()
row = B.run_one("web", a.prompt, a.host, B._token(), budget_sec=a.budget)
text = json.dumps(row, ensure_ascii=False, indent=1)
print(text)
if a.out:
    open(a.out, "w", encoding="utf-8").write(text)
