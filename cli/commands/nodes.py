"""Remote node management CLI commands."""

from __future__ import annotations

from cli.context import CLIContext
from cli.presentation import echo, render_error, secho

import os
import shutil
import uuid
from pathlib import Path

import typer

from core.config import (
    ConfigManager,
    FTPRemote,
    GoogleDriveRemote,
    GooglePhotosRemote,
    LocalRemote,
    OneDriveBusinessRemote,
    OneDriveRemote,
    PikPakRemote,
    RemoteConfig,
    SFTPRemote,
    SharePointRemote,
    WebDAVRemote,
)
from core.factory import get_storage_provider
from storage.base import DeleteCapability, managed_storage


def _render_add_remote_error(provider: str, name: str, exc: Exception) -> None:
    render_error(
        f"無法建立 {provider} Remote `{name}`。",
        cause=exc,
        next_steps=(
            "確認必要欄位、認證資訊與路徑格式後重試。",
            "也可使用 `drive-unix remote add` 的互動式 Wizard 建立 Remote。",
        ),
    )

def _password_reference(
    config_manager: ConfigManager,
    *,
    remote_name: str,
    prompt_text: str,
    env_name: str | None,
    kind: str = "password",
) -> str:
    if env_name:
        return config_manager.environment_secret_ref(env_name)
    value = typer.prompt(prompt_text, hide_input=True)
    return config_manager.store_remote_secret(remote_name, kind, value)


def _optional_secret_reference(
    config_manager: ConfigManager,
    *,
    remote_name: str,
    env_name: str | None,
    prompt_secret: bool,
    prompt_text: str,
    kind: str,
) -> str | None:
    if env_name:
        return config_manager.environment_secret_ref(env_name)
    if not prompt_secret:
        return None
    value = typer.prompt(prompt_text, hide_input=True)
    return config_manager.store_remote_secret(remote_name, kind, value)

def add_sp(
    name: str = typer.Argument(..., help="節點名稱 (例如: work_sp)"),
    base_url: str = typer.Argument(..., help="SharePoint 根網址 (例如: https://tenant.sharepoint.com)"),
    site: str = typer.Argument(..., help="站點路徑 (例如: /sites/my-project)"),
    email: str = typer.Argument(..., help="登入信箱"),
    password_env: str | None = typer.Option(None, "--password-env", help="從指定環境變數讀取密碼")
):
    """
    快速新增一個 SharePoint 遠端節點到設定檔
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    
    try:
        password_ref = _password_reference(
            config_manager, remote_name=name,
            prompt_text=f"請輸入 {email} 的密碼", env_name=password_env,
        )
        remote = SharePointRemote(
            type="sharepoint",
            base_url=base_url,
            site=site,
            email=email,
            password_ref=password_ref,
        )
        config_manager.add_remote(name, remote)
        secho(f"✅ 成功新增 SharePoint 節點 '{name}'！設定檔已更新。", fg=typer.colors.GREEN)
    except Exception as exc:
        _render_add_remote_error("SharePoint", name, exc)
        raise typer.Exit(code=1) from exc

def add_onedrive_business(
    name: str = typer.Argument(..., help="節點名稱 (例如: work_odb)"),
    base_url: str = typer.Argument(..., help="根網址 (例如: https://tenant-my.sharepoint.com)"),
    email: str = typer.Argument(..., help="登入信箱"),
    password_env: str | None = typer.Option(None, "--password-env", help="從指定環境變數讀取密碼"),
    site: str = typer.Option("", "--site", "-s", help="個人網站路徑，例如 /personal/xxx (預設留空自動解析)")
):
    """
    新增一個 OneDrive Business 遠端節點到設定檔
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    
    try:
        password_ref = _password_reference(
            config_manager, remote_name=name,
            prompt_text=f"請輸入 {email} 的密碼", env_name=password_env,
        )
        from core.config import OneDriveBusinessRemote
        new_config = OneDriveBusinessRemote(
            type="onedrive_business",
            base_url=base_url,
            email=email,
            password_ref=password_ref,
            site=site
        )
        config_manager.add_remote(name, new_config)
        secho(f"✅ 成功新增 OneDrive Business 節點 '{name}'！設定檔已更新。", fg=typer.colors.GREEN)
    except Exception as exc:
        _render_add_remote_error("OneDrive Business", name, exc)
        raise typer.Exit(code=1) from exc

