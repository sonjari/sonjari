"""「돌려받을 항목」 검사 — 굵은 제목 줄 **안**에 이름과 값이 같이 있는 꼴 (2026-11-20 맥 0.4.49 날씨 판).

「**오늘 서울 날씨: 최저 기온 -3°, 최고 기온 3° (맑음)**」가 제목으로 잡히고 아래 줄이 없어 met=False(「비었다」)였다.
"""
from alture_jarvis.outbound import check_needs


def test_values_inside_a_bold_heading_line_count():
    answer = "네이버에서 오늘 서울 날씨를 확인했습니다.\n\n**오늘 서울 날씨: 최저 기온 -3°, 최고 기온 3° (맑음)**"
    assert [i["met"] for i in check_needs(["최저 기온", "최고 기온"], answer)] == [True, True]


def test_unobtained_value_inside_heading_is_not_filled():
    out = check_needs(["최저 기온"], "**오늘 날씨: 최저 기온 확인 못 함, 최고 기온 3°**")[0]
    assert out["met"] is None and out.get("negative")


def test_a_title_word_after_the_name_is_not_a_value():
    assert check_needs(["가격"], "**가격 비교**\n\n")[0]["met"] is False
    assert check_needs(["가격"], "**가격 비교**\n\n| 가게 | 값 |\n|---|---|\n| A | 1000 |")[0]["met"] is True


def test_colon_value_in_heading():
    assert check_needs(["라이선스"], "**라이선스: MIT**")[0]["met"] is True
