"""
Read Write File
"""
import json
import os
import time
from redis import Redis
from module import config, functions

def read_data(redis: Redis | None = config.REDIS,
              redis_sync_key: str | None = config.REDIS_SYNC_KEY,
              data_location: str = config.DATA_LOCATION,
              redis_sync_expires: int = int(config.REDIS_SYNC_EXPIRES),
              redis_sync: bool = config.REDIS_SYNC) -> dict | None:
    """
    Reads and returns data from Redis or a local cache file.

    Parameters:
    -   redis (Redis): Redis instance to connect to.
    -   redis_sync (bool): Flag to determine whether to use Redis as the data source.
    -   redis_sync_key (str): Key to use for Redis.
    -   data_location (str): Path to the local cache file.
    -   redis_sync_expires (int): Expiration time (in seconds) for the Redis cache.

    Returns:
    -   dict or None: If Redis is used, returns a dictionary containing the retrieved data.
        If a local cache file is used or Redis fails to retrieve data, returns None.

    Raises:
    -   N/A
    """
    if redis_sync:
        functions.log("INFO", '讀取資料中...')
        if os.path.isfile(data_location):
            functions.log("INFO", '存在緩存資料...')
            with open(data_location, 'r', encoding='utf-8') as file:
                data = json.loads(file.read())
                functions.log("INFO", '讀取緩存資料...')
            if data['TIME'] < (time.time() - redis_sync_expires):
                functions.log("INFO", '緩存過期...')
                data = {}
                functions.log("INFO", '線上取得資料...')
                data = redis.get(redis_sync_key)
                if data:
                    data = json.loads(data)
                    time_of_now = time.time()
                    data['TIME'] = time_of_now
                    with open(data_location, 'w', encoding='utf-8') as file:
                        functions.log("INFO", '寫入緩存...')
                        file.write(json.dumps(data, ensure_ascii=False))
                else:
                    functions.log("INFO", '資料取得失敗，將進行初始化作業')
                    data = None
        else:
            functions.log("INFO", '不存在緩存資料...')
            data = {}
            functions.log("INFO", '線上取得資料...')
            data = redis.get(redis_sync_key)
            if data:
                data = json.loads(data)
                time_of_now = time.time()
                data['TIME'] = time_of_now
                with open(data_location, 'w', encoding='utf-8') as file:
                    functions.log("INFO", '寫入緩存...')
                    file.write(json.dumps(data, ensure_ascii=False))
                functions.log("INFO", '成功讀取資料')
            else:
                functions.log("INFO", '資料取得失敗，將進行初始化作業')
                data = None
    else:
        functions.log("INFO", '讀取資料中...')
        if os.path.isfile(data_location):
            functions.log("INFO", '存在緩存資料...')
            with open(data_location, 'r', encoding='utf-8') as file:
                data = json.loads(file.read())
                functions.log("INFO", '讀取緩存資料...')
            functions.log("INFO", '成功讀取資料')
        else:
            functions.log("INFO", '資料取得失敗，將進行初始化作業')
            data = None
    return data


def write_data(data: dict,
               redis: Redis | None = config.REDIS,
               redis_sync_key: str | None = config.REDIS_SYNC_KEY,
               data_location: str = config.DATA_LOCATION,
               redis_sync: bool = config.REDIS_SYNC) -> bool:
    """
    Writes data to a Redis database or local cache file.

    Args:
    -   data (dict): The data to be written.
    -   redis (Redis | None): A Redis client object.
    -   redis_sync_key (str | None): The key to use for Redis storage.
    -   data_location (str): The path to the local cache file.
    -   redis_sync (bool): A boolean indicating whether to use Redis as the data source.

    Returns:
    -   bool: True if the write was successful.

    Raises:
    -   N/A
    """
    data = json.dumps(data, ensure_ascii=False)
    if redis_sync:
        redis.set(redis_sync_key, data)
    with open(data_location, 'w', encoding='utf-8') as file:
        file.write(data)
    return True
