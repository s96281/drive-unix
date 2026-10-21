# auth/providers/sharepoint_cookie.py

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

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
) -> SharePointCookieResult:
    """
    Always login and fetch a fresh SharePoint cookie.

    This function does NOT read or write cache.
    Cache should be handled by auth.cache.CachedAuthProvider.

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

    with sync_playwright() as p:
        browser = None

        try:
            try:
                browser = p.chromium.launch(
                    headless=headless,
                    slow_mo=slow_mo,
                )
            except Exception as exc:
                if auto_install_browser and "Executable doesn't exist" in str(exc):
                    subprocess.run(
                        ["playwright", "install", "chromium"],
                        check=True,
                    )
                    browser = p.chromium.launch(
                        headless=headless,
                        slow_mo=slow_mo,
                    )
                else:
                    raise SharePointBrowserLaunchError(
                        f"Failed to launch Chromium browser: {exc}"
                    ) from exc

            context = browser.new_context()
            page = context.new_page()

            try:
                page.goto(
                    sharepoint_base_url,
                    wait_until="domcontentloaded",
                    timeout=login_timeout_ms,
                )

                # Email step
                page.wait_for_selector(
                    'input[name="loginfmt"]',
                    timeout=login_timeout_ms,
                )
                page.fill('input[name="loginfmt"]', email)
                page.click('input[type="submit"]')

                # Password step
                page.wait_for_selector(
                    'input[name="passwd"]',
                    timeout=login_timeout_ms,
                )
                page.fill('input[name="passwd"]', password)
                page.click('input[type="submit"]')

                # Optional "Stay signed in?" prompt.
                # Usually idBtn_Back means "No".
                try:
                    page.wait_for_selector(
                        'input[id="idBtn_Back"]',
                        timeout=stay_signed_in_timeout_ms,
                    )
                    page.click('input[id="idBtn_Back"]')
                except PlaywrightTimeoutError:
                    pass

                # Give SharePoint enough time to set auth cookies.
                if after_login_wait_seconds > 0:
                    time.sleep(after_login_wait_seconds)

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
                raise SharePointLoginTimeoutError("\n".join(msg_parts)) from exc
            except Exception as exc:
                s_path, p_title, p_url, vis_err = _capture_failure_artifact(
                    page, reason="login_exception", screenshot_dir=screenshot_dir
                )
                if not isinstance(exc, (SharePointCookieAuthError,)):
                    msg = f"登入 SharePoint 時發生未預期錯誤: {exc}"
                    if s_path:
                        msg += f"\n📸 失敗畫面截圖已儲存至: {s_path}"
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
                raise SharePointCookieNotFoundError("\n".join(msg_parts))

            cookie_header = f"rtFa={rtfa};FedAuth={fedauth}"

            return SharePointCookieResult(
                cookie_header=cookie_header,
                rtFa=rtfa,
                FedAuth=fedauth,
                cookies=cookies,
                created_at=time.time(),
            )

        finally:
            if browser is not None:
                browser.close()


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
        expires_in_seconds: Optional[int] = None,
        screenshot_dir: Optional[Path | str] = None,
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
        self.expires_in_seconds = expires_in_seconds
        self.screenshot_dir = screenshot_dir
        self.metadata = dict(metadata or {})

    def get_auth_context(self) -> AuthContext:
        """
        Return a fresh AuthContext.

        This provider itself does not cache. If you want cache behavior,
        wrap this provider with auth.cache.CachedAuthProvider.
        """
        return self.refresh()

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
        )

        expires_at = None
        if self.expires_in_seconds is not None:
            expires_at = result.created_at + self.expires_in_seconds

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