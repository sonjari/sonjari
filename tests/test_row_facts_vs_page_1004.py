"""답 표의 줄에 적은 금액·시킨 근무형태를 **그 줄의 페이지**와 맞춘다 · 빼 놓은 것에 경고하지 않는다 · 날짜 옆의 「내일」 (2026-10-04 채용 공고 조사 판 788ef850).

한 문장 요청(이력서를 보고 서울 뺀 광역권 · 정규직 · 연봉)에 공고 21개를 읽고 추천 표 다섯 줄을 냈다. 원문과 맞춰 보니:
  · 데이터나루터 「연봉 3,000만원」 — 그 공고는 「면접 후 결정」. 같은 페이지 광고의 「30000원」이 있어 금액 검사를 지나갔다.
  · 한울이엔지(정밀기계) — 정규직 표에 넣었는데 그 공고의 근무형태는 「계약직, 전임」.
  · 「10/08(내일!)」 — 오늘은 10/04.
  · 빼 놓은 파트타임·기간제 표를 보고 「'정규직'을 시키셨는데 답에 기간제가 들어 있습니다」.
  · 걸음 기록의 주소가 200자에서 잘려(사람인 주소 221자) 줄↔페이지 대조가 21개 전부 말없이 건너뛰었다.
실제 판의 답·원문으로 돌려 둘을 잡고 헛경고가 사라지는 것을 확인한 뒤 줄여서 시험으로 둔다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from alture_jarvis import agent as agent_module
from alture_jarvis import plan
from alture_jarvis.agent import BrowserAgent, mend_day_words

LONG = "&location=ts&searchword=%ED%9A%8C%EA%B3%84&searchType=search&paid_fl=n&search_uuid=9496d128-276d-493f-987f-d2d2af12f204&company_cd=0,1,2,3,4,5,6,7,9,10&panel_type=&x=" + "y" * 60
DATA = "https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=search&rec_idx=51000006" + LONG
HANUL_SPACE = "https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=search&rec_idx=51000007" + LONG
HANUL_ADMIN = "https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=search&rec_idx=51000001" + LONG
NURIGEN = "https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=search&rec_idx=51000008" + LONG

PAGES = {
    DATA: ("[(주)데이터나루터] [신입/경력] 정부R&D 사업관리(사업비·행정) 담당자 (D-10) - 사람인",
           "(주)데이터나루터\n근무형태\n정규직 수습기간 3개월\n급여\n면접 후 결정\n근무지역\n대전 유성구\n광고: 건축기사 필기 비법노트\n30000원\n13%\n26000원"),
    HANUL_SPACE: ("[한울이엔지(주)] [정밀기계사업부] 사업관리팀 국책과제 담당자 (채용시 마감) - 사람인",
                    "한울이엔지(주)\n근무형태\n계약직, 전임\n급여\n면접 후 결정\n근무지역\n대전 유성구"),
    HANUL_ADMIN: ("[한울이엔지(주)] 연구관리/총무/행정 직원 채용합니다 (D-27) - 사람인",
                    "한울이엔지(주)\n근무형태\n계약직 정규직 전환 가능 - 무기계약직\n급여\n면접 후 결정"),
    NURIGEN: ("[누리젠(주)] 누리젠(주) 연구기획/행정 담당자 경력 채용 공고 (채용시 마감) - 사람인",
              "누리젠(주)\n근무형태\n정규직 수습기간 3개월\n급여\n연봉 3,600 만원\n근무지역\n대전 유성구"),
}
ASKED = "나래이 이력서를 본 뒤에 사람인에서 대전이나 광역권 정규직으로 연봉이 센 공고를 찾아줘"


def _steps() -> list[dict[str, Any]]:
    return [
        {"step": index, "tool": "browser_extract", "ok": True,
         # 걸음 증거의 주소는 200자에서 잘린다 — 온전한 주소는 근거 기록에 있다.
         "evidence": {"url": url[:200], "title": title},
         "evidence_record": {"type": "body_read", "ok": True, "source_id": url, "step": index}}
        for index, (url, (title, _body)) in enumerate(PAGES.items(), start=1)
    ]


def _agent() -> BrowserAgent:
    agent = object.__new__(BrowserAgent)
    bodies = {BrowserAgent._url_key(url): body for url, (_title, body) in PAGES.items()}
    agent._page_bodies = lambda _steps, _job: bodies  # type: ignore[method-assign]
    return agent


def _check(answer: str, asked: str = ASKED) -> str:
    return _agent()._row_facts_vs_page_check(asked, answer, _steps(), "job")


TABLE = (
    "## 정규직 + 대전 (조건 만족)\n\n"
    "| 회사 | 직무 | 지역 | 연봉 | 마감 |\n|---|---|---|---|---|\n"
    "| **데이터나루터** | 정부R&D 사업비 집행·정산 | 대전 유성구 | **3,000만원** | 10/14 |\n"
    "| **누리젠** | 연구기획/행정 | 대전 유성구 | 3,600만원 | 채용시 |\n"
    "| **한울이엔지(정밀기계)** | 국책과제 사업관리 | 대전 유성구 | 미정 | 채용시 |\n"
)


# --- 금액 ---------------------------------------------------------------------

def test_an_amount_that_is_not_on_that_rows_page_is_named() -> None:
    notes = _check(TABLE)

    assert "줄에 적은 금액이 그 줄의 페이지에 없습니다" in notes and "「데이터나루터」 3,000만원" in notes
    assert "누리젠" not in notes, "그 페이지에 있는 금액은 부르지 않는다(3,600 만원)"


def test_a_unit_changes_the_number_by_exactly_its_zeros() -> None:
    """3,000만원은 30,000,000원과 같다 — 「30000원」과는 다르다. 0 이 몇 개든 같다고 보면 광고의 값으로 지나간다."""
    won = TABLE.replace("3,600만원", "36,000,000원")

    assert "누리젠" not in _check(won)
    assert "「데이터나루터」 3,000만원" in _check(won)


# --- 근무형태 ------------------------------------------------------------------

def test_a_recommended_row_whose_page_says_another_employment_type_is_named() -> None:
    notes = _check(TABLE)

    assert "'정규직' 를 시키셨는데" in notes and "「한울이엔지(정밀기계)」의 근무형태는 「계약직, 전임」" in notes


def test_two_postings_by_one_company_are_told_apart_by_the_other_cells() -> None:
    """한울이엔지 공고를 둘 열었다 — 줄의 「국책과제 사업관리」가 제목에 든 쪽을 고른다. 똑같이 맞으면 고르지 않는다."""
    titles = {BrowserAgent._url_key(url): title for url, (title, _body) in PAGES.items()}

    space = BrowserAgent._page_for_row(["**한울이엔지(정밀기계)**", "국책과제 사업관리", "대전 유성구"], titles)
    unsure = BrowserAgent._page_for_row(["**한울이엔지**", "대전 유성구", "미정"], titles)

    assert space == BrowserAgent._url_key(HANUL_SPACE)
    assert unsure == ""


def test_a_page_that_names_both_types_is_not_blamed() -> None:
    table = TABLE.replace("| **한울이엔지(정밀기계)** | 국책과제 사업관리 |", "| **한울이엔지** | 연구관리/총무/행정 직원 |")

    assert "근무형태는" not in _check(table), "「계약직 정규직 전환 가능」은 시킨 말이 들어 있다 — 모르면 판정하지 않는다"


def test_no_condition_was_asked_then_none_is_checked() -> None:
    assert "근무형태는" not in _check(TABLE, asked="사람인에서 대전 공고 세 개 찾아줘")


def test_rows_that_were_set_aside_are_not_checked() -> None:
    aside = (
        "## ⚠️ 표에서 제외한 항목 (정규직 조건 불충분)\n\n"
        "| 회사 | 직무 | 지역 | 제외 이유 |\n|---|---|---|---|\n"
        "| 한울이엔지(정밀기계) | 국책과제 사업관리 | 대전 유성구 | **계약직** |\n"
    )

    assert _check(aside) == ""


# --- 걸음 기록의 잘린 주소 --------------------------------------------------------

def test_the_whole_address_comes_from_the_evidence_record() -> None:
    step = _steps()[0]

    assert len(step["evidence"]["url"]) == 200 < len(DATA)
    assert BrowserAgent._step_page_url(step) == DATA
    assert BrowserAgent._step_page_url({"evidence": {"url": "https://a.b/c"}}) == "https://a.b/c"


def test_the_page_checks_all_bind_by_the_whole_address() -> None:
    source = __import__("inspect").getsource(agent_module)

    assert source.count("url = self._step_page_url(step)") + source.count("url = cls._step_page_url(step)") >= 2
    assert "url, title = self._step_page_url(step)" in source


# --- 빼 놓은 것에 경고하지 않는다 --------------------------------------------------

ANSWER_WITH_ASIDE = (
    "정규직이 아닌 항목(파트타임·기간제)을 표에 섞어 넣은 오류를 바로잡겠습니다. 조건에 맞지 않아 표에서 제외하고 정리합니다.\n\n"
    + TABLE
    + "\n## ⚠️ 표에서 제외한 항목 (정규직 조건 불충분)\n\n"
    "| 회사 | 직무 | 지역 | 제외 이유 |\n|---|---|---|---|\n"
    "| KAIST 이민호 연구실 | 위촉행정원 | 대전 유성구 | **기간제**(연봉 4,080만원) |\n\n"
    "## 📋 정직한 한계\n- 연봉이 명시된 정규직은 적습니다.\n"
)


def test_what_was_set_aside_with_a_reason_is_not_a_broken_condition() -> None:
    assert plan.broken_conditions(ASKED, ANSWER_WITH_ASIDE) == []
    assert "기간제" not in plan.without_excluded_parts(ANSWER_WITH_ASIDE)
    assert "정직한 한계" in plan.without_excluded_parts(ANSWER_WITH_ASIDE), "다음 제목부터는 다시 본다"


def test_a_condition_the_answer_itself_breaks_is_still_caught() -> None:
    """2026-08-16 의 그 판 — 정규직을 시켰는데 추천 줄에 계약직이라고 적었다. 이건 그대로 잡는다."""
    answer = "| 회사 | 형태 |\n|---|---|\n| 가나상사 | 계약직 |\n| 다라물산 | 파견직 |\n"

    assert ("정규직", "계약직") in plan.broken_conditions("정규직 공고 3개를 골라줘", answer)


# --- 「읽지 않고 적은 것」 헛경고 둘 -----------------------------------------------

def test_a_name_whose_words_sit_together_in_what_was_read_counts_as_read() -> None:
    source = "채용중 10 / KAIST AI미래학과 이민호교수 연구실 기간제근로자(위촉행정원) 모집 / D-8"
    scattered = "KAIST 공고 목록 … " + "다른 글 " * 60 + " 이민호 … " + "또 다른 글 " * 60 + " 연구실 소개"

    assert agent_module._name_words_were_read_together("KAIST 이민호 연구실", source) is True
    assert agent_module._name_words_were_read_together("KAIST 이민호 연구실", scattered) is False, "흩어져 있는 낱말은 치지 않는다"
    assert agent_module._name_words_were_read_together("KAIST 박주찬 연구실", source) is False
    assert agent_module._name_words_were_read_together("연구실", source) is False, "낱말 하나짜리는 이 길로 판정하지 않는다"


def test_a_line_of_facts_split_by_slashes_is_not_an_item_name() -> None:
    assert agent_module._is_a_list_of_facts("최나래 / 1991년생 / 한울대 행정졸업(전공 사회학, 복수 행정)") is True
    assert agent_module._is_a_list_of_facts("연구관리/총무/행정 직원 채용합니다") is False
    assert agent_module._is_a_list_of_facts("A / B 비교") is False


# --- 날짜 옆의 「내일」 -----------------------------------------------------------

TODAY = datetime(2026, 10, 4)


def test_tomorrow_next_to_a_date_four_days_away_is_corrected() -> None:
    assert mend_day_words("마감 **10/08(내일!)** 가장 급함", TODAY) == "마감 **10/08(4일 뒤!)** 가장 급함"
    assert mend_day_words("10월 6일(내일) 마감", TODAY) == "10월 6일(모레) 마감"
    assert mend_day_words("10/01 (오늘) 마감", TODAY) == "10/01 (3일 지남) 마감"


def test_a_day_word_that_matches_its_date_is_left_alone() -> None:
    for text in ("10/05(내일) 마감", "10월 4일(오늘)", "10/6 (모레)", "내일 다시 볼게요", "13/40(내일)", None, ""):
        assert mend_day_words(text, TODAY) == text


def test_a_january_deadline_seen_in_december_is_next_year() -> None:
    assert mend_day_words("1/1(내일)", datetime(2026, 12, 31)) == "1/1(내일)"
    assert mend_day_words("1/3(내일)", datetime(2026, 12, 31)) == "1/3(3일 뒤)"


# --- 실전 판 574826ac 에서 나온 둘: 소제목 아래도 빼 놓은 자리다 · 설명 문장은 항목이 아니다 -------------

NOTHING_QUALIFIED = (
    "대전·세종·충남 지역에서 정규직으로 채용하는 공고를 찾지 못했습니다.\n\n"
    "「연구비 정산」 검색 결과 15건은 모두 **서울·경기 지역**이거나 **계약직**이었습니다.\n\n"
    "### 표에 넣지 않고 뺀 공고 (15건 전체)\n\n"
    "**정규직이지만 지역이 다른 곳 (정규직O, 지역X)**\n\n"
    "| 순위 | 회사 | 근무지역 | 근무형태 |\n|---|---|---|---|\n| 1 | 큰길회계법인 | 서울 강남구 | 정규직 |\n\n"
    "**계약직이고 지역도 다른 곳 (정규직X, 지역X)**\n\n"
    "| 순위 | 회사 | 근무지역 | 근무형태 |\n|---|---|---|---|\n| 5 | 한울대학교산학협력단 | 서울 성동구 | 계약직 |\n\n"
    "## 못 한 이유\n\n- 조건을 동시에 만족하는 공고가 0건이었습니다.\n"
)


def test_a_bold_subheading_does_not_end_the_set_aside_part() -> None:
    """`###` 제목 아래의 굵은 글씨 줄은 더 낮은 층이다 — 같거나 높은 층의 제목이 와야 빼 놓은 자리가 끝난다."""
    kept = plan.without_excluded_parts(NOTHING_QUALIFIED)

    assert "한울대학교산학협력단" not in kept and "큰길회계법인" not in kept
    assert "못 한 이유" in kept and "0건이었습니다" in kept


def test_a_sentence_that_explains_why_nothing_qualified_is_not_an_item() -> None:
    assert plan.broken_conditions("대전 지역의 정규직 공고 5개를 정리해줘", NOTHING_QUALIFIED) == []


def test_a_listed_item_that_breaks_the_condition_is_caught_in_any_list_shape() -> None:
    asked = "정규직 공고 3개를 골라줘"

    assert plan.broken_conditions(asked, "1. 가나상사 — 계약직, 서울\n2. 다라물산 — 정규직")
    assert plan.broken_conditions(asked, "- 가나상사: 파견직\n- 다라물산: 정규직")
    assert plan.broken_conditions(asked, "| 가나상사 | 인턴 |\n| 다라물산 | 정규직 |")
