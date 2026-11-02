"""전사 상한이 창을 따라 커진다 (2026-10-31 대표 「걸음마다 첫 글자 70초」).

창을 192K 로 올렸는데 전사 상한은 131K 짝(18만 자) 그대로라 약 7.7만 토큰(창의 40%)에서 접혔고, 접힐 때마다 앞을 다시 읽었다.
"""
from alture_jarvis.transcript_policy import chat_transcript_budget, transcript_cap_chars, window_fitted_budget

SWIFT = "hf.co/ukisai/Swift-1.5-Qwen3.8-27B"


def test_small_and_usual_windows_keep_the_old_numbers() -> None:
    assert chat_transcript_budget(32768, SWIFT)[0] == 34406
    assert chat_transcript_budget(65536, SWIFT)[0] == 80281
    assert chat_transcript_budget(131072, SWIFT)[0] == 172032
    assert transcript_cap_chars(131072) == 180_000


def test_a_192k_window_is_no_longer_held_to_the_131k_cap() -> None:
    budget = chat_transcript_budget(196608, SWIFT)[0]
    assert budget > 180_000
    # 그 판의 실제 값: 18만 자를 보냈을 때 7.7만 토큰 — 자리가 넉넉하니 넓힐 수 있어야 한다(예전엔 18만 자 천장).
    assert window_fitted_budget(budget, num_ctx=196608, sent_chars=180_000, prompt_tokens=77_367, widen=True) > 180_000


def test_the_measured_fit_still_stops_overflow() -> None:
    # 창이 거의 찼으면 상한이 커져도 넣지 않는다 — 넘치지 않게 하는 것은 서버가 알려 준 토큰 수다.
    assert window_fitted_budget(263_782, num_ctx=196608, sent_chars=250_000, prompt_tokens=190_000, widen=True) < 250_000
