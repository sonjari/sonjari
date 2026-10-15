"""글에서 비밀을 **걷어 내고, 걷었다고 남긴다** (전략안 §43, P4).

## 왜

이 저장소의 `CLAUDE.md` 에 운영 API 키가 평문으로 적혀 있다. 다른 AI 도구의 지침을
그대로 가져오면 자비스 기억에 키가 들어간다. 사람이 쓴 지침 파일에는 키·토큰·비밀번호가
생각보다 자주 섞인다 — 「이 키로 확인해라」 같은 운영 메모가 지침이 되기 때문이다.

## 규율

1. **조용히 지우지 않는다.** 걷은 자리에 `[비밀 걷어 냄: API 키]` 를 남긴다. 무엇이
   빠졌는지 모르면 사람이 지침을 고칠 수 없다.
2. **원문 비밀은 결과에 한 글자도 안 싣는다.** 조각(`segments`)에도 표시 글자만 간다.
3. **이메일·전화는 걷지 않고 표시만** 한다. 지침에 연락처가 있는 것은 흔하고 정당하다 —
   걷을지는 사람이 정한다(`redact_contacts`).
4. **오탐이 미탐만큼 나쁘다.** 이 저장소는 게이트를 붙였다 오탐으로 적재율을 96%→19% 로
   떨어뜨린 적이 있다. (양방향 표본 시험: `tests/test_secret_scrub.py`)

## 역검증에서 배운 것 (2026-09-14)

첫 판을 저장소 문서·코드 368개에 대 봤더니 **74곳을 잘못 걷었다.** 전부 「이름」을 보고
값을 걷은 것이었다 — `tokens = re.compile(`, `"X-JARVIS-TOKEN": self.control_token}`,
`"password_fields": len(`. 지침 파일에는 코드 블록이 흔히 들어가므로 그대로 두면 지침이
망가진다. 그래서 이름이 걸려도 **값이 비밀처럼 생겼는지**(`_secret_like`)를 따로 본다.
긴 무작위 문자열은 「글자 종류가 **자주 바뀌는가**」로 가른다 — 식별자는 낱말 경계에서만
바뀌고(글자당 ≈0.25), 무작위 키는 거의 글자마다 바뀐다(62자 알파벳에서 ≈0.62).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

# 값이 아니라 **자리 표시**거나 **값을 가져오는 코드**다.
_PLACEHOLDER = re.compile(
    r"^(?:\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\$env:[A-Za-z_]\w*|%[A-Za-z_]\w*%|<[^>]*>?|\{\{[^}]*\}\}|"
    r"x{3,}|\*{3,}|\.{3,}|…|your[_-]?\w*|changeme|example\w*|dummy\w*|none|null|true|false|"
    r"pass(?:word)?|passwd|pw|pwd|secret|token|user|username|"
    r"(?:os\.environ|process\.env|os\.getenv|getenv|env)\b.*|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+[\[(]?)$",
    re.IGNORECASE,
)

# (라벨, 정규식, 걷을 그룹, 값 모양도 봐야 하나)
# 머리줄·대입문은 **이름은 남기고 값만** 걷는다. 「어느 키였는지」는 지침의 뜻이다.
_RULES: list[tuple[str, re.Pattern[str], int, bool]] = [
    ("개인 키", re.compile(
        r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----"), 0, False),
    ("API 키", re.compile(r"\bsk-(?:ant-|proj-|or-)?[A-Za-z0-9_-]{20,}"), 0, False),
    ("GitHub 토큰", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"), 0, False),
    ("Slack 토큰", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), 0, False),
    ("AWS 키", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0, False),
    ("Google API 키", re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), 0, False),
    ("결제 키", re.compile(r"\b(?:live|test)_(?:sk|ck|gsk|gck)_[A-Za-z0-9]{10,}"), 0, False),
    ("토큰(JWT)", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), 0, False),
    # 머리줄: `X-PRODUCT-API-KEY: 값` · `Authorization: Bearer 값`
    ("API 키", re.compile(
        r"(?i)\bX-[A-Za-z0-9-]*(?:API-?KEY|TOKEN|SECRET|AUTH)[A-Za-z0-9-]*[\"']?\s*:\s*[\"']?([^\s\"'`]{8,})"), 1, True),
    ("인증 토큰", re.compile(
        r"(?i)\bAuthorization[\"']?\s*:\s*[\"']?(?:Bearer|Basic|Token)\s+([^\s\"'`]{8,})"), 1, True),
    # 주소 안: `https://user:pass@host` · `?token=값`
    ("주소 안 비밀번호", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:([^\s/@]{3,})@"), 1, False),
    ("주소 안 토큰", re.compile(
        r"(?i)[?&](?:token|access_token|api_key|apikey|key|secret|password|sig|signature)=([^&\s#\"'`]{6,})"), 1, True),
    # 대입문: `WORKER_AUTH_TOKEN=값` · `"api_key": "값"` · `password = 값`
    ("비밀 값", re.compile(
        r"(?i)\b[\"']?([A-Za-z0-9_]*(?:API_?KEY|SECRET|TOKEN|PASSWORD|PASSWD|ACCESS_KEY|PRIVATE_KEY)[A-Za-z0-9_]*)"
        r"[\"']?\s*[:=]\s*[\"']?([^\s\"'`#,;&]{6,})"), 2, True),
    ("비밀번호", re.compile(r"(?:비밀번호|비번|암호)\s*[:：=]\s*[\"'`]?([^\s\"'`]{4,})"), 1, False),
]

_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{32,}(?![A-Za-z0-9_\-])")
_QUERY_NAME = re.compile(r"[?&](?!(?:token|access_token|api_key|apikey|key|secret|password|sig|signature)=)[A-Za-z_][\w-]*=$")
# `GPU-9b3e…` · UUID · 커밋 해시 — 짧은 접두어 뒤가 16진수뿐이면 무작위 키가 아니라 이름이다.
_HEXISH = re.compile(r"^(?:[A-Za-z]{1,6}[-_])?[0-9a-f][0-9a-f-]*$")

_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+82[-\s]?)?0(?:1[016789]|2|[3-6][1-5])[-\s.]?\d{3,4}[-\s.]?\d{4}(?!\d)")


def _entropy(text: str) -> float:
    counts = Counter(text)
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values())


def _class(ch: str) -> str:
    if ch.isupper():
        return "U"
    if ch.islower():
        return "L"
    if ch.isdigit():
        return "D"
    return "S"


def looks_random(token: str, *, min_len: int = 32) -> bool:
    """긴 문자열이 **키처럼 무작위인가.**

    - 16진수뿐(커밋 해시·digest·UUID, 짧은 접두어 허용)이면 아니다.
    - 대문자·소문자·숫자가 **셋 다** 있어야 한다.
    - 글자 종류가 바뀌는 비율이 0.4 이상 — `ConversationMemoryBackend2` 는 낱말 경계에서만
      바뀌어(≈0.25) 떨어진다. 무작위 키는 ≈0.62 다.
    """
    if len(token) < min_len or _HEXISH.match(token):
        return False
    letters = [c for c in (_class(ch) for ch in token) if c != "S"]
    if not {"U", "L", "D"} <= set(letters):
        return False
    switches = sum(1 for a, b in zip(letters, letters[1:]) if a != b)
    if switches < 0.4 * (len(letters) - 1):
        return False
    return _entropy(token) >= 3.6


def _secret_like(value: str) -> bool:
    """이름이 「token」이어도 **값**이 비밀처럼 생겨야 걷는다.

    코드의 `tokens = re.compile(` · `control_token = config.x` 는 값이 아니라 식이다.
    """
    value = value.strip("\"'`").rstrip(")}],;:")
    if len(value) < 6 or _PLACEHOLDER.match(value):
        return False
    if any(ch in value for ch in "()[]{}|<>"):
        return False  # 함수 호출·첨자·sed 식 — 값이 아니라 식이다(역검증: `s|^TOSS_SECRET_KEY=.*|`)
    if "://" in value:
        return False  # 주소다(`TOKEN_URI = "https://…/token"`). 주소 안 비밀은 주소 규칙이 본다
    if value.replace(".", "").replace("_", "").isdigit():
        return False  # `max_tokens: 1000000`
    has_letter = any(ch.isalpha() for ch in value)
    has_digit = any(ch.isdigit() for ch in value)
    has_symbol = any(ch in "!@#$%^*+/=~" for ch in value)
    if has_letter and (has_digit or has_symbol):
        return True
    return looks_random(value, min_len=20)


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    kind: str  # "secret" | "contact"
    label: str


def _secret_spans(text: str) -> list[_Span]:
    spans: list[_Span] = []
    for label, pattern, group, check_value in _RULES:
        for match in pattern.finditer(text):
            value = match.group(group)
            if not value:
                continue
            if group and _PLACEHOLDER.match(value.strip("\"'`").rstrip(")}],;:")):
                continue
            if check_value and not _secret_like(value):
                continue
            end = match.end(group)
            # 값 끝에 붙은 닫는 괄호·쉼표는 비밀이 아니다 — 남겨야 코드가 안 깨진다.
            while end > match.start(group) and text[end - 1] in ")}],;:":
                end -= 1
            spans.append(_Span(match.start(group), end, "secret", label))
    for match in _LONG_TOKEN.finditer(text):
        # 주소의 평범한 인자 값(`?filter=…` 인코딩 문자열)은 키가 아니다. 비밀 이름의 인자
        # (`?token=`)는 위의 주소 규칙이 이미 잡았다. (역검증: 날짜인자 인수인계서의 filter 값)
        # ★ 창의 **끝**에 붙은 인자만 본다 — 앞쪽 `?type=` 을 먼저 찾아 놓치던 것(시험이 잡음).
        if _QUERY_NAME.search(text[max(0, match.start() - 40):match.start()]):
            continue
        if looks_random(match.group(0)):
            spans.append(_Span(match.start(), match.end(), "secret", "긴 무작위 문자열"))
    return spans


def _merge(spans: list[_Span]) -> list[_Span]:
    """겹치면 먼저 시작한 것 — 같으면 긴 것 — 을 남긴다. 한 비밀을 두 번 세지 않는다."""
    out: list[_Span] = []
    for span in sorted(spans, key=lambda s: (s.start, -(s.end - s.start))):
        if out and span.start < out[-1].end:
            last = out[-1]
            if span.end > last.end:
                out[-1] = _Span(last.start, span.end, last.kind, last.label)
            continue
        out.append(span)
    return out


def marker(label: str) -> str:
    return f"[비밀 걷어 냄: {label}]"


def scrub(text: str, *, redact_contacts: bool = False) -> dict[str, Any]:
    """비밀을 걷은 글과, 화면이 그대로 그릴 수 있는 조각 목록을 준다.

    돌려주는 것:
      text      저장할 글(걷은 자리에 표시 글자)
      segments  [{"t": "text"|"secret"|"contact", "v": 보일 글자, "label"?}]
                ★ secret 조각의 v 는 표시 글자다 — 원문이 아니다
      secrets   {라벨: 개수}
      contacts  {"이메일"|"전화번호": 개수}  (redact_contacts 면 걷고 secrets 쪽에도 센다)
    """
    source = str(text or "")
    secrets = _merge(_secret_spans(source))
    covered = [(s.start, s.end) for s in secrets]

    def free(start: int, end: int) -> bool:
        return all(end <= a or start >= b for a, b in covered)

    contacts = [
        _Span(m.start(), m.end(), "contact", label)
        for label, pattern in (("이메일", _EMAIL), ("전화번호", _PHONE))
        for m in pattern.finditer(source)
        if free(m.start(), m.end())
    ]
    spans = _merge(secrets + contacts)

    segments: list[dict[str, str]] = []
    pieces: list[str] = []
    secret_counts: Counter[str] = Counter()
    contact_counts: Counter[str] = Counter()
    cursor = 0
    for span in spans:
        if span.start > cursor:
            segments.append({"t": "text", "v": source[cursor:span.start]})
            pieces.append(source[cursor:span.start])
        original = source[span.start:span.end]
        if span.kind == "secret" or redact_contacts:
            shown = marker(span.label)
            segments.append({"t": "secret", "v": shown, "label": span.label})
            pieces.append(shown)
            secret_counts[span.label] += 1
            if span.kind == "contact":
                contact_counts[span.label] += 1
        else:
            segments.append({"t": "contact", "v": original, "label": span.label})
            pieces.append(original)
            contact_counts[span.label] += 1
        cursor = span.end
    if cursor < len(source):
        segments.append({"t": "text", "v": source[cursor:]})
        pieces.append(source[cursor:])

    return {
        "text": "".join(pieces),
        "segments": segments,
        "secrets": dict(secret_counts),
        "secret_total": sum(secret_counts.values()),
        "contacts": dict(contact_counts),
        "contact_total": sum(contact_counts.values()),
    }


__all__ = ["looks_random", "marker", "scrub"]
