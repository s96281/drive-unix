#!/usr/bin/env python3
"""drive-unix 統一安裝與初始化導引核心腳本 (Unified Setup Orchestrator).

整合個人電腦 (PC / Desktop) 與雲端伺服器 (VPS / Headless) 之從頭架設、
依賴與 Playwright 檢查、Upstash 端對端加密 (E2EE) 跨端同步設定、
Systemd 服務註冊與 Web 控制台啟動。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ==============================================================================
# 0. 終端色彩與格式化輸出 (Terminal Colors & Formatting)
# ==============================================================================
NO_COLOR = os.environ.get("NO_COLOR", "0") == "1" or not sys.stdout.isatty()

if not NO_COLOR and platform.system() == "Windows":
    try:
        # Enable ANSI escape sequences on Windows console
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


def _c(text: str, color_code: str) -> str:
    return text if NO_COLOR else f"\033[{color_code}m{text}\033[0m"


def red(text: str) -> str:
    return _c(text, "1;31")


def green(text: str) -> str:
    return _c(text, "1;32")


def yellow(text: str) -> str:
    return _c(text, "1;33")


def blue(text: str) -> str:
    return _c(text, "1;34")


def cyan(text: str) -> str:
    return _c(text, "1;36")


def bold(text: str) -> str:
    return _c(text, "1")


def dim(text: str) -> str:
    return _c(text, "2")


def log_step(step: str, title: str) -> None:
    print(f"\n{cyan(f'[{step}]')} {bold(title)}")


def log_info(msg: str) -> None:
    print(f" {blue('ℹ')} {msg}")


def log_success(msg: str) -> None:
    print(f" {green('✔')} {msg}")


def log_warn(msg: str) -> None:
    print(f" {yellow('⚠')} {msg}")


def log_error(msg: str) -> None:
    print(f" {red('✖')} {msg}")


def print_banner() -> None:
    border = "=" * 70
    print(cyan(border))
    print(cyan(bold("    drive-unix 全方位一鍵初始化與架設精靈 (Unified Setup Wizard)")))
    print(cyan(border))
    print(f" 系統平台: {green(platform.system())} ({platform.machine()})")
    print(f" Python:   {green(platform.python_version())} ({sys.executable})")
    print(f" 工作目錄: {green(str(Path.cwd()))}")
    print(cyan(border))


# ==============================================================================
# 1. 輔助函式 (Helper Utilities)
# ==============================================================================
SCRIPT_DIR = Path(__file__).resolve().parent.parent


def get_actual_user_and_home() -> tuple[str, Path]:
    """Resolve the real non-root user and home directory even under sudo."""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        user = sudo_user
        try:
            import pwd
            home = Path(pwd.getpwnam(user).pw_dir)
        except Exception:
            home = Path(f"/home/{user}")
        return user, home

    user = getpass.getuser()
    home = Path.home()
    return user, home


def is_running_as_root() -> bool:
    if hasattr(os, "geteuid"):
        return os.geteuid() == 0
    return False


def run_command(
    cmd: list[str] | str,
    *,
    shell: bool = False,
    check: bool = True,
    capture_output: bool = False,
    as_user: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute subprocess command safely with optional sudo/user switching."""
    if isinstance(cmd, str) and not shell:
        cmd = cmd.split()

    if as_user and is_running_as_root() and as_user != "root":
        if isinstance(cmd, list):
            cmd = ["sudo", "-u", as_user] + cmd
        else:
            cmd = f"sudo -u {as_user} {cmd}"

    try:
        return subprocess.run(
            cmd,
            shell=shell,
            check=check,
            capture_output=capture_output,
            text=True,
        )
    except subprocess.CalledProcessError as err:
        if not capture_output:
            log_error(f"指令執行失敗 (結束碼 {err.returncode}): {cmd}")
        raise


def prompt_input(
    prompt_text: str,
    default: str | None = None,
    hide_input: bool = False,
    required: bool = False,
) -> str:
    """Prompt user for input with default value and optional masking."""
    display_prompt = f" {bold('?')} {prompt_text}"
    if default:
        display_prompt += f" {dim(f'[{default}]')}: "
    else:
        display_prompt += ": "

    while True:
        try:
            if hide_input:
                val = getpass.getpass(display_prompt)
            else:
                val = input(display_prompt)
        except (KeyboardInterrupt, EOFError):
            print("\n")
            log_warn("已取消安裝。")
            sys.exit(130)

        val = val.strip()
        if not val and default is not None:
            return default
        if not val and required:
            print(f"   {yellow('此欄位不可為空，請重新輸入。')}")
            continue
        return val


