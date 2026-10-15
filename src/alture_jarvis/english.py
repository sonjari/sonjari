"""영어 요청을 읽는 규칙 — 하네스의 영어판 (2026-09-23 밤, 영어판 P1).

## 왜 따로 두나

하네스(계획 층·라우터·스킬 고르기)는 한국어 정규식으로 짜여 있었다. 같은 뜻을 영어로 시키면 요구를 못 뽑았다
(계획 동등성 10/85, 스킬 0/42 — `scripts/measure_language_parity.py`). 요구가 없으면 되받기도, 미달 판정도, 구글 갈래도
안 돈다 — 한국어에서 「라우팅 낱말표 → 78% 창작」으로 겪은 그 모양이 영어 사용자에게 그대로 간다.

## 한 가지 규율: 영어 규칙은 **영어가 주된 요청에만** 건다

한국어 요청에도 영어 낱말이 섞인다(`test`·`post`·`Python`·`index.html`). 영어 규칙을 모든 요청에 걸면 **한국어 판정이
조용히 바뀐다.** 그래서 `english_dominant` 가 참일 때만 여기 규칙을 쓴다 — 한국어 판정 불변이 **구조로** 보장된다.
(바꾼 뒤 `scripts/harness_snapshot.py --compare` 로 실제 요청 1,181개를 재서 확인한다.)

## 옮기는 법

한국어 규칙의 **뜻을 옮긴다. 넓히지 않는다.** 한국어가 좁게 잡는 자리(예: 「사이트 이름을 대고 개수를 말하면 읽기 요구」)를
영어에서만 넓히면 두 언어의 판정이 갈리고, 한쪽 사용자는 다른 제품을 쓰게 된다. 한국어 쪽이 틀렸으면 **한국어를 고친다**
(그리고 스냅샷으로 바뀐 것을 하나하나 본다).

영어는 한국어와 모양이 다르다 — 부정이 **동사 앞**에 오고(「Don't publish」), 수량 뒤에 단위 대신 **명사**가 온다(「3 job posts」).
이 파일은 그 차이만 다룬다.
"""

from __future__ import annotations

import re

# ── 언어 판정 ─────────────────────────────────────────────────────────────────

_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]")


def english_dominant(text: str) -> bool:
    """영어가 주된 요청인가. 한국어 사이트 이름 한둘이 섞인 영어 문장(「Find jobs on 사람인」)도 영어다.

    한글이 **4자 이하**이고 글자의 15% 미만일 때만 참이다. 비율만 보면 「이 저장소에서 테스트가 실패한다: <긴 영어 오류>」처럼
    **지시는 한국어**인데 붙여넣은 영어가 긴 요청이 영어로 잡혀 한국어 판정을 잃는다(실제 요청 1,181개 중 3개가 그랬다).
    영어 문장에 섞이는 한글은 사이트 이름 정도다(사람인 3자·잡코리아 4자).
    """
    hangul = len(_HANGUL.findall(text or ""))
    latin = len(_LATIN.findall(text or ""))
    if latin < 3 or hangul > 4:
        return False
    return hangul < 0.15 * (hangul + latin)


# ── 부정 ─────────────────────────────────────────────────────────────────────
#
# 한국어는 부정이 동사 **뒤**에 온다(「발행하지 마」). 영어는 **앞**이다(「Don't publish」). 그래서 매치 **앞**의 같은 문장만 본다.
# 부정어와 동사 사이에 두 낱말까지 허용한다(「never ever publish」·「do not actually send」). 더 멀면 다른 동사의 부정이다:
# 「Never publish it, only save the draft」에서 save 는 부정이 아니다.
_NEGATION_BEFORE = re.compile(
    r"\b(?:don'?t|do\s+not|never|not|no\s+need\s+to|without|avoid|shouldn'?t|mustn'?t|won'?t|stop|refrain\s+from)"
    r"\s+(?:[\w'’]+\s+){0,2}$",
    re.I,
)


_QUOTED = re.compile(r"[\"“][^\"”]{0,80}[\"”]|(?<![A-Za-z])'[^']{0,80}'(?![A-Za-z])|[‘][^’]{0,80}[’]")


def unquoted(compact: str) -> str:
    """따옴표 안을 지운 문장 — 따옴표 안은 **적을 내용**이지 시키는 말이 아니다(「write 'scope check'」의 check)."""
    # 따옴표 **문자는 남긴다** — 「본문은 '…'」처럼 따옴표가 있다는 사실 자체를 보는 규칙이 있다.
    return _QUOTED.sub(lambda m: m.group(0)[0] + " " * (len(m.group(0)) - 2) + m.group(0)[-1], compact)


def first_unnegated(pattern: re.Pattern[str], compact: str) -> re.Match[str] | None:
    """부정되지 않은 첫 매치 — 「No need to make a file」·「Don't fix anything」의 동사는 시킨 게 아니다."""
    for match in pattern.finditer(compact):
        if not negated_before(compact, match.start()):
            return match
    return None


def negated_before(compact: str, start: int) -> bool:
    """이 자리에서 시작한 표현이 **하지 말라는 말**인가 — 같은 문장 안, 바로 앞만 본다."""
    head = compact[max(0, start - 40) : start]
    for stop in (".", "!", "?", ";", chr(10)):
        cut = head.rfind(stop)
        if cut >= 0:
            head = head[cut + 1 :]
    return bool(_NEGATION_BEFORE.search(head))


# ── 수량 ─────────────────────────────────────────────────────────────────────
#
# 한국어는 수 뒤에 **단위**(개·곳·건·권·명)가 와서 「세는 말」인지가 저절로 갈린다. 영어는 단위가 없고 **명사**가 온다
# (「3 accounting job posts」). 그래서 수 뒤 다섯 낱말 안에서 세는 명사를 찾는다. 못 찾으면 수량이 아니다(「3pm」·「10%」·「2 decimal places」).

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

