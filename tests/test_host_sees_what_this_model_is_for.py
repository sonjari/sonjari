"""바깥 AI 가 이 PC 의 손자리 모델에 맞춰 맡길 일을 나눈다 (2026-10-01 밤 대표: 「9B 에게 시킬 일, 20B 이상에게 시킬 일 — 4B·8GB 도」).

모든 PC 에 같은 문장을 박으면 4B 노트북에서도 「조사→문서 9/10」을 믿게 된다. 그래서 사용법(`sonjari_guide`) 끝에
**지금 모델 크기**로 고른 칸을 붙이고, 코드 일을 맡겼는데 코드 모델이 작으면 결과에 `model_hint` 를 싣는다.
판정은 결정론이다 — 작은 모델에게 「너보다 나은 모델」을 묻지 않는다.
"""

from __future__ import annotations

from alture_jarvis.hf_catalog import code_upgrade, looks_like_code_task, model_fit_note, model_hint, tier_of


def test_each_size_gets_its_own_row() -> None:
    assert tier_of(4)[0].startswith("작은 모델")
    assert tier_of(9)[0].startswith("중간 모델")
    assert tier_of(27)[0].startswith("큰 모델")
    assert "9/10" in tier_of(9)[3] and "안 쟀습니다" in tier_of(4)[3]


def test_the_note_names_this_pcs_model_and_the_upgrade() -> None:
    note = model_fit_note("qwen3.5:9b", "qwen3.5:9b", 14.9, code_upgrade(14.9, "qwen3.5:9b"))
    assert "`qwen3.5:9b` (9B)" in note and "중간 모델" in note
    assert "Qwen 3.8 27B" in note and "규칙 추천" in note
    small = model_fit_note("qwen3.5:4b", "qwen3.5:4b", 5.0, code_upgrade(5.0, "qwen3.5:4b"))
    assert "작은 모델" in small.split("크기별 기준")[0] and "더 큰 모델이 들어갑니다" not in small


def test_a_code_task_on_a_small_model_gets_a_hint_and_research_does_not() -> None:
    upgrade = code_upgrade(14.9, "qwen3.5:9b")
    assert "코드 탭 모델 이름" in model_hint("이 저장소의 main.py 버그 고쳐줘", upgrade)
    assert model_hint("사람인에서 여수 회계 공고 3개 찾아 엑셀로", upgrade) == ""
    assert model_hint("main.py 버그 고쳐줘", None) == ""
    assert looks_like_code_task("refactor this script") and not looks_like_code_task("교보문고 책 가격")


def test_instructions_tell_the_host_to_pass_the_hint_on() -> None:
    from alture_jarvis.mcp_server import INSTRUCTIONS

    assert "model_hint" in INSTRUCTIONS and len(INSTRUCTIONS) <= 1500
