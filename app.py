from __future__ import print_function
from flask import Flask,redirect,request,render_template,url_for,make_response
from flask_caching import Cache
import random, json, os, time, redis, hashlib, requests, urllib.parse, datetime, sys, re, base64, shutil
from http.cookiejar import CookieJar
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen, build_opener, HTTPCookieProcessor, Request
import xml.etree.ElementTree as ET


DEBUG = True

# 效能分析工具
if DEBUG:
    from flask import g
    from pyinstrument import Profiler


# 設定設定檔、金鑰存放位置
if os.name == 'nt': # Windows
    data_location = './data'
    cookies_location = './cookies'
else: # Linux、MacOS
    data_location = '/tmp/data'
    cookies_location = '/tmp/cookies'

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

# 設定網站快取存放位置
CACHE_LOCATION = './cache'

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


# 權限管理
def logout():
    if request.referrer:
        response = make_response(redirect(request.referrer))
    else:
        response = make_response(redirect(url_for('home')))
    response.set_cookie('user', '', path='/', expires=0)
    response.set_cookie('password', '', path='/', expires=0)
    return response

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

# @cache.cached(timeout=86400, make_cache_key='url', query_string=True)
@cache.memoize(timeout=86400, args_to_ignore=['account','site','path','download','_logout','_previousdirectory'])
def main(url,account = None,site = None,path = None,download = None,_logout = None,_previousdirectory = None):
    headings = ['Name', 'Last edit time', 'Size']
    data = read_data()
    def sharepointaccounts(data) -> list:
        response = []
        for i in data['SharePointAccountList']:
            response.append(i)
        return response
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
    def getdownloadlink(data, account, site, path) -> str:
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
    def previousdirectory(url) -> str:
        url = urllib.parse.unquote(url)
        if 'path' in url:
            if len(url.split('&')[2].split('/')) == 2:
                new_url = "&".join(url.split('&')[:-1])
            else:
                new_url = "&".join(url.split('&')[:-1])+'&'+urllib.parse.quote("/".join(url.split('&')[2].split('/')[:-1])).replace('%3D','=')
        elif 'site' in url:
            new_url = url.split('&')[0]
        return new_url


    BackgroundImageList = data['ApiOnedriveSetting']['backgroud_image_list']
    BackgroundImage = BackgroundImageList[random.randint(0, len(BackgroundImageList))-1]
    _url = url
    # logout = request.args.get('logout')
    if _previousdirectory:
        response = previousdirectory(_url)
    elif _logout:
        response = logout()
    elif download:
        downloadlink = getdownloadlink(data, account, site, path)
        if downloadlink == 0:
            response = make_response('Path is not file or not exist')
        else:
            response = make_response(redirect(downloadlink))
    elif path:
        # 列出路徑檔案
        SharePointFileList = [['..', '', '', previousdirectory(_url)]]
        sharepointsite_path_files = sharepointsite_path_files(data, account, site, path)
        for i in sharepointsite_path_files:
            name = i
            time = utc_local_convert(sharepointsite_path_files[i]['lastModifiedDateTime'])
            size = sizeof_fmt(sharepointsite_path_files[i]['size'])
            if sharepointsite_path_files[i]['type'] == 'folder':
                url = _url + '/' + urllib.parse.quote(name)
                SharePointFileList.append([name, time, size, url])
            else:
                url = _url + '/'  + urllib.parse.quote(name) + '&download=1'
                url = url.replace('http://','https://')
                SharePointFileList.append([name, time, size, url])
        response = make_response(render_template('sharepoint_main.html', headings = headings, BackgroundImage=BackgroundImage, SharePointFileList = SharePointFileList))
    elif site or path == '/':
        # 列出SharePoint網站根目錄
        SharePointFileList = [['..', '', '', previousdirectory(_url)]]
        sharepointsite_root_files = sharepointsite_root_files(data, account, site)
        for i in sharepointsite_root_files:
            name = i
            time = utc_local_convert(sharepointsite_root_files[i]['lastModifiedDateTime'])
            size = sizeof_fmt(sharepointsite_root_files[i]['size'])
            if sharepointsite_root_files[i]['type'] == 'folder':
                url = _url + '&path=/' + urllib.parse.quote(name)
                SharePointFileList.append([name, time, size, url])
            else:
                url = _url + '&path=/' + urllib.parse.quote(name) + '&download=1'
                url = url.replace('http://','https://')
                SharePointFileList.append([name, time, size, url])
        response = make_response(render_template('sharepoint_main.html', headings = headings, BackgroundImage=BackgroundImage, SharePointFileList = SharePointFileList))
    elif account:
        # 列出SharePoint帳號的網站
        SharePointFileList = [['..', '', '', url_for('home')]]
        for i in sharepointsites(data, account):
            detail = sharepointsite_details(data, account, i)
            SharePointFileList.append([i, utc_local_convert(detail['lastModifiedDateTime']), sizeof_fmt(detail['size']), _url + '&site=' + i])
        response = make_response(render_template('sharepoint_main.html', headings = headings, BackgroundImage=BackgroundImage, SharePointFileList = SharePointFileList))
    else:
        # 列出SharePoint帳號列表
        SharePointFileList = []
        for i in sharepointaccounts(data):
            SharePointFileList.append([i, '', '', _url + '?account=' + i])
        response = make_response(render_template('sharepoint_main.html', headings = headings, BackgroundImage=BackgroundImage, SharePointFileList = SharePointFileList))
    return response