def add_drive(
    name: str = typer.Argument(..., help="節點名稱 (例如: my_gdrive)"),
    cred_path: str = typer.Argument(..., help="Google Cloud OAuth credentials.json 的本機路徑")
):
    """
    新增一個 Google Drive 遠端節點到設定檔
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    
    if not os.path.exists(cred_path):
        render_error(
            "找不到 Google OAuth 憑證檔案。",
            cause=cred_path,
            next_steps=(
                "確認 credentials.json 路徑是否正確。",
                "請使用 Google Cloud OAuth Client 下載的 JSON 憑證檔。",
            ),
        )
        raise typer.Exit(code=1)
        
    try:
        secret_dir = str(config_manager.secret_files_dir)
        os.makedirs(secret_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(secret_dir, 0o700)
        except OSError:
            pass

        internal_cred_path = os.path.join(secret_dir, f"{name}_client_secret.json")
        shutil.copy2(cred_path, internal_cred_path)
        try:
            os.chmod(internal_cred_path, 0o600)
        except OSError:
            pass

        new_config = GoogleDriveRemote(
            type="google_drive",
            # Keep the managed credential path relative to config.toml so an
            # explicit --include-secrets export remains portable.
            credentials_json=Path(internal_cred_path).relative_to(config_manager.config_path.parent).as_posix(),
            root_folder_id="root"
        )
        config_manager.add_remote(name, new_config)
        
        secho(f"✅ 成功新增 Google Drive 節點 '{name}'！設定檔已更新。", fg=typer.colors.GREEN)
        secho(f"📂 憑證檔案已自動託管至: {internal_cred_path} (您現在可以安全地刪除原始檔案)", fg=typer.colors.CYAN)
        echo(f"💡 提示：第一次使用此節點 (例如執行 ls {name}:/) 時，將會自動彈出瀏覽器要求您登入 Google 帳號授權。")
        
    except Exception as exc:
        _render_add_remote_error("Google Drive", name, exc)
        raise typer.Exit(code=1) from exc

def add_photos(
    name: str = typer.Argument(..., help="節點名稱 (例如: my_photos)"),
    cred_path: str = typer.Argument(..., help="Google Cloud OAuth credentials.json 的本機路徑"),
    album: str | None = typer.Option(None, "--album", "-a", help="預設相簿名稱 (可選)"),
):
    """
    新增一個 Google Photos 遠端節點到設定檔
    """
    ctx = CLIContext.create()
    config_manager = ctx.config

    if not os.path.exists(cred_path):
        render_error(
            "找不到 Google OAuth 憑證檔案。",
            cause=cred_path,
            next_steps=(
                "確認 credentials.json 路徑是否正確。",
                "請使用 Google Cloud OAuth Client 下載的 JSON 憑證檔。",
            ),
        )
        raise typer.Exit(code=1)

    try:
        secret_dir = str(config_manager.secret_files_dir)
        os.makedirs(secret_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(secret_dir, 0o700)
        except OSError:
            pass

        internal_cred_path = os.path.join(secret_dir, f"googlephotos_{name}_client_secret.json")
        shutil.copy2(cred_path, internal_cred_path)
        try:
            os.chmod(internal_cred_path, 0o600)
        except OSError:
            pass

        new_config = GooglePhotosRemote(
            type="googlephotos",
            credentials_json=Path(internal_cred_path).relative_to(config_manager.config_path.parent).as_posix(),
            default_album=album,
        )
        config_manager.add_remote(name, new_config)

        secho(f"✅ 成功新增 Google Photos 節點 '{name}'！設定檔已更新。", fg=typer.colors.GREEN)
        secho(f"📂 憑證檔案已自動託管至: {internal_cred_path} (您現在可以安全地刪除原始檔案)", fg=typer.colors.CYAN)
        echo(f"💡 提示：第一次使用此節點 (例如執行 ls {name}:/) 時，將會自動彈出瀏覽器要求您登入 Google 帳號授權。")

    except Exception as exc:
        _render_add_remote_error("Google Photos", name, exc)
        raise typer.Exit(code=1) from exc

def add_local(
    name: str = typer.Argument(..., help="節點名稱 (例如: my_mac 或 my_nas)"),
    root_path: str = typer.Argument(..., help="作為根目錄的本機絕對路徑 (例如: /Users/henry/Downloads 或 D:\\Data)"),
    allow_missing: bool = typer.Option(False, "--allow-missing", help="允許儲存目前不存在的本機路徑"),
):
    """
    新增一個本機資料夾作為遠端節點 (讓本機資料夾也能與雲端進行統一的 sync/cp)
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    
    if not os.path.exists(root_path) and not allow_missing:
        secho(f"⚠️ 指定的本機路徑不存在: {root_path}", fg=typer.colors.YELLOW)
        if not typer.confirm("仍要將此路徑寫入設定嗎？"):
            raise typer.Abort()
        
    try:
        new_config = LocalRemote(
            type="local",
            root_path=os.path.abspath(root_path)
        )
        config_manager.add_remote(name, new_config)
        secho(f"✅ 成功新增本機節點 '{name}'！設定檔已更新。", fg=typer.colors.GREEN)
    except Exception as exc:
        _render_add_remote_error("Local", name, exc)
        raise typer.Exit(code=1) from exc

