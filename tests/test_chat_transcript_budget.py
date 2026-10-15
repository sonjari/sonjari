"""대화 판 전사 예산은 모델 문맥 창의 비율 (2026-09-24 노트북 실측: 4B 에 73.8K 토큰을 밀어 넣어 사고가 되풀이됐다)."""

from __future__ import annotations

from alture_jarvis.agent import chat_transcript_budget, is_small_model


def test_small_models_are_recognised_by_their_size_tag():
    for small in ("qwen3.5:4b", "gemma4:e4b", "gemma3:4b", "llama3.2:3b", "qwen3:1.7b", "qwen3:0.6b"):
        assert is_small_model(small), small
    # 「a3b」는 활성 파라미터 — 35B 모델이다.
    for big in ("qwen3.6:35b-a3b", "gemma4:26b", "qwen3.5:14b", "qwen3.5:9b", "plopfit-gemma4-qat", ""):
        assert not is_small_model(big), big


def test_the_laptop_4b_gets_a_third_of_its_window():
    budget, page = chat_transcript_budget(77_824, "qwen3.5:4b")
    # 예전 값 180,000자(≈9만 토큰)는 창(77,824)보다 컸다 — 상한이 없던 셈이다.
    assert budget < 77_824 * 2 * 0.5
    assert 40_000 <= budget <= 55_000
    assert page <= budget // 4


def test_the_big_model_keeps_about_what_it_had():
    budget, page = chat_transcript_budget(131_072, "qwen3.6:35b-a3b")
    assert 160_000 <= budget <= 180_000
    assert page == 30_000


def test_a_tiny_window_still_leaves_room_to_work():
    budget, _ = chat_transcript_budget(8_192, "llama3.2:3b")
    assert budget >= 12_000


def test_a_small_model_on_a_32k_window_still_gets_a_working_budget():
    budget, page = chat_transcript_budget(32_768, "qwen3.5:4b")
    # 비율(35%)이었으면 약 1.7만 자 — 페이지 하나 겨우. 모델이 감당하는 양으로 정하면 창의 75% 안에서 3.6만 자.
    assert 35_000 <= budget <= 37_000
    assert budget <= (32_768 - 8_192) * 0.75 * 2
