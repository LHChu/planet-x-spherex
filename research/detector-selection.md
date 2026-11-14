# Preview detector 選擇與本機驗收

## 行為與限制

`POST /api/preview` 新增可選的 `detector`：JSON 整數 1～6；省略或 `null` 是 Auto。前端原座標表單新增一個 Auto／D1～D6 下拉選單，沒有重設版面。Auto 保持原查詢、排序與候選重試行為。

指定 detector 時，後端從 SIA `energy_bandpassname` 辨識 detector，**在候選排序與任何 Cutout 下載之前篩選**，渲染後再確認 FITS IMAGE 的 `DETECTOR` 確實相符。失敗只嘗試同 detector 的其他候選；不切到其他 detector。

每個 collection 先查 MAXREC=50。找不到指定 detector 且回應 OVERFLOW 或筆數達 MAXREC 時，擴大為 500、2000。優先 DR1；DR1 沒有匹配時再查 QR3。找到可用候選即可進入原排序／下載流程，不必為了宣稱完整而繼續下載 metadata。成功仍保留 `metadata.truncated`，並新增 `requested_detector` 及 `detector_search`（每次查詢的 collection、MAXREC、回傳數、匹配數、未知 detector 數、截斷狀態）。

MAXREC=2000 仍截斷、或存在無法辨識的 detector 值而沒有匹配時，保留「搜尋不完整」狀態；不能用它推論 NASA 沒有資料。重查是有界的 prefix expansion，沒有假設 SIA 支援分頁。沒有放大原有每次 SIA 8 MiB、FITS 32 MiB、16 次上游請求（含重試）、120 秒總期限、20 秒單次逾時、10 個 Cutout 候選的限制；兩個 collection 最多 6 次 metadata 查詢，重試仍共用同一個 RequestBudget。

| HTTP / code | 含義 |
|---|---|
| 404 `detector_not_found` | DR1、QR3 均完整且 detector 可辨識，但指定 detector 沒有候選。只描述此座標／半徑和這兩個 collections。 |
| 503 `detector_search_incomplete` | 結果仍截斷、detector 資訊未知，或請求／等待預算耗盡；不能判定沒有資料。 |
| 502 `detector_cutout_failed` | 找到指定 detector 候選，但預算內未能取得通過既有 WCS／有效像素檢查及 detector 核對的 Cutout。 |
| 502 `upstream_error` | SIA 網路／VOTable／QUERY_STATUS 失敗；不回報成沒有資料。 |
| 504 `upstream_timeout` | SIA 或 Cutout 逾時／總期限耗盡。 |
| 422 `invalid_input` | detector 不是整數 1～6 或 null；拒絕字串、布林與小數。 |

WCS、FLAGS、NaN、Histogram、Linear／Asinh、PNG cache 沿用原實作。時間序列 `/api/epochs/search` 的行為與欄位不變：座標欄位抽成共用 CoordinateRequest，新的單一 `detector` 只屬於 PreviewRequest，避免被 epochs 的繼承模型意外接受；原 `detectors` 清單仍照舊。

## 本機驗收（專案根目錄，PowerShell）

1. 使用本次已建立且安裝相依套件的 `.venv`，啟動 FastAPI，保留這個 terminal：

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
   ```

   若使用自己的環境，將 Python 路徑換成該環境即可；首次安裝測試相依套件用 `-m pip install -r backend/requirements-dev.txt`。

2. 另開 terminal 啟動前端：

   ```powershell
   node frontend/tools/serve.mjs
   ```

   打開 http://127.0.0.1:5500/planet-x/，使用「本機 localhost」，API 基底為 `http://127.0.0.1:8000`。不要加 `--fixture`，該模式不是 NASA detector 查詢驗收。

3. 填入 RA **133.79513**、Dec **-7.24515**、radius **0.01**，detector 選 **D6**，再按搜尋。成功後核對：

   - 指定 detector 為 D6，實際 Detector=6、波段 SPHEREx-D6。
   - 檢查 FITS 觀測日期、WCS 落點及 `target_spectral` 實際像素波長。
   - Histogram 與 min/max 亮度控制可用；Linear／Asinh、正反相與縮放可操作。
   - `metadata.requested_detector=6`、`metadata.sia.detector=6`、`metadata.detector=6`；若 SIA 截斷，頁面與 metadata 仍會標示。
   - 若回傳錯誤，畫面應呈現上述原因，選項仍保持 D6，不會自動切回 Auto／D1。

4. 可選：改回 Auto 再按搜尋，確認沿用既有自動選圖；也可指定 D1 再查。每次按搜尋都會進行上游查詢，請少量操作。亮度、stretch、反相與縮放不會新增 NASA 請求。

也可直接呼叫 API 驗證 D6（會實際連線 NASA）：

```powershell
$detectorBody = @{ ra = 133.79513; dec = -7.24515; radius_deg = 0.01; detector = 6 } | ConvertTo-Json
$detectorPreview = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/preview -ContentType 'application/json' -Body $detectorBody -TimeoutSec 180
$detectorPreview.metadata | Select-Object requested_detector, detector, observation, target_pixel_xy, target_spectral, truncated, detector_search
```

先前保留的 D6 cutout 是 2025-05-05 觀測，目標像素波長約 4.860934 μm；它已用本機 SIA/XML/FITS 離線重播通過新 selector 的完整 FastAPI 流程。NASA 結果與候選排序可能變動，**指定 D6 只保證 detector，不保證選到完全相同的曝光或波長**。

**D6 查詢成功不代表辨識出 WISE 0855。** 輸入座標未提供參考 epoch，仍須依實際觀測日期處理自行運動／視差，並另做天體辨識與科學驗證。

## 離線測試

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
node --test frontend/tests/*.test.mjs
```

新增 `backend/tests/test_detectors.py`，覆蓋 Auto、D1～D6、篩選在排序／下載之前、前 50 筆沒有但擴大後找到、DR1 無匹配改查 QR3、已截斷但有匹配、截斷仍無匹配、完整無資料、未知 detector、錯誤／缺失 QUERY_STATUS、預算與逾時、FITS detector 不符、輸入驗證與 epochs 不接受 preview-only 欄位。另以先前保留的 WISE 0855 XML/FITS 走完整 D6 API 離線回放；沒有 fixture 時該測試明確 skip。

前端新增 selector 數值傳送、Auto 不帶新欄位、查詢中停用、錯誤顯示與不偷偷 fallback 的測試。原影像科學資料／亮度與 epochs 測試保留。最終後端 68 項中 67 項通過、1 項 live NASA 測試略過；前端 30 項通過，`git diff --check` 通過。這次沒有新增 NASA 下載，沒有 Commit、Push 或部署；未做新一輪 live NASA 或真實瀏覽器點選驗收。
