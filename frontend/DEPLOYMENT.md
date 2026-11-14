# GitHub Pages 前端發布（Phase 5.2）

預期網站：`https://zo4j433.github.io/planet-x-spherex/`。
API：`https://planet-x-spherex.onrender.com`。此輪僅準備設定與本機驗證，未 Commit、Push 或部署。

## 維護者設定

1. 在 repository **Settings → Pages → Build and deployment → Source** 選 **GitHub Actions**。
2. 若 repository／組織限制 Actions，允許 workflow 使用的官方 `actions/checkout`、`setup-node`、`configure-pages`、`upload-pages-artifact`、`deploy-pages`。
3. 在 **Settings → Environments → github-pages → Deployment branches and tags** 限制只允許 `main`；可依需要另設審核者。Pages 顯示 HTTPS 選項時確認 **Enforce HTTPS**。
4. Render Dashboard 的 `CORS_ORIGINS` 應包含 `https://zo4j433.github.io`。它是 origin，不能包含 `/planet-x-spherex/` 或尾端 `/`。多來源以逗號分隔；若需要本機連公開 API，再保留本機來源。
5. 自行檢閱、Commit 並 Push 到 `main` 後才會觸發首次發布。日後在 **Actions → Deploy frontend to GitHub Pages → Run workflow → main** 可手動重部署；其他分支會跳過。無需 PAT 或自訂 secret。

workflow 將建置與部署分開：建置只有 `contents: read`，checkout 不保留憑證；部署才授予 `pages: write` 與 `id-token: write`。同時僅允許一個 Pages 發布流程，不取消正在進行的部署。官方設定說明：[Pages 自訂 workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。

## 發布內容與部署前驗證

使用 Node.js 22（CI）；本機測試本輪使用 Node.js 24.18.0。不需安裝 npm 套件。

```powershell
node frontend/tools/build-pages.mjs
node frontend/tools/test.mjs
node frontend/tools/serve.mjs
```

開啟 `http://127.0.0.1:5500/planet-x-spherex/`，舊 `/planet-x/` 與根路徑亦保留。
打包器只複製以下八個檔案到被 Git 忽略的 `frontend/dist/`：

- `index.html`、`styles.css`、`config.js`、`app.js`
- `brightness.js`、`wcs-axes.js`、`color-bar.js`、`epochs.js`

artifact 根目錄就是網站根目錄，不另包一層 `frontend/`。若 dist 出現白名單外項目，建置直接失敗，請檢查並清理該目錄再執行；不會遞迴複製原始目錄。新增網站資源時須同步更新白名單及 artifact 驗證。

測試會重建 artifact、比對內容、檢查 JS 語法，並以本機 HTTP 驗證根路徑與真實 repository 子路徑的相對資源、MIME 類型、尾斜線導向，以及測試／fixture／後端檔案不可存取。所有既有前端測試一併執行，無 NASA 請求或 FITS 下載。

`config.js` 僅含公開 API origin。首次開啟公開網站預設 Render，本機預設 localhost；使用者已儲存的連線設定仍保留。若有舊設定，請在 API connection settings 選 Render 並填入正式 HTTPS origin，或清除該網站的 `spherex-api-v1` localStorage。HTTPS 頁面拒絕 HTTP API；公開頁面拒絕 loopback。Preview 與 Multi-epoch 的圖片路徑均套用選定的 API origin。

## 驗收

1. Actions 的 build 與 deploy 均成功，deployment URL 為上述 Pages URL；直接開啟與重新整理 `/planet-x-spherex/` 均正常。
2. 瀏覽器 Network 確認八個靜態檔案均為 200，CSS／JS MIME 正確；Console 無資源 404、Mixed Content 或 CORS 錯誤。公開頁面預設 API 為正式 Render HTTPS。
3. 不查詢 NASA 的驗收：切換 Preview／Multi-epoch、Detector、API 設定；用下列 OPTIONS 確認 CORS（不提交 POST）。

```powershell
$headers = @{
  Origin = 'https://zo4j433.github.io'
  'Access-Control-Request-Method' = 'POST'
  'Access-Control-Request-Headers' = 'content-type'
}
$response = Invoke-WebRequest -UseBasicParsing -Method Options `
  -Uri 'https://planet-x-spherex.onrender.com/api/preview' -Headers $headers
$response.StatusCode
$response.Headers['Access-Control-Allow-Origin']
```

應為 200，允許來源應為 `https://zo4j433.github.io`。2026-11-15 本輪實際結果符合，允許方法為 `GET, POST, OPTIONS`，允許 `Content-Type`；Dashboard 中環境變數實值未直接讀取。

4. 離線 Multi-epoch 驗收可用 `node frontend/tools/serve.mjs --epochs-fixture --port=5501 --fixture-port=8002`，在本機頁面將 Local API 設為 `http://127.0.0.1:8002`。此為合成資料，不是正式科學結果；此模式的 Preview 仍依賴既有 `research/outputs/`，乾淨 checkout 請以自動測試驗證 Preview／Histogram／Brightness。若本機已安裝後端科學套件，可改用 `--wcs-fixture`，以離線合成資料驗證 Preview、Detector 選擇、WCS 軸、Color Bar 與播放器（必要時用 `--python=` 指定虛擬環境 Python）；不會下載 FITS。
5. 真實 Preview 搜尋及 Multi-epoch 的 Search／Load frames 會觸發上游查詢或下載，**不屬於本輪驗收範圍**；未以公開站進行端到端科學查詢。待另行授權後再執行。

本輪自動測試 80 項全數通過（含既有 UI／播放器回歸測試）。測試採最小 DOM／fetch 替身與本機 HTTP，不等同部署後真實瀏覽器整合驗證。