def add_ftp(
    name: str = typer.Argument(..., help="節點名稱 (例如: my_ftp)"),
    host: str = typer.Argument(..., help="FTP 伺服器 IP 或網址"),
    port: int = typer.Option(21, "--port", "-P", help="FTP 連接埠"),
    user: str = typer.Option("anonymous", "--user", "-u", help="FTP 帳號"),
    password_env: str | None = typer.Option(None, "--password-env", help="從指定環境變數讀取密碼"),
    tls: bool = typer.Option(False, "--tls", help="是否啟用 FTPS (TLS/SSL)"),
    passive: bool = typer.Option(True, "--passive/--active", help="使用被動或主動模式"),
    root_path: str = typer.Option("/", "--root", help="根目錄路徑")
):
    """
    新增一個 FTP/FTPS 遠端節點到設定檔
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    
    try:
        password_ref = None
        if password_env or user.lower() != "anonymous":
            password_ref = _password_reference(
                config_manager, remote_name=name,
                prompt_text=f"請輸入 {user} 的密碼", env_name=password_env,
            )

        from core.config import FTPRemote
        new_config = FTPRemote(
            type="ftp",
            host=host,
            port=port,
            username=user,
            password_ref=password_ref,
            tls=tls,
            passive=passive,
            root_path=root_path
        )
        config_manager.add_remote(name, new_config)
        secho(f"✅ 成功新增 FTP 節點 '{name}'！設定檔已更新。", fg=typer.colors.GREEN)
        
    except Exception as exc:
        _render_add_remote_error("FTP", name, exc)
        raise typer.Exit(code=1) from exc

def add_webdav(
    name: str = typer.Argument(..., help="節點名稱 (例如: my_nas)"),
    base_url: str = typer.Argument(..., help="WebDAV 伺服器網址 (例如: https://nas.local:5006)"),
    user: str = typer.Option(..., "--user", "-u", prompt="請輸入 WebDAV 帳號", help="WebDAV 帳號"),
    password_env: str | None = typer.Option(None, "--password-env", help="從指定環境變數讀取密碼")
):
    """
    新增一個 WebDAV 遠端節點到設定檔
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    try:
        password_ref = _password_reference(
            config_manager, remote_name=name,
            prompt_text=f"請輸入 {user} 的密碼", env_name=password_env,
        )
        from core.config import WebDAVRemote
        new_config = WebDAVRemote(
            type="webdav",
            base_url=base_url,
            username=user,
            password_ref=password_ref,
        )
        config_manager.add_remote(name, new_config)
        secho(f"✅ 成功新增 WebDAV 節點 '{name}'！設定檔已更新。", fg=typer.colors.GREEN)
    except Exception as exc:
        _render_add_remote_error("WebDAV", name, exc)
        raise typer.Exit(code=1) from exc

