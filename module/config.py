"""
Provides configuration variables and functions for the application.
"""
import os
from redis import Redis

DEBUG = False

# 設定設定檔、金鑰、快取存放位置
if os.name == 'nt':  # Windows
    CACHE_LOCATION = './data/cache'
    DATA_LOCATION = './data/data'
    COOKIES_LOCATION = './data/cookies'
else:  # Linux、MacOS
    DATA_LOCATION = './data/data'
    COOKIES_LOCATION = './data/cookies'
    CACHE_LOCATION = './data/cache'

# 如果你的資料庫擁有上萬文件，可以適當調高此參數(建議不高於5000)
REQUEST_SIZE = 2000

# 設定是否由資料庫同步資料
REDIS_SYNC = False
# 設定Redis資料庫
REDIS = Redis(
    host='global-liked-dassie-31251.upstash.io',
    port='31251',
    password='585f5b3af15540d381dc46bf429a7420',
    ssl=True,
    decode_responses=True
)
# 設定同步資料間隔時間
REDIS_SYNC_EXPIRES = 432000
# 設定資料庫鍵
REDIS_SYNC_KEY = 'HenrySharePoint'

REQUEST_TIME_OUT = 30

UTC = 8

CACHE_CONFIG = {
    "DEBUG": False,
    "CACHE_TYPE": "FileSystemCache",
    "CACHE_DEFAULT_TIMEOUT": 4320000,
    "CACHE_IGNORE_ERRORS": False,
    "CACHE_DIR": CACHE_LOCATION,
    "CACHE_THRESHOLD": 500
}

HEADINGS = ['Name', 'Last edit time', 'Size']
