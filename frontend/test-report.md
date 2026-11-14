# Phase 3 本機測試紀錄

日期：2026-11-14。未部署、未修改 `backend/` 或 `research/`。

## 已通過

- `node --test frontend/tests/app.test.mjs`：23 項通過，0 失敗。
- `node --check frontend/app.js`、`node --check frontend/tools/serve.mjs`：語法檢查通過。
- 本機 HTTP：`/`、`/planet-x/` 與子路徑下 `styles.css`、`config.js`、`app.js` 均回傳 200。
- 獨立 fixture API：POST 使用 Phase 1 真實已存 metadata，兩個 PNG URL 均可下載，PNG IHDR 尺寸皆為 29×29；OPTIONS 204 與指定 CORS origin 正常。

自動測試涵蓋：數值 POST、RA／Dec／半徑邊界、公開網站禁用 localhost、Render HTTPS、拒絕無效 URL、代理內部影像 URL 重設 origin、觀測欄位、metadata 安全文字呈現、12 倍與 32 倍縮放、反相切換、no_images、busy、upstream_timeout、cutout_failed、invalid_input、internal_error、網路／CORS 失敗、無效 JSON、PNG 失敗、localStorage 不可用及 180 秒中止後恢復表單。

## 未完成的環境驗證

- 真實 FastAPI／NASA 串接：本次環境未發現 8000 listener；`research/.venv/Scripts/python.exe` 指向已不存在的 Python 3.11 執行檔。`py -0p` 僅列出 Python 3.9。未變更使用者 Python 安裝或後端環境。
- 真實瀏覽器視覺、互動、窄螢幕與 CORS enforcement：瀏覽器自動化 host unavailable；原生 Chrome 介面存取核准等待逾時。未取得瀏覽器畫面，因此無法宣稱視覺驗收通過。
- Render 串接：尚未提供真實 Render 網址。

回放 API 與 DOM 替身測試並非真實 NASA、FastAPI 或瀏覽器端對端測試。後端環境修復後，請依根目錄 README 啟動前後端，實際搜尋範例座標，確認 PNG、UTC、detector、反相與縮放，再檢查無資料／斷線／快取到期與手機尺寸。Render URL 可用後，再從本機前端選 Render 驗證 HTTPS 與 CORS，通過後才部署。
