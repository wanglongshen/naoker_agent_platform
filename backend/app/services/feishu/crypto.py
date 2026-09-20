from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


def derive_token_key(secret: str) -> bytes:
    """Derive a 32-byte AES key from a base secret via HKDF-SHA256."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"feishu-token-v1",
        info=b"feishu-token-encryption",
    ).derive(secret.encode("utf-8"))


def encrypt_token(plaintext: str, key: bytes) -> str:
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_token(ciphertext: str, key: bytes) -> str:
    raw = base64.b64decode(ciphertext)
    nonce, ct = raw[:12], raw[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")
