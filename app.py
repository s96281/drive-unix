from __future__ import print_function
from flask import Flask,redirect,request,render_template,url_for,make_response
from ansi2html import Ansi2HTMLConverter
import random, json, os, time, redis, subprocess, archey, hashlib, requests, urllib.parse, datetime
from http.cookiejar import CookieJar
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen, build_opener, HTTPCookieProcessor, Request
import base64
import random
import re
import sys
import time
import xml.etree.ElementTree as ET


#設定資料庫
REDIS = redis.Redis(
  host= 'usw2-stable-sunfish-30320.upstash.io',
  port= '30320',
  password= 'ef2629d1f9ee4d61bf9b41bf6c738da0',
  decode_responses=True
)

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

def discover_sts(username):
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
    # if len(sys.argv) < 3:
    #     print("Usage: get-sharepoint-auth-cookie.py endpointURL username password", file=sys.stderr)
    #     exit(1)

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
    except URLError as x:
        print("Failed to login to SharePoint site: {}".format(x.reason))
        exit(1)

def read_data() -> dict:
    DatasNeedRead = ['SharePointAccountList','ApiOnedriveSetting']
    print('讀取資料中...')
    if os.path.isfile('/tmp/data'):
        print('存在緩存資料...')
        f = open('/tmp/data')
        data = json.loads(f.read())
        print('讀取緩存資料...')
        f.close()
        if data['TIME'] < (time.time()-432000):
            print('緩存過期...')
            data = {}
            for i in DatasNeedRead:
                data[i] = REDIS.hgetall(i)
            print('線上取得資料...')
            T = time.time()
            data['TIME']= T
            with open('/tmp/data', 'w') as f:
                print('寫入緩存...')
                f.write(json.dumps(data))
        print('成功讀取資料')
    else:
        print('不存在緩存資料...')
        data = {}
        for i in DatasNeedRead:
            data[i] = REDIS.hgetall(i)
        print('線上取得資料...')
        T = time.time()
        data['TIME']= T
        with open('/tmp/data', 'w') as f:
            print('寫入緩存...')
            f.write(json.dumps(data))
        print('成功讀取資料')
    return data

def read_cookie(endpoint, username, password) -> str:
    print('讀取憑證中...')
    if os.path.isfile('/tmp/cookies'):
        print('存在憑證資料...')
        f = open('/tmp/cookies')
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
                with open('/tmp/cookies', 'w') as f:
                    f.write(json.dumps(cookies))
                    print('寫入憑證...')
            print('成功讀取憑證')
        else:
            print('用戶不存在...')
            T = time.time()
            cookies[username] = {'cookie': get_cookie(endpoint, username, password), 'TIME': T}
            print('線上取得憑證...')
            with open('/tmp/cookies', 'w') as f:
                f.write(json.dumps(cookies))
                print('寫入憑證...')
            print('成功讀取憑證')
    else:
        print('不存在憑證資料...')
        cookies = {}
        T = time.time()
        cookies[username] = {'cookie': get_cookie(endpoint, username, password), 'TIME': T}
        print('線上取得憑證...')
        with open('/tmp/cookies', 'w') as f:
            f.write(json.dumps(cookies))
            print('寫入憑證...')
        print('成功讀取憑證')
    return cookies[username]['cookie']

def sizeof_fmt(num, suffix="B") -> str:
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"

