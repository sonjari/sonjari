"""「야놀자**에** 들어가서」는 출처를 댄 것이다.

2026-09-04. 「야놀자에 직접 들어가서 밀양 숙소를 찾아줘」가 출처 판정에 안 걸렸다.
그물이 조사 **「에서」 하나만** 보고 있었고, 사이트에 들어가라는 말로는 「에」가 더
자연스럽다. 두 군데가 같이 망가진다:

    ① 라우터가 「가서 봐야 아는 것」으로 안 본다
    ② `SiteAtlas` 가 배울 이름을 못 받는다 — 어제 야놀자를 제대로 열고 제목까지
       「NOL(야놀자)」로 받았는데 표에 안 들어갔고, 오늘 모델이 주소를 지어냈다
       (`yyj.co.kr` → host_does_not_exist → 판이 통째로 헛돌았다)
"""

from __future__ import annotations

import pytest

from alture_jarvis.agent import named_sources
from alture_jarvis.site_atlas import SEED, SiteAtlas


@pytest.mark.parametrize(
    "prompt, name",
    [
        ("야놀자에 직접 들어가서 이번 주 토요일 밀양 숙소를 찾아줘", "야놀자"),
        ("사람인에들어가서 직접 스크랩해주라", "사람인"),
        ("너가 위시캣에 들어가서 프로필을 어떻게 할지 고민을 해보자", "위시캣"),
        ("잡코리아로 접속해서 공고 좀 봐줘", "잡코리아"),
        ("쿠팡에 한번 들어가 봐", "쿠팡"),
    ],
)
def test_entering_a_site_names_it(prompt: str, name: str) -> None:
    assert name in named_sources(prompt)


def test_the_old_particle_still_works() -> None:
    assert "크몽" in named_sources("크몽에서 AI 자동화 서비스 상위 5개를 알려줘")


@pytest.mark.parametrize(
    "prompt",
    [
        "오후 3시에 회의에 들어가야 해",
        "내가 지금 수정 페이지로 들어와있으니까 너는 기입만 하면 돼",
        "그 연구비 관리로 들어가서 조건을 바꿔줘",
        "설정으로 들어가서 알림을 꺼줘",
    ],
)
def test_a_place_inside_a_screen_is_not_a_site(prompt: str) -> None:
    """조사만 넓히면 「3시에」·「회의에」가 전부 출처가 된다. 동사와 짝일 때만 본다."""
    assert not named_sources(prompt), named_sources(prompt)


def test_a_bare_particle_is_not_enough() -> None:
    """들어간다는 말이 없으면 「에」는 그냥 조사다."""
    assert not named_sources("내일 밀양에 놀러 가려고 하는데 뭐 하면 좋을까")


def test_yanolja_is_seeded_from_a_visit_we_actually_made() -> None:
    """씨앗은 사람이 확인한 것만 넣는다 — 이건 우리 트레이스에서 왔다."""
    assert SEED["야놀자"] == "yanolja.com"
    assert SiteAtlas().host_for("야놀자") == "yanolja.com"


def test_an_unknown_name_still_says_it_does_not_know() -> None:
    """모르면 모른다고 해야 모델이 주소를 지어내지 않는다."""
    assert SiteAtlas().host_for("듣도보도못한사이트") == ""
