"""한 사이트의 한글 · 영문 이름은 **한 곳**이다 (2026-10-19 판 51f35b07).

1. 「깃허브 저장소 …」와 「깃허브 계정」 · 배운 표의 「GitHub」가 같이 걸려 진행에 「GitHub에서 하기」 · 「깃허브에서 하기」 두 줄이
   섰다. 이름만 보고 따로 셌다 — 주소(github.com)로 묶는다.
2. 맡긴 쪽의 항목 「로그인된 깃허브 계정 이름」에 답은 「**현재 로그인된 GitHub 계정: `garam-sonjari`**」였다. 같은 사이트의
   두 표기를 한 말로 보고, 「이름: 값」 줄의 이름이 항목 낱말을 다 담으면(머리 낱말 「이름」 하나는 빠져도) 그 자리로 본다.
"""

from __future__ import annotations

from alture_jarvis import outbound, plan

GITHUB_PROMPT = (
    "크롬에서 깃허브 저장소 sonjari/sonjari 의 README.ko.md 한 줄을 웹 편집기로 고치고 PR 을 열어 줘. 순서: "
    "(1) https://github.com/sonjari/sonjari 를 열어 오른쪽 위 프로필로 로그인된 깃허브 계정 이름을 확인해."
)
LEARNED = {"GitHub": ("github.com",), "K-STARTUP": ("k-startup.go.kr",), "K-Startup": ("k-startup.go.kr",)}


def _sites(prompt: str, known: dict | None = None) -> list[str]:
    return [r.label for r in plan.extract(prompt, known_sites=known) if r.kind == "site"]


def test_korean_and_english_names_of_one_site_are_one_place() -> None:
    labels = _sites(GITHUB_PROMPT + " GitHub 계정이 narae1010 이면 계속해.", LEARNED)
    assert labels == ["깃허브에서 하기"], labels


def test_the_name_that_comes_first_in_the_request_is_the_label() -> None:
    assert _sites("GitHub 에서 트렌딩 저장소 3개 찾아 줘. 깃허브 로그인은 하지 마.", LEARNED) == ["GitHub에서 하기"]
    assert _sites("레딧 r/LocalLLM 에서 인기 글 5개 열어 읽어 줘 (Reddit 로그인 필요 없음)") == ["레딧에서 하기"]


def test_two_different_sites_stay_two() -> None:
    labels = _sites("깃허브에서 저장소를 찾고 노션에 정리해 줘")
    assert labels == ["깃허브에서 하기", "노션에서 하기"], labels


def test_needs_label_and_answer_may_spell_the_site_differently() -> None:
    answer = (
        "로그인된 계정 이름을 확인했습니다.\n\n**현재 로그인된 GitHub 계정: `garam-sonjari`**\n\n"
        "요청하신 `narae1010`이 아니므로 아무것도 고치지 않고 여기서 멈추겠습니다."
    )
    checked = outbound.check_needs(["로그인된 깃허브 계정 이름", "PR 주소", "바뀐 줄"], answer)
    assert [item["met"] for item in checked] == [True, None, None], checked


def test_loose_name_match_never_says_missing() -> None:
    """느슨하게 맞춘 자리는 채움의 증거로만 쓴다 — 값이 비었다고 「없다」(False)로 단정하지 않는다."""
    answer = "## 로그인된 GitHub 계정\n\n## 다음 절\n내용"
    assert outbound.check_needs(["로그인된 깃허브 계정 이름"], answer)[0]["met"] is None


def test_a_short_name_does_not_fill_a_longer_label() -> None:
    """「PR: …」 한 줄이 「PR 주소」를 채우지 않는다 — 두 낱말짜리 이름은 둘 다 있어야 한다."""
    assert outbound.check_needs(["PR 주소"], "PR: 열지 않았습니다")[0]["met"] is None
    assert outbound.check_needs(["PR 주소"], "- PR 주소: https://github.com/sonjari/sonjari/pull/3")[0]["met"] is True


def test_a_colon_inside_a_sentence_is_not_a_named_slot() -> None:
    """운영 판 d4c7eb06: 「1. 메모장 창을 새로 열었습니다 (창 ID: 48827506)」는 「메모장 창 제목」 자리가 아니다(창 번호다)."""
    answer = "**완료한 것:**\n1. 메모장 창을 새로 열었습니다 (창 ID: 48827506)\n2. 글을 입력했습니다"
    assert outbound.check_needs(["메모장 창 제목"], answer)[0]["met"] is None
    assert outbound.check_needs(["메모장 창 제목"], "- 메모장 창: 제목 없음 - Windows 메모장")[0]["met"] is True


def test_a_numbered_slot_name_still_counts() -> None:
    answer = "- **② 요금제:** 개인용 무료, 기업용 문의\n- **⑥ 사용자 후기:** 칭찬 5가지, 불만 없음"
    assert [x["met"] for x in outbound.check_needs(["요금제", "사용자 후기"], answer)] == [True, True]


def test_a_korean_site_name_inside_another_word_is_not_the_site() -> None:
    assert outbound._canon_sites("크레딧") == "크레딧"
    assert outbound._canon_sites("레딧 글") == "reddit.com 글"
    assert outbound._canon_sites("16GB 깃허브") == "16gb github.com"
