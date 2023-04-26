"""
Pages function of website.
"""
import time
import urllib.parse
import hashlib
from typing import Callable
import markdown
import chardet
import requests
from flask import render_template, make_response, redirect, url_for, Request, Response, Markup
from flask_caching import Cache
from module.read_write_data import write_data, read_data
from module.auth.cookie_auth import read_cookie
from module.functions import random_background, get_file_type
from module.permission import is_login, is_admin, logout, login
from module.drive_platforms.drive import get_downloadlink
from module import config


def reflash(path: str, cache: Cache, func: Callable,
            user_request: Request) -> Response:
    """
    Reflashes the cache for a given path and redirects the user to the previous page.

    Args:
        path (str): The path for which the cache needs to be cleared.
        cache (Cache): The cache object used to store cached data.
        func (Callable): The function whose cache needs to be cleared.
        user_request (Request): A request object containing information about the user.

    Returns:
        Response: A response object that redirects the user to the previous page.

    Raises:
        N/A
    """
    if path != '':
        cache.delete_memoized(func, path)
        response = make_response(redirect(user_request.referrer))
    else:
        response = make_response(redirect(url_for("home")))
    return response


def initialization(user_request: Request) -> str | Response:
    """
    Initializes the application with user-provided data, clears the cache for a given path,
        and redirects the user to the previous page.

    Args:
        user_request (Request): A request object containing information about the user.

    Returns:
        Union[str, Response]: If the request method is 'GET',
            returns a rendered template for the initialization page.
            Otherwise, initializes the application with the user-provided data,
            clears the cache for a given path, and redirects the user to the previous page.

    Raises:
        N/A
    """
    if user_request.method == 'GET':
        return render_template('initialization.html')
    data = {"SharePointAccountList": {}, "ApiOnedriveSetting": {}}
    try:
        local_password = user_request.form.get('local_password')
        data = {
            "Sites": {
                user_request.form['alia']: {
                    "type": user_request.form['type'],
                    "site": user_request.form['site'],
                    "endpoint": user_request.form['endpoint'],
                    "username": user_request.form['username'],
                    "password": user_request.form['password'],
                    "alia": user_request.form['alia']
                }
            },
            "ApiOnedriveSetting": {
                "backgroud_image_list":
                user_request.form.get('background',
                                      default="").split(',')[:-1],
                "anonymous_viewlist":
                user_request.form.get('anonymous_viewlist') == '0',
                "anonymous_download":
                user_request.form.get('anonymous_download') == '0',
                "top_md":
                user_request.form.get('top_md') == "True",
                "bottom_md":
                user_request.form.get('bottom_md') == "True",
                "page_encrypt":
                user_request.form.get('page_encrypt') == "True",
                "passfile":
                user_request.form['passfile'],
                "users": {
                    user_request.form.get('local_user'): {
                        "rank":
                        "admin",
                        "password":
                        hashlib.sha256(local_password.encode()).hexdigest()
                    }
                },
                "CACHE_TYPE":
                user_request.form.get('CACHE_TYPE', default="FileSystemCache")
            }
        }
    except KeyError as esc:
        print({"error": esc})
    time_of_now = time.time()
    data['TIME'] = time_of_now
    write_data(data)
    return redirect(url_for("home"))


def setting(user_request: Request) -> Response:
    """
    This function handles the setting page.
    It checks if the user is logged in and an admin,
    and if not, it redirects them to the login page.
    If the user is logged in and an admin,
    it checks if the form is submitted.
    If it is, it updates the settings and redirects the user to the setting page.
    If the form is not submitted, it renders the setting page.

    Args:
    - user_request (Request): A request object containing information about the user.

    Returns:
    - Response: A response object that cotain setting page.

    Raises:
    - None

    """
    data = read_data()
    if not is_login(data, user_request):
        response = redirect(user_request.base_url + '/?login')
    elif not is_admin(data, user_request) and is_login(data, user_request):
        response = 'Permission not allow'
    if 'logout' in user_request.args:
        response = logout(user_request)
    elif user_request.form:
        if 'background' in user_request.form:
            data["ApiOnedriveSetting"][
                "backgroud_image_list"] = user_request.form.get(
                    'background', default="").split(',')[:-1]
            data["ApiOnedriveSetting"][
                "anonymous_viewlist"] = user_request.form.get(
                    'anonymous_viewlist') == '0'
            data["ApiOnedriveSetting"][
                "anonymous_download"] = user_request.form.get(
                    'anonymous_download') == '0'
            data["ApiOnedriveSetting"]["CACHE_TYPE"] = user_request.form.get(
                'CACHE_TYPE', default="FileSystemCache")
            data["ApiOnedriveSetting"]["top_md"] = user_request.form.get(
                'top_md') == "True"
            data["ApiOnedriveSetting"]["bottom_md"] = user_request.form.get(
                'bottom_md') == "True"
            data["ApiOnedriveSetting"]["page_encrypt"] = user_request.form.get(
                'page_encrypt') == "True"
            data["ApiOnedriveSetting"]["passfile"] = user_request.form.get(
                'passfile')
        elif 'type' in str(user_request.form):
            nth_of_new_drive = 0
            alia = ''
            needdelete = []
            for i in user_request.form:
                if user_request.form.get(i) == '':
                    needdelete.append('-'.join(i.split('-')[1:]).replace(
                        '%$%', ' '))
                if 'NEW' in str(i):
                    if i.split('-')[1] == nth_of_new_drive:
                        key = i.split('-')[0].replace('NEW', '')
                        data["Sites"][alia][key] = user_request.form.get(i)
                    else:
                        alia = user_request.form.get(i)
                        key = i.split('-')[0].replace('NEW', '')
                        data["Sites"][alia] = {key: user_request.form.get(i)}
                        nth_of_new_drive = i.split('-')[1]
                else:
                    key = i.split('-')[0]
                    val = '-'.join(i.split('-')[1:]).replace('%$%', ' ')
                    data["Sites"][val][key] = user_request.form.get(i)
            for i in needdelete:
                try:
                    data["Sites"].pop(i)
                except KeyError:
                    pass
        elif 'user' in user_request.form:
            pop = user_request.form.get('pop')
            if not pop:
                user = user_request.form.get('user')
                password = user_request.form.get('password')
                isadmin = user_request.form.get('isadmin')
                data["ApiOnedriveSetting"]["users"][user] = {
                    "rank":
                    "admin" if isadmin == '0' else "guest",
                    "password":
                    hashlib.sha256(password.encode()).hexdigest() if password
                    else data["ApiOnedriveSetting"]["users"][user]["password"]
                }
            else:
                user = user_request.form.get('user')
                data["ApiOnedriveSetting"]["users"].pop(user)
        write_data(data)
        response = make_response(redirect(user_request.base_url + "?setting"))
    else:
        response = make_response(
            render_template('sharepoint_setting.html',
                            Users=data["ApiOnedriveSetting"]["users"],
                            Sites=data['Sites'],
                            backgroud_image_list=data['ApiOnedriveSetting']
                            ['backgroud_image_list'],
                            BackgroundImage=random_background(data),
                            passfile=data["ApiOnedriveSetting"]["passfile"]))
    return response


