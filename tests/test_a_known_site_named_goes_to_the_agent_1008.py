"""지목한 이름이 우리가 아는 사이트면 에이전트로 간다 (2026-10-08).

「위키백과에서 '○○' 문서를 열어 읽고, 반포된 해를 문서에 적힌 대로 한 줄로 알려줘」가 도구 0회·10초로 기억에서 답했다.
출처를 지목했어도 구체값 낱말표(가격·제목·목록…)에 안 걸리면 모델 판단으로 넘어갔기 때문이다.

그 조건은 「프로그램에서·현장에서」 같은 헛이름을 거르려던 것인데, 주소를 아는 이름에는 그 걱정이 없다.
낱말을 더 넣지 않고 **표에 있다는 사실**로 가른다. 운영 요청 1,673개에 대 보니 바뀌는 27개 중 22개는 이미 모델 판단으로
도구를 쓰던 요청, 5개는 가서 봐야 했는데 에이전트로 안 간 요청이었다.
"""
from __future__ import annotations

import pytest

from alture_jarvis.runtime import JarvisRuntime


@pytest.mark.parametrize("prompt", [
    "위키백과에서 '훈민정음' 문서를 열어 읽고, 반포된 해를 문서에 적힌 대로 한 줄로 알려줘.",
    "커리어넷에서 데이터 분석가 직업 정보를 찾아 하는 일과 필요 역량을 알려줘",
    "깃허브에서 요즘 설계 흐름이 어떤지 한번 알아봐줘",
])
def test_a_named_site_we_know_is_enough(prompt: str) -> None:
    assert JarvisRuntime._requires_named_source(prompt)


@pytest.mark.parametrize("prompt", [
    "프로그램에서 오류가 나는데 왜 그럴까",
    "현장에서 느낀 점을 정리해줘",
    "우리 회의에서 나온 말을 정리해줘",
    # 모르는 이름은 예전처럼 구체값을 물어야 한다.
    "골리에서 어떻게 생각하는지 궁금하네",
])
def test_a_name_we_do_not_know_still_needs_a_particular_ask(prompt: str) -> None:
    assert not JarvisRuntime._requires_named_source(prompt)


def test_an_unknown_name_with_a_particular_ask_still_goes() -> None:
    assert JarvisRuntime._requires_named_source("골리에서 무선마우스 상위 3개 가격 알려줘")


@pytest.mark.parametrize("prompt", [
    # 「에서」 꼴이 아니다 — 그래도 아는 사이트 이름이 있고 개수·제목을 물었다(실기에서 네 판 중 한 판이 기억으로 지어냈다).
    "네이버 뉴스 IT/과학 섹션 첫 화면의 헤드라인 5개를 번호 목록으로 알려줘.",
    "깃허브 트렌딩 목록 맨 위 5개의 이름과 별 수를 알려줘",
    "What are the top 3 trending repos on GitHub today?",
])
def test_a_known_site_mentioned_with_a_particular_ask_goes(prompt: str) -> None:
    assert JarvisRuntime._requires_named_source(prompt)


@pytest.mark.parametrize("prompt", [
    # 아는 사이트 이름은 있지만 구체값을 묻지 않았다 — 예전처럼 모델 판단에 맡긴다.
    "네이버가 요즘 어떤 회사인지 한마디로 말해줘",
    # 구체값은 물었지만 아는 사이트 이름이 없다.
    "우리 팀 회의 안건 3개를 정리해줘",
    # 영문 이름은 낱말 경계로 본다 — 다른 낱말 속의 글자열은 이름이 아니다.
    "List 3 things about githubbing as a hobby",
])
def test_a_mention_without_both_halves_is_left_to_the_model(prompt: str) -> None:
    assert not JarvisRuntime._requires_named_source(prompt)
