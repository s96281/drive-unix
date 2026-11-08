"""Tests for per-identity persistent browser profiles (SharePoint cookie auth)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import auth.providers.sharepoint_cookie as sharepoint_cookie
from auth.providers.sharepoint_cookie import (
    DEFAULT_BROWSER_PROFILE_ROOT,
    SharePointCookieProvider,
    _is_kmsi_prompt,
    _prepare_profile_dir,
    _probe_sharepoint_session,
    _try_reuse_persisted_session,
    get_identity_profile_dir,
    get_cookie,
    resolve_browser_profile_root,
)


# ---------------------------------------------------------------------------
# Profile path resolution
# ---------------------------------------------------------------------------


def test_resolve_browser_profile_root_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DRIVE_UNIX_BROWSER_PROFILE_DIR", raising=False)
    monkeypatch.delenv("DRIVE_UNIX_BROWSER_PROFILE_ENABLED", raising=False)

    assert resolve_browser_profile_root() == DEFAULT_BROWSER_PROFILE_ROOT


def test_resolve_browser_profile_root_custom(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DRIVE_UNIX_BROWSER_PROFILE_DIR", str(tmp_path / "profiles"))

    assert resolve_browser_profile_root() == tmp_path / "profiles"


@pytest.mark.parametrize("value", ["0", "false", "off", "no", "disabled"])
def test_resolve_browser_profile_root_disabled_by_dir_value(
    monkeypatch: pytest.MonkeyPatch, value: str
):
    monkeypatch.setenv("DRIVE_UNIX_BROWSER_PROFILE_DIR", value)

    assert resolve_browser_profile_root() is None


def test_resolve_browser_profile_root_disabled_by_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DRIVE_UNIX_BROWSER_PROFILE_DIR", raising=False)
    monkeypatch.setenv("DRIVE_UNIX_BROWSER_PROFILE_ENABLED", "false")

    assert resolve_browser_profile_root() is None


def test_get_identity_profile_dir_is_per_identity(tmp_path: Path):
    key_a = "ea1994807d17da0d0974ad4fb0b04985f640c3c3ccd578100ede1668d987f506"
    key_b = "552e1ddf5c4e961abfb518f8a51235eb0e5f0644151c1570270609df879614b6"

    dir_a = get_identity_profile_dir(key_a, root=tmp_path)
    dir_b = get_identity_profile_dir(key_b, root=tmp_path)

    assert dir_a == tmp_path / key_a
    assert dir_b == tmp_path / key_b
    assert dir_a != dir_b


def test_get_identity_profile_dir_disabled_or_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DRIVE_UNIX_BROWSER_PROFILE_DIR", "off")

    assert get_identity_profile_dir("abc") is None
    assert get_identity_profile_dir("", root=Path("/tmp")) is None


def test_prepare_profile_dir_creates_directory(tmp_path: Path):
    target = tmp_path / "profiles" / "identity"

    prepared = _prepare_profile_dir(target)

    assert prepared == target
    assert target.is_dir()
    assert _prepare_profile_dir(None) is None


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _cookie(name: str, value: str, expires: float = -1) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "domain": "contoso.sharepoint.com",
        "path": "/",
        "expires": expires,
    }


def _auth_cookies(rtfa: str = "fresh-rtfa", fedauth: str = "fresh-fed") -> list[dict[str, Any]]:
    return [_cookie("rtFa", rtfa, 4_102_444_800), _cookie("FedAuth", fedauth, 4_102_444_800)]


class _FakeLocator:
    def __init__(self, *, visible: bool = False) -> None:
        self._visible = visible
        self._count = 1 if visible else 0
        self.first = self
        self.clicks = 0
        self.filled: list[str] = []

    def count(self) -> int:
        return self._count

    def is_visible(self) -> bool:
        return self._visible

    def inner_text(self) -> str:
        return ""

    def click(self, **kwargs: Any) -> None:
        self.clicks += 1

    def fill(self, value: str, **kwargs: Any) -> None:
        self.filled.append(value)

    def nth(self, index: int) -> "_FakeLocator":
        return self


class _FakeResponse:
    def __init__(self, status: int, url: str) -> None:
        self.status = status
        self.url = url


class _FakeRequest:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(url)
        return self._response


class _FakePage:
    def __init__(self, locators: dict[str, _FakeLocator] | None = None) -> None:
        self.url = "https://login.microsoftonline.com/common/login"
        self.visited: list[str] = []
        self.screenshots = 0
        self.submit_clicks = 0
        self.on_login_cookies: list[dict[str, Any]] = []
        self._locators = locators or {}
        self._context: "_FakeContext | None" = None

    def goto(self, url: str, **kwargs: Any) -> None:
        self.visited.append(url)
        self.url = "https://login.microsoftonline.com/common/login"

    def locator(self, selector: str) -> _FakeLocator:
        return self._locators.get(selector, _FakeLocator(visible=False))

    def fill(self, selector: str, value: str, **kwargs: Any) -> None:
        self._locators.setdefault(selector, _FakeLocator(visible=True)).fill(value)

    def click(self, selector: str, **kwargs: Any) -> None:
        self._locators.setdefault(selector, _FakeLocator(visible=True)).click()
        if selector != 'input[type="submit"]':
            return
        self.submit_clicks += 1
        if self.submit_clicks >= 2:
            # After the password submit the browser lands back on SharePoint and
            # SharePoint issues a new cookie pair.
            self.url = "https://contoso.sharepoint.com/SitePages/Home.aspx"
            if self._context is not None:
                self._context.jar = list(self.on_login_cookies)

    def screenshot(self, **kwargs: Any) -> None:
        self.screenshots += 1

    def title(self) -> str:
        return "Sign in to your account"

    def content(self) -> str:
        return "<html></html>"

    def wait_for_timeout(self, ms: int) -> None:
        return None


class _FakeContext:
    def __init__(
        self,
        jar: list[dict[str, Any]],
        *,
        probe: _FakeResponse | None = None,
    ) -> None:
        self.jar = list(jar)
        self.page = _FakePage()
        self.page._context = self
        self.request = _FakeRequest(
            probe or _FakeResponse(200, "https://contoso.sharepoint.com")
        )
        self.cleared: list[dict[str, Any]] = []
        self.closed = False

    @property
    def pages(self) -> list[_FakePage]:
        return [self.page]

    def cookies(self) -> list[dict[str, Any]]:
        return list(self.jar)

    def clear_cookies(self, **filters: Any) -> None:
        self.cleared.append(filters)
        self.jar = [
            cookie
            for cookie in self.jar
            if not all(
                cookie.get(key) == value
                for key, value in filters.items()
                if value is not None
            )
        ]

    def new_page(self) -> _FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, context: _FakeContext) -> None:
        self._context = context
        self.closed = False

    def new_context(self) -> _FakeContext:
        return self._context

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, context: _FakeContext) -> None:
        self._context = context
        self.persistent_calls: list[tuple[str, dict[str, Any]]] = []
        self.launch_calls = 0

    def launch_persistent_context(self, path: str, **kwargs: Any) -> _FakeContext:
        self.persistent_calls.append((path, kwargs))
        return self._context

    def launch(self, **kwargs: Any) -> _FakeBrowser:
        self.launch_calls += 1
        return _FakeBrowser(self._context)


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium

    def __enter__(self) -> "_FakePlaywright":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


def _install_fake_playwright(
    monkeypatch: pytest.MonkeyPatch, context: _FakeContext
) -> _FakeChromium:
    chromium = _FakeChromium(context)
    monkeypatch.setattr(
        sharepoint_cookie,
        "sync_playwright",
        lambda: _FakePlaywright(chromium),
    )
    monkeypatch.setattr(sharepoint_cookie.time, "sleep", lambda seconds: None)
    return chromium


# ---------------------------------------------------------------------------
# Session probe / reuse
# ---------------------------------------------------------------------------


def test_probe_sharepoint_session_ok():
    context = _FakeContext(
        [],
        probe=_FakeResponse(200, "https://contoso.sharepoint.com/_api/web/currentuser"),
    )

    assert _probe_sharepoint_session(context, "https://contoso.sharepoint.com/") is True
    assert context.request.calls == ["https://contoso.sharepoint.com/_api/web/currentuser"]


def test_probe_sharepoint_session_rejects_unauthorized():
    context = _FakeContext(
        [],
        probe=_FakeResponse(401, "https://contoso.sharepoint.com/_api/web/currentuser"),
    )

    assert _probe_sharepoint_session(context, "https://contoso.sharepoint.com") is False


def test_probe_sharepoint_session_rejects_login_redirect():
    context = _FakeContext(
        [],
        probe=_FakeResponse(200, "https://login.microsoftonline.com/common/oauth2/authorize"),
    )

    assert _probe_sharepoint_session(context, "https://contoso.sharepoint.com") is False


def test_try_reuse_requires_both_cookies():
    context = _FakeContext([{"name": "rtFa", "value": "x"}])

    assert _try_reuse_persisted_session(context, "https://contoso.sharepoint.com") is None


def test_try_reuse_returns_cookies_when_session_valid():
    cookies = _auth_cookies()
    context = _FakeContext(cookies)

    assert _try_reuse_persisted_session(context, "https://contoso.sharepoint.com") == cookies


# ---------------------------------------------------------------------------
# get_cookie integration with a persistent profile
# ---------------------------------------------------------------------------


def test_get_cookie_reuses_persisted_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cookies = _auth_cookies("saved-rtfa", "saved-fed")
    context = _FakeContext(cookies)
    chromium = _install_fake_playwright(monkeypatch, context)
    profile_dir = tmp_path / "profiles" / "identity"

    result = get_cookie(
        "https://contoso.sharepoint.com",
        "user@contoso.com",
        "secret",
        profile_dir=profile_dir,
    )

    assert result.rtFa == "saved-rtfa"
    assert result.FedAuth == "saved-fed"
    assert result.profile_dir == str(profile_dir)
    assert result.cookie_header == "rtFa=saved-rtfa;FedAuth=saved-fed"
    # No login navigation happened.
    assert context.page.visited == []
    assert context.cleared == []
    # Persistent context launched with the identity profile directory.
    assert chromium.persistent_calls[0][0] == str(profile_dir)
    assert chromium.launch_calls == 0
    assert profile_dir.is_dir()
    assert context.closed is True


def test_get_cookie_stale_profile_falls_back_to_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    stale = _auth_cookies("stale-rtfa", "stale-fed")
    context = _FakeContext(stale, probe=_FakeResponse(403, "https://contoso.sharepoint.com/_api/web/currentuser"))
    context.page._locators = _login_locators()
    context.page.on_login_cookies = _auth_cookies("fresh-rtfa", "fresh-fed")
    _install_fake_playwright(monkeypatch, context)

    result = get_cookie(
        "https://contoso.sharepoint.com",
        "user@contoso.com",
        "secret",
        profile_dir=tmp_path / "profile",
        screenshot_dir=tmp_path / "debug",
    )

    assert result.rtFa == "fresh-rtfa"
    assert result.FedAuth == "fresh-fed"
    # Stale cookies were removed before the new login.
    cleared_names = {entry.get("name") for entry in context.cleared}
    assert cleared_names == {"rtFa", "FedAuth"}
    assert context.page.visited == ["https://contoso.sharepoint.com"]


def test_get_cookie_force_login_skips_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    context = _FakeContext(_auth_cookies("stale-rtfa", "stale-fed"))
    context.page._locators = _login_locators()
    context.page.on_login_cookies = _auth_cookies("new-rtfa", "new-fed")
    _install_fake_playwright(monkeypatch, context)

    result = get_cookie(
        "https://contoso.sharepoint.com",
        "user@contoso.com",
        "secret",
        profile_dir=tmp_path / "profile",
        force_login=True,
        screenshot_dir=tmp_path / "debug",
    )

    assert result.rtFa == "new-rtfa"
    assert context.page.visited == ["https://contoso.sharepoint.com"]


def test_get_cookie_without_profile_uses_temporary_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    context = _FakeContext([])
    context.page._locators = _login_locators()
    context.page.on_login_cookies = _auth_cookies()
    chromium = _install_fake_playwright(monkeypatch, context)

    result = get_cookie(
        "https://contoso.sharepoint.com",
        "user@contoso.com",
        "secret",
        screenshot_dir=tmp_path / "debug",
    )

    assert result.rtFa == "fresh-rtfa"
    assert result.profile_dir is None
    assert chromium.launch_calls == 1
    assert chromium.persistent_calls == []
    assert context.request.calls == []
    assert context.cleared == []


def test_locked_profile_falls_back_to_temporary_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    context = _FakeContext([])
    context.page._locators = _login_locators()
    context.page.on_login_cookies = _auth_cookies()

    class _LockedChromium(_FakeChromium):
        def launch_persistent_context(self, path: str, **kwargs: Any) -> _FakeContext:
            self.persistent_calls.append((path, kwargs))
            raise RuntimeError(
                "ProcessSingleton: SingletonLock already exists in the user data directory"
            )

    chromium = _LockedChromium(context)
    monkeypatch.setattr(
        sharepoint_cookie,
        "sync_playwright",
        lambda: _FakePlaywright(chromium),
    )
    monkeypatch.setattr(sharepoint_cookie.time, "sleep", lambda seconds: None)

    result = get_cookie(
        "https://contoso.sharepoint.com",
        "user@contoso.com",
        "secret",
        profile_dir=tmp_path / "profile",
        screenshot_dir=tmp_path / "debug",
    )

    # The profile was locked, so the login ran in a temporary context and the
    # result must not claim to be persisted.
    assert chromium.persistent_calls[0][0] == str(tmp_path / "profile")
    assert chromium.launch_calls == 1
    assert result.rtFa == "fresh-rtfa"
    assert result.profile_dir is None


def _login_locators() -> dict[str, _FakeLocator]:
    return {
        'input[type="email"]': _FakeLocator(visible=True),
        'input[type="password"]': _FakeLocator(visible=True),
        'input[id="idBtn_Back"]': _FakeLocator(visible=True),
        'input[id="idSIButton9"]': _FakeLocator(visible=True),
        "#kmsiTitle": _FakeLocator(visible=True),
    }


def test_persistent_profile_answers_yes_to_kmsi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    context = _FakeContext([])
    context.page._locators = _login_locators()
    context.page.on_login_cookies = _auth_cookies()
    _install_fake_playwright(monkeypatch, context)

    get_cookie(
        "https://contoso.sharepoint.com",
        "user@contoso.com",
        "secret",
        profile_dir=tmp_path / "profile",
        screenshot_dir=tmp_path / "debug",
    )

    assert context.page._locators['input[id="idSIButton9"]'].clicks >= 1
    assert context.page._locators['input[id="idBtn_Back"]'].clicks == 0


def test_temporary_context_keeps_kmsi_no_behaviour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    context = _FakeContext([])
    context.page._locators = _login_locators()
    context.page.on_login_cookies = _auth_cookies()
    _install_fake_playwright(monkeypatch, context)

    get_cookie(
        "https://contoso.sharepoint.com",
        "user@contoso.com",
        "secret",
        screenshot_dir=tmp_path / "debug",
    )

    assert context.page._locators['input[id="idBtn_Back"]'].clicks >= 1
    assert context.page._locators['input[id="idSIButton9"]'].clicks == 0


# ---------------------------------------------------------------------------
# Provider wiring
# ---------------------------------------------------------------------------


def test_provider_passes_profile_dir_and_uses_real_cookie_expiry(tmp_path: Path):
    provider = SharePointCookieProvider(
        base_url="https://contoso.sharepoint.com",
        email="user@contoso.com",
        password="secret",
        profile_dir=tmp_path / "profile",
        expires_in_seconds=86_400,
    )

    assert provider.profile_dir == tmp_path / "profile"
    assert provider.reuse_existing_session is True
    assert provider.force_login is False


def test_provider_reset_profile(tmp_path: Path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "Cookies").write_text("x", encoding="utf-8")

    provider = SharePointCookieProvider(
        base_url="https://contoso.sharepoint.com",
        email="user@contoso.com",
        password="secret",
        profile_dir=profile_dir,
    )

    assert provider.reset_profile() is True
    assert not profile_dir.exists()
    assert provider.reset_profile() is False


def test_is_kmsi_prompt_detection():
    page = _FakePage({"#kmsiTitle": _FakeLocator(visible=True)})
    assert _is_kmsi_prompt(page) is True

    page = _FakePage({'input[id="idBtn_Back"]': _FakeLocator(visible=True)})
    assert _is_kmsi_prompt(page) is True

    page = _FakePage()
    assert _is_kmsi_prompt(page) is False