def add_onedrive(
    name: str = typer.Argument(..., help="節點名稱 (例如: my_onedrive)"),
    client_id: str = typer.Argument(..., help="Azure AD 應用程式的 Client ID"),
    secret_env: str | None = typer.Option(None, "--secret-env", help="從指定環境變數讀取 Client Secret"),
    secret_prompt: bool = typer.Option(False, "--secret-prompt", help="以隱藏輸入方式設定 Client Secret"),
    tenant: str = typer.Option("common", "--tenant", "-t", help="租戶 (預設 common 通吃個人與企業版)")
):
    """
    新增一個 Microsoft OneDrive 遠端節點到設定檔
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    
    try:
        if secret_env and secret_prompt:
            raise ValueError("--secret-env 與 --secret-prompt 不可同時使用。")
        client_secret_ref = _optional_secret_reference(
            config_manager, remote_name=name, env_name=secret_env,
            prompt_secret=secret_prompt, prompt_text="請輸入 Client Secret",
            kind="client-secret",
        )
        from core.config import OneDriveRemote
        new_config = OneDriveRemote(
            type="onedrive",
            client_id=client_id,
            client_secret_ref=client_secret_ref,
            tenant=tenant
        )
        config_manager.add_remote(name, new_config)
        
        secho(f"✅ 成功新增 OneDrive 節點 '{name}'！設定檔已更新。", fg=typer.colors.GREEN)
        echo(f"💡 提示：在 Azure AD (Microsoft Entra ID) 註冊應用程式時，「驗證」平台務必選擇「Web (網頁)」或「行動與傳統型應用程式」（切勿選「單頁應用程式 (SPA)」），重新導向 URI 設定為: http://localhost:8080")
        echo(f"💡 第一次使用此節點 (例如執行 ls {name}:/) 時，將會自動彈出瀏覽器要求您登入微軟帳號授權。")
        
    except Exception as exc:
        _render_add_remote_error("OneDrive", name, exc)
        raise typer.Exit(code=1) from exc

def add_pikpak(
    name: str = typer.Argument(..., help="節點名稱 (例如: mypik)"),
    username: str = typer.Argument(..., help="PikPak 帳號/信箱"),
    password_env: str | None = typer.Option(None, "--password-env", help="從指定環境變數讀取密碼"),
    password: str | None = typer.Option(None, "--password", hidden=True, help="明文密碼 (禁止使用)"),
) -> None:
    """新增一個 PikPak 遠端節點到設定檔。"""
    if password is not None:
        render_error(
            "安全規範限制：禁止使用 --password 參數傳入明文密碼。",
            cause=ValueError("Plaintext password flag is prohibited."),
            next_steps=(
                "請改用 `--password-env ENV_VAR` 參照環境變數中的密碼。",
                "或不帶密碼參數，直接在互動提示中安全輸入密碼並儲存至 Secret Store。",
            ),
        )
        raise typer.Exit(code=1)

    ctx = CLIContext.create()
    config_manager = ctx.config

    try:
        password_ref = _password_reference(
            config_manager,
            remote_name=name,
            prompt_text=f"請輸入 {username} 的密碼",
            env_name=password_env,
        )
        remote = PikPakRemote(
            type="pikpak",
            username=username,
            password_ref=password_ref,
            root_folder_id="",
        )
        config_manager.add_remote(name, remote)
        secho(f"✅ 成功新增 PikPak 節點 '{name}'！設定檔已更新。", fg=typer.colors.GREEN)
    except Exception as exc:
        _render_add_remote_error("PikPak", name, exc)
        raise typer.Exit(code=1) from exc

def list_nodes(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="顯示設定檔路徑等診斷資訊")
):
    """
    列出所有已設定的遠端節點
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    if verbose:
        secho(f"🔍 實際讀取的設定檔路徑: {config_manager.config_path}", fg=typer.colors.YELLOW)
    remotes = config_manager.config.remotes
    
    if not remotes:
        secho("⚠️ 目前沒有設定任何 Remote。可執行 `drive-unix remote add` 開始設定。", fg=typer.colors.YELLOW)
        return
        
    secho(f"📋 目前共設定了 {len(remotes)} 個遠端節點：\n", fg=typer.colors.CYAN, bold=True)
    
    for name, remote in remotes.items():
        is_default = "⭐ (預設)" if name == config_manager.config.default_remote else ""
        
        secho(f"📦 節點名稱: {name} {is_default}", fg=typer.colors.GREEN, bold=True)
        echo(f"   ├─ 類型: {remote.type}")
        
        if remote.type == "sharepoint":
            echo(f"   ├─ 網址: {remote.base_url}")
            echo(f"   ├─ 站點: {getattr(remote, 'site', '無')}")
            echo(f"   └─ 信箱: {remote.email}")
        elif remote.type == "onedrive_business":
            echo(f"   ├─ 網址: {remote.base_url}")
            echo(f"   ├─ 站點: {remote.site or '(自動解析)'}")
            echo(f"   └─ 信箱: {remote.email}")
        elif remote.type == "google_drive":
            echo(f"   ├─ 憑證: {remote.credentials_json}")
            echo(f"   └─ 根目錄: {remote.root_folder_id}")
        elif remote.type == "onedrive":
            echo(f"   ├─ 用戶端 ID: {remote.client_id}")
            secret_display = "已設定" if remote.client_secret_ref else "未設定"
            echo(f"   ├─ 金鑰狀態: {secret_display}")
            echo(f"   └─ 租戶: {remote.tenant}")
        elif remote.type == "local":
            echo(f"   └─ 根目錄: {remote.root_path}")
        elif remote.type == "ftp":
            echo(f"   ├─ 伺服器: {remote.host}:{remote.port}")
            echo(f"   ├─ 帳號: {remote.username}")
            tls_str = "啟用" if remote.tls else "停用"
            echo(f"   ├─ FTPS (TLS): {tls_str}")
            echo(f"   └─ 根目錄: {remote.root_path}")
        elif remote.type == "webdav":
            echo(f"   ├─ 網址: {remote.base_url}")
            echo(f"   └─ 帳號: {remote.username}")
        elif remote.type == "sftp":
            echo(f"   ├─ 伺服器: {remote.host}:{remote.port}")
            echo(f"   ├─ 帳號: {remote.username}")
            if remote.key_filename:
                echo(f"   ├─ 金鑰: {remote.key_filename}")
            if remote.known_hosts:
                echo(f"   ├─ Known Hosts: {remote.known_hosts}")
            echo(f"   └─ 根目錄: {remote.root_path}")
        else:
            echo(f"   └─ 未知類型的設定")
            
        echo("")

