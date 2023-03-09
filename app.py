from __future__ import print_function
from flask import Flask, redirect, request, render_template, url_for, make_response, Markup, send_file
from flask_caching import Cache
import random
import json
import os
import time
import redis
import hashlib
import requests
import urllib.parse
import datetime
import sys
import re
import base64
import chardet
import markdown
from http.cookiejar import CookieJar
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen, build_opener, HTTPCookieProcessor, Request
import xml.etree.ElementTree as ET
from natsort import os_sorted, natsorted


DEBUG = False

# 效能分析工具
if DEBUG:
    from flask import g
    from pyinstrument import Profiler


# 設定設定檔、金鑰、快取存放位置
if os.name == 'nt':  # Windows
    CACHE_LOCATION = './cache'
    data_location = './data'
    cookies_location = './cookies'
else:  # Linux、MacOS
    data_location = './data'
    cookies_location = './cookies'
    CACHE_LOCATION = './cache'

# 如果你的資料庫擁有上萬文件，可以適當調高此參數(建議不高於5000)
REQUEST_SIZE = 2000

# 設定是否由資料庫同步資料
Redis_sync = False

# 設定資料庫
if Redis_sync:
    REDIS = redis.Redis(
        host='global-liked-dassie-31251.upstash.io',
        port='31251',
        password='585f5b3af15540d381dc46bf429a7420',
        ssl=True,
        decode_responses=True
    )
    # 設定同步資料間隔時間
    Redis_sync_expires = 432000
    # 設定資料庫鍵
    Redis_sync_key = 'HenrySharePoint'


# 設定時區
UTC = 8

# 設定快取參數
CacheConfig = {
    "DEBUG": False,
    "CACHE_TYPE": "FileSystemCache",
    "CACHE_DEFAULT_TIMEOUT": 432000,
    "CACHE_IGNORE_ERRORS": False,
    "CACHE_DIR": CACHE_LOCATION,
    "CACHE_THRESHOLD": 500
}


requests = requests.Session()
# 獲取使用者Cookie
# 作者：Krzysztof Nowicki
# 修改：Henry Yo
authXmlManaged = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
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

authXmlFederated = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
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

authXmlFederated2 = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
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


def discover_sts(username: str):
    request = urlopen("https://login.microsoft.com/GetUserRealm.srf",
                      "login={}&xml=1".format(username).encode('utf-8'))
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
        return stsurl.text
    else:
        return None


def buildAuthXmlManaged(username, password, endpoint):
    return authXmlManaged.format(username, password, endpoint)


def getSecurityTokenManaged(username, password, endpoint):
    authReq = buildAuthXmlManaged(username, password, endpoint)
    try:
        request = urlopen(
            "https://login.microsoftonline.com/extSTS.srf", authReq.encode('utf-8'))
    except URLError:
        raise RuntimeError("Failed to send login request.")
    ns = {"soap": "http://www.w3.org/2003/05/soap-envelope",
          "wssec": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"}
    authRespTree = ET.parse(request)
    authToken = None
    fault = authRespTree.find(".//soap:Fault", ns)
    if fault is not None:
        reason = fault.find("soap:Reason/soap:Text", ns)
        if reason is not None:
            reason = reason.text
        else:
            reason = "*Unknown reason*"
        raise RuntimeError(
            "Railed to retrieve authentication token: {}".format(reason))
    tokenElm = authRespTree.find(".//wssec:BinarySecurityToken", ns)
    if tokenElm is None:
        raise RuntimeError("Failed to extract authentication token.")
    else:
        authToken = tokenElm.text
    return authToken


def buildAuthXmlFederated(username, password, stsurl):
    timestamp = time.time()
    ctime = time.gmtime(timestamp)
    etime = time.gmtime(timestamp + 1 * 60)
    ctime_str = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", ctime)
    etime_str = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", etime)
    nonce = base64.standard_b64encode(
        bytearray(random.getrandbits(8) for _ in range(32)))
    return authXmlFederated.format(stsurl, ctime_str, etime_str, username, password, nonce.decode('utf-8'))


def buildAuthXmlFederated2(assertion):
    return authXmlFederated2.format(assertion)


def getSecurityTokenFederated(username, password, endpoint, stsurl):
    authReq = buildAuthXmlFederated(username, password, stsurl)
    try:
        req = Request(stsurl, authReq.encode('utf-8'),
                      {"Content-Type": "application/soap+xml; charset=utf-8"})
        request = urlopen(req)
    # pylint: disable=unused-variable
    except URLError as x:
        raise RuntimeError("Failed to send login request.")
    ns = {"soap": "http://www.w3.org/2003/05/soap-envelope",
          "wssec": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd",
          "saml": "urn:oasis:names:tc:SAML:1.0:assertion"}
    # The assertion must be copied into the second request as-is without any processing as it contains a signature.
    text = request.read()
    match = re.search(r"<saml:Assertion .*</saml:Assertion>",
                      text.decode('utf-8'))
    authReq2 = buildAuthXmlFederated2(match.group(0))
    try:
        req = Request("https://login.microsoftonline.com/rst2.srf", authReq2.encode('utf-8'),
                      {"Content-Type": "application/soap+xml; charset=utf-8"})
        request = urlopen(req)
    except URLError as x:
        raise RuntimeError("Failed to send login request.")
    authRespTree = ET.parse(request)
    authToken = None
    fault = authRespTree.find(".//soap:Fault", ns)
    if fault is not None:
        reason = fault.find("soap:Reason/soap:Text", ns)
        if reason is not None:
            reason = reason.text
        else:
            reason = "*Unknown reason*"
        raise RuntimeError(
            "Railed to retrieve authentication token: {}".format(reason))
    tokenElm = authRespTree.find(".//wssec:BinarySecurityToken", ns)
    if tokenElm is None:
        raise RuntimeError("Failed to extract authentication token.")
    else:
        authToken = tokenElm.text
    return authToken


def get_cookie(endpoint, username, password):
    stsurl = discover_sts(username)
    try:
        if stsurl is None:
            authToken = getSecurityTokenManaged(username, password, endpoint)
        else:
            authToken = getSecurityTokenFederated(
                username, password, endpoint, stsurl)
    except RuntimeError as x:
        print(str(x), file=sys.stderr)
        exit(1)
    endpointUrl = urlparse(endpoint)
    if endpointUrl.scheme not in ["http", "https"] or not endpointUrl.netloc:
        print("Invalid endpoint URL: {}".format(endpoint), file=sys.stderr)
        exit(1)
    cookiejar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookiejar))
    try:
        try:
            request = Request("{0}://{1}/_forms/default.aspx?wa=wsignin1.0".format(
                endpointUrl.scheme, endpointUrl.netloc))
            # pylint: disable=unused-variable
            response = opener.open(request, data=authToken.encode('utf-8'))
            cookieStr = ""
            cookiesFound = []
            for cookie in cookiejar:
                if cookie.name in ("FedAuth", "rtFa"):
                    cookieStr += cookie.name + "=" + cookie.value + "; "
                    cookiesFound.append(cookie.name)
            if "FedAuth" not in cookiesFound or "rtFa" not in cookiesFound:
                print("Incomplete cookies retrieved.", file=sys.stderr)
                exit(1)
            # print(cookieStr)
            return cookieStr
        except:
            from office365.runtime.auth.user_credential import UserCredential
            from office365.sharepoint.client_context import ClientContext
            user_credentials = UserCredential(username, password)
            ctx = ClientContext(endpoint).with_credentials(user_credentials)
            ctx.load(ctx.web)
            ctx.execute_query()
            cookieStr = 'rtFa='+vars(vars(vars(ctx)['_auth_context'])['_provider'])['_cached_auth_cookies']['rtFa']+'; FedAuth='+vars(
                vars(vars(ctx)['_auth_context'])['_provider'])['_cached_auth_cookies']['FedAuth']
            return cookieStr
    except URLError as x:
        print("Failed to login to SharePoint site: {}".format(x.reason))
        exit(1)
