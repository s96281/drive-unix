"""
Provides configuration variables and functions for the application.
"""
import os
from redis import Redis

# 設定設定檔、金鑰、快取存放位置
if os.name == 'nt':  # Windows
    CACHE_LOCATION = './data/cache'
    DATA_LOCATION = './data/data'
    COOKIES_LOCATION = './data/cookies'
    LOG_LOCATION = './data/log.txt'
else:  # Linux、MacOS
    DATA_LOCATION = './data/data'
    COOKIES_LOCATION = './data/cookies'
    CACHE_LOCATION = './data/cache'
    LOG_LOCATION = './data/log.txt'

# 如果你的資料庫中單個文件夾擁有大量文件，可以適當調高此參數(建議不高於5000)
REQUEST_SIZE = 2000

# 設定是否由資料庫同步資料
REDIS_SYNC = os.environ.get("REDIS_SYNC") != "False"
# 設定Redis資料庫
REDIS = Redis(
    host=os.environ.get("REDIS_host") or 'global-liked-dassie-31251.upstash.io',
    port=os.environ.get("REDIS_port") or '31251',
    password=os.environ.get("REDIS_password") or '585f5b3af15540d381dc46bf429a7420',
    ssl=True,
    decode_responses=True
)
# 設定同步資料間隔時間
REDIS_SYNC_EXPIRES = os.environ.get("REDIS_SYNC_EXPIRES") or 3600 # Sync per hour
# 設定資料庫鍵
REDIS_SYNC_KEY = os.environ.get("REDIS_SYNC_KEY") or 'TEMP_DATA'


UTC = os.environ.get("UTC") or 8


# 請勿更改下列設定，除非你知道自己在做甚麼
CACHE_CONFIG = {
    "DEBUG": False,
    "CACHE_TYPE": "FileSystemCache",
    "CACHE_DEFAULT_TIMEOUT": 4320000,
    "CACHE_IGNORE_ERRORS": False,
    "CACHE_DIR": CACHE_LOCATION,
    "CACHE_THRESHOLD": 500
}


DEBUG = False

HEADINGS = ['Name', 'Last edit time', 'Size']

REQUEST_TIME_OUT = 30

THUMBNAIL_SIZE = "large" # or "medium", "small"

LOG_LEVEL = "WARN" # or "ERROR", "INFO"