def remove_node(
    name: str = typer.Argument(..., help="要移除的節點名稱")
):
    """
    從設定檔中移除指定的遠端節點
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    try:
        config_manager.remove_remote(name)
        secho(f"✅ 成功移除節點 '{name}'。", fg=typer.colors.GREEN)
    except Exception as exc:
        render_error(
            f"無法移除 Remote `{name}`。",
            cause=exc,
            next_steps=("執行 `drive-unix remote list` 確認 Remote 名稱。",),
        )
        raise typer.Exit(code=1) from exc

def rename_node(
    old_name: str = typer.Argument(..., help="目前的節點名稱"),
    new_name: str = typer.Argument(..., help="新的節點名稱")
):
    """
    重新命名現有的遠端節點
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    try:
        config_manager.rename_remote(old_name, new_name)
        secho(f"✅ 成功將節點 '{old_name}' 重新命名為 '{new_name}'！", fg=typer.colors.GREEN)
    except Exception as exc:
        render_error(
            f"無法將 Remote `{old_name}` 重新命名為 `{new_name}`。",
            cause=exc,
            next_steps=(
                "確認舊名稱存在，且新名稱尚未被使用。",
                "執行 `drive-unix remote list` 查看現有名稱。",
            ),
        )
        raise typer.Exit(code=1) from exc

def edit_node(
    name: str = typer.Argument(..., help="要編輯的節點名稱"),
    base_url: str = typer.Option(None, "--base-url", "-b", help="新的根網址"),
    site: str = typer.Option(None, "--site", "-s", help="新的站點路徑"),
    email: str = typer.Option(None, "--email", "-e", help="新的登入信箱"),
    password_env: str | None = typer.Option(None, "--password-env", help="將密碼綁定到指定環境變數"),
    password_prompt: bool = typer.Option(False, "--password-prompt", help="以隱藏輸入方式更新密碼"),
    clear_password: bool = typer.Option(False, "--clear-password", help="移除目前的密碼 reference"),
):
    """
    編輯現有遠端節點的設定（僅需提供要修改的參數）
    """
    ctx = CLIContext.create()
    config_manager = ctx.config
    try:
        remote = config_manager.get_remote(name)
        secret_modes = sum(bool(value) for value in (password_env, password_prompt, clear_password))
        if secret_modes > 1:
            raise ValueError("--password-env、--password-prompt、--clear-password 只能擇一。")

        password_ref = None
        update_password_ref = False
        old_password_ref = getattr(remote, "password_ref", None)
        if password_env:
            password_ref = config_manager.environment_secret_ref(password_env)
            update_password_ref = True
        elif password_prompt:
            account = getattr(remote, "email", None) or getattr(remote, "username", name)
            password_ref = config_manager.store_remote_secret(
                name, "password", typer.prompt(f"請輸入 {account} 的新密碼", hide_input=True)
            )
            update_password_ref = True
        elif clear_password:
            update_password_ref = True

        updates = {
            "base_url": base_url,
            "site": site,
            "email": email,
        }
        config_manager.edit_remote(name, **updates)
        if update_password_ref:
            setattr(remote, "password_ref", password_ref)
            config_manager.save()
            if old_password_ref and old_password_ref != password_ref:
                config_manager.secret_store.delete(old_password_ref)
        secho(f"✅ 成功更新節點 '{name}' 的設定！", fg=typer.colors.GREEN)
        
    except ValueError as exc:
        render_error(
            f"Remote `{name}` 的更新參數無效。",
            cause=exc,
            next_steps=("執行 `drive-unix remote edit --help` 查看可修改欄位。",),
        )
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        render_error(
            f"無法更新 Remote `{name}`。",
            cause=exc,
            next_steps=(
                "確認設定檔可寫入，且新的認證資料有效。",
                "更新後可執行 `drive-unix remote test NAME` 驗證。",
            ),
        )
        raise typer.Exit(code=1) from exc


