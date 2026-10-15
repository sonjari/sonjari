"""요청한 날짜로 주소를 갈아 끼운다 — 달력을 두드리지 말고.

## 이 파일이 지키는 고장 (2026-09-04 실측)

잡 `cd3e84c0` — 「야놀자에 직접 들어가서 **이번 주 토요일** 1박(성인 2명)으로 밀양
숙소를 찾아줘」. 자비스는 야놀자에 잘 들어갔고, 목록을 받았고, 상세 두 곳을 실제로
열어 본문을 읽고 「밀양 마틴 50,000원」이라고 답했다. 전부 진짜로 한 일이다.

그런데 열린 주소가 이거였다:

    …/stay/domestic/3011753?adultCount=2&checkInDate=2026-09-04&checkOutDate=2026-09-05

**9월 4일 밤이다.** 물은 것은 9월 5일이었고, 9/5 는 60,000원이었다(20% 차이).
같은 판의 어뮤즈는 9/5 에 예약마감이었다 — "있다"고 답한 곳이 못 자는 곳이었다.

증거 원장은 이걸 절대 못 잡는다. 가격은 **진짜로 읽은 값**이기 때문이다.
틀린 것은 읽은 값이 아니라 어느 밤을 열었는가다.

잡 `3b5f3a76` — 날짜를 명시해서 다시 시켰더니 달력 위젯을 32번 두드리다 673초에
예산이 끝났다. 그래서 위젯이 아니라 주소로 간다.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from alture_jarvis.dates import RequestedStay, requested_stay, rewrite_date_params

KST = ZoneInfo("Asia/Seoul")

# 실측한 그 날. 금요일이다.
FRIDAY = datetime(2026, 9, 4, 15, 0, tzinfo=KST)

# 실측한 그 주소.
YANOLJA = (
    "https://nol.yanolja.com/stay/domestic/3011753?adultCount=2"
    "&checkInDate=2026-09-04&checkOutDate=2026-09-05&srpKeyword=%EB%B0%80%EC%96%91"
)


# ─────────────────────────────────────────────────────────────────────────────
# 요청문 읽기
# ─────────────────────────────────────────────────────────────────────────────


def test_이번주_토요일은_모델이_더하지_않는다():
    """모델은 이걸 9/6 이라고 답했다. 맞는 값은 9/5 다."""
    stay = requested_stay("야놀자에 직접 들어가서 이번 주 토요일 1박(성인 2명)으로 밀양 숙소를 찾아줘", now=FRIDAY)
    assert stay is not None
    assert stay.start == date(2026, 9, 5)
    assert stay.end == date(2026, 9, 6)  # 「1박」이 체크아웃을 만든다
    assert stay.nights() == 1


def test_명시한_날짜를_그대로_읽는다():
    stay = requested_stay(
        "반드시 체크인 2026-09-05, 체크아웃 2026-09-06, 성인 2명 조건으로 봐야 해", now=FRIDAY
    )
    assert stay is not None
    assert (stay.start, stay.end) == (date(2026, 9, 5), date(2026, 9, 6))


def test_한국어는_이름표가_날짜_뒤에_온다():
    """★ 라이브 잡 `746b25bb` 가 잡은 것.

    「2026-09-19 체크인, 2026-09-20 체크아웃으로」 — 앞 창만 보던 코드가 9/20 의
    앞에 있는 「체크인」(그건 9/19 의 꼬리표다)을 집어 **9월 20일 밤을 열었다.**
    하루를 통째로 밀어 놓고 "요청하신 조건으로 확인했다"고 답했다.
    """
    stay = requested_stay("2026-09-19 체크인, 2026-09-20 체크아웃으로 밀양 숙소를 찾아줘", now=FRIDAY)
    assert stay is not None
    assert (stay.start, stay.end) == (date(2026, 9, 19), date(2026, 9, 20))


def test_이름표가_앞에_와도_읽는다():
    """뒤 창을 먼저 본다고 앞 어순이 깨지면 안 된다 — 쉼표에서 끊는 이유다."""
    stay = requested_stay("체크인 2026-09-05, 체크아웃 2026-09-06 으로", now=FRIDAY)
    assert stay is not None
    assert (stay.start, stay.end) == (date(2026, 9, 5), date(2026, 9, 6))


def test_체크인만_이름표를_달아도_다음_날짜가_체크아웃이다():
    stay = requested_stay("체크인 2026-09-05, 2026-09-07 까지", now=FRIDAY)
    assert stay is not None
    assert (stay.start, stay.end) == (date(2026, 9, 5), date(2026, 9, 7))


def test_거꾸로_적어도_이름표를_믿는다():
    stay = requested_stay("체크아웃은 2026-09-08, 체크인은 2026-09-06 으로 잡아줘", now=FRIDAY)
    assert stay is not None
    assert (stay.start, stay.end) == (date(2026, 9, 6), date(2026, 9, 8))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("내일 묵을 데 찾아줘", date(2026, 9, 5)),
        ("모레 1박으로 부산 숙소", date(2026, 9, 6)),
        ("이번 주말에 갈 만한 숙소", date(2026, 9, 5)),  # 다가오는 토요일
        ("다음 주 토요일 숙소 찾아줘", date(2026, 9, 12)),  # 이번 주를 건너뛴다
        ("9월 7일 숙소", date(2026, 9, 7)),
        ("2026-10-03 체크인", date(2026, 10, 3)),
    ],
)
def test_상대_표현들(text, expected):
    stay = requested_stay(text, now=FRIDAY)
    assert stay is not None and stay.start == expected


@pytest.mark.parametrize(
    "text",
    [
        "밀양 숙소 좀 찾아줘",  # 날짜가 없다
        "가격이 3박 4일치로 얼마인지",  # 「박」은 있지만 시작일이 없다
        "",
        "노트북 3개 사고 싶은데 추천해줘",
    ],
)
def test_확신_못_하면_아무것도_안_읽는다(text):
    """None 이면 주소는 예전 그대로 열린다. 잘못 읽는 것보다 안 읽는 게 낫다."""
    assert requested_stay(text, now=FRIDAY) is None


def test_지나간_날짜는_안_읽는다():
    """「9월 1일」은 이미 지났다. 지난 밤을 열면 지금 고치려는 것보다 나쁘다."""
    assert requested_stay("9월 1일 숙소", now=FRIDAY) is None


# ─────────────────────────────────────────────────────────────────────────────
# 주소 갈아 끼우기
# ─────────────────────────────────────────────────────────────────────────────


def test_야놀자_상세주소가_요청한_밤으로_바뀐다():
    """이 파일이 존재하는 이유. 실측한 그 주소, 실측한 그 요청."""
    stay = requested_stay("이번 주 토요일 1박(성인 2명)으로 밀양 숙소", now=FRIDAY)
    rewrite = rewrite_date_params(YANOLJA, stay)
    assert rewrite is not None
    assert "checkInDate=2026-09-05" in rewrite.url
    assert "checkOutDate=2026-09-06" in rewrite.url
    # 나머지 인자는 손대지 않는다.
    assert "adultCount=2" in rewrite.url
    assert "srpKeyword" in rewrite.url
    assert rewrite.changed["checkInDate"] == ("2026-09-04", "2026-09-05")


def test_체크아웃을_모르면_원래_숙박일수를_옮긴다():
    """「토요일 숙소」라고만 하면 며칠 묵는지는 요청문에 없다.

    그때 하루로 못 박으면 2박 검색을 1박으로 바꿔 버린다.
    """
    url = "https://x.example/stay?checkInDate=2026-09-04&checkOutDate=2026-09-07"
    rewrite = rewrite_date_params(url, RequestedStay(start=date(2026, 9, 10)))
    assert rewrite is not None
    assert "checkInDate=2026-09-10" in rewrite.url
    assert "checkOutDate=2026-09-13" in rewrite.url  # 3박 그대로


def test_원래_형식을_지킨다():
    """`20260905` 를 `2026-09-05` 로 바꾸면 사이트가 못 읽는다."""
    url = "https://x.example/list?stdate=20260904&eddate=20260905"
    rewrite = rewrite_date_params(url, RequestedStay(start=date(2026, 9, 6), end=date(2026, 9, 7)))
    assert rewrite is not None
    assert "stdate=20260906" in rewrite.url and "eddate=20260907" in rewrite.url

    dotted = "https://x.example/list?from=2026.09.04&to=2026.09.05"
    rewrite = rewrite_date_params(dotted, RequestedStay(start=date(2026, 9, 6), end=date(2026, 9, 7)))
    assert rewrite is not None
    assert "2026.09.06" in rewrite.url and "2026.09.07" in rewrite.url


def test_이름이_말이_없으면_이른_쪽이_시작이다():
    url = "https://x.example/p?a=2026-09-04&b=2026-09-06"
    rewrite = rewrite_date_params(url, RequestedStay(start=date(2026, 9, 10)))
    assert rewrite is not None
    assert "a=2026-09-10" in rewrite.url
    assert "b=2026-09-12" in rewrite.url  # 2박 유지


def test_이름도_순서도_모르면_손대지_않는다():
    """안전 쪽. 셋 이상인데 아무것도 안 알려 주면 원래 주소 그대로 연다."""
    url = "https://x.example/p?a=2026-09-04&b=2026-09-06&c=2026-09-08"
    assert rewrite_date_params(url, RequestedStay(start=date(2026, 9, 10))) is None


def test_날짜_인자가_없으면_안_건드린다():
    url = "https://nol.yanolja.com/stay/domestic/3011753?adultCount=2"
    assert rewrite_date_params(url, RequestedStay(start=date(2026, 9, 10))) is None
    assert rewrite_date_params("https://example.com/article/1", RequestedStay(start=date(2026, 9, 10))) is None


def test_이미_맞는_날짜면_다시_안_연다():
    """바꿀 게 없으면 None — 같은 주소를 두 번 열 이유가 없다."""
    stay = RequestedStay(start=date(2026, 9, 4), end=date(2026, 9, 5))
    assert rewrite_date_params(YANOLJA, stay) is None


def test_요청한_날짜가_없으면_아무것도_안_한다():
    assert rewrite_date_params(YANOLJA, None) is None


def test_날짜가_아닌_숫자는_후보가_아니다():
    """`vendorItemId=20260904` 같은 것에 걸리면 안 된다 — 값 모양만 보고 고르므로
    실제로 날짜 모양인 것만 잡힌다. 아래는 날짜 모양이 아니다."""
    url = "https://x.example/p?vendorItemId=1234567890&price=20260"
    assert rewrite_date_params(url, RequestedStay(start=date(2026, 9, 10))) is None


# ─────────────────────────────────────────────────────────────────────────────
# 브라우저 배선 — 도구가 대신 바꿔서 연다 (안내문이 아니라)
# ─────────────────────────────────────────────────────────────────────────────


def _future_prompt(days: int = 30) -> str:
    """★ **시계에 묶이지 않는** 요청문. (2026-09-06 00:32 에 물린 자리)

    `set_requested_stay` 는 `now=` 를 못 받는다 — 라이브와 같은 길로 돌리려고
    일부러 그렇게 뒀다. 그래서 검사가 날짜를 하드코딩하면 **그 날이 지나는 순간
    조용히 빨개진다.** 이 세션 중에 자정을 넘겨 실제로 그렇게 됐다.

    앞으로의 날짜를 계산해서 넣으면 언제 돌려도 같은 뜻이다.
    """
    from datetime import timedelta

    from alture_jarvis.clock import KST

    today = datetime.now(KST).date()
    start = today + timedelta(days=days)
    end = start + timedelta(days=1)
    return f"체크인 {start.isoformat()}, 체크아웃 {end.isoformat()} 으로 봐줘"


def _future_dates(days: int = 30):
    from datetime import timedelta

    from alture_jarvis.clock import KST

    start = datetime.now(KST).date() + timedelta(days=days)
    return start, start + timedelta(days=1)


class _FakeWorker:
    """`BrowserWorker` 의 항해 부분만 흉내 낸다. 실제 크롬은 안 띄운다."""

    def __init__(self, fail_on: str = "") -> None:
        self.visited: list[str] = []
        self.fail_on = fail_on

    def _goto_checked(self, page, url):
        self.visited.append(url)
        if self.fail_on and self.fail_on in url:
            raise RuntimeError("site_blocked:x.example")


def _bind(worker):
    from alture_jarvis.browser import BrowserWorker

    worker.set_requested_stay = BrowserWorker.set_requested_stay.__get__(worker)
    worker._goto_with_dates = BrowserWorker._goto_with_dates.__get__(worker)
    worker._date_rewrite_evidence = BrowserWorker._date_rewrite_evidence
    worker._requested_stay = None
    return worker


def test_도구가_대신_바꿔서_연다():
    """안내문이 아니라 코드가 한다 — 사고 R."""
    worker = _bind(_FakeWorker())
    worker.set_requested_stay("이번 주 토요일 1박으로 밀양 숙소 찾아줘")
    # `now` 를 못 주는 자리라 요청문의 상대 표현 대신 명시 날짜로 확인한다.
    worker.set_requested_stay(_future_prompt())
    rewrite = worker._goto_with_dates(None, YANOLJA)
    assert rewrite is not None
    assert worker.visited == [rewrite.url]
    start, _end = _future_dates()
    assert f"checkInDate={start.isoformat()}" in worker.visited[0]


def test_바꾼_주소가_안_열리면_원래_주소로_되돌아간다():
    """못 바꾼 것이 못 여는 것보다 낫다."""
    start, _end = _future_dates()
    worker = _bind(_FakeWorker(fail_on=f"checkInDate={start.isoformat()}"))
    worker.set_requested_stay(_future_prompt())
    rewrite = worker._goto_with_dates(None, YANOLJA)
    assert rewrite is None
    assert len(worker.visited) == 2
    assert worker.visited[1] == YANOLJA  # 원래 주소로 실제로 갔다


def test_날짜를_못_읽으면_예전대로_연다():
    worker = _bind(_FakeWorker())
    worker.set_requested_stay("밀양 숙소 좀 찾아줘")
    assert worker._goto_with_dates(None, YANOLJA) is None
    assert worker.visited == [YANOLJA]


def test_바꾼_것은_증거에_남는다():
    """조용히 바꾸면 안 된다 — 사람이 '왜 이 날짜를 봤나'를 물을 자리다."""
    from alture_jarvis.browser import BrowserWorker

    stay = RequestedStay(start=date(2026, 9, 5), end=date(2026, 9, 6))
    rewrite = rewrite_date_params(YANOLJA, stay)
    marks = BrowserWorker._date_rewrite_evidence(rewrite)
    assert marks["date_rewritten"] == (
        "checkInDate 2026-09-04→2026-09-05, checkOutDate 2026-09-05→2026-09-06"
    )
    assert marks["date_original_url"] == YANOLJA
    assert "달력 위젯을 누르지 마라" in marks["date_instruction"]
    assert BrowserWorker._date_rewrite_evidence(None) == {}


def test_증거가_장부를_실제로_통과한다():
    """★ 라이브에서 잡은 것 — 중첩 dict 로 내면 장부가 **통째로 버린다.**

    `_step_evidence` 마지막 줄이 「dict 는 안 싣는다」다. 모델은 지시 문자열을 받아
    잘 답했는데 장부에는 한 줄도 안 남아, 나중에 "어느 밤을 열었나"를 물으면
    주소를 손으로 뜯어보는 수밖에 없었다. 증거는 **장부를 통과해야** 증거다.
    """
    from alture_jarvis.agent import _step_evidence
    from alture_jarvis.browser import BrowserWorker

    rewrite = rewrite_date_params(YANOLJA, RequestedStay(start=date(2026, 9, 5), end=date(2026, 9, 6)))
    evidence = {"action": "opened_result", "url": rewrite.url, **BrowserWorker._date_rewrite_evidence(rewrite)}
    ledger = _step_evidence(evidence)
    assert "2026-09-04→2026-09-05" in ledger["date_rewritten"]
    assert ledger["date_original_url"] == YANOLJA


def test_판이_바뀌면_지난_판의_날짜를_버린다():
    """순위가 새면 딴 사이트를 열듯, 날짜가 새면 엉뚱한 밤을 연다."""
    worker = _bind(_FakeWorker())
    worker.set_requested_stay(_future_prompt())
    assert worker._requested_stay is not None

    from alture_jarvis.browser import BrowserWorker

    worker._last_results = []
    worker._reads_since_search = 0
    worker._searches_without_read = 0
    worker._searched_before = False
    BrowserWorker.forget_results(worker)
    assert worker._requested_stay is None


# ─────────────────────────────────────────────────────────────────────────────
# 목록은 주소로 못 바꾼다 — 그 사실을 그 자리에서 말해 준다
# ─────────────────────────────────────────────────────────────────────────────


class _PageAt:
    def __init__(self, url: str) -> None:
        self.url = url


def _list_worker(prompt: str):
    from alture_jarvis.browser import BrowserWorker

    worker = _FakeWorker()
    worker._requested_stay = None
    worker.set_requested_stay = BrowserWorker.set_requested_stay.__get__(worker)
    worker._stay_note_for_list = BrowserWorker._stay_note_for_list.__get__(worker)
    worker.set_requested_stay(prompt)
    return worker


# 야놀자 목록 — 검색 조건이 불투명한 덩어리 하나로 접혀 있어 주소로 못 바꾼다.
YANOLJA_LIST = (
    "https://nol.yanolja.com/discovery/list/search/PRODUCT_CATEGORY_KOREA_ACCOMMODATION"
    "?filter=4XAAjW4YDKiGgVn9lFSyTxpjxAorLCVFlxeJFDYNPXa0IMAZYlWKBPjR2h8r"
)


def test_주소로_못_바꾸는_목록에서는_달력을_누르지_말라고_한다():
    """라이브 잡 `746b25bb`: 목록에서 달력을 24걸음 두드리다 608초를 태웠다.

    ★ 2026-09-20: 원래 `2026-09-19` 를 박아 뒀더니 그날이 지나자 깨졌다 — `requested_stay` 는 지난 체크인을
      일부러 버린다. 날짜는 오늘 기준 미래로 만든다.
    """
    from datetime import date, timedelta

    check_in = date.today() + timedelta(days=30)
    check_out = check_in + timedelta(days=1)
    worker = _list_worker(f"체크인 {check_in.isoformat()}, 체크아웃 {check_out.isoformat()} 으로 밀양 숙소")
    note = worker._stay_note_for_list(_PageAt(YANOLJA_LIST))
    assert check_in.isoformat() in note and check_out.isoformat() in note
    assert "달력 위젯을 누르지 마라" in note
    assert "browser_open_result" in note


def test_날짜를_요청_안_한_판에서는_아무_말도_안_한다():
    """96%는 날짜 없는 판이다. 거기에 이 말이 끼면 순수한 소음이다."""
    worker = _list_worker("사람인에서 부산 학원 강사 공고 찾아줘")
    assert worker._stay_note_for_list(_PageAt(YANOLJA_LIST)) == ""


def test_이미_요청한_날짜인_목록에는_말하지_않는다():
    """주소에 날짜가 있고 그게 요청한 날짜면 바로잡을 것이 없다."""
    worker = _list_worker("체크인 2026-09-19, 체크아웃 2026-09-20 으로 밀양 숙소")
    dated = "https://x.example/list?checkIn=2026-09-19&checkOut=2026-09-20"
    assert worker._stay_note_for_list(_PageAt(dated)) == ""


# ─────────────────────────────────────────────────────────────────────────────
# 목록도 갈아 끼운다 — 두 장치가 서로를 상쇄하던 자리
# ─────────────────────────────────────────────────────────────────────────────


class _ListPage:
    """지금 떠 있는 목록. `_goto_checked` 로 다시 열면 주소가 바뀐다."""

    def __init__(self, url: str) -> None:
        self.url = url


def _list_fixer(prompt: str, url: str):
    """`_apply_requested_dates_here` 만 진짜에서 빌려 온 워커."""
    from alture_jarvis.browser import BrowserWorker

    worker = _FakeWorker()
    worker._requested_stay = None
    worker.page = _ListPage(url)
    worker._wait_until_operable = lambda page: {"count": 1, "ms": 1, "polls": 1}
    worker.set_requested_stay = BrowserWorker.set_requested_stay.__get__(worker)
    worker._apply_requested_dates_here = BrowserWorker._apply_requested_dates_here.__get__(worker)
    worker._stay_note_for_list = BrowserWorker._stay_note_for_list.__get__(worker)
    worker.set_requested_stay(prompt)
    return worker


# 여기어때 목록 — 야놀자와 달리 **주소에 날짜가 실려 있다.**
def _yeogi_list(check_in: str = "2026-09-05", check_out: str = "2026-09-06") -> str:
    return (
        "https://www.yeogi.com/domestic-accommodations"
        f"?keyword=%EA%B2%BD%EC%A3%BC&checkIn={check_in}&checkOut={check_out}&personal=2"
    )


# 사이트가 준 기본 날짜(과거여도 된다 — 바뀌는 쪽이지 요청하는 쪽이 아니다).
YEOGI_LIST = _yeogi_list()


def test_목록도_요청한_날짜로_다시_연다():
    """★ 라이브 잡 `e8d7fa0f` 가 잡은 것.

    날짜 교체가 `_open`·`_open_result` 두 문에만 걸려 있었다. 목록은 검색칸에
    쳐서 그 자리에 뜨므로 그 문을 안 지난다 — 주소에 날짜가 멀쩡히 있는데도
    아무도 안 바꿨고, 모델이 **달력을 10 걸음 두드렸다**(24 걸음 판의 42%).
    """
    worker = _list_fixer(_future_prompt(), YEOGI_LIST)
    fix = worker._apply_requested_dates_here(worker.page)
    assert fix is not None
    start, end = _future_dates()
    assert f"checkIn={start.isoformat()}" in fix.url and f"checkOut={end.isoformat()}" in fix.url
    assert "keyword=%EA%B2%BD%EC%A3%BC" in fix.url, "검색어를 잃으면 안 된다"
    assert worker.visited == [fix.url], "다시 여는 것까지 해야 목록이 그 날짜가 된다"


def test_바꿨으면_바꿨다고_말한다():
    """★ 두 장치가 서로를 상쇄하던 자리.

    안내는 「주소로 바꿀 수 있으면 말 안 한다」였다. 바꿀 수 있다는 것과 바꿨다는
    것은 다르다 — 침묵과 무동작이 겹쳐 **아무도 일을 안 했다.**
    """
    worker = _list_fixer(_future_prompt(), YEOGI_LIST)
    fix = worker._apply_requested_dates_here(worker.page)
    note = worker._stay_note_for_list(worker.page, applied=fix)
    start, _end = _future_dates()
    assert "다시 열었다" in note and start.isoformat() in note
    assert "달력 위젯을 누르지 마라" in note


def test_이미_맞는_날짜면_다시_안_열고_말도_안_한다():
    start, end = _future_dates()
    right = _yeogi_list(start.isoformat(), end.isoformat())
    worker = _list_fixer(_future_prompt(), right)
    assert worker._apply_requested_dates_here(worker.page) is None
    assert worker.visited == [], "바꿀 게 없는데 다시 열면 그냥 왕복 낭비다"
    assert worker._stay_note_for_list(worker.page) == ""


def test_주소로_못_바꾸는_목록은_예전처럼_말로_알린다():
    """야놀자는 조건을 불투명한 덩어리에 접는다 — 이 길로는 못 고친다."""
    worker = _list_fixer(_future_prompt(), YANOLJA_LIST)
    assert worker._apply_requested_dates_here(worker.page) is None
    note = worker._stay_note_for_list(worker.page)
    assert "달력 위젯을 누르지 마라" in note and "browser_open_result" in note


def test_날짜를_안_물은_판은_목록을_안_건드린다():
    """96%는 날짜 없는 판이다. 거기서 페이지를 다시 열면 순수한 손해다."""
    worker = _list_fixer("사람인에서 부산 학원 강사 공고 찾아줘", YEOGI_LIST)
    assert worker._apply_requested_dates_here(worker.page) is None
    assert worker.visited == []


def test_다시_열다_실패해도_판을_안_죽인다():
    """이 층은 거들 뿐이지 목록의 조건이 아니다."""
    worker = _list_fixer(_future_prompt(), YEOGI_LIST)
    start, _end = _future_dates()
    worker.fail_on = f"checkIn={start.isoformat()}"
    assert worker._apply_requested_dates_here(worker.page) is None


def test_어느_길로_목록에_와도_날짜를_맞춘다():
    """★ 라이브 세 판이 **세 가지 다른 길**로 목록에 도착했다 (2026-09-05).

        e8d7fa0f   browser_site_search 로            ← 훅 걸림
        9deffc9e   홈에서 달력 두드리고 클릭으로       ← 훅 안 걸림 (11걸음 낭비)
        (그 밖)    load_more 로

    문에 걸면 다른 문으로 들어온다 — 이 파일이 방금 고친 것과 같은 종류의 실수다.
    그래서 「화면이 목록이다」가 확정되는 자리(`_recover_results_for_open`)에도 건다.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "src" / "alture_jarvis" / "browser.py"
    ).read_text(encoding="utf-8")
    body = source.split("def _recover_results_for_open(")[1].split("\n    def ")[0]
    assert "_apply_requested_dates_here(page)" in body, (
        "클릭으로 목록에 도착한 판에서 날짜가 안 맞춰진다"
    )
    # 세 문 모두에 걸려 있어야 한다.
    assert source.count("self._apply_requested_dates_here(page)") >= 3


