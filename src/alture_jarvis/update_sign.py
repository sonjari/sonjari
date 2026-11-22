"""업데이트 서명 확인 — minisign 형식 · ed25519 · **표준 라이브러리만** (2026-11-16).

## 왜 이 파일이 있나

맥 업데이트는 테일넷 밖(인터넷 배포처)에서 받는다. `updater.py` 머리말이 「배포처가 테일넷 밖으로 나가면 그때는
서명이 필요하다」고 적어 둔 그 경계다. 서명은 **타우리 업데이터와 같은 열쇠 · 같은 형식(minisign)** 을 쓴다 —
열쇠가 둘이면 잃어버릴 것 · 갈아 끼울 것도 둘이 된다(설계 `docs/설계_맥업데이트_2026-11-16.ko.md` §4).

## 왜 `cryptography` 를 안 쓰나

이 PC · 맥 venv 에 깔려 있긴 한데 **선언된 의존이 아니다**(맥에선 아무 부품도 그걸 요구하지 않는다 — 11-16 `pip show`).
새로 깐 맥엔 없을 수 있다. 여기서 필요한 것은 **확인**뿐이고(서명은 빌드 PC 에서 `tauri signer sign` 이 한다),
RFC 8032 §5.1.7 확인 절차는 짧으며 `hashlib` 에 SHA-512 · BLAKE2b 가 다 있다.

★ 우리가 짠 암호 코드라는 점이 대가다. 그래서 시험이 셋으로 묶는다: RFC 8032 시험 벡터 · **실제 타우리 CLI 가 만든 서명** ·
  `cryptography` 로 만든 무작위 서명과의 대조(`tests/test_update_sign_1116.py`). 이 파일을 고치면 그 셋이 다 돌아야 한다.

## minisign 형식 (11-16 타우리 CLI 2.11.4 로 만든 것을 풀어 확인)

    공개 열쇠   untrusted comment: …
                base64( "Ed" | 열쇠번호 8 | 공개열쇠 32 )
    서명        untrusted comment: …
                base64( "ED" | 열쇠번호 8 | 서명 64 )      ← "ED" = 파일을 BLAKE2b-512 로 먼저 줄여 서명, "Ed" = 파일 그대로
                trusted comment: timestamp:…\tfile:…
                base64( 전역서명 64 )                     ← 서명 64 + 신뢰 주석 글자에 대한 서명

타우리는 위 두 덩어리(글 전체)를 **한 번 더 base64** 로 싸서 설정 · latest.json 에 넣는다. 둘 다 받는다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass


class SignatureError(ValueError):
    """서명이 맞지 않거나 읽을 수 없다. 메시지는 사람이 읽는 한국어다."""


# ── ed25519 확인 (RFC 8032 §5.1 · §6 참고 구현을 확인에 필요한 만큼만) ─────────────────────────────

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


# 점은 확장 좌표 (X, Y, Z, T) · x = X/Z, y = Y/Z, x*y = T/Z
def _add(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    aa = (y1 - x1) * (y2 - x2) % _P
    bb = (y1 + x1) * (y2 + x2) % _P
    cc = 2 * t1 * t2 * _D % _P
    dd = 2 * z1 * z2 % _P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, point: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    q = (0, 1, 1, 0)  # 항등원
    while s > 0:
        if s & 1:
            q = _add(q, point)
        point = _add(point, point)
        s >>= 1
    return q


def _equal(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    x1, y1, z1, _ = a
    x2, y2, z2, _ = b
    return (x1 * z2 - x2 * z1) % _P == 0 and (y1 * z2 - y2 * z1) % _P == 0


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


def _decompress(raw: bytes) -> tuple[int, int, int, int] | None:
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


_G_Y = 4 * _inv(5) % _P
_G = (_recover_x(_G_Y, 0) or 0, _G_Y, 1, (_recover_x(_G_Y, 0) or 0) * _G_Y % _P)


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """RFC 8032 §5.1.7. 맞으면 True. 모양이 틀린 입력도 예외 없이 False."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    a = _decompress(public_key)
    if a is None:
        return False
    r_raw = signature[:32]
    r = _decompress(r_raw)
    if r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:  # 서명 가단성 막기 — RFC 가 「반드시 거절」로 적은 칸
        return False
    h = int.from_bytes(hashlib.sha512(r_raw + public_key + message).digest(), "little") % _L
    return _equal(_mul(s, _G), _add(r, _mul(h, a)))


