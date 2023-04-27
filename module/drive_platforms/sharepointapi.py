"""
Read SharePoint Sites with access token.
"""
import urllib.parse
import markdown
import requests
from markupsafe import Markup
from module.auth import token_auth
from module import config


def sharepointapi_details(data: dict, alia: str) -> dict:
    try:
        site = data['Sites'][alia]["site"]
        access_token = token_auth.read_token(data, site)
        headers = {'Authorization': 'Bearer ' + access_token}
        url = "https://graph.microsoft.com/v1.0/sites/" + site + "/drive/root/children"
        res = requests.get(url,
                           headers=headers,
                           timeout=config.REQUEST_TIME_OUT).json()
        return res
    except KeyError:
        return {"error": f"Drive {alia} not found."}

