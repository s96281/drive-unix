"""
flask-sharepoint-explorer
"""
import os
import time
import hashlib
import urllib.parse
from flask import Flask, redirect, request, render_template
from flask import make_response, send_file, g
from flask_caching import Cache
from natsort import os_sorted
from module.config import DEBUG, CACHE_LOCATION, CACHE_CONFIG, HEADINGS
from module import permission, functions, pages, read_write_data, drive
from module.auth import microsoft_token_auth

app = Flask(__name__)
app.config.from_mapping(CACHE_CONFIG)
cache = Cache(app)

@cache.memoize()
def main(url):
    """
    Main function to return webpage.
    """
    data = read_write_data.read_data()
    drive_type = drive.drivetype(data, url)
    if drive_type in ["SharePointSitePW", "OneDrivePW", "SharePointSiteAPI", "OneDriveAPI"]:
        background = functions.random_background(data)
        if url[-1] == '/':
            url = url[:-1]
        item_list = [['..', '', '', f"/{'/'.join(url.split('/')[0:-1])}"]]
        folder_list = []
        file_list = []
        site = url.split('/')[0]
        path = '/'.join(url.split('/')[1:])
        sharepointsite_files_dict = drive.files(data, site, path)
        if "warning" in sharepointsite_files_dict or "error" in sharepointsite_files_dict:
            if path.split("/")[-1] in drive.files(data, site, "/".join(path.split("/")[:-1])):
                ret = {"message": f"{path} is a file, not a folder.", "site": site, "path": path}
            else:
                ret = sharepointsite_files_dict
        else:
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
            ret = make_response(
                render_template('sharepoint_main.html',
                                headings=HEADINGS,
                                BackgroundImage=background,
                                FILELIST=item_list,
                                headnote=note[0],
                                footnote=note[1]))
    elif drive_type == "GoogleDriveAPI":
        ret = make_response(f"{drive_type} not support yet.")
    else:
        ret = make_response("Drive Type Not Support.")
    return ret


# 首頁，權限確認後列出帳號


@app.route("/", methods=['POST', 'GET'])
def home():
    """
    Home page.
    """
    if not os.path.exists(CACHE_LOCATION):
        os.mkdir(CACHE_LOCATION)

    data = read_write_data.read_data()

    if data is None:
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
            "anonymous_viewlist"] is False and not permission.is_login(
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
    """
    List files under folder path.
    """
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

    if data is None:
        return pages.initialization(request)

    if path.split('/')[0] not in data["Sites"]:
        ret = make_response({"error": f"Drive {path.split('/')[0]} not found."}, 404)
        return ret

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
                microsoft_token_auth.init_access_token(data, request)
            elif i == "SharePointSiteAPI":
                return microsoft_token_auth.init_access_token(data, request)
            else:
                return redirect(request.base_url)
    else:
        if data["Sites"][path.split('/')[0]]["type"] == "SharePointSiteAPI":
            if data["Sites"][path.split('/')[0]].get("refresh_token") is None:
                return microsoft_token_auth.init_access_token(data, request)
            elif time.time() - data["Sites"][path.split('/')
                                             [0]]["t"] > 60 * 60:
                microsoft_token_auth.reflash_token(data, path.split('/')[0])
        if data["ApiOnedriveSetting"][
                "anonymous_viewlist"] is False and not permission.is_login(
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
                        main_response = main(url=path)
                        if isinstance(main_response, dict) and "message" in main_response:
                            response = make_response(redirect(drive.get_downloadlink(data, main_response["site"], main_response["path"])))
                        elif isinstance(main_response, dict) and "warning" in main_response:
                            response = make_response(main_response, 404)
                        else:
                            response = make_response(main_response)
                    else:
                        response = make_response(
                            render_template("sharepoint_encrypt.html",
                                            warning="加密資料夾，請輸入密碼"))
            else:
                main_response = main(url=path)
                if isinstance(main_response, dict) and "message" in main_response:
                    response = make_response(redirect(drive.get_downloadlink(data, main_response["site"], main_response["path"])))
                elif isinstance(main_response, dict) and "warning" in main_response:
                    response = make_response(main_response, 404)
                else:
                    response = make_response(main_response)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response


# Run the flask app.
if __name__ == '__main__':
    if not os.path.exists(CACHE_LOCATION):
        os.mkdir(CACHE_LOCATION)
    app.run(debug=True)
