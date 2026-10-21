import base64
import hashlib
import json
import os
import secrets
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from typing import Any, Dict, Optional, cast

from requests_oauthlib import OAuth2Session
from auth.base import AuthContext, AuthProvider
from auth.exceptions import AuthLoginError
from core.logging import get_logger


# 允許微軟 OAuth 授權回應附帶額外/不同排序的 Scope (例如微軟自動附加 openid, profile, email)
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

logger = get_logger("auth.onedrive")

class OAuthCallbackServer(HTTPServer):
    """HTTP server with typed OAuth callback state."""

    auth_code: str | None
    auth_error: str | None
    auth_response: str | None

    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler]):
        super().__init__(server_address, handler_class)
        self.auth_code = None
        self.auth_error = None
        self.auth_response = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """微型 HTTP 伺服器，用來捕捉瀏覽器回傳的授權碼 (Authorization Code)"""

    def do_GET(self) -> None:
        query = urlparse(self.path).query
        params = parse_qs(query)
        server = cast(OAuthCallbackServer, self.server)
        server.auth_response = f"http://localhost:8080{self.path}"
        if 'error' in params:
            server.auth_error = params.get('error_description', params['error'])[0]
        elif 'code' in params:
            server.auth_code = params['code'][0]

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        if server.auth_error:
            error_hint = ""
            if "AADSTS9002325" in server.auth_error or "Proof Key for Code Exchange" in server.auth_error:
                error_hint = """
                <div style="background-color: #fff3cd; color: #856404; padding: 16px; border-radius: 8px; margin: 20px auto; max-width: 620px; text-align: left; border: 1px solid #ffeeba; font-size: 14px; line-height: 1.6;">
                    <strong>🔍 建議解決方式 (AADSTS9002325)：</strong><br>
                    此錯誤代表 Azure AD 應用程式註冊平台類型設定有誤。<br>
                    請至 <b>Azure Portal &gt; Microsoft Entra ID &gt; 應用程式註冊 (App registrations) &gt; 驗證 (Authentication)</b>：
                    <ol style="margin-top: 8px; padding-left: 20px;">
                        <li>檢查重新導向 URI 是否被誤設在「單頁應用程式 (Single-page application)」平台中。若是，請刪除該重新導向 URI。</li>
                        <li>點擊<b>「新增平台 (Add a platform)」</b>，選擇<b>「Web (網頁)」</b>。</li>
                        <li>將重新導向 URI 設定為：<code>http://localhost:8080</code> 並儲存。</li>
                        <li>若不使用 Client Secret（公用用戶端），亦可選用「行動與傳統型應用程式 (Mobile and desktop applications)」。</li>
                    </ol>
                </div>
                """
            html_content = f"""
            <html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; text-align: center; padding-top: 40px; background-color: #f8fafc; color: #1e293b;">
            <h1 style="color: #dc2626;">❌ OneDrive 授權失敗</h1>
            <p style="color: #64748b; max-width: 620px; margin: 12px auto; word-break: break-all; font-size: 14px;">{server.auth_error}</p>
            {error_hint}
            <p style="color: #94a3b8; font-size: 13px; margin-top: 24px;">您可以關閉此視窗並回到命令列或應用程式中重試。</p>
            </body></html>
            """
            self.wfile.write(html_content.encode("utf-8"))
        else:
            self.wfile.write(
                """
                <html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; text-align: center; padding-top: 50px; background-color: #f8fafc; color: #1e293b;">
                <h1 style="color: #16a34a;">✅ 授權成功！</h1>
                <p style="color: #64748b; font-size: 14px;">您現在可以關閉這個視窗並回到應用程式了。</p>
                <script>setTimeout(window.close, 3000);</script>
                </body></html>
                """.encode("utf-8")
            )

    # 關閉預設的 log 輸出，保持終端機乾淨
    def log_message(self, format: str, *args: Any) -> None:
        return

