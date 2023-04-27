"""
Read SharePoint Sites with password.
"""
import urllib.parse
import markdown
import requests
from markupsafe import Markup
from module.auth.microsoft_cookie_auth import read_cookie
from module import config


def sharepointpw_details(data: dict, alia: str) -> dict:
    """
    Retrieves the details of the SharePoint account, including the endpoint, username,
    password, and cookie, and returns the JSON response obtained by sending a GET request
    to the specified SharePoint site.

    Args:
    - data: A dictionary containing the SharePoint account list and its details.
    - alia: A string representing the name of the SharePoint site to access.

    Returns:
    - A dictionary containing the JSON response obtained by sending a GET request to the
    specified SharePoint site.
    """
    try:
        endpoint = data['Sites'][alia]["endpoint"]
        username = data['Sites'][alia]["username"]
        password = data['Sites'][alia]["password"]
        site = data['Sites'][alia]["site"]
        cookie = read_cookie(endpoint, username, password)
        header = {
            'cookie': cookie,
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0',
            'Sec-Fetch-User': '?1'
        }
        url = endpoint + '_api/v2.1/sites/' + \
            endpoint.split('/')[2] + \
            ':/sites/' + site + ':/drive/root'
        res = requests.get(url,
                           headers=header,
                           timeout=config.REQUEST_TIME_OUT).json()
        return res
    except KeyError:
        return {"error": f"Drive {alia} not found."}


def sharepointpw_getdownloadlink(data: dict, alia: str,
                                 path: str) -> str | dict:
    """Get the download link of a file from a SharePoint site.

    Args:
    -   data (dict): A dictionary containing information about the SharePoint sites.
    -   site (str): The name of the SharePoint site.
    -   path (str): The path of the file in the SharePoint site.

    Returns:
    -   str or dict: The download link of the file if it exists,
            otherwise dict that contain the reasion of error.

    """
    try:
        endpoint = data['Sites'][alia]["endpoint"]
        username = data['Sites'][alia]["username"]
        password = data['Sites'][alia]["password"]
        site = data['Sites'][alia]["site"]
        cookie = read_cookie(endpoint, username, password)
        header = {
            'cookie': cookie,
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0',
            'Sec-Fetch-User': '?1'
        }
        path = urllib.parse.quote(path)
        url = endpoint + '_api/v2.1/sites/' + endpoint.split(
            '/')[2] + ':/sites/' + site + ':/drive/root:' + path
        res = requests.get(url,
                           headers=header,
                           timeout=config.REQUEST_TIME_OUT).json()
        if "error" in res:
            if config.DEBUG:
                print({
                    "error":
                    f"SharePoint REST API response error: {res['error']}",
                    "function": "sharepointpw_getdownloadlink",
                    "arguments": f"data: {data}, site: {site}, path: {path}"
                })
            else:
                pass
        elif '@content.downloadUrl' in res:
            return res['@content.downloadUrl']
        return {"error": res}
    except KeyError:
        return {"error": f"Drive {alia} not found."}


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


def sharepointpw_root_files(data: dict, alia: str) -> dict:
    """
    Retrieves the root files and folders of a SharePoint site using the provided
    authentication credentials.

    Args:
        data (dict): A dictionary containing authentication data for the SharePoint site.
        site (str): The name of the SharePoint site whose root files are to be retrieved.

    Returns:
        dict: A dictionary containing the retrieved root files and folders of the SharePoint site.
        The dictionary is in the format\n
        {name: {"type": folder/file, "lastModifiedDateTime": time, "size": size}}\n
        where 'name' is the name of the file/folder, 'type' is the type of the file/folder,
        'lastModifiedDateTime' is the time the file/folder was last modified,
        and 'size' is the size of the file/folder in bytes.

    Raises:
        None.
    """
    try:
        response = {}
        endpoint = data['Sites'][alia]["endpoint"]
        username = data['Sites'][alia]["username"]
        password = data['Sites'][alia]["password"]
        site = data['Sites'][alia]["site"]
        cookie = read_cookie(endpoint, username, password)
        header = {
            'cookie': cookie,
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0',
            'Sec-Fetch-User': '?1'
        }
        url = endpoint + '_api/v2.1/sites/' + endpoint.split('/')[2] + ':/sites/' + \
            site + ':/drive/root/children?$top=' + \
            str(config.REQUEST_SIZE)+'&select=name,folder,lastModifiedDateTime,size'
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
        return {"error": f"Drive {alia} not found."}


