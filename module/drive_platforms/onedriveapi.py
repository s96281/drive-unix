"""
Read OneDrive with access token.
"""
import urllib.parse
import markdown
import requests
from markupsafe import Markup
from module.auth import microsoft_token_auth
from module import config


def ondriveapi_detail(data: dict, alia: str) -> dict:
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
        access_token = microsoft_token_auth.read_token(data, alia)
        url = 'https://graph.microsoft.com/v1.0/drive/root'
        headers = {'Authorization': 'Bearer ' + access_token}
        res = requests.get(url,
                           headers=headers,
                           timeout=config.REQUEST_TIME_OUT).json()
        return res
    except KeyError:
        return {"error": f"Drive {alia} not found."}


def onedriveapi_getdownloadlink(data: dict, alia: str,
                                  path: str) -> str | dict:
    """Get the download link of a file from a OneDrive.

    Args:
    -   data (dict): A dictionary containing information about the OneDrive.
    -   alia (str): The alia of the OneDrive site.
    -   path (str): The path of the file in the OneDrive.

    Returns:
    -   str or dict: The download link of the file if it exists,
            otherwise dict that contain the reasion of error.

    """
    try:
        access_token = microsoft_token_auth.read_token(data, alia)
        path = urllib.parse.quote(path)
        url = f'https://graph.microsoft.com/v1.0/drive/root:{path}'
        headers = {'Authorization': 'Bearer ' + access_token}
        res = requests.get(url,
                           headers=headers,
                           timeout=config.REQUEST_TIME_OUT).json()
        if "@microsoft.graph.downloadUrl" in res:
            return res["@microsoft.graph.downloadUrl"]
        return {"error": res}
    except KeyError:
        return {"error": f"Drive {alia} not found."}


def nextpage(header: dict, url: str) -> dict:
    """
    Fetches all items in a OneDrive folder or drive page by page
    and returns a dictionary of file/folder details.
    
    Args:
    header (dict): HTTP headers to be included in the request.
    url (str): The URL of the OneDrive folder or drive page.
    
    Returns:
    dict: A dictionary of file/folder details for all items in the OneDrive folder or drive.
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


def onedriveapi_root_files(data: dict, alia: str) -> dict:
    """
    Returns a dictionary of the OneDrive files and folders located in the root path.
    
    Args:
    - data (dict): A dictionary containing OneDrive site credentials.
    - site (str): The name of the OneDrive site.
    
    Returns:
    - dict: A dictionary containing the retrieved root files and folders of the OneDrive site.
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
        access_token = microsoft_token_auth.read_token(data, alia)
        headers = {'Authorization': 'Bearer ' + access_token}
        url = f'https://graph.microsoft.com/v1.0/drive/root/children?$top={str(config.REQUEST_SIZE)}&select=name,folder,lastModifiedDateTime,size'
        res = requests.get(url=url,
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


def onedriveapi_path_files(data: dict, alia: str, path: str) -> dict:
    """
    Returns a dictionary of the OneDrive files and folders located in the specified path.
    
    Args:
    - data (dict): A dictionary containing OneDrive site credentials.
    - site (str): The name of the OneDrive site.
    - path (str): The path of the folder whose files and subfolders are to be returned.
    
    Returns:
    - dict: A dictionary containing the retrieved root files and folders of the OneDrive site.
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
        access_token = microsoft_token_auth.read_token(data, alia)
        headers = {'Authorization': 'Bearer ' + access_token}
        path = urllib.parse.quote(path)
        url = f'https://graph.microsoft.com/v1.0/drive/root:{path}:/children?$top={str(config.REQUEST_SIZE)}&select=name,folder,lastModifiedDateTime,size'
        res = requests.get(url=url,
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


def onedriveapi_files(data: dict, alia: str, path: str = None) -> dict:
    """
    Retrieves files and folders information from a OneDrive site's root or a specified path.

    Args:
        data (dict): A dictionary containing information about the OneDrive sites,
        including endpoints, usernames, passwords, and aliases.
        site (str): The alias of the OneDrive site.
        path (str, optional): The path from which to retrieve files and folders. Defaults to None.

    Returns:
        dict: A dictionary containing the name, type, lastModifiedDateTime,
        and size of each file and folder at the specified site or path.
    """
    if path:
        ret = onedriveapi_path_files(data, alia, path)
    else:
        ret = onedriveapi_root_files(data, alia)
    return ret


def onedriveapi_thumbnail(data: dict, alia: str, path: str) -> dict:
    """
    Return a dictionary like {"url": "The thumbnail url of file"} if the file is exist.

    Args:
    - data: A dictionary containing information about the OneDrive.
    - alia: The alia of the OneDrive site.
    - path: The path of the folder whose files and subfolders are to be returned.

    Returns:
    - dict: A dictionary conatin the url of thumbnail or error message.

    Raises:
        N/A.
    """
    try:
        access_token = microsoft_token_auth.read_token(data, alia)
        headers = {'Authorization': 'Bearer ' + access_token}
        path = urllib.parse.quote(path)
        url = f'https://graph.microsoft.com/v1.0/drive/root:{path}:/thumbnails'
        res = requests.get(url,
                           headers=headers,
                           timeout=config.REQUEST_TIME_OUT).json()
        if 'error' in res:
            response = {"error": res["error"]}
        else:
            response = {"url": res["value"][0][config.THUMBNAIL_SIZE]}
        return response
    except KeyError:
        return {"error": f"Drive {alia} not found."}


def onedriveapi_head_foot_note(data: dict, alia: str, path: str,
                                file_list: list) -> list:
    """
    Returns the content of the head.md and foot.md files in the OneDrive site.

    Args:
        data (dict): A dictionary containing the OneDrive site credentials.
        url (str): The URL of the OneDrive site.
        file_list (list): A list of files in the OneDrive site.

    Returns:
        list: A list containing the content of the head.md file,
        followed by the content of the foot.md file.
    """
    response = []
    exts = ['extra', 'codehilite', 'tables', 'toc']
    if data['ApiOnedriveSetting'].get('top_md') and 'top.md' in str(file_list):
        res = requests.get(onedriveapi_getdownloadlink(
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
        res = requests.get(onedriveapi_getdownloadlink(
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
