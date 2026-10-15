"""「○○ 파일로 줘」는 파일 요청이다 · 도구 없이 쓴 답이 「저장했습니다」라고 하면 답이 아니다 (2026-10-13).

네 번 이어 묻기(4B · 창 32K)의 셋째 판 — 「방금 내용을 한글이나 워드 파일로 전달해 줘」가 요구 0개로 돌았다. 그래서 도구 없이
바로 답하는 길로 갔고, 모델은 「…txt 파일로 저장되었습니다」라며 있지도 않은 경로를 댔다. 작은 카드로 쓰는 사람이 같은 날 말한
「존재하지 않는 위치에 파일을 저장하려 한다」와 같은 모양이다.

- 산출물 판정이 동사를 봤다(「정리해 줘」·「만들어 줘」). 형식 이름에 「로」가 붙은 **모양**으로 본다.
- 바로 답하는 길에는 손이 없다. 거기서 나온 「새 파일을 저장했습니다」는 언제나 거짓이다 — 손이 있는 길로 보낸다.

표본의 파일 이름 · 경로는 지어낸 것이다.
"""
from __future__ import annotations

import inspect

import pytest

from alture_jarvis import plan, runtime
from alture_jarvis.runtime import _claimed_files


@pytest.mark.parametrize("ask", [
    "방금 내용을 한글이나 워드 파일로 전달해 줘",
    "한글파일 또는 워드파일로 전달해줘",
    "이거 워드로 줘",
    "엑셀 파일로 보내줘",
    "워드 파일로 달라",
    "이 내용 한글 문서로 받고 싶어",
    "방금 표 엑셀로 뽑아 줄래",
    "결과는 MD 파일로 써 줘",
])
def test_a_format_in_the_receiving_shape_is_a_file_request_whatever_the_verb(ask: str) -> None:
    assert plan.wants_an_artifact(ask), ask
    assert any(requirement.kind == "artifact" for requirement in plan.extract(ask))


@pytest.mark.parametrize("ask", [
    "워드로 된 문서 읽어줘",                  # 이미 있는 것
    "엑셀로 저장된 파일 찾아줘",
    "엑셀로 뭘 할 수 있어?",                  # 묻는 말
    "이 폴더의 파일로 뭘 만들 수 있지",
    "한글로 번역해줘",                        # 한글 = 말
    "한글로 답해줘",
    "키워드로 검색해줘",                      # 「워드」가 든 다른 낱말
    "경력 프로파일로 가는 게 낫지",            # 「파일」이 든 다른 낱말
    "결과만 알려줘. 파일로 만들 필요는 없어",   # 바로 뒤에서 거둔다
    "엑셀로 하지 말고 표로만 보여줘",
    "pdf로 저장해줘",                         # 이 도구가 못 만드는 형식은 요구로 세우지 않는다
])
def test_the_same_words_in_other_shapes_are_not(ask: str) -> None:
    assert not plan.wants_an_artifact(ask), ask


def test_either_of_two_formats_is_accepted() -> None:
    """「한글이나 워드」 — 한글 파일로 만들어도 워드 파일로 만들어도 시킨 것을 채운다."""
    assert set(plan.artifact_extensions("방금 내용을 한글이나 워드 파일로 전달해 줘")) == {".hwpx", ".hwp", ".docx"}
    assert set(plan.artifact_extensions("한글파일 또는 워드파일로 전달해줘")) == {".hwpx", ".hwp", ".docx"}
    assert set(plan.artifact_extensions("엑셀 or 워드로 정리해줘")) == {".xlsx", ".docx"}
    # 하나만 말했으면 예전 그대로다.
    assert plan.artifact_extensions("워드 파일로 정리해 줘") == (".docx",)
    assert plan.artifact_extensions("한글 문서로 만들어줘") == (".hwpx", ".hwp")


def test_a_direct_answer_that_says_it_saved_a_new_file_is_caught() -> None:
    ask = "방금 내용을 한글이나 워드 파일로 전달해 줘"
    lie = "현재 대화에서 논의된 내용을 정리한 문서는 **C:\\Users\\someone\\Documents\\가상\\가상_전략_20261013.txt** 파일로 저장되었습니다."
    assert _claimed_files(lie, ask) == ["C:\\Users\\someone\\Documents\\가상\\가상_전략_20261013.txt"]
    assert _claimed_files("가상_보고서.docx 파일을 만들었습니다. 열어 보세요.", "워드로 줘")
    assert _claimed_files("요청하신 표를 가상_표.xlsx 로 저장했어요.", "엑셀로 줘")


@pytest.mark.parametrize("answer, asked", [
    ("가상_보고서.docx 를 열어 보니 세 쪽입니다.", "가상_보고서.docx 읽어줘"),                      # 질문에 있던 파일
    ("가상_보고서.docx 는 이미 저장했습니다 — 아까 만드신 그 파일입니다.", "아까 만든 가상_보고서.docx 어디 있지"),
    ("README.md 를 먼저 읽어 보시길 권합니다.", "뭐부터 읽지"),                                   # 끝난 말이 없다
    ("엑셀에서 [파일] → [다른 이름으로 저장]을 눌러 report.xlsx 로 저장하세요.", "엑셀 저장 방법"),   # 하는 법 설명
    ("저장은 아직 안 했습니다. 워드 파일로 만들까요?", "정리해줘"),                                 # 파일 이름이 없다
    ("작업을 완료했습니다.", "해줘"),
])
def test_other_mentions_of_files_are_left_alone(answer: str, asked: str) -> None:
    assert _claimed_files(answer, asked) == []


def test_a_file_named_earlier_in_the_conversation_is_not_a_new_claim() -> None:
    earlier = "가상_보고서.docx 를 만들어 두었습니다(앞 판의 답)."
    assert _claimed_files("가상_보고서.docx 에 저장했습니다.", "다시 알려줘", "", earlier) == []


def test_the_router_sends_such_a_draft_to_the_side_that_has_hands() -> None:
    source = inspect.getsource(runtime)
    block = source[source.index("claimed = _claimed_files("):]
    block = block[:block.index("이제야 답이다")]
    assert "discard_draft()" in block and '"reason": "answer_claimed_a_file"' in block
    assert 'return "agent", "", {"route_reason": "claimed_a_file"}' in block
    # 숫자 검사 **뒤**, 답으로 내보내기 **앞**이다.
    assert source.index("answer_had_unsourced_particulars") < source.index("claimed = _claimed_files(") < source.index('"route": "answer", "reason": "model_selected"')
