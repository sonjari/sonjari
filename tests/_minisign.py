"""시험용 minisign 서명 만들기 (2026-11-16) — **시험에서만.** 운영 서명은 빌드 PC 의 `tauri signer sign` 이 한다.

`cryptography` 로 임시 ed25519 열쇠를 만들어 minisign 형식(타우리와 같은 모양)으로 싼다. 없으면 이걸 쓰는 시험은 건너뛴다.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

import pytest

ed25519 = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")


@dataclass
class SigningKey:
    private: object
    public: bytes
    key_id: bytes

    @classmethod
    def new(cls) -> "SigningKey":
        private = ed25519.Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return cls(private=private, public=public, key_id=os.urandom(8))

    def pub_text(self, *, wrap: bool = True) -> str:
        """타우리 설정처럼 base64 로 한 번 더 싼 것(wrap) 또는 minisign.pub 글 그대로."""
        text = ("untrusted comment: minisign public key: " + self.key_id[::-1].hex().upper() + "\n"
                + base64.b64encode(b"Ed" + self.key_id + self.public).decode() + "\n")
        return base64.b64encode(text.encode()).decode() if wrap else text

    def sign(self, data: bytes, *, comment: str = "timestamp:1794810745\tfile:sonjari-mac.json",
             prehashed: bool = True, wrap: bool = True) -> str:
        message = hashlib.blake2b(data, digest_size=64).digest() if prehashed else data
        sig = self.private.sign(message)
        global_sig = self.private.sign(sig + comment.encode())
        text = ("untrusted comment: signature from tauri secret key\n"
                + base64.b64encode((b"ED" if prehashed else b"Ed") + self.key_id + sig).decode() + "\n"
                + "trusted comment: " + comment + "\n"
                + base64.b64encode(global_sig).decode() + "\n")
        return base64.b64encode(text.encode()).decode() if wrap else text
