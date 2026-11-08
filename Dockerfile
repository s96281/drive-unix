# syntax=docker/dockerfile:1
# ==============================================================================
# drive-unix Production Multi-Layer Caching Dockerfile
# Base Image: Python 3.12-slim (Debian Bookworm)
# Includes: FastAPI Web Backend, Playwright Chromium for SharePoint MFA,
#           pre-built React SPA static assets, and backward-compatible symlinks.
# ==============================================================================

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    CONFIG_DIR=/root/.config/drive-unix

WORKDIR /app

# 1. 安裝系統基礎套件與 Playwright Headless Chromium 運作所需之底層圖形庫
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

# 2. 多層快取優化：先複製依賴定義檔並預安裝所有依賴
# 透過最小模組骨架滿足 setuptools 套件發現機制，使依賴項與 Chromium 瀏覽器
# 在程式碼更動時能完全命中 Docker build 快取，避免重複下載。
COPY pyproject.toml requirements.txt README.md ./
RUN mkdir -p application auth cli core domain infrastructure providers storage web && \
    touch main.py application/__init__.py auth/__init__.py cli/__init__.py core/__init__.py \
          domain/__init__.py infrastructure/__init__.py providers/__init__.py storage/__init__.py web/__init__.py && \
    pip install --no-cache-dir -e ".[all,web]" && \
    playwright install chromium && \
    (playwright install-deps chromium || true)

# 3. 複製應用程式完整原始碼與 web/static/ 預先編譯之 SPA 靜態檔案
COPY . /app

# 重新以 editable 模式更新專案入口點映射 (因所有相依套件均已安裝，耗時小於 1 秒)
RUN pip install --no-cache-dir --no-deps -e .

# 4. 建立相容性符號連結：確保 core/config.py 的 ~/.config/mycli 與 ~/.config/drive-unix 雙向一致
RUN mkdir -p /root/.config/drive-unix && \
    ln -s /root/.config/drive-unix /root/.config/mycli

# 5. 持久化 Volume 與服務監聽埠
VOLUME ["/root/.config/drive-unix"]
EXPOSE 8000

# 6. 原生容器健全度檢查探針 (定期向 /api/health 端點確認服務存活)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# 7. 預設啟動指令：啟動 Web 控制台與 REST API (亦可透過 docker-compose 覆寫為 token-center)
CMD ["python", "-m", "web", "--host", "0.0.0.0", "--port", "8000"]