# 結束獲取使用者Cookie


# 讀取網站設定
def read_data() -> dict:
    if Redis_sync:
        print('讀取資料中...')
        if os.path.isfile(data_location):
            print('存在緩存資料...')
            f = open(data_location)
            data = json.loads(f.read())
            print('讀取緩存資料...')
            f.close()
            if data['TIME'] < (time.time()-Redis_sync_expires):
                print('緩存過期...')
                data = {}
                print('線上取得資料...')
                data = REDIS.get(Redis_sync_key)
                if data:
                    data = json.loads(data)
                    T = time.time()
                    data['TIME'] = T
                    with open(data_location, 'w') as f:
                        print('寫入緩存...')
                        f.write(json.dumps(data))
                else:
                    print('資料取得失敗，將進行初始化作業')
                    data = None
        else:
            print('不存在緩存資料...')
            data = {}
            print('線上取得資料...')
            data = REDIS.get(Redis_sync_key)
            if data:
                data = json.loads(data)
                T = time.time()
                data['TIME'] = T
                with open(data_location, 'w') as f:
                    print('寫入緩存...')
                    f.write(json.dumps(data))
                print('成功讀取資料')
            else:
                print('資料取得失敗，將進行初始化作業')
                data = None
        return data
    else:
        print('讀取資料中...')
        if os.path.isfile(data_location):
            print('存在緩存資料...')
            f = open(data_location)
            data = json.loads(f.read())
            print('讀取緩存資料...')
            f.close()
            print('成功讀取資料')
        else:
            print('資料取得失敗，將進行初始化作業')
            data = None
        return data


# 讀取Cookie
def read_cookie(endpoint, username, password) -> str:
    print('讀取憑證中...')
    if os.path.isfile(cookies_location):
        print('存在憑證資料...')
        f = open(cookies_location)
        cookies = json.loads(f.read())
        print('讀取憑證資料...')
        f.close()
        print('檢查憑證資料...')
        if username in cookies:
            print('用戶存在...')
            if cookies[username]['TIME'] < (time.time()-86400):
                print('憑證過期...')
                T = time.time()
                cookies[username] = {'cookie': get_cookie(
                    endpoint, username, password), 'TIME': T}
                print('線上取得憑證...')
                with open(cookies_location, 'w') as f:
                    f.write(json.dumps(cookies))
                    print('寫入憑證...')
            print('成功讀取憑證')
        else:
            print('用戶不存在...')
            T = time.time()
            cookies[username] = {'cookie': get_cookie(
                endpoint, username, password), 'TIME': T}
            print('線上取得憑證...')
            with open(cookies_location, 'w') as f:
                f.write(json.dumps(cookies))
                print('寫入憑證...')
            print('成功讀取憑證')
    else:
        print('不存在憑證資料...')
        cookies = {}
        T = time.time()
        cookies[username] = {'cookie': get_cookie(
            endpoint, username, password), 'TIME': T}
        print('線上取得憑證...')
        with open(cookies_location, 'w') as f:
            f.write(json.dumps(cookies))
            print('寫入憑證...')
        print('成功讀取憑證')
    return cookies[username]['cookie']


# 寫入網站設定
def write_data(data):
    _data = json.dumps(data)
    if Redis_sync:
        REDIS.set(Redis_sync_key, _data)
    with open(data_location, 'w') as f:
        f.write(_data)
    return 0

# 轉換size為人類可讀


def sizeof_fmt(num, suffix="B") -> str:
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"


def utc_local_convert(time) -> str:
    utc = time
    UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
    utcTime = datetime.datetime.strptime(utc, UTC_FORMAT)
    localtime = utcTime + datetime.timedelta(hours=UTC)
    return localtime.ctime()


def url_standardization(url):
    url = urllib.parse.unquote(url)
    url = urllib.parse.quote(url, safe='/?=')
    return url


def randombackground(data):
    try:
        BackgroundImageList = data['ApiOnedriveSetting']['backgroud_image_list']
        BackgroundImage = BackgroundImageList[random.randint(
            0, len(BackgroundImageList))-1]
    except:
        BackgroundImage = ''
    return BackgroundImage

# 權限管理


def loggined(data, request) -> bool:
    user = request.cookies.get('user')
    password = request.cookies.get('password')
    try:
        hash = data["ApiOnedriveSetting"]["users"][user]["password"]
    except:
        # User not exist
        return False
    if hash == password:
        # Pass
        return True
    # Password incorrect
    return False


def is_admin(data, request) -> bool:
    user = request.cookies.get('user')
    if data["ApiOnedriveSetting"]["users"][user]["rank"] == "admin":
        return True
    else:
        return False


