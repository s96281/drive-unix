# VPS 憑證換發中心 (Token Renewal Center) 佈署手冊

本手冊說明如何將 `drive-unix` 佈署至雲端 VPS 主機，作為**集中式憑證換發中心 (Centralized Token Issuance & Renewal Center)**，藉由 Upstash E2EE Serverless Redis 實現多電腦/多裝置自動獲取最新 Token，避免 OAuth Token 或 SharePoint Cookie 過期與輪轉衝突 (Token Rotation Race Condition)。

---

## 1. 架構原理

```text
[個人電腦 / 工作站]                [雲端 Upstash Redis]               [VPS 憑證換發中心]
 (drive-unix client)               (E2EE 密文傳輸中心)               (drive-unix daemon 24/7)
         │                                 │                                 │
         │ 1. push (加密節點與密鑰)          │                                 │
         ├────────────────────────────────►│                                 │
         │                                 │ 2. pull (拉取解密節點)            │
         │                                 │◄────────────────────────────────┤
         │                                 │                                 │
         │                                 │    3. 週期巡檢 (每 30 分鐘)       │
         │                                 │       若 Token 接近過期 (<60分)  │
         │                                 │       經分散式鎖自動向雲端換發     │
         │                                 │                                 │
         │                                 │ 4. put_token (E2EE 回寫新憑證)   │
         │                                 │◄────────────────────────────────┤
         │ 5. 執行檔案操作時發現本地過期      │                                 │
         │    自動拉取最新憑證，無感繼續傳輸   │                                 │
         ├────────────────────────────────►│                                 │
```

### 核心優勢
- **避免重複登入**：個人電腦或自動化腳本不再因 OAuth Token 或 SharePoint Cookie 過期中斷。
- **防止 Token 輪轉失效**：微軟與 Google 的 Refresh Token 具有嚴格輪轉或單一有效性，VPS 透過 Upstash 分散式鎖 (`drive-unix:lock:<identity>`) 保證全網僅由單一節點換發。
- **端對端加密 (E2EE)**：所有憑證在離機前均以 AES-256-GCM (搭配 PBKDF2 600,000 次雜湊衍生金鑰) 加密，Upstash 雲端無法讀取任何明文。
- **Headless 支援**：整合 Playwright Chromium，即便 SharePoint 需要瀏覽器 Cookie 亦可在無 GUI 的 Linux VPS 背景無縫自動換發。

---

## 2. 準備工作

