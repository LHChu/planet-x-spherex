# Planet X and SPHEREx

Phase 4.5 已新增獨立 Multi-epoch 模式與離線播放器；保留原 Preview。實作範圍、離線／真實後端逐步驗收與未驗證限制見 [Phase 4.5 前端報告](frontend/phase4-5-report.md)。離線驗證：`node --test frontend/tests/*.test.mjs`；獨立合成服務：`node frontend/tools/serve.mjs --epochs-fixture --port=5501 --fixture-port=8002`（API 設為 `http://127.0.0.1:8002`，不連 NASA）。

NASA Space Apps 專案：以天球座標探索 SPHEREx 紅外線影像。

- `research/`：Phase 1 NASA 查詢、FITS 處理與已保存的真實輸出。
- `backend/`：FastAPI 單張預覽與 Phase 4.3 多時期 metadata 查詢；API、限制與啟動方式見 [backend/README.md](backend/README.md)。
- `frontend/`：Phase 3 純 HTML、CSS、JavaScript 單張影像預覽，無建置及前端套件依賴。

## Requirements

- **Windows PowerShell**：以下指令以 Windows 為準。
- **Python 3.11**：安裝時請一併安裝 Python Launcher，讓 `py -3.11` 可以選取正確版本。
- **Node.js 18+**：用於啟動前端靜態伺服器與執行前端測試。
- **Git**：用於 Clone Repository。
- **瀏覽器與必要網路連線**：Clone 需要連線 GitHub；安裝 Python 套件需要連線 PyPI 與套件下載站；實際查詢與下載影像需要後端能以 HTTPS 連線 NASA／IRSA（`irsa.ipac.caltech.edu`）。使用 Render 時，瀏覽器也需要能連線至該 Render HTTPS 服務。

安裝工具後，重新開啟 PowerShell。可用以下指令確認版本（Python 應為 3.11，Node.js 應為 18 或以上）：

```powershell
py -3.11 --version
node --version
git --version
```

## Quick Start

除了第一步 Clone 與進入資料夾，**本文件及後端文件的所有指令都從專案根目錄執行**。根目錄是同時含有 `README.md`、`research/`、`backend/`、`frontend/` 的 `planet-x-spherex` 資料夾，不要求放在特定磁碟或絕對路徑。

### 1. Clone Repository

在想存放專案的資料夾開啟 PowerShell：

```powershell
git clone https://github.com/zo4j433/planet-x-spherex.git
Set-Location .\planet-x-spherex
```

接下來請留在此專案根目錄，不要切換到 `backend/` 或 `frontend/`。

### 2. 建立 Python 虛擬環境並安裝套件

```powershell
py -3.11 -m venv research/.venv
.\research\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

`backend/requirements.txt` 已透過 `-r ../research/requirements.txt` 引用研究階段的依賴，pip 會依 requirements 檔案所在位置解析此相對路徑，因此只需執行上面一次安裝指令，不用另裝 `research/requirements.txt`。

以下所有 Python 指令直接使用虛擬環境內的 `python.exe`，**不需要啟用虛擬環境，也不需要執行 `Activate.ps1` 或更改 PowerShell 執行原則**。每位同學應自行建立虛擬環境，不能複製別人的 `.venv`。

### 3. 啟動 FastAPI（Terminal 1，port 8000）

```powershell
.\research\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```


看到 Uvicorn 顯示 `http://127.0.0.1:8000` 後，保持此 Terminal 執行中。

可在瀏覽器開啟健康檢查頁面：

