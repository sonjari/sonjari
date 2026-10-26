"""숫자가 **무엇을** 세는지 판정하는 한 곳.

계획층(:mod:`plan`)과 작업계약(:mod:`task_contract`)이 같은 판정을 쓴다. 두 군데서
세면 반드시 갈린다 — 이 저장소가 상한·분류표에서 여러 번 겪은 자리다.

핵심 명제 하나: **프롬프트 전체의 대표 숫자를 만들지 않는다.** 숫자는 자기가 세는
낱말에 붙는다. 「이 문서를 읽고 핵심 3개를 정리해줘」의 `3` 은 읽을 개수가 아니다.
"""

from __future__ import annotations

import re


#: 수량의 **역할**. 같은 「3개」가 읽을 개수일 수도, 내놓을 개수일 수도 있다.
#:
#: ★ 2026-09-03 스모크. 「이 문서를 직접 읽고 핵심 3개를 정리해줘」에 계획층이
#:   `3개` 를 읽기 개수로 가져가 지목한 문서 말고 **두 개를 더 읽었다.** 프롬프트
#:   전체의 대표 숫자를 만들면 반드시 이렇게 된다 — 숫자는 자기가 세는 것에 붙는다.
ROLE_INPUT = "input_cardinality"
ROLE_OUTPUT = "output_cardinality"
ROLE_ACTION = "action_cardinality"
ROLE_CONSTRAINT = "constraint_value"
ROLE_RANGE = "range_endpoint"
ROLE_UNKNOWN = "unknown"

#: 세는 말과 숫자 사이에 끼는 것들. 「서비스 상위 5개」의 주인은 `상위` 가 아니라
#: `서비스` 다. 이걸 안 건너뛰면 실측 표본의 최빈 낱말이 통째로 `상위` 가 된다.
_COUNT_MARKER = re.compile(
    r"(?:상위|하위|최상위|최소|최대|최대한|약|총|각각|전부|모두|대략|한|적어도|이상|이하"
    r"|(?:개|건|곳|명|회|번)씩?)$"
)
#: 조사만 남은 꼬리. 「공고를 3개」의 `를` 을 떼고 `공고` 를 잡는다.
_OBJECT_TAIL = re.compile(r"(?:은|는|이|가|을|를|의|와|과|도|만|에|에서|으로|에게|한테|부터|까지|중|중에서)$")

#: 세상에 이미 있어서 **가서 읽어야** 하는 것. 이 숫자는 입력 개수다.
_SOURCE_NOUN = re.compile(
    r"^(?:문서|파일|자료|공고|서비스|프로젝트|사이트|홈페이지|페이지|글|기사|논문"
    r"|상품|제품|회사|업체|기업|곳|군데|후보|결과|링크|영상|리뷰|댓글|게시글|포스트"
    r"|블로그|채용|모집|공고문|소스|출처|레포|저장소|커밋|이슈|PR)$"
)
#: 생각해서 **내놓아야** 하는 것. 이 숫자는 출력 개수다.
_PRODUCT_NOUN = re.compile(
    r"^(?:핵심|요점|포인트|항목|섹션|목차|강점|약점|장점|단점|병목|이유|원인|방안"
    r"|대안|제안|아이디어|예시|근거|교훈|시사점|정리|요약|각주|주석|문장|줄|단락"
    r"|질문|답변|가설|시나리오|우선순위|과제|액션|축|기준|관점|갈래"
    # ★ 만들 파일의 **모양**을 세는 말 (2026-10-04 레딧 조사 판 aa741c81). 「엑셀 파일 하나에 시트 두 개로」의 `두 개` 가
    #   옆의 「파일」 때문에 「로컬 자료 2개 이상 직접 열어 읽기」가 됐고, 정작 「글 5개 이상」은 대조표에서 빠졌다.
    r"|시트|워크시트|탭|슬라이드|장표|표|열|행|칸|컬럼)$"
)
#: **한 페이지 안에 줄지어 있는 것** — 세는 것이 페이지가 아니라 그 페이지 속 항목이다.
#:
#: ★ 2026-10-23 레딧 판(62555a75): 「이 레딧 글을 열어서 읽고 … 추천이 많은 댓글 위에서부터 10개를 「누가 · 무슨 말 · 추천 수」로」가
#:   「10개 이상 직접 열어 읽기」가 됐다. 손자리는 글 하나면 끝날 일에 다른 페이지를 열며 8분 넘게 헤맸다(사람이 취소).
#:   「댓글」은 가서 읽는 것이라 `_SOURCE_NOUN`(역할 input)에 그대로 둔다 — 작업계약의 소유권 판정은 바뀌지 않는다.
#:   갈리는 것은 **몇 번 열어야 하는가**다. 글 · 기사 · 공고는 하나가 한 페이지지만, 댓글 열 개는 한 페이지 안에 있다.
#:   리뷰 · 후기는 넣지 않았다 — 「블로그 후기 5개」는 글 다섯 편이다(낱말만으로 못 가른다).
_IN_PAGE_ENTRY_NOUN = re.compile(r"^(?:댓글|대댓글|답글|덧글|리플|코멘트)$")
_IN_PAGE_ENTRY_NOUN_EN = frozenset({"comment", "comments", "reply", "replies"})


