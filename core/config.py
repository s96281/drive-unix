import os
import tempfile
from pathlib import Path
from typing import Any, Literal, Union

import tomlkit
from pydantic import BaseModel, Field, ValidationError
from tomlkit.exceptions import TOMLKitError
from tomlkit.toml_document import TOMLDocument

from enum import Enum
from core.secrets import SecretRepository, SecretStore, SecretStoreError

# ==========================================
# 1. 定義遠端節點與應用程式設定結構 (Pydantic Models)
# ==========================================

class RemoteType(str, Enum):
    SHAREPOINT = "sharepoint"
    ONEDRIVE = "onedrive"
    ONEDRIVE_BUSINESS = "onedrive_business"
    ALIST = "alist"
    GOOGLE_DRIVE = "google_drive"
    GOOGLE_PHOTOS = "googlephotos"
    LOCAL = "local"
    FTP = "ftp"
    WEBDAV = "webdav"
    SFTP = "sftp"
    PIKPAK = "pikpak"

class SharePointRemote(BaseModel):
    type: Literal["sharepoint"]
    base_url: str
    site: str
    email: str
    password_ref: str | None = None
    cache_source: str = "sharepoint_main" 

class GoogleDriveRemote(BaseModel):
    type: Literal["google_drive"]
    credentials_json: str
    root_folder_id: str = "root"

class GooglePhotosRemote(BaseModel):
    type: Literal["googlephotos"]
    credentials_json: str
    default_album: str | None = None

class OneDriveRemote(BaseModel):
    type: Literal["onedrive"]
    client_id: str
    client_secret_ref: str | None = None
    tenant: str = "common"

class OneDriveBusinessRemote(BaseModel):
    type: Literal["onedrive_business"]
    base_url: str
    email: str
    password_ref: str | None = None
    site: str = ""

class AlistRemote(BaseModel):
    type: Literal["alist"]
    base_url: str
    username: str
    password_ref: str | None = None

class LocalRemote(BaseModel):
    type: Literal["local"]
    root_path: str

class FTPRemote(BaseModel):
    type: Literal["ftp"]
    host: str
    port: int = 21
    username: str = "anonymous"
    password_ref: str | None = None
    tls: bool = False
    passive: bool = True
    root_path: str = "/"

class WebDAVRemote(BaseModel):
    type: Literal["webdav"]
    base_url: str
    username: str
    password_ref: str | None = None

class SFTPRemote(BaseModel):
    type: Literal["sftp"]
    host: str
    port: int = 22
    username: str
    password_ref: str | None = None
    key_filename: str | None = None
    known_hosts: str | None = None
    root_path: str = "/"

class PikPakRemote(BaseModel):
    type: Literal["pikpak"]
    username: str
    password_ref: str | None = None
    client_id: str | None = None
    root_folder_id: str = ""

# 允許一個設定檔中包含多種型態的 Remote
RemoteConfig = Union[
    SharePointRemote, 
    OneDriveRemote, 
    OneDriveBusinessRemote,
    AlistRemote, 
    GoogleDriveRemote, 
    GooglePhotosRemote,
    LocalRemote, 
    FTPRemote, 
    WebDAVRemote, 
    SFTPRemote,
    PikPakRemote,
]

class CronTask(BaseModel):
    name: str
    schedule: str
    command: str
    enabled: bool = True
    # ``last_run`` is retained for backwards compatibility with existing config files.
    # New scheduler code records the more precise attempt/success/result fields below.
    last_run: str | None = None
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_exit_code: int | None = None

class UpstashSyncConfig(BaseModel):
    rest_url: str | None = None
    token_ref: str | None = None
    passphrase_ref: str | None = None
    sync_key: str = "drive-unix:sync:default"
    auto_sync_tokens: bool = True
    auto_push_tokens: bool = True
    renew_leeway_minutes: int = 30

class AppConfig(BaseModel):
    default_remote: str | None = None
    remotes: dict[str, RemoteConfig] = Field(default_factory=dict)
    tasks: dict[str, CronTask] = Field(default_factory=dict)
    upstash: UpstashSyncConfig | None = None

# ==========================================
# 2. 定義配置檔路徑常數
# ==========================================

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "mycli"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"

# ==========================================
# 3. 實作配置檔管理器
# ==========================================

