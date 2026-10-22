"""게임 팩 모델 비교 — 채점 기준은 돌리기 전에 고정(2026-09-27)."""
import json, sys, time, urllib.request, urllib.error
from pathlib import Path
S = Path(__file__).resolve().parent / "work"  # 시험용 토큰·데이터·결과는 여기(저장소에 안 올린다 — .gitignore)
BASE = "http://127.0.0.1:8097"
TOKEN = (S / "token").read_text().strip()
PROJECT = r"E:\UnityProjects\OntelicPlayground"
TASKS = {
    "texture": (f"{PROJECT} 유니티 프로젝트에서 2048보다 큰 텍스처가 있는지 점검해서 알려줘. 파일은 고치지 마.",
                "texture_audit", ["UnityTutorial_Skybox05_4k"]),
    "missing": (f"{PROJECT} 유니티 프로젝트의 프리팹이랑 씬에서 빠진 참조(Missing)가 있는지 찾아서 알려줘. 고치지는 마.",
                "missing_references", ["InGameMenu", "VFX_Angry"]),
}

def call(path, body=None, timeout=60):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-Jarvis-Token": TOKEN},
                                 method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def run(model, task, n):
    prompt, recipe, must = TASKS[task]
    job = call("/v1/chat", {"prompt": prompt, "session_id": f"ub-{model}-{task}-{n}-{int(time.time())}",
                            "workspace_mode": "code", "code_workspace": PROJECT, "open_results": False,
                            "measurement": True})
    jid = job["id"]; started = None; detail = {}
    deadline = time.time() + 900
    while time.time() < deadline:
        time.sleep(5)
        try: detail = call(f"/v1/jobs/{jid}")
        except Exception: continue
        if detail.get("started_at") and started is None:
            started = float(detail["started_at"]); deadline = started + 900
        if detail.get("status") in {"completed", "failed", "cancelled", "waiting_approval"}:
            break
    res = detail.get("result") or {}
    steps = (res.get("agent_trace") or {}).get("steps") or []
    answer = str(res.get("answer") or "")
    ran = [s for s in steps if s.get("tool") == "unity_run_recipe"]
    verified = any((s.get("arguments") or {}).get("recipe") == recipe and (s.get("evidence") or {}).get("verified") for s in ran)
    named = all(word in answer for word in must)
    fin = float(detail.get("finished_at") or time.time())
    row = {"model": model, "task": task, "n": n, "job": jid, "status": detail.get("status"),
           "sec": round(fin - (started or fin), 1), "steps": len(steps), "tools": [s.get("tool") for s in steps],
           "recipe_verified": verified, "named_all": named, "pass": bool(verified and named),
           "answer": answer[:1500]}
    with open(S / "results.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(model, task, n, row["status"], row["sec"], "pass" if row["pass"] else "FAIL", row["tools"], flush=True)

if __name__ == "__main__":
    model = sys.argv[1]
    for n in range(1, int(sys.argv[2]) + 1):
        for task in TASKS:
            run(model, task, n)
