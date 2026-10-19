"""바깥 AI 에게 나가는 답을 다듬는다 — 「돌려받아야 할 것」 확인 · 정해진 규칙의 정제 · 한 줄 영수증 (2026-10-15 · 전략안 §55-32).

대표의 설계: 「Claude 가 MCP 로 시킬 때 이 정보는 꼭 들어가야 한다를 잡아 두고, 손자리가 검증해서 안 보내면 과제가 실패할 수
있다 · 안 나가도 되는 것은 정제해서 보낸다 — 데이터의 주권은 당신.」

- **무엇이 민감한가를 작은 모델에게 묻지 않는다.** 모양으로 가린다(정규식). 주민등록번호 · 카드 번호 · 비밀 키는 늘 가리고,
  전화번호 · 메일 주소는 맡긴 쪽이 `needs` 로 밝혔을 때만 내보낸다 — 밝힌 조건이라 「이것 없이는 못 끝낸다」가 참이다.
- 「돌려받아야 할 것」은 답의 표 머리 또는 「이름: 값」 줄로 가린다 — 이 판이 만든 파일(엑셀 · csv · 워드 표)의 머리글도 본다.
  낱말 뜻을 짐작하지 않는다. 그래서 **이름이 붙은 칸을 못 찾으면 「없다」가 아니라 「확인 못 함」(met=None)** 이다 (2026-10-19).
- 이 PC 의 파일은 건드리지 않는다 — 나가는 글(답)만 다듬는다. 파일은 이 PC 에 남고 경로만 나간다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .url_privacy import safe_url, scrub_urls, scrub_urls_deep

__all__ = ["clean_needs", "check_needs", "refine", "receipt", "outbound_record", "outbound_job_view", "showcase_for_outside"]

MAX_NEEDS = 12

# 순서가 뜻이 있다: 긴 모양(키 · 카드)을 먼저 가려야 짧은 모양(전화)이 그 속을 물지 않는다.
_SECRET_KEY = re.compile(
    r"(?<![A-Za-z0-9])(?:sk-ant-[A-Za-z0-9_\-]{20,}|sk-(?:proj-)?[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{30,}"
    r"|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{35}|xox[baprs]-[A-Za-z0-9\-]{10,})"
)
_RRN = re.compile(r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])-?[1-4]\d{6}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)")
_PHONE = re.compile(r"(?<![\d-])(?:01[016789]|0[2-6]\d?)[-. ]?\d{3,4}[-. ]?\d{4}(?![\d-])")
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")

#: needs 의 이름에 이 낱말이 있으면 그 종류는 나가도 된다(맡긴 쪽이 필요하다고 밝혔다).
_ALLOWED_BY = {
    "전화번호": ("전화", "연락처", "휴대폰", "핸드폰", "phone", "tel", "contact"),
    "메일 주소": ("메일", "연락처", "email", "e-mail", "mail", "contact"),
}
_BLANK = {"", "-", "–", "—", "없음", "n/a", "na", "?", "x"}


def _luhn(digits: str) -> bool:
    total, flip = 0, False
    for char in reversed(digits):
        value = int(char)
        if flip:
            value *= 2
            if value > 9:
                value -= 9
        total += value
        flip = not flip
    return total % 10 == 0


def clean_needs(raw: Any) -> list[str]:
    """맡긴 쪽이 준 needs 를 이름 목록으로 — 빈 것 · 겹친 것을 빼고 앞에서 열두 개까지."""
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        label = " ".join(str(item or "").split())[:60]
        if label and label not in out:
            out.append(label)
    return out[:MAX_NEEDS]


def refine(text: str, *, needs: list[str] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """정해진 모양을 「[가림: 종류]」로 바꾸고 종류별 개수를 돌려준다(가린 것이 없으면 빈 목록)."""
    asked = " ".join(needs or []).casefold()
    allowed = {kind for kind, words in _ALLOWED_BY.items() if any(word in asked for word in words)}
    counts: dict[str, int] = {}

    def _mask(kind: str) -> Any:
        def _sub(match: re.Match[str]) -> str:
            if kind == "카드 번호" and not _luhn(re.sub(r"\D", "", match.group(0))):
                return match.group(0)
            counts[kind] = counts.get(kind, 0) + 1
            return f"[가림: {kind}]"
        return _sub

    out = str(text or "")
    for kind, pattern in (("비밀 키", _SECRET_KEY), ("주민등록번호", _RRN), ("카드 번호", _CARD),
                          ("전화번호", _PHONE), ("메일 주소", _EMAIL)):
        if kind in allowed:
            continue
        out = pattern.sub(_mask(kind), out)
    # 답에 옮겨 적은 로그인 화면 주소 · 한 번 쓰는 값(2026-10-19 잡 51f35b07) — 가리지 않고 `scheme://host/path` 로 줄인다.
    out, shortened = scrub_urls(out)
    if shortened:
        counts["로그인 주소"] = shortened
    return out, [{"kind": kind, "count": count} for kind, count in counts.items()]


def _site_name_pattern() -> tuple[re.Pattern[str] | None, dict[str, str]]:
    """사이트의 한글 · 영문 이름 → 주소. 표는 새로 만들지 않고 계획이 쓰는 두 표(`site_atlas.SEED` · `english.SITE_NAMES`)를 그대로 쓴다."""
    from . import english as _en
    from .site_atlas import SEED

    hosts: dict[str, str] = {}
    for name, host in [*SEED.items(), *_en.SITE_NAMES.items()]:
        hosts.setdefault(name.casefold(), host)
    if not hosts:
        return None, {}
    parts = []
    for name in sorted(hosts, key=len, reverse=True):
        # 영문 이름은 낱말로만(「gb」가 「16gb」 속에서 걸리지 않게), 한글 이름은 다른 낱말의 꼬리가 아닐 때만(「크레딧」 속 「레딧」).
        parts.append(rf"(?<![0-9a-z]){re.escape(name)}(?![0-9a-z])" if name.isascii() else rf"(?<![가-힣]){re.escape(name)}")
    return re.compile("|".join(parts)), hosts


_SITE_NAME, _SITE_HOST = _site_name_pattern()


def _canon_sites(text: str) -> str:
    """사이트 이름을 그 주소로 바꾼 소문자 글 — 「깃허브 계정」과 「GitHub 계정」이 같은 말이 된다.

    ★ 2026-10-19 판 51f35b07: 항목 「로그인된 깃허브 계정 이름」에 답은 「현재 로그인된 GitHub 계정: `(계정 이름)`」였다.
      맡긴 쪽(Claude)은 한국어로 묻고 손자리는 사이트의 영문 표기로 답하는 일이 잦다 — 같은 곳의 두 이름을 한 말로 본다.
    """
    folded = str(text or "").casefold()
    if _SITE_NAME is None:
        return folded
    return _SITE_NAME.sub(lambda found: _SITE_HOST.get(found.group(0), found.group(0)), folded)


def _norm(text: str) -> str:
    return re.sub(r"[\s*_`:：]+", "", _canon_sites(text))


#: 낱말 끝에 붙은 조사 — 떼고 견준다(「표현과」 → 「표현」 · 「계정이」 → 「계정」). 세 글자 이상인 낱말에서만 뗀다.
_PARTICLE = re.compile(r"(?:에서|으로|이랑|부터|까지|과|와|은|는|이|가|을|를|의|에|로|도|만|랑)$")


def _words(text: str) -> list[str]:
    out = []
    for token in re.findall(r"[0-9a-z가-힣][0-9a-z가-힣.\-]*", _canon_sites(text)):
        token = token.rstrip(".-")
        stripped = _PARTICLE.sub("", token)
        out.append(stripped if len(stripped) >= 2 and re.search(r"[가-힣]$", token) else token)
    return [word for word in out if word]


def _covers(label: str, key: str) -> bool:
    """이름 붙은 자리(「이름: 값」의 이름 · 제목)가 항목 이름의 낱말을 **모두** 담는가 — 순서 · 조사 · 띄어쓰기와 무관하게.

    마지막 낱말(우리말 명사구의 머리 — 「… 계정 **이름**」 · 「… 결과 **수**」) 하나는 빠져도 된다. 다만 낱말이 셋 이상이고
    앞 낱말은 다 있어야 한다 — 「PR 주소」처럼 둘뿐인 이름은 둘 다 있어야 한다.
    ★ 2026-10-19: 항목 이름과 답의 이름이 글자 그대로 같지 않아도(「로그인된 깃허브 계정 이름」 ↔ 「현재 로그인된 GitHub 계정」)
      같은 자리를 가리키면 채운 것으로 본다. 거꾸로(답의 짧은 이름이 긴 항목 안에 든 것)는 안 본다 — 「정리」 하나가 여러 항목을 채운다.
    """
    want, have = _words(label), _words(key)
    if not want or not have:
        return False

    def _hit(word: str) -> bool:
        return any(got == word or (len(word) >= 2 and len(got) >= 2 and (got.startswith(word) or word.startswith(got)))
                   for got in have)

    missing = [word for word in want if not _hit(word)]
    return not missing or (len(want) >= 3 and missing == [want[-1]])


_SENTENCE_END = re.compile(r"(?:니다|어요|아요|해요|했다|였다|었다|았다)\W*$")


def _a_slot_name(key: str, label: str) -> bool:
    """「이름: 값」의 이름이 **이름답게** 생겼나 — 문장(「메모장 창을 새로 열었습니다 (창 ID」)의 쌍점은 이름 자리가 아니다.

    괄호가 안 닫힌 채 끝나면(괄호 속 쌍점) · 문장 끝맺음으로 끝나면 · 항목 이름보다 낱말이 셋 넘게 많으면 이름이 아니다.
    ★ 2026-10-19 운영 판 대조에서 d4c7eb06 「메모장 창 제목」이 「1. 메모장 창을 새로 열었습니다 (창 ID: 48827506)」로 채워진 것으로
      헛걸려 넣었다(창 제목이 아니라 창 번호다).
    """
    text = str(key or "").strip()
    if text.count("(") != text.count(")") or text.count("（") != text.count("）"):
        return False
    if _SENTENCE_END.search(text):
        return False
    return len(_words(text)) <= len(_words(label)) + 2


#: 「이름: 값」 줄 — 굵게 감싼 꼴(「**현재 로그인된 GitHub 계정: `(계정 이름)`**」)과 번호 · 글머리표가 붙은 꼴까지.
_KEY_VALUE = re.compile(r"(?m)^\s*(?:[-*•]\s+|\d+[.)]\s*)?\**\s*([^:：\n|*]{1,40}?)\s*\**\s*[:：]\s*(.+?)\s*$")


def _tables(answer: str) -> list[tuple[list[str], list[list[str]]]]:
    """답 속 마크다운 표들 → (머리, 줄들)."""
    tables: list[tuple[list[str], list[list[str]]]] = []
    head: list[str] | None = None
    rows: list[list[str]] = []
    for line in str(answer or "").splitlines() + [""]:
        if line.count("|") >= 2:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", cell or "--") for cell in cells):
                continue
            if head is None:
                head = cells
            else:
                rows.append(cells)
            continue
        if head is not None:
            tables.append((head, rows))
        head, rows = None, []
    return tables


_HEADING = re.compile(r"^\s*(?:#{1,6}\s+(.+?)\s*#*|\*\*(.+?)\*\*\s*[:：]?)\s*$")


def _under_heading(want: str, answer: str, label: str = "") -> bool | None:
    """제목(「### 좋게 보는 점」 · 굵은 글씨만 있는 줄)이 그 이름을 담고, 다음 제목 전까지 내용이 있다.

    True = 그 이름의 제목 아래 내용이 있다 · False = 그 이름의 제목은 있는데 아래가 비었다 · None = 그 이름의 제목이 없다.

    ★ 2026-10-15 StepFun 조사 판: 답에 「좋게 보는 점」 · 「나쁘게 보는 점」을 제목 아래 목록으로 다 썼는데 1/6 으로 셌다 —
      표 머리와 「이름: 값」 줄만 봤다. 제목이 이름을 **담는** 쪽만 본다(「분위기」 ⊂ 「④ 댓글 분위기」). 거꾸로(짧은 제목이
      긴 이름 안에 든 것)는 안 본다 — 「정리」 같은 제목 하나가 여러 항목을 채운 것으로 셀 수 있다.
    """
    lines = str(answer or "").splitlines()
    seen_empty = False
    for index, line in enumerate(lines):
        found = _HEADING.match(line)
        if not found:
            continue
        title = found.group(1) or found.group(2) or ""
        strict = want in _norm(title)
        # ★ 2026-10-19: 낱말이 다 들어 있으면(순서 · 조사 · 사이트 한글/영문 표기 무관 — `_covers`) 그 제목도 그 자리다. 다만 이렇게
        #   느슨하게 맞춘 제목은 **채움의 증거로만** 쓴다 — 아래가 비었다고 「없다」로 단정하지 않는다(모르면 확인 못 함).
        #   「이름: 값」꼴의 굵은 줄은 제목이 아니라 값 줄이다 — `_KEY_VALUE` 가 본다.
        loose = not strict and bool(label) and not re.search(r"[:：]\s*\S", title) and _covers(label, title)
        if not strict and not loose:
            continue
        # ★ 2026-10-19: 아래 제목(「## 네 커뮤니티」 밑의 「### r/LocalLLM」)은 그 절의 내용이다 — 같거나 높은 제목에서만 끊는다.
        #   전에는 아무 「#」 제목에서나 끊어서, 하위 절로 나눠 쓴 답을 「제목 아래가 비었다」로 봤다(728ecaa5 「커뮤니티」).
        level = len(line.lstrip()) - len(line.lstrip().lstrip("#")) if line.lstrip().startswith("#") else 0
        for after in lines[index + 1:]:
            stripped = after.lstrip()
            if _HEADING.match(after) and stripped.startswith("#") and \
                    (not level or len(stripped) - len(stripped.lstrip("#")) <= level):
                break
            body = after.strip().lstrip("-*•>|").strip().strip("*").strip()
            if body and not re.fullmatch(r"[-:|\s]+", body) and body.casefold() not in _BLANK:
                return True
        seen_empty = seen_empty or strict
    return False if seen_empty else None


#: 만든 파일에서 머리글과 값을 볼 때 읽는 줄 수 — 「값이 하나라도 있는가」만 보면 되니 앞쪽이면 충분하다.
_FILE_ROWS = 200


def _file_tables(path: str) -> list[tuple[list[str], list[list[str]]]]:
    """만든 파일(.xlsx 시트 · .csv/.tsv · .docx 표 · .md/.txt 의 마크다운 표) → (머리, 줄들). 못 열면 빈 목록.

    머리는 **값이 든 첫 줄**이다 — 시트 위에 빈 줄을 두고 쓴 파일도 있다.
    """
    file = Path(str(path or ""))
    suffix = file.suffix.lower()
    try:
        if not file.is_file():
            return []
        if suffix == ".xlsx":
            from openpyxl import load_workbook

            book = load_workbook(file, read_only=True, data_only=True)
            try:
                found = []
                for sheet in book.worksheets:
                    lines = []
                    for row in sheet.iter_rows(values_only=True):
                        cells = ["" if cell is None else str(cell).strip() for cell in row]
                        if any(cells):
                            lines.append(cells)
                        if len(lines) > _FILE_ROWS:
                            break
                    if lines:
                        found.append((lines[0], lines[1:]))
                return found
            finally:
                book.close()
        if suffix in {".csv", ".tsv"}:
            import csv

            with file.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
                lines = [[cell.strip() for cell in row] for _, row in zip(range(_FILE_ROWS + 1),
                         csv.reader(stream, delimiter="\t" if suffix == ".tsv" else ","))]
            lines = [row for row in lines if any(row)]
            return [(lines[0], lines[1:])] if lines else []
        if suffix == ".docx":
            from docx import Document

            found = []
            for table in Document(str(file)).tables:
                lines = [[cell.text.strip() for cell in row.cells] for row in table.rows[: _FILE_ROWS + 1]]
                lines = [row for row in lines if any(row)]
                if lines:
                    found.append((lines[0], lines[1:]))
            return found
        if suffix in {".md", ".txt"}:
            return _tables(file.read_text(encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 — 못 여는 파일은 아무 칸도 채우지 않는다(없는 칸을 세지 않는다)
        return []
    return []


def _same_column(want: str, name: str) -> bool:
    """머리 이름이 항목 이름과 같은 칸인가 — 서로 담거나, 괄호 풀이(「점수(업보트)」의 「(업보트)」)를 떼고 담는다."""
    have = _norm(name)
    if not have:
        return False
    if want in have or have in want:
        return True
    core = _norm(re.sub(r"[(\[（【][^)\]）】]*[)\]）】]", "", str(name or "")))
    return bool(core) and (want in core or core in want)


def _filled(cell: str) -> bool:
    return str(cell or "").strip().strip("*").strip().casefold() not in _BLANK


def _nothing_came_back(answer: str, files: list[str] | tuple[str, ...]) -> bool:
    """답 글이 비었고 이 판이 만든 파일도 하나도 없다 — 그러면 어떤 항목도 돌아오지 않은 것이 확실하다."""
    if str(answer or "").strip():
        return False
    for path in files or ():
        try:
            if Path(str(path or "")).is_file():
                return False
        except OSError:
            return False
    return True


def check_needs(needs: list[str], answer: str, *, files: list[str] | tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """항목마다 `met` 을 셋 중 하나로 — **이름이 붙은 자리**만 증거로 친다.

    - True  : 그 이름이 붙은 자리에 값이 있다 — 표 머리에 그 이름이 있고 그 칸에 값이 하나라도 있다 · 표의 첫 칸이 그 이름이고
              옆 칸에 값이 있다 · 그 이름을 담은 제목 아래 내용이 있다 · 「이름: 값」 줄이 있다.
    - False : 그 이름이 붙은 자리는 있는데 **비었다**(칸이 다 빈칸 · 「이름: 없음」 · 제목 아래가 빔), 또는 답 글도 만든 파일도
              아예 없다. 「없다」는 이렇게 **비어 있는 것을 본 때만** 말한다.
    - None  : 그 이름이 붙은 자리를 못 찾았다 = **확인 못 함.** 비었다는 뜻이 아니다.

    ★ 2026-10-16 r/LLMDevs 판(job 759ba894): 엑셀에 머리글과 25줄이 다 있었는데 「필요한 것 0/4」였다 — 답은 파일 경로만
      적었고 검사는 답 글만 봤다. 표를 파일로 만들라고 시킨 일은 **파일의 표가 답**이다. `files`(이 판이 만든 파일)의
      표도 같은 규칙(머리 이름 + 그 칸에 값)으로 본다.
    ★ 2026-10-19 Ollama FAQ 세 판(022c62a1 · 029fae29 · f74274ef): 답에 명령 · 기본값 · 주소가 다 있었는데 0/4 · 0/5 · 0/3 이었다.
      항목 이름은 맡긴 쪽이 자유롭게 지은 말이고(「how to set num_ctx」 · 「읽은 FAQ 페이지 URL」), 답은 제 말로 적는다
      (「Setting it with the `num_ctx` parameter」 · 「읽은 페이지 주소」). 이름 낱말 겹침으로 뜻을 맞추는 것은 원리상 깨진다 —
      낱말표를 늘려도 다음 이름에서 또 깨진다. 그래서 못 찾은 것을 「없다」로 단정하던 것을 「확인 못 함」으로 바꿨다.
      바깥 AI 는 거짓 「0/4」를 보고 「손자리 체크리스트가 0/4 라 믿기 어렵다」고 사용자에게 말했다.
    """
    tables = _tables(answer)
    for path in files or ():
        tables.extend(_file_tables(path))
    empty_return = _nothing_came_back(answer, files)
    checked: list[dict[str, Any]] = []
    for label in needs:
        want = _norm(label)
        met = False
        saw_empty = False
        for head, rows in tables:
            for index, name in enumerate(head):
                if not _same_column(want, name):
                    continue
                if any(len(row) > index and _filled(row[index]) for row in rows):
                    met = True
                    break
                saw_empty = True
            if met:
                break
        if not met:
            # ★ 표의 **첫 칸**이 항목 이름인 표(「| 라이선스 | MIT |」) — 머리가 아니라 줄이 이름을 든다 (2026-10-15 GLM 조사 판).
            #   줄이 없는 표(「| 가격 | 129,000원 |」 한 줄)는 머리 줄 자체가 이름 · 값 한 쌍이다 — 머리도 줄로 본다.
            for head, rows in tables:
                for row in (rows or [head]):
                    have = _norm(row[0]) if row else ""
                    # 줄 이름이 항목 이름을 **통째로** 담을 때만 — 거꾸로 보면 「설립」 한 칸이 「회사 국적과 설립」을 채운 것이 된다.
                    if not want or want not in have:
                        continue
                    if any(_filled(cell) for cell in row[1:]):
                        met = True
                        break
                    saw_empty = True
                if met:
                    break
        if not met:
            under = _under_heading(want, answer, label)
            met = under is True
            saw_empty = saw_empty or under is False
        if not met:
            words = r"\s*".join(re.escape(part) for part in label.split())
            for line in re.finditer(rf"(?im)^\s*(?:[-*•]\s*)?\**{words}\**\s*[:：]\s*\**\s*(.*)$", str(answer or "")):
                if _filled(line.group(1)):
                    met = True
                    break
                saw_empty = True
        if not met:
            # ★ 「이름: 값」 줄의 이름이 항목 이름과 글자 그대로 같지 않아도 낱말이 다 있으면 그 자리다(`_covers`, 2026-10-19 판 51f35b07
            #   「현재 로그인된 GitHub 계정: `(계정 이름)`」 ↔ 「로그인된 깃허브 계정 이름」). 채움의 증거로만 쓴다 — 빈 값이어도 「없다」로 안 친다.
            for line in _KEY_VALUE.finditer(str(answer or "")):
                key, value = line.group(1), line.group(2).strip().strip("*`").strip()
                if value.startswith("//") or not _a_slot_name(key, label) or not _covers(label, key):
                    continue
                if _filled(value):
                    met = True
                    break
        checked.append({"label": label, "met": True if met else (False if (saw_empty or empty_return) else None)})
    return checked


def receipt(needs: list[dict[str, Any]] | None, refined: list[dict[str, Any]], *, host: str = "") -> dict[str, Any]:
    """화면과 바깥 AI 가 같이 보는 한 줄 영수증의 재료.

    「이 PC 에 남긴 원문」 숫자는 싣지 않는다 — 지금 세는 값은 하한이고, 두 손 견주기로 역검증한 뒤에만 띄운다(§55-32).

    ★ 2026-10-19: 확인 못 한 항목(met=None)이 하나라도 있으면 「m/n」 분수를 쓰지 않는다 — 「0/3」은 읽는 쪽에 「셋 다 없다」로
      읽힌다. 「필요한 것 3개 · 확인 못 함 3」처럼 셋(채움 · 비어 있음 · 확인 못 함)을 따로 센다.
    """
    items = [item for item in needs or [] if isinstance(item, dict)]
    total = len(needs or [])
    met = sum(1 for item in items if item.get("met") is True)
    missing = sum(1 for item in items if item.get("met") is False)
    unknown = total - met - missing
    hidden = sum(int(item.get("count") or 0) for item in refined)
    parts = [f"{host.strip() or '바깥 AI'} 에게 보냄"]
    if total and not unknown:
        parts.append(f"필요한 것 {met}/{total}")
    elif total:
        parts.append(f"필요한 것 {total}개")
        if met:
            parts.append(f"채움 {met}")
        if missing:
            parts.append(f"비어 있음 {missing}")
        parts.append(f"확인 못 함 {unknown}")
    parts.append(f"정제 {hidden}")
    return {"needs_total": total, "needs_met": met, "needs_missing": missing, "needs_unknown": unknown,
            "refined": hidden, "line": " · ".join(parts)}


def outbound_record(answer: str, payload: dict[str, Any] | None, *, files: list[str] | tuple[str, ...] = ()) -> dict[str, Any] | None:
    """바깥 AI 가 맡긴 판의 답 기록에 붙일 영수증 — 화면이 「손자리의 답」 아래 한 줄로 그린다.

    상태 조회(`delegation.summarize_job`)와 **같은 함수**로 만든다 — 화면과 바깥 AI 가 받은 것이 갈리지 않게.
    문장은 화면이 번역 사전으로 만든다(영어 화면) — 여기서는 숫자와 항목만 싣는다. 바깥 AI 가 맡긴 판이 아니면 None.
    """
    payload = payload if isinstance(payload, dict) else {}
    if str(payload.get("origin") or "") != "mcp":
        return None
    needs = clean_needs(payload.get("needs"))
    cleaned, refined = refine(answer, needs=needs)
    checked = check_needs(needs, cleaned, files=files) if needs else []
    made = receipt(checked, refined, host=str(payload.get("caller") or ""))
    return {"host": str(payload.get("caller") or "")[:80], "needs": checked, "refined": refined,
            "needs_total": made["needs_total"], "needs_met": made["needs_met"], "needs_missing": made["needs_missing"],
            "needs_unknown": made["needs_unknown"], "refined_count": made["refined"]}


def outbound_job_view(job: dict[str, Any]) -> dict[str, Any]:
    """바깥에 나가는 일 사본 — 바깥 AI 가 맡긴 일(origin=mcp)이면 답을 정제한 판으로 바꿔 돌려준다(원본은 건드리지 않는다).

    ★ 2026-10-15: 정제가 MCP 연결 프로세스 안에서만 일어나서, 며칠 사는 옛 연결 프로세스로는 원문이 나갔다. 백엔드의 일 조회 문이
      토큰 없이 읽힐 때 이 사본을 내보낸다 — 연결 프로세스의 판과 상관없이 같은 규칙이 걸린다.
    """
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    result = job.get("result") if isinstance(job.get("result"), dict) else None
    if str(payload.get("origin") or "") != "mcp" or not result or not isinstance(result.get("answer"), str):
        return job
    needs = clean_needs(payload.get("needs"))
    answer, refined = refine(result["answer"], needs=needs)
    # ★ 2026-10-19 잡 51f35b07: 답 말고도 걸음 기록(`agent_trace`) · 근거(`grounding`) 의 주소 칸에 구글 계정 고르기 화면의
    #   `code_challenge` · `nonce` · `state` 가 그대로 있었다. 이 사본은 바깥으로 나가는 것이니 **글이 든 칸을 전부** 훑어
    #   로그인 화면 · 한 번 쓰는 값이 붙은 주소를 줄인다(`url_privacy`). 원본(이 PC 의 기록)은 건드리지 않는다.
    rest, _ = scrub_urls_deep({key: value for key, value in result.items() if key != "answer"})
    shaped = {**rest, "answer": answer, "outbound": {"refined": refined, "needs": needs}}
    if isinstance(result.get("showcase"), list):
        shaped["showcase"] = showcase_for_outside(rest.get("showcase"), needs)
    return {**job, "result": shaped}


def showcase_for_outside(items: Any, needs: list[str] | None = None) -> list[dict[str, Any]]:
    """밖으로 나가는 대표사진 — 글에서 가렸을 값(전화번호 · 메일 주소)이 그 페이지에 있었으면 그 사진은 뺀다 (2026-10-18).

    글은 `refine` 이 가리지만 **그림은 못 가린다.** 그래서 needs 로 밝힌 종류가 아니면 사진째 뺀다 — 글과 같은 선이다.
    주민번호 · 카드 · 비밀 키가 있던 페이지는 고르는 단계(`showcase.pick_showcase_shots`)에서 이미 빠진다.
    나가는 칸은 사진 경로 · 주소 · 제목 · 시각 · 겹친 수뿐이다 — 경로는 `files` 와 같이 **이 PC 의 경로**이고 그림은 PC 에 남는다.
    """
    asked = " ".join(needs or []).casefold()
    allowed = {kind for kind, words in _ALLOWED_BY.items() if any(word in asked for word in words)}
    out: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        if any(str(kind) not in allowed for kind in item.get("contains") or []):
            continue
        shot = {key: item.get(key) for key in ("path", "url", "title", "read_at", "matched")}
        shot["url"] = safe_url(str(shot.get("url") or "")) if shot.get("url") else shot.get("url")
        out.append(shot)
    return out
