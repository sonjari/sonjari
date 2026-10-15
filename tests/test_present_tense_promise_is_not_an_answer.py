"""현재형 존댓말 예고는 답이 아니다 (2026-10-01 밤 운영 판 b9f90b2c·c430d75c·54f2d6b3 — 세 판 연속).

허깅페이스를 9걸음 읽고 최종 답이 「목록에 모델명이 안 나와서 snapshot으로 실제 링크를 확인합니다.」였고 complete 로 나갔다.
그 답이 대화에 남자 다음 판들도 「…검색합니다」·「…조사 중입니다」(대화 갈래, 걸음 0)로 끝났다.
넣기 전에 재 봤다: 운영 답 2,469개 중 새 판정에만 걸린 것 4개 — 전부 진짜 예고, 오탐 0.
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import _only_a_promise, announces_present_action

SEEN = [
    "목록에 모델명이 안 나와서 snapshot으로 실제 링크를 확인합니다.",
    "허깅페이스 트렌딩 모델 목록 페이지가 열렸습니다. 이제 16GB VRAM에서 돌릴 수 있는 모델들을 찾기 위해 검색합니다.",
    "16GB VRAM에서 잘 돌아가는 최신 AI 모델을 허깅페이스(Hugging Face)에서 조사 중입니다.",
    "Paperclip(한국 오픈소스 에이전트 프로젝트)을 확인합니다.",
]


@pytest.mark.parametrize("text", SEEN + ["다음 페이지를 열어 봅니다.", "상세 페이지로 들어갑니다."])
def test_present_tense_next_step_is_caught(text: str) -> None:
    assert announces_present_action(text)
    assert _only_a_promise(text)


@pytest.mark.parametrize("text", [
    "세 곳의 가격을 확인했습니다.",
    "8GB 가 가장 많습니다.",
    "Qwen3 14B 는 Q4 로 약 9GB 를 씁니다.",
    "| 모델 | 크기 |\n|---|---|\n| Qwen3 14B | 9GB |\n\n표의 값은 허깅페이스 목록에서 확인합니다.",
])
def test_real_answers_are_not_caught(text: str) -> None:
    assert not announces_present_action(text)


def test_the_router_and_the_previous_turn_check_use_it() -> None:
    """대화 갈래(걸음 0)의 「조사 중입니다」도 에이전트로 넘긴다 — 두 자리 모두 같은 판정을 쓴다."""
    import inspect

    from alture_jarvis import runtime

    source = inspect.getsource(runtime)
    assert source.count("announces_present_action(") >= 2
