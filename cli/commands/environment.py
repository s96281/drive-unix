"""Environment export/import CLI commands."""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import typer

from cli.presentation import echo, render_error, secho

from auth.cache import DEFAULT_CACHE_DIR
from core.config import DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_PATH, ConfigManager

def export_environment(
    output_path: str = typer.Argument(..., help="匯出的 zip 檔案路徑 (例如: backup.zip)"),
    include_auth_cache: bool = typer.Option(
        False,
        "--include-auth-cache",
        help="同時匯出 OAuth/Cookie 登入快取（包含敏感認證資料）",
    ),
    include_secrets: bool = typer.Option(
        False,
        "--include-secrets",
        help="同時匯出 secret store / OAuth client credential files（高度敏感）",
    ),
):
    """
    匯出目前設定。登入快取預設不匯出，避免 refresh token / cookie 被打包。
    """
    config_dir = Path(DEFAULT_CONFIG_DIR)
    cache_dir = Path(DEFAULT_CACHE_DIR)
    
    try:
        # Loading the config performs the one-time migration of pre-Phase-4
        # inline passwords/client secrets before any archive is produced.
        if Path(DEFAULT_CONFIG_PATH).exists():
            ConfigManager(Path(DEFAULT_CONFIG_PATH))
        output = Path(output_path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        # Archives are private even without secrets because remote topology and
        # account identifiers can still be sensitive.
        fd, temp_output = tempfile.mkstemp(
            prefix=f".{output.name}.",
            suffix=".tmp",
            dir=str(output.parent),
        )
        os.close(fd)
        try:
            try:
                os.chmod(temp_output, 0o600)
            except OSError:
                pass

            with zipfile.ZipFile(temp_output, 'w', zipfile.ZIP_DEFLATED) as zipf:
                if config_dir.exists():
                    sensitive_roots = {"secret-files", "secrets"}
                    sensitive_files = {"secrets.json"}
                    for root_dir, dirs, files in os.walk(config_dir):
                        relative_root = Path(root_dir).relative_to(config_dir)
                        if not include_secrets:
                            dirs[:] = [
                                name for name in dirs
                                if not (relative_root == Path(".") and name in sensitive_roots)
                            ]
                        for file in files:
                            file_path = Path(root_dir) / file
                            relative = file_path.relative_to(config_dir)
                            if not include_secrets and (
                                relative.name in sensitive_files
                                or (relative.parts and relative.parts[0] in sensitive_roots)
                            ):
                                continue
                            arcname = f"config/{relative}"
                            zipf.write(file_path, arcname)

                if include_auth_cache and cache_dir.exists():
                    for root_dir, dirs, files in os.walk(cache_dir):
                        for file in files:
                            file_path = Path(root_dir) / file
                            arcname = f"auth_cache/{file_path.relative_to(cache_dir)}"
                            zipf.write(file_path, arcname)

            os.replace(temp_output, output)
            try:
                os.chmod(output, 0o600)
            except OSError:
                pass
        finally:
            try:
                os.unlink(temp_output)
            except FileNotFoundError:
                pass

        exported_parts = ["設定"]
        if include_secrets:
            exported_parts.append("Secrets")
        if include_auth_cache:
            exported_parts.append("登入快取")
        secho(
            f"✅ 成功匯出{'、'.join(exported_parts)}至: {output}",
            fg=typer.colors.GREEN,
        )
    except Exception as exc:
        render_error(
            "環境匯出失敗。",
            cause=exc,
            next_steps=(
                "確認輸出目錄可寫入，且磁碟空間足夠。",
                "若使用 `--include-secrets` 或 `--include-auth-cache`，請妥善保管產生的壓縮檔。",
            ),
        )
        raise typer.Exit(code=1) from exc

def _safe_extract_environment_zip(zipf: zipfile.ZipFile, destination: Path) -> None:
    """Safely extract environment archives without Zip Slip or symlink escape."""
    destination = destination.resolve()
    allowed_roots = {"config", "auth_cache"}

    for info in zipf.infolist():
        raw_name = info.filename.replace("\\", "/")
        path = Path(*Path(raw_name).parts)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"封存檔包含不安全路徑: {info.filename}")
        if not path.parts or path.parts[0] not in allowed_roots:
            raise ValueError(f"封存檔包含未允許的頂層項目: {info.filename}")

        unix_mode = (info.external_attr >> 16) & 0o170000
        if unix_mode == 0o120000:
            raise ValueError(f"封存檔不可包含符號連結: {info.filename}")

        target = (destination / path).resolve(strict=False)
        try:
            target.relative_to(destination)
        except ValueError as exc:
            raise ValueError(f"封存檔包含越界路徑: {info.filename}") from exc

        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(target, 0o700)
            except OSError:
                pass
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        with zipf.open(info, "r") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass

    config_root = destination / "config"
    cache_root = destination / "auth_cache"
    for directory in (config_root, cache_root):
        if directory.exists():
            for current, dirs, files in os.walk(directory):
                try:
                    os.chmod(current, 0o700)
                except OSError:
                    pass
                for name in files:
                    try:
                        os.chmod(Path(current) / name, 0o600)
                    except OSError:
                        pass

def import_environment(
    input_path: str = typer.Argument(..., help="要匯入的 zip 檔案路徑 (例如: backup.zip)"),
    force: bool = typer.Option(False, "--force", "-f", help="強制覆蓋現有設定檔與快取")
):
    """
    從 Zip 壓縮檔匯入設定檔與登入快取
    """
    if not os.path.exists(input_path):
        render_error(
            "找不到要匯入的環境壓縮檔。",
            cause=input_path,
            next_steps=("確認檔案路徑與副檔名後重試。",),
        )
        raise typer.Exit(code=1)
        
    config_dir = Path(DEFAULT_CONFIG_DIR)
    cache_dir = Path(DEFAULT_CACHE_DIR)
    
    if (config_dir.exists() or cache_dir.exists()) and not force:
        secho("⚠️ 警告：這將會覆蓋您現有的設定檔與登入快取。", fg=typer.colors.YELLOW)
        if not typer.confirm("確定要繼續嗎？"):
            raise typer.Abort()
            
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(input_path, 'r') as zipf:
                _safe_extract_environment_zip(zipf, Path(temp_dir))
                
            temp_config = Path(temp_dir) / "config"
            temp_cache = Path(temp_dir) / "auth_cache"
            
            if temp_config.exists():
                shutil.copytree(temp_config, config_dir, dirs_exist_ok=True)
                echo("✅ 設定檔匯入完成")
                
            if temp_cache.exists():
                shutil.copytree(temp_cache, cache_dir, dirs_exist_ok=True)
                echo("✅ 快取匯入完成")
                
        secho("🎉 匯入流程順利結束！", fg=typer.colors.GREEN)
        
    except typer.Abort:
        secho("🛑 已取消匯入操作。", fg=typer.colors.YELLOW)
    except Exception as exc:
        render_error(
            "環境匯入失敗。",
            cause=exc,
            next_steps=(
                "確認壓縮檔是由 `drive-unix env export` 產生且未損毀。",
                "若現有設定阻擋覆蓋，可確認內容後使用 `--force`。",
            ),
        )
        raise typer.Exit(code=1) from exc

def register(app: typer.Typer) -> None:
    app.command("export-env", hidden=True)(export_environment)
    app.command("import-env", hidden=True)(import_environment)


def register_environment(app: typer.Typer) -> None:
    app.command("export")(export_environment)
    app.command("import")(import_environment)