def report_cookie(user_request: Request) -> str:
    """
    Get the cookie for a SharePoint site.

    Args:
    -   user_request (Request): The request object containing the site to retrieve the cookie for.

    Returns:
    -   str: The cookie value for the site, or an error message if the site is not found or not
            a SharePoint site with a password.

    """
    site = user_request.args.get("cookie")
    data = read_data()
    if site in data['Sites'] and data['Sites'][site][
            "type"] == "SharePointSitePW":
        endpoint = data['Sites'][site]["endpoint"]
        username = data['Sites'][site]["username"]
        password = data['Sites'][site]["password"]
        ret = read_cookie(endpoint, username, password)
    elif site not in data['Sites']:
        print({"error": f"Drive {site} not found"})
        ret = f"Drive {site} not found"
    else:
        print({"error": f"Type of drive {site} is not SharePointSitePW"})
        ret = f"Type of drive {site} is not SharePointSitePW"
    return ret


def status() -> str:
    """
    Return 'Online' if website is online.

    Args:
        N/A

    Returns:
    -   str: 'Online'

    """
    return 'Online'


def preview(user_request: Request) -> Response:
    """
    Displays a preview of the requested file.
    Args:
        user_request: A Request object containing user information.
    Returns:
        A Response object containing the preview page.
    """
    data = read_data()
    # 檢查權限
    if data["ApiOnedriveSetting"][
            "anonymous_viewlist"] is False and not is_login(
                data, user_request):
        return login(user_request)
    mediatype = get_file_type('.' + user_request.path.split('.')[-1])
    alia = user_request.path.split('/')[1]
    path = '/'.join(user_request.path.split('/')[2:])
    if mediatype == 'text':
        txt = requests.get(get_downloadlink(data, alia, path),
                           timeout=config.REQUEST_TIME_OUT).content
        code = chardet.detect(txt)['encoding']
        if code is None:
            txt = '文字編碼錯誤'
        else:
            txt = txt.decode(code)
        sub = ''
    elif mediatype == 'programe':
        txt = requests.get(get_downloadlink(data, alia, path),
                           timeout=config.REQUEST_TIME_OUT).text
        txt = '```' + '\n' + txt + '\n```'
        exts = ['extra', 'codehilite', 'tables', 'toc']
        txt = markdown.markdown(txt, extensions=exts)
        txt = Markup(txt)
        sub = ''
    elif mediatype == 'video':
        sub = user_request.url.replace('mp4?preview=1',
                                       'ass?download=1').replace(
                                           'mkv?preview=1', 'ass?download=1')
        txt = ''
    else:
        txt = sub = ''
    return make_response(
        render_template(
            "sharepoint_preview.html",
            source=user_request.url.replace('preview=1', 'download=1'),
            mediatype=mediatype,
            name=urllib.parse.unquote(user_request.base_url.split('/')[-1]),
            txt=txt,
            SUB=sub))


def download(url: str, user_request: Request) -> Response:
    """
    Downloads the file at the given URL if the user has permission to do so.

    Args:
    - url (str): The URL of the file to download.
    - user_request (Request): A request object containing information about the user.

    Returns:
    - Response: A redirect response object that directs the user to the download link.

    Raises:
    - None

    """
    data = read_data()
    # 檢查權限
    if data["ApiOnedriveSetting"][
            "anonymous_download"] is False and not is_login(
                data, user_request):
        return login(user_request)
    alia = url.split('/')[0]
    path = '/'.join(url.split('/')[1:])
    return redirect(get_downloadlink(data, alia, path))


def cookie(user_request: Request) -> str:
    """
    Generates a cookie for the specified SharePoint site.

    Args:
        user_request (Request): The HTTP request object containing the 
        site's name in the 'cookie' parameter.

    Returns:
        str: The generated cookie string if successful, or an error message 
        if the site is not found or its type is not 'SharePointSitePW'.
    """
    alia = user_request.args.get("cookie")
    data = read_data()
    if alia in data['Sites']:
        endpoint = data['Sites'][alia]["endpoint"]
        username = data['Sites'][alia]["username"]
        password = data['Sites'][alia]["password"]
        ret = read_cookie(endpoint, username, password)
    else:
        ret = "Site Not Found or Site Type Is Not SharePointSitePW"
    return ret