COUNT = re.compile(
    r"(?<![\w$₩#:/.,-])"
    r"(?P<q1>at\s+least\s+|a\s+minimum\s+of\s+|minimum\s+of\s+|no\s+fewer\s+than\s+)?"
    r"(?P<n>\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"(?![\w,.:%-]\d|[\w%])"
    r"(?P<q2>\s*\+|\s+or\s+more)?",
    re.I,
)

#: 수 **바로 뒤**가 이것이면 개수가 아니라 조건·시각·범위다(한국어 `_CONSTRAINT_UNIT`·범위 표지와 같은 자리).
_CONSTRAINT_NEXT = frozenset({
    "pm", "am", "p.m.", "a.m.", "o'clock", "percent", "%", "year", "years", "month", "months", "week", "weeks",
    "day", "days", "hour", "hours", "hr", "hrs", "minute", "minutes", "min", "mins", "second", "seconds", "sec",
    "secs", "won", "dollar", "dollars", "usd", "krw", "credit", "credits", "decimal", "times", "time", "to",
    "k", "m", "gb", "mb", "kb", "st", "nd", "rd", "th", "stars", "star", "point",
})

#: 읽어야 하는 것 — 한국어 `quantities._SOURCE_NOUN` 의 뜻을 옮겼다(책·앱은 한국어도 안 넣었다: 뜻이 같게).
SOURCE_NOUNS = frozenset({
    "document", "documents", "doc", "docs", "file", "files", "material", "materials", "post", "posts",
    "posting", "postings", "listing", "listings", "opening", "openings", "job", "jobs", "service", "services",
    "project", "projects", "site", "sites", "website", "websites", "homepage", "homepages", "page", "pages",
    "article", "articles", "story", "stories", "paper", "papers", "product", "products", "company", "companies",
    "firm", "firms", "business", "businesses", "vendor", "vendors", "place", "places", "spot", "spots",
    "candidate", "candidates", "result", "results", "link", "links", "video", "videos", "review", "reviews",
    "comment", "comments", "blog", "blogs", "source", "sources", "repo", "repos", "repository", "repositories",
    "commit", "commits", "issue", "issues", "pr", "prs", "recruitment", "recruitments", "vacancy", "vacancies",
})

#: 내놓을 것 — 한국어 `_PRODUCT_NOUN`.
PRODUCT_NOUNS = frozenset({
    "point", "points", "takeaway", "takeaways", "highlight", "highlights", "bullet", "bullets", "section",
    "sections", "heading", "headings", "strength", "strengths", "weakness", "weaknesses", "advantage",
    "advantages", "disadvantage", "disadvantages", "pros", "cons", "bottleneck", "bottlenecks", "reason",
    "reasons", "cause", "causes", "way", "ways", "idea", "ideas", "suggestion", "suggestions", "recommendation",
    "recommendations", "proposal", "proposals", "alternative", "alternatives", "example", "examples",
    "lesson", "lessons", "insight", "insights", "implication", "implications", "summary", "summaries",
    "footnote", "footnotes", "note", "notes", "sentence", "sentences", "line", "lines", "paragraph",
    "paragraphs", "question", "questions", "answer", "answers", "hypothesis", "hypotheses", "scenario",
    "scenarios", "priority", "priorities", "task", "tasks", "to-do", "to-dos", "todo", "todos", "action",
    "actions", "axis", "axes", "criterion", "criteria", "perspective", "perspectives", "angle", "angles",
    "tip", "tips", "principle", "principles", "step", "steps", "rule", "rules",
    # 새 문장 역검증에서 더했다(2026-09-23 밤): 「read report.pdf and tell me the three main risks」의 3 은 읽을 문서 수가 아니다.
    "risk", "risks", "problem", "problems", "concern", "concerns", "benefit", "benefits", "factor", "factors",
    "finding", "findings", "change", "changes", "improvement", "improvements", "mistake", "mistakes",
    "requirement", "requirements", "difference", "differences", "feature", "features", "slide", "slides",
})

#: 수 뒤를 훑다가 여기서 멈춘다 — 이 낱말 너머는 다른 구다.
_NOUN_SCAN_STOP = frozenset({
    "for", "in", "on", "from", "with", "that", "which", "who", "where", "then", "by", "at", "into", "about",
    "per", "each", "if", "when", "than", "and", "is", "are", "was", "were",
})
#: 조건·속성의 단위 — 「within 20 miles」·「for 4 guests」·「2 bedrooms」·「three nights」. 읽을 개수가 아니다.
#: ★ 2026-10-03 Online-Mind2Web 영어 과제 300개를 계획 층에 통과시키자 개수 요구 21개가 **거의 전부** 이런 오독이었다
#:   (「between 12 and 18 minutes」 → 「12개 이상 직접 열어 읽기」 — TED 판이 강연 12개를 채우느라 5배 걸리고 틀렸다).
_MEASURE_NOUNS = frozenset({
    "mile", "miles", "mi", "km", "kilometer", "kilometers", "meter", "meters", "foot", "feet", "ft", "inch", "inches",
    "night", "nights", "bed", "beds", "bedroom", "bedrooms", "bath", "baths", "bathroom", "bathrooms", "room", "rooms",
    "guest", "guests", "adult", "adults", "kid", "kids", "child", "children", "person", "persons", "people", "player",
    "players", "passenger", "passengers", "traveler", "travelers", "traveller", "travellers", "seat", "seats",
    "ticket", "tickets", "syllable", "syllables", "letter", "letters", "pound", "pounds", "lb", "lbs", "kg", "gram",
    "grams", "ounce", "ounces", "oz", "liter", "liters", "gallon", "gallons", "degree", "degrees",
    "door", "doors", "seater", "speed", "speeds", "core", "cores",
})
#: 「a group of 4」·「party of 6」 — 앞말이 인원·크기를 말한다.
_MEASURE_BEFORE = re.compile(r"\b(?:group|party|team|family|size|ages?|aged)\s+(?:of\s+)?$", re.I)
_IRREGULAR_PLURALS = frozenset({"people", "children", "men", "women", "mice", "staff", "data"})
_NOT_PLURAL = frozenset({
    "this", "its", "his", "is", "was", "has", "does", "us", "yes", "plus", "less", "across", "always",
    "perhaps", "as", "whose", "series", "news", "ais", "bus", "gas", "focus", "status", "analysis", "basis",
})
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")

ROLE_INPUT = "input_cardinality"
ROLE_OUTPUT = "output_cardinality"
ROLE_UNKNOWN = "unknown"
#: 개수가 아니라 조건의 크기(거리·시간·인원·방). 순위 말(「the last seven days」)이 앞에 있어도 개수로 살리지 않는다.
ROLE_MEASURE = "measure"


def _looks_plural(word: str) -> bool:
    if word in _IRREGULAR_PLURALS:
        return True
    if "'" in word or "’" in word:  # 소유격(men's)은 복수가 아니다
        return False
    return len(word) >= 3 and word.endswith("s") and word not in _NOT_PLURAL and not word.endswith("ss")


def counted_noun(text: str, end: int) -> tuple[str, str]:
    """수 뒤에서 **세는 명사**와 그 역할을 찾는다. 없으면 ("", "") — 수량이 아니다.

    역할은 한국어 `quantities.quantity_role` 과 같은 셋이다: 읽을 것(input) · 내놓을 것(output) · 모름(unknown).
    """
    tail = text[end : end + 80]
    stripped = tail.lstrip()
    if stripped[:1] in ("%", ":", "-", "/"):
        return ("", "")
    if stripped[:1] in ('"', "″", "”"):  # 27" 모니터 — 인치
        return ("", ROLE_MEASURE)
    words = [m.group(0).casefold().strip("'’") for m in _WORD.finditer(tail.split(".")[0].split(",")[0].split(";")[0])]
    if not words:
        return ("", "")
    if words[0] in _CONSTRAINT_NEXT or words[0] in _MEASURE_NOUNS:
        return ("", ROLE_MEASURE)
    # 「between 12 and 18 minutes」·「2 bed and 3+ bath」 — 범위의 앞 수는 뒤 수와 같은 단위다.
    if words[0] in ("and", "or", "to") and len(words) > 1 and (words[1] in _CONSTRAINT_NEXT or words[1] in _MEASURE_NOUNS):
        return ("", ROLE_MEASURE)
    for index, word in enumerate(words[:6]):
        if index and word in _NOUN_SCAN_STOP:
            break
        if word in _MEASURE_NOUNS:
            return ("", ROLE_MEASURE)
        if word in PRODUCT_NOUNS:
            # 「key points」·「action items」처럼 뒤 낱말이 머리일 수 있다 — 바로 뒤가 명사면 그쪽을 본다.
            nxt = words[index + 1] if index + 1 < len(words) else ""
            if nxt in SOURCE_NOUNS:
                return (nxt, ROLE_INPUT)
            return (word, ROLE_OUTPUT)
        if word in SOURCE_NOUNS:
            nxt = words[index + 1] if index + 1 < len(words) else ""
            if nxt in PRODUCT_NOUNS:
                return (nxt, ROLE_OUTPUT)
            if nxt in SOURCE_NOUNS:
                return (nxt, ROLE_INPUT)
            return (word, ROLE_INPUT)
        if _looks_plural(word):
            return (word, ROLE_UNKNOWN)
    return ("", "")


#: 「the top 3.」처럼 명사를 생략한 수 — 앞말이 순위를 말하면 개수다(한국어 「상위 3권」).
_RANK_BEFORE = re.compile(r"\b(?:top|first|best|last|leading)\s+$", re.I)
#: 상한이다, 최소 요구가 아니다 — 「don't open more than 2 pages」·「at most 3」(한국어 「이하」·「최대」).
_UPPER_BOUND_BEFORE = re.compile(
    r"\b(?:more\s+than|no\s+more\s+than|at\s+most|up\s+to|max(?:imum)?(?:\s+of)?|fewer\s+than|less\s+than|under|below)\s+$",
    re.I,
)


def count_value(token: str) -> int:
    token = token.strip().casefold()
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token, 0)


def counts(compact: str) -> list[tuple[int, bool, str, int, int]]:
    """영어 요청의 수량 전부 — (값, 수식어가 붙었나, 역할, 시작, 끝). 세는 명사가 없는 수는 뺀다."""
    found: list[tuple[int, bool, str, int, int]] = []
    for match in COUNT.finditer(compact):
        value = count_value(match.group("n"))
        if not value:
            continue
        if _UPPER_BOUND_BEFORE.search(compact[max(0, match.start() - 16) : match.start()]):
            continue
        if _MEASURE_BEFORE.search(compact[max(0, match.start() - 16) : match.start()]):
            continue
        noun, role = counted_noun(compact, match.end())
        if role == ROLE_MEASURE:
            continue
        if not noun:
            # 「the top 3.」— 명사가 앞 문장에 있다. 앞말이 순위를 말하면 개수로 본다.
            if not _RANK_BEFORE.search(compact[max(0, match.start() - 12) : match.start()]):
                continue
            role = ROLE_UNKNOWN
        qualified = bool(match.group("q1") or match.group("q2"))
        # 「top 5」·「first 5」는 수식이지만 최소 요구가 아니다 — 한국어 「상위 5개」도 수식어로 안 본다.
        found.append((value, qualified, role, match.start("n"), match.end()))
    return found


# ── 읽기 의도 · 행위 개수 ─────────────────────────────────────────────────────

#: 읽으라는 말. 동사는 **시키는 자리**에서만 센다 — 문장 머리·「and/then/please/to」 뒤·「can you」 뒤.
#: 「…because they check the overlapping parts」의 check 는 서술이지 지시가 아니다(한국어 표도 「확인해」처럼 명령형만 잡는다).
#: 명사(출처·공고·기사)는 한국어 표처럼 자리를 안 가린다.
READ_INTENT = re.compile(
    r"(?:^|[.!?;:,]\s*|\b(?:and|then|please|to|also|first|can\s+you|could\s+you|would\s+you)\s+)"
    r"(?:read|open|visit|go\s+(?:in)?to|check|look|browse|skim|research|investigate|find(?!\s+out)|search|dig|explore)\b"
    r"|\b(?:sources?|original|posts?|postings?|listings?|articles?|stories)\b",
    re.I,
)
ACTION_COUNT = re.compile(
    r"\b(?:scrap|clip|bookmark|save|add|register|sign\s+up|apply|upload|post|send|e-?mail|delete|remove"
    r"|write|create|make|submit|book|reserve)\b",
    re.I,
)
VERB_WINDOW_BEFORE = 20
VERB_WINDOW_AFTER = 25

