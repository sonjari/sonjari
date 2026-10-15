"""손으로 만든 검색어의 한 글자 오타는 사용자가 쓴 말로 (2026-10-01 스토어 촬영 판 「파이서」)."""

from urllib.parse import parse_qs, urlparse

from alture_jarvis.search_typo import repair_query, repair_search_url

REQUEST = "교보문고에서 '파이썬' 책 3권을 찾아 제목·판매가·적립 포인트를 엑셀로 정리해 줘"


def test_the_kyobo_url_from_the_capture_is_repaired():
    # 실제로 모델이 만든 주소 그대로 — 「파이서」.
    url = "https://search.kyobobook.co.kr/search?keyword=%ED%8C%8C%EC%9D%B4%EC%84%9C&gbCode=TOT&target=total"
    fixed = repair_search_url(url, REQUEST)
    params = parse_qs(urlparse(fixed).query)
    assert params["keyword"] == ["파이썬"]
    assert params["gbCode"] == ["TOT"] and params["target"] == ["total"]


def test_site_search_query_is_repaired_and_particles_do_not_hide_the_word():
    assert repair_query("파이서 책", REQUEST) == "파이썬 책"
    assert repair_query("무섧마우스", "다나와에서 무선마우스 3개 비교해 줘") == "무선마우스"


def test_words_the_user_wrote_or_chose_are_left_alone():
    assert repair_query("파이썬", REQUEST) == "파이썬"
    # 요청에 없는 다른 낱말(일부러 넓힌 검색)은 후보가 없어 그대로.
    assert repair_query("프로그래밍 입문", REQUEST) == "프로그래밍 입문"
    assert repair_query("python", REQUEST) == "python"


def test_ambiguous_or_far_words_are_not_guessed():
    # 「파이서」에 한 글자 차이 후보가 둘(파이썬·파이선)이면 고르지 않는다.
    assert repair_query("파이서", "파이썬 책이랑 파이선 책 둘 다") == "파이서"
    # 첫 글자가 다르면 같은 말로 보지 않는다.
    assert repair_query("바이썬", REQUEST) == "바이썬"


def test_urls_without_a_search_key_or_without_change_come_back_identical():
    plain = "https://product.kyobobook.co.kr/detail/S000202532365"
    assert repair_search_url(plain, REQUEST) == plain
    ok = "https://search.kyobobook.co.kr/search?keyword=%ED%8C%8C%EC%9D%B4%EC%8D%AC"
    assert repair_search_url(ok, REQUEST) == ok
