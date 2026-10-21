"""End-to-End Encryption (E2EE) utilities using AES-256-GCM and PBKDF2.

Designed for zero-trust cloud backups (e.g. Upstash Redis).
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

DEFAULT_PBKDF2_ITERATIONS = 600_000
KEY_LENGTH_BYTES = 32  # 256 bits
SALT_LENGTH_BYTES = 16
NONCE_LENGTH_BYTES = 12


class CryptoError(RuntimeError):
    """Base exception for cryptographic failures."""


class DecryptionError(CryptoError):
    """Raised when decryption fails (e.g., incorrect passphrase or tampered data)."""


class PayloadCorruptedError(CryptoError):
    """Raised when encrypted payload structure is malformed or invalid."""


def derive_key(passphrase: str, salt: bytes, iterations: int = DEFAULT_PBKDF2_ITERATIONS) -> bytes:
    """Derive a 256-bit encryption key from a passphrase using PBKDF2-HMAC-SHA256."""
    if not passphrase:
        raise ValueError("Passphrase cannot be empty.")
    if len(salt) < 16:
        raise ValueError("Salt must be at least 16 bytes.")

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH_BYTES,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_payload(
    plaintext_bytes: bytes,
    passphrase: str,
    *,
    metadata: dict[str, Any] | None = None,
    iterations: int = DEFAULT_PBKDF2_ITERATIONS,
) -> dict[str, Any]:
    """Encrypt plaintext bytes using AES-256-GCM with a PBKDF2-derived key.

    Returns a JSON-serializable dictionary containing base64-encoded crypto parameters
    and optional public metadata.
    """
    if not passphrase:
        raise ValueError("Passphrase cannot be empty.")

    salt = os.urandom(SALT_LENGTH_BYTES)
    nonce = os.urandom(NONCE_LENGTH_BYTES)
    key = derive_key(passphrase, salt, iterations=iterations)

    aesgcm = AESGCM(key)
    # AESGCM.encrypt appends the 16-byte authentication tag to the ciphertext
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext_bytes, None)

    return {
        "version": 1,
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2HMAC-SHA256",
        "iterations": iterations,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext_with_tag).decode("ascii"),
        "metadata": metadata or {},
    }


def decrypt_payload(encrypted_dict: dict[str, Any], passphrase: str) -> bytes:
    """Verify integrity and decrypt an AES-256-GCM payload dictionary.

    Raises:
        DecryptionError: If the passphrase is incorrect or data was tampered with.
        PayloadCorruptedError: If the dictionary is missing required fields or base64 decoding fails.
    """
    if not passphrase:
        raise ValueError("Passphrase cannot be empty.")

    required_keys = {"version", "algorithm", "kdf", "iterations", "salt", "nonce", "ciphertext"}
    missing = required_keys - set(encrypted_dict.keys())
    if missing:
        raise PayloadCorruptedError(f"Encrypted payload is missing required fields: {missing}")

    if encrypted_dict["algorithm"] != "AES-256-GCM" or encrypted_dict["kdf"] != "PBKDF2HMAC-SHA256":
        raise PayloadCorruptedError(
            f"Unsupported encryption scheme: {encrypted_dict.get('algorithm')}/{encrypted_dict.get('kdf')}"
        )

    try:
        iterations = int(encrypted_dict["iterations"])
        salt = base64.b64decode(encrypted_dict["salt"])
        nonce = base64.b64decode(encrypted_dict["nonce"])
        ciphertext_with_tag = base64.b64decode(encrypted_dict["ciphertext"])
    except Exception as exc:
        raise PayloadCorruptedError(f"Malformed base64 or parameters in payload: {exc}") from exc

    key = derive_key(passphrase, salt, iterations=iterations)
    aesgcm = AESGCM(key)

    try:
        return aesgcm.decrypt(nonce, ciphertext_with_tag, None)
    except InvalidTag as exc:
        raise DecryptionError("密碼錯誤，或雲端加密資料已被竄改 (Authentication Tag verification failed)。") from exc
    except Exception as exc:
        raise DecryptionError(f"解密失敗: {exc}") from exc
