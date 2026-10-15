"""검색어 오타를 **사용자가 실제로 쓴 말**로 바로잡는다 (2026-10-01 스토어 촬영 판).

## 무엇이 있었나

「교보문고에서 '파이썬' 책 3권…」을 맡겼더니 모델이 검색 주소를 손으로 조립하면서 퍼센트 인코딩을 한 글자 틀렸다:

    keyword=%ED%8C%8C%EC%9D%B4%EC%84%9C   = 「파이서」   (「파이썬」은 %EC%8D%AC)

사고 R(2026-08-13 「무섧마우스」) 뒤로 손으로 만든 검색 주소는 도구가 **대신 검색칸에 쳐 넣는데**(`browser._search_like_a_person`),
그 문은 주소에서 꺼낸 검색어를 그대로 믿었다. 쓰레기가 들어가면 쓰레기를 쳐 넣는다 — 「'파이서'에 대한 13,340개의 검색 결과」.
이번엔 모델이 다음 걸음에서 스스로 바로잡았지만, 빈 목록이 나오는 사이트였으면 「그런 책은 없다」로 끝났다.

## 규칙 — 좁게

- 검색어 낱말이 **요청에 그대로 있으면** 안 건드린다(일부러 쓴 말이다).
- 한글 두 글자 이상 낱말만 본다. 요청 낱말(조사를 떼려고 같은 길이의 앞부분도 본다) 중
  **같은 길이 · 첫 글자 같음 · 정확히 한 글자만 다름**인 후보가 **딱 하나**일 때만 바꾼다.
- 후보가 없거나 둘 이상이면 그대로 둔다 — 모르는 것을 고치지 않는다.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_HANGUL_WORD = re.compile(r"[가-힣]{2,}")
#: `browser._HANDMADE_SEARCH` 와 같은 열쇠들 — 검색어가 실리는 주소 칸.
QUERY_KEYS = ("q", "query", "stext", "keyword", "kw", "searchword", "search_word", "term", "k1")


def _candidates(word: str, request: str) -> set[str]:
    found: set[str] = set()
    for token in _HANGUL_WORD.findall(request):
        for piece in {token, token[: len(word)]}:
            if len(piece) != len(word) or piece == word or piece[0] != word[0]:
                continue
            if sum(a != b for a, b in zip(piece, word)) == 1:
                found.add(piece)
    return found


def repair_query(query: str, request: str) -> str:
    """바로잡은 검색어. 바꿀 것이 없으면 받은 그대로."""
    if not query or not request:
        return query

    def fix(match: re.Match[str]) -> str:
        word = match.group(0)
        if word in request:
            return word
        options = _candidates(word, request)
        return options.pop() if len(options) == 1 else word

    return _HANGUL_WORD.sub(fix, query)


def repair_search_url(url: str, request: str) -> str:
    """주소의 검색어 칸만 바로잡은 주소. 바꿀 것이 없으면 받은 그대로."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if not parsed.query:
        return url
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    changed = False
    fixed: list[tuple[str, str]] = []
    for key, value in pairs:
        if key.lower() in QUERY_KEYS:
            repaired = repair_query(value, request)
            if repaired != value:
                value, changed = repaired, True
        fixed.append((key, value))
    if not changed:
        return url
    return urlunparse(parsed._replace(query=urlencode(fixed)))
