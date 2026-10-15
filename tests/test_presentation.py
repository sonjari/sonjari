from __future__ import annotations

from alture_jarvis.presentation import PresentationPolicy


def test_short_conversational_answer_is_voice() -> None:
    decision = PresentationPolicy().decide("준비 완료. 지금 정상 작동 중입니다.")
    assert decision.mode == "voice"
    assert decision.spoken_text == "준비 완료. 지금 정상 작동 중입니다."
    assert decision.display_content


def test_long_answer_becomes_hybrid_with_short_spoken_summary() -> None:
    content = (
        "핵심 결론은 로컬 처리가 가장 안전합니다. "
        "카메라와 음성은 PC 안에서 처리합니다. "
        "조사 결과와 출처는 화면에서 확인할 수 있습니다. "
        "승인이 필요한 작업은 별도 카드로 표시합니다."
    )
    decision = PresentationPolicy().decide(content)
    assert decision.mode == "hybrid"
    assert decision.spoken_text.startswith("로컬 처리가 가장 안전합니다.")
    assert "화면에 정리" not in decision.spoken_text
    assert len(decision.spoken_text) < len(content)
    assert decision.display_content == content
    assert "sentence_count" in decision.reasons


def test_structured_content_is_not_read_aloud() -> None:
    content = """핵심 결론: 카메라는 정상 작동 중입니다.

| 항목 | 상태 |
|---|---|
| 카메라 | 정상 |

```python
print("hello")
```"""
    decision = PresentationPolicy().decide(content)
    assert decision.mode == "hybrid"
    assert decision.spoken_text.startswith("카메라는 정상 작동 중입니다.")
    assert "화면에" not in decision.spoken_text
    assert "table" in decision.reasons
    assert "code" in decision.reasons


def test_screen_override_and_legacy_speak_false() -> None:
    policy = PresentationPolicy()
    assert policy.decide("짧은 답변", requested_mode="screen").mode == "screen"
    legacy = policy.decide("짧은 답변", legacy_speak=False)
    assert legacy.mode == "screen"
    assert legacy.spoken_text == ""


def test_research_always_has_visual_result() -> None:
    decision = PresentationPolicy().decide("결론은 한 문장입니다.", force_visual=True)
    assert decision.mode == "hybrid"
    assert "analysis_or_research" in decision.reasons


def test_research_acknowledgement_is_contextual_and_varied() -> None:
    policy = PresentationPolicy()

    first = policy.research_acknowledgement("여수 내일 날씨 한번 알아봐줘")
    second = policy.research_acknowledgement("여수 내일 날씨 한번 알아봐줘")

    assert "여수 내일 날씨" in first
    assert "여수 내일 날씨" in second
    assert first != second


def test_hybrid_spoken_summary_is_capped_for_fast_tts() -> None:
    policy = PresentationPolicy(short_max_chars=40, hybrid_summary_max_chars=48)
    content = (
        "사용자님이 바로 실행할 수 있는 현실적인 방법을 우선 추천합니다. "
        "업무 흐름을 깨지 않도록 핵심 순서와 주의할 점을 함께 정리했습니다."
    )

    decision = policy.decide(content)

    assert decision.mode == "hybrid"
    assert len(decision.spoken_text) <= 49
    assert decision.display_content == content


def test_hybrid_prefers_complete_short_sentence_over_truncated_signal_sentence() -> None:
    policy = PresentationPolicy(hybrid_summary_max_chars=72)
    content = (
        "사용자님, 구성원을 보니 아주 흥미로운 조합입니다. "
        "30대부터 50대까지 연령대가 다양하기 때문에, 기술적 난이도보다는 실질적 효용성과 "
        "결과물의 가시성에 초점을 맞추는 것이 사용자님의 역량을 가장 잘 보여주는 방법입니다."
    )

    decision = policy.decide(content)

    assert decision.mode == "hybrid"
    assert decision.spoken_text == "사용자님, 구성원을 보니 아주 흥미로운 조합입니다."
    assert not decision.spoken_text.endswith("…")
