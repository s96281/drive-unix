"""
Get the cookie to access Sharepoint drive.
"""
import base64
import json
import os
import time
import random
import re
import sys
from http.cookiejar import CookieJar
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import build_opener, HTTPCookieProcessor, Request, urlopen
import xml.etree.ElementTree as ET
from office365.runtime.auth.user_credential import UserCredential
from office365.sharepoint.client_context import ClientContext
from module import config, functions

# 獲取使用者Cookie
# 作者：Krzysztof Nowicki
# 修改：Henry Yo
AUTHXMLMANAGED = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
      xmlns:a="http://www.w3.org/2005/08/addressing"
      xmlns:u="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
  <s:Header>
    <a:Action s:mustUnderstand="1">http://schemas.xmlsoap.org/ws/2005/02/trust/RST/Issue</a:Action>
    <a:ReplyTo>
      <a:Address>http://www.w3.org/2005/08/addressing/anonymous</a:Address>
    </a:ReplyTo>
    <a:To s:mustUnderstand="1">https://login.microsoftonline.com/extSTS.srf</a:To>
    <o:Security s:mustUnderstand="1"
       xmlns:o="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
      <o:UsernameToken>
        <o:Username>{0}</o:Username>
        <o:Password>{1}</o:Password>
      </o:UsernameToken>
    </o:Security>
  </s:Header>
  <s:Body>
    <t:RequestSecurityToken xmlns:t="http://schemas.xmlsoap.org/ws/2005/02/trust">
      <wsp:AppliesTo xmlns:wsp="http://schemas.xmlsoap.org/ws/2004/09/policy">
        <a:EndpointReference>
          <a:Address>{2}</a:Address>
        </a:EndpointReference>
      </wsp:AppliesTo>
      <t:KeyType>http://schemas.xmlsoap.org/ws/2005/05/identity/NoProofKey</t:KeyType>
      <t:RequestType>http://schemas.xmlsoap.org/ws/2005/02/trust/Issue</t:RequestType>
      <t:TokenType>urn:oasis:names:tc:SAML:1.0:assertion</t:TokenType>
    </t:RequestSecurityToken>
  </s:Body>
</s:Envelope>
"""

AUTHXMLFEDERATED = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
      xmlns:a="http://www.w3.org/2005/08/addressing"
      xmlns:u="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
      xmlns:p="http://schemas.xmlsoap.org/ws/2004/09/policy">
  <s:Header>
    <a:Action s:mustUnderstand="1">http://schemas.xmlsoap.org/ws/2005/02/trust/RST/Issue</a:Action>
    <a:To s:mustUnderstand="1">{0}</a:To>
    <a:ReplyTo>
      <a:Address>http://www.w3.org/2005/08/addressing/anonymous</a:Address>
    </a:ReplyTo>
    <o:Security s:mustUnderstand="1"
                xmlns:o="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
      <u:Timestamp u:Id="_0">
        <u:Created>{1}</u:Created>
        <u:Expires>{2}</u:Expires>
      </u:Timestamp>
      <o:UsernameToken>
        <o:Username>{3}</o:Username>
        <o:Password>{4}</o:Password>
        <o:Nonce>{5}</o:Nonce>
        <u:Created>{1}</u:Created>
      </o:UsernameToken>
    </o:Security>
  </s:Header>
  <s:Body>
    <t:RequestSecurityToken xmlns:t="http://schemas.xmlsoap.org/ws/2005/02/trust">
      <p:AppliesTo>
        <a:EndpointReference>
          <a:Address>urn:federation:MicrosoftOnline</a:Address>
        </a:EndpointReference>
      </p:AppliesTo>
      <t:KeyType>http://schemas.xmlsoap.org/ws/2005/05/identity/NoProofKey</t:KeyType>
      <t:RequestType>http://schemas.xmlsoap.org/ws/2005/02/trust/Issue</t:RequestType>
    </t:RequestSecurityToken>
  </s:Body>
</s:Envelope>
"""

AUTHXMLFEDERATED2 = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
      xmlns:o="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
      xmlns:p="http://schemas.xmlsoap.org/ws/2004/09/policy"
      xmlns:a="http://www.w3.org/2005/08/addressing"
      xmlns:t="http://schemas.xmlsoap.org/ws/2005/02/trust">
  <s:Header>
    <a:Action s:mustUnderstand="1">http://schemas.xmlsoap.org/ws/2005/02/trust/RST/Issue</a:Action>
    <a:To s:mustUnderstand="1">https://login.microsoftonline.com/rst2.srf</a:To>
    <ps:AuthInfo xmlns:ps="http://schemas.microsoft.com/LiveID/SoapServices/v1" Id="PPAuthInfo">
      <ps:BinaryVersion>5</ps:BinaryVersion>
      <ps:HostingApp>Managed IDCRL</ps:HostingApp>
    </ps:AuthInfo>
    <o:Security>
    {}
    </o:Security>
  </s:Header>
  <s:Body>
    <t:RequestSecurityToken Id="RST0">
      <t:RequestType>http://schemas.xmlsoap.org/ws/2005/02/trust/Issue</t:RequestType>
      <p:AppliesTo>
        <a:EndpointReference>
          <a:Address>sharepoint.com</a:Address>
        </a:EndpointReference>
      </p:AppliesTo>
      <p:PolicyReference URI="MBI"/>
    </t:RequestSecurityToken>
  </s:Body>