#: 로컬 자료 / 웹 자료 — 한국어 `_scoped_count_targets` 의 낱말표.
LOCAL_SCOPE_TERMS = ("local", "file", "folder", "document")
#: "local" that is a **kind**, not a place — "5 local LLMs", "local-first apps". Only "local files/folders/…" names a source
#: (2026-10-04: the Korean side misread 「로컬용 모델 5개」 as five local files for the third time — allow-list, not deny-list).
LOCAL_NOT_SOURCE = re.compile(
    r"\blocal(?:ly)?\b(?![\s-]+(?:files?|folders?|documents?|docs?|pdfs?|drives?|disks?|machine|pc|computer|"
    r"director(?:y|ies)|paths?|sources?|data|copy|copies|notes?|spreadsheets?|sheets?))[\w-]*",
    re.IGNORECASE,
)
LOCAL_SCOPE_TERMS_NAMED_WEB = ("local", "file", "folder")
WEB_SCOPE_TERMS = ("public web", "web", "website", "site", "online", "internet")


# ── 행위 요구 ─────────────────────────────────────────────────────────────────
#
# (패턴, 도구, 한국어 이름표) — 한국어 `plan._ACTIONS` 와 **같은 도구·같은 이름표**로 선다. 이름표는 화면에 보이는
# 말이라 P2(사람에게 보이는 말)에서 언어별로 바꾼다 — 여기서 바꾸면 한·영 판정이 갈린다.
ACTIONS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\bsave\b[^.!?\n]{0,24}\bdrafts?\b|\bdrafts?\s+save\b|\bsave\s+to\s+drafts\b", re.I),
     "naver_blog_save_draft", "임시저장"),
    (re.compile(
        r"\b(?:upload|save|put|add|store|copy|move|back\s+up)\b[^.!?\n]{0,40}"
        r"\b(?:to|into|in|on)\s+(?:my\s+|the\s+|our\s+)?(?:google\s+)?drive\b", re.I),
     "google_drive_write", "드라이브에 올리기"),
    # 명사 「publisher」·「publication date」는 행위가 아니다(한국어 「게시자」·「발행일」과 같은 자리).
    (re.compile(r"\bpublish(?!er|ers|ed\s+(?:date|on)|ing\s+date|\s+date)\b|\bpublish(?:ing)?\b(?=\s+(?:it|this|the|them|that))"
                r"|\bpost\s+(?:it|this|that|them)\s+(?:on|to)\b|\bgo\s+live\b", re.I),
     "naver_blog_publish", "발행"),
    (re.compile(r"\b(?:send|shoot)\b[^.!?\n]{0,60}\b(?:e-?mails?|mails?|messages?)\b|\be-?mails?\b[^.!?\n]{0,40}\bsend\b"
                r"|\bsend\b[^.!?\n]{0,40}@|\be-?mail\s+(?:it|this|them|that|the\s+\w+)\s+to\b", re.I),
     "google_gmail_send", "메일 발송"),
    (re.compile(
        r"(?is)(?=.*(?:web\s*page|\bpage\b|\bhtml\b|\bsite\b|web\s*app|landing|front-?end|\bui\b))"
        r".*(?:\b(?:show|open|display|view|check|see)\b[^.!?\n]{0,30}\bpreview\b|\bpreview\s+(?:it|this|the\s+page)\b"
        r"|local_preview_page)"),
     "local_preview_page", "만든 화면 미리보기로 띄우기"),
    (re.compile(r"\b(?:add|create|schedule|book|set\s+up|put|make|register)\b[^.!?\n]{0,40}"
                r"\b(?:event|meeting|appointment|calendar)\b", re.I),
     "google_calendar_create", "일정 등록"),
    (re.compile(r"\b(?:move|reschedule|change|shift|push\s+back|postpone|bring\s+forward|update|edit)\b[^.!?\n]{0,40}"
                r"\b(?:event|meeting|appointment)\b", re.I),
     "google_calendar_update", "일정 수정"),
    (re.compile(r"\b(?:delete|remove|cancel|clear)\b[^.!?\n]{0,40}\b(?:event|meeting|appointment)\b", re.I),
     "google_calendar_delete", "일정 삭제"),
    (re.compile(r"\b(?:click|press|hit)\s+(?:the\s+)?[\"'“]?submit\b|\bsubmit\s+(?:it|the\s+form|the\s+application)\b", re.I),
     "browser_click_confirmed", "폼 제출"),
)

#: 사람이 **적을 내용을 불러준** 표현 — 한국어 `_DICTATED_CONTENT`(「…라고 적어」·「내용은 '…'」).
DICTATED_CONTENT = re.compile(
    r"\b(?:write|type|enter|put)\s+(?:down\s+|in\s+)?[\"'“‘]"
    r"|\b(?:saying|that\s+says|reading)\s*[:：]?\s*[\"'“‘]"
    r"|\b(?:content|text|body)\s*(?:is|should\s+be|[:：])\s*[\"'“‘]",
    re.I,
)


# ── 세는 일(목록 자체가 답) ───────────────────────────────────────────────────

