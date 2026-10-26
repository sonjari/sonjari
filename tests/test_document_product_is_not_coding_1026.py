"""만들 것이 문서면 「코드 · HTML · 프로그램」은 소재다 (2026-10-26 장표 판 26개 중 9개가 코딩 갈래 · 0a39f113 은 code_unverified).

운영 요청 5,252개에 옛 · 새를 대 보니 코딩 → 아님 16(장표 · 책 조사 .md · ChatGPT 질문 엑셀 · 깃허브 조사 · 계획 요청 · 붙여 넣은 글),
아님 → 코딩 0. 바뀐 16판 모두 코딩이 아니었다.
"""

from alture_jarvis.plan import wants_code


def test_document_decks_that_mention_code_are_not_coding() -> None:
    assert not wants_code("손자리 소개 PPT 를 8장으로 만들어 줘. 자료: 클로드 코드가 MCP 로 부른다. 코드는 깃허브에 공개돼 있다.")
    assert not wants_code("IR 장표를 PPTX로 만들어 줘. 대표 김예시(학원 프로그램 회사 7년).")
    assert not wants_code("발표 PPT 7장을 만들어 줘. 먼저 html 없이 한 번 불러 규칙을 받고 장마다 HTML 을 직접 디자인해 넣어.")
    assert not wants_code("YES24 에서 파이썬 프로그래밍 도서 3권을 조사해서 마크다운(.md) 문서로 만들어줘")


def test_real_coding_stays_coding() -> None:
    assert wants_code("calc.py 를 고치고 pytest 로 통과를 확인해")
    assert wants_code("파이썬 스크립트 짜줘")
    assert wants_code("HTML 로 계산기 페이지 만들어 줘")
    # 문서를 만들어도 이름을 댄 코드 파일을 고치라면 코딩이다.
    assert wants_code("report.py 를 고쳐서 결과를 엑셀로 만들어 줘")