_REMOTE_PROVIDER_ALIASES = {
    "local": "local",
    "ftp": "ftp",
    "sftp": "sftp",
    "webdav": "webdav",
    "sharepoint": "sharepoint",
    "sp": "sharepoint",
    "onedrive-business": "onedrive_business",
    "onedrive_business": "onedrive_business",
    "odb": "onedrive_business",
    "google-drive": "google_drive",
    "google_drive": "google_drive",
    "gdrive": "google_drive",
    "google-photos": "googlephotos",
    "googlephotos": "googlephotos",
    "photos": "googlephotos",
    "gphotos": "googlephotos",
    "onedrive": "onedrive",
    "pikpak": "pikpak",
}


def _prompt_remote_provider(provider: str | None) -> str:
    if provider:
        key = provider.strip().lower()
    else:
        echo("可用 Provider: local, google-drive, google-photos, onedrive, onedrive-business, sharepoint, sftp, ftp, webdav, pikpak")
        key = typer.prompt("Provider").strip().lower()
    try:
        return _REMOTE_PROVIDER_ALIASES[key]
    except KeyError as exc:
        raise ValueError(f"不支援的 Provider: {provider or key}") from exc


def _managed_google_credentials(config_manager: ConfigManager, name: str, cred_path: str) -> str:
    source = Path(cred_path).expanduser()
    if not source.exists():
        raise ValueError(f"找不到指定的憑證檔案: {source}")
    secret_dir = config_manager.secret_files_dir
    secret_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    internal = secret_dir / f"{name}_client_secret.json"
    shutil.copy2(source, internal)
    try:
        os.chmod(internal, 0o600)
    except OSError:
        pass
    return internal.relative_to(config_manager.config_path.parent).as_posix()


def _managed_google_photos_credentials(config_manager: ConfigManager, name: str, cred_path: str) -> str:
    source = Path(cred_path).expanduser()
    if not source.exists():
        raise ValueError(f"找不到指定的憑證檔案: {source}")
    secret_dir = config_manager.secret_files_dir
    secret_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    internal = secret_dir / f"googlephotos_{name}_client_secret.json"
    shutil.copy2(source, internal)
    try:
        os.chmod(internal, 0o600)
    except OSError:
        pass
    return internal.relative_to(config_manager.config_path.parent).as_posix()


