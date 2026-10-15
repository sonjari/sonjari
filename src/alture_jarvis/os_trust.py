"""HTTPS 인증서 검사를 **윈도우에게** 맡긴다 (2026-09-24).

왜 있나: 초기화한 노트북에서 첫 실행 「Ollama 설치」가
`CERTIFICATE_VERIFY_FAILED ... unable to get local issuer certificate` 로 죽었다.
개발 PC 에선 한 번도 안 난 일이다.

윈도우는 루트 인증서를 처음부터 다 들고 있지 않고 **필요할 때 받아 온다**(자동 루트 갱신).
엣지·크롬·PowerShell 은 윈도우의 검사 기능을 써서 그때 받아 오지만, 파이썬 `ssl` 은
**지금 저장소에 있는 것만** 읽어 OpenSSL 로 검사한다. 오래 쓴 PC 는 브라우저가 이미 다 받아
놓아서 통과하고, 갓 초기화한 PC 는 GitHub(Sectigo E46 ← USERTrust ECC)·
릴리스 CDN(Let's Encrypt Root YR ← ISRG X1) 루트가 아직 없어서 떨어진다.

`truststore` 는 파이썬의 검사를 윈도우 검사(CertGetCertificateChain)로 바꾼다 —
없는 루트는 윈도우가 받아 오고, 회사 프록시·백신이 넣은 인증서도 브라우저와 똑같이 믿는다.
urllib·httpx·requests 가 모두 `ssl.SSLContext` 를 거치므로 **프로세스 시작에 한 번** 걸면 된다.
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)
_done = False


def use_os_trust_store() -> bool:
    """가능하면 OS 인증서 검사로 바꾼다. 바꿨으면 True. 실패해도 앱은 원래 검사로 계속 돈다."""
    global _done
    if _done:
        return True
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception as exc:  # noqa: BLE001 - 없거나 못 걸어도 기동은 막지 않는다
        _log.warning("OS 인증서 검사로 못 바꿨다(파이썬 기본 검사로 계속): %s", exc)
        return False
    _done = True
    return True