</s:Envelope>
"""


def discover_sts(username: str) -> str | None:
    """
    Discover the security token service (STS) URL for a given username
    in a Microsoft federated authentication environment.

    Args:
        username (str): The username to discover the STS URL for.

    Returns:
        str or None: The STS URL as a string, or None if the namespace type
        is not "Federated" or if the STS URL is missing from the response XML.

    Raises:
        RuntimeError: If the GetUserRealm response XML is missing either the "NameSpaceType"
        or "STSAuthURL" elements, or if the "NameSpaceType" element has an unexpected value.

    Example usage:
        >>> sts_url = discover_sts('johndoe@example.com')
    """
    with urlopen("https://login.microsoft.com/GetUserRealm.srf",
                 f"login={username}&xml=1".encode('utf-8')) as request:
        resp = ET.parse(request)
    nstype = resp.find("./NameSpaceType")
    if nstype is None:
        raise RuntimeError(
            "Invalid GetUserRealm response - missing namespace type")
    if nstype.text == "Federated":
        stsurl = resp.find("./STSAuthURL")
        if stsurl is None:
            raise RuntimeError(
                "Invalid GetUserRealm response - missing STS URL")
        if stsurl.text is None:
            raise RuntimeError(
                "Invalid GetUserRealm response - missing STS URL")
        return stsurl.text
    return None


def build_authxmlmanaged(username: str, password: str, endpoint: str) -> str:
    """
    Build an authentication XML string with a managed identity token for
    a given username and password, to be used in SharePoint requests.

    Args:
        username (str): The username to include in the XML.
        password (str): The password to include in the XML.
        endpoint (str): The SharePoint site endpoint to include in the XML.

    Returns:
        str: The authentication XML string,
            formatted with the given username, password, and endpoint.

    Example usage:
        >>> xml_str = build_authxmlmanaged(
                'johndoe@example.com', 'mypassword', 'https://example.sharepoint.com'
            )
    """
    return AUTHXMLMANAGED.format(username, password, endpoint)


def get_security_token_managed(username: str, password: str,
                               endpoint: str) -> str:
    """
    Gets a security token using the given username, password, and endpoint.

    Args:
        username (str): The username to authenticate with.
        password (str): The password to authenticate with.
        endpoint (str): The endpoint to request the token from.

    Returns:
        str: The security token.

    Raises:
        RuntimeError: If the login request fails or the authentication token cannot be extracted.

    """
    auth_req = build_authxmlmanaged(username, password, endpoint)
    try:
        with urlopen("https://login.microsoftonline.com/extSTS.srf",
                     auth_req.encode('utf-8')) as request:
            auth_resp_tree = ET.parse(request)
    except URLError as esc:
        raise RuntimeError("Failed to send login request.") from esc
    n_s = {
        "soap":
        "http://www.w3.org/2003/05/soap-envelope",
        "wssec":
        "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
    }
    auth_token = None
    fault = auth_resp_tree.find(".//soap:Fault", n_s)
    if fault is not None:
        reason = fault.find("soap:Reason/soap:Text", n_s)
        if reason is not None:
            reason = reason.text
        else:
            reason = "*Unknown reason*"
        raise RuntimeError(
            f"Railed to retrieve authentication token: {reason}")
    token_elm = auth_resp_tree.find(".//wssec:BinarySecurityToken", n_s)
    if token_elm is None:
        raise RuntimeError("Failed to extract authentication token.")
    auth_token = token_elm.text
    if auth_token is None:
        raise RuntimeError("Failed to extract authentication token.")
    return auth_token


def build_authxmlfederated(username: str, password: str, stsurl: str) -> str:
    """
    Builds a SAML authentication request for federated authentication.

    Args:
        username (str): The username for the user to authenticate.
        password (str): The password for the user to authenticate.
        stsurl (str): The URL for the Security Token Service (STS) to use for authentication.

    Returns:
        str: The SAML authentication request as an XML string.
    """
    timestamp = time.time()
    ctime = time.gmtime(timestamp)
    etime = time.gmtime(timestamp + 1 * 60)
    ctime_str = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", ctime)
    etime_str = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", etime)
    nonce = base64.standard_b64encode(
        bytearray(random.getrandbits(8) for _ in range(32)))
    return AUTHXMLFEDERATED.format(stsurl, ctime_str, etime_str, username,
                                   password, nonce.decode('utf-8'))


def build_authxmlfederated2(assertion: str) -> str:
    """
    Builds an XML string containing the assertion required for federated authentication.

    Args:
        assertion (str): The assertion required for federated authentication.

    Returns:
        str: The XML string containing the assertion.

    """
    return AUTHXMLFEDERATED2.format(assertion)


def get_security_token_federated(username: str, password: str,
                                 stsurl: str) -> str | None:
    """
    Retrieves a security token for a federated authentication scenario.

    Args:
        username (str): The user's username.
        password (str): The user's password.
        stsurl (str): The Security Token Service (STS) URL.

    Returns:
        str: The security token, represented as a Base64-encoded string,
            or None if the token could not be retrieved.

    Raises:
        RuntimeError: If the login request failed or
            if the authentication token could not be retrieved.

    The function sends a login request to the specified STS URL,
    passing the user's credentials in an XML format.
    It extracts the SAML assertion from the response and
    sends a second request to retrieve the authentication token.
    The token is returned as a Base64-encoded string.

    If the login request fails or if the authentication token cannot be retrieved,
    the function raises a RuntimeError with a corresponding error message.
    """
    auth_req = build_authxmlfederated(username, password, stsurl)
    try:
        req = Request(stsurl, auth_req.encode('utf-8'),
                      {"Content-Type": "application/soap+xml; charset=utf-8"})
        with urlopen(req) as request:
            text = request.read()
    # pylint: disable=unused-variable
    except URLError as esc:
        raise RuntimeError("Failed to send login request.") from esc
    n_s = {
        "soap": "http://www.w3.org/2003/05/soap-envelope",
        "wssec": "http://docs.oasis-open.org/wss/2004/01/\
           oasis-200401-wss-wssecurity-secext-1.0.xsd",
        "saml": "urn:oasis:names:tc:SAML:1.0:assertion"
    }
    match = re.search(r"<saml:Assertion .*</saml:Assertion>",
                      text.decode('utf-8'))
    if match is None:
        return None
    auth_req2 = build_authxmlfederated2(match.group(0))
    try:
        req = Request("https://login.microsoftonline.com/rst2.srf",
                      auth_req2.encode('utf-8'),
                      {"Content-Type": "application/soap+xml; charset=utf-8"})
        request = urlopen(req)
    except URLError as esc:
        raise RuntimeError("Failed to send login request.") from esc
    auth_resp_tree = ET.parse(request)
    fault = auth_resp_tree.find(".//soap:Fault", n_s)
    if fault is not None:
        reason = fault.find("soap:Reason/soap:Text", n_s)
        if reason is not None:
            reason = reason.text
        else:
            reason = "*Unknown reason*"
        raise RuntimeError("Railed to retrieve authentication token: {reason}")
    token_elm = auth_resp_tree.find(".//wssec:BinarySecurityToken", n_s)
    if token_elm is None:
        raise RuntimeError("Failed to extract authentication token.")
    return token_elm.text


def get_cookie_backup(endpoint: str, username: str, password: str) -> str:
    """
    Obtains the authentication cookies needed to access a SharePoint site using Microsoft Graph API.

    Args:
        endpoint (str): The endpoint URL of the SharePoint site.
        username (str): The username used for authentication.
        password (str): The password used for authentication.

    Returns:
        str: A string containing the required authentication cookies in the format
            "rtFa=value; FedAuth=value".

    Raises:
        ValueError: If any of the input arguments are empty or None.
        ClientRequestError: If an error occurs while executing the request
            to obtain the authentication cookies.
    """
    user_credentials = UserCredential(username, password)
    ctx = ClientContext(endpoint).with_credentials(user_credentials)
    ctx.load(ctx.web)
    ctx.execute_query()
    cookie_str = 'rtFa=' + vars(
        vars(vars(ctx)['_auth_context'])
        ['_provider'])['_cached_auth_cookies']['rtFa'] + '; FedAuth=' + vars(
            vars(vars(ctx)['_auth_context'])
            ['_provider'])['_cached_auth_cookies']['FedAuth']
    return cookie_str


def get_cookie(endpoint: str, username: str, password: str) -> str | None:
    """
    Returns a cookie string for a SharePoint site, authenticated with the given
    credentials.

    Args:
    - endpoint (str): The URL of the SharePoint site to authenticate with.
    - username (str): The username to use for authentication.
    - password (str): The password to use for authentication.

    Returns:
    - str: A cookie string if authentication was successful.
    - None: If authentication was not successful.
    """
    stsurl = discover_sts(username)
    try:
        if stsurl is None:
            auth_token = get_security_token_managed(username, password,
                                                    endpoint)
        else:
            auth_token = get_security_token_federated(username, password,
                                                      stsurl)
    except RuntimeError as esc:
        functions.log("ERROR", str(esc))
        return get_cookie_backup(endpoint, username, password)
    endpoint_url = urlparse(endpoint)
    if endpoint_url.scheme not in ["http", "https"] or not endpoint_url.netloc:
        functions.log("ERROR", f"Invalid endpoint URL: {endpoint}")
        sys.exit(1)
    cookiejar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookiejar))
    try:
        request = Request(
            f"{endpoint_url.scheme}://{endpoint_url.netloc}/_forms/default.aspx?wa=wsignin1.0"
        )
        if auth_token is None:
            return get_cookie_backup(endpoint, username, password)
        opener.open(request, data=auth_token.encode('utf-8'))
        cookie_str = ""
        cookies_found = []
        for cookie in cookiejar:
            if cookie.name in ("FedAuth", "rtFa"):
                if cookie.value is None:
                    return None
                cookie_str += cookie.name + "=" + cookie.value + "; "
                cookies_found.append(cookie.name)
        if "FedAuth" not in cookies_found or "rtFa" not in cookies_found:
            functions.log("ERROR", "Incomplete cookies retrieved.")
            sys.exit(1)
        return cookie_str
    except URLError:
        return get_cookie_backup(endpoint, username, password)


def read_cookie(endpoint: str, username: str, password: str) -> str:
    """
    Reads and retrieves a user's authentication cookie for
    a given endpoint using their username and password.

    Args:
        endpoint (str): The endpoint URL to retrieve the cookie from.
        username (str): The username of the user whose cookie is being retrieved.
        password (str): The password of the user whose cookie is being retrieved.

    Returns:
        str: The authentication cookie for the specified user and endpoint.

    Raises:
        N/A

    Example:
        read_cookie('https://example.com', 'johndoe', 'password123')
    """
    functions.log("INFO", '讀取憑證中...')
    if os.path.isfile(config.COOKIES_LOCATION):
        functions.log("INFO", '存在憑證資料...')
        with open(config.COOKIES_LOCATION, 'r', encoding='utf-8') as file:
            cookies = json.loads(file.read())
            functions.log("INFO", '讀取憑證資料...')
        functions.log("INFO", '檢查憑證資料...')
        if username in cookies:
            functions.log("INFO", '用戶存在...')
            if cookies[username]['TIME'] < (time.time() - 86400):
                functions.log("INFO", '憑證過期...')
                time_of_now = time.time()
                cookies[username] = {
                    'cookie': get_cookie(endpoint, username, password),
                    'TIME': time_of_now
                }
                functions.log("INFO", '線上取得憑證...')
                with open(config.COOKIES_LOCATION, 'w',
                          encoding='utf-8') as file:
                    file.write(json.dumps(cookies))
                    functions.log("INFO", '寫入憑證...')
            functions.log("INFO", '成功讀取憑證')
        else:
            functions.log("INFO", '用戶不存在...')
            time_of_now = time.time()
            cookies[username] = {
                'cookie': get_cookie(endpoint, username, password),
                'TIME': time_of_now
            }
            functions.log("INFO", '線上取得憑證...')
            with open(config.COOKIES_LOCATION, 'w', encoding='utf-8') as file:
                file.write(json.dumps(cookies))
                functions.log("INFO", '寫入憑證...')
            functions.log("INFO", '成功讀取憑證')
    else:
        functions.log("INFO", '不存在憑證資料...')
        cookies = {}
        time_of_now = time.time()
        cookies[username] = {
            'cookie': get_cookie(endpoint, username, password),
            'TIME': time_of_now
        }
        functions.log("INFO", '線上取得憑證...')
        with open(config.COOKIES_LOCATION, 'w', encoding='utf-8') as file:
            file.write(json.dumps(cookies))
            functions.log("INFO", '寫入憑證...')
        functions.log("INFO", '成功讀取憑證')
    return cookies[username]['cookie']