# 布建網站後初始化資料庫，或在接收?initialization=1時執行
def initialization(request):
    if request.method == 'GET':
        return render_template('initialization.html')
    else:
        data = {"SharePointAccountList": {}, "ApiOnedriveSetting": {}}
        local_user = request.form.get('local_user')
        local_password = request.form.get('local_password')
        BackgroundImageList = request.form.get('background')
        anonymous_viewlist = request.form.get('anonymous_viewlist')
        anonymous_download = request.form.get('anonymous_download')
        CACHE_TYPE = request.form.get('CACHE_TYPE')
        top_md = request.form.get('top_md')
        bottom_md = request.form.get('bottom_md')
        page_encrypt = request.form.get('page_encrypt')
        passfile = request.form.get('passfile')
        alia = request.form.get('alia')
        type = request.form.get('type')
        site = request.form.get('site')
        endpoint = request.form.get('endpoint')
        username = request.form.get('username')
        password = request.form.get('password')

        data = {
            "Sites": {
                alia: {
                    "type": type,
                    "site": site,
                    "endpoint": endpoint,
                    "username": username,
                    "password": password,
                    "alia": alia
                }
            },
            "ApiOnedriveSetting": {
                "backgroud_image_list": BackgroundImageList.split(',')[:-1],
                "anonymous_viewlist": True if anonymous_viewlist == '0' else False,
                "anonymous_download": True if anonymous_download == '0' else False,
                "top_md": True if top_md else False,
                "bottom_md": True if bottom_md else False,
                "page_encrypt": True if page_encrypt else False,
                "passfile": passfile,
                "users": {
                    local_user: {
                        "rank": "admin",
                        "password": hashlib.sha256(local_password.encode()).hexdigest()
                    }
                },
                "CACHE_TYPE": CACHE_TYPE
            }
        }
        T = time.time()
        data['TIME'] = T
        write_data(data)
        reflash(request)
        return redirect(url_for("home"))


# 登入頁面，?login時執行
def login(request):
    data = read_data()
    users = data["ApiOnedriveSetting"]["users"]
    if request.method == 'GET':
        user = request.cookies.get('user')
        password = request.cookies.get('password')
        if user in users and users[user]["password"] == password:
            response = make_response(redirect(request.path))
        else:
            response = make_response(render_template('sharepoint_login.html'))
    elif request.method == 'POST':
        user = request.form.get('user')
        password = request.form.get('password')
        pdhash = hashlib.sha256(password.encode()).hexdigest()
        if user in users and users[user]["password"] == pdhash:
            response = make_response(redirect(request.path))
            response.set_cookie('user', user, path='/')
            response.set_cookie('password', pdhash, path='/')
        else:
            response = make_response(render_template(
                'sharepoint_login.html', warning='錯誤'))
    return response


# 設定頁面，?setting時執行
def setting(request):
    data = read_data()
    BackgroundImageList = data['ApiOnedriveSetting']['backgroud_image_list']
    BackgroundImage = randombackground(data)
    if not loggined(data, request):
        response = redirect(request.base_url + '/?login')
    elif not is_admin(data, request) and loggined(data, request):
        response = 'Permission not allow'
    else:
        if 'logout' in request.args:
            response = logout(request)
        elif request.form:
            if 'background' in request.form:
                BackgroundImageList = request.form.get('background')
                anonymous_viewlist = request.form.get('anonymous_viewlist')
                anonymous_download = request.form.get('anonymous_download')
                CACHE_TYPE = request.form.get('CACHE_TYPE')
                top_md = request.form.get('top_md')
                bottom_md = request.form.get('bottom_md')
                page_encrypt = request.form.get('page_encrypt')
                passfile = request.form.get('passfile')
                data["ApiOnedriveSetting"]["backgroud_image_list"] = BackgroundImageList.split(',')[
                    :-1]
                data["ApiOnedriveSetting"]["anonymous_viewlist"] = True if anonymous_viewlist == '0' else False
                data["ApiOnedriveSetting"]["anonymous_download"] = True if anonymous_download == '0' else False
                data["ApiOnedriveSetting"]["CACHE_TYPE"] = CACHE_TYPE
                data["ApiOnedriveSetting"]["top_md"] = True if top_md else top_md
                data["ApiOnedriveSetting"]["bottom_md"] = True if bottom_md else bottom_md
                data["ApiOnedriveSetting"]["page_encrypt"] = True if page_encrypt else page_encrypt
                data["ApiOnedriveSetting"]["passfile"] = passfile
            elif 'type' in str(request.form):
                n = 0
                alia = ''
                needdelete = []
                for i in request.form:
                    if request.form.get(i) == '':
                        needdelete.append(
                            '-'.join(i.split('-')[1:]).replace('%$%', ' '))
                    if 'NEW' in str(i):
                        if i.split('-')[1] == n:
                            key = i.split('-')[0].replace('NEW', '')
                            data["Sites"][alia][key] = request.form.get(i)
                        else:
                            alia = request.form.get(i)
                            key = i.split('-')[0].replace('NEW', '')
                            data["Sites"][alia] = {key: request.form.get(i)}
                            n = i.split('-')[1]
                    else:
                        key = i.split('-')[0]
                        val = '-'.join(i.split('-')[1:]).replace('%$%', ' ')
                        data["Sites"][val][key] = request.form.get(i)
                for i in needdelete:
                    try:
                        data["Sites"].pop(i)
                    except:
                        pass
            elif 'user' in request.form:
                pop = request.form.get('pop')
                if not pop:
                    user = request.form.get('user')
                    password = request.form.get('password')
                    isadmin = request.form.get('isadmin')
                    data["ApiOnedriveSetting"]["users"][user] = {
                        "rank": "admin" if isadmin == '0' else "guest",
                        "password": hashlib.sha256(password.encode()).hexdigest() if password else data["ApiOnedriveSetting"]["users"][user]["password"]
                    }
                else:
                    user = request.form.get('user')
                    data["ApiOnedriveSetting"]["users"].pop(user)
            write_data(data)
            response = make_response(redirect(request.base_url + "?setting"))
        else:
            Sites = data['Sites']
            Users = data["ApiOnedriveSetting"]["users"]
            passfile = data["ApiOnedriveSetting"]["passfile"]
            response = make_response(render_template('sharepoint_setting.html', Users=Users, Sites=Sites,
                                     backgroud_image_list=BackgroundImageList, BackgroundImage=BackgroundImage, passfile=passfile))
    return response


# 登出頁面，?logout時執行
def logout(request):
    if request.referrer:
        response = make_response(redirect(request.referrer))
    else:
        response = make_response(redirect(url_for('home')))
    response.set_cookie('user', '', path='/', expires=0)
    response.set_cookie('password', '', path='/', expires=0)
    return response


