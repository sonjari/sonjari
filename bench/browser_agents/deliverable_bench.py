"""산출물 벤치 — 「답을 말했나」가 아니라 「내놔도 되는 물건이 나왔나」를 잰다.

## 왜 새로 짜나

2026-09-06 벤치는 4 과제 전부 **읽기**였다. 그건 Browser Use 의 앞마당이고 우리
도구의 5% 다. 실제로 사람이 시키는 일 — 이력서·보고서·공고·표 — 은 한 칸도 안 쟀다.

## 채점은 기계가 한다

사람이 읽어서 "좋다/나쁘다"를 매기면 그건 벤치가 아니다. 전부 셀 수 있는 것만 본다.

    1. 파일이 나왔나          (개수 · 형식)
    2. 시킨 형식이 맞나        (xlsx 달라고 했는데 md 만 나왔으면 실패)
    3. 파일 안에 출처 URL 이 있나
    4. ★ 그 URL 이 실재하나    (HTTP 로 찍어 본다)
    5. ★ 파일 안 숫자 중 **도구가 준 적 없는 것**이 몇 개인가
       → 2026-09-06 아침에 공개한 evidence-ledger 로 센다.
         990p 사건이 정확히 이 검사에 걸리는 모양이다.

4·5 번이 이 벤치의 핵심이다. 파일을 만드는 건 쉽고, **근거가 붙은 파일**을 만드는
것이 어렵다.

## 공정성

두 리그에 **같은 프롬프트**를 준다. Browser Use 도 write_file 도구를 갖고 있으므로
파일을 못 만드는 것이 아니다 — 무엇을 만드는지가 다를 뿐이다.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from evidence_ledger import numbers_claimed_in, numbers_in

HERE = pathlib.Path(__file__).parent
JV_PY = pathlib.Path(r"C:\work\monorepo\tools\alture-jarvis\.venv\Scripts\python.exe")
BU_PY = HERE / ".venv" / "Scripts" / "python.exe"
JARVIS_DOCS = pathlib.Path.home() / "Documents" / "JARVIS"
BUDGET = 600

# (이름, 호스트, 프롬프트, 요구한 확장자)
TASKS = [
    ("wishket_xlsx", "wishket.com",
     "위시켓에서 AI 에이전트 관련 프로젝트 3개를 조사해서 엑셀 파일로 정리해줘. "
     "프로젝트명·예상기간·지원자수·공고 URL 을 표로 넣어줘.",
     [".xlsx"]),
    ("yes24_md", "yes24.com",
     "YES24에서 파이썬 책 3권의 쪽수와 ISBN 을 조사해서 표가 들어간 마크다운 문서로 만들어줘. "
     "각 책의 상세페이지 URL 도 같이 넣어줘.",
     [".md"]),
    ("saramin_doc", "saramin.co.kr",
     "사람인에서 여수 회계 채용 공고 3개를 조사해서 문서로 정리해줘. "
     "회사명·고용형태·마감일·공고 URL 을 표로 넣어줘.",
     [".md", ".docx", ".xlsx", ".hwpx"]),
]

URL_RE = __import__("re").compile(r"https?://[^\s)\"'<>\]]+")


READ_FAILURES: list[str] = []


def read_any(path: pathlib.Path) -> str:
    """어떤 형식이든 글자를 꺼낸다.

    ★ 실패를 **본문인 척 돌려주지 않는다** (2026-09-07 에 그렇게 속았다).
      openpyxl 이 없어서 못 읽은 것을 "[읽기 실패 …]" 27자로 돌려줬고, 채점기는
      그걸 문서 내용으로 세었다. 못 읽었으면 빈 문자열을 주고 READ_FAILURES 에
      크게 남긴다 — 조용한 실패가 오늘만 세 번째다.
    """
    suffix = path.suffix.lower()
    try:
        if suffix in {".md", ".txt", ".csv", ".json"}:
            return path.read_text(encoding="utf-8", errors="replace")
        if suffix == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(path, data_only=True)
            return "\n".join(
                " ".join("" if c is None else str(c) for c in row)
                for ws in wb.worksheets for row in ws.iter_rows(values_only=True)
            )
        if suffix == ".docx":
            import docx
            return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    except Exception as exc:
        READ_FAILURES.append(f"{path.name}: {type(exc).__name__}: {exc}")
        return ""
    if suffix not in {".md", ".txt", ".csv", ".json", ".xlsx", ".docx"}:
        READ_FAILURES.append(f"{path.name}: 읽는 법 없음({suffix})")
    return ""


def url_alive(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return 200 <= r.status < 400
    except urllib.error.HTTPError as e:
        return e.code < 500          # 405 등은 살아 있는 주소다
    except Exception:
        return False


def grade(files, tool_numbers, want_ext):
    """센다. 판단하지 않는다."""
    READ_FAILURES.clear()
    texts = {f: read_any(f) for f in files}
    blob = "\n".join(texts.values())
    urls = sorted(set(URL_RE.findall(blob)))
    alive = [u for u in urls[:8] if url_alive(u)]      # 위에서 8개만 찍어 본다
    claimed = numbers_claimed_in(blob)
    return {
        "read_failures": list(READ_FAILURES),
        "files": [f.name for f in files],
        "formats": sorted({f.suffix.lower() for f in files}),
        "format_ok": any(f.suffix.lower() in want_ext for f in files),
        "chars": len(blob),
        "urls": len(urls),
        "urls_checked": len(urls[:8]),
        "urls_alive": len(alive),
        # ★ 파일에 적힌 숫자 중 도구가 준 적 없는 것. 990p 가 걸리는 자리다.
        "numbers_in_doc": len(claimed),
        "unsupported_numbers": sorted(claimed - tool_numbers)[:12],
    }


def jarvis_tool_numbers() -> set:
    """방금 끝난 자비스 잡의 **도구가 준 숫자**를 모은다.

    문서에 적힌 숫자에서 이걸 빼면 「어디서도 안 온 숫자」가 남는다. 990p 가
    걸리는 자리이고, 이 벤치의 핵심 지표다.
    """
    found = set()
    try:
        token = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data/control.token")
        req = urllib.request.Request(
            "http://127.0.0.1:8091/v1/jobs?limit=1",
            headers={"Authorization": "Bearer " + token.read_text(encoding="utf-8").strip()})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        items = d if isinstance(d, list) else (d.get("items") or d.get("jobs") or [])
        steps = (((items[0].get("result") or {}).get("agent_trace") or {}).get("steps") or [])
        for step in steps:
            found |= numbers_in(step.get("evidence") or {})
    except Exception as exc:
        print("  ! 도구 숫자 수집 실패:", type(exc).__name__, exc, flush=True)
    return found


def snapshot(folder: pathlib.Path) -> set:
    return {p for p in folder.glob("*") if p.is_file()} if folder.exists() else set()


def run_jarvis(name, host, prompt, want_ext):
    before = snapshot(JARVIS_DOCS)
    out = HERE / f"deliv_jv_{name}.json"
    t0 = time.time()
    subprocess.run([str(JV_PY), str(HERE / "run_jarvis_one.py"), "--prompt", prompt,
                    "--host", host, "--budget", str(BUDGET), "--out", str(out)],
                   capture_output=True, timeout=BUDGET + 240)
    row = {}
    try:
        row = json.loads(out.read_text(encoding="utf-8"))
    except Exception as exc:
        row = {"error": str(exc)}
    new = sorted(snapshot(JARVIS_DOCS) - before)
    row.update(grade(new, jarvis_tool_numbers(), want_ext))
    row["seconds"] = round(time.time() - t0, 1)
    return row


def run_bu(name, host, prompt, want_ext):
    work = HERE / "bu_work" / name
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    out = work / "result.json"
    t0 = time.time()
    subprocess.run([str(BU_PY), str(HERE / "run_bu.py"), "--prompt", prompt,
                    "--host", host, "--budget", str(BUDGET), "--max-steps", "30",
                    "--out", str(out)],
                   capture_output=True, timeout=BUDGET + 240, cwd=str(work))
    row = {}
    try:
        row = json.loads(out.read_text(encoding="utf-8"))
    except Exception as exc:
        row = {"error": str(exc)}
    made = sorted(p for p in work.glob("**/*") if p.is_file() and p.name != "result.json")
    # 같은 잣대. BU 는 걸음별 결과를 안 남기므로 답 본문에서 모은다(우리보다 후하다).
    row.update(grade(made, numbers_claimed_in(str(row.get("answer") or "")), want_ext))
    row["seconds"] = round(time.time() - t0, 1)
    return row


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    rows = []
    for name, host, prompt, want in TASKS:
        if only and only != name:
            continue
        for arm, fn in (("jarvis_local", run_jarvis), ("browser_use_local", run_bu)):
            print(f"\n{'=' * 68}\n[{arm}] {name}", flush=True)
            r = fn(name, host, prompt, want)
            r.update({"task": name, "arm": arm})
            rows.append(r)
            print(f"  {r.get('seconds')}s  파일 {r.get('files')}  형식맞음 {r.get('format_ok')}", flush=True)
            print(f"  URL {r.get('urls')}개 (살아있음 {r.get('urls_alive')}/{r.get('urls_checked')})  "
                  f"문서내 숫자 {r.get('numbers_in_doc')}", flush=True)
            (HERE / "results" / "deliverable_results.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n완료 — results/deliverable_results.json")
