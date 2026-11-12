"""11-11 맥 판 — 28걸음 뒤 최종 답이 「…한 번 눌러 본다.」(다음 걸음 예고)인데 그대로 답으로 나갔다.

예고 그물의 반말 혼잣말 끝말표가 「해 본다」만 알았다. 「동사 + 아/어 + 본다」 모양 전체로 잡는다 — 양방향.
"""
from __future__ import annotations

import pytest

from alture_jarvis.promise_gate import _only_a_promise


@pytest.mark.parametrize("answer", [
    "게이트 뒤의 실제 다운로드가 자동화에서 되는지 한 번 눌러 본다.",   # 실제 판
    "다운로드 버튼을 찾아 다시 열어 본다.",
    "목록에서 두 번째 상품을 골라 보자.",
    "설정 화면으로 들어가 봐야겠다.",
])
def test_try_verb_monologue_is_a_promise(answer: str) -> None:
    assert _only_a_promise(answer)


@pytest.mark.parametrize("answer", [
    "저녁에 영화를 본다.",                                   # 「를 + 본다」 — 시도 꼴 아님
    "로지텍 MX Master 3S 는 다나와 최저가 109,000원이다.",
    "세 가게 모두 찾아 엑셀로 정리했습니다. 파일: 문서\\Sonjari\\가격.xlsx",
    "결과를 확인해 보니 라이선스는 MIT 다.",
])
def test_results_and_ordinary_sentences_are_not_promises(answer: str) -> None:
    assert not _only_a_promise(answer)


def test_old_ending_table_really_missed_the_real_answer() -> None:
    """양방향: 고치기 전 끝말표(「해 본다」류)만으로는 이 답을 못 잡았다."""
    from alture_jarvis.promise_gate import _TRY_NEXT_ENDING

    assert not _TRY_NEXT_ENDING.search("게이트 뒤의 실제 다운로드가 자동화에서 되는지 한 번 눌러 본다.")
