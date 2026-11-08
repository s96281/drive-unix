"""Secret references and secure-ish persistence backends.

Configuration files store references (``env:``, ``keyring:``, or ``file:``),
never the secret value itself.  OS keyring is preferred when available; a
0600 JSON file is the portability fallback for headless/minimal systems.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

KEYRING_SERVICE = "drive-unix"


class SecretStoreError(RuntimeError):
    """Raised when a configured secret cannot be persisted or resolved."""


class SecretStore(Protocol):
    def put(self, key: str, value: str) -> str: ...
    def get(self, reference: str) -> str | None: ...
    def delete(self, reference: str) -> None: ...


class SecretRepository:
    """Resolve secret references and persist interactive secrets.

    Reference formats:
      * ``env:NAME``: read-only environment variable reference.
      * ``keyring:key``: OS credential/keyring entry.
      * ``file:key``: permission-hardened local fallback store.
    """

    def __init__(
        self,
        file_path: Path,
        *,
        service_name: str = KEYRING_SERVICE,
        prefer_keyring: bool = True,
    ) -> None:
        self.file_path = Path(file_path).expanduser()
        self.service_name = service_name
        self.prefer_keyring = prefer_keyring

    @staticmethod
    def environment_reference(variable: str, *, require_present: bool = True) -> str:
        name = variable.strip()
        if not name:
            raise ValueError("環境變數名稱不可為空。")
        if require_present and not os.getenv(name):
            raise ValueError(f"環境變數 {name} 未設定或內容為空。")
        return f"env:{name}"

    def put(self, key: str, value: str) -> str:
        if not key.strip():
            raise ValueError("Secret key cannot be empty.")
        if not value:
            raise ValueError("Secret value cannot be empty.")

        if self.prefer_keyring and self._keyring_set(key, value):
            return f"keyring:{key}"

        values = self._read_file_store()
        values[key] = value
        self._write_file_store(values)
        return f"file:{key}"

    def get(self, reference: str) -> str | None:
        scheme, key = self._parse_reference(reference)
        if scheme == "env":
            return os.getenv(key)
        if scheme == "keyring":
            return self._keyring_get(key)
        if scheme == "file":
            return self._read_file_store().get(key)
        raise SecretStoreError(f"Unsupported secret reference scheme: {scheme}")

    def delete(self, reference: str) -> None:
        scheme, key = self._parse_reference(reference)
        if scheme == "env":
            return
        if scheme == "keyring":
            self._keyring_delete(key)
            return
        if scheme == "file":
            values = self._read_file_store()
            if key in values:
                del values[key]
                self._write_file_store(values)
            return
        raise SecretStoreError(f"Unsupported secret reference scheme: {scheme}")

    @staticmethod
    def _parse_reference(reference: str) -> tuple[str, str]:
        if not reference or ":" not in reference:
            raise SecretStoreError("Invalid secret reference.")
        scheme, key = reference.split(":", 1)
        if not key:
            raise SecretStoreError("Invalid secret reference: missing key.")
        return scheme.lower(), key

    def _keyring_module(self):
        try:
            import keyring
        except ImportError:
            return None
        return keyring

    def _keyring_set(self, key: str, value: str) -> bool:
        keyring = self._keyring_module()
        if keyring is None:
            return False
        try:
            keyring.set_password(self.service_name, key, value)
            return True
        except Exception:
            # Headless Linux systems frequently have the package installed but
            # no usable backend. Falling back to the local 0600 store keeps the
            # CLI functional without silently losing the credential.
            return False

    def _keyring_get(self, key: str) -> str | None:
        keyring = self._keyring_module()
        if keyring is None:
            raise SecretStoreError(
                "此 secret 使用 OS keyring，但目前環境未安裝 keyring 套件。"
            )
        try:
            value = keyring.get_password(self.service_name, key)
            return value if isinstance(value, str) else None
        except Exception as exc:
            raise SecretStoreError(f"無法從 OS keyring 讀取 secret: {exc}") from exc

    def _keyring_delete(self, key: str) -> None:
        keyring = self._keyring_module()
        if keyring is None:
            return
        try:
            keyring.delete_password(self.service_name, key)
        except Exception:
            # Deleting a missing/unavailable keyring entry should not block
            # removing the remote configuration itself.
            return

    def _read_file_store(self) -> dict[str, str]:
        if not self.file_path.exists():
            return {}
        self._chmod_best_effort(self.file_path.parent, 0o700)
        self._chmod_best_effort(self.file_path, 0o600)
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SecretStoreError(
                f"無法讀取 secret store {self.file_path}: {exc}"
            ) from exc
        if not isinstance(data, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in data.items()
        ):
            raise SecretStoreError(f"Secret store 格式無效: {self.file_path}")
        return data

    def _write_file_store(self, values: dict[str, str]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._chmod_best_effort(self.file_path.parent, 0o700)
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{self.file_path.name}.",
            suffix=".tmp",
            dir=str(self.file_path.parent),
            text=True,
        )
        try:
            self._chmod_best_effort(Path(temp_path), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(values, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.file_path)
            self._chmod_best_effort(self.file_path, 0o600)
        except Exception as exc:
            raise SecretStoreError(
                f"無法寫入 secret store {self.file_path}: {exc}"
            ) from exc
        finally:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass

    @staticmethod
    def _chmod_best_effort(path: Path, mode: int) -> None:
        try:
            os.chmod(path, mode)
        except OSError:
            pass
