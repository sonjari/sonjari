"""제어 API 에 **누가 닿을 수 있나** (2026-08-24).

## 왜 이 검사가 중요한가

이 API 로 들어오면 도구를 실행하고, 브라우저를 몰고, 메일을 보낸다. 위성 갱신을
만들면서 바인딩을 넓혀야 했는데(전에는 `127.0.0.1` 만 들어서 위성에서 아예 안
보였다), 넓힌 만큼 여기서 좁힌다.

**이건 인증이 아니다.** 인증은 토큰이 한다. 이건 「어디서 온 것까지 받나」이고,
방화벽이 사라져도 살아남는 두 번째 겹이다 — 방화벽 규칙은 사람이 지우고 윈도우가
초기화한다. 코드에 박힌 것만 남는다.

## 모르면 거절이다

라우팅에서는 반대로 기울였다(애매하면 도구 쪽으로). **여기서는 반대다** —
거기서 틀리면 몇 초를 잃지만 여기서 틀리면 PC 를 잃는다. 비용이 비대칭인
방향이 반대라, 기울이는 방향도 반대다.
"""

from __future__ import annotations

import pytest

from alture_jarvis import peer_guard


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",        # 화면(HUD)
        "127.0.0.53",
        "::1",
        "::ffff:127.0.0.1",  # IPv4-mapped 로 오는 판이 있다
        "100.64.0.10",     # 본체 테일넷 주소
        "100.64.0.11",    # 위성 노트북
        "100.64.0.1",        # 대역 경계
        "100.127.255.254",
    ],
)
def test_home_and_tailnet_get_through(address: str) -> None:
    assert peer_guard.is_allowed(address), address


@pytest.mark.parametrize(
    "address",
    [
        "192.168.0.15",   # 흔한 가정용 LAN
        "192.168.1.1",
        "192.168.0.91",    # ★ 사무실 LAN — 여기가 열리면 안 된다
        "192.168.0.93",    # NAS
        "10.0.0.5",
        "8.8.8.8",        # 바깥
        "100.128.0.1",    # 대역 **바로 밖**
        "100.63.255.255",
    ],
)
def test_the_office_lan_is_not_the_tailnet(address: str) -> None:
    """★ 이 검사가 빨개지면 사무실 아무 기기나 이 PC 를 몰 수 있다."""
    assert not peer_guard.is_allowed(address), address


@pytest.mark.parametrize("address", ["", "   ", "garbage", "999.1.1.1", "localhost"])
def test_what_it_cannot_read_it_refuses(address: str) -> None:
    """모르는 것을 허용 쪽으로 기울이면 이 자리에서는 곧 전면 개방이다.

    (`localhost` 도 거절이다 — 여기 오는 값은 이미 풀린 IP 라서, 이름이 온다면
     그건 우리가 모르는 경로다.)
    """
    assert not peer_guard.is_allowed(address), address


def test_an_extra_range_can_be_opened_on_purpose() -> None:
    """사무실 LAN 에서 쓰고 싶으면 **일부러** 열 수 있어야 한다."""
    assert not peer_guard.is_allowed("192.168.0.91")
    assert peer_guard.is_allowed("192.168.0.91", ["192.168.0.0/24"])


def test_a_typo_in_the_extra_range_is_loud() -> None:
    """조용히 버리면 「열어 뒀다고 생각했는데 안 열린」 상태가 된다.

    그건 오타 하나로 갱신이 통째로 죽는 모양이고, 아무 데도 안 찍힌다.
    """
    with pytest.raises(ValueError):
        peer_guard.parse_networks(["192.168.0.0/99"])
    with pytest.raises(ValueError):
        peer_guard.parse_networks(["여기적으면안됨"])


def test_the_refusal_says_which_address() -> None:
    """주소를 안 적으면 진단이 불가능하다 — 「왜 403 이지」로 끝난다."""
    assert "192.168.0.9" in peer_guard.refusal("192.168.0.9")
    assert peer_guard.refusal("")


def test_the_documented_defaults_match_the_code() -> None:
    """글로 적은 것과 도는 것이 갈리면, 사람은 글을 믿고 틀린다."""
    for cidr in peer_guard.DEFAULT_ALLOWED:
        network = peer_guard.parse_networks([cidr])[0]
        probe = next(network.hosts()) if network.num_addresses > 2 else network.network_address
        assert peer_guard.is_allowed(str(probe)), cidr


# ── 배선됐는가 (2026-08-24) ───────────────────────────────────────────────────
#
# ★ 위의 검사들은 **판정 함수**만 본다. 그 함수가 아무리 옳아도 앱에 안 달려
#   있으면 아무 일도 안 일어난다 — 이 저장소가 여섯 번 겪은 모양이다
#   (도구를 만들어도 갈래가 없으면 안 쓰인다).
#
#   게다가 `conftest.py` 가 검사용 클라이언트를 전부 루프백으로 만들기 때문에,
#   미들웨어가 통째로 사라져도 다른 검사는 하나도 안 깨진다. **여기서만 잡힌다.**

def test_the_guard_is_actually_wired_into_the_app(tmp_path) -> None:  # noqa: ANN001
    from starlette.testclient import TestClient

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    # 기본값 그대로 만들면 뿌리가 사용자의 진짜 앱 폴더다 — 시험은 임시 폴더를 준다(conftest 의 문이 잡았다 · 2026-10-09).
    app = create_app(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs"))

    with TestClient(app, client=("192.168.0.91", 51000)) as lan:
        refused = lan.get("/health")
    assert refused.status_code == 403, "사무실 LAN 에서 온 요청이 통과했다"
    assert "192.168.0.91" in refused.json().get("detail", ""), "왜 막혔는지를 안 알려 준다"

    with TestClient(app, client=("100.64.0.12", 51000)) as tailnet:
        allowed = tailnet.get("/health")
    assert allowed.status_code == 200, "테일넷 위성이 막혔다 — 갱신이 통째로 죽는다"


def test_the_websocket_is_guarded_too(tmp_path) -> None:  # noqa: ANN001
    """★ `@app.middleware("http")` 는 이름 그대로 HTTP 만 본다.

    소켓은 통째로 비켜 간다. 문지기를 달아 놓고 **실시간 이벤트 통로만 열린**
    상태가 될 뻔했다 — 한 곳만 좁히면 좁힌 줄 알고 넘어가게 된다.
    """
    from starlette.testclient import TestClient
    from websockets.exceptions import WebSocketException  # noqa: F401  (있으면 좋고)

    from alture_jarvis.api import create_app
    from alture_jarvis.config import JarvisConfig

    # 기본값 그대로 만들면 뿌리가 사용자의 진짜 앱 폴더다 — 시험은 임시 폴더를 준다(conftest 의 문이 잡았다 · 2026-10-09).
    app = create_app(JarvisConfig(runtime_root=tmp_path, data_dir=tmp_path / "data", output_dir=tmp_path / "outputs"))
    with TestClient(app, client=("192.168.0.91", 51000)) as lan:
        with pytest.raises(Exception):
            with lan.websocket_connect("/v1/ws"):
                pass