def _interactive_add_remote(provider: str | None, name: str | None) -> str:
    """Interactive task-oriented Remote creation used by ``remote add`` and ``init``."""

    config_manager = CLIContext.create().config
    provider_type = _prompt_remote_provider(provider)
    remote_name = (name or typer.prompt("Remote 名稱")).strip()
    if not remote_name:
        raise ValueError("Remote 名稱不可為空。")

    remote: RemoteConfig
    if provider_type == "local":
        root_path = typer.prompt("本機根目錄")
        if not os.path.exists(root_path):
            secho(f"⚠️ 路徑目前不存在: {root_path}", fg=typer.colors.YELLOW)
            if not typer.confirm("仍要儲存此 Remote 嗎？"):
                raise typer.Abort()
        remote = LocalRemote(type="local", root_path=os.path.abspath(root_path))

    elif provider_type == "google_drive":
        cred_path = typer.prompt("Google OAuth credentials.json 路徑")
        remote = GoogleDriveRemote(
            type="google_drive",
            credentials_json=_managed_google_credentials(config_manager, remote_name, cred_path),
            root_folder_id="root",
        )

    elif provider_type == "googlephotos":
        cred_path = typer.prompt("Google OAuth credentials.json 路徑")
        album = typer.prompt("預設相簿名稱 (可留空)", default="", show_default=False) or None
        remote = GooglePhotosRemote(
            type="googlephotos",
            credentials_json=_managed_google_photos_credentials(config_manager, remote_name, cred_path),
            default_album=album,
        )

    elif provider_type == "sharepoint":
        base_url = typer.prompt("SharePoint 根網址")
        site = typer.prompt("站點路徑（例如 /sites/project）")
        email = typer.prompt("登入信箱")
        password_ref = _password_reference(
            config_manager,
            remote_name=remote_name,
            prompt_text=f"請輸入 {email} 的密碼",
            env_name=None,
        )
        remote = SharePointRemote(
            type="sharepoint",
            base_url=base_url,
            site=site,
            email=email,
            password_ref=password_ref,
        )

    elif provider_type == "onedrive_business":
        base_url = typer.prompt("OneDrive Business 根網址")
        email = typer.prompt("登入信箱")
        site = typer.prompt("個人網站路徑（可留空自動解析）", default="", show_default=False)
        password_ref = _password_reference(
            config_manager,
            remote_name=remote_name,
            prompt_text=f"請輸入 {email} 的密碼",
            env_name=None,
        )
        remote = OneDriveBusinessRemote(
            type="onedrive_business",
            base_url=base_url,
            email=email,
            site=site,
            password_ref=password_ref,
        )

    elif provider_type == "onedrive":
        echo("💡 提示：在 Azure AD (Microsoft Entra ID) 註冊應用程式時，「驗證」平台請選擇「Web (網頁)」（勿選 SPA），重新導向 URI 設定為: http://localhost:8080")
        client_id = typer.prompt("Microsoft Entra Client ID")
        tenant = typer.prompt("Tenant", default="common")
        client_secret_ref = None
        if typer.confirm("需要設定 Client Secret 嗎？", default=False):
            client_secret_ref = config_manager.store_remote_secret(
                remote_name,
                "client-secret",
                typer.prompt("Client Secret", hide_input=True),
            )
        remote = OneDriveRemote(
            type="onedrive",
            client_id=client_id,
            client_secret_ref=client_secret_ref,
            tenant=tenant,
        )

    elif provider_type == "ftp":
        host = typer.prompt("FTP Host")
        port = typer.prompt("Port", default=21, type=int)
        username = typer.prompt("帳號", default="anonymous")
        password_ref = None
        if username.lower() != "anonymous":
            password_ref = _password_reference(
                config_manager,
                remote_name=remote_name,
                prompt_text=f"請輸入 {username} 的密碼",
                env_name=None,
            )
        remote = FTPRemote(
            type="ftp",
            host=host,
            port=port,
            username=username,
            password_ref=password_ref,
            tls=typer.confirm("啟用 FTPS (TLS)？", default=False),
            passive=True,
            root_path=typer.prompt("根目錄", default="/"),
        )

    elif provider_type == "sftp":
        host = typer.prompt("SFTP Host")
        port = typer.prompt("Port", default=22, type=int)
        username = typer.prompt("帳號")
        key_filename = typer.prompt("SSH 私鑰路徑（可留空）", default="", show_default=False) or None
        password_ref = None
        if not key_filename and typer.confirm("使用密碼驗證？", default=True):
            password_ref = _password_reference(
                config_manager,
                remote_name=remote_name,
                prompt_text=f"請輸入 {username} 的密碼",
                env_name=None,
            )
        remote = SFTPRemote(
            type="sftp",
            host=host,
            port=port,
            username=username,
            password_ref=password_ref,
            key_filename=key_filename,
            root_path=typer.prompt("根目錄", default="/"),
        )

    elif provider_type == "webdav":
        base_url = typer.prompt("WebDAV URL")
        username = typer.prompt("帳號")
        password_ref = _password_reference(
            config_manager,
            remote_name=remote_name,
            prompt_text=f"請輸入 {username} 的密碼",
            env_name=None,
        )
        remote = WebDAVRemote(
            type="webdav",
            base_url=base_url,
            username=username,
            password_ref=password_ref,
        )

    elif provider_type == "pikpak":
        username = typer.prompt("帳號/信箱")
        password_ref = _password_reference(
            config_manager,
            remote_name=remote_name,
            prompt_text=f"請輸入 {username} 的密碼",
            env_name=None,
        )
        remote = PikPakRemote(
            type="pikpak",
            username=username,
            password_ref=password_ref,
            root_folder_id="",
        )
    else:  # pragma: no cover - guarded by alias map
        raise ValueError(f"不支援的 Provider: {provider_type}")

    config_manager.add_remote(remote_name, remote)
    if config_manager.config.default_remote is None:
        config_manager.config.default_remote = remote_name
        config_manager.save()
    secho(f"✅ Remote `{remote_name}` 已建立。", fg=typer.colors.GREEN, bold=True)
    echo(f"下一步可執行: drive-unix remote test {remote_name}")
    return remote_name


