"""**「썼나」가 아니라 「잘 썼나」를 센다.** 사슬 벤치의 뒷채점기.

## 왜 따로 붙이나

`multiturn_bench.py` 가 세는 것은 넷이다 — 도달·사슬·산출물·창작. 그런데 이 넷은
전부 통과하면서 **내용이 빈 파일**이 나올 수 있다. 실제 표본이 있다:

    | 도서명                | 쪽수      | ISBN     |
    | Do it! 점프 투 파이썬 | 확인 불가 | 확인 불가 |

이게 파일로 나왔으면 앞 채점기는 **통과**를 준다. 파일 있고, 형식 맞고, 숫자를
안 지어냈으니까 — **칸이 비어서 지어낼 숫자가 아예 없었던 것**인데 그게 만점이
된다. 창작 지표는 채운 칸만 볼 수 있고, 안 채운 칸에 대해서는 침묵한다.

## 세는 것 셋

    행     시킨 개수만큼 나왔나 (3개 시켰는데 2행이면 2/3)
    열     시킨 항목이 열로 있나 (회사명·고용형태·마감일·URL)
    ★채움  **채워야 할 칸 중 몇 %를 실제로 채웠나**

마지막이 「쓰기를 잘하나」에 제일 가깝다.

## 분모를 먼저 정한다

행이 0이어도 채움 비율은 **0%** 이지 「해당 없음」이 아니다. 표가 아예 없으면
채워야 할 칸을 하나도 안 채운 것이다 — 없는 것을 분모에서 빼면 아무것도 안 한
판이 만점으로 올라온다. 이 저장소가 눈금 분모로 다섯 번 속았다.

산문 산출물(이력서 초안)은 표가 아니므로 채움 비율을 내지 않고 **글자수만**
적는다. 억지로 한 숫자에 섞으면 그 숫자가 아무 뜻도 없어진다.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import sqlite3
import sys

import doc_form

sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).parent
DOCS = pathlib.Path.home() / "Documents" / "JARVIS"

#: 「채웠다」로 안 쳐 주는 것. 사람이 보면 빈칸인 말들이다.
_BLANK = re.compile(
    r"^\s*(?:[-–—]+|n/?a|없음|미상|미확인|확인\s*불가|확인\s*못|정보\s*없|알\s*수\s*없"
    r"|tbd|\?+|null|none|0?\s*건|\.{2,})\s*$",
    re.I,
)

#: 과제마다 **무엇을 몇 개** 시켰나. 프롬프트에서 그대로 옮긴 것이다.
#
# 열 이름은 사람이 여러 가지로 쓴다(「공고 URL」·「링크」·「주소」). 그래서 하나가
# 아니라 **낱말 후보 묶음**으로 잡는다 — 이름이 달라서 못 찾는 것과 정말 없는 것을
# 섞으면 채점기가 판보다 좁아진다(2026-09-10 에 형식 목록에서 그 일을 겪었다).
WANT: dict[str, dict] = {
    "wishket_xlsx": {"rows": 3, "cols": {
        "프로젝트명": ("프로젝트", "제목", "명칭", "과제"),
        "예상기간": ("기간", "예상", "개월", "주"),
        "지원자수": ("지원", "제안", "참여"),
        "URL": ("url", "링크", "주소", "http"),
    }},
    "yes24_md": {"rows": 3, "cols": {
        "도서명": ("도서", "제목", "책", "서명"),
        "쪽수": ("쪽", "페이지", "page"),
        "ISBN": ("isbn",),
        "URL": ("url", "링크", "주소", "http"),
    }},
    "saramin_doc": {"rows": 3, "cols": {
        "회사명": ("회사", "기업", "업체"),
        "고용형태": ("고용", "형태", "근무형태"),
        "마감일": ("마감", "접수", "기한"),
        "URL": ("url", "링크", "주소", "http"),
    }},
    "competitor_skill": {"rows": 3, "cols": {
        "프로젝트명": ("프로젝트", "제목", "명칭"),
        # ★ 실제 산출물은 「핵심 **요구 역량**」이라는 열 이름을 썼다 (2026-09-10).
        #   내용은 `Python/Java 기반 AI 시스템`·`Node.js/TypeScript 기반 백엔드`로
        #   정확히 기술 스택인데, 낱말표가 좁아서 **없는 열**로 찍혔다.
        "기술스택": ("기술", "스택", "스킬", "언어", "역량"),
    }},
    # 산문이다. 표로 재지 않는다.
    "resume_skill": {"prose": True},
    # ── 손대지 않은 과제(multiturn_bench.HOLDOUT) — 프롬프트에서 그대로 옮겼다 ──
    "danawa_csv": {"rows": 3, "cols": {
        "상품명": ("상품", "제품", "모델", "이름"),
        "가격": ("가격", "판매가", "최저가", "원"),
        "제조사": ("제조", "브랜드", "메이커"),
        "URL": ("url", "링크", "주소", "http"),
    }},
    "jobkorea_hwpx": {"rows": 3, "cols": {
        "회사명": ("회사", "기업", "업체"),
        "고용형태": ("고용", "형태", "근무형태"),
        "마감일": ("마감", "접수", "기한"),
        "URL": ("url", "링크", "주소", "http"),
    }},
    "aladin_docx": {"rows": 3, "cols": {
        "저자": ("저자", "지은이", "작가"),
        "출판사": ("출판",),
        "정가": ("정가", "가격", "판매가"),
        "URL": ("url", "링크", "주소", "http"),
    }},
    "musinsa_xlsx": {"rows": 3, "cols": {
        "브랜드": ("브랜드", "제조"),
        "상품명": ("상품", "제품", "이름"),
        "가격": ("가격", "판매가", "원"),
        "URL": ("url", "링크", "주소", "http"),
    }},
    # 두 사이트 대조 — 행은 사이트마다 하나다.
    "kyobo_yes24_md": {"rows": 2, "cols": {
        "사이트": ("사이트", "서점", "판매처", "쇼핑몰", "구분"),
        "판매가": ("판매가", "가격", "정가"),
        "쪽수": ("쪽", "페이지", "page"),
        "URL": ("url", "링크", "주소", "http"),
    }},
}


def _cells_from_xlsx(path: pathlib.Path) -> list[list[str]]:
    from openpyxl import load_workbook
    book = load_workbook(path, data_only=True)
    rows: list[list[str]] = []
    for sheet in book.worksheets:
        for row in sheet.iter_rows(values_only=True):
            line = ["" if v is None else str(v).strip() for v in row]
            if any(line):
                rows.append(line)
        if rows:
            break
    return rows


def _cells_from_docx(path: pathlib.Path) -> list[list[str]]:
    import docx
    doc = docx.Document(str(path))
    for table in doc.tables:
        rows = [[c.text.strip() for c in r.cells] for r in table.rows]
        if len(rows) >= 2:
            return rows
    return []


#: 마크다운 표의 **구분선**. `| :--- |` 도 `| :- |` 도 실제로 쓰인다.
#
# 처음에 `-{2,}` 로 잡았다가 대시 하나짜리(`| :- |`)를 통째로 놓쳤다 — 표가 있는데
# 「표 없음 0%」가 나온다. 그렇다고 `-` 하나만 보면 값이 전부 `-` 인 **빈 데이터
# 줄**이 구분선으로 오인된다. 그래서 「글자·숫자가 하나도 없고, 칸마다 대시가
# 있고, 칸이 둘 이상」으로 잡는다.
_MD_RULE_CHARS = re.compile(r"^[\s|:\-]+$")


def _is_md_rule(line: str) -> bool:
    if not line.strip() or not _MD_RULE_CHARS.match(line):
        return False
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return len(cells) >= 2 and all("-" in c for c in cells)


def _cells_from_markdown(text: str) -> list[list[str]]:
    """파이프 표를 꺼낸다. **구분선 위 줄이 머리**다 — 첫 줄이 아니라."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _is_md_rule(line) or i == 0:
            continue
        rows: list[list[str]] = []
        for candidate in lines[i - 1:]:
            if not candidate.strip().startswith("|") and "|" not in candidate:
                break
            if _is_md_rule(candidate):
                continue
            cells = [c.strip() for c in candidate.strip().strip("|").split("|")]
            if any(cells):
                rows.append(cells)
        if len(rows) >= 2:
            return rows
    return []


