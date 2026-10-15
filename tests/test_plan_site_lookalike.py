"""지목한 사이트가 아니라 **주소를 붙인 다른 곳**은 "그 사이트에서 했음"이 아니다.

plan.check 의 사이트 대조는 예전 `part in h`(부분문자열)로 봤다. 그러면
"notkmong.com" 같은 닮은 호스트가 "kmong.com" 요구를 채운 것처럼 통과한다.
그런데 site_atlas.is_on 은 도메인 일치 또는 그 **하위 도메인**만 "그 사이트"라 판정한다.

두 파일이 "이 주소가 그 사이트인가"라는 같은 질문에 다른 답을 주지 말아야 한다.
이 테스트는 그 정합성을 잠근다.
"""

from __future__ import annotations

from alture_jarvis.plan import Requirement, check

def test_lookalike_host_does_not_satisfy_the_named_site() -> None:
    """notkmong.com 은 kmong.com 이 아니다 — 하위 도메인이 아니라 **다른** 호스트."""
    req = Requirement("site", "크몽에서 읽어줘", target=("kmong.com",))
    res = check([req], sources=["https://notkmong.com/job/1"], steps=[])
    assert res[0][1] is False, "닮은 호스트가 지목 사이트를 대신할 수 없다"

def test_subdomain_of_the_named_site_still_counts() -> None:
    """app.kmong.com 은 kmong.com 의 하위 도메인이므로 '그 사이트'다(기존 계약 유지)."""
    req = Requirement("site", "크몽에서 읽어줘", target=("kmong.com",))
    res = check([req], sources=["https://app.kmong.com/job/1"], steps=[])
    assert res[0][1] is True

def test_exact_host_counts() -> None:
    req = Requirement("site", "위시켓에서 읽어줘", target=("wishket.com",))
    res = check([req], sources=["https://wishket.com/market/9"], steps=[])
    assert res[0][1] is True