def getdownloadlink(account, site, file) -> str:
    url = 'https://'+ account.split('@')[1].replace('.','') +'.sharepoint.com/_api/v2.1/sites/'+ account.split('@')[1].replace('.','') +'.sharepoint.com:/sites/'+ site +':/drive/root:/'+file
    if 'root:' in url:
        url = 'https://'+ account.split('@')[1].replace('.','') +'.sharepoint.com/_api/v2.1'+ urllib.parse.quote(file)  
    with open('/tmp/cookies', 'r') as f:
        cookie = json.loads(f.read())[account]['cookie']
    header = {'cookie': cookie, 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
    r = json.loads(requests.get(url, headers = header).text)
    return r['@content.downloadUrl']

def utc_local_convert(time) -> str:
    utc = time
    UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
    utcTime = datetime.datetime.strptime(utc, UTC_FORMAT)
    localtime = utcTime + datetime.timedelta(hours=8)
    return localtime.ctime()

app = Flask(__name__)

@app.route("/")
def index():
    conv = Ansi2HTMLConverter()
    ansi = "".join(subprocess.check_output('archey',text=True))
    #print(subprocess.check_output('archey',text=True))
    html = conv.convert(ansi)
    return html

@app.route("/clc")
def clc():
    print('刪除中...')
    os.remove('/tmp/data')
    os.remove('/tmp/cookies')
    print('已刪除')
    data = read_data()
    print('變數已更新')
    data['TIME'] = time.time()
    with open('/tmp/data', 'w') as f:
        f.write(json.dumps(data))
    print('已重新儲存')
    return 'success'

@app.route("/api")
def api():
    return render_template('api.html')


@app.route("/api/onedrive/login", methods=['POST','GET'])
def api_onedrive_login():
    data = read_data()
    user_hash = json.loads(data['ApiOnedriveSetting']['user_hash'])
    if request.method == 'GET':
        user = request.cookies.get('user')
        password = request.cookies.get('password')
        if user in user_hash and user_hash[user] == password:
            response = make_response(redirect('/api/onedrive'))
        else:
            response = make_response(render_template('api_onedrive_input.html', function = 'inputaccount'))
    elif request.method == 'POST':
        user = request.form.get('user')
        password = request.form.get('password')
        pdhash = hashlib.sha256(password.encode()).hexdigest()
        if user in user_hash and user_hash[user] == pdhash:
            response = make_response(redirect('/api/onedrive'))
            response.set_cookie('user', user, path='/')
            response.set_cookie('password', pdhash, path='/')
        else:
            response = make_response(render_template('api_onedrive_input.html', function = 'inputaccount', warning = '錯誤'))
    return response

@app.route("/api/onedrive", methods=['POST','GET'])
def api_onedrive():
    headings = ['Name', 'Last edit time', 'Size', 'Link']
    def checkpermissionornot(data) -> bool:
        if data['ApiOnedriveSetting']['checkpermissionornot'] == '1':
            return True
        return False
    def checkpermission(request) -> bool:
        user = request.cookies.get('user')
        password = request.cookies.get('password')
        try:
            hash = user_hash[request.cookies.get('user')]
        except:
            hash = ''
        if user and password and hash == password:
            return False
        return True
    def sharepointaccounts(data) -> list:
        response = []
        for i in data['SharePointAccountList']:
            response.append(i)
        return response
    def sharepointsites(data, account) -> list:
        response = data['SharePointAccountList'][account]
        response = json.loads(response)[-1].split(' ')
        return response
    def sharepointsite_details(data, account, site) -> dict:
        [[endpoint, username, password], sites] = [json.loads(data['SharePointAccountList'][account])[:-1],json.loads(data['SharePointAccountList'][account])[-1].split(' ')]
        cookie = read_cookie(endpoint, username, password)
        header = {'cookie': cookie, 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
        domain = account.split('@')[-1].replace('.','')
        url = 'https://' + domain + '.sharepoint.com/_api/v2.1/sites/' + domain + '.sharepoint.com:/sites/' + site + ':/drive/root'
        r = requests.get(url, headers=header).text
        r = json.loads(r)
        return r
    def sharepointsite_root_files(data, account, site) -> dict:
        # {name: {"type": folder/file, "lastModifiedDateTime": time, "size": size}}
        response = {}
        [[endpoint, username, password], sites] = [json.loads(data['SharePointAccountList'][account])[:-1],json.loads(data['SharePointAccountList'][account])[-1].split(' ')]
        cookie = read_cookie(endpoint, username, password)
        header = {'cookie': cookie, 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
        domain = account.split('@')[-1].replace('.','')
        url = 'https://' + domain + '.sharepoint.com/_api/v2.1/sites/' + domain + '.sharepoint.com:/sites/' + site + ':/drive/root/children'
        r = requests.get(url, headers=header).text
        r = json.loads(r)
        for i in r['value']:
            response[i["name"]] = {"type": "folder" if "folder" in i else "file", "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
        return response
    def sharepointsite_path_files(data, account, site, path) -> dict:
        # {name: {"type": folder/file, "lastModifiedDateTime": time, "size": size}}
        response = {}
        [[endpoint, username, password], sites] = [json.loads(data['SharePointAccountList'][account])[:-1],json.loads(data['SharePointAccountList'][account])[-1].split(' ')]
        cookie = read_cookie(endpoint, username, password)
        header = {'cookie': cookie, 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
        domain = account.split('@')[-1].replace('.','')
        path = urllib.parse.quote(path)
        url = 'https://' + domain + '.sharepoint.com/_api/v2.1/sites/' + domain + '.sharepoint.com:/sites/' + site + ':/drive/root:' + path + ':/children'
        r = requests.get(url, headers=header).text
        r = json.loads(r)
        for i in r['value']:
            response[i["name"]] = {"type": "folder" if "folder" in i else "file", "lastModifiedDateTime": i["lastModifiedDateTime"], "size": i["size"]}
        return response
    def getdownloadlink(data, account, site, path) -> str:
        [[endpoint, username, password], sites] = [json.loads(data['SharePointAccountList'][account])[:-1],json.loads(data['SharePointAccountList'][account])[-1].split(' ')]
        cookie = read_cookie(endpoint, username, password)
        header = {'cookie': cookie, 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0', 'Sec-Fetch-User': '?1'}
        domain = account.split('@')[-1].replace('.','')
        path = urllib.parse.quote(path)
        url = 'https://' + domain + '.sharepoint.com/_api/v2.1/sites/' + domain + '.sharepoint.com:/sites/' + site + ':/drive/root:' + path
        r = requests.get(url, headers=header).text
        r = json.loads(r)
        return r['@content.downloadUrl'] if '@content.downloadUrl' in r else 0
    def logout():
        response = make_response(redirect('/api/onedrive'))
        response.set_cookie('user', '', path='/', expires=0)
        response.set_cookie('password', '', path='/', expires=0)
        return response
    def previousdirectory(url) -> str:
        url = urllib.parse.unquote(url)
        if 'path' in url:
            if len(url.split('&')[2].split('/')) == 2:
                new_url = "&".join(url.split('&')[:-1])
            else:
                new_url = "&".join(url.split('&')[:-1])+'&'+urllib.parse.quote("/".join(url.split('&')[2].split('/')[:-1])).replace('%3D','=')
        elif 'site' in url:
            new_url = url.split('&')[0]
        elif 'account' in url:
            new_url = url.split('?')[0]
        return new_url

    # 讀取網站設定等資料
    data = read_data()
    BackgroundImageList = json.loads(data['ApiOnedriveSetting']['backgroud_image_list'])
    BackgroundImage = BackgroundImageList[random.randint(0, len(BackgroundImageList))-1]

    user_hash = json.loads(data['ApiOnedriveSetting']['user_hash'])
    account = request.args.get('account')
    site = request.args.get('site')
    path = request.args.get('path')
    path = urllib.parse.unquote(path) if path else path
    download = request.args.get('download')

    if checkpermissionornot(data) and checkpermission(request):
        response = redirect('/api/onedrive/login')
    else:
        # logout = request.args.get('logout')
        if 'previousdirectory' in request.args:
            response = previousdirectory(request.url)
        elif 'logout' in request.args:
            response = logout()
        elif download:
            downloadlink = getdownloadlink(data, account, site, path)
            if downloadlink == 0:
                response = make_response('Path is not file or not exist')
            else:
                response = make_response(redirect(downloadlink))
        elif path:
            # 列出路徑檔案
            SharePointFileList = [['..', '', '', previousdirectory(request.url)]]
            sharepointsite_path_files = sharepointsite_path_files(data, account, site, path)
            for i in sharepointsite_path_files:
                name = i
                time = utc_local_convert(sharepointsite_path_files[i]['lastModifiedDateTime'])
                size = sizeof_fmt(sharepointsite_path_files[i]['size'])
                if sharepointsite_path_files[i]['type'] == 'folder':
                    SharePointFileList.append([name, time, size, request.url + '/' + urllib.parse.quote(name)])
                else:
                    SharePointFileList.append([name, time, size, request.url + '/'  + urllib.parse.quote(name) + '&download=1'])
            response = make_response(render_template('api_onedrive_input.html', function = 'listfiles', headings = headings, BackgroundImage=BackgroundImage, SharePointFileList = SharePointFileList))
        elif site or path == '/':
            # 列出SharePoint網站根目錄
            SharePointFileList = [['..', '', '', previousdirectory(request.url)]]
            sharepointsite_root_files = sharepointsite_root_files(data, account, site)
            for i in sharepointsite_root_files:
                name = i
                time = utc_local_convert(sharepointsite_root_files[i]['lastModifiedDateTime'])
                size = sizeof_fmt(sharepointsite_root_files[i]['size'])
                if sharepointsite_root_files[i]['type'] == 'folder':
                    SharePointFileList.append([name, time, size, request.url + '&path=/' + urllib.parse.quote(name)])
                else:
                    SharePointFileList.append([name, time, size, request.url + '&path=/' + urllib.parse.quote(name) + '&download=1'])
            response = make_response(render_template('api_onedrive_input.html', function = 'listfiles', headings = headings, BackgroundImage=BackgroundImage, SharePointFileList = SharePointFileList))
        elif account:
            # 列出SharePoint帳號的網站
            SharePointFileList = [['..', '', '', previousdirectory(request.url)]]
            for i in sharepointsites(data, account):
                detail = sharepointsite_details(data, account, i)
                SharePointFileList.append([i, utc_local_convert(detail['lastModifiedDateTime']), sizeof_fmt(detail['size']), request.url + '&site=' + i])
            response = make_response(render_template('api_onedrive_input.html', function = 'listfiles', headings = headings, BackgroundImage=BackgroundImage, SharePointFileList = SharePointFileList))
        else:
            # 列出SharePoint帳號列表
            SharePointFileList = []
            for i in sharepointaccounts(data):
                SharePointFileList.append([i, '', '', request.url + '?account=' + i])
            response = make_response(render_template('api_onedrive_input.html', function = 'listfiles', headings = headings, BackgroundImage=BackgroundImage, SharePointFileList = SharePointFileList))
    return response

@app.route("/api/onedrive/setting", methods=['POST', 'GET'])
def api_onedrive_setting():
    def checkpermission(request) -> bool:
        user = request.cookies.get('user')
        password = request.cookies.get('password')
        try:
            hash = user_hash[request.cookies.get('user')]
        except:
            hash = ''
        if user and password and hash == password:
            return False
        return True
    def addsharepointaccout(data, endpoint, account, password, sites) -> bool:
        try:
            data['SharePointAccountList'][account] = json.dumps([endpoint, account, password, sites])
            REDIS.hset('SharePointAccountList', account, data['SharePointAccountList'][account])
            with open('/tmp/data', 'w') as f:
                f.write(json.dumps(data))
            return True
        except:
            return False
    def addsharepointsite(data, account, site) -> bool:
        # Add site to account that exist.
        try:
            [[endpoint, username, password], sites] = [json.loads(data['SharePointAccountList'][account])[:-1],json.loads(data['SharePointAccountList'][account])[-1].split(' ')]
            sites.append(site)
            data['SharePointAccountList'][account] = json.dumps([endpoint, username, password, " ".join(sites)])
            REDIS.hset('SharePointAccountList', account, data['SharePointAccountList'][account])
            with open('/tmp/data', 'w') as f:
                f.write(json.dumps(data))
            return True
        except:
            return False
    def delsharepointaccout(data, account) -> bool:
        try:
            data['SharePointAccountList'].pop(account, None)
            REDIS.hset('SharePointAccountList', account, data['SharePointAccountList'][account])
            with open('/tmp/data', 'w') as f:
                f.write(json.dumps(data))
            return True
        except:
            return False
    def delsharepointsite(data, account, site) -> bool:
        try:
            [[endpoint, username, password], sites] = [json.loads(data['SharePointAccountList'][account])[:-1],json.loads(data['SharePointAccountList'][account])[-1].split(' ')]
            sites.remove(site)
            data['SharePointAccountList'][account] = json.dumps([endpoint, username, password, " ".join(sites)])
            REDIS.hset('SharePointAccountList', account, data['SharePointAccountList'][account])
            with open('/tmp/data', 'w') as f:
                f.write(json.dumps(data))
            return True
        except:
            return False
    def logout():
        response = make_response(redirect('/api/onedrive'))
        response.set_cookie('user', '', path='/', expires=0)
        response.set_cookie('password', '', path='/', expires=0)
        return response
    def adduser(user, password) -> bool:
        try:
            data['ApiOnedriveSetting']['user_hash'][user] = json.dumps(hashlib.sha256(password.encode()).hexdigest())
            REDIS.hset('ApiOnedriveSetting', 'user_hash', data['ApiOnedriveSetting']['user_hash'])
            with open('/tmp/data', 'w') as f:
                f.write(json.dumps(data))
            return True
        except:
            return False
    def deluser(user) -> bool:
        try:
            user_hash = json.loads(data['ApiOnedriveSetting']['user_hash']).pop(user, None)
            data['ApiOnedriveSetting']['user_hash'] = json.dumps(user_hash)
            REDIS.hset('ApiOnedriveSetting', 'user_hash', data['ApiOnedriveSetting']['user_hash'])
            with open('/tmp/data', 'w') as f:
                f.write(json.dumps(data))
            return True
        except:
            return False
    def UpdateBackgroundImage(list) -> bool:
        pass


    data = read_data()
    user_hash = json.loads(data['ApiOnedriveSetting']['user_hash'])

    if checkpermission(request):
        response = redirect('/api/onedrive/login')
    else:
        if 'logout' in request.args:
            response = logout()
    response = make_response(render_template('api_onedrive_input.html', function = 'setting'))

    return response


@app.route("/api/onedrive/upload", methods=['POST', 'GET'])
def api_onedrive_upload():
    pass


@app.route("/api/b8s6", methods=['POST', 'GET'])
def api_b8s6():
    cookie = 'addinfo=%7B%22chkadmin%22%3A1%2C%22chkarticle%22%3A0%2C%22levelname%22%3A%22%5Cu8bc4%5Cu8bba%5Cu8005%22%2C%22userid%22%3A%2237167%22%2C%22useralias%22%3A%22qwerrty%22%7D;mdnumtime=1672254149;token_1ead7cab=db96c7496c4c9135c4358ac0a88f68776e99ec326c582594b664a22cefc1b1e31672322267;userdown=0;username_1ead7cab=qwerrty'
    header = {'cookie': cookie}
    id = request.args.get('id')
    url = 'https://b8s6.com/zb_users/theme/md/plugin/down.php?type=down&pid='+id
    return redirect('https://proxy.kazeacg.workers.dev/?url=' + json.loads(requests.get(url ,headers = header).text)['url'])

@app.route("/api/c9f8", methods=['POST', 'GET'])
def api_c9f8():
    cookie = 'mdnumtime=0; mdnum=0; username_1ead7cab=qwerrty; token_1ead7cab=466e11124b6064ee052c9bf051b7cf42ada931ed36289c6a3b6a96217596f7f21672322739; addinfo=%7B%22chkadmin%22%3A1%2C%22chkarticle%22%3A0%2C%22levelname%22%3A%22%5Cu8bc4%5Cu8bba%5Cu8005%22%2C%22userid%22%3A%22113068%22%2C%22useralias%22%3A%22qwerrty%22%7D; timezone=8; userdown=0'
    header = {'cookie': cookie}
    id = request.args.get('id')
    url = 'https://c9f8.com/zb_users/theme/md/plugin/down.php?type=down&pid='+id
    return redirect('https://proxy.kazeacg.workers.dev/?url=' + json.loads(requests.get(url ,headers = header).text)['url'])

if __name__ == '__main__':
    app.run()