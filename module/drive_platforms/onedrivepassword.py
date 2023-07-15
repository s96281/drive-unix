"""
Read OneDrive with password.
"""
import urllib.parse
import markdown
import requests
from markupsafe import Markup
from module.auth.microsoft_cookie_auth import read_cookie
from module import config, functions


def ondrivepw_detail(data: dict, drive: str) -> dict:
    """Get details of a OneDrive drive specified by its alias.

    Args:
    -   data (dict): A dictionary containing all the necessary data
            to authenticate and access the OneDrive API.
    -   alia (str): The alias of the drive for which details need to be retrieved.

    Returns:
    -   dict: A dictionary containing the details of the specified OneDrive drive.
              Returns {"error": f"Drive {alia} not found."} if the specified drive is not found.
    """
    try:
        endpoint = data['Sites'][drive]["endpoint"]
        username = data['Sites'][drive]["username"]
        password = data['Sites'][drive]["password"]
        cookie = read_cookie(endpoint, username, password)
        url = endpoint + '_api/v2.1/drive/root'
        header = {
            'cookie': cookie,
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0',
            'Sec-Fetch-User': '?1'
        }
        res = requests.get(url,
                           headers=header,
                           timeout=config.REQUEST_TIME_OUT).json()
        return res
    except KeyError:
        return {"error": f"Drive {drive} not found."}


def ondrivepw_getdownloadlink(data: dict, drive: str, path: str) -> str | dict:
    try:
        endpoint = data['Sites'][drive]["endpoint"]
        username = data['Sites'][drive]["username"]
        password = data['Sites'][drive]["password"]
        cookie = read_cookie(endpoint, username, password)
        header = {
            'cookie': cookie,
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0',
            'Sec-Fetch-User': '?1'
        }
        path = urllib.parse.quote(path)
        url = endpoint + '_api/v2.1/drive/root:' + path
        res = requests.get(url,
                           headers=header,
                           timeout=config.REQUEST_TIME_OUT).json()
        if "error" in res:
            functions.log("ERROR", res['error'])
        elif '@content.downloadUrl' in res:
            return res['@content.downloadUrl']
        return {"error": res}
    except KeyError:
        return {"error": f"Drive {drive} not found."}


def nextpage(header: dict, url: str) -> dict:
    """
    Fetches all items in a SharePoint folder or drive page by page
    and returns a dictionary of file/folder details.
    
    Args:
    header (dict): HTTP headers to be included in the request.
    url (str): The URL of the SharePoint folder or drive page.
    
    Returns:
    dict: A dictionary of file/folder details for all items in the SharePoint folder or drive.
    """
    response = {}
    res = requests.get(url, headers=header,
                       timeout=config.REQUEST_TIME_OUT).json()
    for i in res['value']:
        response[i["name"]] = {
            "type": "folder" if "folder" in i else "file",
            "lastModifiedDateTime": i["lastModifiedDateTime"],
            "size": i["size"]
        }
    if "@odata.nextLink" in res:
        response.update(nextpage(header, res["@odata.nextLink"]))
    return response


def onedrivepw_root_files(data: dict, drive: str) -> dict:
    try:
        response = {}
        endpoint = data["Sites"][drive].get("endpoint")
        username = data["Sites"][drive].get("username")
        password = data["Sites"][drive].get("password")
        cookie = read_cookie(endpoint, username, password)
        url = endpoint + '_api/v2.1/drive/root/children?$top=' + str(
            config.REQUEST_SIZE
        ) + '&select=name,folder,lastModifiedDateTime,size'
        header = {
            'cookie': cookie,
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0',
            'Sec-Fetch-User': '?1'
        }
        res = requests.get(url,
                           headers=header,
                           timeout=config.REQUEST_TIME_OUT).json()
        for i in res['value']:
            response[i["name"]] = {
                "type": "folder" if "folder" in i else "file",
                "lastModifiedDateTime": i["lastModifiedDateTime"],
                "size": i["size"]
            }
        if "@odata.nextLink" in res:
            response.update(nextpage(header, res["@odata.nextLink"]))
        return response
    except KeyError:
        return {"error": f"Drive {drive} not found."}


def onedrivepw_path_files(data: dict, drive: str, path: str) -> dict:
    try:
        response = {}
        endpoint = data["Sites"][drive].get("endpoint")
        username = data["Sites"][drive].get("username")
        password = data["Sites"][drive].get("password")
        cookie = read_cookie(endpoint, username, password)
        header = {
            'cookie': cookie,
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0',
            'Sec-Fetch-User': '?1'
        }
        url = endpoint + '_api/v2.1/drive/root:/' + path + ':/children?$top=' + str(
            config.REQUEST_SIZE
        ) + '&select=name,folder,lastModifiedDateTime,size'
        res = requests.get(url,
                           headers=header,
                           timeout=config.REQUEST_TIME_OUT).json()
        for i in res['value']:
            response[i["name"]] = {
                "type": "folder" if "folder" in i else "file",
                "lastModifiedDateTime": i["lastModifiedDateTime"],
                "size": i["size"]
            }
        if "@odata.nextLink" in res:
            response.update(nextpage(header, res["@odata.nextLink"]))
        return response
    except KeyError:
        return {"error": f"Drive {drive} not found."}


def onedrivepw_files(data: dict, drive: str, path: str = None) -> dict:
    if path:
        ret = onedrivepw_path_files(data, drive, path)
    else:
        ret = onedrivepw_root_files(data, drive)
    return ret


def onedrivepw_head_foot_note(data: dict, drive: str, path: str,
                              file_list: list) -> list:
    response = []
    exts = ['extra', 'codehilite', 'tables', 'toc']
    if data['ApiOnedriveSetting'].get('top_md') and 'top.md' in str(file_list):
        res = requests.get(ondrivepw_getdownloadlink(data, drive,
                                                     path + '/top.md'),
                           timeout=config.REQUEST_TIME_OUT)
        if res.ok:
            txt = Markup(markdown.markdown(res.text, extensions=exts))
            response.append(txt)
        else:
            response.append(None)
    else:
        response.append(None)
    if data['ApiOnedriveSetting'].get('bottom_md') and 'bottom.md' in str(
            file_list):
        res = requests.get(ondrivepw_getdownloadlink(data, drive,
                                                     path + '/bottom.md'),
                           timeout=config.REQUEST_TIME_OUT)
        if res.ok:
            txt = Markup(markdown.markdown(res.text, extensions=exts))
            response.append(txt)
        else:
            response.append(None)
    else:
        response.append(None)
    return response
