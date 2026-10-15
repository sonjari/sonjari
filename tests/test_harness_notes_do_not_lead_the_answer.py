"""하네스 안내문이 답 첫 줄로 새지 않는다 (2026-10-02 공개 전 필수 ③).

운영 판 답이 「[시스템] ★ 아직 남은 것이 있다. 검색을 되풀이하지 않고 지금까지 읽은 근거로 산출물을 만들어라.」로 시작했다.
모델이 대화에 끼운 안내의 모양을 흉내 낸 것이다. 앞머리 줄만 걷고, 본문 중간의 같은 낱말은 건드리지 않는다.
"""

from __future__ import annotations

from alture_jarvis.runtime import strip_leaked_thinking

LEAKED = (
    "[시스템] ★ 아직 남은 것이 있다. 검색을 되풀이하지 않고 지금까지 읽은 근거로 산출물을 만들어라.\n\n"
    "정직하게 다시 정리하겠습니다.\n\n## 최종 답"
)


def test_the_leading_harness_line_is_removed() -> None:
    assert strip_leaked_thinking(LEAKED).startswith("정직하게 다시 정리하겠습니다.")
    assert strip_leaked_thinking("[시스템 안내]\n하나\n\n답입니다").startswith("하나")


def test_the_same_words_in_the_body_stay() -> None:
    body = "표를 만들었습니다.\n참고: [시스템] 이라는 말은 로그에서 본 것입니다."
    assert strip_leaked_thinking(body) == body
    assert strip_leaked_thinking("") == ""
