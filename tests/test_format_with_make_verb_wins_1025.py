"""만드는 말이 붙은 형식이 시킨 형식이다 (2026-10-25 판 891b5d6a).

「소개 PPT를 8장으로 만들어 줘. 자료: … 워드 · 엑셀 · 한글 문서를 직접 다룬다」가 규칙 순서 때문에 .xlsx 를 요구해
PPTX 를 제대로 굽고도 「열 수 있는 산출물 없음 · partial」로 끝났다. 지난 5,239판에 대 보니 바뀐 판은 이 하나였다.
"""

from alture_jarvis.plan import artifact_extensions


def test_material_format_names_do_not_beat_the_made_format() -> None:
    prompt = (
        "「손자리」를 처음 듣는 사람에게 소개하는 PPT를 8장 안팎으로 만들어 줘. "
        "자료: 손자리는 PC의 파일과 워드 · 엑셀 · 한글 문서를 직접 다룬다. 장표는 PPTX로 굽는다."
    )
    assert artifact_extensions(prompt) == (".pptx",)


def test_rule_order_still_wins_when_both_or_neither_are_made() -> None:
    # 둘 다 만드는 말이 붙으면 예전처럼 규칙 순서(엑셀이 앞).
    assert artifact_extensions("엑셀로 정리해서 워드 보고서로 만들어 줘") == (".xlsx",)
    # 둘 다 안 붙으면 예전처럼 규칙 순서.
    assert artifact_extensions("엑셀과 워드 차이 알려 줘") == (".xlsx",)


def test_make_verb_does_not_cross_a_sentence() -> None:
    # 「다룬다.」 뒤 다른 문장의 「만들어」는 엑셀에 붙지 않는다 — 워드에 붙는다.
    assert artifact_extensions("이 도구는 엑셀을 다룬다. 결과는 워드 파일로 만들어 줘") == (".docx",)
