"""문서 속 **정해진 꼴이 있는 번호**를 결정론으로 확인해 한 줄 붙인다 (2026-11-23 지원사업 수행계획서 판 f38ebeb4).

모델이 「사업자등록번호는 보통 3-2-6 인데 이건 3-2-5 라 확인 필요」라고 썼다. 한국 사업자등록번호는 10자리 3-2-5 가
맞다 — 틀린 상식이 멀쩡한 칸을 고치게 만들었다. 상식은 모델에게 맡기지 않고, 계산으로 확인되는 것은 계산해서 읽은 글에
붙인다(사고 R). 지금은 사업자등록번호(고유번호 포함) 하나다: 국세청 검증 숫자(가중치 1 3 7 1 3 7 1 3 5).

이름표(사업자 · 등록번호 · 고유번호)가 번호 앞 40자 안에 있을 때만 본다 — 3-2-5 꼴의 다른 번호를 사업자번호라 부르지 않으려고.
번호 자체는 이미 문서에 있는 글이라 새로 드러내는 값이 아니다.
"""
from __future__ import annotations

import re

FACTS_HEAD = "⟦손자리 계산 확인⟧"

_BIZ_NUMBER = re.compile(r"(?<![\d-])(\d{3})-(\d{2})-(\d{5})(?![\d-])")
_BIZ_LABEL = re.compile(r"사업자|등록\s*번호|고유\s*번호")
_WEIGHTS = (1, 3, 7, 1, 3, 7, 1, 3, 5)


def business_number_ok(digits: str) -> bool:
    """국세청 사업자등록번호 검증 숫자. `digits` 는 숫자 10개."""
    if len(digits) != 10 or not digits.isdigit():
        return False
    values = [int(char) for char in digits]
    total = sum(value * weight for value, weight in zip(values, _WEIGHTS))
    total += (values[8] * 5) // 10
    return (10 - total % 10) % 10 == values[9]


def number_notes(text: str, limit: int = 5) -> list[str]:
    notes: list[str] = []
    for match in _BIZ_NUMBER.finditer(text or ""):
        if not _BIZ_LABEL.search(text[max(0, match.start() - 40):match.start()]):
            continue
        number = match.group(0)
        verdict = "검증 숫자 맞음" if business_number_ok("".join(match.groups())) else "검증 숫자 안 맞음 — 한 자리가 틀렸을 수 있음"
        note = f"사업자등록번호 {number}: 사업자등록번호 꼴(10자리 · 3-2-5)이 맞음 · {verdict}"
        if note not in notes:
            notes.append(note)
        if len(notes) >= limit:
            break
    return notes


def facts_block(text: str) -> str:
    notes = number_notes(text)
    if not notes:
        return ""
    return FACTS_HEAD + " " + " / ".join(notes)