def sharepointpw_path_files(data: dict, alia: str, path: str) -> dict:
    """
    Returns a dictionary of SharePoint site files and folders located in the specified path.
    
    Args:
    - data (dict): A dictionary containing SharePoint site credentials.
    - site (str): The name of the SharePoint site.
    - path (str): The path of the folder whose files and subfolders are to be returned.
    
    Returns:
    - dict: A dictionary containing the retrieved root files and folders of the SharePoint site.
        The dictionary is in the format\n
        {name: {"type": folder/file, "lastModifiedDateTime": time, "size": size}}\n
        where 'name' is the name of the file/folder, 'type' is the type of the file/folder,
        'lastModifiedDateTime' is the time the file/folder was last modified,
        and 'size' is the size of the file/folder in bytes.
    
    Raises:
        N/A.
    """
    try:
        response = {}
        endpoint = data['Sites'][alia]["endpoint"]
        username = data['Sites'][alia]["username"]
        password = data['Sites'][alia]["password"]
        site = data['Sites'][alia]["site"]
        cookie = read_cookie(endpoint, username, password)
        header = {
            'cookie': cookie,
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0',
            'Sec-Fetch-User': '?1'
        }
        path = urllib.parse.quote(path)
        url = endpoint + '_api/v2.1/sites/' + endpoint.split('/')[2] + ':/sites/' + \
            site + ':/drive/root:' + path + ':/children?$top=' + \
            str(config.REQUEST_SIZE)+'&select=name,folder,lastModifiedDateTime,size'
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
        return {"error": f"Drive {alia} not found."}


def sharepointpw_files(data: dict, alia: str, path: str = None) -> dict:
    """
    Retrieves files and folders information from a SharePoint site's root or a specified path.

    Args:
        data (dict): A dictionary containing information about the SharePoint sites,
        including endpoints, usernames, passwords, and aliases.
        site (str): The alias of the SharePoint site.
        path (str, optional): The path from which to retrieve files and folders. Defaults to None.

    Returns:
        dict: A dictionary containing the name, type, lastModifiedDateTime,
        and size of each file and folder at the specified site or path.
    """
    if path:
        ret = sharepointpw_path_files(data, alia, path)
    else:
        ret = sharepointpw_root_files(data, alia)
    return ret


def sharepointpw_head_foot_note(data: dict, alia: str, path: str,
                                file_list: list) -> list:
    """
    Returns the content of the head.md and foot.md files in the SharePoint site.

    Args:
        data (dict): A dictionary containing the SharePoint site credentials.
        url (str): The URL of the SharePoint site.
        file_list (list): A list of files in the SharePoint site.

    Returns:
        list: A list containing the content of the head.md file,
        followed by the content of the foot.md file.
    """
    response = []
    exts = ['extra', 'codehilite', 'tables', 'toc']
    if data['ApiOnedriveSetting'].get('top_md') and 'top.md' in str(file_list):
        res = requests.get(sharepointpw_getdownloadlink(
            data, alia, path + '/top.md'),
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
        res = requests.get(sharepointpw_getdownloadlink(
            data, alia, path + '/bottom.md'),
                           timeout=config.REQUEST_TIME_OUT)
        if res.ok:
            txt = Markup(markdown.markdown(res.text, extensions=exts))
            response.append(txt)
        else:
            response.append(None)
    else:
        response.append(None)
    return response