class OneDriveAuthProvider(AuthProvider):
    provider_name = "onedrive"

    def __init__(self, client_id: str, client_secret: str, tenant: str, token_cache_path: str, metadata: Optional[Dict[str, Any]] = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant = tenant
        self.token_cache_path = token_cache_path
        self.metadata = dict(metadata or {})
        
        # 存取檔案讀寫權限與離線刷新權限
        self.scopes = ["offline_access", "Files.ReadWrite.All"]
        self.auth_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
        self.token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        
        # 由於使用 Localhost 導向，埠號需與 Azure AD 上註冊的一致 (建議註冊 http://localhost:8080)
        self.redirect_uri = "http://localhost:8080"

    def get_auth_context(self) -> AuthContext:
        return self.refresh()

    def refresh(self) -> AuthContext:
        token = None
        
        # 1. 嘗試從快取讀取
        if os.path.exists(self.token_cache_path):
            try:
                with open(self.token_cache_path, 'r') as f:
                    token = json.load(f)
            except Exception:
                pass
                
        oauth = OAuth2Session(self.client_id, scope=self.scopes, redirect_uri=self.redirect_uri)
        
        # 2. 若快取存在且過期，進行無感刷新
        if token and "refresh_token" in token:
            try:
                # requests_oauthlib 的 refresh 判斷會用到 client_id/secret
                extra = {"client_id": self.client_id}
                if self.client_secret:
                    extra["client_secret"] = self.client_secret
                    
                token = oauth.refresh_token(self.token_url, refresh_token=token["refresh_token"], **extra)
                self._save_token(token)
                return self._token_to_auth_context(token)
            except Warning as w:
                if hasattr(w, "token") and isinstance(w.token, dict):
                    token = cast(dict[str, Any], w.token)
                    self._save_token(token)
                    return self._token_to_auth_context(token)
            except Exception:
                # 刷新失敗，退回重新登入
                pass

        # 3. 若無快取或刷新失敗，啟動瀏覽器互動登入
        token = self._interactive_login(oauth)
        self._save_token(token)
        return self._token_to_auth_context(token)

    def _interactive_login(self, oauth: OAuth2Session) -> dict[str, Any]:
        logger.info("準備啟動 OneDrive Microsoft Graph 授權登入流程")

        # PKCE (RFC 7636): 生成 code_verifier 與 code_challenge (S256)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .decode("ascii")
            .rstrip("=")
        )

        authorization_url, state = oauth.authorization_url(
            self.auth_url,
            prompt="select_account",
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )
        
        server = OAuthCallbackServer(('localhost', 8080), OAuthCallbackHandler)
        
        logger.info("已開啟瀏覽器，等待 OneDrive 登入與授權")
        webbrowser.open(authorization_url)
        
        # 啟動伺服器等待回呼。fetch_token 會用完整 callback URL 驗證 state，
        # 避免 authorization code 被其他瀏覽器 session 注入。
        while not server.auth_code and not server.auth_error:
            server.handle_request()

        try:
            if server.auth_error:
                error_msg = server.auth_error
                if "AADSTS9002325" in error_msg or "Proof Key for Code Exchange" in error_msg:
                    error_msg += (
                        "\n[診斷建議] 此錯誤通常是因為 Azure AD (Microsoft Entra ID) 應用程式註冊的重新導向 URI 設定在「單頁應用程式 (SPA)」平台。"
                        "\n請至 Azure Portal > 應用程式註冊 (App registrations) > 驗證 (Authentication)："
                        "\n1. 移除「單頁應用程式 (Single-page application)」平台下的 http://localhost:8080"
                        "\n2. 點擊「新增平台」選擇「Web (網頁)」，並填入重新導向 URI: http://localhost:8080"
                        "\n3. 若不使用 Client Secret，亦可改選「行動與傳統型應用程式 (Mobile and desktop applications)」。"
                    )
                raise AuthLoginError(
                    f"Microsoft OAuth 授權失敗: {error_msg}"
                )

            code = server.auth_code
            logger.info("已接收 OneDrive 授權碼，正在兌換 token")

            extra_token_args: dict[str, Any] = {
                "code_verifier": code_verifier,
            }
            if self.client_secret:
                extra_token_args["client_secret"] = self.client_secret

            try:
                token = oauth.fetch_token(
                    self.token_url,
                    code=code,
                    include_client_id=True,
                    authorization_response=server.auth_response,
                    **extra_token_args,
                )
                if not isinstance(token, dict):
                    raise AuthLoginError("Microsoft OAuth token response 格式無效。")
                return cast(dict[str, Any], token)
            except Warning as w:
                if hasattr(w, "token") and isinstance(w.token, dict):
                    logger.info("微軟回應包含調整後之 Scope，已接受並完成授權")
                    return cast(dict[str, Any], w.token)
                raise AuthLoginError(f"兌換 Token 失敗: {w}") from w
            except Exception as e:
                raise AuthLoginError(f"兌換 Token 失敗: {e}") from e
        finally:
            server.server_close()

    def _save_token(self, token: dict[str, Any]) -> None:
        cache_path = os.path.abspath(os.path.expanduser(self.token_cache_path))
        cache_dir = os.path.dirname(cache_path)
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(cache_dir, 0o700)
        except OSError:
            pass

        fd, temp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(cache_path)}.",
            suffix=".tmp",
            dir=cache_dir,
            text=True,
        )
        try:
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(token, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, cache_path)
            try:
                os.chmod(cache_path, 0o600)
            except OSError:
                pass
        finally:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass

    def _token_to_auth_context(self, token: dict[str, Any]) -> AuthContext:
        merged_metadata = {
            "provider": self.provider_name,
            "auth_type": "oauth2",
        }
        merged_metadata.update(self.metadata)

        return AuthContext(
            headers={
                "Authorization": f"Bearer {token['access_token']}"
            },
            expires_at=token.get("expires_at"),
            metadata=merged_metadata
        )