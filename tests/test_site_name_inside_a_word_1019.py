"""다른 낱말 속에 든 사이트 이름은 장소가 아니다 (2026-10-19).

inline AI 조사 판(d0d36f19)의 「요금제와 크레딧」 속 「레딧」이 배운 사이트 이름에 걸려 대조표에 「레딧에서 하기」가 섰다.
운영 요청 2,379개에 옛 · 새를 대 보니 바뀐 것은 둘(이 판 · AWS 크레딧 화면 읽기 판)뿐이고 둘 다 「크레딧」이었다.
"""

from __future__ import annotations

from alture_jarvis.plan import extract

KNOWN = {"레딧": ("reddit.com",), "네이버 블로그": ("blog.naver.com",), "네이버": ("naver.com",)}


def _sites(prompt: str) -> list[str]:
    return sorted(req.label for req in extract(prompt, known_sites=KNOWN) if req.kind == "site")


def test_a_site_name_inside_another_word_is_not_a_place() -> None:
    assert _sites("이 제품의 요금제와 크레딧을 공식 사이트에서 읽고 정리해 줘") == []
    assert _sites("콘솔의 크레딧 화면을 읽어서 남은 금액을 알려 줘") == []


def test_the_name_itself_still_counts_with_a_particle_after_it() -> None:
    assert _sites("레딧에서 로컬 모델 후기 3개 찾아 읽어 줘") == ["레딧에서 하기"]
    assert _sites("요금제와 크레딧은 공식 사이트, 후기는 레딧 에서 읽어 줘") == ["레딧에서 하기"]


def test_a_longer_name_still_wins_over_its_prefix() -> None:
    assert _sites("네이버 블로그 사용 후기도 몇 개 읽어 줘") == ["네이버 블로그에서 하기"]
