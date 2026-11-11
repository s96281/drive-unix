"""Core upgrade service and version management for drive-unix."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Generator

import requests

from auth.cache import DEFAULT_CACHE_DIR
from core.config import DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_PATH
from core.version import get_git_commit, get_version

logger = logging.getLogger(__name__)

GITHUB_REPO = "s96281/drive-unix"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_TAGS_URL = f"https://api.github.com/repos/{GITHUB_REPO}/tags"

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_upgrade_dir() -> Path:
    """Return the base directory for upgrade cache and pre-upgrade snapshots."""
    upgrade_dir = DEFAULT_CONFIG_DIR / "upgrades"
    upgrade_dir.mkdir(parents=True, exist_ok=True)
    return upgrade_dir


@dataclass
class UpgradeStatus:
    current_version: str
    git_commit: str | None
    latest_version: str
    has_update: bool
    release_date: str | None = None
    release_notes: str | None = None
    release_url: str | None = None
    install_mode: str = "unknown"
    last_checked_at: float | None = None
    is_upgrading: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_install_mode(root: Path | None = None) -> str:
    """Detect whether drive-unix is installed via git, pip, or running in docker."""
    if os.path.exists("/.dockerenv") or os.environ.get("DRIVE_UNIX_DOCKER") == "1":
        return "docker"

    repo_dir = root or PROJECT_ROOT
    if (repo_dir / ".git").is_dir():
        return "git"

    return "pip"


def parse_version(v: str) -> tuple[int, ...]:
    """Parse a semantic version string (e.g. 'v0.1.0' -> (0, 1, 0))."""
    cleaned = v.strip().lstrip("v").strip()
    # Extract only digit sequences joined by dots
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", cleaned)
    if match:
        parts = [int(p) for p in match.groups() if p is not None]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts)
    return (0, 0, 0)


def compare_versions(v1: str, v2: str) -> int:
    """Compare two version strings. Returns -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2."""
    p1 = parse_version(v1)
    p2 = parse_version(v2)
    if p1 < p2:
        return -1
    elif p1 > p2:
        return 1
    return 0


def check_for_updates(force: bool = False, timeout: int = 5) -> UpgradeStatus:
    """Query GitHub Releases to check if an update is available."""
    current_ver = get_version()
    git_commit = get_git_commit(PROJECT_ROOT)
    mode = detect_install_mode(PROJECT_ROOT)

    cache_file = get_upgrade_dir() / "version_cache.json"

    # Check cache if not forced
    if not force and cache_file.is_file():
        try:
            cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
            checked_at = cache_data.get("last_checked_at", 0)
            if time.time() - checked_at < 3600:  # 1 hour cache
                cache_data["current_version"] = current_ver
                cache_data["git_commit"] = git_commit
                cache_data["install_mode"] = mode
                cache_data["has_update"] = compare_versions(current_ver, cache_data.get("latest_version", current_ver)) < 0
                return UpgradeStatus(**cache_data)
        except Exception as e:
            logger.debug("Failed to read upgrade cache: %s", e)

    latest_ver = current_ver
    release_date: str | None = None
    release_notes: str | None = None
    release_url: str | None = None

    try:
        headers = {"User-Agent": f"drive-unix/{current_ver}"}
        resp = requests.get(GITHUB_RELEASES_URL, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            latest_ver = data.get("tag_name", "").lstrip("v") or current_ver
            release_date = data.get("published_at")
            release_notes = data.get("body")
            release_url = data.get("html_url")
        elif resp.status_code == 404:
            # Fallback to tags if releases aren't published yet
            tags_resp = requests.get(GITHUB_TAGS_URL, headers=headers, timeout=timeout)
            if tags_resp.status_code == 200:
                tags = tags_resp.json()
                if tags and isinstance(tags, list):
                    latest_ver = tags[0].get("name", "").lstrip("v") or current_ver
    except Exception as e:
        logger.warning("Could not reach GitHub for update check: %s", e)

    has_update = compare_versions(current_ver, latest_ver) < 0
    status = UpgradeStatus(
        current_version=current_ver,
        git_commit=git_commit,
        latest_version=latest_ver,
        has_update=has_update,
        release_date=release_date,
        release_notes=release_notes,
        release_url=release_url,
        install_mode=mode,
        last_checked_at=time.time(),
        is_upgrading=upgrade_manager.is_running,
    )

    try:
        cache_file.write_text(json.dumps(status.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("Could not write upgrade cache: %s", e)

    return status


def create_pre_upgrade_backup() -> Path:
    """Create a compressed snapshot of the configuration before performing an upgrade."""
    backups_dir = get_upgrade_dir() / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backups_dir / f"pre_upgrade_{timestamp}.zip"

    config_dir = Path(DEFAULT_CONFIG_DIR)
    cache_dir = Path(DEFAULT_CACHE_DIR)

    with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zipf:
        if config_dir.exists():
            for root_dir, _dirs, files in os.walk(config_dir):
                # Skip the upgrades/backups directory itself to prevent recursive bloat
                rel_root = Path(root_dir).relative_to(config_dir)
                if rel_root.parts and rel_root.parts[0] == "upgrades":
                    continue
                for file in files:
                    file_path = Path(root_dir) / file
                    arcname = f"config/{file_path.relative_to(config_dir)}"
                    zipf.write(file_path, arcname)

        if cache_dir.exists():
            for root_dir, _dirs, files in os.walk(cache_dir):
                for file in files:
                    file_path = Path(root_dir) / file
                    arcname = f"auth_cache/{file_path.relative_to(cache_dir)}"
                    zipf.write(file_path, arcname)

    logger.info("Pre-upgrade backup created at %s", backup_file)
    return backup_file


class UpgradeManager:
    """Thread-safe upgrade coordinator with progress tracking and event streaming."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._is_running = False
        self._logs: list[str] = []
        self._current_step = ""
        self._percent = 0
        self._listeners: list[Callable[[str, dict[str, Any]], None]] = []

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def current_step(self) -> str:
        return self._current_step

    @property
    def percent(self) -> int:
        return self._percent

    @property
    def logs(self) -> list[str]:
        return list(self._logs)

    def subscribe(self, callback: Callable[[str, dict[str, Any]], None]) -> Callable[[], None]:
        """Subscribe to upgrade events (log, step, completed, error)."""
        self._listeners.append(callback)

        def unsubscribe():
            if callback in self._listeners:
                self._listeners.remove(callback)

        return unsubscribe

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if event_type == "log" and "text" in data:
            self._logs.append(data["text"])
        elif event_type == "step":
            self._current_step = data.get("step", "")
            self._percent = data.get("percent", self._percent)

        for listener in list(self._listeners):
            try:
                listener(event_type, data)
            except Exception as e:
                logger.debug("Error in upgrade listener: %s", e)

    def run_upgrade(
        self,
        target_version: str | None = None,
        channel: str = "stable",
        backup_config: bool = True,
        force: bool = False,
        dry_run: bool = False,
        restart_after: bool = False,
    ) -> bool:
        """Run the upgrade procedure synchronously (typically launched in a background thread)."""
        with self._lock:
            if self._is_running:
                raise RuntimeError("已有正在進行中的升級任務")
            self._is_running = True
            self._logs.clear()
            self._current_step = "init"
            self._percent = 0

        try:
            return self._execute(
                target_version=target_version,
                channel=channel,
                backup_config=backup_config,
                force=force,
                dry_run=dry_run,
                restart_after=restart_after,
            )
        finally:
            with self._lock:
                self._is_running = False

    def _execute(
        self,
        target_version: str | None,
        channel: str,
        backup_config: bool,
        force: bool,
        dry_run: bool,
        restart_after: bool,
    ) -> bool:
        self._emit("log", {"text": f"🚀 開始執行 drive-unix 升級程序 (頻道: {channel})..."})

        # Step 1: Pre-upgrade Backup
        if backup_config and not dry_run:
            self._emit("step", {"step": "backup", "percent": 15, "message": "正在建立系統組態安全備份..."})
            self._emit("log", {"text": "📦 正在封裝 ~/.config/mycli 與認證快照..."})
            try:
                backup_path = create_pre_upgrade_backup()
                self._emit("log", {"text": f"✅ 備份完成: {backup_path}"})
            except Exception as e:
                self._emit("log", {"text": f"⚠️ 備份遇到問題但繼續升級: {e}"})

        # Step 2: Environment Detection
        mode = detect_install_mode(PROJECT_ROOT)
        self._emit("log", {"text": f"🔍 偵測到執行環境模式: {mode.upper()}"})

        if dry_run:
            self._emit("log", {"text": "🔍 [Dry-Run] 模擬模式：略過實際檔案與依賴安裝"})
            self._emit("step", {"step": "completed", "percent": 100, "message": "模擬升級成功"})
            self._emit("completed", {"success": True, "dry_run": True})
            return True

        # Step 3: Upgrade Execution by Mode
        if mode == "docker":
            self._emit("log", {"text": "🐳 運行於 Docker 容器內，容器檔案系統由外部映像檔驅動。"})
            self._emit("log", {"text": "👉 請在宿主機執行以下指令完成更新："})
            self._emit("log", {"text": "   docker compose pull && docker compose up -d"})
            self._emit("step", {"step": "completed", "percent": 100, "message": "已產生 Docker 更新說明"})
            self._emit("completed", {"success": True, "need_restart": False, "mode": "docker"})
            return True

        if mode == "git":
            success = self._upgrade_git(target_version=target_version, channel=channel)
            if not success:
                self._emit("error", {"message": "Git 更新步驟失敗"})
                return False
        else:
            success = self._upgrade_pip(target_version=target_version)
            if not success:
                self._emit("error", {"message": "Pip 套件更新步驟失敗"})
                return False

        # Step 4: Self Verification
        self._emit("step", {"step": "verify", "percent": 90, "message": "驗證新版本可用性..."})
        self._emit("log", {"text": "🧪 正在驗證核心命令與匯入功能..."})
        try:
            res = subprocess.run(
                [sys.executable, "-m", "main", "--help"],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if res.returncode != 0:
                self._emit("log", {"text": f"❌ 驗證失敗: {res.stderr}"})
                self._emit("error", {"message": "新版本驗證失敗"})
                return False
            self._emit("log", {"text": "✅ 核心功能自檢通過"})
        except Exception as e:
            self._emit("log", {"text": f"⚠️ 自檢超時或異常: {e}"})

        # Step 5: Completed
        new_ver = get_version()
        self._emit("step", {"step": "completed", "percent": 100, "message": f"成功升級至 {new_ver}！"})
        self._emit("log", {"text": f"🎉 drive-unix 已成功更新至版本 {new_ver}"})
        self._emit("completed", {"success": True, "version": new_ver, "need_restart": True})

        # Step 6: Service Restart / Reload if requested
        if restart_after:
            self._emit("log", {"text": "🔄 正在發送訊號重新載入背景服務..."})
            restart_service()

        return True

    def _upgrade_git(self, target_version: str | None, channel: str) -> bool:
        self._emit("step", {"step": "fetch", "percent": 35, "message": "正在拉取 Git 最新代碼與標籤..."})
        self._emit("log", {"text": "🔄 執行 git fetch --tags origin..."})

        res = subprocess.run(["git", "fetch", "--tags", "origin"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        if res.returncode != 0:
            self._emit("log", {"text": f"⚠️ git fetch 失敗: {res.stderr}"})
            # Continue anyway if network or remote issue

        # Checkout or pull
        self._emit("step", {"step": "checkout", "percent": 50, "message": "切換至目標分支或標籤..."})
        if target_version:
            tag = f"v{target_version.lstrip('v')}"
            self._emit("log", {"text": f"📌 切換至標籤 {tag}..."})
            res = subprocess.run(["git", "checkout", tag], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        elif channel == "main":
            self._emit("log", {"text": "📌 拉取 main 主分支最新更動..."})
            res = subprocess.run(["git", "checkout", "main"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
            res = subprocess.run(["git", "pull", "origin", "main"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        else:
            # Default to pulling current branch
            self._emit("log", {"text": "📌 拉取最新代碼..."})
            res = subprocess.run(["git", "pull"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)

        if res.returncode != 0:
            self._emit("log", {"text": f"⚠️ git 切換/拉取提示: {res.stderr or res.stdout}"})

        # Pip install
        self._emit("step", {"step": "install", "percent": 70, "message": "更新 Python 依賴套件..."})
        self._emit("log", {"text": f"📦 執行 {sys.executable} -m pip install -e ...."})
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", "."],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            self._emit("log", {"text": f"❌ pip 安裝失敗: {res.stderr}"})
            return False

        # Frontend build check
        frontend_dir = PROJECT_ROOT / "frontend"
        if frontend_dir.is_dir() and (frontend_dir / "package.json").is_file():
            self._emit("step", {"step": "frontend", "percent": 80, "message": "檢測前端資源與建置..."})
            npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
            if npm_cmd:
                self._emit("log", {"text": "🎨 正在重新編譯前端靜態資產 (npm run build)..."})
                fres = subprocess.run(
                    [npm_cmd, "run", "build"],
                    cwd=str(frontend_dir),
                    capture_output=True,
                    text=True,
                )
                if fres.returncode == 0:
                    self._emit("log", {"text": "✅ 前端資產編譯完成"})
                else:
                    self._emit("log", {"text": f"⚠️ 前端編譯警告: {fres.stderr or fres.stdout}"})
            else:
                self._emit("log", {"text": "ℹ️ 系統未安裝 npm，跳過前端手動編譯"})

        return True

    def _upgrade_pip(self, target_version: str | None) -> bool:
        self._emit("step", {"step": "install", "percent": 60, "message": "正在透過 Pip 安裝新版本..."})
        pkg = f"git+https://github.com/{GITHUB_REPO}.git"
        if target_version:
            pkg += f"@v{target_version.lstrip('v')}"

        self._emit("log", {"text": f"📦 執行 {sys.executable} -m pip install --upgrade {pkg}..."})
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", pkg],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            self._emit("log", {"text": f"❌ pip 更新失敗: {res.stderr}"})
            return False
        return True


upgrade_manager = UpgradeManager()


def restart_service() -> bool:
    """Send signal or command to reload/restart drive-unix background service."""
    logger.info("Attempting to reload/restart drive-unix service...")

    # 1. Linux systemd service check
    if shutil.which("systemctl"):
        for cmd in [
            ["systemctl", "restart", "drive-unix"],
            ["systemctl", "--user", "restart", "drive-unix"],
        ]:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if res.returncode == 0:
                    logger.info("Restarted service via: %s", " ".join(cmd))
                    return True
            except Exception:
                pass

    # 2. If running under uvicorn or custom supervisor, schedule an orderly process reload
    def _deferred_reload():
        time.sleep(1.5)  # Allow API response to flush cleanly to client
        if sys.platform != "win32":
            try:
                os.kill(os.getpid(), signal.SIGHUP)
                return
            except Exception:
                pass
        # Exit process cleanly; process supervisors (docker, systemd, start.sh) will restart it
        if "pytest" not in sys.modules and not os.environ.get("PYTEST_CURRENT_TEST"):
            sys.exit(0)

    threading.Thread(target=_deferred_reload, daemon=True).start()
    return True
