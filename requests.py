import http.client, json, chardet

def get(url, params=None,allow_redirects=True,history = [], **kwargs):
    kwargs.setdefault('headers', {})
    conn = http.client.HTTPSConnection(url.split('/')[2],timeout=3)
    conn.request('GET', url= url, headers= kwargs['headers'])
    response = conn.getresponse()
    status = response.status
    con = response.read()
    headers = response.getheaders()
    class Response():
        def __repr__():
            return '<Response [%s]>' % (status)
        def _ok():
            return status < 400
        def _is_redirect():
            return ('Location' in dict(headers) and status in [301,302,307])
        def _headers():
            return dict(headers)
        def _is_permanent_redirect():
            return ('Location' in dict(headers) and status in [301,302,307])
        def _history():
            return history
        def _next():
            if ('Location' in dict(headers)):
                return dict(headers)['Location']
            return None
        def _apparent_encoding():
            return chardet.detect(con)
        def _content():
            return con
        def _text():
            return con.decode("utf-8")
        def _json():
            try:
                return json.loads(con.decode("utf-8"))
            except:
                return None
        def _links():
            return None
        def _content():
            return con
        def _status_code():
            return status
        def _cookies():
            pass
        def _elapsed():
            return None
        def _encoding():
            if 'Content-Type' in dict(headers):
                try:
                    return dict(headers)['Content-Type'].split(';')[-1]
                except:
                    return chardet.detect(con)
            return chardet.detect(con)
        def _raw():
            return response.__str__()
        def _reason():
            return response.reason
        def _url():
            return url


        apparent_encoding = _apparent_encoding()
        content = _content()
        cookies = _cookies()
        elapsed = _elapsed()
        encoding = _encoding()
        headers = _headers()
        history = _history()
        is_permanent_redirect = _is_permanent_redirect()
        is_redirect = _is_redirect()
        jsonn = _json()
        links = _links()
        nextt = _next()
        ok = _ok()
        raw = _raw()
        reason = _reason()
        status_code = _status_code()
        text = _text()
        url = _url()
    
    # Close the handle of TCP connect.
    conn.close()

    # Follow the 301, 302, 307 redirect if 'allow_redirects' been setting to true.
    if allow_redirects == True and 'Location' in dict(headers):
        url = dict(headers)['Location']
        history.append(Response)
        return get(url, params, allow_redirects,history= history , **kwargs)
    
    return Response