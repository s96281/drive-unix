"""Hashing helpers shared by local storage and CLI commands."""

from __future__ import annotations

import base64
import hashlib

from core.constants import DEFAULT_BUFFER_SIZE


class QuickXorHash:
    """Microsoft QuickXorHash implementation.

    The implementation supports incremental ``update`` calls so callers can hash
    large files without loading the complete file into memory.
    """

    WIDTH_IN_BITS = 160
    SIZE_IN_BYTES = 20
    SHIFT = 11

    def __init__(self) -> None:
        self._bits = 0
        self._length = 0

    def update(self, data: bytes) -> QuickXorHash:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes-like")

        mask = (1 << self.WIDTH_IN_BITS) - 1
        for byte in bytes(data):
            bit_offset = (self._length * self.SHIFT) % self.WIDTH_IN_BITS
            self._bits ^= (byte << bit_offset) & mask

            overflow = bit_offset + 8 - self.WIDTH_IN_BITS
            if overflow > 0:
                self._bits ^= byte >> (8 - overflow)

            self._length += 1

        return self

    def digest(self) -> bytes:
        result = bytearray(self._bits.to_bytes(self.SIZE_IN_BYTES, "little"))
        length_bytes = self._length.to_bytes(8, "little")
        start = self.SIZE_IN_BYTES - 8
        for index, value in enumerate(length_bytes):
            result[start + index] ^= value
        return bytes(result)

    def base64digest(self) -> str:
        return base64.b64encode(self.digest()).decode("ascii")


def calculate_local_hash(
    file_path: str,
    algorithm: str,
    *,
    chunk_size: int = DEFAULT_BUFFER_SIZE,
) -> str:
    """Calculate a local file hash using a bounded memory buffer."""

    normalized = algorithm.lower()
    if normalized in {"quickxorhash", "quickxor", "qxh"}:
        hasher = QuickXorHash()
        with open(file_path, "rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(chunk_size), b""):
                hasher.update(chunk)
        return hasher.base64digest()

    if normalized not in hashlib.algorithms_available:
        raise ValueError(f"不支援的雜湊演算法: {algorithm}")

    hashlib_hasher = hashlib.new(normalized)
    with open(file_path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(chunk_size), b""):
            hashlib_hasher.update(chunk)
    return hashlib_hasher.hexdigest()


__all__ = ["QuickXorHash", "calculate_local_hash"]
