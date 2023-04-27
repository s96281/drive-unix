import json
import os
import time
import hashlib
import urllib.parse
import requests
import markdown
from flask import Flask, redirect, request, render_template
from flask import make_response, send_file
from markupsafe import Markup
from flask_caching import Cache
from natsort import os_sorted
from module.config import DEBUG, CACHE_LOCATION, CACHE_CONFIG, HEADINGS
from module import permission, functions, pages, read_write_data
from module.auth import token_auth
from module.drive_platforms import drive

# 效能分析工具
if DEBUG:
    from flask import g
    from pyinstrument import Profiler

requests = requests.Session()

app = Flask(__name__)
app.config.from_mapping(CACHE_CONFIG)
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
    data = read_write_data.read_data()
    DriveType = drive.drivetype(data, url)
    if DriveType == "SharePointSitePW" or DriveType == "OneDrivePW":
        BackgroundImage = functions.random_background(data)
        if url[-1] == '/':
            url = url[:-1]
        item_list = [['..', '', '', f"/{'/'.join(url.split('/')[0:-1])}"]]
        folder_list = []
        file_list = []
        site = url.split('/')[0]
        path = '/'.join(url.split('/')[1:])
        sharepointsite_files_dict = drive.files(data, site, path)
        for key, values in sharepointsite_files_dict.items():
            last_modified_datetime = functions.utc_local_convert(
                values['lastModifiedDateTime'])
            size = functions.sizeof_fmt(values['size'])
            if values['type'] == 'folder':
                folder_list.append([
                    key, last_modified_datetime, size,
                    f"/{url}/{urllib.parse.quote(key)}"
                ])
            else:
                file_list.append([
                    key, last_modified_datetime, size,
                    f"/{url}/{urllib.parse.quote(key)}?preview=1"
                ])
        folder_list = os_sorted(folder_list, key=lambda x: x[0])
        file_list = os_sorted(file_list, key=lambda x: x[0])
        item_list.extend(folder_list)
        item_list.extend(file_list)
        note = drive.head_foot_note(data, site, path, item_list)
        return make_response(
            render_template('sharepoint_main.html',
                            headings=HEADINGS,
                            BackgroundImage=BackgroundImage,
                            FILELIST=item_list,
                            headnote=note[0],
                            footnote=note[1]))
    elif DriveType == "SharePointSiteAPI":

        def sitename2id(site):
            access_token = token_auth.read_token(data, site)
            headers = {'Authorization': 'Bearer ' + access_token}
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
                response[i["name"]] = {
                    "type": "folder" if "folder" in i else "file",
                    "lastModifiedDateTime": i["lastModifiedDateTime"],
                    "size": i["size"]
                }
            if "@odata.nextLink" in r:
                response.update(nextpage(header, r["@odata.nextLink"]))
            return response

        def sharepointsite_root_files(data, site) -> dict:
            response = {}
            url = "https://graph.microsoft.com/v1.0/sites/" + sitename2id(
                site) + "/drive/root/children"
            access_token = token_auth.read_token(data, site)
            headers = {'Authorization': 'Bearer ' + access_token}
            r = requests.get(url, headers=headers).json()
            for i in r['value']:
                response[i["name"]] = {
                    "type": "folder" if "folder" in i else "file",
                    "lastModifiedDateTime": i["lastModifiedDateTime"],
                    "size": i["size"]
                }
            if "@odata.nextLink" in r:
                response.update(nextpage(headers, r["@odata.nextLink"]))
            return response

        def sharepointsite_path_files(data, site, path) -> dict:
            response = {}
            url = "https://graph.microsoft.com/v1.0/sites/" + sitename2id(
                site) + "/drive/root:/" + path + ":/children"
            access_token = token_auth.read_token(data, site)
            headers = {'Authorization': 'Bearer ' + access_token}
            r = requests.get(url, headers=headers).json()
            for i in r['value']:
                response[i["name"]] = {
                    "type": "folder" if "folder" in i else "file",
                    "lastModifiedDateTime": i["lastModifiedDateTime"],
                    "size": i["size"]
                }
            if "@odata.nextLink" in r:
                response.update(nextpage(headers, r["@odata.nextLink"]))
            return response

        def head_foot_note(data, url, SharePointFileList) -> list:
            response = []
            if data['ApiOnedriveSetting'].get('top_md') and 'top.md' in str(
                    SharePointFileList):
                _url = url + '/top.md'
                path = '/'.join(_url.split('/')[1:])
                r = requests.get(drive.get_downloadlink(data, site, path))
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
            if data['ApiOnedriveSetting'].get(
                    'bottom_md') and 'bottom.md' in str(SharePointFileList):
                _url = url + '/bottom.md'
                path = '/'.join(_url.split('/')[1:])
                r = requests.get(drive.get_downloadlink(data, site, path))
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

        BackgroundImage = functions.random_background(data)

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
                    time = functions.utc_local_convert(
                        sharepointsite_root_files_dict[i]
                        ['lastModifiedDateTime'])
                    size = functions.sizeof_fmt(
                        sharepointsite_root_files_dict[i]['size'])
                    if sharepointsite_root_files_dict[i]['type'] == 'folder':
                        SharePointFileList_FOLDERS.append([
                            name, time, size,
                            '/' + url + '/' + urllib.parse.quote(name)
                        ])
                    else:
                        SharePointFileList_FILES.append([
                            name, time, size, '/' + url + '/' +
                            urllib.parse.quote(name) + '?preview=1'
                        ])
                SharePointFileList_FOLDERS = os_sorted(
                    SharePointFileList_FOLDERS, key=lambda x: x[0])
                SharePointFileList_FILES = os_sorted(SharePointFileList_FILES,
                                                     key=lambda x: x[0])
                SharePointFileList.extend(SharePointFileList_FOLDERS)
                SharePointFileList.extend(SharePointFileList_FILES)
                # pylint: disable=unbalanced-tuple-unpacking
                [headnote, footnote] = head_foot_note(data, url,
                                                      SharePointFileList)
                return make_response(
                    render_template('sharepoint_main.html',
                                    headings=HEADINGS,
                                    BackgroundImage=BackgroundImage,
                                    SharePointFileList=SharePointFileList,
                                    headnote=headnote,
                                    footnote=footnote))
            if len(url.split('/')) > 1:
                # List files in path
                SharePointFileList = [[
                    '..', '', '', '/' + '/'.join(url.split('/')[0:-1])
                ]]
                SharePointFileList_FOLDERS = []
                SharePointFileList_FILES = []
                site = data["Sites"][url.split('/')[0]]["site"]
                path = '/'.join(url.split('/')[1:])
                sharepointsite_path_files_dict = sharepointsite_path_files(
                    data, site, path)
                for i in sharepointsite_path_files_dict:
                    name = i
                    time = functions.utc_local_convert(
                        sharepointsite_path_files_dict[i]
                        ['lastModifiedDateTime'])
                    size = functions.sizeof_fmt(
                        sharepointsite_path_files_dict[i]['size'])
                    if sharepointsite_path_files_dict[i]['type'] == 'folder':
                        SharePointFileList_FOLDERS.append([
                            name, time, size,
                            '/' + url + '/' + urllib.parse.quote(name)
                        ])
                    else:
                        SharePointFileList_FILES.append([
                            name, time, size, '/' + url + '/' +
                            urllib.parse.quote(name) + '?preview=1'
                        ])
                SharePointFileList_FOLDERS = os_sorted(
                    SharePointFileList_FOLDERS, key=lambda x: x[0])
                SharePointFileList_FILES = os_sorted(SharePointFileList_FILES,
                                                     key=lambda x: x[0])
                SharePointFileList.extend(SharePointFileList_FOLDERS)
                SharePointFileList.extend(SharePointFileList_FILES)
                # pylint: disable=unbalanced-tuple-unpacking
                [headnote, footnote] = head_foot_note(data, url,
                                                      SharePointFileList)
                return make_response(
                    render_template('sharepoint_main.html',
                                    headings=HEADINGS,
                                    BackgroundImage=BackgroundImage,
                                    SharePointFileList=SharePointFileList,
                                    headnote=headnote,
                                    footnote=footnote))
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
    if not os.path.exists(CACHE_LOCATION):
        os.mkdir(CACHE_LOCATION)

    data = read_write_data.read_data()

    if data == None:
        return pages.initialization(request)

    if request.args:
        for i in request.args:
            if i == "initialization":
                return pages.initialization(request)
            elif i == "login":
                return pages.login(request)
            elif i == "setting":
                return pages.setting(request)
            elif i == "logout":
                return pages.logout(request)
            elif i == "reflash":
                return redirect(request.base_url)
            elif i == "cookie":
                return pages.cookie(request)
            elif i == "status":
                return pages.status()
            elif i == "code":
                return make_response(request.args.get('code').split('&')[0])
            else:
                return redirect(request.base_url)

    if data["ApiOnedriveSetting"][
            "anonymous_viewlist"] == False and not permission.is_login(
                data, request):
        response = pages.login(request)
    else:
        drive_list = []
        for i in functions.list_drive(data):
            drive_list.append([i, '', '', '/' + i])
        response = make_response(
            render_template('sharepoint_main.html',
                            headings=HEADINGS,
                            BackgroundImage=functions.random_background(data),
                            FILELIST=drive_list))
    return response


