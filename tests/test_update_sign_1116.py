"""업데이트 서명 확인기 — 우리가 짠 암호 코드라 세 갈래로 묶는다 (2026-11-16).

1. RFC 8032 시험 벡터 — 수식이 맞나
2. **실제 타우리 CLI(2.11.4)가 만든 서명** — 형식이 맞나(`fixtures/mac_update/`)
3. `cryptography` 로 만든 무작위 서명과 대조 — 맞는 것은 다 받고, 하나라도 바뀐 것은 다 거절하나

그리고 반례: 바뀐 파일 · 바뀐 신뢰 주석 · 다른 열쇠 · 비트 하나 · 서명 가단성(S ≥ L) · 모양이 틀린 입력.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from alture_jarvis import update_sign

FIXTURES = Path(__file__).parent / "fixtures" / "mac_update"

# RFC 8032 §7.1 TEST 1 · TEST 2
RFC = [
    ("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
     "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
     "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]
_L = 2**252 + 27742317777372353535851937790883648493


@pytest.mark.parametrize("pub,msg,sig", RFC)
def test_rfc8032_vectors_verify(pub: str, msg: str, sig: str) -> None:
    assert update_sign.ed25519_verify(bytes.fromhex(pub), bytes.fromhex(msg), bytes.fromhex(sig))


@pytest.mark.parametrize("pub,msg,sig", RFC)
def test_rfc8032_vectors_refuse_any_changed_byte(pub: str, msg: str, sig: str) -> None:
    pub_b, msg_b, sig_b = bytes.fromhex(pub), bytes.fromhex(msg), bytes.fromhex(sig)
    assert not update_sign.ed25519_verify(pub_b, msg_b + b"x", sig_b)
    for index in (0, 31, 32, 63):
        bad = bytearray(sig_b)
        bad[index] ^= 0x01
        assert not update_sign.ed25519_verify(pub_b, msg_b, bytes(bad)), f"서명 {index}번째 비트 하나를 바꿨는데 받았다"


def test_signature_malleability_is_refused() -> None:
    """S + L 은 수식상 같은 점이지만 RFC 가 「반드시 거절」로 적었다 — 같은 파일에 서명이 둘이 되면 안 된다."""
    pub, msg, sig = (bytes.fromhex(x) for x in RFC[0])
    s = int.from_bytes(sig[32:], "little") + _L
    assert not update_sign.ed25519_verify(pub, msg, sig[:32] + s.to_bytes(32, "little"))


def test_malformed_input_is_false_not_a_crash() -> None:
    assert not update_sign.ed25519_verify(b"", b"", b"")
    assert not update_sign.ed25519_verify(b"\xff" * 32, b"m", b"\x00" * 64)


# ── 실제 타우리 서명 ─────────────────────────────────────────────────────────────────────


def _tauri() -> tuple[bytes, str, str]:
    return ((FIXTURES / "tauri_data.bin").read_bytes(), (FIXTURES / "tauri_data.bin.sig").read_text(),
            (FIXTURES / "tauri_test.pub").read_text())


def test_a_real_tauri_signature_verifies() -> None:
    data, sig, pub = _tauri()
    verified = update_sign.verify(data, sig, pub)
    assert verified.prehashed, "타우리 CLI 는 BLAKE2b 로 먼저 줄인 ED 서명을 만든다(11-16 실측)"
    assert verified.trusted_comment.startswith("timestamp:") and "file:data.bin" in verified.trusted_comment
    assert verified.key_id_hex == "22486BF1EEB1DB94"


def test_a_real_tauri_signature_refuses_a_changed_file() -> None:
    data, sig, pub = _tauri()
    with pytest.raises(update_sign.SignatureError, match="서명이 맞지 않습니다"):
        update_sign.verify(data + b"\n", sig, pub)


def test_a_real_tauri_signature_refuses_a_changed_trusted_comment() -> None:
    """신뢰 주석은 전역 서명이 덮는다 — 주석에 판 번호를 끼워 넣는 위조를 막는 칸."""
    data, sig, pub = _tauri()
    text = base64.b64decode(sig).decode()
    forged = text.replace("file:data.bin", "file:data.bin\tversion:9.9.9")
    with pytest.raises(update_sign.SignatureError, match="신뢰 주석"):
        update_sign.verify(data, base64.b64encode(forged.encode()).decode(), pub)


def test_garbage_is_a_signature_error_not_a_crash() -> None:
    data, sig, pub = _tauri()
    for bad_sig in ("", "aGVsbG8=", "untrusted comment: x\nnot base64\n"):
        with pytest.raises(update_sign.SignatureError):
            update_sign.verify(data, bad_sig, pub)
    for bad_pub in ("", "   ", "aGVsbG8="):
        with pytest.raises(update_sign.SignatureError):
            update_sign.verify(data, sig, bad_pub)


# ── cryptography 로 만든 서명과 대조 ─────────────────────────────────────────────────────


def test_random_signatures_from_a_reference_library_agree() -> None:
    _minisign = pytest.importorskip("_minisign")
    import os

    for round_ in range(12):
        key = _minisign.SigningKey.new()
        data = os.urandom(round_ * 37)
        for prehashed in (True, False):
            for wrap in (True, False):
                sig = key.sign(data, prehashed=prehashed, wrap=wrap)
                verified = update_sign.verify(data, sig, key.pub_text(wrap=wrap))
                assert verified.prehashed is prehashed
                with pytest.raises(update_sign.SignatureError):
                    update_sign.verify(data + b"!", sig, key.pub_text())


def test_another_key_is_refused_by_name() -> None:
    _minisign = pytest.importorskip("_minisign")
    ours, theirs = _minisign.SigningKey.new(), _minisign.SigningKey.new()
    with pytest.raises(update_sign.SignatureError, match="다른 열쇠"):
        update_sign.verify(b"x", theirs.sign(b"x"), ours.pub_text())


def test_another_key_with_our_key_id_is_still_refused() -> None:
    """열쇠 번호는 서명이 아니다 — 번호만 베낀 가짜 열쇠는 수식에서 떨어져야 한다."""
    _minisign = pytest.importorskip("_minisign")
    ours, theirs = _minisign.SigningKey.new(), _minisign.SigningKey.new()
    theirs.key_id = ours.key_id
    with pytest.raises(update_sign.SignatureError, match="서명이 맞지 않습니다"):
        update_sign.verify(b"x", theirs.sign(b"x"), ours.pub_text())
