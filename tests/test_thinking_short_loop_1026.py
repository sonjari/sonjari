"""생각이 짧은 토막 하나를 되풀이하면 끊는다 (2026-10-26 06:05 판 「1:1:1:…」 8,192토큰 · 답 0자)."""

from alture_jarvis.ollama import thinking_is_looping

_HEAD = "자료에서 소식 다섯 개를 골라 장표 여섯 장으로 나눈다. 먼저 표지와 목차를 정하고, " * 4


def test_short_unit_loop_after_real_thought_is_cut():
    assert thinking_is_looping(_HEAD + "1:" * 400)


def test_single_char_and_three_char_loops_are_cut():
    assert thinking_is_looping(_HEAD + "a" * 600)
    assert thinking_is_looping(_HEAD + "ab," * 200)


def test_short_loop_too_short_is_left_alone():
    # 끝 300자를 다 채우기 전에는 끊지 않는다 — 잠깐 이어진 「1:1:」은 정상일 수 있다.
    assert not thinking_is_looping(_HEAD * 3 + "1:" * 50)


def test_normal_korean_thought_is_not_cut():
    text = ("사용자는 국내 AI 에이전트 소식을 원한다. 첫 번째 기사는 스타트업 베타 공개이고, 두 번째는 대기업 시범 도입이다. "
            "세 번째 기사는 공공기관 한글 문서 실증, 네 번째는 로컬 모델 앱, 다섯 번째는 오작동 사례다. "
            "표지에는 제목과 날짜를 넣고, 마지막 장에는 출처 다섯 곳을 적는다. 숫자는 자료에 있는 것만 쓴다. ") * 3
    assert not thinking_is_looping(text)


def test_table_like_thought_is_not_cut():
    rows = "".join(f"| {i}번 장 | 제목 {i} | 근거 {i}곳 |\n|---|---|---|\n" for i in range(1, 30))
    assert not thinking_is_looping(_HEAD + rows)