def prompt_confirm(prompt_text: str, default: bool = True) -> bool:
    """Prompt user for a boolean Yes/No confirmation."""
    opts = "[Y/n]" if default else "[y/N]"
    display_prompt = f" {bold('?')} {prompt_text} {dim(opts)}: "
    while True:
        try:
            val = input(display_prompt).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            log_warn("已取消安裝。")
            sys.exit(130)

        if not val:
            return default
        if val in ("y", "yes", "true", "1"):
            return True
        if val in ("n", "no", "false", "0"):
            return False
        print(f"   {yellow('請輸入 y 或 n。')}")


# ==============================================================================
# 2. 環境變數檔 (.env) 管理
# ==============================================================================
def update_or_create_env_file(
    env_path: Path,
    updates: dict[str, str],
    example_path: Path | None = None,
) -> None:
    """Safely update or create .env file preserving existing keys and comments."""
    existing_lines: list[str] = []
    if env_path.exists():
        try:
            existing_lines = env_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            existing_lines = []
    elif example_path and example_path.exists():
        try:
            existing_lines = example_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            existing_lines = []

    written_keys: set[str] = set()
    new_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _ = stripped.split("=", 1)
            key = key.strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                written_keys.add(key)
                continue
        new_lines.append(line)

    for k, v in updates.items():
        if k not in written_keys:
            new_lines.append(f"{k}={v}")

    content = "\n".join(new_lines) + "\n"
    env_path.write_text(content, encoding="utf-8")

    # Set restrictive permission (0600) on POSIX
    if hasattr(os, "chmod") and platform.system() != "Windows":
        try:
            os.chmod(env_path, 0o600)
        except Exception:
            pass