def _cells_from_csv(text: str) -> list[list[str]]:
    """쉼표 CSV. 칸 안의 쉼표(따옴표로 싼 것)도 제대로 나눈다."""
    import csv as _csv
    import io as _io

    body = text.lstrip("\ufeff")
    rows = [[c.strip() for c in row] for row in _csv.reader(_io.StringIO(body)) if any(c.strip() for c in row)]
    return rows if len(rows) >= 2 and max(len(r) for r in rows) >= 2 else []


def _cells_from_tsv(text: str) -> list[list[str]]:
    """**탭으로 나눈 표도 표다.** 파이프만 보면 못 본다.

    2026-09-10 에 실제로 그렇게 나왔다 — `python_books_info.md` 가 파이프 없이
    탭으로 머리줄과 한 줄을 적었는데, 채점기가 「표 0행」이라고 했다. 내용은
    쪽수·ISBN·URL 이 다 있는 진짜였다(다만 3권 중 1권뿐).

    **띄어쓰기로는 안 나눈다.** 산문 한 줄이 표로 오인되면 채점기가 없는 표를
    보고 점수를 준다 — 못 보는 것보다 나쁘다. 탭은 사람이 산문에 안 쓴다.
    """
    rows = [line.split("	") for line in text.splitlines() if "	" in line]
    rows = [[c.strip() for c in row] for row in rows if len(row) >= 2]
    return rows if len(rows) >= 2 else []