COUNTING_ASK = re.compile(
    r"\bhow\s+many\b(?!\s+(?:hours|minutes|seconds|days|weeks|months|years|won|dollars))"
    r"|\bnumber\s+of\s+(?:results|items|posts|listings|jobs|entries|files|documents|apps|products|hits|matches)\b"
    r"|\bcounts?\s+(?:the|how|all|them)\b"
    r"|\b(?:in|into|as|with)\s+a\s+(?:list|table)\b|\bas\s+a\s+list\b"
    r"|\b(?:just|only)\s+(?:the\s+)?(?:list|titles?|names?|prices?|links?|urls?|addresses)\b"
    r"|\b(?:titles?|names?|prices?|links?)\s+only\b"
    r"|\bwhat\s+(?:[\w'-]+\s+){0,4}(?:are|is|exist)\s+(?:in|inside|on|under)\b",
    re.I,
)
WANTS_DETAIL = re.compile(
    r"\b(?:full\s+text|original\s+text|details?\s+pages?|product\s+pages?|in\s+detail|go\s+into"
    r"|read\s+(?:the\s+)?(?:content|body|details|whole|full)|open\s+(?:each|every|the)\b)",
    re.I,
)


# ── 산출물 · 코드 · 검증 · 셈 ────────────────────────────────────────────────

ARTIFACT_REQUEST_TARGET = re.compile(
    r"\b(?:files?|excel|xlsx|spreadsheets?|sheets?|documents?|docs?|docx|tables?|scripts?|code|reports?"
    r"|images?|csv|hangul|hwpx?|pdf|word\s+(?:documents?|files?|docs?)|powerpoint|pptx?|slides?|decks?)\b",
    re.I,
)
#: 강한 동사 — 대상과 짝이면 산출물이다(한국어 「만들·생성·작성·저장·짜·고쳐·수정·옮기·담아·달아·넣어」).
ARTIFACT_REQUEST_VERB = re.compile(
    r"\b(?:make|create|generate|write|save|export|draft|produce|build|fix|modify|edit|implement|copy|move"
    r"|insert|attach|add|convert|turn\s+(?:it|this|them)\s+into)\b",
    re.I,
)
#: 「정리해줘」류 — **파일 낱말이 있을 때만**, 또는 「문서로」처럼 형식을 댔을 때만 산출물이다.
TIDY_VERB = re.compile(r"\b(?:organi[sz]e|compile|summari[sz]e|tidy|put|list|arrange|sort|write\s+up|put\s+together)\b", re.I)
DOC_FORMAT_REQUEST = re.compile(
    r"\b(?:as|into|in)\s+(?:a|an|one)?\s*(?:[\w-]+\s+)?(?:document|doc|report|write-?up|brief|proposal|deck)\b",
    re.I,
)
REAL_FILE_TARGET = re.compile(
    r"\b(?:files?|excel|xlsx|spreadsheets?|word|docx|hangul|hwpx?|csv|pptx?|powerpoint|images?)\b",
    re.I,
)

CODE_TARGET_WORDS = re.compile(r"\b(?:code|script|function|program)\b", re.I)
CODE_REQUEST_VERB = re.compile(
    r"\b(?:write|implement|build|create|make|generate|fix|modify|edit|refactor|run|code\s+up)\b",
    re.I,
)
#: 언어 이름 **뒤에 붙으면 소재다** — 「Python books」의 대상은 책이다(한국어 `_CODE_TARGET_IS_TOPIC`).
CODE_TARGET_IS_TOPIC = re.compile(
    r"\s*[\"'”’)]?\s*(?:\((?:[^)]{0,20})\)\s*)?(?:programming\s+)?(?:books?|textbooks?|courses?|lectures?|classes|tutorials?"
    r"|materials|jobs?|job\s+posts?|market|developers?|engineers?|experts?|academ(?:y|ies)|tutors?|prices?"
    r"|reviews?|rankings?|lists?"
    # 「the llama.cpp repo」는 읽을 곳이다(한국어 `저장소` 와 같은 고침, 2026-09-28). docs 는 안 넣는다 — 「app.py docs」는 코딩일 수 있다.
    r"|repo|repository|readme|wiki)\b",
    re.I,
)

VERIFY_REQUEST = re.compile(
    r"\b(?:tests?|pytest|unittest)\b[^.!?\n]{0,30}\b(?:pass(?:es|ing)?|succeed|run|green)\b"
    r"|\b(?:pass(?:es|ing)?)\b[^.!?\n]{0,20}\b(?:tests?|pytest|unittest)\b"
    r"|\b(?:re)?run\s+(?:the\s+|all\s+the\s+|all\s+)?(?:[\w-]+\s+)?(?:tests?|pytest)\b"
    r"|\bactually\s+(?:run|execute)|\brun\s+(?:it|the\s+file|the\s+script)\s+(?:and|to)\s+(?:verify|check|confirm)"
    r"|\bverify\s+(?:that\s+)?(?:it|the\s+output)\b|\bmake\s+(?:it|them)\s+(?:work|run)\b|\bwithout\s+errors\b",
    re.I,
)

ARITHMETIC_TARGET = re.compile(
    r"\b(?:primes?|prime\s+numbers?|divisors?|multiples?|gcd|lcm|greatest\s+common|least\s+common|combinations"
    r"|permutations|probability|statistics|average|mean|weighted|median|standard\s+deviation|sum|total|profit"
    r"|how\s+many|ratio|percent(?:age)?|grades?|scores?|discount|interest|compound|calculator)\b|%",
    re.I,
)
COMPUTE_VERB = re.compile(
    r"\b(?:make|create|generate|calculate|compute|work\s+out|figure\s+out|run|save|output|print|answer|solve"
    r"|how\s+much|tally|organi[sz]e|put|tabulate)\b",
    re.I,
)
ARTIFACT_TARGET = re.compile(
    r"\b(?:excel|xlsx|spreadsheets?|csv|word\s+file|docx|document\s+file|graph|chart|plot|simulation"
    r"|as\s+a\s+file|(?:in|into|as)\s+a\s+table)\b",
    re.I,
)