# 權限確認後列出檔案
@app.route("/<path:path>", methods=['POST', 'GET'])
def sub_dir(path):
    if path.split('/')[0] == 'static':
        return send_file('./' + path)
    if path == 'favicon.ico':
        return '404'
    if not os.path.exists(CACHE_LOCATION):
        os.mkdir(CACHE_LOCATION)

    data = read_write_data.read_data()

    def decrypt(password, path):
        if request.form.get('password') == password:
            response = main(url=path)
            response.set_cookie(key=path + "_pw",
                                value=hashlib.sha256(
                                    password.encode()).hexdigest(),
                                max_age=86400,
                                path='/' + path)
        else:
            response = make_response(
                render_template("sharepoint_encrypt.html", warning="密碼錯誤"))
        return response

    if data == None:
        return pages.initialization(request)

    if request.args:
        for i in request.args:
            if i == "initialization":
                return pages.initialization(request)
            elif i == "login":
                return pages.login(request)
            elif i == "setting":
                return pages.setting(request)
            elif i == "logout":
                return pages.logout(request)
            elif i == "reflash":
                return pages.reflash(path, cache, main, request)
            elif i == "cookie":
                return pages.cookie(request)
            elif i == "status":
                return pages.status()
            elif i == "preview":
                return pages.preview(request)
            elif i == "download":
                return pages.download(path, request)
            elif i == "decrypt":
                pass
            elif i == "code":
                token_auth.init_access_token(data, request)
            elif i == "SharePointSiteAPI":
                return token_auth.init_access_token(data, request)
            else:
                return redirect(request.base_url)
    else:
        if data["Sites"][path.split('/')[0]]["type"] == "SharePointSiteAPI":
            if data["Sites"][path.split('/')[0]].get("refresh_token") == None:
                return token_auth.init_access_token(data, request)
            elif time.time() - data["Sites"][path.split('/')
                                             [0]]["t"] > 60 * 60:
                token_auth.reflash_token(data, path.split('/')[0])
        if data["ApiOnedriveSetting"][
                "anonymous_viewlist"] == False and not permission.is_login(
                    data, request):
            response = redirect(request.base_url + '/?login=1')
        else:
            password = drive.get_page_encrypt_pw(data, path)
            if password:
                if request.method == "POST":
                    response = decrypt(password, path)
                else:
                    if request.cookies.get(path + "_pw") == hashlib.sha256(
                            password.encode()).hexdigest():
                        response = main(url=path)
                    else:
                        response = make_response(
                            render_template("sharepoint_encrypt.html",
                                            warning="加密資料夾，請輸入密碼"))
            else:
                response = main(url=path)
        return response


# Run the flask app.
if __name__ == '__main__':
    if not os.path.exists(CACHE_LOCATION):
        os.mkdir(CACHE_LOCATION)
    app.run(debug=False)