@app.route("/initialization", methods=['POST','GET'])
def initialization():
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
                "anonymous_viewlist": True if anonymous_viewlist == '1' else False,
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
        reflash()
        return redirect(url_for('login'))


@app.route("/", methods=['POST','GET'])
def home():
    if not os.path.exists(CACHE_LOCATION):
        os.mkdir(CACHE_LOCATION)
    data = read_data()

    def getdownloadlink(data, account, site, path) -> str:
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

    account = request.args.get('account')
    site = request.args.get('site')
    path = request.args.get('path')
    path = urllib.parse.unquote(path) if path else path
    download = request.args.get('download')
    _logout = request.args.get('logout')
    _previousdirectory = request.args.get("_previousdirectory")
    url = request.url.replace(request.url_root,'')
    url = '/' + url

    if data == None:
        return redirect(url_for('initialization'))
    
    if 'download' in request.args:
        if data["ApiOnedriveSetting"]["anonymous_download"] == True:
            downloadlink = getdownloadlink(data, account, site, path)
            if downloadlink == 0:
                response = make_response('Path is not file or not exist')
            else:
                response = make_response(redirect(downloadlink))
        else:
            if loggined(data, request):
                downloadlink = getdownloadlink(data, account, site, path)
                if downloadlink == 0:
                    response = make_response('Path is not file or not exist')
                else:
                    response = make_response(redirect(downloadlink))
            else:
                response = redirect(url_for('login'))
    else:
        if data["ApiOnedriveSetting"]["anonymous_viewlist"] == True:
            response = main(url,account,site,path,download,_logout,_previousdirectory)
        else:
            if loggined(data, request):
                response = main(url,account,site,path,download,_logout,_previousdirectory)
            else:
                response = redirect(url_for('login'))
    return response

@app.route("/login", methods=['POST','GET'])
def login():
    data = read_data()
    users = data["ApiOnedriveSetting"]["users"]
    if request.method == 'GET':
        user = request.cookies.get('user')
        password = request.cookies.get('password')
        if user in users and users[user]["password"] == password:
            if request.referrer:
                url = request.referrer
                response = make_response(redirect(url))
            else:
                response = make_response(redirect(url_for('home')))
        else:
            response = make_response(render_template('sharepoint_login.html'))
    elif request.method == 'POST':
        user = request.form.get('user')
        password = request.form.get('password')
        pdhash = hashlib.sha256(password.encode()).hexdigest()
        if user in users and users[user]["password"] == pdhash:
            response = make_response(redirect(url_for('home')))
            response.set_cookie('user', user, path='/')
            response.set_cookie('password', pdhash, path='/')
        else:
            response = make_response(render_template('sharepoint_login.html', warning = '錯誤'))
    return response

@app.route("/setting", methods=['POST', 'GET'])
def setting():
    data = read_data()
    BackgroundImageList = data['ApiOnedriveSetting']['backgroud_image_list']
    BackgroundImage = BackgroundImageList[random.randint(0, len(BackgroundImageList))-1]

    if not loggined(data, request):
        response = redirect(url_for('login'))
    elif not is_admin(data, request) and loggined(data, request):
        response = 'Permission not allow'
    else:
        if 'logout' in request.args:
            response = logout()
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
            response = make_response(redirect(url_for("setting")))
        else:
            SharePointAccountList = data['SharePointAccountList']
            Users = data["ApiOnedriveSetting"]["users"]
            response = make_response(render_template('sharepoint_setting.html', Users=Users, SharePointAccountList=SharePointAccountList, backgroud_image_list=BackgroundImageList, BackgroundImage=BackgroundImage))

    return response


@app.route("/reflash")
def reflash():
    if request.referrer:
        url = request.referrer.split('//')[1]
        url = '/'.join(url.split('/')[1:])
        url = '/' + url
        url = urllib.parse.quote(url,safe='?=/:-&%')
        cache.delete_memoized(main, url)
        response = make_response(redirect(request.referrer))
    else:
        response = make_response(redirect(url_for("home")))
    return response

@app.route("/clc")
def clc():
    import shutil
    print('刪除中...')
    os.remove(data_location)
    os.remove(cookies_location)
    shutil.rmtree(CACHE_LOCATION)
    print('已刪除')
    data = read_data()
    print('變數已更新')
    data['TIME'] = time.time()
    write_data(data)
    print('已重新儲存')
    return 'success'


    
@app.route("/cookie")
def cookie():
    user = request.args.get("user")
    data = read_data()
    cookie = read_cookie(data["SharePointAccountList"][user]["endpoint"], user, data["SharePointAccountList"][user]["password"])
    return cookie

@app.route("/status")
def status():
    return 'Online'

if __name__ == '__main__':
    app.run()