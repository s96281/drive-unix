"""Fine-grained token synchronization, distributed locking, and proactive renewal."""

from __future__ import annotations

import json
import logging
import os
import socket
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from auth.base import AuthContext, AuthProvider
from auth.identity import build_identity_cache_key, get_canonical_auth_identity
from core.config import ConfigManager, _chmod_best_effort
from core.crypto import DecryptionError, decrypt_payload, encrypt_payload
from infrastructure.upstash_client import UpstashClient

logger = logging.getLogger("drive_unix.upstash_token_service")


class UpstashTokenService:
    """Manages fine-grained, end-to-end encrypted token sharing on Upstash."""

    def __init__(
        self,
        config_manager: ConfigManager,
        *,
        client: UpstashClient | None = None,
        device_id: str | None = None,
    ) -> None:
        self.config_manager = config_manager
        self._client = client
        self.device_id = device_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
        self._synced_identities: set[str] = set()
        self._picked_from_cloud_identities: set[str] = set()

    def get_sync_status(self) -> tuple[bool, str]:
        """Check if Upstash token sync is configured and enabled, with a descriptive reason."""
        cfg = self.config_manager.config.upstash
        if cfg is not None and not cfg.auto_sync_tokens:
            return False, "設定檔已關閉自動同步憑證 (auto_sync_tokens=false)"
        url, token, _ = self.config_manager.get_upstash_config()
        if not url or not token:
            return False, "尚未設定 Upstash REST URL 或 Token"
        passphrase = self.config_manager.get_upstash_passphrase()
        if not passphrase:
            return False, "尚未設定 E2EE 主密碼 (Passphrase)"
        return True, "已啟用 E2EE 憑證同步"

    def is_enabled(self) -> bool:
        """Check if Upstash token sync is configured and enabled."""
        enabled, _ = self.get_sync_status()
        return enabled

    def get_client(self) -> UpstashClient | None:
        """Obtain or build UpstashClient if configuration exists."""
        if self._client is not None:
            return self._client
        url, token, _ = self.config_manager.get_upstash_config()
        if url and token:
            self._client = UpstashClient(url, token, timeout=3.0)
            return self._client
        return None

    def _token_key(self, identity_key: str) -> str:
        return f"drive-unix:token:{identity_key}"

    def _lock_key(self, identity_key: str) -> str:
        return f"drive-unix:lock:{identity_key}"

    def try_get_token(
        self,
        identity_key: str,
        raw_cache_path: Path | None = None,
        leeway_seconds: int = 60,
    ) -> AuthContext | None:
        """Fetch and decrypt an AuthContext from Upstash if valid and not expired."""
        if not self.is_enabled():
            return None

        client = self.get_client()
        if not client:
            return None

        passphrase = self.config_manager.get_upstash_passphrase()
        if not passphrase:
            return None

        try:
            raw_str = client.get(self._token_key(identity_key))
            if not raw_str:
                return None

            payload = json.loads(raw_str)
            metadata = payload.get("metadata", {})

            expires_at = metadata.get("expires_at")
            if expires_at is not None and (time.time() + leeway_seconds) >= float(expires_at):
                # Cloud token is already expired or expiring imminently
                return None

            decrypted_bytes = decrypt_payload(payload, passphrase)
            bundle = json.loads(decrypted_bytes.decode("utf-8"))

            auth_ctx_data = bundle.get("auth_context")
            if not auth_ctx_data:
                return None

            # Restore underlying raw OAuth token file if available
            raw_content = bundle.get("raw_token_content")
            if raw_cache_path and raw_content:
                self._write_raw_file(raw_cache_path, raw_content)

            auth_context = AuthContext.from_dict(auth_ctx_data)
            if "updated_at" in bundle and "cloud_updated_at" not in auth_context.metadata:
                auth_context.metadata["cloud_updated_at"] = bundle["updated_at"]
            if "device_id" in bundle and "cloud_device_id" not in auth_context.metadata:
                auth_context.metadata["cloud_device_id"] = bundle["device_id"]

            logger.info("成功從 Upstash 自動獲取最新加密憑證 (Identity: %s)", identity_key[:8])
            return auth_context

        except DecryptionError:
            logger.warning("Upstash Token 解密失敗：Passphrase 不符或資料損毀。")
            return None
        except Exception as exc:
            logger.debug("查詢 Upstash Token 時發生非致命例外: %s", exc)
            return None

    def try_put_token(
        self,
        identity_key: str,
        auth_context: AuthContext,
        raw_cache_path: Path | None = None,
    ) -> bool:
        """Encrypt and upload updated AuthContext to Upstash."""
        cfg = self.config_manager.config.upstash
        if not self.is_enabled() or (cfg and not cfg.auto_push_tokens):
            return False

        client = self.get_client()
        passphrase = self.config_manager.get_upstash_passphrase()
        if not client or not passphrase:
            return False

        try:
            raw_content: str | None = None
            if raw_cache_path and raw_cache_path.exists():
                try:
                    raw_content = raw_cache_path.read_text(encoding="utf-8")
                except Exception:
                    pass

            now = time.time()
            bundle = {
                "identity_key": identity_key,
                "device_id": self.device_id,
                "updated_at": now,
                "expires_at": auth_context.expires_at,
                "auth_context": auth_context.to_dict(),
                "raw_token_content": raw_content,
            }
            public_metadata = {
                "identity_key": identity_key,
                "device_id": self.device_id,
                "updated_at": now,
                "expires_at": auth_context.expires_at,
            }

            plaintext = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
            # Use 100k iterations for rapid, responsive token exchange
            encrypted = encrypt_payload(plaintext, passphrase, metadata=public_metadata, iterations=100_000)

            # Store in Upstash with 7-day TTL
            payload_str = json.dumps(encrypted, ensure_ascii=False)
            client.set(self._token_key(identity_key), payload_str, ex_seconds=60 * 60 * 24 * 7)
            self._synced_identities.add(identity_key)
            logger.info("已將最新憑證加密回寫至 Upstash (Identity: %s)", identity_key[:8])
            return True

        except Exception as exc:
            logger.warning("回寫 Token 至 Upstash 失敗: %s", exc)
            return False

    def with_distributed_refresh_lock(
        self,
        identity_key: str,
        refresh_fn: Callable[[], AuthContext],
        raw_cache_path: Path | None = None,
    ) -> AuthContext:
        """Coordinate token refresh using Upstash distributed lock to prevent token rotation collision."""
        if not self.is_enabled():
            return refresh_fn()

        client = self.get_client()
        if not client:
            return refresh_fn()

        lock_key = self._lock_key(identity_key)

        try:
            acquired = client.acquire_lock(lock_key, self.device_id, ttl_seconds=15)
        except Exception:
            acquired = True  # Fallback to local refresh if lock fails

        def _is_valid_peer_refresh(cached_ctx: AuthContext | None) -> bool:
            if not cached_ctx:
                return False
            # 1. If expires_at is explicitly in the future (> now + 60s), peer already renewed it
            if cached_ctx.expires_at is not None and cached_ctx.expires_at > time.time() + 60:
                return True
            # 2. If expires_at is None, only treat as valid peer refresh if it was updated within
            # the last 60s by another device (indicating another device just finished refreshing)
            cloud_updated = cached_ctx.metadata.get("cloud_updated_at")
            cloud_device = cached_ctx.metadata.get("cloud_device_id")
            if cloud_updated is not None and cloud_device != self.device_id:
                try:
                    return (time.time() - float(cloud_updated)) < 60
                except (TypeError, ValueError):
                    pass
            return False

        if acquired:
            try:
                # Double-check if another machine updated it right before we locked
                cached = self.try_get_token(identity_key, raw_cache_path)
                if cached is not None and _is_valid_peer_refresh(cached):
                    self._synced_identities.add(identity_key)
                    self._picked_from_cloud_identities.add(identity_key)
                    return cached

                auth_context = refresh_fn()
                if self.try_put_token(identity_key, auth_context, raw_cache_path):
                    self._synced_identities.add(identity_key)
                return auth_context
            finally:
                try:
                    client.release_lock(lock_key, self.device_id)
                except Exception:
                    pass
        else:
            # Another device is actively refreshing this identity!
            logger.info("偵測到其他裝置正在換發憑證 (Identity: %s)，等候並拾取結果...", identity_key[:8])
            time.sleep(1.5)
            cached = self.try_get_token(identity_key, raw_cache_path)
            if cached is not None and _is_valid_peer_refresh(cached):
                self._synced_identities.add(identity_key)
                self._picked_from_cloud_identities.add(identity_key)
                return cached

            # Fallback if other device timed out or failed
            auth_context = refresh_fn()
            if self.try_put_token(identity_key, auth_context, raw_cache_path):
                self._synced_identities.add(identity_key)
            return auth_context

    def renew_all_tokens(
        self,
        leeway_minutes: int = 30,
        remote_filter: str | None = None,
        progress_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Proactively inspect and renew expiring tokens across deduplicated accounts."""
        from storage.registry import DEFAULT_PROVIDER_REGISTRY

        # Ensure the provider registry uses this token service instance
        self.config_manager._upstash_token_service = self

        leeway_seconds = leeway_minutes * 60
        now = time.time()

        cloud_enabled, cloud_reason = self.get_sync_status()
        cloud_disabled_reason = None if cloud_enabled else cloud_reason

        renewed: list[str] = []
        skipped: list[str] = []
        cloud_synced: list[str] = []
        errors: dict[str, str] = {}

        # 1. Group remotes by canonical auth identity
        identity_to_remotes: dict[str, list[str]] = {}
        for r_name, remote in self.config_manager.config.remotes.items():
            if remote_filter and r_name != remote_filter:
                continue
            if remote.type not in {"sharepoint", "onedrive_business", "onedrive", "google_drive", "googlephotos"}:
                continue
            ident = get_canonical_auth_identity(r_name, remote, self.config_manager)
            identity_to_remotes.setdefault(ident, []).append(r_name)

        total_remotes = sum(len(remotes) for remotes in identity_to_remotes.values())
        if progress_cb:
            progress_cb({
                "event": "start",
                "total_remotes": total_remotes,
                "unique_count": len(identity_to_remotes),
                "cloud_enabled": cloud_enabled,
                "cloud_disabled_reason": cloud_disabled_reason,
            })

        # 2. Renew each unique identity once
        for idx, (ident, remotes_group) in enumerate(identity_to_remotes.items(), start=1):
            primary_remote_name = remotes_group[0]
            ident_key = build_identity_cache_key(ident)

            if progress_cb:
                progress_cb({
                    "event": "checking",
                    "index": idx,
                    "total": len(identity_to_remotes),
                    "identity": ident,
                    "identity_key": ident_key,
                    "remotes": remotes_group,
                })

            try:
                storage = DEFAULT_PROVIDER_REGISTRY.create(primary_remote_name, self.config_manager)
                auth_prov = getattr(storage, "auth_provider", None)
                if not auth_prov:
                    skipped.append(primary_remote_name)
                    if progress_cb:
                        progress_cb({
                            "event": "skipped",
                            "identity": ident,
                            "remotes": remotes_group,
                            "expires_at": None,
                            "remaining_seconds": None,
                        })
                    continue

                ctx = auth_prov.get_auth_context()
                exp = ctx.expires_at
                remaining_sec = (exp - now) if exp is not None else None

                # Check if expiring soon
                if remaining_sec is not None and remaining_sec > leeway_seconds:
                    skipped.extend(remotes_group)
                    if progress_cb:
                        progress_cb({
                            "event": "skipped",
                            "identity": ident,
                            "remotes": remotes_group,
                            "expires_at": exp,
                            "remaining_seconds": remaining_sec,
                        })
                    continue

                # Trigger refresh under lock
                if progress_cb:
                    progress_cb({
                        "event": "refreshing",
                        "identity": ident,
                        "remotes": remotes_group,
                        "expires_at": exp,
                        "remaining_seconds": remaining_sec,
                    })

                new_ctx = auth_prov.refresh()
                renewed.extend(remotes_group)

                is_picked = ident_key in self._picked_from_cloud_identities
                is_pushed = ident_key in self._synced_identities and not is_picked
                is_synced = is_picked or is_pushed

                if is_synced:
                    cloud_synced.extend(remotes_group)

                if is_pushed:
                    sync_action = "pushed"
                elif is_picked:
                    sync_action = "picked"
                elif not cloud_enabled:
                    sync_action = "disabled"
                else:
                    sync_action = "failed"

                if progress_cb:
                    progress_cb({
                        "event": "renewed",
                        "identity": ident,
                        "remotes": remotes_group,
                        "cloud_synced": is_synced,
                        "sync_action": sync_action,
                        "token_key": self._token_key(ident_key) if (is_synced or cloud_enabled) else None,
                    })

                logger.info("換發中心成功換發帳號憑證: %s (關聯節點: %s)", ident, remotes_group)

            except Exception as exc:
                errors[primary_remote_name] = str(exc)
                if progress_cb:
                    progress_cb({
                        "event": "error",
                        "identity": ident,
                        "remotes": remotes_group,
                        "error": str(exc),
                    })
                logger.error("換發中心換發節點 %s 失敗: %s", primary_remote_name, exc)

        pushed_remotes: list[str] = []
        picked_remotes: list[str] = []
        for ident, remotes_group in identity_to_remotes.items():
            ident_key = build_identity_cache_key(ident)
            if ident_key in self._picked_from_cloud_identities:
                picked_remotes.extend([r for r in remotes_group if r in renewed])
            elif ident_key in self._synced_identities:
                pushed_remotes.extend([r for r in remotes_group if r in renewed])

        return {
            "status": "ok",
            "cloud_enabled": cloud_enabled,
            "cloud_disabled_reason": cloud_disabled_reason,
            "unique_identities_count": len(identity_to_remotes),
            "renewed_remotes": sorted(set(renewed)),
            "pushed_remotes": sorted(set(pushed_remotes)),
            "picked_remotes": sorted(set(picked_remotes)),
            "skipped_remotes": sorted(set(skipped)),
            "cloud_synced_remotes": sorted(set(cloud_synced)),
            "errors": errors,
        }

    @staticmethod
    def _write_raw_file(path: Path, content: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _chmod_best_effort(path.parent, 0o700)
            fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            _chmod_best_effort(Path(tmp), 0o600)
            os.replace(tmp, path)
            _chmod_best_effort(path, 0o600)
        except Exception:
            pass