def remote_add(
    provider_or_name: str | None = typer.Argument(None, help="Provider 類型或 Remote 名稱；省略時進入互動選擇"),
    name: str | None = typer.Option(None, "--name", "-n", help="Remote 名稱"),
    remote_type: str | None = typer.Option(None, "--type", "-t", help="Provider 類型 (例如 googlephotos, local)"),
) -> None:
    """以互動式 Wizard 新增 Remote。"""

    try:
        if remote_type:
            target_provider = remote_type
            target_name = provider_or_name or name
        elif provider_or_name and provider_or_name.strip().lower() in _REMOTE_PROVIDER_ALIASES:
            target_provider = provider_or_name
            target_name = name
        else:
            target_provider = None
            target_name = provider_or_name or name
        _interactive_add_remote(target_provider, target_name)
    except typer.Abort:
        secho("🛑 已取消 Remote 設定。", fg=typer.colors.YELLOW)
    except Exception as exc:
        render_error(
            "Remote Wizard 無法完成設定。",
            cause=exc,
            next_steps=(
                "檢查輸入內容後重試。",
                "執行 `drive-unix remote add --help` 查看 Provider 與名稱參數。",
            ),
        )
        raise typer.Exit(code=1) from exc


def remote_test(
    name: str = typer.Argument(..., help="要測試的 Remote 名稱"),
    write: bool = typer.Option(False, "--write", help="額外建立並刪除暫存資料夾以驗證寫入權限"),
) -> None:
    """測試 Remote 的連線、讀取，以及選擇性的寫入能力。"""

    config_manager = CLIContext.create().config
    try:
        with managed_storage(get_storage_provider(name, config_manager)) as storage:
            echo(f"[1/2] 測試 [{name}] 認證與讀取...")
            storage.list_dir("/")
            secho("✅ 認證與讀取成功", fg=typer.colors.GREEN)

            if not write:
                echo("[2/2] 寫入測試：未執行（加上 --write 可驗證）")
                return

            test_path = f"/.drive-unix-write-test-{uuid.uuid4().hex[:8]}"
            echo(f"[2/2] 測試寫入與清理: {test_path}")
            if not storage.mkdir(test_path, parents=False):
                raise RuntimeError("Provider 回報無法建立測試資料夾。")
            if not storage.delete(test_path, permanent=False):
                raise RuntimeError("測試資料夾建立成功，但清理失敗。")
            cleanup = (
                "永久刪除"
                if storage.delete_capability == DeleteCapability.PERMANENT_ONLY
                else "移至回收桶"
            )
            secho(f"✅ 寫入成功；測試資料夾已{cleanup}", fg=typer.colors.GREEN)
    except Exception as exc:
        render_error(
            f"Remote `{name}` 測試失敗。",
            cause=exc,
            next_steps=(
                "確認網路、認證與根目錄讀取權限。",
                "必要時執行 `drive-unix remote edit NAME ...` 修正設定。",
                "若失敗發生在 `--write`，請確認建立與刪除權限。",
            ),
        )
        raise typer.Exit(code=1) from exc


def init_setup() -> None:
    """首次使用導引：建立 Remote、驗證連線並提供下一步。"""

    config_manager = CLIContext.create().config
    secho("drive-unix 初始設定", fg=typer.colors.CYAN, bold=True)
    if config_manager.config.remotes:
        echo("已偵測到 Remote 設定：")
        list_nodes(verbose=False)
        echo("可使用 `drive-unix remote add` 新增，或 `drive-unix remote test NAME` 驗證連線。")
        return

    try:
        name = _interactive_add_remote(None, None)
    except typer.Abort:
        secho("🛑 已取消初始設定。", fg=typer.colors.YELLOW)
        return
    echo("")
    echo(f"設定完成。建議先驗證連線: drive-unix remote test {name}")
    echo(f"第一個瀏覽指令: drive-unix ls {name}:/")

def register(app: typer.Typer) -> None:
    """Register backwards-compatible root aliases (hidden from root help)."""
    app.command("add-sp", hidden=True)(add_sp)
    app.command("add-odb", hidden=True)(add_onedrive_business)
    app.command("add-gdrive", hidden=True)(add_drive)
    app.command("add-photos", hidden=True)(add_photos)
    app.command("add-local", hidden=True)(add_local)
    app.command("add-ftp", hidden=True)(add_ftp)
    app.command("add-webdav", hidden=True)(add_webdav)
    app.command("add-onedrive", hidden=True)(add_onedrive)
    app.command("add-pikpak", hidden=True)(add_pikpak)
    app.command("list-nodes", hidden=True)(list_nodes)
    app.command("remove-node", hidden=True)(remove_node)
    app.command("rename-node", hidden=True)(rename_node)
    app.command("edit-node", hidden=True)(edit_node)
    app.command("init")(init_setup)


def register_remote(app: typer.Typer) -> None:
    app.command("add")(remote_add)
    app.command("list")(list_nodes)
    app.command("remove")(remove_node)
    app.command("rename")(rename_node)
    app.command("edit")(edit_node)
    app.command("test")(remote_test)