# 刷新頁面，?reflash時執行
def reflash(path):
    if path != '':
        if DEBUG:
            with open("claer-cache-arg", 'w') as f:
                f.write(path)
        cache.delete_memoized(main, path)
        response = make_response(redirect(request.referrer))
    else:
        response = make_response(redirect(url_for("home")))
    return response


# 返回下載地址，?download時執行
def getdownloadlink(data, site, path):
    alia = ''
    for i in data["Sites"]:
        if data["Sites"][i]["site"] == site:
            alia = data["Sites"][i]["alia"]
    endpoint = data['Sites'][alia]["endpoint"]
    username = data['Sites'][alia]["username"]
    password = data['Sites'][alia]["password"]
    cookie = read_cookie(endpoint, username, password)
    header = {'cookie': cookie,
              'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
    path = urllib.parse.quote(path)
    url = endpoint + '_api/v2.1/sites/' + endpoint.split('.')[0].split(
        '/')[-1] + '.sharepoint.com:/sites/' + site + ':/drive/root:' + path
    r = requests.get(url, headers=header).text
    r = json.loads(r)
    return r['@content.downloadUrl'] if '@content.downloadUrl' in r else 0


# 回傳使用者憑證，?cookie=user時執行
def cookie(request):
    site = request.args.get("cookie")
    data = read_data()
    if site in data['Sites']:
        endpoint = data['Sites'][site]["endpoint"]
        username = data['Sites'][site]["username"]
        password = data['Sites'][site]["password"]
        cookie = read_cookie(endpoint, username, password)
    else:
        cookie = "Site Not Found or Site Type Is Not SharePointSitePW"
    return cookie


# 回傳網站狀態，?status時執行
def status(request):
    return 'Online'

# 讀取頁面加密密碼


def get_page_encrypt_pw(data, path):
    if not data["ApiOnedriveSetting"]["page_encrypt"] or len(path.split('/')) < 1:
        return None
    path += '/' + data["ApiOnedriveSetting"]["passfile"]
    site = data['Sites'][path.split('/')[0]]['site']
    path = '/'.join(path.split('/')[1:])
    try:
        r = requests.get(getdownloadlink(data, site, path))
        return r.text if r.ok else None
    except:
        return None

# 辨認檔案型態


def get_file_type(extension):
    extension = extension.lower()
    video_extensions = [".mp4", ".mkv", ".flv", ".avi", ".mov", ".wmv"]
    image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp"]
    audio_extensions = [".mp3", ".wav", ".flac", ".aac"]
    document_extensions = [".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"]
    text_extensions = [".txt"]
    program_extensions = [".json", ".py",
                          ".c", ".cpp", ".java", ".html", ".htm"]

    if extension in video_extensions:
        return "video"
    elif extension in image_extensions:
        return "image"
    elif extension in audio_extensions:
        return "audio"
    elif extension in document_extensions:
        return "office"
    elif extension in text_extensions:
        return "text"
    elif extension in program_extensions:
        return "programe"
    else:
        return "unknown"

# 檔案預覽


def preview(request):
    data = read_data()
    # 檢查權限
    if data["ApiOnedriveSetting"]["anonymous_viewlist"] == False and not loggined(data, request):
        return login(request)
    mediatype = get_file_type('.'+request.path.split('.')[-1])
    if mediatype == 'text':
        site = request.path.split('/')[1]
        path = '/'.join(request.path.split('/')[2:])
        txt = requests.get(getdownloadlink(data, site, path)).content
        code = chardet.detect(txt)['encoding']
        txt = txt.decode(code)
        SUB = ''
    elif mediatype == 'programe':
        site = request.path.split('/')[1]
        path = '/'.join(request.path.split('/')[2:])
        txt = requests.get(getdownloadlink(data, site, path)).text
        txt = '```' + '\n' + txt + '\n```'
        exts = ['extra', 'codehilite', 'tables', 'toc']
        txt = markdown.markdown(txt, extensions=exts)
        txt = Markup(txt)
        SUB = ''
    elif mediatype == 'video':
        SUB = request.url.replace('mp4?preview=1', 'ass?download=1').replace(
            'mkv?preview=1', 'ass?download=1')
        txt = ''
    else:
        txt = SUB = ''
    return make_response(render_template("sharepoint_preview.html", source=request.url.replace('preview=1', 'download=1'), mediatype=mediatype, name=urllib.parse.unquote(request.base_url.split('/')[-1]), txt=txt, SUB=SUB))


def download(url):
    data = read_data()
    # 檢查權限
    if data["ApiOnedriveSetting"]["anonymous_download"] == False and not loggined(data, request):
        return login(request)
    site = url.split('/')[0]
    path = '/'.join(url.split('/')[1:])
    return redirect(getdownloadlink(data, site, path))


def init_access_token(data, request):
    path = request.path
    site = path.split('/')[1]
    client_id = data["Sites"][site]["client_id"]
    client_secret = data["Sites"][site]["client_secret"]
    redirect_uri = data["Sites"][site]["redirect_uri"]
    authorization_url = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id='+client_id+'&response_type=code&redirect_uri=' + urllib.parse.quote(redirect_uri) + '%2F&scope=https%3A%2F%2Fgraph.microsoft.com%2FFiles.ReadWrite.All%20Sites.ReadWrite.All%20offline_access'
    if request.method == "GET":
        response = make_response(render_template("init_access_token.html", authorization_url=authorization_url))
    else:
        code = request.form.get("code")
        HEADERS = {'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'}
        url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
        FormData = {'client_id':client_id,'scope':'https://graph.microsoft.com/Files.ReadWrite.All Sites.ReadWrite.All offline_access','redirect_uri':redirect_uri,'client_secret':client_secret,'grant_type':'authorization_code','code':code}
        FormData = urllib.parse.urlencode(FormData)
        r = requests.post(url=url, headers=HEADERS, data=FormData).json()
        try:
            access_token = r['access_token']
            refresh_token = r['refresh_token']
            data["Sites"][site]["access_token"] = access_token
            data["Sites"][site]["refresh_token"] = refresh_token
            data["Sites"][site]["t"] = time.time()
            write_data(data)
            response = make_response(redirect(request.url.split('?')[0]))
        except:
            response = make_response(render_template("init_access_token.html", authorization_url=authorization_url, warning="Error!" + json.dumps(r)))
    return response

def reflash_token(data, site):
    client_id = data["Sites"][site]['client_id']
    client_secret = data["Sites"][site]['client_secret']
    redirect_uri = data["Sites"][site]['redirect_uri']
    refresh_token = data["Sites"][site]['refresh_token']
    url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
    HEADERS = {'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'}
    formdata = 'client_id='+client_id+'&scope=https%3A%2F%2Fgraph.microsoft.com%2FFiles.ReadWrite.All%20Sites.ReadWrite.All%20offline_access&redirect_uri=' + redirect_uri + '&client_secret='+client_secret+'&grant_type=refresh_token&refresh_token='+refresh_token
    try:
        retur = requests.post(url=url, headers=HEADERS, data=formdata).json()
        access_token = retur['access_token']
        refresh_token = retur['refresh_token']
        data["Sites"][site]["access_token"] = access_token
        data["Sites"][site]["refresh_token"] = refresh_token
        data["Sites"][site]["t"] = time.time()
        write_data(data)
    except:
        return "Error, Unable to reflash token. Please check setting."

def get_access_token(data, site) -> str:
    if time.time() - data["Sites"][site]['t'] > 60*60:
        reflash_token(data, site)
    access_token = data["Sites"][site]["access_token"]
    return access_token

def print_code(request):
    return make_response(request.args.get("code").split('&')[0])

app = Flask(__name__)
app.config.from_mapping(CacheConfig)
cache = Cache(app)


# 效能分析工具
if DEBUG:
    @app.before_request
    def before_request():
        if "profile" in request.args:
            g.profiler = Profiler()
            g.profiler.start()

    @app.after_request
    def after_request(response):
        if not hasattr(g, "profiler"):
            return response
        g.profiler.stop()
        output_html = g.profiler.output_html()
        return make_response(output_html)


@cache.memoize()
def main(url):
    if DEBUG:
        with open("cache-arg", 'w') as f:
            f.write(url)

    data = read_data()

    def drivetype(data, url):
        try:
            return data["Sites"][url.split('/')[0]]['type']
        except:
            return None
    
    DriveType = drivetype(data, url)
    if DriveType == "SharePointSitePW":
        # pylint: disable=unused-variable
        def sharepointsite_details(data, account, site) -> dict:
            endpoint = data['SharePointAccountList'][account]["endpoint"]
            username = data['SharePointAccountList'][account]["username"]
            password = data['SharePointAccountList'][account]["password"]
            cookie = read_cookie(endpoint, username, password)
            header = {'cookie': cookie,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
            url = endpoint + '_api/v2.1/sites/' + \
                endpoint.split('.')[0].split('/')[-1] + \
                '.sharepoint.com:/sites/' + site + ':/drive/root'
            r = requests.get(url, headers=header).text
            r = json.loads(r)
            return r

        def nextpage(header, url) -> dict:
            response = {}
            r = requests.get(url, headers=header).text
            r = json.loads(r)
            if DEBUG:
                print(r)
            for i in r['value']:
                response[i["name"]] = {"type": "folder" if "folder" in i else "file",
                                    "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
            if "@odata.nextLink" in r:
                response.update(nextpage(header, r["@odata.nextLink"]))
            return response

        def sharepointsite_root_files(data, site) -> dict:
            # {name: {"type": folder/file, "lastModifiedDateTime": time, "size": size}}
            response = {}        
            endpoint = data['Sites'][site]["endpoint"]
            username = data['Sites'][site]["username"]
            password = data['Sites'][site]["password"]
            cookie = read_cookie(endpoint, username, password)
            header = {'cookie': cookie,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
            url = endpoint + '_api/v2.1/sites/' + endpoint.split('.')[0].split('/')[-1] + '.sharepoint.com:/sites/' + \
                data['Sites'][site]["site"] + ':/drive/root/children?$top=' + \
                str(REQUEST_SIZE)+'&select=name,folder,lastModifiedDateTime,size'
            r = requests.get(url, headers=header).json()
            if DEBUG:
                print(url, r)
            for i in r['value']:
                response[i["name"]] = {"type": "folder" if "folder" in i else "file",
                                    "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
            if "@odata.nextLink" in r:
                response.update(nextpage(header, r["@odata.nextLink"]))
            return response

        def sharepointsite_path_files(data, site, path) -> dict:
            # {name: {"type": folder/file, "lastModifiedDateTime": time, "size": size}}
            response = {}
            endpoint = data['Sites'][site]["endpoint"]
            username = data['Sites'][site]["username"]
            password = data['Sites'][site]["password"]
            cookie = read_cookie(endpoint, username, password)
            header = {'cookie': cookie,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
            path = urllib.parse.quote(path)
            url = endpoint + '_api/v2.1/sites/' + endpoint.split('.')[0].split('/')[-1] + '.sharepoint.com:/sites/' + site + \
                ':/drive/root:' + path + ':/children?$top=' + \
                str(REQUEST_SIZE)+'&select=name,folder,lastModifiedDateTime,size'
            r = requests.get(url, headers=header).text
            r = json.loads(r)
            if DEBUG:
                print(r)
            for i in r['value']:
                response[i["name"]] = {"type": "folder" if "folder" in i else "file",
                                    "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
            if "@odata.nextLink" in r:
                response.update(nextpage(header, r["@odata.nextLink"]))
            return response

        def head_foot_note(data, url, SharePointFileList) -> list:
            site = url.split('/')[0]
            response = []
            if data['ApiOnedriveSetting'].get('top_md') and 'top.md' in str(SharePointFileList):
                _url = url+'/top.md'
                path = '/'.join(_url.split('/')[1:])
                r = requests.get(getdownloadlink(data, site, path))
                if r.ok:
                    txt = r.text
                    exts = ['extra', 'codehilite', 'tables', 'toc']
                    txt = markdown.markdown(txt, extensions=exts)
                    txt = Markup(txt)
                    response.append(txt)
                else:
                    response.append(None)
            else:
                response.append(None)
            if data['ApiOnedriveSetting'].get('bottom_md') and 'bottom.md' in str(SharePointFileList):
                _url = url+'/bottom.md'
                path = '/'.join(_url.split('/')[1:])
                r = requests.get(getdownloadlink(data, site, path))
                if r.ok:
                    txt = r.text
                    exts = ['extra', 'codehilite', 'tables', 'toc']
                    txt = markdown.markdown(txt, extensions=exts)
                    txt = Markup(txt)
                    response.append(txt)
                else:
                    response.append(None)
            else:
                response.append(None)
            return response

        headings = ['Name', 'Last edit time', 'Size']

        BackgroundImage = randombackground(data)
        try:
            if url[-1] == '/':
                url = url[:-1]
            if len(url.split('/')) == 1:
                # List root files in site
                SharePointFileList = [['..', '', '', '/']]
                SharePointFileList_FOLDERS = []
                SharePointFileList_FILES = []
                site = url.split('/')[0]
                sharepointsite_root_files_dict = sharepointsite_root_files(
                    data, site)
                for i in sharepointsite_root_files_dict:
                    name = i
                    time = utc_local_convert(
                        sharepointsite_root_files_dict[i]['lastModifiedDateTime'])
                    size = sizeof_fmt(sharepointsite_root_files_dict[i]['size'])
                    if sharepointsite_root_files_dict[i]['type'] == 'folder':
                        SharePointFileList_FOLDERS.append(
                            [name, time, size, '/' + url + '/' + urllib.parse.quote(name)])
                    else:
                        SharePointFileList_FILES.append(
                            [name, time, size, '/' + url + '/' + urllib.parse.quote(name) + '?preview=1'])
                SharePointFileList_FOLDERS = os_sorted(SharePointFileList_FOLDERS, key=lambda x: x[0])
                SharePointFileList_FILES = os_sorted(SharePointFileList_FILES, key=lambda x: x[0])
                SharePointFileList.extend(SharePointFileList_FOLDERS)
                SharePointFileList.extend(SharePointFileList_FILES)
                # pylint: disable=unbalanced-tuple-unpacking
                [headnote, footnote] = head_foot_note(
                    data, url, SharePointFileList)
                return make_response(render_template('sharepoint_main.html', headings=headings, BackgroundImage=BackgroundImage, SharePointFileList=SharePointFileList, headnote=headnote, footnote=footnote))
            if len(url.split('/')) > 1:
                # List files in path
                SharePointFileList = [
                    ['..', '', '', '/' + '/'.join(url.split('/')[0:-1])]]
                SharePointFileList_FOLDERS = []
                SharePointFileList_FILES = []
                site = data["Sites"][url.split('/')[0]]["site"]
                path = '/'.join(url.split('/')[1:])
                sharepointsite_path_files_dict = sharepointsite_path_files(
                    data, site, path)
                for i in sharepointsite_path_files_dict:
                    name = i
                    time = utc_local_convert(
                        sharepointsite_path_files_dict[i]['lastModifiedDateTime'])
                    size = sizeof_fmt(sharepointsite_path_files_dict[i]['size'])
                    if sharepointsite_path_files_dict[i]['type'] == 'folder':
                        SharePointFileList_FOLDERS.append(
                            [name, time, size, '/' + url + '/' + urllib.parse.quote(name)])
                    else:
                        SharePointFileList_FILES.append(
                            [name, time, size, '/' + url + '/' + urllib.parse.quote(name) + '?preview=1'])
                SharePointFileList_FOLDERS = os_sorted(SharePointFileList_FOLDERS, key=lambda x: x[0])
                SharePointFileList_FILES = os_sorted(SharePointFileList_FILES, key=lambda x: x[0])
                SharePointFileList.extend(SharePointFileList_FOLDERS)
                SharePointFileList.extend(SharePointFileList_FILES)
                # pylint: disable=unbalanced-tuple-unpacking
                [headnote, footnote] = head_foot_note(
                    data, url, SharePointFileList)
                return make_response(render_template('sharepoint_main.html', headings=headings, BackgroundImage=BackgroundImage, SharePointFileList=SharePointFileList, headnote=headnote, footnote=footnote))
        except:
            return make_response('Page Not Found', 404)
    elif DriveType ==  "SharePointSiteAPI":
        def sitename2id(site):
            access_token = get_access_token(data, site)
            headers = {'Authorization': 'Bearer '+access_token}
            url = "https://graph.microsoft.com/v1.0/sites?search='" + site + "'"
            r = requests.get(url, headers=headers).json()['value']
            for i in r:
                if i["webUrl"].split('/')[-1] == site:
                    return i["id"].split(',')[1]
            return None

        def nextpage(header, url) -> dict:
            response = {}
            r = requests.get(url, headers=header).text
            r = json.loads(r)
            if DEBUG:
                print(r)
            for i in r['value']:
                response[i["name"]] = {"type": "folder" if "folder" in i else "file",
                                    "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
            if "@odata.nextLink" in r:
                response.update(nextpage(header, r["@odata.nextLink"]))
            return response
        
        def sharepointsite_root_files(data, site) -> dict:
            response = {}
            url = "https://graph.microsoft.com/v1.0/sites/" + sitename2id(site) + "/drive/root/children"
            access_token = get_access_token(data, site)
            headers = {'Authorization': 'Bearer '+access_token}
            r = requests.get(url, headers=headers).json()
            for i in r['value']:
                response[i["name"]] = {"type": "folder" if "folder" in i else "file",
                                    "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
            if "@odata.nextLink" in r:
                response.update(nextpage(headers, r["@odata.nextLink"]))
            return response

        def sharepointsite_path_files(data, site, path) -> dict:
            response = {}
            url = "https://graph.microsoft.com/v1.0/sites/" + sitename2id(site) + "/drive/root:/" + path + ":/children"
            access_token = get_access_token(data, site)
            headers = {'Authorization': 'Bearer '+access_token}
            r = requests.get(url, headers=headers).json()
            for i in r['value']:
                response[i["name"]] = {"type": "folder" if "folder" in i else "file",
                                    "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
            if "@odata.nextLink" in r:
                response.update(nextpage(headers, r["@odata.nextLink"]))
            return response

        def head_foot_note(data, url, SharePointFileList) -> list:
            response = []
            if data['ApiOnedriveSetting'].get('top_md') and 'top.md' in str(SharePointFileList):
                _url = url+'/top.md'
                path = '/'.join(_url.split('/')[1:])
                r = requests.get(getdownloadlink(data, site, path))
                if r.ok:
                    txt = r.text
                    exts = ['extra', 'codehilite', 'tables', 'toc']
                    txt = markdown.markdown(txt, extensions=exts)
                    txt = Markup(txt)
                    response.append(txt)
                else:
                    response.append(None)
            else:
                response.append(None)
            if data['ApiOnedriveSetting'].get('bottom_md') and 'bottom.md' in str(SharePointFileList):
                _url = url+'/bottom.md'
                path = '/'.join(_url.split('/')[1:])
                r = requests.get(getdownloadlink(data, site, path))
                if r.ok:
                    txt = r.text
                    exts = ['extra', 'codehilite', 'tables', 'toc']
                    txt = markdown.markdown(txt, extensions=exts)
                    txt = Markup(txt)
                    response.append(txt)
                else:
                    response.append(None)
            else:
                response.append(None)
            return response

        headings = ['Name', 'Last edit time', 'Size']

        BackgroundImage = randombackground(data)

        try:
            if url[-1] == '/':
                url = url[:-1]
            if len(url.split('/')) == 1:
                # List root files in site
                SharePointFileList = [['..', '', '', '/']]
                SharePointFileList_FOLDERS = []
                SharePointFileList_FILES = []
                site = url.split('/')[0]
                sharepointsite_root_files_dict = sharepointsite_root_files(
                    data, site)
                for i in sharepointsite_root_files_dict:
                    name = i
                    time = utc_local_convert(
                        sharepointsite_root_files_dict[i]['lastModifiedDateTime'])
                    size = sizeof_fmt(sharepointsite_root_files_dict[i]['size'])
                    if sharepointsite_root_files_dict[i]['type'] == 'folder':
                        SharePointFileList_FOLDERS.append(
                            [name, time, size, '/' + url + '/' + urllib.parse.quote(name)])
                    else:
                        SharePointFileList_FILES.append(
                            [name, time, size, '/' + url + '/' + urllib.parse.quote(name) + '?preview=1'])
                SharePointFileList_FOLDERS = os_sorted(SharePointFileList_FOLDERS, key=lambda x: x[0])
                SharePointFileList_FILES = os_sorted(SharePointFileList_FILES, key=lambda x: x[0])
                SharePointFileList.extend(SharePointFileList_FOLDERS)
                SharePointFileList.extend(SharePointFileList_FILES)
                # pylint: disable=unbalanced-tuple-unpacking
                [headnote, footnote] = head_foot_note(
                    data, url, SharePointFileList)
                return make_response(render_template('sharepoint_main.html', headings=headings, BackgroundImage=BackgroundImage, SharePointFileList=SharePointFileList, headnote=headnote, footnote=footnote))
            if len(url.split('/')) > 1:
                # List files in path
                SharePointFileList = [
                    ['..', '', '', '/' + '/'.join(url.split('/')[0:-1])]]
                SharePointFileList_FOLDERS = []
                SharePointFileList_FILES = []
                site = data["Sites"][url.split('/')[0]]["site"]
                path = '/'.join(url.split('/')[1:])
                sharepointsite_path_files_dict = sharepointsite_path_files(
                    data, site, path)
                for i in sharepointsite_path_files_dict:
                    name = i
                    time = utc_local_convert(
                        sharepointsite_path_files_dict[i]['lastModifiedDateTime'])
                    size = sizeof_fmt(sharepointsite_path_files_dict[i]['size'])
                    if sharepointsite_path_files_dict[i]['type'] == 'folder':
                        SharePointFileList_FOLDERS.append(
                            [name, time, size, '/' + url + '/' + urllib.parse.quote(name)])
                    else:
                        SharePointFileList_FILES.append(
                            [name, time, size, '/' + url + '/' + urllib.parse.quote(name) + '?preview=1'])
                SharePointFileList_FOLDERS = os_sorted(SharePointFileList_FOLDERS, key=lambda x: x[0])
                SharePointFileList_FILES = os_sorted(SharePointFileList_FILES, key=lambda x: x[0])
                SharePointFileList.extend(SharePointFileList_FOLDERS)
                SharePointFileList.extend(SharePointFileList_FILES)
                # pylint: disable=unbalanced-tuple-unpacking
                [headnote, footnote] = head_foot_note(
                    data, url, SharePointFileList)
                return make_response(render_template('sharepoint_main.html', headings=headings, BackgroundImage=BackgroundImage, SharePointFileList=SharePointFileList, headnote=headnote, footnote=footnote))
        except:
            return make_response('Page Not Found', 404)
    elif DriveType == "OneDrivePW":
        def nextpage(header, url) -> dict:
            response = {}
            r = requests.get(url, headers=header).text
            r = json.loads(r)
            if DEBUG:
                print(r)
            for i in r['value']:
                response[i["name"]] = {"type": "folder" if "folder" in i else "file",
                                    "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
            if "@odata.nextLink" in r:
                response.update(nextpage(header, r["@odata.nextLink"]))
            return response
        def onedrive_root_files(data, site) -> dict:
            response = {}
            endpoint = data["Sites"][site].get("endpoint")
            username = data["Sites"][site].get("username")
            password = data["Sites"][site].get("password")
            cookie = read_cookie(endpoint, username, password)
            url = endpoint + '_api/v2.1/drive/root/children?$top='+str(REQUEST_SIZE)+'&select=name,folder,lastModifiedDateTime,size'
            header = {'cookie': cookie,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
            r = requests.get(url, headers=header).json()
            if DEBUG:
                print(url, r)
            for i in r['value']:
                response[i["name"]] = {"type": "folder" if "folder" in i else "file",
                                    "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
            if "@odata.nextLink" in r:
                response.update(nextpage(header, r["@odata.nextLink"]))
            return response
        def onedrive_path_files(data, site, path) -> dict:
            response = {}
            endpoint = data["Sites"][site].get("endpoint")
            username = data["Sites"][site].get("username")
            password = data["Sites"][site].get("password")
            cookie = read_cookie(endpoint, username, password)
            url = endpoint + '_api/v2.1/drive/root:/'+path+':/children?$top='+str(REQUEST_SIZE)+'&select=name,folder,lastModifiedDateTime,size'            
            header = {'cookie': cookie,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
            r = requests.get(url, headers=header).json()
            if DEBUG:
                print(url, r)
            for i in r['value']:
                response[i["name"]] = {"type": "folder" if "folder" in i else "file",
                                    "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
            if "@odata.nextLink" in r:
                response.update(nextpage(header, r["@odata.nextLink"]))
            return response
        try:
            if url[-1] == '/':
                url = url[:-1]
            if len(url.split('/')) == 1:
                # List root files in site
                SharePointFileList = [['..', '', '', '/']]
                SharePointFileList_FOLDERS = []
                SharePointFileList_FILES = []
                site = url.split('/')[0]
                sharepointsite_root_files_dict = sharepointsite_root_files(
                    data, site)
                for i in sharepointsite_root_files_dict:
                    name = i
                    time = utc_local_convert(
                        sharepointsite_root_files_dict[i]['lastModifiedDateTime'])
                    size = sizeof_fmt(sharepointsite_root_files_dict[i]['size'])
                    if sharepointsite_root_files_dict[i]['type'] == 'folder':
                        SharePointFileList_FOLDERS.append(
                            [name, time, size, '/' + url + '/' + urllib.parse.quote(name)])
                    else:
                        SharePointFileList_FILES.append(
                            [name, time, size, '/' + url + '/' + urllib.parse.quote(name) + '?preview=1'])
                SharePointFileList_FOLDERS = os_sorted(SharePointFileList_FOLDERS, key=lambda x: x[0])
                SharePointFileList_FILES = os_sorted(SharePointFileList_FILES, key=lambda x: x[0])
                SharePointFileList.extend(SharePointFileList_FOLDERS)
                SharePointFileList.extend(SharePointFileList_FILES)
                # pylint: disable=unbalanced-tuple-unpacking
                [headnote, footnote] = head_foot_note(
                    data, url, SharePointFileList)
                return make_response(render_template('sharepoint_main.html', headings=headings, BackgroundImage=BackgroundImage, SharePointFileList=SharePointFileList, headnote=headnote, footnote=footnote))
            if len(url.split('/')) > 1:
                # List files in path
                SharePointFileList = [
                    ['..', '', '', '/' + '/'.join(url.split('/')[0:-1])]]
                SharePointFileList_FOLDERS = []
                SharePointFileList_FILES = []
                site = data["Sites"][url.split('/')[0]]["site"]
                path = '/'.join(url.split('/')[1:])
                sharepointsite_path_files_dict = sharepointsite_path_files(
                    data, site, path)
                for i in sharepointsite_path_files_dict:
                    name = i
                    time = utc_local_convert(
                        sharepointsite_path_files_dict[i]['lastModifiedDateTime'])
                    size = sizeof_fmt(sharepointsite_path_files_dict[i]['size'])
                    if sharepointsite_path_files_dict[i]['type'] == 'folder':
                        SharePointFileList_FOLDERS.append(
                            [name, time, size, '/' + url + '/' + urllib.parse.quote(name)])
                    else:
                        SharePointFileList_FILES.append(
                            [name, time, size, '/' + url + '/' + urllib.parse.quote(name) + '?preview=1'])
                SharePointFileList_FOLDERS = os_sorted(SharePointFileList_FOLDERS, key=lambda x: x[0])
                SharePointFileList_FILES = os_sorted(SharePointFileList_FILES, key=lambda x: x[0])
                SharePointFileList.extend(SharePointFileList_FOLDERS)
                SharePointFileList.extend(SharePointFileList_FILES)
                # pylint: disable=unbalanced-tuple-unpacking
                [headnote, footnote] = head_foot_note(
                    data, url, SharePointFileList)
                return make_response(render_template('sharepoint_main.html', headings=headings, BackgroundImage=BackgroundImage, SharePointFileList=SharePointFileList, headnote=headnote, footnote=footnote))
        except:
            return make_response('Page Not Found', 404)
    elif DriveType == "OneDriveAPI":
        pass
    elif DriveType == "GoogleDriveAPI":
        pass
    else:
        return make_response("Drive Type Not Support.")

# 首頁，權限確認後列出帳號


@app.route("/", methods=['POST', 'GET'])
def home():
    def sharepointaccounts(data) -> list:
        return list(data['Sites'])

    headings = ['Name', 'Last edit time', 'Size']

    if not os.path.exists(CACHE_LOCATION):
        os.mkdir(CACHE_LOCATION)

    data = read_data()

    if data == None:
        return initialization(request)

    if request.args:
        for i in request.args:
            if i == "initialization":
                return initialization(request)
            elif i == "login":
                return login(request)
            elif i == "setting":
                return setting(request)
            elif i == "logout":
                return logout(request)
            elif i == "reflash":
                return reflash(request)
            elif i == "cookie":
                return cookie(request)
            elif i == "status":
                return status(request)
            elif i == "code":
                return make_response(request.args.get('code').split('&')[0])
            else:
                return redirect(request.base_url)

    if data["ApiOnedriveSetting"]["anonymous_viewlist"] == False and not loggined(data, request):
        response = login(request)
    else:
        SharePointFileList = []
        for i in sharepointaccounts(data):
            SharePointFileList.append([i, '', '', '/' + i])
        response = make_response(render_template('sharepoint_main.html', headings=headings,
                                 BackgroundImage=randombackground(data), SharePointFileList=SharePointFileList))
    return response


# 權限確認後列出檔案
@app.route("/<path:path>", methods=['POST', 'GET'])
def dir(path):
    if path.split('/')[0] == 'static':
        return send_file('./'+path)
    if path == 'favicon.ico':
        return '404'
    if not os.path.exists(CACHE_LOCATION):
        os.mkdir(CACHE_LOCATION)

    data = read_data()

    def decrypt(password, path):
        if request.form.get('password') == password:
            response = main(url=path)
        else:
            response = make_response(render_template(
                "sharepoint_encrypt.html", warning="密碼錯誤"))
        return response

    if data == None:
        return initialization(request)


    if request.args:
        for i in request.args:
            if i == "initialization":
                return initialization(request)
            elif i == "login":
                return login(request)
            elif i == "setting":
                return setting(request)
            elif i == "logout":
                return logout(request)
            elif i == "reflash":
                return reflash(path)
            elif i == "cookie":
                return cookie(request)
            elif i == "status":
                return status(request)
            elif i == "preview":
                return preview(request)
            elif i == "download":
                return download(path)
            elif i == "decrypt":
                pass
            elif i == "SharePointSiteAPI":
                return init_access_token(data, request)
            else:
                return redirect(request.base_url)
    else:
        if data["Sites"][path.split('/')[0]]["type"] == "SharePointSiteAPI":
            if data["Sites"][path.split('/')[0]]["refresh_token"] == "":
                return init_access_token(data, request)
            elif time.time() - data["Sites"][path.split('/')[0]]["t"] > 60*60:
                reflash_token(data, path.split('/')[0])
        if data["ApiOnedriveSetting"]["anonymous_viewlist"] == False and not loggined(data, request):
            response = redirect(request.base_url + '/?login=1')
        else:
            password = get_page_encrypt_pw(data, path)
            if password:
                if request.method == "POST":
                    response = decrypt(password, path)
                else:
                    response = make_response(render_template(
                        "sharepoint_encrypt.html", warning="加密資料夾，請輸入密碼"))
            else:
                response = main(url=path)
        return response


# Run the flask app.
if __name__ == '__main__':
    if not os.path.exists(CACHE_LOCATION):
        os.mkdir(CACHE_LOCATION)
    app.run(debug=False)