# ── minisign ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PublicKey:
    key_id: bytes
    key: bytes

    @property
    def key_id_hex(self) -> str:
        # minisign 이 「public key: 22486BF1EEB1DB94」로 보여 주는 값은 열쇠번호를 거꾸로 읽은 16진수다.
        return self.key_id[::-1].hex().upper()


@dataclass(frozen=True)
class Verified:
    """확인을 지난 서명. `trusted_comment` 는 **확인 뒤에만** 믿을 수 있다(전역 서명이 덮는다)."""

    key_id_hex: str
    trusted_comment: str
    prehashed: bool


def _unwrap(text: str) -> str:
    """타우리처럼 글 전체를 base64 로 한 번 더 싼 것이면 벗긴다. 이미 글이면 그대로."""
    stripped = text.strip()
    if stripped.startswith("untrusted comment:"):
        return stripped
    try:
        decoded = base64.b64decode(stripped, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise SignatureError("minisign 글이 아닙니다(base64 로도 풀리지 않음)") from exc
    if not decoded.lstrip().startswith("untrusted comment:"):
        raise SignatureError("minisign 글이 아닙니다(untrusted comment 줄이 없음)")
    return decoded.strip()


def _b64(line: str, size: int, what: str) -> bytes:
    try:
        raw = base64.b64decode(line.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError(f"{what} 이 base64 가 아닙니다") from exc
    if len(raw) != size:
        raise SignatureError(f"{what} 길이가 {len(raw)} 바이트입니다(기대 {size})")
    return raw


def load_public_key(text: str) -> PublicKey:
    """`minisign.pub` 글, 또는 그것을 base64 로 싼 타우리 설정 값."""
    if not text or not text.strip():
        raise SignatureError("공개 열쇠가 비어 있습니다")
    lines = [line for line in _unwrap(text).splitlines() if line.strip()]
    if len(lines) < 2:
        raise SignatureError("공개 열쇠 글에 열쇠 줄이 없습니다")
    raw = _b64(lines[1], 42, "공개 열쇠")
    if raw[:2] != b"Ed":
        raise SignatureError("ed25519 공개 열쇠가 아닙니다")
    return PublicKey(key_id=raw[2:10], key=raw[10:42])


def verify(data: bytes, signature_text: str, public_key: PublicKey | str) -> Verified:
    """minisign 서명 확인. 맞으면 `Verified`, 아니면 `SignatureError`.

    순서가 중요하다 — **확인을 마치기 전에는 신뢰 주석을 한 글자도 쓰지 않는다**(타우리 플러그인 주석과 같은 규칙).
    """
    key = load_public_key(public_key) if isinstance(public_key, str) else public_key
    lines = [line.rstrip("\r") for line in _unwrap(signature_text).splitlines()]
    if len(lines) < 4 or not lines[2].startswith("trusted comment: "):
        raise SignatureError("서명 글의 줄 모양이 minisign 이 아닙니다")
    raw = _b64(lines[1], 74, "서명")
    algorithm, key_id, sig = raw[:2], raw[2:10], raw[10:74]
    if algorithm not in (b"Ed", b"ED"):
        raise SignatureError("모르는 서명 방식입니다")
    if key_id != key.key_id:
        raise SignatureError(
            f"다른 열쇠로 만든 서명입니다(서명 {key_id[::-1].hex().upper()} ≠ 박아 둔 {key.key_id_hex})"
        )
    prehashed = algorithm == b"ED"
    message = hashlib.blake2b(data, digest_size=64).digest() if prehashed else data
    if not ed25519_verify(key.key, message, sig):
        raise SignatureError("서명이 맞지 않습니다 — 파일이 바뀌었거나 가짜입니다")
    comment = lines[2][len("trusted comment: "):]
    global_sig = _b64(lines[3], 64, "전역 서명")
    if not ed25519_verify(key.key, sig + comment.encode("utf-8"), global_sig):
        raise SignatureError("신뢰 주석의 서명이 맞지 않습니다 — 주석이 바뀌었습니다")
    return Verified(key_id_hex=key.key_id_hex, trusted_comment=comment, prehashed=prehashed)