def lives_inside_a_page(obj: str) -> bool:
    """세는 낱말이 **한 페이지 안의 항목**인가 — 이 개수는 열 페이지 수가 아니라 답에 담을 항목 수다."""
    obj = (obj or "").strip()
    return bool(obj) and bool(_IN_PAGE_ENTRY_NOUN.match(obj) or obj.casefold() in _IN_PAGE_ENTRY_NOUN_EN)


#: 조건값이 되는 단위. 「경력 3년」은 세는 것이 아니라 거르는 값이다.
_CONSTRAINT_UNIT = frozenset({"년", "개월", "주", "일", "시간", "분", "초", "원", "만원", "퍼센트", "%"})
#: **같이 가는 사람**을 세는 말. 「인원은 2명」·「성인 2명」은 찾을 개수가 아니라 조건값이다.
#:
#: ★ 2026-10-08 숙소 조사 판: 「…인원은 2명이고 예약은 하지 말고 알아보기만 해줘」가 「2개 실제로 처리하기」가 됐다.
#:   값이 전부 맞는 답 끝에 「2개를 처리하라고 하셨는데 하나도 안 했습니다」가 붙었고 판은 부분 완료로 끝났다.
#:   사람 수는 「경력 3년」과 같은 자리다 — 세는 것이 아니라 거르는 값.
_PARTY_NOUN = re.compile(
    r"^(?:인원|인원수|성인|어른|대인|소인|아이|어린이|아동|유아|일행|투숙객|탑승객|승객|동행)$"
)
#: 「2명이서」·「2명이 갈」 — 세는 낱말 없이도 같이 가는 사람 수다.
_PARTY_TAIL = re.compile(r"^\s*(?:이서|이\s*(?:갈|가는|묵|잘|쓸|탈|머물|이용|숙박|여행))")
#: 실제 수행 횟수.
_ACTION_UNIT = frozenset({"번", "회", "차례"})
#: 「11번가」 · 「3번지」 — 이름의 일부다. 「번」은 받침이 있어 뒤에 조사 「가」가 올 수 없으니, 「가 · 지」가 붙고 거기서 낱말이
#: 끝나거나 자리 조사가 오면 횟수가 아니다. 「두번가봤는데」 · 「3번지켜봤는데」처럼 움직씨가 붙은 것은 그대로 횟수다.
#:
#: ★ 2026-10-13 촬영 판: 「다나와, 11번가, G마켓에서 …」의 「11번」이 `action_cardinality 11` 로 읽혔다.
#:   넓게 잡지 않는다 — 「뒤에 글자가 붙으면 이름」은 운영 요청에서 붙여 쓴 진짜 횟수(「3번먹었는데」)까지 뺐다.
_NAME_AFTER_BEON = re.compile(r"^(?:가|지)(?:(?![가-힣])|에서|에|의|와|과|랑|로|쪽|도)")


