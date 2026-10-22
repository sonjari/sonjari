"""값 칸 배우기 — 손자리가 일하면서 **사이트의 어느 칸에 무슨 값이 있는지**를 스스로 배우고, 스스로 검증한다 (2026-10-21).

## 왜

대표(10-20): 「레시피를 확장하는 것은 손자리가 해야 한다 — 그게 핵심 킬러 기능」. 그런데 T4 실측(설계 §10-4)에서 주소 레시피는
빠르게 하지 않았다 — 시간은 상세 페이지 본문을 읽는 데 든다. 예스24 상세 본문 20,000자(약 1만 4천 토큰)를 읽느라
첫 글자까지 17초였는데, 답에 쓴 값(쪽수 · 출판사 · 판매가)은 본문의 작은 칸 몇 개에 있었다.
그 칸을 배우면 본문 대신 값만 줄 수 있다.

## 발상의 출처

AutoScraper(MIT, alirezamika/autoscraper — 2026-10-21 손자리가 직접 열어 확인)의 「예시 값을 주면 규칙을 배워 저장하고
모델 없이 재사용」. 코드는 들이지 않았다. 우리는 HTML 구조 대신 **이미 읽은 본문 글 + 이름표**로 배우고, 그 위에 검증을 얹는다.

## 규칙 (모델이 아니라 이 코드가 정한다)

- 배우기: 답의 「이름: 값」(목록 줄 · 표 줄)의 값이 본문에서 **이름표 줄 바로 다음 줄**에 있을 때만 칸이 된다.
  이름표는 본문에서 **한 번만** 나와야 한다(여러 번 나오는 줄은 우연히 붙은 것이다 — 첫 시험에서 출판사가 「혼공 체크표」에 붙었다).
  그 칸으로 본문을 다시 읽어 **답의 값과 같아야** 남긴다.
- 값: 이름표 다음 줄의 첫 칸(줄 끝이나 「|」까지). 견줄 때는 숫자의 차례로 본다(「2022년 06월 01일」 = 「2022년 6월 1일」,
  「19,800원 (10% 할인)」 은 「19,800원」 과 같다 — 앞부분이 같으면).
- 검증: 같은 사이트의 다른 페이지에서 칸이 뽑은 값과 그 판의 답이 맞으면 +1, 틀리면 그 칸을 버린다.
  **두 번 맞고 한 번도 안 틀린 칸만 믿는다**(`TRUST_AFTER`). 배운 판 자체는 검증으로 치지 않는다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

#: 이만큼 맞아야 믿는다.
TRUST_AFTER = 2
#: 이름표로 받는 줄의 길이 상한.
LABEL_MAX = 24
#: 답에서 「이름: 값」 을 읽는 꼴 — 「- **쪽수:** 552쪽」 · 「쪽수: 552쪽」 · 「| 쪽수 | 552쪽 |」.
_PAIR_LINE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:\*\*)?(?P<label>[^:：|*\n]{1,20}?)(?:\*\*)?\s*[:：]\s*(?:\*\*)?(?P<value>[^\n]+?)(?:\*\*)?\s*$"
)
_TABLE_ROW = re.compile(r"^\s*\|\s*(?P<label>[^|]{1,20}?)\s*\|\s*(?P<value>[^|]{1,80}?)\s*\|\s*$")
_RULE_ROW = re.compile(r"^\s*\|?\s*:?-{2,}")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SPACES = re.compile(r"\s+")


def _clean(text: str) -> str:
    return re.sub(r"\*\*|`", "", str(text or "")).strip()


def answer_pairs(answer: str) -> list[tuple[str, str]]:
    """답에서 「이름: 값」 짝. 표 머리 · 구분 줄 · 출처 줄은 뺀다."""
    pairs: list[tuple[str, str]] = []
    for line in str(answer or "").splitlines():
        if _RULE_ROW.match(line):
            continue
        found = _PAIR_LINE.match(line) or _TABLE_ROW.match(line)
        if not found:
            continue
        label, value = _clean(found.group("label")), _clean(found.group("value"))
        # 값 뒤의 괄호 설명(「19,800원 (정가 22,000원, 10% 할인)」)은 값이 아니다.
        value = re.split(r"\s+\(", value)[0].strip()
        if label and value and len(value) <= 60 and not label.startswith(("출처", "http", "#")):
            pairs.append((label, value))
    return pairs


def _key(value: str) -> tuple:
    """견주는 열쇠 — 숫자가 있으면 숫자의 차례, 없으면 빈칸 뺀 글(소문자)."""
    numbers = tuple(int(float(n.replace(",", ""))) for n in _NUMBER.findall(str(value or "")))
    return numbers if numbers else (_SPACES.sub("", str(value or "")).casefold(),)


def same_value(said: str, got: str) -> bool:
    """답의 값과 칸의 값이 같은가 — 칸이 더 길면 앞부분이 같으면 같다."""
    want, have = _key(said), _key(got)
    if not want or not have or want == ("",) or have == ("",):
        return False
    if isinstance(want[0], int) and isinstance(have[0], int):
        return have[: len(want)] == want
    if isinstance(want[0], str) and isinstance(have[0], str):
        return have[0].startswith(want[0])
    return False


def _shares_a_word(label: str, anchor: str) -> bool:
    """두 글자 이상 겹치는가 — 빈칸 · 문장부호는 빼고 소문자로."""
    a = re.sub(r"[\s\W_]+", "", str(label or "")).casefold()
    b = re.sub(r"[\s\W_]+", "", str(anchor or "")).casefold()
    return any(a[i : i + 2] in b for i in range(len(a) - 1)) if len(a) >= 2 else False


def read_cell(cell: dict[str, Any], body: str) -> str:
    """칸이 가리키는 값 — 이름표 줄 바로 다음 줄의 첫 칸(줄 끝이나 「|」까지)."""
    anchor = re.escape(str(cell["anchor"]))
    found = re.search(r"(?m)^[ \t]*" + anchor + r"[ \t]*\n[ \t]*([^\n|]{1,60}?)[ \t]*(?=\||\n|$)", str(body or ""))
    return found.group(1).strip() if found else ""


def learn(answer: str, body: str) -> list[dict[str, Any]]:
    """이 판의 답과 읽은 본문에서 값 칸 **후보**를 뽑는다."""
    text = str(body or "")
    lines = [line.strip() for line in text.splitlines()]
    counts: dict[str, int] = {}
    for line in lines:
        counts[line] = counts.get(line, 0) + 1
    cells: list[dict[str, Any]] = []
    for label, value in answer_pairs(answer):
        key = _key(value)
        if isinstance(key[0], str) and len(key[0]) < 2:
            continue
        for index in range(1, len(lines)):
            above = lines[index - 1]
            if not (1 < len(above) <= LABEL_MAX) or _NUMBER.fullmatch(above) or counts.get(above) != 1:
                continue
            # 이름표가 답의 이름과 두 글자 이상 겹쳐야 한다(「쪽수」 ⊂ 「쪽수, 무게, 크기」). 첫 시험에서 출판사가 「혼공 체크표」,
            # 저자가 「[ 개정판 ]」에 우연히 붙었다 — 그 책에만 있는 줄이다. 틀리게 배우느니 덜 배운다.
            if not _shares_a_word(label, above):
                continue
            cell = {"field": label, "anchor": above, "agree": 0, "disagree": 0}
            if same_value(value, read_cell(cell, text)):
                cells.append(cell)
                break
    return cells


def apply(cells: list[dict[str, Any]], body: str) -> dict[str, str]:
    """칸들로 본문에서 값을 뽑는다. 못 뽑은 칸은 빼고."""
    out: dict[str, str] = {}
    for cell in cells:
        value = read_cell(cell, body)
        if value and cell["field"] not in out:
            out[cell["field"]] = value
    return out


def trusted(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [cell for cell in cells if int(cell.get("agree") or 0) >= TRUST_AFTER and not int(cell.get("disagree") or 0)]


def verify(cells: list[dict[str, Any]], answer: str, body: str) -> list[dict[str, Any]]:
    """다른 페이지 · 다른 판에서 칸이 뽑은 값과 답을 견준다. 맞으면 +1, 틀리면 그 칸을 버린다. 답에 그 이름이 없으면 그대로."""
    said = dict(answer_pairs(answer))
    kept: list[dict[str, Any]] = []
    for cell in cells:
        if cell["field"] not in said:
            kept.append(cell)
            continue
        got = read_cell(cell, body)
        if got and same_value(said[cell["field"]], got):
            kept.append({**cell, "agree": int(cell.get("agree") or 0) + 1})
        elif got:
            continue  # 틀렸다 — 버린다(다음 판에서 다시 배울 수는 있다)
        else:
            kept.append(cell)
    return kept


#: 사람이 「무엇을」 물었는지 가르는 속성 낱말. 물은 것이 **모두** 믿는 칸으로 덮일 때만 본문을 줄인다 — 하나라도 안 덮이면 본문 그대로.
ATTRIBUTE_WORDS = (
    "가격", "판매가", "정가", "할인", "쪽수", "페이지", "출판사", "저자", "지은이", "역자", "발행일", "출간일", "출판일", "isbn",
    "평점", "별점", "리뷰", "후기", "재고", "배송", "마감", "연봉", "급여", "위치", "주소", "경력", "학력", "용량", "무게", "크기",
    "사이즈", "색상", "제조사", "브랜드", "모델명", "출시일", "수량", "순위", "price", "pages", "publisher", "author", "rating",
)
#: 물은 낱말 → 같은 것으로 보는 칸 이름(「가격」을 물었으면 「판매가」 칸이 덮는다).
_SAME_AS = {"가격": ("판매가", "가격"), "페이지": ("쪽수", "페이지"), "출간일": ("발행일", "출간일", "출판일"),
            "출판일": ("발행일", "출간일", "출판일"), "지은이": ("저자", "지은이"), "별점": ("평점", "별점"), "평점": ("평점", "별점")}


def _covers(word: str, field: str) -> bool:
    field = str(field or "").casefold()
    return any(name in field for name in _SAME_AS.get(word, (word,))) or _shares_a_word(word, field)


#: 줄일 때 남기는 본문 앞부분(제목 · 첫 설명이 대개 여기 있다).
COMPACT_HEAD_CHARS = 1500


def compact_text(cells: list[dict[str, Any]], body: str, asked: str) -> tuple[str, list[str]]:
    """믿는 칸이 물은 것을 **모두** 덮으면 (줄인 본문, 쓴 칸 이름들). 아니면 ("", []).

    줄인 본문 = 「배운 값」 몇 줄 + 본문 앞부분. 다른 내용이 필요하면 다시 읽으라는 안내를 붙인다 — 모르는 것을 지우지 않는다.
    """
    good = trusted(cells)
    if not good:
        return "", []
    text = str(asked or "").casefold()
    asked_words = [word for word in ATTRIBUTE_WORDS if word in text]
    if not asked_words:
        return "", []
    covered = [word for word in asked_words if any(_covers(word, str(cell["field"])) for cell in good)]
    if len(covered) != len(asked_words):
        return "", []
    values = apply(good, body)
    if not values:
        return "", []
    lines = [f"{field}: {value}" for field, value in values.items()]
    head = str(body or "")[:COMPACT_HEAD_CHARS]
    note = ("[손자리가 이 사이트에서 배운 값 칸으로 읽었다 — 칸마다 앞선 판들에서 " + str(TRUST_AFTER)
            + "번 이상 답과 맞았다. 아래 값이 이 페이지의 값이다. 본문의 다른 내용이 필요하면 browser_extract 를 한 번 더 부르면 본문 전체를 준다.]")
    compact = note + "\n" + "\n".join(lines) + "\n\n[본문 앞부분]\n" + head
    # 짧은 페이지는 줄일 것이 없다 — 「값 + 앞부분」이 원문의 절반보다 길면 원문 그대로(줄여서 얻는 것 없이 잃기만 한다).
    if len(compact) * 2 > len(str(body or "")):
        return "", []
    return compact, list(values)


def _ident(cell: dict[str, Any]) -> tuple[str, str]:
    return (str(cell.get("field")), str(cell.get("anchor")))


class ValueCellBook:
    """사이트(호스트)별 값 칸 — `문서\\Sonjari\\recipes\\value_cells\\<호스트>.json`. 사람 폴더라 스토어 판에서도 쓸 수 있다."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def _path(self, host: str) -> Path:
        return self.directory / (re.sub(r"[^a-z0-9.\-]", "_", host.lower()) + ".json")

    def cells(self, host: str) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._path(host).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [cell for cell in (data.get("cells") or []) if isinstance(cell, dict) and cell.get("anchor")]

    def save(self, host: str, cells: list[dict[str, Any]]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(host).write_text(json.dumps({"host": host, "cells": cells}, ensure_ascii=False, indent=1), encoding="utf-8")

    def observe(self, url: str, answer: str, body: str) -> dict[str, Any]:
        """판 하나가 끝났을 때: 기존 칸을 이 페이지로 검증하고, 새 후보를 배운다. 무엇이 바뀌었는지 돌려준다.

        같은 판 안에서 배운 칸을 곧바로 그 판으로 검증하지 않는다 — 배운 판은 검증이 아니다.
        """
        host = (urlparse(str(url or "")).hostname or "").lower()
        if not host or not body:
            return {"host": host, "learned": 0, "trusted": 0, "newly_trusted": 0}
        before = self.cells(host)
        checked = verify(before, answer, body)
        known = {_ident(cell) for cell in checked}
        learned = [cell for cell in learn(answer, body) if _ident(cell) not in known]
        after = checked + learned
        if after != before:
            self.save(host, after)
        return {"host": host, "learned": len(learned), "dropped": len(before) - len(checked),
                "trusted": len(trusted(after)), "newly_trusted": len(trusted(after)) - len(trusted(before)), "cells": len(after)}
