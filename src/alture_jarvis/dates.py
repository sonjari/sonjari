"""요청한 날짜를 **코드가** 읽고, 주소의 날짜 인자를 **코드가** 갈아 끼운다.

## 왜 이 파일이 있는가 (2026-09-04 실측)

사용자가 「야놀자에 들어가서 이번 주 토요일 1박으로 밀양 숙소를 찾아줘」라고 했다.
자비스는 야놀자에 잘 들어갔고, 목록도 잘 받았고, 상세 두 곳을 실제로 열어 읽었다.
답도 냈다 — **9월 4일 밤의 가격으로.**

    열린 주소 …/stay/domestic/3011753?adultCount=2
                &checkInDate=2026-09-04&checkOutDate=2026-09-05

    9/4 체크인 → 숙박 50,000원~
    9/5 체크인 → 숙박 60,000원~      ← 하루 차이로 20%

증거 원장은 이걸 못 잡는다. **가격은 진짜로 읽은 값이니까.** 틀린 것은 읽은 값이
아니라 **어느 밤을 열었는가**다. 같은 판에서 어뮤즈는 9/5 에 예약마감이었다 —
즉 "있다"고 답한 숙소가 실제로는 못 자는 곳이었다.

날짜를 **명시해서** 다시 시켰더니 이번엔 달력 위젯을 32번 두드리다 673초에 예산이
끝났다(잡 `3b5f3a76`). QA 세계의 정설이 한 줄로 있다 — **「달력을 누르지 마라.
값을 직접 넣어라.」** 문(門)은 URL 인자다.

## 왜 안내문이 아니라 코드인가

이 저장소가 여러 번 배운 것이다(사고 R). 「날짜를 URL 로 바꿔라」라고 프롬프트에
적으면 **안 한다.** 실측으로 셋을 확인한 날이 있다 — 검색 주소 손조립 금지 안내를
받고도 12건이 손으로 조립했고, "스크롤해라"는 6%만 따랐고, "N개는 열어 읽어라"는
165번 열고 스크롤은 1번이었다. 결정론으로 박을 수 있는 것은 코드로 옮긴다.

그리고 「이번 주 토요일」을 모델이 더하면 **틀린다.** 2026-09-04(금)에 물었더니
9/6~9/7 이라고 답했다(맞는 값 9/5~9/6). 요일 계산을 금지한 것과 똑같은 병이 한 칸
옆에서 난 것이라, 여기서도 계산은 코드가 한다.

## 안전 쪽 원칙

- **못 읽으면 아무것도 안 한다.** 날짜를 못 뽑았거나 인자 짝을 확신 못 하면 원래
  주소 그대로 연다. 이 파일이 하는 일은 전부 "확신할 때만".
- **원래 형식을 지킨다.** `2026-09-05`·`20260905`·`2026.09.05` 를 섞지 않는다.
- **길이를 지킨다.** 체크아웃을 못 읽었으면 원래 주소의 숙박 일수를 그대로 옮긴다.
- **키를 추측하지 않는다.** 이름만 보고 고르지 않고 **값이 날짜 모양인 것**만
  후보로 삼는다. 원장 등록에서 배운 것과 같다 — 추측한 키는 조용히 무동작이 된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .clock import KST, WEEKDAYS_KO

# ─────────────────────────────────────────────────────────────────────────────
# 1. 요청문에서 날짜 읽기
# ─────────────────────────────────────────────────────────────────────────────

# 「2026-09-05」·「2026.09.05」·「2026/09/05」. 연도를 요구하는 것은 일부러다 —
# 연도 없는 `9/5` 는 아래에서 따로 본다(가격·비율과 헷갈리기 쉬워 조건이 다르다).
_ISO = re.compile(r"(?<![0-9])(20[2-9][0-9])[-./](0?[1-9]|1[0-2])[-./](0?[1-9]|[12][0-9]|3[01])(?![0-9])")

# 「9월 5일」·「9월5일」
_KO_MD = re.compile(r"(?<![0-9])(0?[1-9]|1[0-2])\s*월\s*(0?[1-9]|[12][0-9]|3[01])\s*일")

# 「1박」·「2박 3일」. 숙박 일수 → 체크아웃을 만든다.
_NIGHTS = re.compile(r"(?<![0-9])([1-9])\s*박")

# 「내일」·「모레」류. 낱말 하나가 곧 날짜인 것들.
_OFFSET_WORDS = {"오늘": 0, "오늘밤": 0, "금일": 0, "내일": 1, "낼": 1, "명일": 1, "모레": 2, "글피": 3}
_OFFSET_RE = re.compile("|".join(sorted(_OFFSET_WORDS, key=len, reverse=True)))

# 「이번 주 토요일」·「다음주 금요일」·「이번 주말」.
#
# ★ 「이번 주 X요일」의 뜻을 **다가오는 그 요일**로 잡는다. 달력상 이번 주가
#   지났으면(월요일에 「이번 주 일요일」) 그 주의 일요일이 맞지만, 사람이 숙소를
#   찾으며 지난 날을 말하는 경우는 없다. 지나간 날로 여는 것이 훨씬 나쁜 고장이라
#   앞으로만 본다.
_THIS_WEEK = re.compile(r"이번\s*주\s*([월화수목금토일])\s*요일")
_NEXT_WEEK = re.compile(r"다음\s*주\s*([월화수목금토일])\s*요일")
_BARE_WEEKDAY = re.compile(r"(?<![가-힣])([월화수목금토일])\s*요일")
_WEEKEND = re.compile(r"(이번\s*주말|다음\s*주말|주말)")

# 체크인/체크아웃을 **이름으로** 말해 준 자리. 두 날짜의 순서를 못 믿을 때 쓴다.
_CHECKIN_LABEL = re.compile(r"(체크인|체크\s*인|입실|입주|시작일|출발일|가는\s*날)")
_CHECKOUT_LABEL = re.compile(r"(체크아웃|체크\s*아웃|퇴실|종료일|도착일|오는\s*날)")

_MAX_FUTURE_DAYS = 400  # 이보다 먼 날짜는 잘못 읽은 것으로 본다
_RECENT_PAST_DAYS = 60  # 연도 없는 날짜를 내년으로 굴려도 되는 경계


@dataclass(frozen=True)
class RequestedStay:
    """요청문에서 읽어 낸 날짜. `end` 는 모를 수 있다(1박이라고 안 했을 때)."""

    start: date
    end: date | None = None
    source: str = ""

    def nights(self) -> int | None:
        if self.end is None:
            return None
        return (self.end - self.start).days


def _weekday_index(char: str) -> int:
    return WEEKDAYS_KO.index(char)


def _next_weekday(today: date, target: int, *, at_least_days: int = 0) -> date:
    """`today` 이후로 처음 오는 그 요일. 오늘이 그 요일이면 오늘로 본다."""
    delta = (target - today.weekday()) % 7
    while delta < at_least_days:
        delta += 7
    return today + timedelta(days=delta)


def _sane(day: date, today: date) -> bool:
    """지나간 날·너무 먼 날은 잘못 읽은 것이다."""
    return today <= day <= today + timedelta(days=_MAX_FUTURE_DAYS)


def _absolute_dates(text: str, today: date) -> list[tuple[int, date, str]]:
    """요청문에 **적혀 있는** 날짜들. (위치, 날짜, 원문) 으로 돌려준다."""
    found: list[tuple[int, date, str]] = []
    for m in _ISO.finditer(text):
        try:
            day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        found.append((m.start(), day, m.group(0)))
    for m in _KO_MD.finditer(text):
        month, dom = int(m.group(1)), int(m.group(2))
        try:
            day = date(today.year, month, dom)
        except ValueError:
            continue
        if day < today:
            # 연도가 없다. **한참** 지났으면 내년을 말한 것이다(12월에 「1월 3일」).
            # 하지만 **막 지난** 날이면 내년으로 굴리면 안 된다 — 9월 4일에 「9월
            # 1일」을 2027년으로 읽는 것은 누가 봐도 틀린 답이고, 그 날짜로 숙소를
            # 여는 것이 지금 고치려는 고장보다 나쁘다. 그럴 땐 안 읽는다.
            if (today - day).days <= _RECENT_PAST_DAYS:
                continue
            try:
                day = date(today.year + 1, month, dom)
            except ValueError:
                continue
        found.append((m.start(), day, m.group(0)))
    found.sort(key=lambda item: item[0])
    return found


def _label_around(text: str, start: int, end: int) -> str:
    """이 날짜에 붙은 이름표. `"in"` · `"out"` · 없으면 빈 문자열.

    ## ★ 뒤를 먼저 보는 이유 (2026-09-04 라이브에서 잡음)

    처음엔 **앞만** 봤다(`text[pos-14:pos]`). 영어 어순이면 그게 맞는데
    한국어는 이름표가 **날짜 뒤**에 온다:

        "2026-09-19 체크인, 2026-09-20 체크아웃으로"

    그래서 9/20 의 앞 창에 든 「체크인」(9/19 의 꼬리표)을 9/20 의 이름표로 읽고,
    **9월 20일 밤을 열었다.** 라이브 잡 `746b25bb` 가 실제로 그랬다 — 하루를
    통째로 밀어 놓고 "요청하신 조건으로 확인했다"고 답했다. 고치려던 고장을
    한 칸 옆에서 다시 낸 셈이다.

    뒤 창은 **쉼표·물결·다음 숫자에서 끊는다.** 안 끊으면 "체크인 9/5, 체크아웃
    9/6" 에서 9/5 의 뒤 창이 「체크아웃」을 집어 정반대로 읽는다.
    """
    tail = text[end : end + 12]
    for stop in (",", "，", "~", "·", "/", "\n"):
        tail = tail.split(stop)[0]
    tail = re.split(r"[0-9]", tail)[0]
    for window in (tail, text[max(0, start - 14) : start]):
        if not window.strip():
            continue
        # 「체크아웃」이 「체크인」보다 먼저다 — 둘 다 「체크」로 시작한다.
        if _CHECKOUT_LABEL.search(window):
            return "out"
        if _CHECKIN_LABEL.search(window):
            return "in"
    return ""


def _relative_date(text: str, today: date) -> tuple[date, str] | None:
    """「이번 주 토요일」·「내일」 같은 상대 표현 하나. 없으면 None."""
    # 주(週)를 짚은 표현이 낱말 하나짜리보다 구체적이므로 먼저 본다.
    if (m := _THIS_WEEK.search(text)) is not None:
        return _next_weekday(today, _weekday_index(m.group(1))), m.group(0)
    if (m := _NEXT_WEEK.search(text)) is not None:
        # 「다음 주」는 이번 주를 건너뛴다. 오늘이 금요일이고 「다음 주 토요일」이면
        # 내일이 아니라 여드레 뒤다.
        return _next_weekday(today, _weekday_index(m.group(1)), at_least_days=7), m.group(0)
    if (m := _WEEKEND.search(text)) is not None:
        base = 7 if m.group(0).startswith("다음") else 0
        return _next_weekday(today, _weekday_index("토"), at_least_days=base), m.group(0)
    if (m := _OFFSET_RE.search(text)) is not None:
        return today + timedelta(days=_OFFSET_WORDS[m.group(0)]), m.group(0)
    if (m := _BARE_WEEKDAY.search(text)) is not None:
        # 맨 「토요일」. 다가오는 그 요일로 본다.
        return _next_weekday(today, _weekday_index(m.group(1))), m.group(0)
    return None


def requested_stay(prompt: str, *, now: datetime | None = None) -> RequestedStay | None:
    """요청문에서 **묵을 날**을 읽는다. 확신 못 하면 None.

    None 을 넉넉히 돌려주는 쪽으로 만들었다. 여기서 잘못 읽으면 멀쩡한 주소를
    엉뚱한 날로 바꿔 열게 되고, 그건 지금 고치려는 고장보다 나쁘다.
    """
    text = (prompt or "").strip()
    if not text:
        return None
    today = (now or datetime.now(KST)).date()

    absolute = _absolute_dates(text, today)
    nights_match = _NIGHTS.search(text)
    nights = int(nights_match.group(1)) if nights_match else None

    start: date | None = None
    end: date | None = None
    source = ""

    if absolute:
        # 이름표가 있으면 그것을 믿는다. 「체크아웃 9/6, 체크인 9/5」처럼 거꾸로
        # 적어도 맞게 읽는다.
        labelled: dict[str, date] = {}
        for pos, day, raw in absolute:
            label = _label_around(text, pos, pos + len(raw))
            if label:
                labelled.setdefault(label, day)
        if "in" in labelled:
            start, end = labelled["in"], labelled.get("out")
            if end is None:
                # 체크인만 이름표를 달았다(「체크인 9/5, 9/6」). 뒤에 오는 다음
                # 날짜가 체크아웃이다 — 버리면 1박이 원래 주소의 일수로 되돌아간다.
                end = next((d for _, d, _ in absolute if d > start), None)
            source = "라벨"
        else:
            usable = [day for _, day, _ in absolute if _sane(day, today)]
            if usable:
                start = usable[0]
                if len(usable) >= 2 and usable[1] > usable[0]:
                    end = usable[1]
                source = "명시"

    if start is None:
        relative = _relative_date(text, today)
        if relative is not None:
            start, source = relative[0], relative[1]

    if start is None:
        return None
    if not _sane(start, today):
        return None
    if end is None and nights:
        end = start + timedelta(days=nights)
    if end is not None and end <= start:
        end = None
    return RequestedStay(start=start, end=end, source=source)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 주소의 날짜 인자 갈아 끼우기
# ─────────────────────────────────────────────────────────────────────────────

# 값이 **날짜 모양**인 것만 후보다. 이름은 그다음에 본다.
#
# 키를 이름으로 추측하지 않는 이유: 사이트마다 다르다(야놀자 `checkInDate`,
# 여기어때 `checkIn`, 인터파크 `stdate`, 코레일 `txtGoAbrdDt`). 다 적을 수 없고,
# 빠뜨린 것은 조용히 무동작이 된다. **값의 모양은 사이트를 안 가린다.**
_DATE_VALUE = re.compile(r"^(20[2-9][0-9])([-./]?)(0[1-9]|1[0-2])\2(0[1-9]|[12][0-9]|3[01])$")

# 이름에 방향이 적혀 있으면 그것이 순서보다 세다.
_NAME_START = ("checkin", "checkindate", "startdate", "start", "from", "dep", "go", "sdate", "stdate", "in")
_NAME_END = ("checkout", "checkoutdate", "enddate", "end", "to", "arr", "back", "edate", "eddate", "out")


def _parse_date_value(value: str) -> tuple[date, str] | None:
    """날짜 모양이면 (날짜, 구분자). 아니면 None."""
    m = _DATE_VALUE.match((value or "").strip())
    if m is None:
        return None
    try:
        return date(int(m.group(1)), int(m.group(3)), int(m.group(4))), m.group(2)
    except ValueError:
        return None


def _format_like(day: date, separator: str) -> str:
    return f"{day.year:04d}{separator}{day.month:02d}{separator}{day.day:02d}"


def _direction(name: str) -> str:
    """인자 이름이 시작/끝 중 어느 쪽을 말하는가. 모르면 빈 문자열."""
    low = re.sub(r"[^a-z]", "", (name or "").lower())
    # 긴 낱말이 먼저다 — `checkout` 이 `out` 보다, `checkin` 이 `in` 보다 세다.
    for word in sorted(_NAME_END, key=len, reverse=True):
        if word in low:
            return "end"
    for word in sorted(_NAME_START, key=len, reverse=True):
        if word in low:
            return "start"
    return ""


@dataclass(frozen=True)
class DateRewrite:
    """주소를 바꿨다는 기록. 증거에 그대로 실린다."""

    url: str
    original_url: str
    changed: dict[str, tuple[str, str]]  # 인자 이름 → (전, 후)

    def summary(self) -> str:
        return ", ".join(f"{k} {old}→{new}" for k, (old, new) in self.changed.items())


def rewrite_date_params(url: str, stay: RequestedStay | None) -> DateRewrite | None:
    """주소에 날짜 인자가 있으면 요청한 날짜로 바꾼 주소를 돌려준다.

    바꿀 것이 없거나 확신이 안 서면 **None** — 부르는 쪽은 원래 주소를 그대로 쓴다.

    ## 두 칸일 때 짝 짓는 법

    이름에 방향이 적혀 있으면(`checkInDate`/`checkOutDate`) 그것을 쓴다. 이름이
    말이 없으면 **값의 크기**로 가른다(이른 날이 시작). 둘 다 안 되면 손대지 않는다.

    ## 체크아웃을 모를 때

    원래 주소의 **숙박 일수를 그대로 옮긴다.** 「토요일 숙소」라고만 했으면 며칠
    묵는지는 요청문에 없다 — 그때 하루로 못 박으면 2박 검색을 1박으로 바꿔 버린다.
    """
    if stay is None or not url:
        return None
    parsed = urlparse(url)
    if not parsed.query:
        return None
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if not pairs:
        return None

    # 값이 날짜 모양인 인자만 후보. (자리, 이름, 날짜, 구분자)
    slots = [
        (index, name, parsed_value[0], parsed_value[1])
        for index, (name, value) in enumerate(pairs)
        if (parsed_value := _parse_date_value(value)) is not None
    ]
    if not slots:
        return None

    start_slots = [s for s in slots if _direction(s[1]) == "start"]
    end_slots = [s for s in slots if _direction(s[1]) == "end"]
    unnamed = [s for s in slots if _direction(s[1]) == ""]

    if not start_slots and not end_slots:
        # 이름이 말이 없다. 두 칸이고 값이 다르면 이른 쪽이 시작이다.
        if len(unnamed) == 2 and unnamed[0][2] != unnamed[1][2]:
            ordered = sorted(unnamed, key=lambda s: s[2])
            start_slots, end_slots = [ordered[0]], [ordered[1]]
        elif len(unnamed) == 1:
            start_slots = unnamed
        else:
            # 셋 이상인데 이름이 아무것도 안 알려 준다 → 안전 쪽. 손대지 않는다.
            return None
    if not start_slots:
        # 끝만 있고 시작이 없다. 무엇을 기준으로 옮길지 모른다 → 손대지 않는다.
        return None

    original_start = start_slots[0][2]
    new_start = stay.start
    new_end = stay.end
    if new_end is None and end_slots:
        # 숙박 일수를 그대로 옮긴다.
        span = (end_slots[0][2] - original_start).days
        new_end = new_start + timedelta(days=span if span > 0 else 1)

    changed: dict[str, tuple[str, str]] = {}
    updated = list(pairs)
    for index, name, old_day, separator in slots:
        if (index, name, old_day, separator) in start_slots:
            target = new_start
        elif (index, name, old_day, separator) in end_slots and new_end is not None:
            target = new_end
        else:
            continue
        if target == old_day:
            continue
        formatted = _format_like(target, separator)
        updated[index] = (name, formatted)
        changed[name] = (_format_like(old_day, separator), formatted)

    if not changed:
        return None
    rebuilt = urlunparse(parsed._replace(query=urlencode(updated, doseq=False)))
    return DateRewrite(url=rebuilt, original_url=url, changed=changed)