#: 이름이 붙은 파일 **앞**이 이것이면 그 파일은 만들 것이 아니라 읽을 재료다 — 「Read INSTRUCTIONS.md and implement …」.
#: 한국어 `plan._NAMED_FILE_IS_READ`(「…md 를 읽고」)와 같은 판정이고, 영어는 읽는 말이 앞에 온다 (2026-10-13).
#: 「in tidy.py」 · 「from app.py」는 넣지 않는다 — 고칠 파일을 가리키는 말이기도 하다.
NAMED_FILE_IS_READ_BEFORE = re.compile(r"\b(?:read|reading|open|look\s+at|parse|load|based\s+on|according\s+to)\s+(?:the\s+)?(?:file\s+)?$", re.I)


#: 형식 → 확장자. 한국어 `_artifact_extensions` 의 규칙 순서를 그대로 따른다.
EXTENSION_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\b(?:excel|spreadsheets?)\b", re.I), (".xlsx",)),
    (re.compile(r"(?<![A-Za-z])csv(?![A-Za-z])", re.I), (".csv",)),
    (re.compile(r"\bWord\b|\bword\s+(?:doc|docs|document|documents|file|files)\b"), (".docx",)),
    (re.compile(r"(?<![A-Za-z])pptx?(?![A-Za-z])|\bpowerpoint\b|\bslides?\b|\bdecks?\b|\bpresentation\b", re.I), (".pptx",)),
    (re.compile(r"\bhangul\b|(?<![A-Za-z])hwpx?(?![A-Za-z])", re.I), (".hwpx", ".hwp")),
    (re.compile(r"\bmarkdown\b|(?<![A-Za-z.])md(?![A-Za-z])", re.I), (".md",)),
    (re.compile(r"\bpython\b", re.I), (".py",)),
    (re.compile(r"\btypescript\b", re.I), (".ts", ".tsx")),
    (re.compile(r"\bjavascript\b", re.I), (".js", ".jsx")),
    (re.compile(r"\bimages?\b", re.I), (".png", ".jpg", ".jpeg", ".webp")),
)
TOPIC_PRONE_LANGUAGES = frozenset({"python", "typescript", "javascript"})


# ── 쓰기 금지 ─────────────────────────────────────────────────────────────────
#
# 한국어 `write_prohibition_scope` 와 같은 세 값을 낸다: "" · "clause"(지목한 대상만) · "job"(판 전체가 조사 전용).
# 「Don't modify the test file」은 대상 금지(clause), 「Don't create any files」·「research only」는 판 전체(job).
JOB_WIDE_PROHIBITION = re.compile(
    r"\b(?:research|analy[sz]e|review|investigate)\s+only\b"
    # ★ `only read …` 에도 `just` 와 같은 예외를 둔다 (2026-10-08 전수조사 3-6). 「Only read the top 3 results and make an
    #   Excel file」이 판 전체 읽기 전용이 됐다 — 뒤에 대상이 오면 「그것만 읽어라」지 「아무것도 쓰지 마라」가 아니다.
    r"|\bonly\s+(?:research|analy[sz]e|review|investigate|read)\b(?!\s+(?:it|the|this|that|these|those|and|\d))"
    r"|\bjust\s+(?:research|analy[sz]e|review|read)\b(?!\s+(?:it|the|this|that|and))"
    r"|\bread[ -]?only\b"
    r"|\b(?:don'?t|do\s+not|never)\s+(?:write|modify|edit|create|make|save)\s+(?:any|a|an)\s+(?:files?|documents?)\b"
    r"|\b(?:don'?t|do\s+not|never)\s+(?:write|modify|edit|create|make|save)\s+(?:files?|documents?|anything)\b",
    re.I,
)
CLAUSE_PROHIBITION = re.compile(
    r"\b(?:don'?t|do\s+not|never|without)\s+(?:modify(?:ing)?|edit(?:ing)?|chang(?:e|ing)|touch(?:ing)?|delet(?:e|ing)"
    r"|overwrit(?:e|ing))\b[^.!?\n]{0,40}\b(?:files?|tests?|documents?)\b",
    re.I,
)


#: 금지 바로 뒤에 **건드려도 되는 것을 남겨 두는 말** — 「any files other than these three」·「anything except app.py」.
#: 한국어 `_COMPLEMENT_QUALIFIER`(「○○ 밖의 파일은 건드리지 마라」)의 짝이다(같은 날 한국어 쪽에서 실제로 난 사고).
_COMPLEMENT_AFTER = re.compile(r"^\s*(?:other\s+than|except(?:\s+for)?|besides|apart\s+from|outside(?:\s+of)?|but\s+(?:the|this|these|those))\b", re.I)


def write_prohibition_scope(compact: str) -> str:
    for match in JOB_WIDE_PROHIBITION.finditer(compact):
        if _COMPLEMENT_AFTER.match(compact[match.end():]):
            continue  # 「… other than X」 — X 는 고치라는 판이다
        return "job"
    if JOB_WIDE_PROHIBITION.search(compact):
        return "clause"
    if CLAUSE_PROHIBITION.search(compact):
        return "clause"
    return ""


# ── 그 밖의 판정 ──────────────────────────────────────────────────────────────

TASK_REQUEST = re.compile(
    r"\b(?:find|look\s+up|look\s+into|research|search|read|open|check|review|organi[sz]e|make|create|generate|write"
    r"|draft|compile|calculate|send|upload|post|publish|register|book|schedule|add|please|can\s+you|could\s+you"
    r"|would\s+you|pick|choose|compare|recommend|analy[sz]e|summari[sz]e|translate|fix|build|implement|run|start"
    r"|go\s+ahead|proceed|list|tell\s+me|show\s+me|give\s+me|put|save|advise|suggest|help|explain|judge|evaluate"
    r"|assess|decide|plan|propose)\b",
    re.I,
)
CONTINUATION = re.compile(
    r"\b(?:as\s+you\s+(?:suggested|said|proposed)|like\s+you\s+said|go\s+ahead|continue|keep\s+going|carry\s+on"
    r"|the\s+rest|all\s+of\s+(?:it|them)|do\s+it|same\s+as\s+before|like\s+before)\b",
    re.I,
)
#: 맞장구로 **시작하는** 말 — "Yes, do that" · "Sure". 글 머리에서만 본다(한국어 `plan._ASSENT_LEAD` 의 짝).
#: ★ 2026-10-08: 예전에는 yes·ok·sure 가 글 어디에 있든 이어짓기였다 — "That looks okay to me, thanks" 같은 소감에
#:   앞 요청이 통째로 붙는다(같은 날 한국어 쪽에서 「…왜이렇게 좋아…」로 실제로 난 사고와 같은 모양).
ASSENT_LEAD = re.compile(r"^(?:yes|yeah|yep|ok(?:ay)?|sure|sounds\s+good|alright|all\s+right)\b[\s,.!]*", re.I)
#: 맞장구 뒤에 이만큼까지는 "Yes, that one" 같은 짧은 지목으로 본다. 넘으면 시키는 말이 있어야 한다.
ASSENT_TAIL_MAX_CHARS = 16