def test_오늘만_말한_판에는_날짜_경고를_안_붙인다():
    """운영 기록 12번 중 11번이 헛발이었다 — 레딧·네이버 뉴스·날씨·K-Startup 에 「가격·잔여를 쓰지 마라」가 붙었다.

    2026-10-05 9B 판(ef1e8e25): 「오늘 허깅페이스에서 뜨는 모델」에 이 경고가 붙어, 눈앞의 목록을 두고 날짜를 넣어 다시 검색했다.
    지금 떠 있는 목록이 곧 오늘 것이다 — 기간이 없으면 바로잡을 것이 없다.
    """
    for prompt in ("오늘 허깅페이스에서 뜨고 있는 최신 모델 후보 5개를 찾아줘", "네이버에서 오늘 대구 날씨를 찾아서 한 줄로 알려줘",
                   "오늘자 국내 뉴스 네이버에서 한번 알아봐줘"):
        worker = _list_worker(prompt)
        assert worker._stay_note_for_list(_PageAt("https://huggingface.co/models")) == "", prompt


def test_오늘부터_며칠_묵는지_말했으면_여전히_알린다():
    worker = _list_worker("오늘부터 2박으로 경주 숙소 가격 알아봐줘")
    if worker._requested_stay is not None and worker._requested_stay.end is not None:
        assert "달력 위젯을 누르지 마라" in worker._stay_note_for_list(_PageAt(YANOLJA_LIST))