def unit_is_part_of_a_name(unit: str, tail: str) -> bool:
    """`unit` 바로 뒤의 글(`tail`)을 보면 이 「N번」이 이름의 일부인가."""
    return unit == "번" and bool(_NAME_AFTER_BEON.match(tail or ""))


#: 범위의 끝점을 만드는 표지. 「1순위부터 3순위까지」는 개수가 아니다.
_RANGE_EDGE = re.compile(r"^\s*(?:부터|까지|~|-)")
_RANGE_BEFORE = re.compile(r"(?:부터|까지)\s*$")


def _object_before(text: str, start: int) -> tuple[str, int, int]:
    """숫자가 **무엇을** 세는지 원문에서 찾는다.

    표지(`상위`·`총`)와 조사를 건너뛰고 가장 가까운 실제 낱말을 잡는다.
    못 찾으면 빈 값을 돌려준다 — 지어내지 않는다. 소유권은 원문 span 이 있을
    때만 인정한다.
    """
    head = text[:start]
    for _ in range(4):
        match = re.search(r"([가-힣A-Za-z]{1,12})[\s,·0-9]*$", head)
        if not match:
            return ("", -1, -1)
        word = match.group(1)
        stripped = _OBJECT_TAIL.sub("", word) or word
        if _COUNT_MARKER.search(stripped) or _RANGE_BEFORE.search(word):
            head = head[: match.start(1)]
            continue
        return (stripped, match.start(1), match.start(1) + len(stripped))
    return ("", -1, -1)


def _object_after(text: str, end: int) -> tuple[str, int, int]:
    """세는 말이 숫자 **뒤**에 오는 모양. 「상위 5개 서비스」가 그것이다.

    한국어는 둘 다 쓴다(「서비스 5개」·「5개 서비스」). 뒤를 안 보면 실측에서
    unknown 의 가장 큰 덩어리가 그대로 남는다.
    """
    match = re.match(r"\s*(?:의|개의)?\s*([가-힣]{1,12})", text[end:])
    if not match:
        return ("", -1, -1)
    word = _OBJECT_TAIL.sub("", match.group(1)) or match.group(1)
    start = end + match.start(1)
    return (word, start, start + len(word))


def counted_object(text: str, start: int, end: int) -> tuple[str, int, int]:
    """숫자가 세는 것을 앞뒤로 찾되, **뜻이 잡히는 쪽**을 고른다.

    앞이 비면 뒤를 본다. 앞이 있어도 분류가 안 되고 뒤가 분류되면 뒤를 쓴다 —
    「검색했을 때 상위 5개 서비스」에서 앞은 배경이고 뒤가 목적어다.
    """
    back = _object_before(text, start)
    if back[0] and (_SOURCE_NOUN.match(back[0]) or _PRODUCT_NOUN.match(back[0])):
        return back
    forward = _object_after(text, end)
    if forward[0] and (_SOURCE_NOUN.match(forward[0]) or _PRODUCT_NOUN.match(forward[0])):
        return forward
    return back if back[0] else forward


def quantity_role(unit: str, obj: str, tail: str) -> str:
    """단위 → 세는 낱말 → 범위 표지 순으로 본다. 모르면 모른다고 한다."""
    if unit in _CONSTRAINT_UNIT:
        return ROLE_CONSTRAINT
    if unit == "명" and ((obj and _PARTY_NOUN.match(obj)) or _PARTY_TAIL.match(tail)):
        return ROLE_CONSTRAINT
    if unit in _ACTION_UNIT:
        return ROLE_ACTION
    if unit == "순위" or _RANGE_EDGE.match(tail):
        return ROLE_RANGE
    if obj:
        if _SOURCE_NOUN.match(obj):
            return ROLE_INPUT
        if _PRODUCT_NOUN.match(obj):
            return ROLE_OUTPUT
    return ROLE_UNKNOWN
