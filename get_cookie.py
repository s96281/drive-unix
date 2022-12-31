#!/usr/bin/python

# This script can be used to obtain authentication cookies in order to gain access
# to a SharePoint site's REST or WebDAV API using a username and password.
#
# Usage: python get-sharepoint-auth-cookie.py https://<somesite>.sharepoint.com/ your.name@domain.com <domain-password>
#
# The script returns a string containing two HTTP cookies: FedAuth and rtFa. These
# cookies can be attached to HTTP requests to the SharePoint site in order to satisfy
# authentication requirements
#
# WARNING: Be careful when using this script in another scripts - it requires that
#          your system password is supplied as argument. Please make sure that your
#          password is passed to this script in a secure way and not stored in the
#          calling script.
#
# WARNING: The returned cookies are effectively a form of a password that allows
#          access to the SharePoint site with privileges of the authenticated user
#          for the validity duration of the cookie. Make sure these cookies are
#          kept safe leaking them to an unauthorized party is effectively equal
#          to leaking your password.

from __future__ import print_function
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

if __name__ == "__main__":
  get_cookie("https://mailswdpsntpcedutw.sharepoint.com/","s96281@mails.wdps.ntpc.edu.tw","Aa.22545521")