# ==============================================================================
# 3. 核心安裝與初始化流程 (Setup Orchestrator)
# ==============================================================================
class SetupOrchestrator:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.is_win = platform.system() == "Windows"
        self.is_linux = platform.system() == "Linux"
        self.is_mac = platform.system() == "Darwin"
        self.root_dir = SCRIPT_DIR
        self.actual_user, self.actual_home = get_actual_user_and_home()

        # Paths
        if self.is_win:
            self.config_dir = Path(os.environ.get("USERPROFILE", str(self.actual_home))) / ".config" / "drive-unix"
        else:
            self.config_dir = self.actual_home / ".config" / "drive-unix"

        self.env_file = self.root_dir / ".env"
        self.env_example = self.root_dir / ".env.production.example"
        self.role: str = ""
        self.host: str = ""
        self.port: int = 8000

    def run(self) -> None:
        print_banner()

        # Stage 1: Role Selection
        self.stage_select_role()

        # Stage 2: Dependencies & Playwright
        self.stage_verify_dependencies()

        # Stage 3: Directory Structure & Permissions
        self.stage_init_directories()

        # Stage 4: Network & Base Configuration (.env)
        self.stage_configure_network()

        # Stage 5: Upstash Cloud E2EE Sync Setup
        self.stage_setup_upstash()

        # Stage 6: Service & Startup
        self.stage_configure_services()

        # Stage 7: Final Summary
        self.stage_final_summary()

    # --------------------------------------------------------------------------
    # Stage 1: 角色選擇 (Role Selection)
    # --------------------------------------------------------------------------
    def stage_select_role(self) -> None:
        log_step("1/7", "選擇部署角色 (Deployment Role)")

        # Auto-detection heuristic
        auto_role = "pc"
        if self.is_linux:
            # If running in terminal without graphical session, or on typical cloud VM
            has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
            if not has_display or is_running_as_root():
                auto_role = "vps"

        if self.args.role:
            self.role = self.args.role.lower()
            if self.role not in ("pc", "vps"):
                log_error(f"不支援的角色: {self.role}，僅支援 pc 或 vps。")
                sys.exit(1)
            log_info(f"已指定部署角色: {green(self.role.upper())}")
            return

        if self.args.non_interactive:
            self.role = auto_role
            log_info(f"非互動模式：自動選用角色 {green(self.role.upper())}")
            return

        print("\n請選擇此主機的運作角色：")
        print(f"  {bold('[1] 個人電腦 / 工作站 (PC / Desktop / Laptop)')}")
        print("      - 本機使用，Web 介面預設綁定 127.0.0.1:8000")
        print("      - 支援透過 Upstash 與雲端/其他設備雙向同步節點與憑證")
        print("      - 提供快速啟動腳本與瀏覽器一鍵開啟")
        print(f"  {bold('[2] 雲端 VPS 伺服器 (VPS / Headless Server)')}")
        print("      - 生產伺服器，全天候常駐 (Systemd / Docker)")
        print("      - 集中式憑證換發中心 (Upstash Token Renewal Center)")
        print("      - Web 介面預設綁定 0.0.0.0:8000，支援 Nginx/Caddy 反向代理\n")

        default_opt = "2" if auto_role == "vps" else "1"
        choice = prompt_input(
            f"請選擇安裝模式 (1: PC, 2: VPS)",
            default=default_opt,
        )

        if choice in ("2", "vps", "server"):
            self.role = "vps"
        else:
            self.role = "pc"

        log_success(f"目前選擇角色: {bold(green(self.role.upper()))}")

    # --------------------------------------------------------------------------
    # Stage 2: 依賴與 Playwright 檢查
    # --------------------------------------------------------------------------
    def stage_verify_dependencies(self) -> None:
        log_step("2/7", "檢查核心相依套件與瀏覽器驅動")

        # 1. Check Python version
        py_ver = sys.version_info
        if py_ver < (3, 12):
            log_error(f"需要 Python 3.12 以上版本！目前環境版本: {platform.python_version()}")
            sys.exit(1)
        log_success(f"Python 核心版本相容 ({platform.python_version()})")

        # 2. Check Playwright Chromium
        if not self.args.skip_playwright:
            log_info("檢查 Playwright Chromium (用於 SharePoint / Microsoft 365 認證)...")
            try:
                # Test if playwright is importable
                import playwright  # noqa: F401
                pw_installed = True
            except ImportError:
                pw_installed = False

            if pw_installed:
                # Check browser install
                do_install_pw = True
                if not self.args.non_interactive:
                    do_install_pw = prompt_confirm(
                        "是否檢查並安裝 Playwright Chromium 瀏覽器核心？",
                        default=True,
                    )
                if do_install_pw:
                    log_info("正在安裝 Playwright Chromium...")
                    try:
                        run_command([sys.executable, "-m", "playwright", "install", "chromium"])
                        if self.is_linux and is_running_as_root():
                            log_info("正在配置 Linux 系統圖形依賴函式庫...")
                            run_command([sys.executable, "-m", "playwright", "install-deps", "chromium"])
                        log_success("Playwright Chromium 瀏覽器核心安裝完成！")
                    except Exception as exc:
                        log_warn(f"Playwright 安裝警告 (若不使用 SharePoint 可忽略): {exc}")
            else:
                log_warn("尚未安裝 playwright Python 套件，跳過瀏覽器核心下載。")
        else:
            log_info("依指定略過 Playwright 檢查。")

        # 3. Check Web static assets
        static_html = self.root_dir / "web" / "static" / "index.html"
        if static_html.exists():
            log_success("前端 Web UI 控制台靜態資源已就緒 (web/static/)")
        else:
            log_warn("未在 web/static/ 偵測到編譯後的前端靜態資源。")
            if shutil.which("npm"):
                if self.args.non_interactive or prompt_confirm("偵測到 npm，是否立即編譯前端 (frontend/)？", default=True):
                    log_info("正在安裝 npm 套件並建置前端...")
                    try:
                        run_command("npm install", shell=True, cwd=self.root_dir / "frontend")
                        run_command("npm run build", shell=True, cwd=self.root_dir / "frontend")
                        log_success("前端靜態資源編譯成功！")
                    except Exception as exc:
                        log_warn(f"前端編譯失敗: {exc}")

    # --------------------------------------------------------------------------
    # Stage 3: 目錄結構與權限初始化
    # --------------------------------------------------------------------------
    def stage_init_directories(self) -> None:
        log_step("3/7", "初始化系統組態目錄與安全權限")

        log_dir = self.config_dir / "logs"
        debug_dir = self.config_dir / "debug"
        profiles_dir = self.config_dir / "browser-profiles"
        project_logs = self.root_dir / "logs"

        for directory in (self.config_dir, log_dir, debug_dir, profiles_dir, project_logs):
            directory.mkdir(parents=True, exist_ok=True)

        if not self.is_win:
            try:
                os.chmod(self.config_dir, 0o700)
                os.chmod(log_dir, 0o700)
                os.chmod(debug_dir, 0o700)
                os.chmod(profiles_dir, 0o700)
            except Exception:
                pass

        log_success(f"已建立組態目錄: {self.config_dir} (權限已嚴格鎖定)")

    # --------------------------------------------------------------------------
    # Stage 4: 網路與基礎組態 (.env)
    # --------------------------------------------------------------------------
    def stage_configure_network(self) -> None:
        log_step("4/7", "設定網路監聽與環境變數 (.env)")

        default_host = "0.0.0.0" if self.role == "vps" else "127.0.0.1"
        default_port = 8000

        if self.args.host:
            self.host = self.args.host
        elif self.args.non_interactive:
            self.host = default_host
        else:
            self.host = prompt_input("Web 服務監聽 IP (Host)", default=default_host)

        if self.args.port:
            self.port = self.args.port
        elif self.args.non_interactive:
            self.port = default_port
        else:
            port_str = prompt_input("Web 服務監聽埠號 (Port)", default=str(default_port))
            try:
                self.port = int(port_str)
            except ValueError:
                self.port = default_port

        env_updates = {
            "DRIVE_UNIX_HOST": self.host,
            "DRIVE_UNIX_PORT": str(self.port),
            "PYTHONUNBUFFERED": "1",
            "DRIVE_UNIX_CONFIG_DIR": str(self.config_dir),
            "DRIVE_UNIX_DEBUG_DIR": str(self.config_dir / "debug"),
            "SHAREPOINT_SCREENSHOT_DIR": str(self.config_dir / "debug"),
            "DRIVE_UNIX_BROWSER_PROFILE_DIR": str(self.config_dir / "browser-profiles"),
            "DRIVE_UNIX_BROWSER_PROFILE_ENABLED": "true",
            "DRIVE_UNIX_LOG_LEVEL": "INFO",
            "NO_COLOR": "0",
        }

        update_or_create_env_file(self.env_file, env_updates, self.env_example)
        log_success(f"已更新環境變數檔: {self.env_file} (監聽 {self.host}:{self.port})")

    # --------------------------------------------------------------------------
    # Stage 5: Upstash 雲端多端安全同步 (E2EE) 設定
    # --------------------------------------------------------------------------
    def stage_setup_upstash(self) -> None:
        log_step("5/7", "設定 Upstash 雲端多端安全同步 (E2EE)")

        if self.args.skip_upstash:
            log_info("依指定略過 Upstash 設定。")
            return

        # Check existing config from core.config if available
        existing_url = ""
        existing_token = ""
        existing_sync_key = "drive-unix:sync:default"
        existing_passphrase = ""

        try:
            from core.config import ConfigManager
            config_mgr = ConfigManager()
            url, token, key = config_mgr.get_upstash_config()
            existing_url = url or ""
            existing_token = token or ""
            existing_sync_key = key or "drive-unix:sync:default"
            pass_val = config_mgr.get_upstash_passphrase()
            existing_passphrase = pass_val or ""
        except Exception:
            pass

        # Also check current .env if not found in config
        if self.env_file.exists():
            for line in self.env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("UPSTASH_REDIS_REST_URL=") and not existing_url:
                    existing_url = line.split("=", 1)[1].strip()
                elif line.startswith("UPSTASH_REDIS_REST_TOKEN=") and not existing_token:
                    existing_token = line.split("=", 1)[1].strip()
                elif line.startswith("UPSTASH_SYNC_KEY=") and not existing_sync_key:
                    existing_sync_key = line.split("=", 1)[1].strip()
                elif line.startswith("UPSTASH_SYNC_PASSPHRASE=") and not existing_passphrase:
                    existing_passphrase = line.split("=", 1)[1].strip()

        print("\n" + bold("Upstash Serverless Redis 端對端加密 (E2EE) 跨裝置同步："))
        print("  - 自動在個人電腦與 VPS 之間同步所有雲端節點與憑證")
        print("  - 離機前採用 AES-256-GCM + PBKDF2 600,000 次雜湊加密，零信任雲端安全")
        print("  - VPS 可作為 Token 換發中心，自動在背景更新過期憑證\n")

        do_configure = True
        if not self.args.non_interactive:
            if existing_url and existing_token:
                print(f"偵測到既有 Upstash 連線設定: {cyan(existing_url)}")
                do_configure = prompt_confirm("是否重新設定或測試 Upstash 連線？", default=True)
            else:
                do_configure = prompt_confirm(
                    "是否現在設定 Upstash 雲端同步？ (強烈推薦多端使用者啟用)",
                    default=True,
                )

        if not do_configure:
            log_info("略過 Upstash 設定。可於稍後隨時執行 `drive-unix upstash config` 配置。")
            return

        # Upstash REST URL
        url = self.args.upstash_url or ""
        if not url:
            if self.args.non_interactive:
                url = existing_url
            else:
                url = prompt_input(
                    "Upstash REST URL (例如: https://...upstash.io)",
                    default=existing_url if existing_url else None,
                    required=True,
                )

        # Upstash REST Token
        token = self.args.upstash_token or ""
        if not token:
            if self.args.non_interactive:
                token = existing_token
            else:
                token_hint = "(已保存，直接按 Enter 保留)" if existing_token else None
                prompt_text = f"Upstash REST Token {token_hint}" if token_hint else "Upstash REST Token"
                token_input = prompt_input(
                    prompt_text,
                    default=existing_token if existing_token else None,
                    hide_input=True,
                    required=not bool(existing_token),
                )
                token = token_input if token_input else existing_token

        # Sync Key
        sync_key = self.args.sync_key or ""
        if not sync_key:
            if self.args.non_interactive:
                sync_key = existing_sync_key
            else:
                sync_key = prompt_input(
                    "同步金鑰 (Sync Key)",
                    default=existing_sync_key or "drive-unix:sync:default",
                )

        # Passphrase
        passphrase = self.args.passphrase or ""
        if not passphrase:
            if self.args.non_interactive:
                passphrase = existing_passphrase
            else:
                print("\n" + yellow("【重要安全提示：E2EE 主密碼 (Passphrase)】"))
                print("此密碼用於 AES-256-GCM 本地加密所有 Token 與雲端配置。")
                print("所有需要同步的主機（個人電腦、VPS、NAS）必須使用「完全相同」的主密碼！")
                while True:
                    p1 = prompt_input(
                        "請輸入 E2EE 主密碼 (Passphrase)",
                        default=existing_passphrase if existing_passphrase else None,
                        hide_input=True,
                        required=not bool(existing_passphrase),
                    )
                    effective_p = p1 if p1 else existing_passphrase
                    if existing_passphrase and not p1:
                        passphrase = existing_passphrase
                        break
                    p2 = prompt_input("請再次輸入主密碼以確認", hide_input=True, required=True)
                    if effective_p != p2:
                        print(red("兩次輸入的密碼不一致，請重新輸入！"))
                        continue
                    passphrase = effective_p
                    break

        # Live Connection Test
        log_info("正在測試 Upstash Redis 連線與認證...")
        test_ok = False
        try:
            from infrastructure.upstash_client import UpstashClient
            client = UpstashClient(url, token, timeout=8.0)
            if client.ping():
                log_success("Upstash 連線與認證成功！(PONG 回應正常)")
                test_ok = True
            else:
                log_error("Upstash 連線未回傳預期 PONG 回應。")
        except Exception as exc:
            log_error(f"Upstash 連線測試失敗: {exc}")

        if not test_ok and not self.args.non_interactive:
            proceed_anyway = prompt_confirm("連線測試未通過，是否仍要保存此組設定？", default=False)
            if not proceed_anyway:
                log_warn("已取消 Upstash 設定保存。")
                return

        # Save to ConfigManager & SecretStore
        try:
            from core.config import ConfigManager
            cfg_mgr = ConfigManager()
            cfg_mgr.set_upstash_config(
                rest_url=url,
                rest_token=token,
                sync_key=sync_key,
                passphrase=passphrase,
                auto_sync_tokens=True,
                auto_push_tokens=True,
                renew_leeway_minutes=60,
            )
            log_success("已將 Upstash 金鑰加密儲存至本機 SecretStore (config.toml & secrets.json)。")
        except Exception as exc:
            log_warn(f"寫入 ConfigManager 警告: {exc}")

        # Save to .env
        env_upstash = {
            "UPSTASH_REDIS_REST_URL": url,
            "UPSTASH_REDIS_REST_TOKEN": token,
            "UPSTASH_SYNC_KEY": sync_key,
            "UPSTASH_SYNC_PASSPHRASE": passphrase,
            "UPSTASH_AUTO_SYNC_TOKENS": "true",
            "UPSTASH_AUTO_PUSH_TOKENS": "true",
            "UPSTASH_RENEW_LEEWAY_MINUTES": "60",
        }
        update_or_create_env_file(self.env_file, env_upstash, self.env_example)
        log_success("已同步更新 .env 檔案中之 Upstash 生產環境設定。")

        # Smart Cloud Push / Pull Check
        if test_ok and passphrase:
            self.handle_smart_sync(url, token, sync_key, passphrase)

    def handle_smart_sync(self, url: str, token: str, sync_key: str, passphrase: str) -> None:
        """Inspect cloud bundle and offer smart pull or push."""
        try:
            from application.upstash_sync_service import UpstashSyncService
            from core.config import ConfigManager
            from infrastructure.upstash_client import UpstashClient

            client = UpstashClient(url, token)
            service = UpstashSyncService(client=client)
            status = service.inspect_remote_bundle(sync_key=sync_key)

            if status.get("exists"):
                count = status.get("remotes_count", 0)
                names = ", ".join(status.get("remote_names", [])) or "無"
                dev = status.get("device_name", "未知主機")
                t_str = status.get("created_at", "未知時間")

                print("\n" + green(f"✨ 偵測到雲端存在既有備份！ (來源: {dev}, 時間: {t_str})"))
                print(f"   雲端包含 {bold(str(count))} 個節點: {cyan(names)}")

                do_pull = True
                if not self.args.non_interactive:
                    do_pull = prompt_confirm(
                        "是否立即從 Upstash 下載並解密還原這些節點至本機？ (建議新機器選 Y)",
                        default=True,
                    )

                if do_pull:
                    log_info("正在下載並還原雲端節點與憑證...")
                    res = service.pull(passphrase=passphrase, sync_key=sync_key, merge=True)
                    restored = ", ".join(res.get("restored_remotes", [])) or "無"
                    log_success(f"節點還原完成！已成功恢復節點: {green(restored)}")
            else:
                cfg = ConfigManager()
                local_count = len(cfg.config.remotes)
                if local_count > 0:
                    names = ", ".join(cfg.config.remotes.keys())
                    print(f"\n雲端槽尚無備份，但本機已配置 {bold(str(local_count))} 個節點 ({cyan(names)})。")
                    do_push = True
                    if not self.args.non_interactive:
                        do_push = prompt_confirm(
                            "是否立即將本機既有節點與憑證加密上傳 (Push) 至 Upstash？",
                            default=True,
                        )
                    if do_push:
                        log_info("正在加密上傳本機配置至 Upstash...")
                        service.push(passphrase=passphrase, sync_key=sync_key)
                        log_success("已成功加密備份至雲端！其他節點或 VPS 現在皆可同步使用。")
                else:
                    log_info("雲端與本機目前皆為初始空白狀態，稍後可透過 Web 控制台或 CLI 新增 Remote。")
        except Exception as exc:
            log_warn(f"雲端智慧同步檢查略過: {exc}")

    # --------------------------------------------------------------------------
    # Stage 6: 服務與常駐守護行程配置
    # --------------------------------------------------------------------------
    def stage_configure_services(self) -> None:
        log_step("6/7", "配置系統背景服務與自動啟動")

        if self.args.skip_service:
            log_info("依指定略過服務配置。")
            return

        if self.role == "vps":
            self.setup_vps_systemd()
        else:
            self.setup_pc_shortcuts()

    def setup_vps_systemd(self) -> None:
        """Deploy and optionally start systemd services on Linux VPS."""
        if not self.is_linux:
            log_warn("非 Linux 系統，跳過 Systemd 服務註冊。")
            return

        has_systemctl = bool(shutil.which("systemctl"))
        if not has_systemctl:
            log_warn("系統未偵測到 systemctl，跳過 Systemd 註冊。")
            return

        log_info(f"正在為使用者 {green(self.actual_user)} 生成 Systemd 服務單元...")

        py_bin = sys.executable
        cli_bin = str(Path(sys.executable).parent / "drive-unix")
        if not Path(cli_bin).exists():
            cli_bin = f"{sys.executable} -m cli.app"

        # 1. drive-unix-web.service
        web_service = f"""[Unit]
Description=drive-unix Web Management UI & REST API Server
Documentation=https://github.com/your-org/drive_unix
After=network-online.target
Wants=network-online.target
PartOf=drive-unix.target

[Service]
Type=simple
User={self.actual_user}
Group={self.actual_user}
WorkingDirectory={self.root_dir}
EnvironmentFile=-{self.env_file}
Environment=PYTHONUNBUFFERED=1
ExecStart={py_bin} -m web --host {self.host} --port {self.port}

Restart=always
RestartSec=10
LimitNOFILE=65535

ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target drive-unix.target
"""

        # 2. drive-unix-renew.service
        renew_service = f"""[Unit]
Description=drive-unix Upstash Token Renewal Center Daemon
Documentation=https://github.com/your-org/drive_unix
After=network-online.target
Wants=network-online.target
PartOf=drive-unix.target

[Service]
Type=simple
User={self.actual_user}
Group={self.actual_user}
WorkingDirectory={self.root_dir}
EnvironmentFile=-{self.env_file}
Environment=PYTHONUNBUFFERED=1
ExecStart={py_bin} -m cli.app upstash renew-tokens --interval 1800 --leeway 60

Restart=always
RestartSec=15
LimitNOFILE=65535

ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target drive-unix.target
"""

        # 3. drive-unix.target
        target_unit = """[Unit]
Description=drive-unix Multi-Cloud Storage Suite (Web Console & Token Daemon)
Wants=drive-unix-web.service drive-unix-renew.service
After=network.target

[Install]
WantedBy=multi-user.target
"""

        # Write to systemd directory
        systemd_dir = Path("/etc/systemd/system")
        can_write_systemd = is_running_as_root() or (shutil.which("sudo") is not None)

        if can_write_systemd:
            try:
                for fname, content in (
                    ("drive-unix-web.service", web_service),
                    ("drive-unix-renew.service", renew_service),
                    ("drive-unix.target", target_unit),
                ):
                    target_p = systemd_dir / fname
                    if is_running_as_root():
                        target_p.write_text(content, encoding="utf-8")
                    else:
                        subprocess.run(
                            f"echo '{content}' | sudo tee {target_p} > /dev/null",
                            shell=True,
                            check=True,
                        )

                log_success("已成功安裝 Systemd 服務檔案至 /etc/systemd/system/")

                # Copy nginx template if nginx sites-available exists
                nginx_avail = Path("/etc/nginx/sites-available")
                nginx_src = self.root_dir / "deploy" / "nginx" / "drive-unix.conf"
                if nginx_avail.exists() and nginx_src.exists():
                    log_info("偵測到 Nginx 環境，正在複製最佳化反向代理範本...")
                    if is_running_as_root():
                        shutil.copy(nginx_src, nginx_avail / "drive-unix.conf")
                    else:
                        subprocess.run(
                            f"sudo cp {nginx_src} /etc/nginx/sites-available/drive-unix.conf",
                            shell=True,
                        )
                    log_success("已複製 Nginx 設定範本: /etc/nginx/sites-available/drive-unix.conf")

                # Daemon reload
                if is_running_as_root():
                    run_command(["systemctl", "daemon-reload"])
                else:
                    run_command("sudo systemctl daemon-reload", shell=True)

                do_start = self.args.start
                if not do_start and not self.args.non_interactive:
                    do_start = prompt_confirm(
                        "是否立即啟用並啟動 Systemd 守護服務 (drive-unix.target)？",
                        default=True,
                    )

                if do_start:
                    log_info("正在啟動 drive-unix 背景常駐服務...")
                    cmd = "systemctl enable --now drive-unix.target"
                    if not is_running_as_root():
                        cmd = "sudo " + cmd
                    run_command(cmd, shell=True)
                    log_success("Systemd 服務已成功啟動！(Web 控制台與 Upstash 憑證換發常駐中)")

                    # Probe healthcheck
                    self.probe_healthcheck()
            except Exception as exc:
                log_warn(f"Systemd 安裝或啟動過程中遇到錯誤: {exc}")
        else:
            log_warn("未取得管理員 (root/sudo) 權限，請手動複製 deploy/systemd/ 至 /etc/systemd/system/")

    def setup_pc_shortcuts(self) -> None:
        """Setup convenience runners for PC."""
        log_info("PC 模式初始化：確認啟動腳本就緒...")
        if self.is_win:
            log_success("可使用專案目錄下的 start.bat 或 start.ps1 一鍵啟動 Web 控制台。")
        else:
            log_success("可執行 `python -m web` 或 `./scripts/deploy.sh start` 啟動服務。")

        do_launch = self.args.start
        if not do_launch and not self.args.non_interactive:
            do_launch = prompt_confirm("是否立即啟動 drive-unix Web 管理介面並開啟瀏覽器？", default=True)

        if do_launch:
            url = f"http://{self.host}:{self.port}"
            log_info(f"正在開啟 Web 控制台: {green(url)}")
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass

            log_info("伺服器準備就緒！按 Ctrl+C 可隨時關閉。")
            try:
                subprocess.run([sys.executable, "-m", "web", "--host", self.host, "--port", str(self.port)])
            except KeyboardInterrupt:
                print("\n")
                log_info("Web 服務已由使用者終止。")

    def probe_healthcheck(self) -> None:
        """Probe local health endpoint."""
        target_url = f"http://127.0.0.1:{self.port}/api/health"
        log_info(f"正在驗證伺服器健康檢查 ({target_url})...")
        time.sleep(1.5)
        for _ in range(5):
            try:
                req = urllib.request.Request(target_url, headers={"User-Agent": "drive-unix-setup"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("status") == "ok":
                            log_success(f"健康檢查通過！伺服器運行正常 (version: {data.get('version', '0.1.0')})")
                            return
            except Exception:
                time.sleep(1.0)
        log_warn("健康檢查探針尚未收到 ok 回應，服務可能仍在初始化中。可執行 `scripts/deploy.sh status` 查看。")

    # --------------------------------------------------------------------------
    # Stage 7: 完成總結 (Final Summary)
    # --------------------------------------------------------------------------
    def stage_final_summary(self) -> None:
        log_step("7/7", "🎉 drive-unix 初始化設定完成！")

        border = "=" * 70
        print(green(border))
        print(green(bold("       🎉 drive-unix Multi-Cloud Suite 環境已成功就緒！")))
        print(green(border))

        access_host = self.host if self.host != "0.0.0.0" else "<您的伺服器_IP>"
        web_url = f"http://{access_host}:{self.port}"

        print(f" • 運作模式:       {cyan(self.role.upper())}")
        print(f" • Web 控制台位址: {bold(green(web_url))}")
        print(f" • REST API 文件:  {cyan(web_url + '/docs')}")
        print(f" • 環境組態檔案:   {cyan(str(self.env_file))}")
        print(f" • 本地密鑰金庫:   {cyan(str(self.config_dir))}")

        print("\n" + bold("常用維運與操作指令速查："))
        if self.role == "vps":
            print(f"   - 啟動全套服務:     {yellow('./scripts/deploy.sh start')} (或 sudo systemctl start drive-unix.target)")
            print(f"   - 查詢服務運行狀態: {yellow('./scripts/deploy.sh status')}")
            print(f"   - 查看即時即時日誌: {yellow('./scripts/deploy.sh logs')}")
            print(f"   - 停止背景服務:     {yellow('./scripts/deploy.sh stop')}")
        else:
            print(f"   - 啟動控制台:       {yellow('start.bat')} (或 python -m web)")
            print(f"   - 瀏覽雲端儲存:     {yellow('drive-unix ls <remote>:/')}")
            print(f"   - 執行雙向同步:     {yellow('drive-unix bisync <src> <dst>')}")

        print(f"   - 重新執行設定導引: {yellow('drive-unix setup')} (或 python scripts/setup.py)")
        print(f"   - 查看 Upstash 狀態: {yellow('drive-unix upstash status')}")
        print(f"   - 加密推送最新設定: {yellow('drive-unix upstash push')}")
        print(f"   - 拉取解密雲端設定: {yellow('drive-unix upstash pull')}")
        print(green(border) + "\n")


# ==============================================================================
# 4. 主程式 CLI 參數解析與進入點
# ==============================================================================
def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="drive-unix 統一安裝與初始化導引精靈 (Unified Setup Wizard)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--role",
        choices=["pc", "vps"],
        help="指定安裝角色 (pc: 個人電腦/工作站, vps: 雲端伺服器/換發中心)",
    )
    parser.add_argument(
        "--host",
        help="指定 Web 服務監聽 IP (預設: PC 為 127.0.0.1, VPS 為 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="指定 Web 服務監聽埠號 (預設: 8000)",
    )
    parser.add_argument(
        "--upstash-url",
        help="指定 Upstash REST URL (例如: https://...upstash.io)",
    )
    parser.add_argument(
        "--upstash-token",
        help="指定 Upstash REST Token",
    )
    parser.add_argument(
        "--sync-key",
        help="指定 Upstash 同步金鑰 (預設: drive-unix:sync:default)",
    )
    parser.add_argument(
        "--passphrase",
        help="指定 E2EE 主密碼 (Passphrase)",
    )
    parser.add_argument(
        "--skip-upstash",
        action="store_true",
        help="略過 Upstash 雲端多端同步設定",
    )
    parser.add_argument(
        "--skip-playwright",
        action="store_true",
        help="略過 Playwright Chromium 瀏覽器核心安裝",
    )
    parser.add_argument(
        "--skip-service",
        action="store_true",
        help="略過背景常駐服務 (Systemd) 註冊",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="設定完成後自動啟動服務或開啟 Web 介面",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="非互動自動化模式 (不提示輸入，缺少參數使用預設值)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    orchestrator = SetupOrchestrator(args)
    orchestrator.run()


if __name__ == "__main__":
    main()