def table_of(path: pathlib.Path) -> list[list[str]]:
    """어떤 형식이든 표를 꺼낸다. 못 꺼내면 빈 목록 — **빈 목록은 「표 없음」이지
    「읽기 실패」가 아니다.** 두 가지를 한 값으로 돌려주면 조용히 고장 난다."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".xlsx":
            return _cells_from_xlsx(path)
        if suffix == ".docx":
            rows = _cells_from_docx(path)
            if rows:
                return rows
        if suffix == ".hwpx":
            # 읽는이는 한글 표를 칸마다 한 줄로 풀어 준다 — 구조째 꺼내는 쪽을 쓴다.
            tables = doc_form.hwpx_tables(path)
            if tables:
                return tables[0]
        # ★ 원문과 **자비스 읽는이** 둘 다 본다 (2026-09-10).
        #
        #   `python-docx` 가 이 워드 파일의 표를 못 봤는데(`tables` 가 비었다),
        #   자비스의 `document_reader` 는 같은 파일에서 표를 파이프로 꺼내 왔다.
        #   전용 라이브러리가 늘 더 잘 읽는다는 보장이 없다 — 실제로 여기서
        #   그 가정 때문에 다 채운 표가 「0행 0%」로 찍혔다.
        texts: list[str] = []
        if suffix in (".md", ".txt", ".csv"):
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        try:
            sys.path.insert(0, str(HERE.parents[1] / "src"))
            from alture_jarvis.document_reader import preview_of_file
            texts.append(preview_of_file(path, chars=40_000) or "")
        except Exception:
            pass
        # ★ 쉼표 CSV 를 못 읽었다 (2026-09-13, 새 과제를 돌리기 전에 발견).
        #   탭만 표로 봤기 때문에 멀쩡한 CSV 가 「표 0행」으로 찍혔을 것이다.
        if suffix == ".csv":
            rows = _cells_from_csv(texts[0] if texts else "")
            if rows:
                return rows
        for raw in texts:
            rows = _cells_from_markdown(raw) or _cells_from_tsv(raw)
            if rows:
                return rows
        return []
    except Exception:
        return []


#: 마크다운 절 머리. 표 대신 절로 항목을 적는 판을 알아보려고 쓴다.
#: 과제마다 **어떤 파일로** 시켰고 주소를 요구했나. multiturn_bench.TASKS 와 같다.
FORM: dict[str, dict] = {
    "wishket_xlsx": {"ext": (".xlsx",), "url": True},
    "yes24_md": {"ext": (".md",), "url": True},
    "saramin_doc": {"ext": (".docx", ".md", ".xlsx", ".hwpx"), "url": True},
    "resume_skill": {"ext": (".docx", ".md"), "url": False},
    "competitor_skill": {"ext": (".md", ".xlsx", ".docx"), "url": False},
    "danawa_csv": {"ext": (".csv",), "url": True},
    "jobkorea_hwpx": {"ext": (".hwpx",), "url": True},
    "aladin_docx": {"ext": (".docx",), "url": True},
    "musinsa_xlsx": {"ext": (".xlsx",), "url": True},
    "kyobo_yes24_md": {"ext": (".md",), "url": True},
}


def trace_of(job_id: str) -> dict | None:
    """그 판의 장부. 값이 **읽은 원문에 있는지** 대조하는 데 쓴다."""
    if not job_id:
        return None
    try:
        row = _snapshot().execute(
            "SELECT result_json FROM jobs WHERE id LIKE ?", (job_id + "%",)).fetchone()
        return (json.loads(row[0] or "{}").get("agent_trace") or None) if row else None
    except Exception:
        return None


_SECTION = re.compile(r"^#{2,4}\s+\S", re.M)


def _text_of(path: pathlib.Path) -> str:
    """글자만 꺼낸다. 못 읽으면 빈 문자열."""
    try:
        if path.suffix.lower() in (".md", ".txt", ".csv"):
            return path.read_text(encoding="utf-8", errors="replace")
        sys.path.insert(0, str(HERE.parents[1] / "src"))
        from alture_jarvis.document_reader import preview_of_file
        return preview_of_file(path, chars=40_000) or ""
    except Exception:
        return ""

def grade(task: str, path: pathlib.Path) -> dict:
    spec = WANT.get(task) or {}
    if spec.get("prose"):
        try:
            sys.path.insert(0, str(HERE.parents[1] / "src"))
            from alture_jarvis.document_reader import preview_of_file
            body = preview_of_file(path, chars=40_000) or ""
        except Exception:
            body = ""
        return {"kind": "산문", "chars": len(body)}

    want_rows = int(spec.get("rows") or 0)
    want_cols: dict = spec.get("cols") or {}
    table = table_of(path)
    header = [c.lower() for c in (table[0] if table else [])]
    body = table[1:] if len(table) > 1 else []

    # 어느 열이 어느 항목인가. 못 찾으면 -1 — 그 항목의 칸은 **전부 안 채운 것**이다.
    where: dict[str, int] = {}
    for label, words in want_cols.items():
        where[label] = next(
            (i for i, head in enumerate(header)
             if any(w in head for w in words)), -1)

    filled = 0
    total = want_rows * len(want_cols)          # ★ 분모는 **시킨 것**이다
    for r in range(want_rows):
        row = body[r] if r < len(body) else []
        for label in want_cols:
            i = where[label]
            value = row[i] if 0 <= i < len(row) else ""
            if value and not _BLANK.match(value):
                filled += 1
    # ★ **빈 표와 표 없음은 다르다** (2026-09-11).
    #
    #   yes24 판이 이렇게 나왔다 — 표 머리줄만 있고 값은 절(`##`)에 들어갔다:
    #
    #       | 제목 | 저자 | 쪽수 | ISBN13 | 상세페이지 URL |
    #       | --- | --- | --- | --- | --- |
    #       ## 1. Do it! 첫 파이썬
    #       엘리스 코딩 | 이지스퍼블리싱 | 268쪽 | 9791163031567 | https://…
    #
    #   3권 전부 쪽수·ISBN·URL 이 다 있다. 그런데 표가 비어서 0% 로 찍혔고,
    #   **그 판의 프롬프트는 표를 요구하지도 않았다**(「마크다운 문서로 만들어줘」).
    #   채점기가 과제보다 좁았다 — 오늘 세 번째 같은 병이다.
    #
    #   점수는 그대로 둔다(표로 안 나온 것은 사실이다). 대신 **왜 0% 인지를
    #   같이 적는다** — 「값이 없다」와 「표 밖에 있다」를 구별 못 하면 다음 사람이
    #   내용까지 없는 줄 안다.
    note = ""
    if want_rows and not body:
        sections = len(_SECTION.findall(_text_of(path)))
        if sections >= want_rows:
            note = f"표는 비었지만 본문 절 {sections}개에 값이 있다 — 형식 문제다"
    return {
        "kind": "표",
        **({"note": note} if note else {}),
        "rows": f"{min(len(body), want_rows)}/{want_rows}",
        "cols": f"{sum(1 for i in where.values() if i >= 0)}/{len(want_cols)}",
        "missing_cols": [k for k, i in where.items() if i < 0],
        "filled": f"{filled}/{total}",
        "filled_pct": round(100 * filled / total) if total else 0,
    }


_SNAPSHOT: "sqlite3.Connection | None" = None


def _snapshot() -> "sqlite3.Connection":
    """살아 있는 DB 를 **한 번만** 뜬다.

    처음엔 부를 때마다 복사했다가 한 판을 잃었다 — 자비스가 쓰는 중인 파일을
    거듭 복사하니 어떤 회차는 앞뒤가 안 맞는 사본이 나왔고, 실제로 만든 37KB
    문서가 「파일 없음」으로 찍혔다. **재는 도구가 대상보다 부산해서는 안 된다.**
    """
    global _SNAPSHOT
    if _SNAPSHOT is not None:
        return _SNAPSHOT
    src = pathlib.Path("C:/RoboMetaFit/tools/alture-jarvis/data")
    tmp = pathlib.Path("C:/Users/user/AppData/Local/Temp/claude/cg.sqlite")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):   # ★ WAL 없이 뜨면 방금 쓴 판이 안 보인다
        one = src / ("jarvis.db" + suffix)
        if one.exists():
            shutil.copy(one, str(tmp) + suffix)
    _SNAPSHOT = sqlite3.connect(tmp)
    return _SNAPSHOT


def paths_made(job_id: str) -> list[pathlib.Path]:
    """이 판이 **실제로 어디에 무엇을 썼나** — 걸음의 증거에서 직접 읽는다.

    ★ 2026-09-10. 앞 채점기는 `~/Documents/JARVIS` 만 훑었는데,
    `artifact_from_observations` 는 **판 작업방**(`outputs/workspace/<job>/`)에
    쓴다. 그래서 37KB 짜리 워드 문서가 「파일 없음」으로 찍혔고, 그 판의 답이
    파일 이름을 대는 것을 보고 하마터면 **「안 한 일을 했다고 답했다」고 뒤집어
    씌울 뻔했다.** 실제로는 도구가 제대로 만들었고 우리 눈금이 딴 데를 봤다.

    폴더를 훑지 않고 증거를 읽는 이유: 도구가 늘어나면 쓰는 자리도 늘어난다.
    훑을 폴더 목록은 늘 낡는다.
    """
    if not job_id:
        return []
    try:
        conn = _snapshot()
        row = conn.execute(
            "SELECT result_json FROM jobs WHERE id LIKE ?", (job_id + "%",)).fetchone()
        steps = (json.loads(row[0] or "{}").get("agent_trace") or {}).get("steps") or []
    except Exception:
        return []
    out: list[pathlib.Path] = []
    for step in steps:
        raw = str(((step.get("evidence") or {}).get("output_path")) or "").strip()
        if raw and step.get("ok"):
            one = pathlib.Path(raw)
            if one.exists() and one not in out:
                out.append(one)
    return out


def main() -> None:
    src = HERE / "results" / (sys.argv[1] if len(sys.argv) > 1 else "multiturn.json")
    rows = json.loads(src.read_text(encoding="utf-8"))
    out = []
    for row in rows:
        task = str(row.get("task") or "")
        # ★ 벤치가 판 직후에 떠 둔 사본이 먼저다 — 같은 이름은 다음 라운드가 덮는다.
        made = [pathlib.Path(k) for k in (row.get("kept") or []) if pathlib.Path(k).exists()]
        if not made:
            made = paths_made(str(row.get("job") or ""))
            made += [DOCS / n for n in (row.get("files") or []) if (DOCS / n).exists()]
        names = [str(p) for p in made]
        if not names:
            out.append({**{k: row.get(k) for k in ("round", "task")},
                        "verdict": "파일 없음", "filled_pct": 0})
            print(f"[r{row.get('round')}] {task:17} 파일 없음 → 채움 0%")
            continue
        # 여러 개면 시킨 형식에 맞는 것을 고른다. 없으면 첫 번째.
        best = max(made, key=lambda p: (p.suffix.lower() in (".xlsx", ".md", ".docx"),
                                        p.stat().st_size))
        card = grade(task, best)
        spec = FORM.get(task) or {}
        card.update(doc_form.check(
            best,
            want_ext=spec.get("ext", (best.suffix.lower(),)),
            table_task=not (WANT.get(task) or {}).get("prose"),
            url_wanted=bool(spec.get("url")),
            trace=trace_of(str(row.get("job") or "")),
        ))
        out.append({**{k: row.get(k) for k in ("round", "task")},
                    "file": best.name, **card})
        best = best.name
        form_line = (f"{chr(10)}       양식·근거 {card['form']}"
                     + "".join(f"{chr(10)}         ✗ {f}" for f in card.get("failed") or []))
        if card["kind"] == "산문":
            print(f"[r{row.get('round')}] {task:17} 산문 {card['chars']}자  ({best})" + form_line)
        else:
            print(f"[r{row.get('round')}] {task:17} 행 {card['rows']} · 열 {card['cols']}"
                  f" · ★채움 {card['filled']} ({card['filled_pct']}%)"
                  + (f" · 없는 열 {card['missing_cols']}" if card["missing_cols"] else "")
                  + (f"{chr(10)}       ★ {card['note']}" if card.get("note") else "")
                  + form_line)
    (HERE / "results" / ("content_grade_holdout.json" if "holdout" in src.name else "content_grade.json")).write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    table = [r for r in out if r.get("kind") == "표" or r.get("verdict")]
    if table:
        avg = round(sum(r.get("filled_pct", 0) for r in table) / len(table))
        print(f"\n표 산출물 {len(table)}판 · 평균 채움 {avg}%")
    made_rows = [r for r in out if r.get("form_ok") is not None]
    if made_rows:
        clean = sum(1 for r in made_rows if r.get("form_ok"))
        print(f"만든 파일 {len(made_rows)}개 · 양식·근거 전부 통과 {clean}개")
        tally: dict[str, int] = {}
        for r in made_rows:
            for f in r.get("failed") or []:
                key = f.split(" — ")[0]
                tally[key] = tally.get(key, 0) + 1
        if tally:
            print("  걸린 항목: " + " · ".join(
                f"{k} {v}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1])))
    print("results/content_grade.json")


if __name__ == "__main__":
    main()