1. **取得 Upstash Redis 認證**：
   - 至 [Upstash Console](https://console.upstash.com/) 建立免費 Redis 資料庫。
   - 取得 **REST URL** (例如 `https://...upstash.io`) 與 **REST Token**。
2. **在本地電腦推送既有節點拓撲**：
   在已有設定 Google Drive、OneDrive 或 SharePoint 的本地電腦執行：
   ```bash
   # 設定 Upstash 連線資訊
   drive-unix upstash config

   # 加密上傳至 Upstash (設定一組您記得住的 E2EE 主密碼 Passphrase)
   drive-unix upstash push -p 'YourSecretPassphrase'
   ```

---

## 3. 佈署方式 A：原生 Linux Systemd 服務 (推薦)

適用於標準 Ubuntu 22.04 / 24.04 或 Debian 12 VPS，環境將直接建立在您的家目錄（例如 `~/drive-unix`），避免 root 權限衝突。

### 步驟 1：使用一鍵安裝腳本
在 VPS 專案目錄（例如 `~/drive-unix`）下執行：
```bash
sudo bash deploy/setup_vps.sh
```
該腳本會自動完成：
- 識別目前登入使用者，並在使用者家目錄建立環境。
- 安裝 Python 3.12 系統相依套件與建置工具。
- 以當前使用者身份建立虛擬環境 `.venv` 並安裝專案完整依賴 (`all, web`)。
- 安裝 Playwright Chromium 及 Linux 圖形相依函式庫。
- 動態生成以目前使用者身分執行的 Systemd 服務檔。

### 步驟 2：初次拉取雲端節點
切換至虛擬環境並拉取加密設定：
```bash
cd ~/drive-unix
source .venv/bin/activate

# 設定連線端點 (與本地電腦一致)
drive-unix upstash config

# 拉取並解密節點與憑證
drive-unix upstash pull -p 'YourSecretPassphrase'
```

### 步驟 3：測試單次換發
執行單次巡檢，確認各帳號與雲端連線狀態：
```bash
drive-unix upstash renew-tokens --leeway 60
```

### 步驟 4：啟動常駐守護服務 (Systemd)
```bash
# 啟用並立即啟動憑證換發守護行程 (每 30 分鐘巡檢一次)
sudo systemctl enable --now drive-unix-renew.service

# 查看即時日誌
sudo journalctl -u drive-unix-renew.service -f
```

*(可選)* 若需要使用網頁圖形化介面 (Web UI)：
```bash
sudo systemctl enable --now drive-unix-web.service
```

---

## 4. 佈署方式 B：Docker / Docker Compose

若您的 VPS 使用 Docker 或容器化管理平臺：

### 步驟 1：配置環境變數
在專案根目錄建立 `.env` 檔案：
```bash
UPSTASH_REDIS_REST_URL=https://your-db.upstash.io
UPSTASH_REDIS_REST_TOKEN=your_upstash_rest_token
UPSTASH_SYNC_PASSPHRASE=YourSecretPassphrase
```

### 步驟 2：啟動容器
```bash
docker compose up -d
```
- `token-center` 容器將以背景常駐模式運作，每 30 分鐘自動巡檢與換發憑證。
- `web-ui` 容器在 `http://<VPS_IP>:8000` 提供網頁管理介面。

### 步驟 3：在容器內初次拉取節點 (若尚未自動拉取)
```bash
docker compose exec token-center drive-unix upstash pull -p 'YourSecretPassphrase'
```

---

## 5. 運維與檢查指令速查

| 操作 | 指令 |
| :--- | :--- |
| **手動觸發即時巡檢換發** | `drive-unix upstash renew-tokens --leeway 60` |
| **針對特定節點單獨換發** | `drive-unix upstash renew-tokens -r my-sharepoint` |
| **查看雲端備份狀態** | `drive-unix upstash status` |
| **測試 Upstash 連線延遲** | `drive-unix upstash test` |
| **查看 Systemd 運行日誌** | `journalctl -u drive-unix-renew.service -n 50 -f` |
| **查看 Docker 運行日誌** | `docker compose logs -f token-center` |

---

## 6. 本地客戶端使用

當 VPS 憑證換發中心在雲端 24/7 運作後，本地客戶端：
1. 確保已開啟自動同步憑證：
   `drive-unix upstash config --auto-sync-tokens`
2. 進行日常傳輸 (`drive-unix sync`, `bisync`, `ls`, `upload`, `download`) 時，程式會在本地憑證過期時自動由 Upstash 拾取 VPS 換發好的最新密文並解密，完全無痛且無須再次人工登入。

---

## 7. SharePoint 登入失敗自動截圖排查

當在無 GUI 的 Headless VPS 上進行 SharePoint / OneDrive Business 登入換發時，若遇到密碼錯誤、微軟 2FA / 驗證碼、或條件式存取 (Conditional Access) 阻擋：

1. **自動擷取畫面與錯誤文字**：
   系統會在例外拋出前自動截取 Headless 瀏覽器當前的完整畫面 (`.png`)，並自動擷取頁面上的微軟錯誤警告訊息、頁面標題與當前網址。
2. **截圖存放目錄**：
   預設存放於：`~/.config/drive-unix/debug/sharepoint_<reason>_<timestamp>.png`
   （亦可透過環境變數 `SHAREPOINT_SCREENSHOT_DIR` 自訂存放路徑）。
3. **終端機錯誤提示包含截圖路徑**：
   ```text
   Timed out while logging into SharePoint.
   頁面提示訊息: '密碼不正確。請確定使用貴組織帳戶的密碼。'
   (頁面標題: '登入您的帳戶', URL: https://login.microsoftonline.com/...)
   📸 失敗畫面截圖已儲存至: /home/g6172506/.config/drive-unix/debug/sharepoint_timeout_20261022_001500.png
   ```
4. **線上檢視方式**：
   - **透過 Web API 直接預覽**：若已啟動 Web 服務，可直接開啟 `http://<VPS_IP>:8000/api/settings/debug/screenshots` 檢視截圖列表，或以 `http://<VPS_IP>:8000/api/settings/debug/screenshots/<filename>` 在瀏覽器檢視圖片。
   - **透過 SCP 下載至本機**：
     ```bash
     scp user@vps_ip:~/.config/drive-unix/debug/*.png .
     ```

---

## 8. Microsoft Authenticator 數字比對 (Number Matching) 自動探測

當登入觸發微軟雙重驗證（MFA），並在畫面上顯示需要於手機輸入的配對數字時：

1. **自動即時解析數字**：
   系統探測到 Authenticator 挑戰頁面時，會自動從頁面 DOM（`#richContext_display`）解析出配對數字（例如 `42`）。
2. **自動延長等候時間**：
   等候時間自動動態延長至 **90 秒**，給予使用者充裕時間開啟手機輸入。
3. **終端與日誌提示**：
   在終端機（或 `journalctl -u drive-unix-renew -f`）顯示醒目標誌：
   ```text
   =================================================================
   🔔【Microsoft 雙重驗證 (MFA) - 請在手機輸入數字】
   微軟要求數字比對！請開啟手機上的 Microsoft Authenticator 並輸入：

                     👉 【 42 】 👈

   系統正在背景等候您的手機核准 (最長等候 90 秒)...
   =================================================================
   ```
4. **即時 API 狀態查詢**：
   亦可透過 Web API 即時查詢當前是否有進行中的 MFA 數字挑戰：
   `GET /api/settings/debug/mfa-status`
   回應：`{"active": true, "number": "42", "message": "請在手機輸入數字：42"}`
5. **手機核准後全自動推進**：
   當在手機上點擊確認後，Headless 瀏覽器會自動偵測頁面跳轉與「保持登入」提示，自動完成憑證換發、加密存入 Upstash，並清除暫存截圖。

