"""내용을 요청 안에 다 적어 준 산출물은 「근거 읽기」 · 자료 속 사이트를 요구로 세우지 않는다 (2026-10-26 거짓 「일부만 됨」).

장표 판 셋(fa828a92 · 8c9de860 · c81cf6b6)이 「장 구성: ① … 깃허브에 Apache-2.0 …」으로 PPT 를 굽고도 「일부만 됨」이었다.
운영 5,252판에 옛 · 새를 대 보니 바뀐 판 13(모두 손자리 소개 장표) · 요구가 늘어난 판 0 · 「일부만 됨 → 완료」 3.
"""

from alture_jarvis.answer_gate import named_sources
from alture_jarvis.plan import extract, supplied_content_head

DECK = ("손자리를 소개하는 발표 PPT 7장을 만들어 줘(제목: 「손자리 소개」). 차분한 흰 바탕 디자인으로. "
        "장 구성: ① 표지 ② 손자리가 뭔가(내 PC 에서 도는 로컬 AI) ③ 어떻게 쓰나(클로드가 손자리를 불러 읽기와 조사를 맡긴다) "
        "④ 믿을 수 있게 하는 장치 ⑤ 설치(마이크로소프트 스토어) · 공개(깃허브, Apache-2.0)")


def _labels(prompt: str) -> list[str]:
    return [r.label for r in extract(prompt, has_named_source=bool(named_sources(prompt)), must_observe=True,
                                     observe_from=frozenset({"web", "named"}), own_from=prompt)]


def test_a_deck_with_its_content_written_in_needs_no_reading_or_site() -> None:
    assert supplied_content_head(DECK) is not None
    assert _labels(DECK) == ["실제 산출물 파일 만들기"]


def test_research_or_acting_on_something_keeps_the_old_requirements() -> None:
    """운영 대 보기에서 첫 판정이 같이 빼던 꼴들 — 예전대로 둔다."""
    for prompt in (
        "AI 에이전트 시장을 조사해서 PPT 5장으로 만들어 줘. 장 구성: ① 시장 ② 경쟁 ③ 전망 ④ 결론",
        "자비스, 로보메타핏 블로그에 새 글 하나 써서 임시저장까지 해줘. 주제: 학부모 상담 - 첫째 - 둘째 - 셋째",
        "src/alture_jarvis/delegated_branch.py 에 함수 하나를 더해줘. 배경: ① 작업 폴더 ② 가지 ③ 정리",
        "레딧 r/ClaudeAI 의 이번 달 인기 글에서 문서로 정리해 줘. 기준: - 개발자 아님 - 대화창만 - 바로 따라 함",
    ):
        assert supplied_content_head(" ".join(prompt.split())) is None, prompt