def is_continuation(compact: str) -> bool:
    """이 영어 문장이 **앞 말에 기대는 지시**인가(길이 상한은 부르는 쪽이 본다)."""
    if CONTINUATION.search(compact):
        return True
    lead = ASSENT_LEAD.match(compact)
    if not lead:
        return False
    tail = compact[lead.end():].strip()
    return len(tail) <= ASSENT_TAIL_MAX_CHARS or bool(TASK_REQUEST.search(tail))
#: 개수 **바로 앞에** 요청 동사가 있는가 — "find 5 posts"·"pick the best 3"·"read at least 4". 한국어 `plan._ASKED_DIRECTLY` 의 짝.
#: 조건절의 개수("that have 10 or more reviews")는 앞에 다른 말이 있어 안 걸린다 (2026-10-04).
ASKED_DIRECTLY = re.compile(
    r"\b(?:find|list|pick|choose|select|read|compare|get|show|give\s+me|gather|collect|summari[sz]e|recommend|open|check|name|tell\s+me)"
    r"\s+(?:me\s+)?(?:the\s+)?(?:top\s+|best\s+|first\s+|latest\s+|newest\s+)?(?:at\s+least\s+|exactly\s+|up\s+to\s+)?$",
    re.I,
)
FOOTNOTE_REQUEST = re.compile(r"\bfoot\s*notes?\b|\bannotat(?:e|ions?)\b", re.I)
EVERYWHERE = re.compile(r"\b(?:everywhere|wherever|each|every|all|throughout|multiple|several)\b", re.I)

SOCIAL_REMARK = re.compile(
    r"\b(?:thanks|thank\s+you|thx|great\s+job|nice\s+work|good\s+job|well\s+done|awesome|love\s+it|perfect"
    r"|you'?re\s+the\s+best|amazing)\b",
    re.I,
)
ENDS_AS_REQUEST = re.compile(
    r"(?:\?|\b(?:please|can\s+you|could\s+you|now|next)\b[^.!]*$|\b(?:do|make|find|send|write|check|show|tell)\b[^.!]*$)",
    re.I,
)


# ── 출처를 댔나 · 가서 봐야 아는 값인가 ───────────────────────────────────────

NAMED_SOURCE = re.compile(
    # 「in Google Drive」도 출처다(한국어 「드라이브에서」). in 은 대문자 이름 앞에서만 걸린다 — 「in the folder」는 아니다.
    r"\b(?i:on|from|at|in)\s+(?i:the\s+|both\s+|my\s+)?"
    r"(?P<name>[A-Z][A-Za-z0-9]+(?:\s+(?:[A-Z][A-Za-z0-9]+|News|Blog|Store))?|[a-z0-9-]+\.(?:com|co\.kr|kr|net|org|io|ai))"
)
NAMED_SOURCE_ENTERED = re.compile(
    r"\b(?i:go\s+(?:in)?to|visit|open|browse|search|check)\s+(?i:the\s+)?"
    r"(?P<name>[A-Z][A-Za-z0-9]+(?:\s+(?:[A-Z][A-Za-z0-9]+|News|Blog|Store))?|[a-z0-9-]+\.(?:com|co\.kr|kr|net|org|io|ai))"
)
#: 대문자로 시작해도 출처가 아닌 말 — 한국어 `_NOT_A_SOURCE` 의 영어판.
NOT_A_SOURCE = frozenset({
    "I", "A", "An", "The", "This", "That", "My", "Our", "Your", "It", "AI", "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday", "Sunday", "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December", "Excel", "Word", "Markdown", "CSV", "PDF",
    "Hangul", "Windows", "Desktop", "Documents", "Downloads", "Python", "JavaScript", "TypeScript", "Make",
    "Find", "Search", "Open", "Check", "Tell", "Please",
})
PARTICULAR_REQUEST = re.compile(
    r"\bprices?\b|\bcosts?\b|\bhow\s+much\b|\btitles?\b|\blist\b|\branking\b|\btop\s+\d|\breviews?\b|\bratings?\b"
    r"|\bin\s+stock\b|\blistings?\b|\bspecs?\b|\bjob\s+posts?\b|\bpostings?\b|\bdeadlines?\b|\bbudgets?\b"
    r"|\bwhere\s+(?:is|can|do|to)\b|\bwhich\s+(?:menu|tab|page|screen)\b|\bhow\s+many\b",
    re.I,
)


def named_sources(compact: str) -> list[str]:
    seen: list[str] = []
    for pattern in (NAMED_SOURCE, NAMED_SOURCE_ENTERED):
        for match in pattern.finditer(compact):
            name = match.group("name").strip()
            first = name.split()[0]
            if first in NOT_A_SOURCE or len(name) < 2:
                continue
            # 블로그는 **쓰는 곳**이지 읽는 출처가 아니다 — 「on the Robometafit blog」·「on Naver Blog」
            # (한국어 「블로그에」도 출처로 안 센다).
            if name.casefold().endswith(" blog") or compact[match.end() : match.end() + 6].casefold().startswith(" blog"):
                continue
            if name not in seen:
                seen.append(name)
    return seen


# ── 라우터 낱말표 (runtime) ───────────────────────────────────────────────────
#
# 한국어 표와 같은 뜻, 같은 규칙: 강한 조사 동사면 조사다 · 도구 이름을 부르면 조사다 · 약한 동사는 「내 컴퓨터」를 안 가리킬 때만.

