"""로그인 · 계정 화면의 주소와 **한 번 쓰는 값**을 밖으로 내보내지 않는다 (2026-10-19).

## 왜

잡 `51f35b07`(2026-10-19): 대표가 같은 크롬 탭에서 깃허브 계정을 더하는 사이에 손자리가 그 화면을 읽었고, 맡긴 쪽(클로드)에게
돌려준 `sources` 에 이 주소가 그대로 실렸다:

    https://accounts.google.com/v3/signin/accountchooser?client_id=…&code_challenge=…&nonce=…&state=…&continue=…

`code_challenge` · `nonce` · `state` 는 그 로그인 한 번을 묶는 값이다. 출처로서의 쓸모는 「구글 계정 고르기 화면을 봤다」 한 줄이면
충분하고, 값은 바깥 AI 의 대화 기록 · 로그에 남을 까닭이 없다.

## 규칙 (사이트 목록이 아니라 모양으로)

1. **로그인 · 인증 화면**(`is_sign_in_url`) — 인증 전용 호스트(`accounts.google.com` 등) · `login.` / `auth.` / `sso.` 로 시작하는
   호스트 · 경로 마디가 `login` · `signin` · `oauth2.0` · `authorize` · `auth` · `session` … 인 주소. 물음표 뒤와 `#` 뒤를 통째로 버린다.
2. **늘 비밀인 이름**(`access_token` · `id_token` · `code_challenge` · `nonce` · `password` · `client_secret` · `…token` …)이 물음표나
   `#` 뒤에 있으면 같은 처리.
3. `code` · `state` · `session` 같은 **흔한 이름은 OAuth 표식이 같이 있을 때만**(`client_id` · `redirect_uri` · `response_type` …).
   증권 화면의 `?code=005930`, 땅 매물의 `?state=TX` 는 평범한 출처다 — 그대로 둔다.
4. 지우지 않고 **줄인다**: `scheme://host/path`. 「그 화면을 봤다」는 사실은 남는다(조용히 지우면 출처가 거짓이 된다).
   `user:pass@` 도 버린다.

경로 자체에 값을 박는 사이트(`/reset/<토큰>`)는 아직 못 가린다 — 모양만으로는 평범한 글 번호와 갈리지 않는다.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

__all__ = ["is_sign_in_url", "has_one_time_values", "safe_url", "scrub_urls", "scrub_urls_deep"]

#: 로그인만 하는 호스트. 여기 오는 주소는 어떤 쿼리든 로그인 한 번에 묶인 값이다.
_AUTH_HOSTS = frozenset({
    "accounts.google.com", "login.microsoftonline.com", "login.microsoft.com", "login.live.com",
    "nid.naver.com", "accounts.kakao.com", "kauth.kakao.com", "appleid.apple.com", "idmsa.apple.com",
    "auth.openai.com", "login.yahoo.com",
})
#: 이 이름으로 시작하는 호스트는 로그인 문이다(`login.genspark.ai` · `auth.example.com` · `sso.company.kr`).
_AUTH_HOST_PREFIX = ("login.", "auth.", "sso.", "signin.", "accounts.", "account.")
#: 경로 마디 — 한 마디가 통째로 이 이름일 때만(`/docs/authentication` 은 아니다). `oauth2.0` 은 네이버.
_AUTH_SEGMENT = re.compile(
    r"^(?:login|log-in|logon|signin|sign-in|sign_in|servicelogin|accountchooser|oauth|oauth2|oauth2\.0|"
    r"authorize|authorization|auth|sso|saml|saml2|session|sessions|2fa|mfa)$",
    re.IGNORECASE,
)
#: 늘 비밀인 쿼리 이름.
_ALWAYS = frozenset({
    "access_token", "id_token", "refresh_token", "auth_token", "authtoken", "token", "jwt", "id_token_hint",
    "code_challenge", "code_verifier", "nonce", "client_secret", "password", "passwd", "pwd", "secret",
    "api_key", "apikey", "auth", "authkey", "auth_key", "sessionid", "session_id", "jsessionid", "phpsessid",
    "signature", "x-amz-signature", "x-amz-credential", "x-amz-security-token", "x-goog-signature", "x-goog-credential",
    "samlrequest", "samlresponse", "oauth_token", "oauth_verifier", "authenticity_token", "csrf_token", "_csrf",
    "xsrf_token", "otp", "login_hint",
})
#: 혼자서는 평범한 이름 — OAuth 표식이 같이 있을 때만 비밀이다.
_WITH_OAUTH = frozenset({"code", "state", "session", "sid", "ticket", "assertion", "relaystate"})
#: 「이 주소는 OAuth 주고받기다」 표식.
_OAUTH_MARKS = frozenset({"client_id", "redirect_uri", "response_type", "code_challenge", "scope_challenge"})

_URL = re.compile(r"https?://[^\s<>\"'`)\]}|]+", re.IGNORECASE)


def _host(parts: Any) -> str:
    try:
        return (parts.hostname or "").lower()
    except ValueError:
        return ""


def is_sign_in_url(url: str) -> bool:
    """로그인 · 인증 · 계정 고르기 화면의 주소인가."""
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return False
    if parts.scheme.lower() not in ("http", "https"):
        return False
    host = _host(parts)
    if not host:
        return False
    if host in _AUTH_HOSTS or host.startswith(_AUTH_HOST_PREFIX):
        return True
    return any(_AUTH_SEGMENT.match(segment) for segment in (parts.path or "").split("/") if segment)


def _params(parts: Any) -> list[str]:
    """값이 **있는** 이름만 — 빈 칸(`my-password=`)은 내보낼 값이 없다(셀레니움 연습 폼이 그 모양이다)."""
    names: list[str] = []
    for chunk in (parts.query, parts.fragment):
        if "=" not in (chunk or ""):
            continue
        try:
            names.extend(name.strip().lower() for name, value in parse_qsl(chunk, keep_blank_values=True) if value.strip())
        except ValueError:
            continue
    return names


def _name_is_secret(name: str) -> bool:
    return name in _ALWAYS or name.endswith(("_token", "_secret", "password", "_passwd"))


def has_one_time_values(url: str) -> bool:
    """물음표 · `#` 뒤에 로그인 한 번에 묶인 값(토큰 · 비밀 · OAuth 주고받기)이 있나."""
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return False
    names = _params(parts)
    if not names:
        return False
    if any(_name_is_secret(name) for name in names):
        return True
    oauth = any(name in _OAUTH_MARKS for name in names)
    return oauth and any(name in _WITH_OAUTH for name in names)


def safe_url(url: str) -> str:
    """밖으로 내보내도 되는 모양. 로그인 화면이거나 한 번 쓰는 값이 있으면 `scheme://host/path` 로 줄인다. 아니면 그대로."""
    text = str(url or "")
    try:
        parts = urlsplit(text.strip())
    except ValueError:
        return text
    if parts.scheme.lower() not in ("http", "https") or not _host(parts):
        return text
    userinfo = "@" in (parts.netloc or "")
    if not (userinfo or is_sign_in_url(text) or has_one_time_values(text)):
        return text
    netloc = parts.netloc.rsplit("@", 1)[-1]
    if not (is_sign_in_url(text) or has_one_time_values(text)):
        # 비밀번호가 든 `user:pass@` 만 있으면 그것만 뺀다 — 쿼리는 평범한 값이다.
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def scrub_urls(text: str) -> tuple[str, int]:
    """글 안의 주소를 `safe_url` 로 바꾼다. (바뀐 글, 줄인 주소 수)."""
    count = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal count
        raw = match.group(0)
        # 문장 끝 구두점은 주소가 아니다 — 떼어 두고 붙인다.
        tail = ""
        while raw and raw[-1] in ".,;:!?」』":
            tail = raw[-1] + tail
            raw = raw[:-1]
        safe = safe_url(raw)
        if safe != raw:
            count += 1
        return safe + tail

    value = str(text or "")
    if "http" not in value.lower():
        return value, 0
    return _URL.sub(_sub, value), count


def scrub_urls_deep(value: Any) -> tuple[Any, int]:
    """dict · list 안의 글을 전부 훑어 주소를 줄인 사본과 줄인 수를 돌려준다(원본은 안 바꾼다)."""
    if isinstance(value, str):
        return scrub_urls(value)
    if isinstance(value, dict):
        total = 0
        out: dict[Any, Any] = {}
        for key, item in value.items():
            out[key], n = scrub_urls_deep(item)
            total += n
        return out, total
    if isinstance(value, (list, tuple)):
        total = 0
        items: list[Any] = []
        for item in value:
            cleaned, n = scrub_urls_deep(item)
            items.append(cleaned)
            total += n
        return (items if isinstance(value, list) else tuple(items)), total
    return value, 0
