from __future__ import print_function
from flask import Flask,redirect,request,render_template,url_for,make_response, Markup
from flask_caching import Cache
import random, json, os, time, redis, hashlib, requests, urllib.parse, datetime, sys, re, base64, shutil, chardet, markdown
from http.cookiejar import CookieJar
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen, build_opener, HTTPCookieProcessor, Request
import xml.etree.ElementTree as ET


DEBUG = False

# 效能分析工具
if DEBUG:
    from flask import g
    from pyinstrument import Profiler


# 設定設定檔、金鑰、快取存放位置
if os.name == 'nt': # Windows
    CACHE_LOCATION = './cache'
    data_location = './data'
    cookies_location = './cookies'
else: # Linux、MacOS
    data_location = '/tmp/data'
    cookies_location = '/tmp/cookies'
    CACHE_LOCATION = './cache'

# 如果你的資料庫擁有上萬文件，可以適當調高此參數(建議不高於5000)
REQUEST_SIZE = 2000

# 設定是否由資料庫同步資料
Redis_sync = False

# 設定資料庫
if Redis_sync:
    REDIS = redis.Redis(
        host= 'global-liked-dassie-31251.upstash.io',
        port= '31251',
        password= '585f5b3af15540d381dc46bf429a7420',
        ssl=True,
        decode_responses=True
    )
    # 設定同步資料間隔時間
    Redis_sync_expires = 432000
    # 設定資料庫鍵
    Redis_sync_key = 'data'


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

def discover_sts(username:str):
    request = urlopen("https://login.microsoft.com/GetUserRealm.srf", "login={}&xml=1".format(username).encode('utf-8'))
    resp = ET.parse(request)
    nstype = resp.find("./NameSpaceType")
    if nstype is None:
        raise RuntimeError("Invalid GetUserRealm response - missing namespace type")
    if nstype.text == "Federated":
        stsurl = resp.find("./STSAuthURL")
        if stsurl is None:
            raise RuntimeError("Invalid GetUserRealm response - missing STS URL")
        return stsurl.text
    else:
        return None

def buildAuthXmlManaged(username, password, endpoint):
    return authXmlManaged.format(username, password, endpoint)

def getSecurityTokenManaged(username, password, endpoint):
    authReq = buildAuthXmlManaged(username, password, endpoint)
    try:
        request = urlopen("https://login.microsoftonline.com/extSTS.srf", authReq.encode('utf-8'))
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
        raise RuntimeError("Railed to retrieve authentication token: {}".format(reason))
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
    nonce = base64.standard_b64encode(bytearray(random.getrandbits(8) for _ in range(32)))
    return authXmlFederated.format(stsurl, ctime_str, etime_str, username, password, nonce.decode('utf-8'))

def buildAuthXmlFederated2(assertion):
    return authXmlFederated2.format(assertion)

def getSecurityTokenFederated(username, password, endpoint, stsurl):
    authReq = buildAuthXmlFederated(username, password, stsurl)
    try:
        req = Request(stsurl, authReq.encode('utf-8'), {"Content-Type": "application/soap+xml; charset=utf-8"})
        request = urlopen(req)
    except URLError as x:
        raise RuntimeError("Failed to send login request.")
    ns = {"soap": "http://www.w3.org/2003/05/soap-envelope",
          "wssec": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd",
          "saml": "urn:oasis:names:tc:SAML:1.0:assertion"}
    # The assertion must be copied into the second request as-is without any processing as it contains a signature.
    text = request.read()
    match = re.search(r"<saml:Assertion .*</saml:Assertion>", text.decode('utf-8'))
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
        raise RuntimeError("Railed to retrieve authentication token: {}".format(reason))
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
            authToken = getSecurityTokenFederated(username, password, endpoint, stsurl)
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
            #print(cookieStr)
            return cookieStr
        except:
            from office365.runtime.auth.user_credential import UserCredential
            from office365.sharepoint.client_context import ClientContext
            user_credentials = UserCredential(username,password)
            ctx = ClientContext(endpoint).with_credentials(user_credentials)
            ctx.load(ctx.web)
            ctx.execute_query()
            cookieStr = 'rtFa='+vars(vars(vars(ctx)['_auth_context'])['_provider'])['_cached_auth_cookies']['rtFa']+'; FedAuth='+vars(vars(vars(ctx)['_auth_context'])['_provider'])['_cached_auth_cookies']['FedAuth']
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
                    data['TIME']= T
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
                data['TIME']= T
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
                cookies[username] = {'cookie': get_cookie(endpoint, username, password), 'TIME': T}
                print('線上取得憑證...')
                with open(cookies_location, 'w') as f:
                    f.write(json.dumps(cookies))
                    print('寫入憑證...')
            print('成功讀取憑證')
        else:
            print('用戶不存在...')
            T = time.time()
            cookies[username] = {'cookie': get_cookie(endpoint, username, password), 'TIME': T}
            print('線上取得憑證...')
            with open(cookies_location, 'w') as f:
                f.write(json.dumps(cookies))
                print('寫入憑證...')
            print('成功讀取憑證')
    else:
        print('不存在憑證資料...')
        cookies = {}
        T = time.time()
        cookies[username] = {'cookie': get_cookie(endpoint, username, password), 'TIME': T}
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
    url = urllib.parse.quote(url,safe='/?=')
    return url

