"""
Permission control.
"""
import hashlib
from flask import Request, Response, make_response, redirect, render_template, url_for
from module import functions
from module.read_write_data import read_data

def is_login(data: dict, user_request: Request) -> bool:
    """
    Determines if a user is logged in based on their cookies and the data dictionary.

    Args:
    -   data (dict): A dictionary containing the 'ApiOnedriveSetting' key,
            which maps to another dictionary containing the 'users' key.
            The value of this key is a dictionary mapping usernames to another
            dictionary containing the 'password' key.
            The value of this key is the hashed password for the user.
    -   user_request (request): A request object containing the user's cookies.

    Returns:
    -   bool: True if the user is logged in and their password matches the
            hashed password in the data dictionary, False otherwise.

    Raises:
    -   KeyError: If the 'ApiOnedriveSetting' or 'users' keys are not present
            in the input dictionary.
    """
    user = user_request.cookies.get('user')
    password = user_request.cookies.get('password')
    try:
        password_hash = data["ApiOnedriveSetting"]["users"][user]["password"]
    except KeyError as esc:
        functions.log("ERROR", esc)
        return False
    if password_hash == password:
        return True
    return False


def is_admin(data: dict, user_request: Request) -> bool:
    """
    Determines if a user is logged in as an admin based on their cookies and the data dictionary.

    Args:
    -   data (dict): A dictionary containing the 'ApiOnedriveSetting' key,
            which maps to another dictionary containing the 'users' key.
            The value of this key is a dictionary mapping usernames to
            another dictionary containing the 'password' and 'rank' keys.
            The value of the 'password' key is the hashed password for
            the user and the value of the 'rank' key is their user rank.
    -   user_request (request): A request object containing the user's cookies.

    Returns:
    -   bool: True if the user is logged in and their rank is 'admin' in the data dictionary,
            False otherwise.

    Raises:
    -   KeyError: If the 'ApiOnedriveSetting' or 'users' keys are not present in the input
            dictionary.
    """
    user = user_request.cookies.get('user')
    try:
        if data["ApiOnedriveSetting"]["users"][user]["rank"] == "admin":
            return True
        return False
    except KeyError:
        return False


def login(user_request: Request) -> Response:
    """
    Handles user login authentication and sets cookies.

    Args:
    -   user_request (Request): The HTTP request object containing user login information.

    Returns:
    -   Response: The HTTP response object with the appropriate redirection or error message.

    Raises:
    -   N/A
    """
    data = read_data()
    users = data["ApiOnedriveSetting"]["users"]
    if user_request.method == 'GET':
        user = user_request.cookies.get('user')
        password = user_request.cookies.get('password')
        if user in users and users[user]["password"] == password:
            response = make_response(redirect(user_request.full_path))
        else:
            response = make_response(render_template('sharepoint_login.html'))
    elif user_request.method == 'POST':
        user = user_request.form.get('user')
        password = user_request.form.get('password')
        pdhash = hashlib.sha256(password.encode()).hexdigest()
        if user in users and users[user]["password"] == pdhash:
            response = make_response(redirect(user_request.full_path))
            response.set_cookie('user', user, path='/')
            response.set_cookie('password', pdhash, path='/')
        else:
            response = make_response(render_template(
                'sharepoint_login.html', warning='錯誤'))
    return response


def logout(request: Request) -> Response:
    """
    Clears user cookies and redirects back to the previous page or to the home page.

    Args:
    -   request (Request): The request object containing the cookies to be cleared.

    Returns:
    -   Response: A response object with cleared cookies and a redirect to the previous
            page or home page.

    Raises:
    -   N/A
    """
    if request.referrer:
        response = make_response(redirect(request.referrer))
    else:
        response = make_response(redirect(url_for('home')))
    response.set_cookie('user', '', path='/', expires=0)
    response.set_cookie('password', '', path='/', expires=0)
    return response

def check_viewer_permission(request: Request, data: dict, path: str, password: str) -> bool:
    """
    Check viewer permission for accessing a resource based on the provided parameters.

    Args:
        request (Request): The HTTP request object.
        data (dict): A dictionary containing API settings, specifically 'ApiOnedriveSetting'.
        path (str): The path to the resource being accessed.
        password (str): The password provided for encrypted access, if applicable.

    Returns:
        bool: True if the viewer has permission to access the resource, False otherwise.

    The function evaluates viewer permission based on the encryption settings and the user's administrative status.
    - If encryption is set to 'None' and the user is an admin, permission is granted.
    - If encryption is set to 'page' or 'drive' and the user is not an admin, the function checks the provided password
      against the hashed password stored in the request cookies for the specified path.

    Note:
    - The function relies on the 'is_admin' function, which is expected to return a boolean indicating whether the
      user has administrative privileges.

    Example:
    ```
    permission = check_viewer_permission(request_object, api_data, "/documents", "secretpassword")
    if permission:
        # Allow access to the resource
    else:
        # Deny access to the resource
    ```
    """
    if data["ApiOnedriveSetting"]["encrypt"] == "None" or is_admin(data, request) is True:
        return True
    if data["ApiOnedriveSetting"]["encrypt"] == "page" and is_admin(data, request) is False:
        if request.cookies.get(path + "_pw") == hashlib.sha256(password.encode()).hexdigest():
            return True
        else:
            return False
    elif data["ApiOnedriveSetting"]["encrypt"] == "drive" and is_admin(data, request) is False:
        if request.cookies.get(path.split('/')[0] + "_pw") == hashlib.sha256(password.encode()).hexdigest():
            return True
        else:
            return False