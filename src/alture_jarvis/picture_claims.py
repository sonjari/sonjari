"""답이 **보지 못한 것**을 사실처럼 말하는 두 가지를 잡는다 (2026-11-23 NIPA 수행계획서 판 f38ebeb4).

1. 그림 자리를 「없다」고 함 — 직인 · 서명 도장이 그림으로 「(직인)」 · 「(인/서명)」 글자 위에 찍혀 있었는데 답은
   「서명/인감 미기재 · 날인 필요」라고 했다. 읽기(`pdf_marks`)가 쪽 끝에 「⟦그림 …⟧ 「서명」 글자 위」를 적어 두므로,
   그 이름표 글자가 든 답 줄이 「없음 · 미기재 · 누락」을 말하면 경고한다. 그림 속을 읽지 않았으니 맞는 말은 「확인 못 함」이다.

2. 모델이 스스로 물음표를 단 짐작 — 「(회사 이름)의 제품(로봇 메타버스 피팅?)」. 회사 이름을 보고 제품을 지어냈고,
   물음표는 모델 자신도 모른다는 표시다. 괄호 안 물음표 짐작이 **읽은 글에도 요청에도 없으면** 경고한다.
   낱말 목록이 아니라 「모델이 붙인 짐작 표시 + 근거 없음」 두 조건으로 가른다.

여기는 순수 함수만 둔다(답 · 읽은 글 → 걸린 것). 문구와 붙이는 자리는 `agent.py` 가 맡는다.
"""
from __future__ import annotations

import re

from .pdf_marks import PICTURE_HEAD

#: 그림 표시 줄에서 「…」 이름표를 꺼낸다 — 글자 위 · 근처만(바탕 · 떨어진 자리는 그 글자의 일이 아니다).
_PICTURE_LABEL = re.compile(r"((?:「[^」]{1,24}」(?: · )?)+) (?:글자 위|근처)")
_QUOTED = re.compile(r"「([^」]{1,24})」")
#: 「없다」를 말하는 꼴. 이름표가 든 줄에서만 보므로 넓게 잡아도 다른 줄을 건드리지 않는다.
_ABSENT = re.compile(
    r"미\s*기재|미\s*날인|미\s*서명|미\s*작성|누락|없음|없습니다|없다|없어|없는|비어\s*있|빈\s*칸|빈칸|공란|"
    r"안\s*찍|안\s*되어|빠져\s*있|되어\s*있지\s*않|missing|not\s+signed|no\s+(?:seal|signature|stamp)",
    re.IGNORECASE,
)
#: 「못 봤다」를 말하는 줄은 정직한 말이다 — 「확인할 수 없음」의 「없음」을 없다로 읽지 않는다.
_HONEST = re.compile(
    r"확인\s*(?:못|하지\s*못|할\s*수\s*없|이\s*안\s*되|불가)|볼\s*수\s*없|보지\s*못|읽지\s*(?:못|않)|알\s*수\s*없|"
    r"그림(?:으로|이라|이어서)|이미지(?:로|라)|cannot\s+(?:see|verify|confirm)|could\s+not\s+(?:see|verify|confirm)|not\s+verified",
    re.IGNORECASE,
)
_NOISE = re.compile(r"[\W_]+")
#: 이름표가 이보다 짧으면(느슨하게 만든 뒤) 줄 맞추기에 쓰지 않는다 — 「인」 한 글자는 모든 줄에 걸린다.
_ANCHOR_MIN = 2

#: 괄호 안 물음표 짐작 — 「제품(로봇 메타버스 피팅?)」 · 「고래회원(고려해운?)」. 괄호가 **낱말에 바로 붙어**(띄어쓰기 없이) 그 낱말을
#: 풀어 쓴 꼴이고, 물음표는 괄호 닫기 바로 앞 **하나**뿐이어야 한다. 운영 답 5,633개 역검증(2026-11-23): 괄호 물음표 23판 중
#: 21판은 짐작이 아니라 질문이었다 — 「(진행해도 될까요?)」 · 「차별점 (Why Us?)」 · 「(투자자? 실무자? 학생?)」 · 「분석(왜 …가?)」.
_HEDGE = re.compile(r"(?<=\w)[(（]([^()（）\n?？]{2,40}?)\s*[?？][)）]")
#: 질문 꼴 — 묻는 낱말로 시작하거나 묻는 끝말로 끝나면 짐작이 아니라 질문이다.
_QUESTION_START = re.compile(r"(?i)^(?:왜|무엇|뭘|뭐|어떻게|어떤|어느|누가|누구|언제|어디|얼마|몇|why|what|how|who|when|where|which)")
_QUESTION_END = re.compile(r"(?:가|나|니|까|냐|요|죠|지|래)$")
#: 짐작 안 글자가 이보다 짧으면 보지 않는다 — 「(?)」 · 「(왜?)」 같은 말버릇.
_HEDGE_MIN = 3


def _loose(text: str) -> str:
    return _NOISE.sub("", str(text or "")).lower()


def picture_anchors(text: str) -> list[str]:
    """읽은 글의 「⟦그림 …⟧」 줄에서 그림이 찍힌 자리의 글자 이름표들."""
    anchors: list[str] = []
    for line in str(text or "").splitlines():
        if not line.startswith(PICTURE_HEAD):
            continue
        for group in _PICTURE_LABEL.finditer(line):
            for name in _QUOTED.findall(group.group(1)):
                if len(_loose(name)) >= _ANCHOR_MIN and name not in anchors:
                    anchors.append(name)
    return anchors


def absent_claims_on_pictures(answer: str, anchors: list[str]) -> list[str]:
    """그림이 찍힌 자리(이름표)를 「없다 · 미기재」라고 말한 답 줄의 이름표들."""
    found: list[str] = []
    loose_anchors = [(name, _loose(name)) for name in anchors if _loose(name)]
    for line in str(answer or "").splitlines():
        if not _ABSENT.search(line) or _HONEST.search(line):
            continue
        loose_line = _loose(line)
        for name, key in loose_anchors:
            if key in loose_line and name not in found:
                found.append(name)
    return found


def unsupported_hedges(answer: str, material: str) -> list[str]:
    """괄호 안 물음표 짐작 중 읽은 글 · 요청 어디에도 없는 것(원문 그대로, 물음표 포함)."""
    haystack = _loose(material)
    found: list[str] = []
    for match in _HEDGE.finditer(str(answer or "")):
        inner = match.group(1).strip()
        key = _loose(inner)
        if len(key) < _HEDGE_MIN or key in haystack:
            continue
        if _QUESTION_START.search(inner) or _QUESTION_END.search(inner):
            continue
        shown = inner + "?"
        if shown not in found:
            found.append(shown)
    return found