def randombackground(data):
    BackgroundImageList = data['ApiOnedriveSetting']['backgroud_image_list']
    BackgroundImage = BackgroundImageList[random.randint(0, len(BackgroundImageList))-1]
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
        endpoint = request.form.get('Host')
        account = request.form.get('Account')
        password = request.form.get('Password')
        sites = request.form.get('Sites')
        data = {
            "SharePointAccountList": {
                account: {
                    "endpoint": endpoint if endpoint[-1] == '/' else endpoint + '/',
                    "username": account,
                    "password": password,
                    "sites": sites.split(',')[:-1]
                }
            },
            "ApiOnedriveSetting": {
                "backgroud_image_list": BackgroundImageList.split(',')[:-1],
                "anonymous_viewlist": True if anonymous_viewlist == '0' else False,
                "anonymous_download": True if anonymous_download == '0' else False,
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
        data['TIME']= T
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
            response = make_response(render_template('sharepoint_login.html', warning = '錯誤'))
    return response



# 設定頁面，?setting時執行
def setting(request):
    data = read_data()
    BackgroundImageList = data['ApiOnedriveSetting']['backgroud_image_list']
    BackgroundImage = BackgroundImageList[random.randint(0, len(BackgroundImageList))-1]

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
                data["ApiOnedriveSetting"]["backgroud_image_list"] = BackgroundImageList.split(',')[:-1]
                data["ApiOnedriveSetting"]["anonymous_viewlist"] = True if anonymous_viewlist == '0' else False
                data["ApiOnedriveSetting"]["anonymous_download"] = True if anonymous_download == '0' else False
                data["ApiOnedriveSetting"]["CACHE_TYPE"] = CACHE_TYPE
            elif 'Host' in request.form:
                endpoint = request.form.get('Host')
                account = request.form.get('Account')
                password = request.form.get('Password')
                sites = request.form.get('Sites')
                data["SharePointAccountList"][account] = {
                    "endpoint": endpoint,
                    "username": account,
                    "password": password,
                    "sites": sites.split(',')[:-1]
                }
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
            SharePointAccountList = data['SharePointAccountList']
            Users = data["ApiOnedriveSetting"]["users"]
            response = make_response(render_template('sharepoint_setting.html', Users=Users, SharePointAccountList=SharePointAccountList, backgroud_image_list=BackgroundImageList, BackgroundImage=BackgroundImage))
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
            with open("claer-cache-arg",'w') as f:
                f.write(path)
        cache.delete_memoized(main, path)
        response = make_response(redirect(request.referrer))
    else:
        response = make_response(redirect(url_for("home")))
    return response



# 返回下載地址，?download時執行
def getdownloadlink(data, account, site, path):
    endpoint = data['SharePointAccountList'][account]["endpoint"]
    username = data['SharePointAccountList'][account]["username"]
    password = data['SharePointAccountList'][account]["password"]
    cookie = read_cookie(endpoint, username, password)
    header = {'cookie': cookie, 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
    path = urllib.parse.quote(path)
    url = endpoint + '_api/v2.1/sites/' + endpoint.split('.')[0].split('/')[-1] + '.sharepoint.com:/sites/' + site + ':/drive/root:' + path
    r = requests.get(url, headers=header).text
    r = json.loads(r)
    return r['@content.downloadUrl'] if '@content.downloadUrl' in r else 0


# 回傳使用者憑證，?cookie=user時執行
def cookie(request):
    user = request.args.get("cookie")
    data = read_data()
    cookie = read_cookie(data["SharePointAccountList"][user]["endpoint"], user, data["SharePointAccountList"][user]["password"])
    return cookie



# 回傳網站狀態，?status時執行
def status(request):
    return 'Online'

# 辨認檔案型態
def get_file_type(extension):
        extension = extension.lower()
        video_extensions = [".mp4", ".mkv", ".flv", ".avi", ".mov", ".wmv"]
        image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp"]
        audio_extensions = [".mp3", ".wav", ".flac", ".aac"]
        document_extensions = [".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"]
        text_extensions = [".txt"]
        program_extensions = [".json",".py",".c",".cpp",".java",".html",".htm"]

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
        account = request.path.split('/')[1]
        site = request.path.split('/')[2]
        path = '/'.join(request.path.split('/')[3:])
        txt = requests.get(getdownloadlink(data, account, site, path)).content
        code = chardet.detect(txt)['encoding']
        txt = txt.decode(code)
    elif mediatype == 'programe':
        account = request.path.split('/')[1]
        site = request.path.split('/')[2]
        path = '/'.join(request.path.split('/')[3:])
        txt = requests.get(getdownloadlink(data, account, site, path)).text
        txt = '```'  + request.path.split('.')[-1] + '\n' + txt + '\n```'
        exts = ['markdown.extensions.extra', 'markdown.extensions.codehilite','markdown.extensions.tables','markdown.extensions.toc']
        txt = markdown.markdown(txt,extensions=exts)
        txt = Markup(txt)
    else:
        txt = ''
    return make_response(render_template("sharepoint_preview.html",source=request.url.replace('preview=1','download=1'),mediatype=mediatype,name=urllib.parse.unquote(request.base_url.split('/')[-1]),txt=txt))

def download(url):
    data = read_data()
    # 檢查權限
    if data["ApiOnedriveSetting"]["anonymous_download"] == False and not loggined(data, request):
        return login(request)
    account = url.split('/')[0]
    site = url.split('/')[1]
    path = '/'.join(url.split('/')[2:])
    return redirect(getdownloadlink(data, account, site, path))

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
        with open("cache-arg",'w') as f:
            f.write(url)
    def sharepointsites(data, account) -> list:
        response = data['SharePointAccountList'][account]["sites"]
        return response
    def sharepointsite_details(data, account, site) -> dict:
        endpoint = data['SharePointAccountList'][account]["endpoint"]
        username = data['SharePointAccountList'][account]["username"]
        password = data['SharePointAccountList'][account]["password"]
        cookie = read_cookie(endpoint, username, password)
        header = {'cookie': cookie, 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
        url = endpoint + '_api/v2.1/sites/' + endpoint.split('.')[0].split('/')[-1] + '.sharepoint.com:/sites/' + site + ':/drive/root'
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
            response[i["name"]] = {"type": "folder" if "folder" in i else "file", "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
        if "@odata.nextLink" in r:
            response.update(nextpage(header, r["@odata.nextLink"]))
        return response
    def sharepointsite_root_files(data, account, site) -> dict:
        # {name: {"type": folder/file, "lastModifiedDateTime": time, "size": size}}
        response = {}
        endpoint = data['SharePointAccountList'][account]["endpoint"]
        username = data['SharePointAccountList'][account]["username"]
        password = data['SharePointAccountList'][account]["password"]
        cookie = read_cookie(endpoint, username, password)
        header = {'cookie': cookie, 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
        url = endpoint + '_api/v2.1/sites/' + endpoint.split('.')[0].split('/')[-1] + '.sharepoint.com:/sites/' + site + ':/drive/root/children?$top='+str(REQUEST_SIZE)+'&select=name,folder,lastModifiedDateTime,size'
        r = requests.get(url, headers=header).text
        r = json.loads(r)
        if DEBUG:
            print(url,r)
        for i in r['value']:
            response[i["name"]] = {"type": "folder" if "folder" in i else "file", "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
        if "@odata.nextLink" in r:
            response.update(nextpage(header, r["@odata.nextLink"]))
        return response
    def sharepointsite_path_files(data, account, site, path) -> dict:
        # {name: {"type": folder/file, "lastModifiedDateTime": time, "size": size}}
        response = {}
        endpoint = data['SharePointAccountList'][account]["endpoint"]
        username = data['SharePointAccountList'][account]["username"]
        password = data['SharePointAccountList'][account]["password"]
        cookie = read_cookie(endpoint, username, password)
        header = {'cookie': cookie, 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
        path = urllib.parse.quote(path)
        url = endpoint + '_api/v2.1/sites/' + endpoint.split('.')[0].split('/')[-1] + '.sharepoint.com:/sites/' + site + ':/drive/root:' + path + ':/children?$top='+str(REQUEST_SIZE)+'&select=name,folder,lastModifiedDateTime,size'
        r = requests.get(url, headers=header).text
        r = json.loads(r)
        if DEBUG:
            print(r)
        for i in r['value']:
            response[i["name"]] = {"type": "folder" if "folder" in i else "file", "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
        if "@odata.nextLink" in r:
            response.update(nextpage(header, r["@odata.nextLink"]))
        return response
    headings = ['Name', 'Last edit time', 'Size']
    data = read_data()
    BackgroundImageList = data['ApiOnedriveSetting']['backgroud_image_list']
    BackgroundImage = BackgroundImageList[random.randint(0, len(BackgroundImageList))-1]
    if url[-1] == '/':
        url = url[:-1]
    if len(url.split('/')) == 1:
        SharePointFileList = [['..', '', '', '/']]
        account = url.split('/')[0]
        for i in sharepointsites(data, account):
            detail = sharepointsite_details(data, account, i)
            SharePointFileList.append([i, utc_local_convert(detail['lastModifiedDateTime']), sizeof_fmt(detail['size']), '/' + url + '/' + i])
        return make_response(render_template('sharepoint_main.html', headings = headings, BackgroundImage=BackgroundImage, SharePointFileList = SharePointFileList))
    if len(url.split('/')) == 2:
        SharePointFileList = [['..', '', '', '/'+ url.split('/')[0]]]
        account = url.split('/')[0]
        site = url.split('/')[1]
        sharepointsite_root_files_dict = sharepointsite_root_files(data, account, site)
        for i in sharepointsite_root_files_dict:
            name = i
            time = utc_local_convert(sharepointsite_root_files_dict[i]['lastModifiedDateTime'])
            size = sizeof_fmt(sharepointsite_root_files_dict[i]['size'])
            if sharepointsite_root_files_dict[i]['type'] == 'folder':
                SharePointFileList.append([name, time, size, '/' + url + '/' + urllib.parse.quote(name)])
            else:
                SharePointFileList.append([name, time, size, '/' + url + '/' + urllib.parse.quote(name) + '?preview=1'])
        return make_response(render_template('sharepoint_main.html', headings = headings, BackgroundImage=BackgroundImage, SharePointFileList = SharePointFileList))
    if len(url.split('/')) > 2:
        SharePointFileList = [['..', '', '', '/' + url.split('/')[0] + '/' + '/'.join(url.split('/')[1:-1])]]
        account = url.split('/')[0]
        site = url.split('/')[1]
        path = '/'.join(url.split('/')[2:])
        sharepointsite_path_files_dict = sharepointsite_path_files(data, account, site, path)
        for i in sharepointsite_path_files_dict:
            name = i
            time = utc_local_convert(sharepointsite_path_files_dict[i]['lastModifiedDateTime'])
            size = sizeof_fmt(sharepointsite_path_files_dict[i]['size'])
            if sharepointsite_path_files_dict[i]['type'] == 'folder':
                SharePointFileList.append([name, time, size, '/' + url + '/' + urllib.parse.quote(name)])
            else:
                SharePointFileList.append([name, time, size, '/' + url + '/' + urllib.parse.quote(name) + '?preview=1'])
        return make_response(render_template('sharepoint_main.html', headings = headings, BackgroundImage=BackgroundImage, SharePointFileList = SharePointFileList))


# 首頁，權限確認後列出帳號
@app.route("/", methods=['POST','GET'])
def home():
    def sharepointaccounts(data) -> list:
        response = []
        for i in data['SharePointAccountList']:
            response.append(i)
        return response

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
            else:
                return redirect(request.base_url)
            
    
    if data["ApiOnedriveSetting"]["anonymous_viewlist"] == False and not loggined(data, request):
        response = login(request)
    else:
        SharePointFileList = []
        for i in sharepointaccounts(data):
            SharePointFileList.append([i, '', '', '/' + i])
        response = make_response(render_template('sharepoint_main.html', headings=headings, BackgroundImage=randombackground(data), SharePointFileList=SharePointFileList))
    return response


# 權限確認後列出檔案
@app.route("/<path:path>", methods=['POST','GET'])
def dir(path):
    if path == 'favicon.ico':
        return '404'
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
                return reflash(path)
            elif i == "cookie":
                return cookie(request)
            elif i == "status":
                return status(request)
            elif i == "preview":
                return preview(request)
            elif i == "download":
                return download(path)
            else:
                return redirect(request.base_url)
            
    if data["ApiOnedriveSetting"]["anonymous_viewlist"] == False and not loggined(data, request):
        response = redirect(request.base_url + '/?login=1')
    else:
        response = main(url=path)
    return response


# Run the flask app.
if __name__ == '__main__':
    if not os.path.exists(CACHE_LOCATION):
        os.mkdir(CACHE_LOCATION)
    app.run(debug=False)