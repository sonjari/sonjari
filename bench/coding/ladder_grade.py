"""사다리 결과를 채점한다. 사용: ladder_grade.py <폴더(results.json + workspaces.zip)> [라벨]"""
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import ladder  # noqa: E402

folder = Path(sys.argv[1])
label = sys.argv[2] if len(sys.argv) > 2 else folder.name
raw = (folder / "results.json").read_text(encoding="utf-8-sig")
rows = json.loads(raw)
if isinstance(rows, dict):
    rows = [rows]

work = folder / "ws"
if work.exists():
    shutil.rmtree(work)
with zipfile.ZipFile(folder / "workspaces.zip") as z:
    for member in z.infolist():
        # Compress-Archive 는 백슬래시 경로를 쓴다 — 정규화해서 푼다.
        target = work / member.filename.replace("\\", "/")
        if member.is_dir() or member.filename.endswith(("/", "\\")):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(z.read(member))

print(f"=== {label} ===")

# ── 분모를 먼저 정한다 (2026-09-22) ─────────────────────────────────────────────
# 예전 채점기는 **돌지도 않은 판**(승인 대기에서 멈춤·취소돼 걸음 0)을 분모에 넣었고, **시간 초과로 멈춘 판**(status=running)을
# 파일만 보고 통과로 셌다. 그래서 두 벤치의 숫자가 같은 잣대가 아니었다(15/18 은 실제로는 16판 중 15). 이제 세 가지를 따로 센다.
#   실행 판   잡이 끝까지 돌았거나(completed/failed) 시간 초과로 우리가 멈춘 것(timed_out)
#   제외      돌지 못한 것 — 승인 대기에서 멈춤 · 걸음 0 으로 취소됨
def classify(row: dict) -> str:
    status = str(row.get("status") or "")
    steps = int(row.get("steps") or 0)
    if row.get("timed_out") or (status == "running" and int(row.get("seconds") or 0) >= 1200):
        return "timeout"      # 옛 드라이버는 status=running 으로만 남겼다
    if status in ("completed", "failed"):
        return "ran"
    if status in ("waiting_approval", "needs_input") or (status == "cancelled" and steps == 0):
        return "excluded"
    return "ran" if steps > 0 else "excluded"


print(f"{'과제':<22}{'잡':<10}{'초':>5}{'걸음':>5}  {'채점':<6}  구분   이유 / 도구열")
graded = []
for row in rows:
    task = row["id"]
    ws = work / f"{task}-r{row['rep']}"
    result = ladder.check(task, ws) if ws.exists() else {"passed": False, "why": "작업 폴더 없음"}
    tools = row.get("tools") or []
    if isinstance(tools, str):
        tools = [tools]
    kind = classify(row)
    graded.append((task, row["status"], row["seconds"], row["steps"], result["passed"], result["why"], tools, row, kind))
    mark = "✅" if result["passed"] else "❌"
    if kind == "timeout":
        mark = "⏱" + mark
    if kind == "excluded":
        mark = "—"
    shown = result["why"] or "통과"
    label_kind = {"ran": "실행", "timeout": "초과", "excluded": "제외"}[kind]
    print(f"{task:<22}{row['status']:<10}{row['seconds']:>5}{row['steps']:>5}  {mark:<6}  {label_kind}   {shown[:100]}")

scheduled = len(graded)
ran = [g for g in graded if g[8] in ("ran", "timeout")]
excluded = [g for g in graded if g[8] == "excluded"]
files_ok = sum(1 for g in ran if g[4])
finished = [g for g in ran if g[8] == "ran"]
completed = sum(1 for g in finished if g[1] == "completed")
strict = sum(1 for g in finished if g[1] == "completed" and g[4])
timeouts = sum(1 for g in ran if g[8] == "timeout")
print(f"\n예정 {scheduled}판 · 실행 {len(ran)}판 (제외 {len(excluded)}: 돌지 못함 · 시간 초과로 멈춘 것 {timeouts}판은 실행에 포함)")
print(f"  파일 채점 통과      {files_ok}/{len(ran)}   ← 파일만 보면 되는 것(시간 초과 판 포함 · 잡이 실패로 끝나도 파일이 맞으면 통과)")
print(f"  잡 완료            {completed}/{len(ran)}   ← 잡이 스스로 completed 로 끝난 것")
print(f"  엄격 통과          {strict}/{len(ran)}   ← 잡이 completed 이고 파일도 통과 (머리 숫자는 이것)")
print("\n--- 도구열 ---")
for task, status, secs, steps, ok, why, tools, row, _kind in graded:
    print(f"{task}: {' '.join(str(t).replace('local_','').replace('browser_','b_') for t in tools)[:220]}")
    diag = row.get("diagnosis")
    if diag and diag not in ("null", ""):
        print(f"   diagnosis={str(diag)[:300]}")
    if row.get("error"):
        print(f"   error={row['error']} completion_state={row.get('completion_state')}")
