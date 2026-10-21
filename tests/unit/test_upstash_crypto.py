from __future__ import annotations

import base64
import pytest

from core.crypto import (
    DecryptionError,
    PayloadCorruptedError,
    decrypt_payload,
    derive_key,
    encrypt_payload,
)


def test_crypto_roundtrip():
    passphrase = "my-super-secret-password-123"
    plaintext = b"sensitive node and secret configuration bundle"
    metadata = {"device": "laptop-1", "count": 3}

    encrypted = encrypt_payload(plaintext, passphrase, metadata=metadata, iterations=10_000)
    assert encrypted["version"] == 1
    assert encrypted["algorithm"] == "AES-256-GCM"
    assert encrypted["metadata"]["device"] == "laptop-1"
    assert "ciphertext" in encrypted

    decrypted = decrypt_payload(encrypted, passphrase)
    assert decrypted == plaintext


def test_crypto_wrong_passphrase_fails():
    passphrase = "correct-passphrase"
    plaintext = b"secret data"

    encrypted = encrypt_payload(plaintext, passphrase, iterations=10_000)

    with pytest.raises(DecryptionError, match="密碼錯誤"):
        decrypt_payload(encrypted, "wrong-passphrase")


def test_crypto_tampered_ciphertext_fails():
    passphrase = "passphrase"
    plaintext = b"secret data"
    encrypted = encrypt_payload(plaintext, passphrase, iterations=10_000)

    raw_bytes = bytearray(base64.b64decode(encrypted["ciphertext"]))
    raw_bytes[0] ^= 0xFF
    encrypted["ciphertext"] = base64.b64encode(raw_bytes).decode("ascii")

    with pytest.raises(DecryptionError):
        decrypt_payload(encrypted, passphrase)


def test_crypto_corrupted_payload_fields():
    with pytest.raises(PayloadCorruptedError):
        decrypt_payload({"version": 1}, "pass")

    with pytest.raises(PayloadCorruptedError):
        decrypt_payload(
            {
                "version": 1,
                "algorithm": "UNKNOWN",
                "kdf": "PBKDF2HMAC-SHA256",
                "iterations": 1000,
                "salt": "abc",
                "nonce": "abc",
                "ciphertext": "abc",
            },
            "pass",
        )


def test_empty_passphrase_rejected():
    with pytest.raises(ValueError, match="Passphrase cannot be empty"):
        derive_key("", b"0" * 16)

    with pytest.raises(ValueError, match="Passphrase cannot be empty"):
        encrypt_payload(b"hello", "")

    with pytest.raises(ValueError, match="Passphrase cannot be empty"):
        decrypt_payload({}, "")
