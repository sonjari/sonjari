"""자료의 낱말을 한 자모만 틀리게 옮긴 오타 — 「클로드 → 크로드」 · 「클라우드 → 크라우드」 (2026-10-26 소개 판 e5cb9df2).

로컬 27B 가 자료에 맞게 적힌 낱말을 장에 옮기며 받침 하나를 빠뜨렸다. 정답이 자료에 있으니 코드가 고칠 수 있는 자리다
(최소 개입 사다리 0~1단). 헛걸림을 줄이려고 좁게 문다:

- 자료(요청 글)에 나온 **세 글자 이상** 한글 낱말만 기준으로 삼는다.
- 결과 글의 같은 길이 토막이 그 낱말과 **자모 딱 하나**만 다르고(초성 · 중성 · 종성 중 한 칸), 그 토막 자체는 자료에 없을 때.
- 토막은 낱말 머리에서 시작해야 한다(앞 글자가 한글이 아니다) — 「…손자를」 같은 낱말 가운데는 보지 않는다.
- **마지막 글자가 다르면 보지 않는다** — 조사 · 어미가 사는 자리다(「학원이 ↔ 학원에」 · 「조사하 ↔ 조사해」).
- 끝의 한 글자 조사를 떼고도 **세 글자 이상** 남는 낱말만 본다(「문서를 ↔ 순서를」은 두 글자 낱말 + 조사).

10-26 첫 판정을 지난 장표 · 문서 쓰기 1,045번에 대 보니 147건 중 거의 전부가 위 두 갈래 헛걸림이었다 — 좁혔다.
"""

from __future__ import annotations

import re
from typing import Iterable

_HANGUL_WORD = re.compile(r"[가-힣]{3,}")


def _jamo(syllable: str) -> tuple[int, int, int]:
    code = ord(syllable) - 0xAC00
    return code // 588, (code % 588) // 28, code % 28


def _one_jamo_apart(a: str, b: str) -> bool:
    """같은 길이의 두 한글 토막이 자모 딱 하나만 다른가(마지막 글자의 종성 차이는 빼고)."""
    if len(a) != len(b) or a == b:
        return False
    diffs = 0
    for index, (x, y) in enumerate(zip(a, b)):
        if x == y:
            continue
        jx, jy = _jamo(x), _jamo(y)
        changed = [k for k in range(3) if jx[k] != jy[k]]
        if len(changed) != 1 or index == len(a) - 1:
            return False
        diffs += 1
        if diffs > 1:
            return False
    return diffs == 1


#: 낱말 끝에 붙는 한 글자 조사 — 떼고 나서 세 글자 이상 남아야 본다.
_PARTICLES = set("이가은는을를에의와과도로만야께")


def _stem_long_enough(word: str) -> bool:
    stem = word[:-1] if word and word[-1] in _PARTICLES else word
    return len(stem) >= 3


def vocabulary(source: str) -> set[str]:
    """자료 글의 세 글자 이상 한글 낱말 — 조사가 붙은 꼴도 앞에서부터 잘라 넣는다(「클로드가」 → 클로드가 · 클로드)."""
    words: set[str] = set()
    for token in _HANGUL_WORD.findall(source or ""):
        for end in range(3, len(token) + 1):
            words.add(token[:end])
    return words


def find(text: str, source: str) -> list[tuple[str, str]]:
    """(틀린 토막, 자료의 낱말) 목록 — 자료에 없고, 자료 낱말과 자모 하나만 다른 낱말 머리 토막."""
    vocab = vocabulary(source)
    if not vocab:
        return []
    by_length: dict[int, list[str]] = {}
    for word in vocab:
        by_length.setdefault(len(word), []).append(word)
    found: dict[str, str] = {}
    for match in re.finditer(r"[가-힣]+", text or ""):
        token = match.group(0)
        for length in range(3, len(token) + 1):
            piece = token[:length]
            if piece in vocab or not _stem_long_enough(piece):
                continue
            candidates = [word for word in by_length.get(length, ()) if _stem_long_enough(word) and _one_jamo_apart(piece, word)]
            # 자료에 그 낱말이 **하나로** 정해질 때만 — 둘 이상이면 무엇이 맞는지 모른다.
            if len(candidates) == 1 and piece not in found:
                found[piece] = candidates[0]
    # 자료에서 **낱말로 서는 꼴**만 남긴다 — 뒤에 한글이 없거나 한 글자 조사만 오는 꼴(「클라우」 ✗ · 「클라우드」 ✓).
    particles = "".join(sorted(_PARTICLES))
    stands = {good for good in found.values()
              if re.search(rf"(?<![가-힣]){re.escape(good)}[{particles}]?(?![가-힣])", source or "")}
    kept = {bad: good for bad, good in found.items() if good in stands}
    # 같은 자리를 짧은 꼴이 이미 설명하면 조사까지 붙은 긴 꼴은 뺀다(「크라우드」가 있으면 「크라우드에」는 뺀다).
    return [(bad, good) for bad, good in kept.items()
            if not any(other != bad and bad.startswith(other) and good.startswith(kept[other]) for other in kept)]


def fix(text: str, pairs: Iterable[tuple[str, str]]) -> str:
    """낱말 머리의 틀린 토막을 자료의 낱말로 바꾼다."""
    for bad, good in pairs:
        text = re.sub(rf"(?<![가-힣]){re.escape(bad)}", good, text)
    return text
