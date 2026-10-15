"""문서 파일 이름이 받는 곳이면 산출물 요구다 (2026-10-02 밤 레딧 기록 예약 02d3bdf0).

「reddit_반응기록.xlsx 에 … 기록해줘」가 요구 0개(근거 1개 읽기만)로 돌아, 글 6개를 다 읽고 「이제 엑셀에 기록하겠습니다」로
끝났다. 동사(기록·적어·넣어)를 낱말표에 더하지 않고 대상의 모양(파일 이름 + 에/로)으로 본다.
"""

from __future__ import annotations

from alture_jarvis.plan import extract, wants_an_artifact

REDDIT = (
    "크롬에서 레딧 프로필을 열어 글마다 조회수를 읽고, 그 내용을 "
    "C:/Users/me/Documents/JARVIS/reddit/reddit_반응기록.xlsx 에 오늘 날짜·시각을 붙여 기록해줘. "
    "엑셀 파일이 이미 있으면 기존 행은 지우지 말고 아래에 덧붙여."
)


def test_a_named_file_as_the_destination_is_an_artifact() -> None:
    assert wants_an_artifact(REDDIT)
    assert wants_an_artifact("결과 문구를 그대로 naver_result.md 에 적어줘")
    assert wants_an_artifact("요약을 a.md로 넣어줘")


def test_a_named_file_to_read_is_not() -> None:
    assert not wants_an_artifact("report.docx 에서 표를 찾아줘")
    assert not wants_an_artifact("data.csv 를 읽고 요약해줘")
    assert not wants_an_artifact("파일을 수정하지 말고 summary.md 에 뭐가 있는지만 알려줘")


def test_the_plan_now_waits_for_the_file() -> None:
    kinds = {item.kind for item in extract(REDDIT)}
    assert "artifact" in kinds, kinds