WEB_RESEARCH_VERBS = re.compile(
    r"\b(?:research|google\s+(?:it|this|that|for)|search\s+(?:the\s+web|online|the\s+internet|google|naver)"
    r"|web\s+search|internet\s+search|look\s+(?:it|this|that)\s+up\s+online|investigate)\b",
    re.I,
)
WEB_RESEARCH_NAMED_TOOLS = re.compile(
    r"\b(?:browser|internet|on\s+the\s+web|online|on\s+google|on\s+naver(?!\s+blog)|web\s+search)\b",
    re.I,
)
WEB_RESEARCH_SOFT_VERBS = re.compile(
    r"\b(?:search|find|look\s+up|look\s+into|look\s+for|check\s+out|dig|figure\s+out|find\s+out|explore)\b",
    re.I,
)
#: 「내 컴퓨터 안」 — 한국어 표는 맨 「파일」도 안쪽으로 보지만, 영어의 「an Excel file」·「Don't make a file」은 **내놓을 형식**이다.
#: 그래서 지시어가 붙은 파일·폴더와 경로·파일 이름만 안쪽으로 본다.
WEB_RESEARCH_INSIDE = re.compile(
    r"\b(?:my|this|that|these|those|the|local)\s+(?:files?|folders?)\b|\bfolders?\b|\bdesktop\b|\bmy\s+computer\b"
    r"|\bthis\s+computer\b|\bdownloads\b|\bdirector(?:y|ies)\b|\bdrive\b",
    re.I,
)
WEB_RESEARCH_REFUSALS = re.compile(
    r"\b(?:don'?t|do\s+not|no\s+need\s+to)\s+(?:search|look\s+(?:it\s+)?up|google|research)\b|\bwithout\s+searching\b"
    # 「just answer with the result」는 결과만 달라는 말이지 찾지 말라는 말이 아니다 — 「기억으로·바로」가 붙을 때만 거절이다.
    r"|\bfrom\s+memory\b|\bwhat\s+you\s+(?:already\s+)?know\b|\bjust\s+answer\s+(?:from\s+memory|directly|right\s+away)\b"
    r"|\banswer\s+directly\b",
    re.I,
)
LOCAL_SOURCE_PHRASES = re.compile(
    r"\b(?:this|that|the|our)\s+(?:folder|directory|project|repo|repository|codebase|file)\b|\bfolder\s+structure\b"
    r"|\bsource\s+code\b|\bcodebase\b|\bour\s+code\b|\byour\s+code\b|\bour\s+system\b",
    re.I,
)
LOCAL_INSPECTION_VERBS = re.compile(
    r"\b(?:analy[sz]e|look\s+at|go\s+through|review|summari[sz]e|check|read|figure\s+out|evaluate|assess|tell\s+me"
    r"|what'?s\s+in|what\s+is\s+in|list|count|how\s+many|open|show|find|explain)\b",
    re.I,
)
NAVER_BLOG_SUBJECT = re.compile(r"\bnaver\s+blog\b|\bblog\b|\bblog\s+post\b", re.I)
NAVER_BLOG_ACTION = re.compile(
    r"\b(?:post|write|publish|draft|save|upload|fill|register|put\s+up)\b",
    re.I,
)

#: 사람이 부르는 영문 사이트 이름 → 호스트 (한국어 `site_atlas.SEED` 의 짝).
SITE_NAMES: dict[str, str] = {
    "Wishket": "wishket.com",
    "Kmong": "kmong.com",
    "Freemoa": "freemoa.net",
    "Saramin": "saramin.co.kr",
    "JobKorea": "jobkorea.co.kr",
    "Job Korea": "jobkorea.co.kr",
    "Naver Blog": "blog.naver.com",
    "Naver": "naver.com",
    "GitHub": "github.com",
    "Notion": "notion.so",
    "Yanolja": "yanolja.com",
    # 씨앗(site_atlas.SEED)과 짝 — 2026-09-24 새 PC 가 몰랐던 가게 넷
    "Danawa": "danawa.com",
    "Coupang": "coupang.com",
    "11st": "11st.co.kr",
    "Gmarket": "gmarket.co.kr",
    "Kyobo": "kyobobook.co.kr",
    "Kyobo Book": "kyobobook.co.kr",
    "Musinsa": "musinsa.com",
    "Yeogi": "yeogi.com",
    "Yeogieottae": "yeogi.com",
    # 씨앗(site_atlas.SEED)과 짝 — 2026-10-08 경험으로 배운 한글 이름 여섯
    "Aladin": "aladin.co.kr",
    "Enuri": "enuri.com",
    "Ohouse": "ohou.se",
    "Olive Young": "oliveyoung.co.kr",
    "Wikipedia": "wikipedia.org",
    "Career Net": "career.go.kr",
    # ★ 씨앗(`site_atlas.SEED`)에 있는데 영어 이름이 없던 셋 (2026-10-09). 없으면 영어 요청에서 그 사이트를 못 알아본다.
    #   손자리가 우리 숙제로 찾아 넣었고(판 hw4 — 빠진 셋을 정확히 찾고 시험까지 붙였다) 검토해 옮겼다.
    #   짝이 어긋나면 `tests/test_a_seed_site_always_has_an_english_name.py` 가 잡는다.
    "YES24": "yes24.com",
    "Reddit": "reddit.com",
    # 대학알리미. 그 사이트 영문판의 이름은 「Higher Education in Korea」다(손자리가 영문판을 열어 확인했다고 보고).
    # 그 이름은 **표에 넣지 않는다** — 이 표는 문장 어디에든 그 글자가 있으면 사이트를 지목한 것으로 읽는데(`plan.extract`),
    # 그것은 일반 문구라 「한국의 고등교육 동향을 정리해 줘」 같은 요청까지 이 사이트로 묶는다. 주소에서 딴 이름을 쓴다.
    "Academyinfo": "academyinfo.go.kr",
}
