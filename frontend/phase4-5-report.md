# Phase 4.5 最小多時期前端與驗收

日期：2026-11-14。只修改前端與文件，保留工作目錄既有 Phase 4.4 後端變更；沒有更動後端 API 契約、查詢 NASA、下載 FITS、Commit、Push 或部署。

後續小幅 UI／UX 調整：主清單只保留當下可選候選與可取消勾選的已選列。未知 detector／obs_id、異 detector、同曝光替代版本及達三張上限後的未選列均隱藏。同曝光預設保留 API 首筆合法產品，已選代表優先保留，不代表科學版本優劣。新增 Select first 2／3，依可見清單第一筆的 detector 重選前 2／3 個曝光；不足時停用，且不自動載入。取消勾選可恢復其他合法候選。此次全套前端離線測試更新為 **50 項通過、0 失敗**，含不可選列隱藏、快速選取、精確 payload 與播放器／模式切換零額外 fetch；語法與 diff 檢查通過，未新增瀏覽器或真實 NASA 驗證。

## 已完成

- Preview / Multi-epoch 各自保留畫面與結果，共用座標、API origin 與 D1～D6 選擇。Preview 的 Histogram、Brightness、Linear／Asinh、反相與縮放保留。
- Multi-epoch 呼叫 `POST /api/epochs/search`，將 Preview 的單值 detector 轉為 `detectors: [n]`；Auto 省略此篩選。顯示 SIA 時間、來源、產品狀態、校準狀態／警告，以及來源 partial／error／truncated。更多時期以明確按鈕沿用原查詢與 cursor，沒有自動掃頁。
- 選取同一已知 detector、不同非空 obs_id 的 2～3 個產品；相同曝光只顯示一筆代表產品。未知曝光／detector 與其他不可選候選不顯示於主清單。未經 FITS 驗證的 metadata 不宣稱同波長。
- 僅 `Load frames` 會 POST `search_id` 與按 SIA 時間排序的 product_ids。檢查回應的產品與原始 index，禁止以其他曝光補位。PNG 僅接受指定 API origin 與該序列／slot 路徑；不抓 NPZ、不做前端 WCS 重投影、旋轉或亮度重新正規化。
- 明確載入時最多抓取三張 PNG，以 blob URL／已解碼圖片節點保留於記憶體。播放器按實際回傳 UTC 排序，保留 backend slot index；缺時間排最後。上一張／下一張循環，手動操作會暫停；播放速度支援 0.5／1／2 fps，拖動、播放、縮放與切回模式不增加 fetch。重新查詢／載入會釋放舊 blob URL。
- 每個 slot 顯示 UTC、time_source、detector、目標波長／bandwidth、來源 collection、產品／曝光 ID、狀態與 alignment。FITS 時間優先由後端提供；失敗 slot 保留後端 SIA fallback 時間與錯誤。完整來源 URL、校準與配對診斷留在完整序列 metadata。
- `comparable_visualization` 只描述後端共用正規化視覺化；仍不是測光序列。`observation_browse` 明示逐張 stretch，不能比較亮度或推論光變。時間軸按影格等距排列，明示觀測本身非等時間間隔。
- 部分／全部失敗不移除 slot；PNG HTTP 失敗／解碼失敗也留在原位置。`search_expired`、`invalid_cursor`、`frame_not_found` 明示重新查詢；過期搜尋停用 Load frames。沒有自動重試，busy 保留 Retry-After。已成功載入的 blob 可在伺服器快取到期後繼續播放。

## 自動驗證

從專案根目錄執行，不需 npm install：

```powershell
node --test frontend/tests/*.test.mjs
node --check frontend/app.js
node --check frontend/epochs.js
node --check frontend/tools/serve.mjs
node --check frontend/tools/epochs-fixture.mjs
git diff --check
```

結果：**45 項通過、0 失敗**（既有 Preview 28、Brightness 2、新增 Multi-epoch 15）。涵蓋 API payload、手動載入、同 detector／不同曝光／三張上限、SIA 候選排序、實際 FITS UTC 排序、播放／暫停／速度／模式切換、拖動／縮放零額外 fetch、blob 釋放、部分與全部失敗 slot、兩種序列語意、cursor、過期搜尋、PNG 快取失效、busy／Retry-After、無效 JSON、網路／CORS、逾時及座標驗證。測試以 Node VM 與 DOM／網路替身執行，不等於瀏覽器端對端測試。

另以真實本機 HTTP 檢查靜態 `epochs.js` 為 200、合成搜尋／三張 manifest 保留 slot 0／1／2（ready-to-browse／failed／ready-to-browse），PNG 回應為 image/png、合法 PNG signature、29×29。合成 PNG 不驗證科學 WCS 對齊。

## 本機離線逐步驗收（建議先做）

1. 在專案根目錄的 PowerShell 啟動專用合成服務：

   ```powershell
   node frontend/tools/serve.mjs --epochs-fixture --port=5501 --fixture-port=8002
   ```

