# -*- coding: utf-8 -*-
"""백엔드의 스택을 짧은 간격으로 찍어 시각과 함께 남긴다 — 「모델도 도구도 아닌 시간」에 무엇이 도는지 보려고.

쓰기: python spy_backend.py <저장 파일> [초=90] [간격=0.4]   (py-spy 가 깔려 있어야 한다 — `pip install py-spy`)

찍는 동안 다른 창에서 사다리 한 판을 돌리고, 끝나면 `spy_tail.py` 로 구간별로 추린다.
★ 백엔드는 `scripts\\task_entry.py` 로 뜬다. 명령줄에 `alture_jarvis` 가 든 것을 찾으면 MCP 서버가 잡힌다(2026-10-07 에 그렇게 한 번 헛찍었다).
"""
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SPY = shutil.which("py-spy") or str(Path(os.environ.get("APPDATA", "")) / "Python" / "Python311" / "Scripts" / "py-spy.exe")
out = Path(sys.argv[1])
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 90.0
gap = float(sys.argv[3]) if len(sys.argv) > 3 else 0.4

listing = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     # 백엔드는 `scripts\task_entry.py` 로 뜬다(MCP 서버 `-m alture_jarvis.mcp_server` 와 음성 서버는 다른 프로세스다).
     "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*task_entry.py*' } "
     "| Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json"],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
).stdout
rows = json.loads(listing) if listing.strip() else []
rows = rows if isinstance(rows, list) else [rows]
ids = {int(r["ProcessId"]) for r in rows}
# 실제 인터프리터는 자식 쪽이다(venv 실행기가 부모).
child = [r for r in rows if int(r["ParentProcessId"]) in ids]
target = int((child or rows)[0]["ProcessId"]) if rows else 0
print("백엔드 프로세스:", [(r["ProcessId"], r["ParentProcessId"]) for r in rows], "→ 찍을 대상", target)
if not target:
    raise SystemExit("백엔드를 못 찾음")

end = time.time() + seconds
count = 0
with out.open("w", encoding="utf-8") as handle:
    while time.time() < end:
        at = time.time()
        dump = subprocess.run([SPY, "dump", "--pid", str(target)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace").stdout
        handle.write(json.dumps({"at": at, "dump": dump}, ensure_ascii=False) + "\n")
        handle.flush()
        count += 1
        time.sleep(max(0.0, gap - (time.time() - at)))
print("찍은 수", count)