class ConfigManager:
    _upstash_token_service: Any = None

    def __init__(
        self,
        config_path: Path = DEFAULT_CONFIG_PATH,
        *,
        secret_store: SecretStore | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.secret_store: SecretStore = secret_store or SecretRepository(
            self.config_path.parent / "secrets.json"
        )
        self.secret_files_dir = self.config_path.parent / "secret-files"
        self._doc: TOMLDocument | None = None
        self._legacy_secrets_migrated = False
        self.config: AppConfig = self._load()
        if self._legacy_secrets_migrated:
            self.save()

    def _load(self) -> AppConfig:
        if not self.config_path.exists():
            return AppConfig()
        _chmod_best_effort(self.config_path.parent, 0o700)
        _chmod_best_effort(self.config_path, 0o600)
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                content = f.read()
            self._doc = tomlkit.loads(content)
            raw_dict = self._doc.unwrap()
            self._legacy_secrets_migrated = self._migrate_legacy_secrets(raw_dict)
            return AppConfig.model_validate(raw_dict)
        except (OSError, TOMLKitError, ValidationError, SecretStoreError) as exc:
            raise RuntimeError(f"無法讀取配置檔 {self.config_path}: {exc}") from exc

    def _migrate_legacy_secrets(self, raw_dict: dict) -> bool:
        """Move pre-Phase-4 inline secrets out of config.toml on first load."""
        remotes = raw_dict.get("remotes")
        if not isinstance(remotes, dict):
            return False

        migrated = False
        field_map = {
            "sharepoint": ("password", "password_ref", "password"),
            "onedrive_business": ("password", "password_ref", "password"),
            "alist": ("password", "password_ref", "password"),
            "ftp": ("password", "password_ref", "password"),
            "webdav": ("password", "password_ref", "password"),
            "sftp": ("password", "password_ref", "password"),
            "pikpak": ("password", "password_ref", "password"),
            "onedrive": ("client_secret", "client_secret_ref", "client-secret"),
        }

        for remote_name, remote in remotes.items():
            if not isinstance(remote, dict):
                continue
            spec = field_map.get(str(remote.get("type", "")))
            if spec is None:
                continue
            legacy_field, reference_field, secret_kind = spec
            if legacy_field not in remote:
                continue

            legacy_value = remote.pop(legacy_field)
            migrated = True
            if remote.get(reference_field) or not legacy_value:
                continue
            reference = self.secret_store.put(
                f"remote/{remote_name}/{secret_kind}",
                str(legacy_value),
            )
            remote[reference_field] = reference

        return migrated

    def store_remote_secret(self, remote_name: str, kind: str, value: str) -> str:
        return self.secret_store.put(f"remote/{remote_name}/{kind}", value)

    def environment_secret_ref(self, variable: str) -> str:
        repository = self.secret_store
        if isinstance(repository, SecretRepository):
            return repository.environment_reference(variable)
        name = variable.strip()
        if not name or not os.getenv(name):
            raise ValueError(f"環境變數 {name or '<empty>'} 未設定或內容為空。")
        return f"env:{name}"

    def resolve_secret(
        self,
        reference: str | None,
        *,
        remote_name: str,
        label: str,
        required: bool = True,
    ) -> str | None:
        if not reference:
            if required:
                raise ValueError(f"遠端節點 '{remote_name}' 缺少 {label} secret reference。")
            return None
        value = self.secret_store.get(reference)
        if value:
            return value
        if required:
            raise ValueError(
                f"遠端節點 '{remote_name}' 的 {label} secret 無法解析 ({reference})。"
            )
        return None

    def get_upstash_config(self) -> tuple[str | None, str | None, str]:
        """Resolve Upstash REST URL, token, and sync key from config or environment."""
        url = os.getenv("UPSTASH_REDIS_REST_URL")
        token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
        sync_key = os.getenv("UPSTASH_SYNC_KEY") or "drive-unix:sync:default"

        if self.config.upstash:
            if not url and self.config.upstash.rest_url:
                url = self.config.upstash.rest_url
            if not token and self.config.upstash.token_ref:
                token = self.secret_store.get(self.config.upstash.token_ref)
            if sync_key == "drive-unix:sync:default" and self.config.upstash.sync_key:
                sync_key = self.config.upstash.sync_key

        return url, token, sync_key

    def get_upstash_passphrase(self) -> str | None:
        """Resolve Upstash E2EE passphrase from environment or secret store."""
        env_pw = os.getenv("UPSTASH_SYNC_PASSPHRASE")
        if env_pw:
            return env_pw
        if self.config.upstash and self.config.upstash.passphrase_ref:
            return self.secret_store.get(self.config.upstash.passphrase_ref)
        return None

    def set_upstash_config(
        self,
        rest_url: str,
        rest_token: str | None = None,
        sync_key: str = "drive-unix:sync:default",
        passphrase: str | None = None,
        auto_sync_tokens: bool | None = None,
        auto_push_tokens: bool | None = None,
        renew_leeway_minutes: int | None = None,
    ) -> None:
        """Persist Upstash REST configuration and securely store the token/passphrase."""
        token_ref: str | None = None
        if rest_token:
            token_ref = self.secret_store.put("upstash/rest_token", rest_token)
        elif self.config.upstash and self.config.upstash.token_ref:
            token_ref = self.config.upstash.token_ref

        passphrase_ref: str | None = None
        if passphrase:
            passphrase_ref = self.secret_store.put("upstash/passphrase", passphrase)
        elif self.config.upstash and self.config.upstash.passphrase_ref:
            passphrase_ref = self.config.upstash.passphrase_ref

        cur = self.config.upstash
        effective_auto_sync = auto_sync_tokens if auto_sync_tokens is not None else (cur.auto_sync_tokens if cur else True)
        effective_auto_push = auto_push_tokens if auto_push_tokens is not None else (cur.auto_push_tokens if cur else True)
        effective_leeway = renew_leeway_minutes if renew_leeway_minutes is not None else (cur.renew_leeway_minutes if cur else 30)

        self.config.upstash = UpstashSyncConfig(
            rest_url=rest_url,
            token_ref=token_ref,
            passphrase_ref=passphrase_ref,
            sync_key=sync_key,
            auto_sync_tokens=effective_auto_sync,
            auto_push_tokens=effective_auto_push,
            renew_leeway_minutes=effective_leeway,
        )
        self.save()

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        _chmod_best_effort(self.config_path.parent, 0o700)

        if self._doc is None:
            self._doc = tomlkit.document()

        config_dict = self.config.model_dump(exclude_none=True)
        for key, value in config_dict.items():
            self._doc[key] = value

        content = tomlkit.dumps(self._doc)
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{self.config_path.name}.",
            suffix=".tmp",
            dir=str(self.config_path.parent),
            text=True,
        )

        try:
            _chmod_best_effort(temp_path, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            os.replace(temp_path, self.config_path)
            _chmod_best_effort(self.config_path, 0o600)
        finally:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass

    def get_remote(self, name: str) -> RemoteConfig:
        if name not in self.config.remotes:
            raise ValueError(f"找不到名為 '{name}' 的遠端節點設定。")
        return self.config.remotes[name]

    def add_remote(self, name: str, remote_config: RemoteConfig) -> None:
        self.config.remotes[name] = remote_config
        self.save()
        
    def remove_remote(self, name: str) -> None:
        if name in self.config.remotes:
            remote = self.config.remotes[name]
            references = self._secret_references(remote)
            del self.config.remotes[name]
            self.save()
            for reference in references:
                self.secret_store.delete(reference)

    def rename_remote(self, old_name: str, new_name: str) -> None:
        if old_name not in self.config.remotes:
            raise ValueError(f"找不到名為 '{old_name}' 的遠端節點。")
        if new_name in self.config.remotes:
            raise ValueError(f"名稱 '{new_name}' 已經存在，請選擇其他名稱。")
        self.config.remotes[new_name] = self.config.remotes.pop(old_name)
        if self.config.default_remote == old_name:
            self.config.default_remote = new_name
        self.save()

    def edit_remote(self, name: str, **kwargs) -> None:
        if name not in self.config.remotes:
            raise ValueError(f"找不到名為 '{name}' 的遠端節點。")
        remote = self.config.remotes[name]
        for key, value in kwargs.items():
            if value is not None and hasattr(remote, key):
                setattr(remote, key, value)
        self.save()

    @staticmethod
    def _secret_references(remote: RemoteConfig) -> tuple[str, ...]:
        references: list[str] = []
        for field in ("password_ref", "client_secret_ref"):
            value = getattr(remote, field, None)
            if value:
                references.append(value)
        return tuple(references)

    def add_task(self, name: str, task: CronTask) -> None:
        self.config.tasks[name] = task
        self.save()

    def remove_task(self, name: str) -> None:
        if name in self.config.tasks:
            del self.config.tasks[name]
            self.save()
        else:
            raise ValueError(f"找不到名為 '{name}' 的排程任務。")

    def toggle_task(self, name: str, enabled: bool) -> None:
        if name in self.config.tasks:
            self.config.tasks[name].enabled = enabled
            self.save()
        else:
            raise ValueError(f"找不到名為 '{name}' 的排程任務。")

    def update_task_attempt(self, name: str, attempted_at: str) -> None:
        """Persist that a scheduler invocation was accepted for execution."""
        if name in self.config.tasks:
            task = self.config.tasks[name]
            task.last_attempt_at = attempted_at
            # Keep the legacy field in sync so older releases can still read the file.
            task.last_run = attempted_at
            self.save()

    def update_task_result(
        self,
        name: str,
        *,
        completed_at: str,
        exit_code: int,
    ) -> None:
        """Persist the most recent scheduler process result."""
        if name in self.config.tasks:
            task = self.config.tasks[name]
            task.last_exit_code = exit_code
            if exit_code == 0:
                task.last_success_at = completed_at
            self.save()

    def update_task_last_run(self, name: str, last_run: str) -> None:
        """Backward-compatible alias for the pre-Phase-3 scheduler API."""
        self.update_task_attempt(name, last_run)

def _chmod_best_effort(path, mode: int) -> None:
    """Best-effort permission hardening for config files/directories."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass
