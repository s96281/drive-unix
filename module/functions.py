"""
Different small functions.
"""
import random
import urllib
from datetime import datetime, timedelta
from module import config


def sizeof_fmt(num: float | int, suffix: str = "B") -> str:
    """
    Formats the given size in bytes into a human-readable string with appropriate unit suffix.

    Args:
        num (float or int): The size in bytes to be formatted.
        suffix (str, optional): The unit suffix to be appended to the formatted string.
            Default is "B".

    Returns:
        str: A human-readable string representing the size with appropriate unit suffix.

    Examples:
        >>> sizeof_fmt(1024)
        '1.0KiB'
        >>> sizeof_fmt(123456789)
        '117.7MiB'
        >>> sizeof_fmt(9876543210, "bytes")
        '9.2GiBytes'
    """
    for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"


def utc_local_convert(time: float, utc: int = config.UTC) -> str:
    """
    Converts a UTC timestamp into a local time string.

    Args:
        time (float): A UTC timestamp in seconds since the epoch.
        utc (int, optional): The offset from UTC in hours. Default is 0.

    Returns:
        str: A string representing the local time in the format "Day Mon DD HH:MM:SS YYYY", where:
            - Day is the abbreviated name of the day of the week (e.g. "Mon").
            - Mon is the abbreviated name of the month (e.g. "Jan").
            - DD is the day of the month as a zero-padded decimal number (e.g. "01").
            - HH is the hour (24-hour clock) as a zero-padded decimal number (e.g. "08").
            - MM is the minute as a zero-padded decimal number (e.g. "59").
            - SS is the second as a zero-padded decimal number (e.g. "23").
            - YYYY is the year as a four-digit decimal number (e.g. "2022").

    Examples:
        >>> utclocalconvert(1643108652.0)
        'Sat Jan 29 17:50:52 2022'
        >>> utclocalconvert(1643108652.0, -5)
        'Sat Jan 29 12:50:52 2022'
    """
    utc_format = "%Y-%m-%dT%H:%M:%SZ"
    utc_time = datetime.strptime(time, utc_format)
    local_time = utc_time + timedelta(hours=utc)
    return local_time.ctime()


def url_standardization(url: str) -> str:
    """
    Converts a URL string to a standardized format.

    Args:
        url (str): A string representing a URL.

    Returns:
        str: A string representing the standardized format of the input URL, where:
            - The URL is first unquoted using the urllib.parse.unquote() function.
            - The unquoted URL is then quoted again using the urllib.parse.quote() function,
                using the safe characters '/?='.

    Examples:
        >>> url_standardization("param1=value1&param2=value2")
        'param1=value1%26param2=value2'
    """
    url = urllib.parse.unquote(url)
    url = urllib.parse.quote(url, safe='/?=')
    return url


def random_background(data: dict) -> str:
    """
    Returns a randomly selected background image from a list of images obtained from the input
        dictionary.

    Args:
        data (dict): A dictionary containing the 'ApiOnedriveSetting' key, which maps to another
            dictionary containing the 'backgroudimagelist' key. The value of this key is a list of
            strings representing URLs of background images.

    Returns:
        str: A string representing a URL of a randomly selected background image from the input.
            If the list is empty or the keys are not present in the input dictionary,
            an empty string is returned.

    Raises:
        IndexError: If the input list is empty.
        KeyError: If the 'ApiOnedriveSetting' or 'backgroudimagelist' keys
            are not present in the input dictionary.
    """
    try:
        background_image_list = data['ApiOnedriveSetting'][
            'backgroud_image_list']
        background_image = background_image_list[
            random.randint(0, len(background_image_list)) - 1]
    except (IndexError, KeyError) as esc:
        print({"error": esc})
        background_image = ''
    return background_image


def list_drive(data: dict) -> list:
    """
    Returns a list of all the drives available in the data dictionary.
    
    Args:
    - data (dict): A dictionary containing all the SharePoint site data.
    
    Returns:
    - A list of all the drives available in the data dictionary.
    """
    return list(data['Sites'])


def get_file_type(extension: str) -> str:
    """
    Determines the type of a file based on its extension.

    Args:
        extension (str): The file extension to check.

    Returns:
        str: The file type, which can be one of the following: 'video', 'image',
             'audio', 'office', 'text', 'program', or 'unknown'.
    """
    extension = extension.lower()
    video_extensions = [".mp4", ".mkv", ".flv", ".avi", ".mov", ".wmv"]
    image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp"]
    audio_extensions = [".mp3", ".wav", ".flac", ".aac"]
    document_extensions = [".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".pdf"]
    text_extensions = [".txt"]
    program_extensions = [".json", ".py",
                          ".c", ".cpp", ".java", ".html", ".htm"]

    if extension in video_extensions:
        return "video"
    elif extension in image_extensions:
        return "image"
    elif extension in audio_extensions:
        return "audio"
    elif extension in document_extensions:
        return "office"
    elif extension in text_extensions:
        return "text"
    elif extension in program_extensions:
        return "programe"
    else:
        return "unknown"