[http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

正常情況下應看到 `{"status":"ok"}`。

互動式 API 文件：

[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

注意：健康檢查不會連線 NASA。


### 4. 啟動前端（Terminal 2，port 5500）

**另開一個 PowerShell Terminal，工作目錄也設為剛才 Clone 的專案根目錄**。例如使用 VS Code 開啟整個 `planet-x-spherex` 資料夾，再新增 Terminal；請確認新 Terminal 位於根目錄。

```powershell
node frontend/tools/serve.mjs
```

前端不需要 `npm install`，直接使用 Node.js 內建模組。保持此 Terminal 執行中；前後端需同時運作。


### 5. 開啟頁面並測試影像查詢

在瀏覽器開啟：

**[http://127.0.0.1:5500/planet-x/](http://127.0.0.1:5500/planet-x/)**

也支援根路徑：

[http://127.0.0.1:5500/](http://127.0.0.1:5500/)


在頁面的「API 連線設定」選「本機 localhost」，API 基底網址填 `http://127.0.0.1:8000`，使用以下已驗證範例後按「搜尋 NASA 影像」：

| 欄位 | 測試值 | 單位 |
|---|---|---|
| 赤經 RA | `127.69444` | 度 |
| 赤緯 Dec | `-39.17760` | 度 |
| 搜尋半徑 `radius_deg` | `0.01` | 度 |

查詢可能需要數分鐘。成功時可看到 NASA PNG、觀測時間與 detector，並切換黑底白光／白底黑光、調整縮放。範例曾成功取得影像，但仍需 NASA 上游服務正常。完成使用後，在兩個 Terminal 分別按 `Ctrl+C` 停止伺服器。

### 啟動問題排查

- `py -3.11` 找不到 Python：先安裝 Python 3.11 與 Python Launcher，重新開啟 Terminal 後再建立環境。
- `.venv` 指向不存在的 Python：該環境可能來自另一台電腦或舊安裝，請先移走舊的 `research/.venv`，再依第二步重新建立與安裝。
- `node` 或 `git` 無法辨識：確認已安裝並加入 PATH，安裝後重新開啟 Terminal。
- 找不到 `backend.app.main` 或前端腳本：確認目前位於專案根目錄。
- port 8000／5500 已被占用：停止之前啟動的同一個伺服器，再依原指令重啟。
- 頁面開啟但 API 無法連線：確認 Terminal 1 仍在執行、`/health` 正常，以及頁面 API 網址為 `http://127.0.0.1:8000`。本機預設 CORS 已允許 `http://127.0.0.1:5500`，不需要修改後端。
- `/health` 正常但查詢失敗：健康檢查不代表 NASA 可連線，請依頁面錯誤與後端日誌確認網路或上游服務狀態。API 錯誤代碼見 [後端說明](backend/README.md#錯誤)。

## 本機功能與資料回放

預設座標為已驗證範例 RA `127.69444`、Dec `-39.17760`、半徑 `0.01` 度。可切換黑底／白底 PNG，並以 1–32 倍原始像素縮放。預設 12 倍，29×29 影像顯示為 348×348。觀測時間採 API 提供的 UTC／MJD，缺少欄位顯示「未提供」。

搜尋半徑與 Cutout 尺寸不同：搜尋半徑最大 `5/60` 度，Cutout 固定邊長 3 arcmin。放大不會增加科學資訊，前端不補點、不重新處理 FITS、不直接查 NASA。本版沒有時間序列動畫。

### 僅用既有資料回放

若後端暫時無法啟動，且本機已有 Phase 1 產生的 `research/outputs/metadata.json`、`black-background.png`、`white-background.png`，可以測試前端顯示流程。**`research/outputs/` 被 Git 忽略，剛 Clone 不會有這些檔案，首次啟動請使用上面的正式後端流程。** 先停止原本的前端伺服器，再從根目錄執行：

```powershell
node frontend/tools/serve.mjs --fixture
```

頁面 API 基底網址改成 `http://127.0.0.1:8001`。此選項啟動獨立的**測試回放 API**，直接讀取 `research/outputs/metadata.json` 與兩張既有 PNG，不會呼叫 NASA，不修改或取代 FastAPI。不同座標仍回放相同影像，不能用於科學查詢，也不能視為真實後端整合驗證。正式本機測試請改回 8000。伺服器均只監聽 `127.0.0.1`；按 Ctrl+C 停止。

## API 設定與錯誤

前端只 POST `/api/preview`，傳送數值 `{ra, dec, radius_deg}`，並載入回傳的 `/api/images/{key}.png` 或反相版本。PNG 路徑會套用使用者選定的 API origin，避免反向代理回傳內部 HTTP 主機。切換顯示模式不重新 POST。

本機／Render 各自的網址保存在瀏覽器 `localStorage`，儲存功能被封鎖時仍可使用。公開前端預設 Render、拒絕 localhost 後端；Render 與 HTTPS 頁面要求 HTTPS API。網址只接受 origin，不接受路徑、帳密或參數。

介面區分查詢中、查無影像、API 錯誤、網路／CORS 錯誤與圖片載入失敗。查詢期間禁止重複提交。180 秒等待期限只中止前端等待，後端可能仍在執行；不自動重試。`busy` 會顯示 `Retry-After`，請依提示稍後手動重試。PNG 載入期限為 30 秒。圖片可能因快取到期、容量淘汰或後端重啟失效，需重新搜尋。

## GitHub Pages 部署準備（Phase 5.2，尚未部署）

操作與驗收方式見 [frontend/DEPLOYMENT.md](frontend/DEPLOYMENT.md)。`.github/workflows/deploy-pages.yml` 在 `main` 更新或手動執行時，先離線驗證，再發布 `frontend/dist/`；本輪未執行部署。

`node frontend/tools/build-pages.mjs` 僅打包首頁、CSS 與六個 JS 檔案，排除後端、研究資料、測試、fixture 及工具。資源採相對路徑，支援 `/planet-x-spherex/`。

1. Render API 已公開於 `https://planet-x-spherex.onrender.com`，正式前端預設此 HTTPS origin；本機首次開啟仍預設 `http://127.0.0.1:8000`。
2. Render 的 `CORS_ORIGINS` 必須包含 `https://zo4j433.github.io`，不含 repository 路徑或尾端斜線；本輪實際 OPTIONS 預檢已通過。
3. GitHub repository 的 **Settings → Pages → Build and deployment → Source** 選 **GitHub Actions**，並限制 `github-pages` environment 僅允許 `main`。
4. 完成檢閱後由維護者自行 Commit／Push；推送到 `main` 會發布。手動重部署請在 Actions 選擇此 workflow，使用 `main` 執行。

GitHub Pages 只提供前端靜態檔案，不能執行 FastAPI，也不會把網站的 localhost 連線轉送至專案開發者電腦。每位使用者需連線到公開可用的 Render API。

## Render 後端部署準備（Phase 5.1）

部署設定、環境變數、免費方案限制與操作步驟見 [backend/DEPLOYMENT.md](backend/DEPLOYMENT.md)；本機離線驗證結果見 [backend/phase5-1-report.md](backend/phase5-1-report.md)。Render API 已公開部署，`/docs` 已由使用者在瀏覽器驗證。

## 前端驗證

需要 Node.js 18+，不需 `npm install`：

```powershell
node frontend/tools/test.mjs
node --check frontend/app.js
node --check frontend/tools/serve.mjs
```

測試使用 Node VM 的最小 DOM／fetch 替身，驗證請求、輸入邊界、狀態、縮放、反相、安全文字呈現及 API 環境切換；不等同真實瀏覽器測試。已完成項目與待驗證限制見 [frontend/test-report.md](frontend/test-report.md)。
