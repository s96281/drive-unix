"""
IDK
"""
import requests
from module.drive_platforms import sharepointpassword, onedrivepassword
from module import config


def drivetype(data: dict, url: str) -> str:
    """
    Returns the type of the drive (e.g. OneDrive, SharePoint) associated with the provided URL,
    if it exists in the given data dictionary.

    Args:
    - data (dict): A dictionary containing information about the drives.
    - url (str): The URL of the drive whose type needs to be determined.

    Returns:
    - str: The type of the drive associated with the provided URL,
        if it exists in the data dictionary. If the URL
        is not found in the dictionary, returns None.
    """
    try:
        return data["Sites"][url.split('/')[0]]['type']
    except KeyError:
        return None


def get_downloadlink(data: dict, alia: str, path: str) -> str | None:
    """
    Get download link of a file located in the specified drive and path.

    Args:
    - data (dict): The dictionary containing the credentials and information for all drives.
    - site (str): The name of the site where the file is located.
    - path (str): The path to the file in the site.

    Returns:
    - str: The download link of the file if it is successfully retrieved.
    - dict: A dictionary containing an error message if the download link cannot be retrieved.

    Raises:
    - None

    """
    site_type = data["Sites"][alia]["type"]
    if site_type == "SharePointSitePW":
        ret = sharepointpassword.sharepointpw_getdownloadlink(
            data, alia, path)
    elif site_type == "SharePointSiteAPI":
        pass
    elif site_type == "OneDrivePW":
        ret = onedrivepassword.ondrivepw_getdownloadlink(data, alia, path)
    elif site_type == "OneDriveAPI":
        pass
    elif site_type == "GoogleDriveAPI":
        pass
    return ret


def get_page_encrypt_pw(data: dict, path: str) -> str | None:
    """
    Returns the encryption password for a page if page encryption is enabled and
    the password file exists.

    Args:
    - data: A dictionary containing configuration data.
    - path: The path to the page for which to retrieve the encryption password.

    Returns:
    - The encryption password if page encryption is enabled and the password file
      exists, or None otherwise.
    """
    if not data["ApiOnedriveSetting"]["page_encrypt"] or len(path.split('/')) < 1:
        return None
    path += '/' + data["ApiOnedriveSetting"]["passfile"]
    alia = path.split('/')[0]
    path = '/'.join(path.split('/')[1:])
    url = get_downloadlink(data, alia, path)
    if 'error' not in url:
        res = requests.get(url, timeout=config.REQUEST_TIME_OUT)
        return res.text if res.ok else None
    return None


def details(data: dict, alia: str) -> dict:
    """
    Returns details for the specified drive.

    Args:
        data (dict): The data dictionary containing information about the drives.
        alia (str): The name of the drive for which details are required.

    Returns:
        dict: A dictionary containing details for the specified drive.

    Raises:
        None
    """
    drive_type = drivetype(data, alia)
    if drive_type == "SharePointSitePW":
        ret = sharepointpassword.sharepointpw_details(data, alia)
    elif drive_type == "SharePointSiteAPI":
        pass
    elif drive_type == "OneDrivePW":
        ret = onedrivepassword.ondrivepw_detail(data, alia)
    elif drive_type == "OneDriveAPI":
        pass
    elif drive_type == "GoogleDriveAPI":
        pass
    return ret


def files(data: dict, alia: str, path: str = None) -> dict:
    drive_type = drivetype(data, alia)
    if drive_type == "SharePointSitePW":
        ret = sharepointpassword.sharepointpw_files(data, alia, path)
    elif drive_type == "SharePointSiteAPI":
        pass
    elif drive_type == "OneDrivePW":
        ret = onedrivepassword.onedrivepw_files(data, alia, path)
    elif drive_type == "OneDriveAPI":
        pass
    elif drive_type == "GoogleDriveAPI":
        pass
    return ret


def head_foot_note(data: dict, alia: str, path: str, file_list: list) -> list:
    drive_type = drivetype(data, alia)
    if drive_type == "SharePointSitePW":
        ret = sharepointpassword.sharepointpw_head_foot_note(data, alia, path, file_list)
    elif drive_type == "SharePointSiteAPI":
        pass
    elif drive_type == "OneDrivePW":
        ret = onedrivepassword.onedrivepw_head_foot_note(data, alia, path, file_list)
    elif drive_type == "OneDriveAPI":
        pass
    elif drive_type == "GoogleDriveAPI":
        pass
    return ret
