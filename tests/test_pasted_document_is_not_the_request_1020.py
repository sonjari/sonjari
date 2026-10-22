"""붙여넣은 글 속 사이트 · 숫자는 시킨 일이 아니다 (2026-10-20 대표 실사용 판 6c8de096).

「그러면 mcp 는 … 따로 하는 거는 어떤데」 밑에 설계 문서를 붙여넣었더니, 문서 속 예시에서
「깃허브에서 하기 · 다나와에서 하기 · 노션에서 하기 · 사이트 정렬·필터로 보기」가 섰다. 사람은 생각을 물었다.
운영 요청 2,454개로 재 보니 바뀌는 것은 6개였고, 진짜 요구를 잃은 판은 없었다(`plan.own_words`).
"""

from __future__ import annotations

from alture_jarvis.answer_gate import named_sources
from alture_jarvis.plan import extract, own_words

DOC = (
    "확장 설계 초안\n"
    "가르칠 때 사용자가 보는 것은 읽어 주기 카드다. 녹화기는 저장됨으로 끝난다. 우리는 확인할 것까지 보여 준다.\n"
    "예를 들어 다나와에서 가장 싼 값을 찾는 레시피는 걸음마다 확인 조건이 붙는다. 깃허브에서 저장소를 읽는 일도 같다.\n"
    "노션에서 회의록을 찾는 일은 노션 MCP 가 있으면 그 도구로 하고, 없으면 브라우저로 한다. 값마다 출처가 붙는다.\n"
    "바깥 서버가 준 값도 근거 원장에 들어간다. 원장에 없는 값은 답에 쓰지 않는다. 이것이 우리 확장의 불변식이다.\n"
    "쓰기 도구는 모든 권한 모드에서 승인을 받는다. 읽기 도구는 자동 모드부터 바로 쓰고 한 줄 영수증을 남긴다.\n"
    "레시피를 다시 돌릴 때는 걸음마다 맞았는지 틀렸는지가 붙은 실행 영수증이 남는다. 사이트가 바뀌면 그 걸음에서 멈춘다.\n"
    "남의 재생기는 화면이 바뀌어도 눌러 버리고 끝났다고 말한다. 우리는 멈춘 자리와 까닭을 사람에게 그대로 보여 준다.\n"
)


def _labels(prompt: str) -> list[str]:
    return [item.label for item in extract(prompt)]


def test_sites_inside_a_pasted_design_doc_are_not_requirements() -> None:
    prompt = "그러면 mcp 는 내부 툴이라 따로 하는 거는 어떤데\n\n\n" + DOC + "\n\n클로드는 이렇게 하자고 하네"
    assert _labels(prompt) == []
    assert "노션" not in named_sources(prompt)


def test_the_same_doc_with_a_real_ask_keeps_what_the_person_asked() -> None:
    prompt = "아래 문서 읽고 다나와에서 최저가 3개 찾아 줘\n\n" + DOC
    labels = _labels(prompt)
    assert any("다나와" in label for label in labels)
    assert not any("깃허브" in label or "노션" in label for label in labels)


def test_one_long_instruction_is_the_request_itself() -> None:
    """글 전체가 한 덩어리면 그 글이 곧 지시다 — 가르지 않는다."""
    assert own_words(DOC + "다나와에서 찾아 줘") is None


def test_a_long_block_that_asks_is_not_pasted_text() -> None:
    """2026-10-07 에 37판을 잃은 꼴 — 긴 지시문 · 인계문은 시키는 문장이 들어 있어 사람 말로 남는다."""
    task = (
        "깃허브의 오픈소스 코딩 에이전트 저장소를 직접 읽고 아래 여섯 질문의 답을 마크다운 파일(pi.md)로 정리해줘. "
        "README 만 보지 말고 packages 폴더의 소스 파일을 열어서 읽어라. 질문마다 근거가 된 파일의 깃허브 주소와 그 자리의 "
        "원문을 같이 적어라. 소스에서 찾지 못한 것은 추측하지 말고 못 찾음이라고 적어라. 질문 1 환경변수를 어떻게 넘기나. "
        "질문 2 끝났다를 누가 판정하나. 질문 3 작은 모델을 위한 장치가 있나. 질문 4 거짓 완료를 막는 장치가 있나. "
        "질문 5 작업 폴더를 어떻게 가두나. 질문 6 대화가 길어지면 어떻게 하나 — 컨텍스트 압축이 언제 일어나나."
    )
    prompt = task + "\n\n파일 맨 위에 읽은 날짜와 읽은 파일 목록을 적어라."
    assert own_words(prompt) is None
    assert any("깃허브" in label for label in _labels(prompt))


def test_a_noun_phrase_ending_in_hal_geot_is_not_an_ask() -> None:
    """표 머리 「기능 밖 (지켜야 할 것)」 때문에 문서 덩어리가 지시로 읽혔다."""
    table = "장면\t보는 것\t기능 밖 (지켜야 할 것)\n" + DOC
    prompt = "이거 어떤데\n\n" + table + "\n\n클로드 생각이래"
    assert _labels(prompt) == []
