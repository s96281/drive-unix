"""Upstash synchronization application service.

Coordinates bundle collection, E2EE encryption, cloud upload/download via Upstash,
and safe multi-device merging into local configuration and secret stores.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from auth.cache import DEFAULT_CACHE_DIR
from core.config import (
    ConfigManager,
    CronTask,
    RemoteConfig,
    _chmod_best_effort,
)
from core.crypto import (
    DecryptionError,
    PayloadCorruptedError,
    decrypt_payload,
    encrypt_payload,
)
from infrastructure.upstash_client import UpstashClient


class UpstashSyncService:
    """Manages the full lifecycle of Upstash cloud sync for remotes and secrets."""

    def __init__(
        self,
        config_manager: ConfigManager,
        *,
        client: UpstashClient | None = None,
        cache_dir: Path | str | None = None,
    ) -> None:
        self.config_manager = config_manager
        self._client = client
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self._remote_adapter: TypeAdapter[RemoteConfig] = TypeAdapter(RemoteConfig)

    def get_client(self) -> UpstashClient:
        """Resolve and return an UpstashClient instance."""
        if self._client is not None:
            return self._client

        url, token, _ = self.config_manager.get_upstash_config()
        if not url:
            raise ValueError(
                "未設定 Upstash REST URL。請先執行 `drive-unix upstash config` 或設定 UPSTASH_REDIS_REST_URL 環境變數。"
            )
        if not token:
            raise ValueError(
                "未設定 Upstash REST Token。請先執行 `drive-unix upstash config` 或設定 UPSTASH_REDIS_REST_TOKEN 環境變數。"
            )

        self._client = UpstashClient(url, token)
        return self._client

    def get_sync_key(self, override_key: str | None = None) -> str:
        """Resolve the effective sync key."""
        if override_key and override_key.strip():
            return override_key.strip()
        _, _, default_key = self.config_manager.get_upstash_config()
        return default_key or "drive-unix:sync:default"

    def collect_sync_bundle(
        self,
        *,
        include_auth_cache: bool = False,
        include_tasks: bool = True,
    ) -> dict[str, Any]:
        """Collect all remotes, secret values, secret files, and optional caches into a bundle dict."""
        remotes_dict: dict[str, Any] = {}
        secrets_dict: dict[str, str] = {}
        secret_files_dict: dict[str, str] = {}
        auth_cache_dict: dict[str, str] = {}

        # 1. Remotes & Secrets
        for name, remote in self.config_manager.config.remotes.items():
            remotes_dict[name] = remote.model_dump(mode="json")
            for field in ("password_ref", "client_secret_ref"):
                ref = getattr(remote, field, None)
                if ref:
                    secret_val = self.config_manager.secret_store.get(ref)
                    if secret_val is not None:
                        secrets_dict[ref] = secret_val

        # 2. Secret Files (e.g. Google OAuth client secrets)
        secret_dir = self.config_manager.secret_files_dir
        if secret_dir.exists() and secret_dir.is_dir():
            for file_path in secret_dir.iterdir():
                if file_path.is_file():
                    try:
                        secret_files_dict[file_path.name] = file_path.read_text(encoding="utf-8")
                    except Exception:
                        pass

        # 3. Tasks (optional)
        tasks_dict: dict[str, Any] = {}
        if include_tasks:
            for task_name, task in self.config_manager.config.tasks.items():
                tasks_dict[task_name] = task.model_dump(mode="json")

        # 4. Auth Cache (optional)
        if include_auth_cache and self.cache_dir.exists() and self.cache_dir.is_dir():
            for root_dir, _, files in os.walk(self.cache_dir):
                for fname in files:
                    full_p = Path(root_dir) / fname
                    rel_p = full_p.relative_to(self.cache_dir).as_posix()
                    try:
                        auth_cache_dict[rel_p] = full_p.read_text(encoding="utf-8")
                    except Exception:
                        pass

        return {
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "device_name": socket.gethostname(),
            "remotes_count": len(remotes_dict),
            "includes_auth_cache": include_auth_cache,
            "includes_tasks": include_tasks,
            "app_config": {
                "default_remote": self.config_manager.config.default_remote,
                "remotes": remotes_dict,
                "tasks": tasks_dict,
            },
            "secrets": secrets_dict,
            "secret_files": secret_files_dict,
            "auth_cache": auth_cache_dict,
        }

    def push(
        self,
        passphrase: str,
        *,
        sync_key: str | None = None,
        include_auth_cache: bool = False,
        include_tasks: bool = True,
        iterations: int = 600_000,
    ) -> dict[str, Any]:
        """Encrypt local bundle and upload to Upstash."""
        client = self.get_client()
        target_key = self.get_sync_key(sync_key)

        bundle = self.collect_sync_bundle(
            include_auth_cache=include_auth_cache,
            include_tasks=include_tasks,
        )

        plaintext = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
        public_metadata = {
            "created_at": bundle["created_at"],
            "device_name": bundle["device_name"],
            "remotes_count": bundle["remotes_count"],
            "includes_auth_cache": include_auth_cache,
            "includes_tasks": include_tasks,
            "remote_names": sorted(bundle["app_config"]["remotes"].keys()),
        }

        encrypted_payload = encrypt_payload(
            plaintext,
            passphrase,
            metadata=public_metadata,
            iterations=iterations,
        )

        payload_json = json.dumps(encrypted_payload, ensure_ascii=False)
        client.set(target_key, payload_json)

        return {
            "status": "ok",
            "sync_key": target_key,
            "remotes_count": bundle["remotes_count"],
            "created_at": bundle["created_at"],
            "device_name": bundle["device_name"],
            "payload_size_bytes": len(payload_json.encode("utf-8")),
        }

    def fetch_status(self, sync_key: str | None = None) -> dict[str, Any]:
        """Inspect remote sync bundle status from Upstash without decrypting secrets."""
        client = self.get_client()
        target_key = self.get_sync_key(sync_key)

        raw = client.get(target_key)
        if raw is None:
            return {
                "exists": False,
                "sync_key": target_key,
                "local_remotes_count": len(self.config_manager.config.remotes),
                "local_remote_names": sorted(self.config_manager.config.remotes.keys()),
            }

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PayloadCorruptedError(f"雲端資料非有效 JSON 格式: {exc}") from exc

        metadata = payload.get("metadata", {})
        return {
            "exists": True,
            "sync_key": target_key,
            "version": payload.get("version"),
            "algorithm": payload.get("algorithm"),
            "created_at": metadata.get("created_at"),
            "device_name": metadata.get("device_name"),
            "remote_names": metadata.get("remote_names", []),
            "remotes_count": metadata.get("remotes_count", 0),
            "includes_auth_cache": metadata.get("includes_auth_cache", False),
            "includes_tasks": metadata.get("includes_tasks", False),
            "local_remotes_count": len(self.config_manager.config.remotes),
            "local_remote_names": sorted(self.config_manager.config.remotes.keys()),
        }

    def pull(
        self,
        passphrase: str,
        *,
        sync_key: str | None = None,
        strategy: str = "merge",
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Pull encrypted bundle from Upstash, decrypt, and merge into local environment."""
        if strategy not in {"merge", "replace"}:
            raise ValueError(f"不支援的合併策略 '{strategy}'，可選: merge, replace")

        client = self.get_client()
        target_key = self.get_sync_key(sync_key)

        raw = client.get(target_key)
        if raw is None:
            raise ValueError(f"Upstash 上找不到指定的同步金鑰 '{target_key}' 備份資料。")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PayloadCorruptedError(f"雲端資料非有效 JSON 格式: {exc}") from exc

        decrypted_bytes = decrypt_payload(payload, passphrase)
        try:
            bundle = json.loads(decrypted_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise PayloadCorruptedError(f"解密後資料損毀，非有效 JSON 格式: {exc}") from exc

        incoming_remotes: dict[str, Any] = bundle.get("app_config", {}).get("remotes", {})
        local_remotes = set(self.config_manager.config.remotes.keys())
        incoming_names = set(incoming_remotes.keys())

        new_names = sorted(incoming_names - local_remotes)
        conflicting_names = sorted(incoming_names & local_remotes)

        if dry_run:
            return {
                "status": "dry_run",
                "sync_key": target_key,
                "strategy": strategy,
                "created_at": bundle.get("created_at"),
                "device_name": bundle.get("device_name"),
                "incoming_remotes": sorted(incoming_names),
                "local_remotes": sorted(local_remotes),
                "new_remotes": new_names,
                "conflicting_remotes": conflicting_names,
                "overwrite": overwrite,
            }

        # 1. Restore secret-files first
        secret_files = bundle.get("secret_files", {})
        if secret_files:
            self.config_manager.secret_files_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            _chmod_best_effort(self.config_manager.secret_files_dir, 0o700)
            for fname, content in secret_files.items():
                dest_file = self.config_manager.secret_files_dir / fname
                dest_file.write_text(content, encoding="utf-8")
                _chmod_best_effort(dest_file, 0o600)

        # 2. Restore secret values into target machine's secret store
        secrets_raw = bundle.get("secrets", {})
        ref_map: dict[str, str] = {}
        for old_ref, secret_val in secrets_raw.items():
            if old_ref.startswith("env:"):
                # Environment variables remain machine-specific references
                ref_map[old_ref] = old_ref
                continue

            # Strip old scheme e.g. "keyring:remote/work/password" -> "remote/work/password"
            if ":" in old_ref:
                _, key_name = old_ref.split(":", 1)
            else:
                key_name = old_ref

            new_ref = self.config_manager.secret_store.put(key_name, secret_val)
            ref_map[old_ref] = new_ref

        # 3. Handle Replace strategy
        if strategy == "replace":
            for existing in list(self.config_manager.config.remotes.keys()):
                self.config_manager.remove_remote(existing)

        # 4. Import / Merge Remotes
        restored: list[str] = []
        overwritten: list[str] = []
        skipped: list[str] = []

        for name, raw_remote in incoming_remotes.items():
            if name in self.config_manager.config.remotes:
                if strategy == "merge" and not overwrite:
                    skipped.append(name)
                    continue
                overwritten.append(name)
            else:
                restored.append(name)

            # Re-map secret references to local store references
            for ref_field in ("password_ref", "client_secret_ref"):
                old_val = raw_remote.get(ref_field)
                if old_val and old_val in ref_map:
                    raw_remote[ref_field] = ref_map[old_val]

            # Validate and store remote
            remote_model = self._remote_adapter.validate_python(raw_remote)
            self.config_manager.config.remotes[name] = remote_model

        # 5. Default remote
        if not self.config_manager.config.default_remote and bundle.get("app_config", {}).get("default_remote"):
            self.config_manager.config.default_remote = bundle["app_config"]["default_remote"]

        # 6. Tasks
        tasks_restored = 0
        if bundle.get("includes_tasks"):
            for t_name, t_raw in bundle.get("app_config", {}).get("tasks", {}).items():
                if t_name not in self.config_manager.config.tasks or overwrite:
                    self.config_manager.config.tasks[t_name] = CronTask.model_validate(t_raw)
                    tasks_restored += 1

        # 7. Auth Cache
        cache_restored = 0
        if bundle.get("auth_cache"):
            self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            _chmod_best_effort(self.cache_dir, 0o700)
            for cache_path_rel, cache_content in bundle["auth_cache"].items():
                target_cache_file = self.cache_dir / cache_path_rel
                target_cache_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                target_cache_file.write_text(cache_content, encoding="utf-8")
                _chmod_best_effort(target_cache_file, 0o600)
                cache_restored += 1

        self.config_manager.save()

        return {
            "status": "ok",
            "sync_key": target_key,
            "strategy": strategy,
            "restored_remotes": restored,
            "overwritten_remotes": overwritten,
            "skipped_remotes": skipped,
            "total_local_remotes": len(self.config_manager.config.remotes),
            "tasks_restored": tasks_restored,
            "cache_restored": cache_restored,
            "created_at": bundle.get("created_at"),
            "device_name": bundle.get("device_name"),
        }

    def delete_bundle(self, sync_key: str | None = None) -> bool:
        """Delete sync bundle from Upstash."""
        client = self.get_client()
        target_key = self.get_sync_key(sync_key)
        deleted = client.delete(target_key)
        return deleted > 0
