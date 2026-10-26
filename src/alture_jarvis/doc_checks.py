"""문서의 숫자 검사 — 틀린 것이 확실할 때만 잡는다 (2026-10-25 대표 「문서도 똑같이」).

장표(`slide_parts.arithmetic_problems`)와 같은 생각이다. 꼴 카드(견적서 · 공문 · 사업계획서 …)가 「다 쓴 뒤 검사는 코드로」라고
적었으니, 코드가 실제로 한다:

    식 = 값 · 값(식)           장표와 같은 계산 검사
    표의 수량 × 단가 = 금액     줄마다, 합계 줄은 위 줄들의 합, 세액은 공급가액의 10%
    한글 금액 ↔ 숫자           「금113,560원(금일십일만삼천오백육십원)」 · 「일금 일백만 원정(₩1,000,000)」
    날짜 ↔ 요일               「2026. 10. 25.(일)」 · 「2026년 10월 25일(일)」

헛걸림을 줄이려고 **확실히 읽히는 것만** 본다 — 숫자로 못 읽는 칸 · 단위가 섞인 칸은 건너뛴다. 모양(문체 · 번호 체계)은 보지 않는다.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any

from .slide_parts import arithmetic_problems

_SKIP_KEYS = frozenset({"path", "format", "open", "__job_id", "theme", "style"})


def _strings(value: Any, key: str = "") -> list[str]:
    if key in _SKIP_KEYS:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _strings(v, str(k))]
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in _strings(item)]
    return []


def _tables(value: Any) -> list[list[list[str]]]:
    """인자 어디든 있는 표(머리줄 + 줄들) — [[칸, …], …]."""
    found: list[list[list[str]]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key not in _SKIP_KEYS:
                found.extend(_tables(item))
    elif isinstance(value, list):
        if len(value) >= 2 and all(isinstance(row, (list, tuple)) for row in value):
            found.append([[str(cell) for cell in row] for row in value])
        else:
            for item in value:
                found.extend(_tables(item))
    return found


_UNIT = {"억": 1e8, "만": 1e4, "천": 1e3}


#: 수량 · 금액 칸 끝에 붙는 단위 말(「12개월」 · 「1회」 · 「200장」) — 실제 견적서 판 ba286682 에서 못 읽었다.
_COUNT_WORDS = re.compile(r"(개월|개|회|장|건|명|곳|식|대|부|권|매|박스|세트|EA|ea|Ea|시간|일|주)$")


def _money(cell: str) -> float | None:
    """「1,200,000」 · 「1,200,000원」 · 「₩1,200,000」 · 「120만 원」 · 「12개월」 → 수. 못 읽으면 None."""
    text = str(cell).strip().replace("₩", "").replace("원", "").replace(" ", "")
    text = _COUNT_WORDS.sub("", text.replace("−", "-"))
    match = re.fullmatch(r"(-?\d[\d,]*(?:\.\d+)?)(억|만|천)?", text)
    if not match:
        return None
    return float(match.group(1).replace(",", "")) * _UNIT.get(match.group(2) or "", 1.0)


def _col(header: list[str], *names: str) -> int | None:
    for name in names:
        for i, cell in enumerate(header):
            if name in cell.replace(" ", ""):
                return i
    return None


def table_problems(table: list[list[str]]) -> list[str]:
    # 머리줄은 표 안 어디에 있든 「수량 · 단가」(없으면 「공급가액」)가 있는 첫 줄 — 시트 통째면 맨 위는 제목 줄이다(ba286682).
    start = next((i for i, row in enumerate(table) if _col(row, "수량") is not None and _col(row, "단가") is not None), None)
    if start is None:
        start = next((i for i, row in enumerate(table) if _col(row, "공급가액") is not None), 0)
    table = table[start:]
    header = table[0]
    qty = _col(header, "수량")
    price = _col(header, "단가")
    amount = _col(header, "공급가액", "금액")
    tax = _col(header, "세액", "부가세")
    found: list[str] = []
    if amount is None:
        return found
    total_of_rows = 0.0
    counted = 0
    for row in table[1:]:
        if len(row) <= amount:
            continue
        first = " ".join(row[:2]).replace(" ", "")
        value = _money(row[amount])
        if re.search(r"^(합계|총계|소계|계)|합계", first):
            if value is not None and counted >= 2 and abs(value - total_of_rows) > max(1.0, total_of_rows * 0.001):
                found.append(f"표의 「{row[0]}」 {row[amount]} — 위 줄들의 {header[amount]}을 더하면 {total_of_rows:,.0f}")
            continue
        if value is None:
            continue
        if qty is not None and price is not None and len(row) > max(qty, price):
            q, p = _money(row[qty]), _money(row[price])
            if q is not None and p is not None and abs(q * p - value) > max(1.0, value * 0.001):
                found.append(f"표의 「{row[0] or row[1]}」 줄 {row[qty]} × {row[price]} = {q * p:,.0f} 인데 {header[amount]}은 {row[amount]}")
        if tax is not None and len(row) > tax and header[amount].replace(" ", "") != "금액":
            t = _money(row[tax])
            if t is not None and abs(value * 0.1 - t) > 10:
                found.append(f"표의 「{row[0] or row[1]}」 줄 세액 {row[tax]} — {header[amount]} {row[amount]}의 10%면 {value * 0.1:,.0f}")
        total_of_rows += value
        counted += 1
    return found


_DIGIT = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_SMALL = {"십": 10, "백": 100, "천": 1000}
_BIG = {"만": 10**4, "억": 10**8, "조": 10**12}


def korean_number(text: str) -> int | None:
    """「일십일만삼천오백육십」 → 113560. 못 읽는 글자가 있으면 None."""
    text = text.replace(" ", "")
    if not text:
        return None
    total = section = digit = 0
    for char in text:
        if char in _DIGIT:
            digit = _DIGIT[char]
        elif char in _SMALL:
            section += (digit or 1) * _SMALL[char]
            digit = 0
        elif char in _BIG:
            total += (section + digit or 1) * _BIG[char]
            section = digit = 0
        else:
            return None
    return total + section + digit


_PAIR_GOV = re.compile(r"금\s*([\d,]+)\s*원\s*\(\s*금\s*([가-힣 ]+?)\s*원\s*\)")
_PAIR_PLAIN = re.compile(r"일금\s*([가-힣 ]+?)\s*원\s*정?\s*\(\s*₩?\s*([\d,]+)\s*원?\s*\)")


_LONE = re.compile(r"일금\s*([가-힣 ]+?)\s*원\s*정?")
_NUMBER = re.compile(r"\d[\d,]{3,}")


def amount_problems(texts: list[str]) -> list[str]:
    found = []
    # 짝 없는 한글 금액(숫자와 다른 칸) — 문서 안 어느 금액과도 같지 않으면 틀렸다(실제 견적서 판 ba286682:
    # 합계 1,669,800 옆 칸에 「일금 육백육십육만구천팔백원정」 = 6,669,800).
    numbers = {int(n.replace(",", "")) for text in texts for n in _NUMBER.findall(text)}
    for text in texts:
        for match in _LONE.finditer(text):
            words = korean_number(match.group(1))
            if words is None or words < 1000 or words in numbers or not numbers:
                continue
            near = min(numbers, key=lambda n: abs(n - words) / max(n, words))
            found.append(f"「{match.group(0).strip()}」 = {words:,}원 — 문서의 어떤 금액과도 같지 않다(가까운 금액 {near:,}원)")
    for text in texts:
        for match in _PAIR_GOV.finditer(text):
            number, words = int(match.group(1).replace(",", "")), korean_number(match.group(2))
            if words is not None and words != number:
                found.append(f"「{match.group(0)}」 — 한글 금액은 {words:,}원")
        for match in _PAIR_PLAIN.finditer(text):
            words, number = korean_number(match.group(1)), int(match.group(2).replace(",", ""))
            if words is not None and words != number:
                found.append(f"「{match.group(0)}」 — 한글 금액은 {words:,}원")
    return found


_DAY_NAMES = "월화수목금토일"
_DATE_DOT = re.compile(r"(\d{4})\.\s?(\d{1,2})\.\s?(\d{1,2})\.?\s*\(([월화수목금토일])\)")
_DATE_KO = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*\(([월화수목금토일])(?:요일)?\)")


def weekday_problems(texts: list[str]) -> list[str]:
    found = []
    for text in texts:
        for pattern in (_DATE_DOT, _DATE_KO):
            for match in pattern.finditer(text):
                try:
                    day = _dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                except ValueError:
                    found.append(f"「{match.group(0)}」 — 없는 날짜")
                    continue
                right = _DAY_NAMES[day.weekday()]
                if right != match.group(4):
                    found.append(f"「{match.group(0)}」 — 그날은 {right}요일")
    return found


def problems(arguments: dict[str, Any]) -> list[str]:
    """문서 쓰기 인자 전체에서 확실히 틀린 숫자 · 날짜를 모은다."""
    texts = _strings(arguments)
    rows_as_text = [" · ".join(row) for table in _tables(arguments) for row in table]
    found = arithmetic_problems(texts + rows_as_text)
    found += amount_problems(texts)
    found += weekday_problems(texts)
    for table in _tables(arguments):
        found += table_problems(table)
    return list(dict.fromkeys(found))
