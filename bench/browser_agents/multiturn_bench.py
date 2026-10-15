"""조사부터 쓰기까지 **한 판에** — 실제 쓰임을 재는 벤치.

## 왜 새로 짜나

지금까지 잰 것은 전부 **조사(읽기)** 였다. 그런데 사람이 실제로 시키는 일은
「찾아서 → 정리해서 → 파일로」 한 줄이다. 그 사슬이 끊기면 앞이 아무리 좋아도
쓸모가 없다.

그리고 2026-09-09 에 클릭 상한을 20초 → 8초로 내렸는데 **조사 3곳에서만 쟀다.**
폼 제출·저장은 조사보다 느릴 수 있어 그 값이 쓰기를 깨뜨릴 수 있다. 내가 바꾼
값이 회귀를 만들었는지 확인하는 것도 이 벤치의 몫이다.

## 채점 — 전부 기계가 센다

    도달        그 사이트에 실제로 갔나
    산출물      파일이 나왔나 · 시킨 형식인가
    ★ 근거      파일 안 숫자 중 도구가 준 적 없는 것 (창작 지표)
    ★ 스킬      그 판에 스킬이 실제로 주입됐나  (95종이 일에 닿는가)
    사슬        조사 도구와 쓰기 도구가 **한 판 안에** 다 있었나

마지막이 이 벤치의 핵심이다. 조사만 하고 안 쓰거나, 안 찾고 쓰기만 하면
「한방」이 아니다.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"E:\evidence-ledger\src")
from evidence_ledger import numbers_claimed_in  # noqa: E402

HERE = pathlib.Path(__file__).parent
import os  # noqa: E402

# 시험 백엔드(예: 8097)로 돌릴 때만 바꾼다(2026-10-01 16GB 밤 측정 · scripts/bench_research_tasks.py 와 같은 변수).
BASE = os.environ.get("JARVIS_BENCH_BASE", "http://127.0.0.1:8091")
TOKEN = pathlib.Path(os.environ.get("JARVIS_BENCH_TOKEN_FILE",
                                    "C:/RoboMetaFit/tools/alture-jarvis/data/control.token")).read_text().strip()
DOCS = pathlib.Path.home() / "Documents" / "JARVIS"

#: 조사 쪽 도구와 쓰기 쪽 도구. **한 판에 둘 다** 있어야 사슬이 이어진 것이다.
READ_TOOLS = {"browser_extract", "browser_read", "browser_open_result", "browser_site_search",
              "google_drive_read", "local_read_document", "local_read_text_file"}
WRITE_TOOLS = {"local_write_document", "local_edit_document", "local_edit_spreadsheet",
               "local_write_file", "artifact_from_observations", "sandbox_run",
               "google_drive_write", "google_drive_prepare_write"}

TASKS = [
    ("wishket_xlsx", "wishket.com", [".xlsx"],
     "위시켓에서 AI 에이전트 관련 프로젝트 3개를 조사해서 엑셀로 정리해줘. "
     "프로젝트명·예상기간·지원자수·공고 URL 을 표로 넣어줘."),
    ("yes24_md", "yes24.com", [".md"],
     "YES24에서 파이썬 책 3권의 쪽수와 ISBN 을 조사해서 마크다운 문서로 만들어줘. "
     "상세페이지 URL 도 같이 넣어줘."),
    ("saramin_doc", "saramin.co.kr", [".docx", ".md", ".xlsx", ".hwpx"],
     "사람인에서 여수 회계 채용 공고 3개를 조사해서 문서로 정리해줘. "
     "회사명·고용형태·마감일·공고 URL 을 표로 넣어줘."),
    # ★ 스킬이 붙어야 잘 되는 과제. 95종이 실제로 일에 닿는지 본다.
    ("resume_skill", "saramin.co.kr", [".docx", ".md"],
     "사람인에서 여수 회계 채용 공고 2개를 보고, 거기 지원할 이력서 초안을 "
     "문서로 만들어줘. 공고가 요구하는 자격을 반영해줘."),
    # ★ `.docx` 를 뒤늦게 넣었다 (2026-09-10). 프롬프트는 「경쟁 분석 **문서로**
    #   정리해줘」이고 워드 문서는 그 말의 정답이다 — 마크다운만 받던 것은 채점기가
    #   과제보다 좁았던 것이다. 골대를 옮기는 것이 아니라 **처음부터 좁았던 것을**
    #   푸는 것이라, 이 판의 실패 원인(파일을 아예 안 만듦)과는 무관하다.
    ("competitor_skill", "wishket.com", [".md", ".xlsx", ".docx"],
     "위시켓에서 AI 에이전트 개발 프로젝트 3개를 조사해서 "
     "경쟁 분석 문서로 정리해줘. 어떤 기술 스택이 자주 요구되는지 정리해줘."),
]


def get(path: str):
    req = urllib.request.Request(BASE + path,
                                 headers={"X-Jarvis-Token": TOKEN})
    return json.load(urllib.request.urlopen(req, timeout=30))


def read_any(path: pathlib.Path) -> str:
    """어떤 형식이든 글자를 꺼낸다. 못 읽으면 **빈 문자열** — 실패를 본문인 척
    돌려주면 채점기가 그것을 내용으로 센다(2026-09-07 에 그렇게 속았다)."""
    sys.path.insert(0, str(HERE.parents[1] / "src"))
    try:
        from alture_jarvis.document_reader import preview_of_file
        return preview_of_file(path, chars=8000)
    except Exception:
        return ""


def _audit_db():
    """살아 있는 DB 를 **읽기 전용으로 직접** 연다. 복사하지 않는다.

    ★ 2026-09-11. 전에는 부를 때마다 `shutil.copy` 로 사본을 떴는데, 자비스가
      쓰는 중인 파일이라 어떤 회차는 앞뒤가 안 맞는 사본이 나왔다. 실제로 붙어
      있던 스킬이 「없음」으로 찍혔다 — 5판 중 2판이 그랬다.

      같은 병을 `content_grade.py` 에서 먼저 만났고 거기서는 「한 번만 뜬다」로
      고쳤다. **여기서는 그 답이 틀리다** — 벤치는 판을 돌리는 **도중에** 읽으므로
      한 번 뜨면 뒤에 오는 판의 기록이 영영 안 보인다.

      그래서 복사를 아예 없애고 `mode=ro` 로 라이브를 직접 읽는다. SQLite 는 WAL
      에서 동시 읽기를 허용하므로 자비스를 방해하지 않고, 사본이 없으니 어긋날
      일도 없다. **같은 병이라도 자리가 다르면 약이 다르다.**
    """
    import sqlite3
    live = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data/jarvis.db")
    conn = sqlite3.connect(f"file:{live.as_posix()}?mode=ro", uri=True, timeout=5.0)
    conn.execute("PRAGMA query_only = 1")
    return conn


def skills_for(job_id: str) -> list[str]:
    """이 판에 실제로 주입된 스킬. 감사 기록이 진실이다.

    ★ **판마다 DB 를 복사하면 안 된다** (2026-09-11). 자비스가 쓰는 중인 파일을
      거듭 복사하니 어떤 회차는 앞뒤가 안 맞는 사본이 나왔고, 실제로 붙어 있던
      스킬이 「없음」으로 찍혔다 — 5판 중 2판이 그랬다.

      같은 병을 `content_grade.py` 에서 먼저 만났는데 **거기만 고쳤다.** 병이 두
      곳에 살면 한 곳만 고치고 고쳤다고 믿게 된다(오늘 `took_ms` 와 404 에서도
      같은 모양이었다). 그래서 여기서도 한 번만 뜨고 그 연결을 재사용한다.
    """
    if not job_id:
        return []
    import sqlite3
    try:
        conn = _audit_db()
        rows = conn.execute(
            "SELECT payload_json FROM audit_log WHERE event='skill_route_selected'"
            " AND subject_id=?", (job_id,)).fetchall()
    except Exception:
        return []
    found: list[str] = []
    for (raw,) in rows:
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            continue
        for key in ("skill", "name", "collection"):
            value = str(data.get(key) or "").strip()
            if value:
                found.append(value)
                break
    return found


def snapshot() -> set:
    return {p for p in DOCS.glob("*") if p.is_file()} if DOCS.exists() else set()


#: ★ **손대지 않은 과제** — 과적합 검사용 (2026-09-13, 결과 보기 전에 커밋).
#
#   사흘 동안 위 다섯 과제만 돌리며 고쳤다. 고친 것들은 범용이었지만(표 모양·빈 답·
#   잠긴 파일·속생각 태그) 그건 **우리 주장**이고, 처음 보는 일에서 되는지는 아무도
#   모른다. 사용자님 말: 「벤치 위주로만 하는 게 아니라 동적으로 다 잘하게 해야 돼.」
#
#   고른 기준 — 튜닝한 사이트(위시켓·예스24 단독·사람인)를 피하고, 새 형식(CSV·한글)과
#   새 모양(두 사이트 대조)을 넣었다. **결과를 보고 과제를 바꾸지 않는다.** 여기서
#   망하면 망한 대로 남긴다(§12). 고치더라도 이 다섯으로 다시 재서 올리지 않는다 —
#   그러면 이것도 튜닝 대상이 된다. 다음 검사는 또 새 과제로 한다.
HOLDOUT = [
    ("danawa_csv", "danawa.com", [".csv"],
     "다나와에서 무선 마우스 인기 상품 3개를 조사해서 CSV 파일로 정리해줘. "
     "상품명·가격·제조사·상품 URL 을 넣어줘."),
    ("jobkorea_hwpx", "jobkorea.co.kr", [".hwpx"],
     "잡코리아에서 순천 사무직 채용 공고 3개를 조사해서 한글 문서로 정리해줘. "
     "회사명·고용형태·마감일·공고 URL 을 표로 넣어줘."),
    ("aladin_docx", "aladin.co.kr", [".docx"],
     "알라딘에서 데이터 분석 책 3권을 조사해서 워드 문서로 만들어줘. "
     "저자·출판사·정가·상세페이지 URL 을 표로 넣어줘."),
    ("musinsa_xlsx", "musinsa.com", [".xlsx"],
     "무신사에서 남성 반팔 티셔츠 인기 상품 3개를 조사해서 엑셀로 정리해줘. "
     "브랜드·상품명·가격·상품 URL 을 넣어줘."),
    ("kyobo_yes24_md", "kyobobook.co.kr", [".md"],
     "교보문고와 YES24에서 '혼자 공부하는 파이썬' 책의 판매가와 쪽수를 각각 확인해서 "
     "비교하는 마크다운 문서로 만들어줘. 사이트별 상세페이지 URL 도 넣어줘."),
]


def main() -> None:
    """★ 가드가 없어서 **import 만으로 벤치가 돌았다** (2026-09-09).

    채점기를 시험하려고 모듈을 불러왔더니 그 자리에서 9판이 시작됐다.
    재는 도구가 부작용을 갖고 있으면 그 도구로 아무것도 못 시험한다.
    """
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    only = sys.argv[2] if len(sys.argv) > 2 else ""
    # `holdout` 이면 손대지 않은 과제를 돌리고, **결과를 따로** 쓴다 — 튜닝 과제의
    # 결과 파일을 덮으면 두 숫자를 나란히 볼 수 없다.
    holdout = only == "holdout"
    tasks = HOLDOUT if holdout else TASKS
    if holdout:
        only = ""
    result_name = "multiturn_holdout.json" if holdout else "multiturn.json"
    # ★ 모델·조건마다 이름표 (2026-09-15, 모델 큐레이션 실측). 이름표 없이 돌리면 26B 기준 결과
    #   `multiturn.json` 을 덮어써 나란히 비교할 수 없게 된다. `MT_TAG=qwen35_9b_32k` 처럼 준다.
    import os
    tag = "".join(ch for ch in os.environ.get("MT_TAG", "") if ch.isalnum() or ch in "_-")
    if tag:
        result_name = result_name.replace(".json", f"_{tag}.json")
    rows = []
    if tag and (HERE / "results" / result_name).exists():
        # ★ 같은 이름표로 과제를 나눠 부르면(`… 3 resume_skill` 다음 `… 3 competitor_skill`) 뒤 호출이 앞 결과를
        #   덮었다(2026-09-15 A2 첫 판에서 이력서 3판이 사라짐). 이름표가 있으면 이어 붙인다.
        try:
            rows = json.loads((HERE / "results" / result_name).read_text(encoding="utf-8"))
        except ValueError:
            rows = []
    for rnd in range(1, rounds + 1):
        for name, host, want_ext, prompt in tasks:
            if only and only != name:
                continue
            before = snapshot()
            out = HERE / f"mt_{name}_{rnd}{'_' + tag if tag else ''}.json"
            started = time.time()
            subprocess.run([str(HERE / ".venv/Scripts/python.exe"), str(HERE / "run_jarvis_one.py"),
                            "--prompt", prompt, "--host", host, "--budget", "900", "--out", str(out)],
                           capture_output=True, timeout=1200)
            try:
                row = json.loads(out.read_text(encoding="utf-8"))
            except Exception as exc:
                row = {"error": str(exc)}
            job = (get("/v1/jobs?limit=1") or [{}])[0]
            result = job.get("result") or {}
            trace = result.get("agent_trace") or {}
            steps = trace.get("steps") or []
            used = [str(s.get("tool") or "") for s in steps if s.get("ok")]
            # ★ **새 파일만 세면 덮어쓰기를 놓친다** (2026-09-09).
            #
            #   `python_books.md` 를 제대로 만들었는데 채점기가 「파일 0개」라고 했다.
            #   같은 이름이 이미 있어서 차집합에 안 걸린 것이다 — 판을 반복하면
            #   두 번째부터는 **늘 덮어쓰기**라 3판 중 3판이 0개로 찍혔다.
            #
            #   그래서 이름이 아니라 **판이 무엇을 만들었다고 말했는가**(걸음의 경로)와
            #   **그 파일이 이 판 도중에 쓰였는가**(수정 시각)를 본다.
            made = [p for p in snapshot()
                    if p.stat().st_mtime >= started - 2] or sorted(snapshot() - before)
            blob = "\n".join(read_any(p) for p in made)
            seen = set(trace.get("tool_numbers") or []) | set(trace.get("tool_numbers_body") or [])
            claimed = numbers_claimed_in(blob)
            # ★ 스킬 주입은 **걸음이 아니라 감사 기록**에 남는다(`skill_route_selected`).
            #   걸음에서 "skill" 이 든 도구를 찾으면 늘 0 이 나온다 — 주입은 도구 호출이
            #   아니라 프롬프트 조립 단계에서 일어나기 때문이다. 처음에 그렇게 셌다가
            #   「스킬 0종」이라는 거짓 결과를 낼 뻔했다.
            skills = skills_for(str(job.get("id") or ""))
            # ★ **판이 끝나자마자 떠 둔다** (2026-09-13).
            #
            #   라운드마다 같은 이름(`python_books_report.md`)으로 덮어쓴다. 채점은
            #   벤치가 다 끝난 뒤에 도는데, 그때 1판 파일 자리에는 3판 파일이 있다 —
            #   1판을 3판 내용으로 채점하고 있었을 수 있다. 내용·양식을 검사하려면
            #   **그 판이 만든 바로 그 파일**이어야 한다.
            keep_dir = HERE / "results" / "artifacts" / (
                f"{'holdout_' if holdout else ''}{tag + '_' if tag else ''}r{rnd}_{name}")
            kept: list[str] = []
            if made:
                keep_dir.mkdir(parents=True, exist_ok=True)
                for one in made:
                    try:
                        target = keep_dir / one.name
                        shutil.copy2(one, target)
                        kept.append(str(target))
                    except OSError:
                        continue
            row.update({
                "round": rnd, "task": name, "job": str(job.get("id") or "")[:8],
                "files": [p.name for p in made],
                "kept": kept,
                "format_ok": any(p.suffix.lower() in want_ext for p in made),
                "chars": len(blob),
                "read_used": sorted(set(used) & READ_TOOLS),
                "write_used": sorted(set(used) & WRITE_TOOLS),
                # ★ 사슬이 이어졌나 — 조사와 쓰기가 **한 판 안에** 다 있어야 한다.
                "chain_ok": bool(set(used) & READ_TOOLS) and bool(set(used) & WRITE_TOOLS),
                "skills": skills,
                "answer_numbers": len(claimed),
                "unsupported": sorted(claimed - seen)[:10],
                "tool_sec": round(sum(int(s.get("took_ms") or 0) for s in steps) / 1000, 1),
                "wall_sec": round(time.time() - started, 1),
            })
            rows.append(row)
            print(f"[r{rnd}] {name:17} {row.get('elapsed_sec')}s 걸음{str(row.get('steps')):>3} "
                  f"· 사슬 {'O' if row['chain_ok'] else 'X'} · 파일 {row['files']} "
                  f"· 형식 {'O' if row['format_ok'] else 'X'} · ★근거없음 {len(row['unsupported'])}",
                  flush=True)
            (HERE / "results" / result_name).write_text(
                json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"완료 — results/{result_name}")



if __name__ == "__main__":
    main()