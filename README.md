# Planet X and SPHEREx

NASA Space Apps 專案：以天球座標探索 SPHEREx 紅外線影像。

- `research/`：Phase 1 NASA 查詢、FITS 處理與已保存的真實輸出。
- `backend/`：Phase 2 FastAPI；API、限制與啟動方式見 [backend/README.md](backend/README.md)。
- `frontend/`：Phase 3 純 HTML、CSS、JavaScript 單張影像預覽，無建置及前端套件依賴。

## 本機使用

在專案根目錄開啟終端機，依後端 README 啟動 FastAPI（預設 `http://127.0.0.1:8000`），另一個終端機執行：

```powershell
node frontend/tools/serve.mjs
```

開啟 **http://127.0.0.1:5500/planet-x/**。選「本機 localhost」，API 基底網址填 `http://127.0.0.1:8000`，再搜尋。也支援根路徑 http://127.0.0.1:5500/。

預設座標為已驗證範例 RA `127.69444`、Dec `-39.17760`、半徑 `0.01` 度。可切換黑底／白底 PNG，並以 1–32 倍原始像素縮放。預設 12 倍，29×29 影像顯示為 348×348。觀測時間採 API 提供的 UTC／MJD，缺少欄位顯示「未提供」。

搜尋半徑與 Cutout 尺寸不同：搜尋半徑最大 `5/60` 度，Cutout 固定邊長 3 arcmin。放大不會增加科學資訊，前端不補點、不重新處理 FITS、不直接查 NASA。本版沒有時間序列動畫。

### 僅用既有資料回放

若後端暫時無法啟動，可以測試前端顯示流程：

```powershell
node frontend/tools/serve.mjs --fixture
```

頁面 API 基底網址改成 `http://127.0.0.1:8001`。此選項啟動獨立的**測試回放 API**，直接讀取 `research/outputs/metadata.json` 與兩張既有 PNG，不會呼叫 NASA，不修改或取代 FastAPI。不同座標仍回放相同影像，不能用於科學查詢，也不能視為真實後端整合驗證。正式本機測試請改回 8000。伺服器均只監聽 `127.0.0.1`；按 Ctrl+C 停止。

## API 設定與錯誤

前端只 POST `/api/preview`，傳送數值 `{ra, dec, radius_deg}`，並載入回傳的 `/api/images/{key}.png` 或反相版本。PNG 路徑會套用使用者選定的 API origin，避免反向代理回傳內部 HTTP 主機。切換顯示模式不重新 POST。

本機／Render 各自的網址保存在瀏覽器 `localStorage`，儲存功能被封鎖時仍可使用。公開前端預設 Render、拒絕 localhost 後端；Render 與 HTTPS 頁面要求 HTTPS API。網址只接受 origin，不接受路徑、帳密或參數。

介面區分查詢中、查無影像、API 錯誤、網路／CORS 錯誤與圖片載入失敗。查詢期間禁止重複提交。180 秒等待期限只中止前端等待，後端可能仍在執行；不自動重試。`busy` 會顯示 `Retry-After`，請依提示稍後手動重試。PNG 載入期限為 30 秒。圖片可能因快取到期、容量淘汰或後端重啟失效，需重新搜尋。

## GitHub Pages 部署準備（尚未部署）

`frontend/index.html`、`styles.css`、`config.js`、`app.js` 即為完整靜態網站；CSS／JS／首頁連結均使用相對路徑，支援 `/REPOSITORY/` 子路徑，不需要 React 或建置程序。

日後部署時，把 `frontend/` **內容**作為 Pages artifact 根目錄；`tools/`、`tests/` 及測試報告不需上傳。沒有新增自動部署 workflow，避免推送時意外部署。

1. 先有可用的 Render FastAPI HTTPS 服務，沿用單一 worker。
2. 可在 `frontend/config.js` 的 `renderApiBase` 填入真實 Render origin，例如 `https://YOUR-SERVICE.onrender.com`；也可保持空白，由訪客自行設定。不要填入密鑰。
3. 在 Render **環境變數**設定既有 `CORS_ORIGINS`，例如 `http://127.0.0.1:5500,http://localhost:5500,https://YOUR_ACCOUNT.github.io`。GitHub Pages origin 不含 repository 路徑或尾端斜線。此步只需設定環境，不需修改後端程式。
4. 先在本機前端選 Render 做成功／失敗串接驗證，再另行部署 Pages。

GitHub Pages 只提供前端靜態檔案，不能執行 FastAPI，也不會把網站的 localhost 連線轉送至專案開發者電腦。每位使用者需連線到公開可用的 Render API。

## 前端驗證

需要 Node.js 18+，不需 `npm install`：

```powershell
node --test frontend/tests/app.test.mjs
node --check frontend/app.js
node --check frontend/tools/serve.mjs
```

測試使用 Node VM 的最小 DOM／fetch 替身，驗證請求、輸入邊界、狀態、縮放、反相、安全文字呈現及 API 環境切換；不等同真實瀏覽器測試。已完成項目與待驗證限制見 [frontend/test-report.md](frontend/test-report.md)。
