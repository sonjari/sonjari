"""「없다 · 아직 없다」는 **본 범위 안의 말**이다 — 답이 그 범위를 안 적었으면 걸음 기록에서 옮겨 붙인다 (2026-10-19).

★ 2026-10-19 판 1bc39285. 「Show GN 에 AI · 로컬 모델 글이 많던데(memopro · HeyMoa · AIPath · 시그렌즈) 알아봐 줘」에 손자리는
  `news.hada.io/show` 첫 화면을 읽고, 거기서 글 넷(점수 1~2점)을 골라 연 뒤 이렇게 끝맺었다:

      Show GN에서 "로컬 모델로 일하는 에이전트"는 아직 없었습니다. 손자리가 그 자리에 있습니다.

  목록 **한 쪽**과 글 **몇 개**로 「(그런 것은) 아직 없다」를 말했다. 범위를 붙이는 규칙(`agent._list_scope_fact`, 10-02 K-Startup
  분업 실험)은 이미 있었는데 이 답에는 안 붙었다. 까닭이 둘이었다:
    1. 단정 꼴이 「목록 · 검색 결과 · 공고 · 결과 · 제목」 낱말을 요구했다 — 「Show GN에서 …는 아직 없었습니다」에는 그 낱말이 없다.
    2. 범위를 **검색 도구**(`browser_search` · `browser_site_search`)의 검색어 · 건수로만 만들었다 — 이 판은 목록 주소를 직접 열었다.
  두 곳 다 낱말 · 도구 이름으로 「목록」을 알아보던 자리다. 이제 범위는 **걸음이 남긴 모양**으로 정한다:
  `plan.pages_results_were_opened_from`(검색 도구가 도착한 화면 · `listing` 칸 · 쪽만 넘긴 목록 · 링크를 모아 글을 고른 목록)과,
  그 목록 밖에서 실제로 읽은 글의 수.

원칙은 `_list_end_fact` · `_list_scope_fact` 와 같다 — **거짓을 찾지 않고 참인 범위를 붙인다.** 틀려 봐야 참인 한 줄이 붙는다.
그래도 헛붙임은 줄인다(운영 답 3,587개 대조에서 걸러 낸 것):
  - 목록을 하나도 안 본 판(글 한 장을 읽고 「무료 요금제는 없었다」)은 그 글이 범위의 전부라 붙이지 않는다.
  - 목록 끝까지 본 판(더 불러오기가 안 늘었다) · 검색이 0건만 돌려준 판은 「없다」가 본 그대로라 붙이지 않는다.
  - 답이 스스로 범위를 적었으면(「글 4개 중에는」 · 「첫 화면에서는」 · 「읽은 범위 안에서」) 붙이지 않는다.
  - 따옴표 안의 「없습니다」는 페이지 글을 옮겨 적은 것이라 안 본다(「"아직 작성된 리뷰가 없어요"로 나타났습니다」).
  - 내 PC 의 폴더 · 파일만 본 판(「파일이 없습니다」)은 웹 목록이 없으니 여기 안 걸린다.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from . import english as _english
from .plan import pages_results_were_opened_from

#: 「…가 없다」를 **단정**하는 꼴. 낱말로 거짓을 잡으려는 것이 아니라 범위를 붙일 자리를 찾는다.
#:   - 「아직 없었습니다」 · 「아직 나오지 않았다」 — 있을 법한 것이 **아직** 없다는 결론(이 판).
#:   - 「하나도 · 한 건도 · 아무 글도 없었다」 — 다 봤다는 투의 결론.
#:   - 「존재하지 않았다」.
#: 서술어로 끝난 말만 받는다 — 「아직 검증 없음」 · 「생태계 없음」 같은 이름꼴 소제목은 결론이 아니다.
#: ※ 「목록 · 공고 … 없었다」(10-02 의 옛 꼴)는 여기 넣지 않았다 — 검색 도구가 없는 판까지 넓혀 봤더니 운영 답에서 새로 붙은 넷이
#:   전부 헛붙임이었다(「공고, 별도 마감일 없음」 · 「목록에 없는 값: 없음」 · 「요건을 추출할 수 없었습니다」). 그 꼴은 검색 범위가
#:   있을 때 옛 자리(`agent._list_scope_fact`)가 그대로 맡는다.
_NOT_THERE = re.compile(
    r"아직[^.\n]{0,16}?(?:없(?:었습니다|었다|었어요|습니다|어요|다)(?![가-힣])|존재하지\s*않|나오지\s*않|안\s*나왔|올라오지\s*않)"
    r"|(?:하나도|한\s*(?:개|건|곳|편|군데|명)도|아무\s*(?:것|글|곳|제품|공고)도)\s*"
    r"(?:없(?:었|습니다|어요|다)|안\s*보|보이지\s*않|찾지\s*못|찾을\s*수\s*없)"
    r"|존재하지\s*않(?:았|습니다|는다|아요)"
)
_NOT_THERE_EN = re.compile(
    r"(?i)\b(?:there\s+(?:is|are|was|were)\s+(?:still\s+)?no\b|(?:is|are|was|were)\s+not\s+(?:yet\s+)?(?:any|listed|found)\b"
    r"|none\s+of\s+the\s+(?:posts|results|listings|items)|no\s+(?:posts?|results?|listings?|items?)\s+(?:mention|match|were|was))"
)
#: 답이 **스스로 범위를 적은** 꼴 — 그러면 붙이지 않는다(같은 말을 두 번 하지 않는다).
_SCOPE_SAID = re.compile(
    r"\d+\s*(?:개|건|곳|쪽|페이지|편|군데)\s*(?:중|에서|가운데|안|만|을\s*(?:보|읽|열))"
    r"|(?:본|읽은|확인한|살펴본|훑은|열어\s*본)\s*(?:범위|글|목록|페이지|화면|것)\s*(?:안|중|에서|에는|에선|으로는|로는|만)"
    r"|(?:첫|1)\s*(?:쪽|페이지|화면)|(?:목록|결과|화면)\s*(?:내|안)에서?|상위\s*\d+|범위\s*안"
    r"|(?i:\b(?:of|among)\s+the\s+\d+|\bfirst\s+page\b|\bin\s+what\s+I\s+(?:read|saw)\b)"
)
#: 한 문장 — 마침표 · 표 칸에서 끊는다(줄은 미리 나눈다).
_SENTENCE = re.compile(r"[^.!?|]+[.!?]?")
#: 따옴표 — 그 안의 「없습니다」는 페이지 글을 옮겨 적은 것이다.
_QUOTE_PAIRS = {"“": "”", "‘": "’", "「": "」", "『": "』"}
_QUOTE_SAME = ('"',)


def _key(url: str) -> str:
    key = re.sub(r"^https?://", "", str(url or "").strip()).split("#", 1)[0].rstrip("/")
    host, _, rest = key.partition("/")
    return host.lower() + ("/" + rest if rest else "")


def _short(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.")
    path = parsed.path.rstrip("/")
    return (host + path)[:48] or url[:48]


def _inside_quotes(text: str, at: int, *, english: bool = False) -> bool:
    """`text[at]` 이 따옴표 안인가 — 여는 짝이 닫히지 않았거나, 곧은 따옴표가 앞에 홀수 개.

    홑따옴표(')는 한국어 답에서만 센다 — 영어의 「don't」 · 「Apple's」가 따옴표로 세어지면 뒤 문장이 다 따옴표 안이 된다.
    """
    before = text[:at]
    if any(before.count(mark) % 2 for mark in (_QUOTE_SAME if english else (*_QUOTE_SAME, "'"))):
        return True
    return any(before.rfind(open_) > before.rfind(close) for open_, close in _QUOTE_PAIRS.items())


def denied_sentence(answer: str) -> str:
    """답에서 「없다」를 단정하고 **범위는 안 적은** 첫 문장. 없으면 빈 문자열."""
    text = answer or ""
    english = _english.english_dominant(text)
    pattern = _NOT_THERE_EN if english else _NOT_THERE
    # 따옴표는 줄 단위로 본다 — 마침표가 따옴표 안에서 문장을 끊어도(「"아직 리뷰가 없습니다." — 」) 여는 따옴표를 놓치지 않게.
    for line in text.splitlines():
        for found in _SENTENCE.finditer(line):
            claim = pattern.search(found.group(0))
            sentence = found.group(0).strip()
            if not claim or _SCOPE_SAID.search(sentence) or _inside_quotes(line, found.start() + claim.start(), english=english):
                continue
            return sentence
    return ""


def absence_scope_note(answer: str, steps: list[dict[str, Any]], sources: list[str]) -> str:
    """답이 「없다 · 아직 없다」를 범위 없이 단정했고, 그 판이 **목록에서 고른 일부**만 봤으면 본 범위를 한 줄로 붙인다.

    `sources` — 본문을 실제로 받아 온 주소(`agent.BrowserAgent._sources_actually_read`). 목록 화면은 거기서 뺀 것이 「연 글」이다.
    """
    if not denied_sentence(answer):
        return ""
    if any(
        isinstance(step.get("evidence"), dict) and step["evidence"].get("grew") is False
        for step in steps or () if str(step.get("tool") or "") == "browser_load_more"
    ):
        return ""                                   # 목록 끝까지 봤다 — 「없다」가 본 그대로다
    lists = {_key(url): url for url in pages_results_were_opened_from(steps)}
    searches: list[tuple[str, int]] = []
    for step in steps or ():
        evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
        if not step.get("ok") or not evidence:
            continue
        if str(step.get("tool") or "") in {"browser_search", "browser_site_search"}:
            query = str(evidence.get("query") or (step.get("arguments") or {}).get("query") or "").strip()
            count = evidence.get("result_count")
            item = (query, count if isinstance(count, int) else -1)
            if query and item not in searches:
                searches.append(item)
            if evidence.get("url"):
                lists.pop(_key(str(evidence["url"])), None)   # 검색 화면은 검색어로 적는다
    if not lists and not searches:
        return ""                                   # 목록을 안 봤다 — 읽은 글이 범위의 전부다
    if searches and not lists and all(count == 0 for _query, count in searches):
        return ""                                   # 검색이 0건만 돌려줬다 — 「없다」가 본 그대로다
    read_items = {_key(source) for source in sources or () if source.startswith(("http://", "https://"))} - set(lists)
    screens = len(searches) + len(lists)
    if _english.english_dominant(answer or ""):
        places = [f"search “{query}” ({count} results)" if count >= 0 else f"search “{query}”" for query, count in searches[:4]]
        places += [_short(url) for url in list(lists.values())[:4]]
        return (
            f"\n\nℹ Tool log: “there is none / not yet” applies only to what Sonjari saw — {screens} list screen(s) "
            f"({', '.join(places)}) and {len(read_items)} page(s) opened from them. Other pages and other posts were not looked at."
        )
    places = [f"「{query}」 {count}건" if count >= 0 else f"「{query}」" for query, count in searches[:4]]
    places += [_short(url) for url in list(lists.values())[:4]]
    return (
        f"\n\nℹ 도구 기록: 「없다 · 아직 없다」는 손자리가 본 범위 안의 말입니다 — 목록 화면 {screens}곳"
        f"({' · '.join(places)})과 거기서 연 글 {len(read_items)}개. 그 밖의 쪽 · 글은 보지 않았습니다."
    )