2. 打開 `http://127.0.0.1:5501/planet-x/`，必要時強制重新整理。API 環境選本機，基底網址填 `http://127.0.0.1:8002`。合成服務僅監聽 loopback，不連 NASA，不依賴 `research/outputs`。畫面候選來源會清楚顯示 `SYNTHETIC_UI_FIXTURE`，不可當成真實觀測。
3. 選 Multi-epoch，使用預設 RA `127.69444`、Dec `-39.17760`、radius `0.01`、Detector Auto，按「查詢觀測時期」。應只查 metadata，沒有自動產生影格；表格按 SIA 日期排列。
4. 確認同曝光的 product-5 不在主清單。選 D1 的 exposure-0，確認 D2 product-4 已隱藏；再選 product-1、product-2，確認未選的第四個產品隱藏，取消一個勾選後恢復。只選一張時 Load frames 停用。也可按 Select first 2／3 重選可見清單中同 detector 的前 2／3 個曝光，確認不會立即發出影格請求。
5. 開啟瀏覽器開發工具 Network，按 Load frames。預設 `failed` 情境保留中間 slot 1 故意失敗，其餘兩張為合成 PNG；確認日期、detector、λ／bandwidth 與錯誤原因顯示。不要將合成移動亮點解讀為科學結果。
6. 播放、暫停、改速度、拖動滑桿、上一張／下一張與縮放。應訪問所有 slot，失敗位置顯示原因，不能跳過；Network 的搜尋、影格 manifest、PNG 請求數不得因播放器操作增加。PNG 的 blob URL 不需要向 NASA 或影格 API 重取。
7. 確認 `observation_browse` 顯示不可比較亮度／不可解讀為光變，以及非等時間間隔提醒。切回 Preview，再切回 Multi-epoch，應保留結果且播放已暫停。
8. 以 Ctrl+C 停止此合成服務，重開加上以下其中一個旗標，再重新查詢／載入：`--scenario=expired` 應出現 search_expired 與重新查詢提示；`--scenario=cache-miss` 應保留所有 slot 並提示 PNG 快取失效；`--scenario=all-failed` 保留全部失敗且播放停用；`--scenario=comparable` 驗證共用亮度範圍與非測光序列文案。`--scenario=browse` 為全張可載入的 observation_browse。

5501／8002 如已占用，可改 `--port`／`--fixture-port`，同步修改瀏覽器網址及 API 基底。預設埠仍為 5500／8001。新增合成服務不模擬全部 FastAPI 驗證與快取政策；錯誤／分頁的更多分支由 VM 測試覆蓋。

## 真實後端的少量人工驗收

修復／準備 Python 3.11 與 requirements 後，依根 README 啟動：

```powershell
.\research\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

另開 Terminal 執行 `node frontend/tools/serve.mjs`，瀏覽 `http://127.0.0.1:5500/planet-x/`，API 設 `http://127.0.0.1:8000`。先驗收 Preview 的既有查詢、Histogram、Brightness、Linear／Asinh、反相與縮放；再以相同既有研究座標、D1 做一次 Multi-epoch 查詢。檢查日期／來源後只選 2～3 張不同曝光，明確按一次 Load frames。這步會下載少量真實 FITS，不能保證任意同 detector 產品會判定 comparable。後續播放／拖動不應新增 API 請求。遇到失敗保留原 slot，按提示重新查詢，避免連續批次重試。

## 未驗證的限制

- 本輪沒有完成真實瀏覽器畫面、點選、窄螢幕、鍵盤／輔助技術與實際 CORS enforcement 驗收：瀏覽器工具回報 `The browser access host is unavailable`。HTTP／VM 通過不能替代以上驗收。
- 沒有真實 FastAPI／NASA 前端端對端驗證，也沒有新增或重跑真實 FITS 科學驗證。本輪嘗試跑 backend test_epochs／test_epoch_frames，但現有 venv 指向不存在的 Python 3.11，啟動即失敗；`py --list` 只有 3.9，未修改使用者安裝。Phase 4.4 報告中的既有測試結果不是本輪重跑結果。
- 未驗證 Render／HTTPS／公開部署、瀏覽器記憶體實測、長時間背景分頁的 timer 節流或 D2～D6 真實多時期資料。瀏覽器可能降低背景播放頻率；不承諾精準實時間隔。
- 合成來源僅用來測 UI；其固定測試日期、波長與 PNG 並不代表真實 NASA 觀測，也不證明幾何／光譜／校準合格。comparable 合成情境只測文案分支。
- SIA 候選時間以 MJD 轉成 UTC 顯示，尚非 FITS DATE-OBS；載入後使用後端 observation_utc 與 time_source。未知時間不猜測，排最後。影格間隔與真實觀測時間無線性比例。
- WCS、校準、波長、背景／PSF／variance 等科學限制延續 Phase 4.4；不能用此播放器推論光變、測光或移動天體。
- 英文介面全面整理、WCS 軸、Surface Brightness Color Bar、視覺美化及 Gaia 均未納入。
