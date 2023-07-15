"""
Read SharePoint Sites with access token.
"""
import urllib.parse
import markdown
import requests
from markupsafe import Markup
from module.auth import microsoft_token_auth
from module import config, read_write_data, functions


def sitename2id(data: dict, alia: str) -> str | None:
    """
    Convert Site name to id.
    
    Args:
    - data: A dictionary containing the SharePoint account list and its details.
    - alia: A string representing the name of the SharePoint site to access.

    Returns:
    - str or None: Retuen id string of the drive if it is exist, else return None.
    """
    try:
        if "id" not in data["Sites"][alia]:
            access_token = microsoft_token_auth.read_token(data, alia)
            headers = {'Authorization': 'Bearer ' + access_token}
            site = data['Sites'][alia]["site"]
            url = "https://graph.microsoft.com/v1.0/sites?search=*"
            res = requests.get(url,
                               headers=headers,
                               timeout=config.REQUEST_TIME_OUT).json()['value']
            site_id = None
            for i in res:
                if i["displayName"] == site:
                    site_id = i["id"].split(',')[1]
                elif i["name"] == site:
                    site_id = i["id"].split(',')[1]
            if site_id:
                data["Sites"][alia]["id"] = site_id
                read_write_data.write_data(data)
                return site_id
            raise RuntimeError(f"Can not get drive id of {alia}")
        return data["Sites"][alia]["id"]
    except KeyError:
        return None


def sharepointapi_details(data: dict, alia: str) -> dict:
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
        site_id = sitename2id(data, alia)
        access_token = microsoft_token_auth.read_token(data, alia)
        headers = {'Authorization': 'Bearer ' + access_token}
        url = "https://graph.microsoft.com/v1.0/sites/" + site_id + "/drive/root"
        res = requests.get(url,
                           headers=headers,
                           timeout=config.REQUEST_TIME_OUT).json()
        return res
    except KeyError:
        return {"error": f"Drive {alia} not found."}


def sharepointapi_getdownloadlink(data: dict, alia: str,
                                  path: str) -> str | dict:
    """Get the download link of a file from a SharePoint site.

    Args:
    -   data (dict): A dictionary containing information about the SharePoint sites.
    -   alia (str): The alia of the SharePoint site.
    -   path (str): The path of the file in the SharePoint site.

    Returns:
    -   str or dict: The download link of the file if it exists,
            otherwise dict that contain the reasion of error.

    """
    try:
        site_id = sitename2id(data, alia)
        access_token = microsoft_token_auth.read_token(data, alia)
        headers = {'Authorization': 'Bearer ' + access_token}
        path = urllib.parse.quote(path)
        url = "https://graph.microsoft.com/v1.0/sites/" + site_id + "/drive/root:/" + path
        res = requests.get(url,
                           headers=headers,
                           timeout=config.REQUEST_TIME_OUT).json()
        if "error" in res:
            functions.log("ERROR", res['error'])
        elif '@microsoft.graph.downloadUrl' in res:
            return res['@microsoft.graph.downloadUrl']
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


def sharepointapi_root_files(data: dict, alia: str) -> dict:
    try:
        response = {}
        site_id = sitename2id(data, alia)
        access_token = microsoft_token_auth.read_token(data, alia)
        headers = {'Authorization': 'Bearer ' + access_token}
        url = "https://graph.microsoft.com/v1.0/sites/" + site_id + "/drive/root/children"
        res = requests.get(url,
                           headers=headers,
                           timeout=config.REQUEST_TIME_OUT).json()
        for i in res['value']:
            response[i["name"]] = {
                "type": "folder" if "folder" in i else "file",
                "lastModifiedDateTime": i["lastModifiedDateTime"],
                "size": i["size"]
            }
        if "@odata.nextLink" in res:
            response.update(nextpage(headers, res["@odata.nextLink"]))
        return response
    except KeyError:
        return {"error": f"Drive {alia} not found."}


def sharepointapi_path_files(data: dict, alia: str, path: str) -> dict:
    try:
        response = {}
        site_id = sitename2id(data, alia)
        access_token = microsoft_token_auth.read_token(data, alia)
        headers = {'Authorization': 'Bearer ' + access_token}
        path = urllib.parse.quote(path)
        url = "https://graph.microsoft.com/v1.0/sites/" \
            + site_id + "/drive/root:/" + path + ":/children"
        res = requests.get(url,
                           headers=headers,
                           timeout=config.REQUEST_TIME_OUT).json()
        for i in res['value']:
            response[i["name"]] = {
                "type": "folder" if "folder" in i else "file",
                "lastModifiedDateTime": i["lastModifiedDateTime"],
                "size": i["size"]
            }
        if "@odata.nextLink" in res:
            response.update(nextpage(headers, res["@odata.nextLink"]))
        return response
    except KeyError:
        return {"error": f"Drive {alia} not found."}


def sharepointapi_files(data: dict, alia: str, path: str = None) -> dict:
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
        ret = sharepointapi_path_files(data, alia, path)
    else:
        ret = sharepointapi_root_files(data, alia)
    return ret


def sharepointapi_thumbnail(data: dict, alia: str, path: str) -> dict:
    pass


def sharepointapi_head_foot_note(data: dict, alia: str, path: str,
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
        res = requests.get(sharepointapi_getdownloadlink(
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
        res = requests.get(sharepointapi_getdownloadlink(
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
