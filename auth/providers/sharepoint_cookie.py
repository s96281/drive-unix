# auth/providers/sharepoint_cookie.py

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, cast

from playwright.sync_api import (
    Cookie,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from auth.base import AuthContext, AuthProvider

from auth.exceptions import (
    AuthCredentialNotFoundError,
    AuthLoginError,
    AuthProviderError,
    AuthTimeoutError,
)

logger = logging.getLogger("drive_unix.auth.sharepoint")

DEFAULT_LOGIN_TIMEOUT_MS = 30_000
DEFAULT_STAY_SIGNED_IN_TIMEOUT_MS = 5_000
DEFAULT_AFTER_LOGIN_WAIT_SECONDS = 5
DEFAULT_SHAREPOINT_EXPIRY_SECONDS = 1 * 24 * 3600  # 1 天 (86,400 秒)

# Persistent browser profile (one directory per canonical auth identity).
DEFAULT_BROWSER_PROFILE_ROOT = Path.home() / ".config" / "drive-unix" / "browser-profiles"
DEFAULT_SESSION_PROBE_TIMEOUT_MS = 15_000

_FALSY_ENV_VALUES = frozenset({"0", "false", "no", "off", "none", "disabled"})


def resolve_browser_profile_root() -> Optional[Path]:
    """Resolve the root directory holding per-identity browser profiles.

    Environment variables:
        DRIVE_UNIX_BROWSER_PROFILE_DIR:
            Explicit root directory. A falsy value (0/false/off/no/none/disabled)
            disables persistent profiles entirely.
        DRIVE_UNIX_BROWSER_PROFILE_ENABLED:
            Set to a falsy value to disable persistent profiles when
            DRIVE_UNIX_BROWSER_PROFILE_DIR is not set.

    Returns:
        The profile root path, or None when persistent profiles are disabled.
    """
    raw = (os.getenv("DRIVE_UNIX_BROWSER_PROFILE_DIR") or "").strip()
    if raw:
        if raw.lower() in _FALSY_ENV_VALUES:
            return None
        return Path(raw).expanduser()

    enabled = (os.getenv("DRIVE_UNIX_BROWSER_PROFILE_ENABLED") or "").strip().lower()
    if enabled in _FALSY_ENV_VALUES:
        return None

    return DEFAULT_BROWSER_PROFILE_ROOT


def get_identity_profile_dir(
    identity_key: str,
    *,
    root: Optional[Path | str] = None,
) -> Optional[Path]:
    """Return the browser profile directory for a single canonical identity.

    One identity == one profile directory. Never share a profile directory
    between different identities: Microsoft login cookies (esctx/AADSSO/uaid)
    are keyed by host+name only, so a shared profile lets one account overwrite
    the single sign-on state of another.

    Args:
        identity_key:
            Output of ``auth.identity.build_identity_cache_key``.
        root:
            Optional explicit profile root; defaults to
            ``resolve_browser_profile_root()``.

    Returns:
        ``<root>/<identity_key>``, or None when profiles are disabled or the
        identity key is empty.
    """
    key = (identity_key or "").strip()
    if not key:
        return None

    resolved_root = Path(root).expanduser() if root is not None else resolve_browser_profile_root()
    if resolved_root is None:
        return None

    return resolved_root / key


def _prepare_profile_dir(profile_dir: Optional[Path | str]) -> Optional[Path]:
    """Create the profile directory with owner-only permissions."""
    if profile_dir is None:
        return None

    path = Path(profile_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        # Windows / restricted filesystems may not support chmod.
        pass
    return path


def _browser_launch_error(
    exc: Exception,
    profile_dir: Optional[Path],
) -> SharePointCookieAuthError:
    hint = ""
    if profile_dir is not None:
        message = str(exc).lower()
        if "singleton" in message or "already in use" in message or "user data directory" in message:
            hint = (
                f" (瀏覽器 profile 目錄可能正被其他行程使用: {profile_dir}。"
                "同一 identity 的換發不可並行執行。)"
            )
    return SharePointBrowserLaunchError(f"Failed to launch Chromium browser: {exc}{hint}")


def _is_profile_locked(exc: Exception) -> bool:
    """Detect Chromium's user-data-dir process singleton lock error."""
    message = str(exc).lower()
    return (
        "processsingleton" in message
        or "singletonlock" in message
        or "already in use" in message
        or "user data directory" in message
    )


def _open_browser_context(
    playwright: Any,
    *,
    profile_dir: Optional[Path],
    headless: bool,
    slow_mo: Optional[int],
    auto_install_browser: bool,
) -> tuple[Any, Any, bool]:
    """Open a browser context, persistent when a profile directory is given.

    Returns:
        (browser, context, used_profile). ``browser`` is None for persistent
        contexts because the context owns the browser process. ``used_profile``
        is False when the persistent profile was locked by another process and
        a temporary context was used instead.
    """

    def _launch() -> tuple[Any, Any, bool]:
        if profile_dir is not None:
            try:
                context = playwright.chromium.launch_persistent_context(
                    str(profile_dir),
                    headless=headless,
                    slow_mo=slow_mo,
                )
                return None, context, True
            except Exception as exc:
                if not _is_profile_locked(exc):
                    raise
                logger.warning(
                    "瀏覽器 profile 正被其他行程使用，改用臨時 profile: %s",
                    profile_dir,
                )

        browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo)
        return browser, browser.new_context(), False

    try:
        return _launch()
    except Exception as exc:
        if auto_install_browser and "Executable doesn't exist" in str(exc):
            subprocess.run(
                ["playwright", "install", "chromium"],
                check=True,
            )
            try:
                return _launch()
            except Exception as retry_exc:
                raise _browser_launch_error(retry_exc, profile_dir) from retry_exc
        raise _browser_launch_error(exc, profile_dir) from exc


def _first_page(context: Any) -> Any:
    """Return the existing page of a context, creating one when needed."""
    try:
        pages = list(context.pages)
    except Exception:
        pages = []
    return pages[0] if pages else context.new_page()


def _find_cookie_expiry(cookies: List[Cookie], name: str) -> Optional[float]:
    """Return the absolute expiry timestamp of a cookie, or None for session cookies."""
    for cookie in cookies:
        if cookie.get("name") != name:
            continue
        try:
            expires = float(cookie.get("expires", -1) or -1)
        except (TypeError, ValueError):
            return None
        return expires if expires > 0 else None
    return None


def _probe_sharepoint_session(
    context: Any,
    sharepoint_base_url: str,
    *,
    timeout_ms: int = DEFAULT_SESSION_PROBE_TIMEOUT_MS,
) -> bool:
    """Check whether the cookies in ``context`` still authenticate against SharePoint.

    Uses the SharePoint REST endpoint ``/_api/web/currentuser`` with the
    context's cookie jar. A redirect back to the Microsoft login page or any
    non-200 response is treated as an expired session.
    """
    base = (sharepoint_base_url or "").rstrip("/")
    if not base:
        return False

    try:
        response = context.request.get(
            f"{base}/_api/web/currentuser",
            headers={"Accept": "application/json;odata=nometadata"},
            timeout=timeout_ms,
            fail_on_status_code=False,
        )
    except Exception as exc:
        logger.debug("探測既有 SharePoint session 失敗: %s", exc)
        return False

    if response.status != 200:
        logger.debug("既有 SharePoint session 已失效 (HTTP %s)", response.status)
        return False

    final_url = (getattr(response, "url", "") or "").lower()
    if "login.microsoftonline.com" in final_url or "login.live.com" in final_url:
        logger.debug("既有 SharePoint session 被導向登入頁，視為失效")
        return False

    return True


def _try_reuse_persisted_session(
    context: Any,
    sharepoint_base_url: str,
) -> Optional[List[Cookie]]:
    """Return cookies when the persisted profile is still signed in."""
    try:
        cookies: List[Cookie] = cast(List[Cookie], context.cookies())
    except Exception:
        return None

    if not (_find_cookie_value(cookies, "rtFa") and _find_cookie_value(cookies, "FedAuth")):
        return None

    if not _probe_sharepoint_session(context, sharepoint_base_url):
        return None

    return cookies


def _clear_auth_cookies(context: Any) -> int:
    """Remove stale rtFa/FedAuth cookies before a fresh login.

    A persisted profile may still carry an expired SharePoint session. If those
    cookies are not removed, the browser keeps sending them and the newly issued
    cookies can end up shadowed by the stale ones (host-only vs parent domain).

    Returns:
        Number of cookie entries that were removed.
    """
    try:
        cookies = context.cookies()
    except Exception:
        return 0

    removed = 0
    for cookie in cookies:
        name = cookie.get("name")
        if name not in ("rtFa", "FedAuth"):
            continue
        try:
            context.clear_cookies(
                name=name,
                domain=cookie.get("domain"),
                path=cookie.get("path"),
            )
            removed += 1
        except Exception:
            logger.debug("無法清除過期的 %s cookie (domain=%s)", name, cookie.get("domain"))
    return removed


def _is_kmsi_prompt(page: Any) -> bool:
    """Detect Microsoft's 'Stay signed in?' (KMSI) prompt."""
    for selector in ('#kmsiTitle', 'input[id="idBtn_Back"]'):
        try:
            locator = page.locator(selector)
            if locator.count() > 0 and locator.first.is_visible():
                return True
        except Exception:
            continue
    return False


def _capture_failure_artifact(
    page: Any,
    *,
    reason: str,
    screenshot_dir: Optional[Path | str] = None,
) -> tuple[Optional[Path], str, str, Optional[str]]:
    """
    Capture screenshot, title, current URL, and any visible error text on failure.
    Returns (screenshot_path, page_title, page_url, visible_error_text).
    """
    page_title = ""
    page_url = ""
    visible_error = None
    screenshot_path = None

    if page is None:
        return None, "", "", None

    try:
        page_title = page.title()
    except Exception:
        pass

    try:
        page_url = page.url
    except Exception:
        pass

    # Extract any visible Microsoft login error message on page
    try:
        error_selectors = [
            "#passwordError",
            "#usernameError",
            "#errorMessage",
            ".alert-error",
            "div[role='alert']",
            "div[id*='Error']",
            "div[id*='error']",
        ]
        for sel in error_selectors:
            loc = page.locator(sel)
            if loc.count() > 0:
                text = loc.first.inner_text().strip()
                if text:
                    visible_error = text
                    break
    except Exception:
        pass

    # Save screenshot
    try:
        if screenshot_dir is None:
            env_dir = os.getenv("SHAREPOINT_SCREENSHOT_DIR") or os.getenv("DRIVE_UNIX_DEBUG_DIR")
            if env_dir:
                target_dir = Path(env_dir)
            else:
                target_dir = Path.home() / ".config" / "drive-unix" / "debug"
        else:
            target_dir = Path(screenshot_dir)

        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_reason = "".join(c if c.isalnum() or c in "-_" else "_" for c in reason)[:30]
        screenshot_path = target_dir / f"sharepoint_{safe_reason}_{timestamp}.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        logger.info("已擷取 SharePoint 登入失敗畫面截圖: %s", screenshot_path)
    except Exception as exc:
        logger.debug("擷取 SharePoint 失敗截圖時發生例外: %s", exc)

    return screenshot_path, page_title, page_url, visible_error


class SharePointLoginRecorder:
    """
    Records per-second screenshot frames during SharePoint login.
    If login succeeds, all frames and the session folder are cleaned up automatically.
    If login fails, frames are preserved in debug_dir for step-by-step troubleshooting.
    """

    def __init__(
        self,
        base_dir: Optional[Path | str] = None,
        *,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.frame_index = 0
        self.start_time = time.time()
        self.frames: list[Path] = []

        if not self.enabled:
            self.session_dir: Optional[Path] = None
            return

        if base_dir is None:
            env_dir = os.getenv("SHAREPOINT_SCREENSHOT_DIR") or os.getenv("DRIVE_UNIX_DEBUG_DIR")
            if env_dir:
                root_dir = Path(env_dir)
            else:
                root_dir = Path.home() / ".config" / "drive-unix" / "debug"
        else:
            root_dir = Path(base_dir)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.session_dir = root_dir / f"sharepoint_session_{timestamp}"
        try:
            self.session_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.enabled = False
            self.session_dir = None

    def capture(self, page: Any, step_label: str = "") -> Optional[Path]:
        """Capture a single frame if enabled."""
        if not self.enabled or not self.session_dir or page is None:
            return None

        self.frame_index += 1
        elapsed = int(time.time() - self.start_time)
        clean_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in step_label)[:25]
        if clean_label:
            filename = f"frame_{self.frame_index:03d}_{elapsed:02d}s_{clean_label}.png"
        else:
            filename = f"frame_{self.frame_index:03d}_{elapsed:02d}s.png"

        frame_path = self.session_dir / filename
        try:
            page.screenshot(path=str(frame_path), full_page=True)
            self.frames.append(frame_path)
            return frame_path
        except Exception as exc:
            logger.debug("擷取畫面失敗: %s", exc)
            return None

    def cleanup_on_success(self) -> None:
        """Remove all temporary screenshots on successful login."""
        if not self.session_dir or not self.session_dir.exists():
            return
        try:
            shutil.rmtree(self.session_dir, ignore_errors=True)
            logger.info("SharePoint 登入成功，已自動清除暫存歷程截圖 (%d 張)", len(self.frames))
        except Exception as exc:
            logger.debug("清除截圖目錄失敗: %s", exc)

    def get_summary(self) -> str:
        """Return summary of captured frames for error reporting."""
        if not self.session_dir or not self.frames:
            return ""
        return f"\n📸 登入歷程連環截圖 (每秒 1 張，共 {len(self.frames)} 張) 已保留於:\n   {self.session_dir}"


def _detect_microsoft_authenticator_challenge(page: Any) -> tuple[bool, Optional[str]]:
    """
    Detects if Microsoft login is waiting for mobile Authenticator approval.
    Returns (is_mfa_active, number_to_enter_on_phone).
    """
    if page is None:
        return False, None

    # 1. First, check dedicated number matching element
    number_selectors = [
        "#richContext_display",
        "div.display-sign-in-number",
        "#idRichContext_FTP .table-cell",
        "#idRichContext_FTP",
        "div[id*='richContext']",
        "div[id*='RichContext']",
    ]
    for sel in number_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                text = loc.first.inner_text().strip()
                match = re.search(r"\b(\d{1,3})\b", text)
                if match:
                    return True, match.group(1)
        except Exception:
            pass

    # 2. Check for general Authenticator push prompt (without number matching or pending load)
    title_selectors = [
        "#idDiv_SAASTO_Title",
        "#idDiv_SAOTCC_Title",
        "#idDiv_SAASTO_Description",
        "#idDiv_SAOTCC_Description",
    ]
    for sel in title_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                text = loc.first.inner_text().strip()
                match = re.search(r"\b(\d{1,3})\b", text)
                if match:
                    return True, match.group(1)
                return True, None
        except Exception:
            pass

    # 3. Check page title or text for keywords
    try:
        page_title = page.title()
        if any(kw in page_title for kw in ["Approve", "核准", "Authenticator"]):
            return True, None
    except Exception:
        pass

    return False, None


def _save_active_mfa_status(number: Optional[str], active: bool) -> None:
    """Save active MFA challenge number to a local file for status APIs or tools."""
    try:
        debug_dir = Path.home() / ".config" / "drive-unix" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        status_file = debug_dir / "mfa_challenge.json"
        if active:
            data = {
                "active": True,
                "number": number,
                "updated_at": time.time(),
                "message": f"請在手機輸入數字：{number}" if number else "請在手機點擊核准",
            }
            status_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        else:
            if status_file.exists():
                status_file.unlink(missing_ok=True)
    except Exception:
        pass


def _handle_keep_account_secure_or_skip(
    page: Any,
    recorder: Optional[SharePointLoginRecorder] = None,
) -> bool:
    """
    Detects Microsoft's "Let's keep your account secure" / "Help us protect your account"
    screen or any "Not now" / "Not know" / "Skip for now" prompts, and automatically clicks to bypass.
    Returns True if a skip button or link was clicked.
    """
    if page is None:
        return False

    skip_selectors = [
        # IDs commonly used by Microsoft for skip/ask later actions
        '#btnAskLater',
        'a[id="btnAskLater"]',
        'button[id="btnAskLater"]',
        'a[id*="AskLater"]',
        'button[id*="AskLater"]',
        'a[id*="Skip"]',
        'button[id*="Skip"]',
        # Text based buttons/links (case-insensitive where possible)
        'button:has-text("Not now")',
        'a:has-text("Not now")',
        'button:has-text("Not know")',
        'a:has-text("Not know")',
        'button:has-text("Skip for now")',
        'a:has-text("Skip for now")',
        'button:has-text("Ask later")',
        'a:has-text("Ask later")',
        'button:has-text("現在不要")',
        'a:has-text("現在不要")',
        'button:has-text("稍後再說")',
        'a:has-text("稍後再說")',
        'button:has-text("稍後")',
        'a:has-text("稍後")',
        'button:has-text("略過")',
        'a:has-text("略過")',
    ]

    for sel in skip_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                txt = loc.first.inner_text().strip()
                logger.info("偵測到帳戶安全提示，自動點擊跳過選項: '%s'", txt or sel)
                loc.first.click()
                if recorder:
                    recorder.capture(page, step_label="skip_secure_prompt")
                return True
        except Exception:
            pass

    # Check if page heading or text mentions keeping account secure
    try:
        content = page.content().lower()
        if any(kw in content for kw in ["keep your account secure", "protect your account", "保護您的帳戶", "保持帳戶安全"]):
            for tag in ["a", "button", "input[type='button']", "div[role='button']"]:
                locs = page.locator(tag)
                for i in range(min(locs.count(), 10)):
                    item = locs.nth(i)
                    if item.is_visible():
                        item_text = item.inner_text().lower().strip()
                        if any(w in item_text for w in ["not now", "not know", "skip", "later", "稍後", "略過", "不要"]):
                            logger.info("偵測到安全提示頁面跳過按鈕: '%s'，自動點擊...", item_text)
                            item.click()
                            if recorder:
                                recorder.capture(page, step_label="skip_secure_prompt")
                            return True
    except Exception:
        pass

    return False


def _wait_for_condition_with_recording(
    page: Any,
    condition_fn: Callable[[], bool],
    *,
    timeout_ms: int,
    step_name: str,
    recorder: SharePointLoginRecorder,
    poll_interval_ms: int = 1000,
    detect_mfa: bool = False,
) -> bool:
    """
    Polls condition_fn every poll_interval_ms (default 1000ms = 1 sec).
    Captures a screenshot frame every second while waiting.
    If detect_mfa is True and an Authenticator challenge is detected:
      - Prominently displays the number to enter on the phone
      - Dynamically extends the timeout so the user has sufficient time (90s) to approve
    Returns True if condition became True before timeout, False otherwise.
    """
    start = time.perf_counter()
    timeout_s = timeout_ms / 1000.0
    mfa_notified = False

    while True:
        try:
            if condition_fn():
                if mfa_notified:
                    logger.info("🎉【MFA 驗證完成】已成功在手機上核准，繼續完成 SharePoint 驗證！")
                    _save_active_mfa_status(None, active=False)
                return True
        except Exception:
            pass

        # Check for MFA Challenge
        if detect_mfa:
            is_mfa, number = _detect_microsoft_authenticator_challenge(page)
            if is_mfa:
                step_name = "wait_mfa"
                if not mfa_notified:
                    mfa_notified = True
                    # Dynamically extend timeout to at least 90s from this moment
                    timeout_s = max(timeout_s, (time.perf_counter() - start) + 90.0)
                    _save_active_mfa_status(number, active=True)
                    if number:
                        banner = (
                            "\n" + "=" * 65 + "\n"
                            f"🔔【Microsoft 雙重驗證 (MFA) - 請在手機輸入數字】\n"
                            f"微軟要求數字比對！請開啟手機上的 Microsoft Authenticator 並輸入：\n\n"
                            f"                  👉 【 {number} 】 👈\n\n"
                            f"系統正在背景等候您的手機核准 (最長等候 90 秒)..."
                            "\n" + "=" * 65 + "\n"
                        )
                    else:
                        banner = (
                            "\n" + "=" * 65 + "\n"
                            "🔔【Microsoft 雙重驗證 (MFA) - 請於手機確認】\n"
                            "微軟已發送登入推播！請在手機上的 Microsoft Authenticator 點擊「核准 (Approve)」...\n"
                            "系統正在背景等候您的手機核准 (最長等候 90 秒)..."
                            "\n" + "=" * 65 + "\n"
                        )
                    logger.warning(banner.strip())

        recorder.capture(page, step_label=step_name)

        if (time.perf_counter() - start) >= timeout_s:
            if mfa_notified:
                _save_active_mfa_status(None, active=False)
            return False

        remaining_ms = int(max(100, min(poll_interval_ms, (timeout_s - (time.perf_counter() - start)) * 1000)))
        try:
            page.wait_for_timeout(remaining_ms)
        except Exception:
            time.sleep(remaining_ms / 1000.0)


class SharePointCookieAuthError(AuthProviderError):
    """Base exception for SharePoint cookie authentication errors."""


class SharePointLoginTimeoutError(AuthTimeoutError, SharePointCookieAuthError):
    """Raised when SharePoint / Microsoft login page does not respond in time."""


class SharePointCookieNotFoundError(
    AuthCredentialNotFoundError,
    SharePointCookieAuthError,
):
    """Raised when rtFa or FedAuth cannot be found after login."""


class SharePointBrowserLaunchError(SharePointCookieAuthError):
    """Raised when Playwright browser cannot be launched."""


@dataclass(frozen=True)
class SharePointCookieResult:
    """
    Raw SharePoint cookie result.

    This is intentionally more detailed than AuthContext because provider-level
    callers may want to inspect raw cookies during debugging.
    """

    cookie_header: str
    rtFa: str
    FedAuth: str
    cookies: list[Cookie]
    created_at: float
    cookie_expires_at: Optional[float] = None
    profile_dir: Optional[str] = None

    def to_auth_context(
        self,
        *,
        provider_name: str,
        account: str,
        resource: str,
        expires_at: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuthContext:
        """
        Convert SharePoint cookie result into a generic AuthContext.

        The upper layers should consume AuthContext instead of directly
        depending on SharePoint-specific cookie fields.
        """
        merged_metadata: Dict[str, Any] = {
            "provider": provider_name,
            "account": account,
            "resource": resource,
            "created_at": self.created_at,
            "auth_type": "cookie",
        }

        if metadata:
            merged_metadata.update(metadata)

        return AuthContext(
            headers={
                "Cookie": self.cookie_header,
            },
            expires_at=expires_at,
            metadata=merged_metadata,
        )


def get_cookie(
    sharepoint_base_url: str,
    email: str,
    password: str,
    *,
    headless: bool = True,
    slow_mo: Optional[int] = None,
    login_timeout_ms: int = DEFAULT_LOGIN_TIMEOUT_MS,
    stay_signed_in_timeout_ms: int = DEFAULT_STAY_SIGNED_IN_TIMEOUT_MS,
    after_login_wait_seconds: int = DEFAULT_AFTER_LOGIN_WAIT_SECONDS,
    auto_install_browser: bool = True,
    screenshot_dir: Optional[Path | str] = None,
    profile_dir: Optional[Path | str] = None,
    reuse_existing_session: bool = True,
    force_login: bool = False,
) -> SharePointCookieResult:
    """
    Always login and fetch a fresh SharePoint cookie.

    This function does NOT read or write cache.
    Cache should be handled by auth.cache.CachedAuthProvider.

    Args:
        profile_dir:
            Optional persistent browser profile directory. When provided,
            Chromium runs with ``launch_persistent_context`` so cookies,
            localStorage and IndexedDB survive across runs. Must be unique per
            canonical auth identity.
        reuse_existing_session:
            When a persistent profile already holds a valid session, return its
            cookies without running the login flow. Ignored without a profile.
        force_login:
            Skip session reuse and always run the full login flow.

    Returns:
        SharePointCookieResult containing:
        - cookie_header: "rtFa=...;FedAuth=..."
        - rtFa
        - FedAuth
        - raw Playwright cookies
        - created_at timestamp
    """
    headless = True
    if not sharepoint_base_url:
        raise ValueError("sharepoint_base_url is required.")

    if not email:
        raise ValueError("email is required.")

    if not password:
        raise ValueError("password is required.")

    profile_path = _prepare_profile_dir(profile_dir)

    with sync_playwright() as p:
        browser = None
        context = None

        try:
            browser, context, used_profile = _open_browser_context(
                p,
                profile_dir=profile_path,
                headless=headless,
                slow_mo=slow_mo,
                auto_install_browser=auto_install_browser,
            )
            persist_session = profile_path is not None and used_profile
            page = _first_page(context)

            if persist_session and reuse_existing_session and not force_login:
                reused_cookies = _try_reuse_persisted_session(context, sharepoint_base_url)
                if reused_cookies is not None:
                    logger.info(
                        "沿用已保存的瀏覽器登入狀態，跳過登入流程 (profile=%s)",
                        profile_path,
                    )
                    return _build_cookie_result(
                        reused_cookies,
                        profile_dir=profile_path,
                    )

            if persist_session:
                cleared = _clear_auth_cookies(context)
                if cleared:
                    logger.info("已清除 %d 個過期的 SharePoint 驗證 cookie，準備重新登入", cleared)

            recorder = SharePointLoginRecorder(base_dir=screenshot_dir)

            # Cookies already in the jar before this login flow. A persisted profile
            # may carry stale rtFa/FedAuth that must not be mistaken for success.
            initial_cookie_values = {
                name: _find_cookie_value(context.cookies(), name)
                for name in ("rtFa", "FedAuth")
            }

            try:
                page.goto(
                    sharepoint_base_url,
                    wait_until="domcontentloaded",
                    timeout=login_timeout_ms,
                )
                recorder.capture(page, step_label="goto_done")
                time.sleep(1)
                # Step 1: Wait for email input (takes screenshot every sec)
                email_ready = _wait_for_condition_with_recording(
                    page,
                    lambda: page.locator('input[type="email"]').is_visible(),
                    timeout_ms=login_timeout_ms,
                    step_name="wait_email",
                    recorder=recorder,
                )
                if not email_ready:
                    # The persistent profile may have signed in silently between
                    # navigation and this check (e.g. KMSI + valid rtFa).
                    if persist_session:
                        reused_cookies = _try_reuse_persisted_session(
                            context, sharepoint_base_url
                        )
                        if reused_cookies is not None:
                            logger.info(
                                "登入頁未出現，但既有 session 仍有效，直接沿用 (profile=%s)",
                                profile_path,
                            )
                            recorder.cleanup_on_success()
                            return _build_cookie_result(
                                reused_cookies,
                                profile_dir=profile_path,
                            )
                    raise PlaywrightTimeoutError("等待微軟帳號輸入框 (loginfmt) 超時")

                page.fill('input[type="email"]', email)
                recorder.capture(page, step_label="email_filled")
                page.click('input[type="submit"]')
                recorder.capture(page, step_label="email_submitted")

                # Step 2: Wait for password input (takes screenshot every sec)
                time.sleep(1)
                passwd_ready = _wait_for_condition_with_recording(
                    page,
                    lambda: page.locator('input[type="password"]').is_visible(),
                    timeout_ms=login_timeout_ms,
                    step_name="wait_password",
                    recorder=recorder,
                )
                if not passwd_ready:
                    raise PlaywrightTimeoutError("等待微軟密碼輸入框 (passwd) 超時")
                time.sleep(1)
                page.fill('input[type="password"]', password)
                recorder.capture(page, step_label="passwd_filled")
                page.click('input[type="submit"]')
                recorder.capture(page, step_label="passwd_submitted")

                # Step 3: Wait for cookies or "Stay signed in?" prompt (takes screenshot every sec + MFA detection)
                def _check_cookies_or_prompt() -> bool:
                    try:
                        # 1. Automatically handle "Let's keep your account secure" or "Not now" / "Not know" prompts
                        _handle_keep_account_secure_or_skip(page, recorder=recorder)

                        # 2. Check "Stay signed in?" prompt (No: idBtn_Back, Yes: idSIButton9)
                        btn_back = page.locator('input[id="idBtn_Back"]')
                        btn_yes = page.locator('input[id="idSIButton9"]')
                        if persist_session and _is_kmsi_prompt(page):
                            # Keep the session on disk: choose "Yes" so Microsoft
                            # issues a persistent rtFa instead of a session cookie.
                            if btn_yes.is_visible():
                                btn_yes.click()
                            elif btn_back.is_visible():
                                btn_back.click()
                        elif btn_back.is_visible():
                            btn_back.click()
                        elif btn_yes.is_visible():
                            btn_yes.click()
                    except Exception:
                        pass

                    ck = context.cookies()
                    rtfa_value = _find_cookie_value(ck, "rtFa")
                    fedauth_value = _find_cookie_value(ck, "FedAuth")
                    if not rtfa_value or not fedauth_value:
                        return False

                    # A persisted profile may still hold stale rtFa/FedAuth cookies.
                    # Only accept them once the browser has left the Microsoft login
                    # page, i.e. SharePoint itself issued the session.
                    try:
                        current_url = (page.url or "").lower()
                    except Exception:
                        current_url = ""
                    if "login.microsoftonline.com" in current_url or "login.live.com" in current_url:
                        return False

                    # Fresh cookies from this login are trusted directly. Cookies that
                    # are identical to the pre-login snapshot must be verified against
                    # SharePoint, otherwise a stale profile would look like a success.
                    if (rtfa_value, fedauth_value) != (
                        initial_cookie_values.get("rtFa"),
                        initial_cookie_values.get("FedAuth"),
                    ):
                        return True

                    return _probe_sharepoint_session(context, sharepoint_base_url)

                wait_cookies_timeout_ms = max(
                    20_000,
                    (stay_signed_in_timeout_ms + (after_login_wait_seconds * 1000))
                )
                _wait_for_condition_with_recording(
                    page,
                    _check_cookies_or_prompt,
                    timeout_ms=wait_cookies_timeout_ms,
                    step_name="wait_auth",
                    recorder=recorder,
                    detect_mfa=True,
                )

                cookies = context.cookies()

            except PlaywrightTimeoutError as exc:
                s_path, p_title, p_url, vis_err = _capture_failure_artifact(
                    page, reason="timeout", screenshot_dir=screenshot_dir
                )
                msg_parts = [
                    "Timed out while logging into SharePoint. "
                    "The login flow may have changed, MFA may be required, "
                    "or the account may be blocked by Conditional Access."
                ]
                if vis_err:
                    msg_parts.append(f"頁面提示訊息: '{vis_err}'")
                if p_title or p_url:
                    msg_parts.append(f"(頁面標題: '{p_title}', URL: {p_url})")
                if s_path:
                    msg_parts.append(f"📸 失敗畫面截圖已儲存至: {s_path}")
                msg_parts.append(recorder.get_summary())
                raise SharePointLoginTimeoutError("\n".join(filter(None, msg_parts))) from exc
            except Exception as exc:
                s_path, p_title, p_url, vis_err = _capture_failure_artifact(
                    page, reason="login_exception", screenshot_dir=screenshot_dir
                )
                if not isinstance(exc, (SharePointCookieAuthError,)):
                    msg = f"登入 SharePoint 時發生未預期錯誤: {exc}"
                    if s_path:
                        msg += f"\n📸 失敗畫面截圖已儲存至: {s_path}"
                    msg += recorder.get_summary()
                    raise SharePointCookieAuthError(msg) from exc
                raise

            rtfa = _find_cookie_value(cookies, "rtFa")
            fedauth = _find_cookie_value(cookies, "FedAuth")

            if not rtfa or not fedauth:
                s_path, p_title, p_url, vis_err = _capture_failure_artifact(
                    page, reason="missing_cookies", screenshot_dir=screenshot_dir
                )
                found_cookie_names = sorted(
                    {
                        str(cookie.get("name"))
                        for cookie in cookies
                        if cookie.get("name")
                    }
                )
                msg_parts = [
                    "Could not find required SharePoint cookies: rtFa and FedAuth. "
                    f"Found cookies: {found_cookie_names}. "
                    "This may happen if login failed, MFA is required, "
                    "or SharePoint changed its authentication flow."
                ]
                if vis_err:
                    msg_parts.append(f"頁面提示訊息: '{vis_err}'")
                if p_title or p_url:
                    msg_parts.append(f"(頁面標題: '{p_title}', URL: {p_url})")
                if s_path:
                    msg_parts.append(f"📸 失敗畫面截圖已儲存至: {s_path}")
                msg_parts.append(recorder.get_summary())
                raise SharePointCookieNotFoundError("\n".join(filter(None, msg_parts)))

            # 登入成功：清除所有每秒錄製的暫存截圖
            recorder.cleanup_on_success()

            return _build_cookie_result(
                cookies,
                profile_dir=profile_path if persist_session else None,
            )

        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass


def _build_cookie_result(
    cookies: List[Cookie],
    *,
    profile_dir: Optional[Path] = None,
) -> SharePointCookieResult:
    """Build a SharePointCookieResult from a cookie jar."""
    rtfa = _find_cookie_value(cookies, "rtFa")
    fedauth = _find_cookie_value(cookies, "FedAuth")

    if not rtfa or not fedauth:
        found_cookie_names = sorted(
            {str(cookie.get("name")) for cookie in cookies if cookie.get("name")}
        )
        raise SharePointCookieNotFoundError(
            "Could not find required SharePoint cookies: rtFa and FedAuth. "
            f"Found cookies: {found_cookie_names}."
        )

    return SharePointCookieResult(
        cookie_header=f"rtFa={rtfa};FedAuth={fedauth}",
        rtFa=rtfa,
        FedAuth=fedauth,
        cookies=cookies,
        created_at=time.time(),
        cookie_expires_at=_find_cookie_expiry(cookies, "rtFa"),
        profile_dir=str(profile_dir) if profile_dir is not None else None,
    )


class SharePointCookieProvider(AuthProvider):
    """
    AuthProvider implementation for SharePoint cookie authentication.

    This provider only knows how to fetch fresh SharePoint cookies.
    It does not know anything about file cache, TTL, or cache keys.

    Use it with CachedAuthProvider if cache is needed.
    """

    provider_name = "sharepoint_cookie"

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        password: str | None,
        headless: bool = True,
        slow_mo: Optional[int] = None,
        login_timeout_ms: int = DEFAULT_LOGIN_TIMEOUT_MS,
        stay_signed_in_timeout_ms: int = DEFAULT_STAY_SIGNED_IN_TIMEOUT_MS,
        after_login_wait_seconds: int = DEFAULT_AFTER_LOGIN_WAIT_SECONDS,
        auto_install_browser: bool = True,
        expires_in_seconds: Optional[int] = DEFAULT_SHAREPOINT_EXPIRY_SECONDS,
        screenshot_dir: Optional[Path | str] = None,
        profile_dir: Optional[Path | str] = None,
        reuse_existing_session: bool = True,
        force_login: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            base_url:
                SharePoint site URL.

            email:
                Microsoft account email.

            password:
                Microsoft account password.

            headless:
                Whether Playwright runs in headless mode.

            slow_mo:
                Playwright slow motion delay in milliseconds.
                Useful for debugging login flow.

            expires_in_seconds:
                Optional synthetic expiry.
                SharePoint cookies may not expose a simple reliable expiry,
                so you may choose to set this to something like 3600 or 86400.
                Cache layer can also apply TTL independently.

            screenshot_dir:
                Optional directory to store failure screenshots.

            profile_dir:
                Optional persistent browser profile directory. One directory per
                canonical auth identity; never share it between identities.

            reuse_existing_session:
                Reuse the persisted session instead of logging in again when it
                is still valid. Requires ``profile_dir``.

            force_login:
                Always run the full login flow, ignoring the persisted session.

            metadata:
                Additional non-sensitive metadata.
        """
        if not base_url:
            raise ValueError("base_url is required.")

        if not email:
            raise ValueError("email is required.")

        if not password:
            raise ValueError("password is required.")

        self.base_url = base_url
        self.email = email
        self.password: str = password
        self.headless = headless
        self.slow_mo = slow_mo
        self.login_timeout_ms = login_timeout_ms
        self.stay_signed_in_timeout_ms = stay_signed_in_timeout_ms
        self.after_login_wait_seconds = after_login_wait_seconds
        self.auto_install_browser = auto_install_browser
        self.expires_in_seconds = (
            expires_in_seconds if expires_in_seconds is not None else DEFAULT_SHAREPOINT_EXPIRY_SECONDS
        )
        self.screenshot_dir = screenshot_dir
        self.profile_dir = Path(profile_dir).expanduser() if profile_dir else None
        self.reuse_existing_session = reuse_existing_session
        self.force_login = force_login
        self.metadata = dict(metadata or {})

    def get_auth_context(self) -> AuthContext:
        """
        Return a fresh AuthContext.

        This provider itself does not cache. If you want cache behavior,
        wrap this provider with auth.cache.CachedAuthProvider.
        """
        return self.refresh()

    def reset_profile(self) -> bool:
        """Delete the persisted browser profile of this identity.

        Returns True when a profile directory was removed. Call this after a
        password change or when the stored session is known to be corrupt.
        """
        if self.profile_dir is None:
            return False
        if not self.profile_dir.exists():
            return False

        shutil.rmtree(self.profile_dir, ignore_errors=True)
        logger.warning("已刪除瀏覽器 profile: %s", self.profile_dir)
        return not self.profile_dir.exists()

    def refresh(self) -> AuthContext:
        """
        Force login and return a new AuthContext.
        """
        result = get_cookie(
            sharepoint_base_url=self.base_url,
            email=self.email,
            password=self.password,
            headless=self.headless,
            slow_mo=self.slow_mo,
            login_timeout_ms=self.login_timeout_ms,
            stay_signed_in_timeout_ms=self.stay_signed_in_timeout_ms,
            after_login_wait_seconds=self.after_login_wait_seconds,
            auto_install_browser=self.auto_install_browser,
            screenshot_dir=self.screenshot_dir,
            profile_dir=self.profile_dir,
            reuse_existing_session=self.reuse_existing_session,
            force_login=self.force_login,
        )

        expires_at = None
        if self.expires_in_seconds is not None:
            expires_at = result.created_at + self.expires_in_seconds
            # Never advertise a lifetime longer than the real rtFa cookie.
            if result.cookie_expires_at and result.cookie_expires_at > result.created_at:
                expires_at = min(expires_at, result.cookie_expires_at)

        return result.to_auth_context(
            provider_name=self.provider_name,
            account=self.email,
            resource=self.base_url,
            expires_at=expires_at,
            metadata=self.metadata,
        )


def _find_cookie_value(
    cookies: list[Cookie],
    name: str,
) -> Optional[str]:
    """
    Find cookie value by cookie name.
    """
    for cookie in cookies:
        if cookie.get("name") == name:
            value = cookie.get("value")
            if value:
                return str(value)

    return None