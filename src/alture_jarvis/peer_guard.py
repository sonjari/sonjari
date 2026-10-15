"""**누가 이 API 에 닿을 수 있나** (2026-08-24).

## 왜 생겼나

위성 갱신을 만들고 나서야 알았다 — 본체의 제어 API 는 `127.0.0.1` 만 듣고 있어서
위성에서 아예 안 보였다:

    8091  -> 127.0.0.1   제어 API. 루프백만
    11434 -> ::          오요라마
    7788  -> 0.0.0.0     음성

위성이 두뇌와 음성은 빌리는데 제어 API 만 못 봤다. 갱신을 하려면 열어야 한다.

## 그런데 이 API 는 아무 API 가 아니다

여기로 들어오면 **도구를 실행하고, 브라우저를 몰고, 메일을 보낸다.** LAN 전체에
`0.0.0.0` 으로 여는 것은 사무실 네트워크의 아무 기기에게나 이 PC 를 넘기는 것과
같다. 토큰이 있지만, 토큰 하나에 그만한 것을 걸지 않는다.

## 그래서 두 겹이다

    ① 방화벽/테일스케일   바깥에서 패킷이 오는 것 자체를 막는다
    ② 여기               와도 **테일넷과 루프백이 아니면 받지 않는다**

②가 있는 이유는 ①이 사라질 수 있기 때문이다. 방화벽 규칙은 사람이 지우고,
윈도우 업데이트가 초기화하고, 프로필이 바뀌면 안 먹는다. **코드로 박은 것만
남는다** — 이 저장소가 여러 번 배운 것이다(안내문은 안 먹는다, 되돌림은 조용히
실패한다).

## 왜 100.64.0.0/10 인가

테일스케일이 쓰는 대역이다(CGNAT). 테일넷 주소는 전부 여기 들어오고, 보통의
LAN(192.168·172.16~31·10.x)은 안 들어온다. 그래서 「테일넷에서 왔나」를
주소만 보고 판정할 수 있다.

★ 이 판정은 **여는 범위를 좁히는 용도**지 인증이 아니다. 인증은 토큰이 한다.
  둘 다 있어야 한다 — 주소는 위조될 수 있고, 토큰은 새어 나갈 수 있다.
"""

from __future__ import annotations

import ipaddress
from typing import Iterable

# 루프백. 화면(HUD)·교체 스크립트·MCP 가 전부 여기서 온다.
_LOOPBACK = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)
# 테일스케일 대역.
_TAILNET = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),
)

# 검사·문서에서 같이 쓴다. 글자로 적어 두면 사람이 읽을 수 있다.
DEFAULT_ALLOWED = ("127.0.0.0/8", "::1/128", "100.64.0.0/10", "fd7a:115c:a1e0::/48")


def parse_networks(values: Iterable[str]) -> tuple[ipaddress._BaseNetwork, ...]:
    """설정 문자열 → 대역. **못 읽는 값은 조용히 버리지 않는다.**

    버리면 「열어 뒀다고 생각했는데 안 열린」 상태가 되고, 그건 오타 하나로
    갱신이 통째로 죽는 모양으로 나타난다. 그래서 예외를 낸다.
    """
    out: list[ipaddress._BaseNetwork] = []
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        out.append(ipaddress.ip_network(text, strict=False))
    return tuple(out)


def is_allowed(client_host: str, extra: Iterable[str] = ()) -> bool:
    """이 주소에서 온 요청을 받을 것인가.

    주소를 못 읽으면 **거절한다.** 모르는 것을 허용 쪽으로 기울이면, 이 자리에서는
    그게 곧 전면 개방이다. (라우팅에서는 반대로 기울였다 — 거기서 틀리면 몇 초를
    잃지만, 여기서 틀리면 PC 를 잃는다.)
    """
    if not client_host:
        return False
    text = client_host.strip()
    # `::ffff:127.0.0.1` 같은 IPv4-mapped 형태로 오는 판이 있다.
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    if getattr(address, "ipv4_mapped", None):
        address = address.ipv4_mapped
    for network in (*_LOOPBACK, *_TAILNET, *parse_networks(extra)):
        try:
            if address in network:
                return True
        except TypeError:
            # v4 주소를 v6 대역에 넣어 보는 경우. 그냥 다음 것으로.
            continue
    return False


def refusal(client_host: str) -> str:
    """왜 막혔는지. **주소를 적는다** — 안 적으면 진단이 불가능하다."""
    return (
        f"이 주소에서는 받지 않습니다: {client_host or '알 수 없음'}. "
        "제어 API 는 루프백과 테일넷에만 열려 있습니다."
    )
