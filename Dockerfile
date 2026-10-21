# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    CONFIG_DIR=/root/.config/drive-unix

WORKDIR /app

# 1. 安裝系統基礎套件與 Playwright 運作所需的函式庫
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    ca-certificates \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# 2. 複製專案檔案
COPY pyproject.toml requirements.txt ./
COPY . /app

# 3. 安裝 Python 依賴項及 Playwright 瀏覽器核心 (支援 SharePoint Cookie 自動登入與換發)
RUN pip install --no-cache-dir -e ".[all,web]" && \
    playwright install chromium

# 4. 建立設定檔掛載點目錄
RUN mkdir -p /root/.config/drive-unix

VOLUME ["/root/.config/drive-unix"]

EXPOSE 8000

# 預設執行憑證換發守護行程 (亦可透過 docker-compose 覆寫為 web 伺服器)
CMD ["drive-unix", "upstash", "renew-tokens", "--interval", "1800", "--leeway", "60"]
