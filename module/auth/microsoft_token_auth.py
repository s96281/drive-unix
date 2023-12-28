"""
Get the token to access Sharepoint drive.
"""
import json
import time
import urllib.parse
import requests
from flask import make_response, render_template, redirect, Request, Response
from module.read_write_data import write_data
from module import config, functions


def init_access_token(data: str, request: Request) -> Response:
    """
    Initiates the access token for Microsoft Graph API.

    Args:
    - data (str): JSON string containing access and refresh tokens for the given site.
    - request (Request): Request object from Flask.

    Returns:
    - Response: Flask Response object.

    Raises:
    - KeyError:
        If access or refresh token is not present in the response from the authorization server.

    """
    site = request.path.split('/')[1]
    client_id = data["Sites"][site]["client_id"]
    client_secret = data["Sites"][site]["client_secret"]
    redirect_uri = data["Sites"][site]["redirect_uri"]
    authorization_url = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id='\
        +client_id\
        +'&response_type=code&redirect_uri='\
        + urllib.parse.quote(
            redirect_uri
        )\
        +'&scope=https%3A%2F%2Fgraph.microsoft.com%2FFiles.ReadWrite.All'\
        +'%20Sites.ReadWrite.All%20offline_access'
    if not request.args.get("code") and not request.form.get("code"):
        response = make_response(
            render_template("init_access_token.html",
                            authorization_url=authorization_url))
    else:
        code = request.form.get("code") if request.form.get(
            "code") else request.args.get("code")
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'
        }
        url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
        form_data = {
            'client_id': client_id,
            'scope':
            'https://graph.microsoft.com/Files.ReadWrite.All Sites.ReadWrite.All offline_access',
            'redirect_uri': redirect_uri,
            'client_secret': client_secret,
            'grant_type': 'authorization_code',
            'code': code
        }
        form_data = urllib.parse.urlencode(form_data)
        res = requests.post(url=url,
                            headers=headers,
                            data=form_data,
                            timeout=config.REQUEST_TIME_OUT).json()
        try:
            access_token = res['access_token']
            refresh_token = res['refresh_token']
            data["Sites"][site]["access_token"] = access_token
            data["Sites"][site]["refresh_token"] = refresh_token
            data["Sites"][site]["t"] = time.time()
            write_data(data)
            response = make_response(redirect(request.url.split('?')[0]))
        except KeyError:
            response = make_response(
                render_template("init_access_token.html",
                                authorization_url=authorization_url,
                                warning="Error!" + json.dumps(res)))
    return response


def reflash_token(data: dict, alia: str) -> dict:
    """
    Refreshes the access token for a given site
    using the refresh token stored in the data dictionary.

    Args:
        data (dict): A dictionary containing the configuration data for the application.
        site (str): The name of the site for which to refresh the access token.

    Returns:
        dict: A dictionary containing the configuration data for the application.

    Raises:
        KeyError: If the JSON response from the token endpoint does not contain the expected keys.
    """
    client_id = data["Sites"][alia]['client_id']
    client_secret = data["Sites"][alia]['client_secret']
    redirect_uri = data["Sites"][alia]['redirect_uri']
    refresh_token = data["Sites"][alia]['refresh_token']
    url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'
    }
    formdata = f"client_id={client_id}"\
        + '&scope=https%3A%2F%2Fgraph.microsoft.com%2FFiles.ReadWrite.All%20Sites.ReadWrite.All'\
        + '%20offline_access'\
        + f"&redirect_uri={redirect_uri}"\
        + f"&client_secret={client_secret}"\
        + f"&grant_type=refresh_token&refresh_token={refresh_token}"
    try:
        retur = requests.post(url=url,
                              headers=headers,
                              data=formdata,
                              timeout=config.REQUEST_TIME_OUT).json()
        access_token = retur['access_token']
        refresh_token = retur['refresh_token']
        data["Sites"][alia]["access_token"] = access_token
        data["Sites"][alia]["refresh_token"] = refresh_token
        data["Sites"][alia]["t"] = time.time()
        write_data(data)
        return data
    except KeyError:
        functions.log("ERROR", json.dumps(retur))


def read_token(data: dict, alia: str) -> str:
    """
    Get the access token for the specified site from the data dictionary.
    If the access token has expired (more than 1 hour old), the function refreshes the token 
    by calling the `reflash_token` function and updates the data dictionary. The updated 
    access token is then returned.

    Args:
        data (dict): A dictionary that contains information for accessing the site.
        site (str): The name of the site to access.

    Returns:
        str: The access token for the specified site.
    """
    if time.time() - data["Sites"][alia]['t'] > 60*60:
        data = reflash_token(data, alia)
    access_token = data["Sites"][alia]["access_token"]
    return access_token
