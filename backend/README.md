# SPHEREx Phase 2：本機 FastAPI 後端

## 本機啟動（Windows PowerShell）

第一次 Clone 請先參考[根目錄 README 的 Requirements 與 Quick Start](../README.md#quick-start)。以下所有指令都在 Clone 後的**專案根目錄**執行（同時含有 `backend/`、`research/`、`frontend/` 的資料夾），不要先切換到 `backend/`；不要求特定磁碟或絕對路徑。

建立 Python 3.11 虛擬環境並安裝執行所需套件（已完成者可跳過）：

```powershell
py -3.11 -m venv research/.venv
.\research\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

`backend/requirements.txt` 透過 `-r ../research/requirements.txt` 引用研究階段依賴；pip 依 requirements 檔案位置解析該路徑，不需額外安裝一次。直接使用虛擬環境的 `python.exe`，不需執行 `Activate.ps1`。

啟動 FastAPI（port 8000），並保持此 Terminal 執行中：

```powershell
.\research\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

開啟 http://127.0.0.1:8000/docs 使用互動式 API。`GET /health` 只檢查後端可回應，不呼叫 NASA。

另開一個位於專案根目錄的 Terminal，執行 `node frontend/tools/serve.mjs`（Node.js 18+，不需 `npm install`），再開啟 http://127.0.0.1:5500/planet-x/。頁面選「本機 localhost」，API 基底網址填 `http://127.0.0.1:8000`。前後端分別在兩個 Terminal 運作；按 `Ctrl+C` 停止各自的伺服器。

## PowerShell 測試

保持 FastAPI 執行，另開位於專案根目錄的 PowerShell 執行以下指令。這會實際連線 NASA，PNG 下載至專案根目錄。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
$body = @{ ra = 127.69444; dec = -39.17760; radius_deg = 0.01 } | ConvertTo-Json
$preview = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/preview -ContentType 'application/json' -Body $body -TimeoutSec 900
$preview | ConvertTo-Json -Depth 20
Invoke-WebRequest -Uri $preview.image_url -OutFile preview.png
Invoke-Item preview.png
Invoke-WebRequest -Uri $preview.inverted_image_url -OutFile preview-inverse.png
Invoke-Item preview-inverse.png
```

輸入為十進位度數，`0 <= ra < 360`、`-90 <= dec <= 90`、`0 < radius_deg <= 5/60`；必須為 JSON 數值，拒絕字串、布林值、NaN、Infinity 與多餘欄位。

**搜尋半徑只控制 SIA2 搜尋。Cutout 沿用 Phase 1 已驗證的 3arcmin 完整邊長**，因此不保證輸出影像涵蓋整個搜尋圓。候選需通過 WCS 目標中心與有效像素檢查。影像維度由 IRSA 決定，不強制縮放為 29×29。

成功回傳 `key`、`image_url`、`inverted_image_url`、`expires_in_seconds` 與 `metadata`。metadata 保留原始 SIA 列、MJD 時間、UTC 時間、detector、HDU headers、處理版本、Cutout URL、亮度 stretch、影像維度、FITS 大小、候選嘗試次數、耗時及查詢截斷資訊。

影像 URL 為目前 API 的絕對 URL，`GET /api/images/{key}.png` 回傳 `image/png`。記憶體快取保留至多 32 組／16 MiB，10 分鐘到期，也可能提早因容量限制被淘汰；後端重啟後失效。不存在或到期請重新 POST。FITS 和中間產物只在每次請求專屬暫存目錄使用，結束後清除。一次只執行一項轉圖工作，所以本階段請使用單一 worker。

## 錯誤

API 錯誤格式為 `{"error":{"code":"...","message":"..."}}`，輸入驗證另有 `details`。

| HTTP | code | 含義 |
|---|---|---|
| 422 | invalid_input | 輸入或 JSON 無效 |
| 404 | no_images | DR1 與 QR3 都正常回傳空表 |
| 404 | image_not_found | 圖片 key 無效、到期或遭淘汰 |
| 502 | upstream_error / cutout_failed | NASA／VOTable 失敗，或候選／請求預算內無有效 Cutout |
| 504 | upstream_timeout | SIA2 或全部候選下載逾時 |
| 503 | busy | 已有工作執行，依 Retry-After 重試 |
| 500 | internal_error | 未預期後端錯誤，詳細原因記錄於伺服器日誌 |

DR1 只有空表才查 QR3，查詢上限仍為 50 筆；先按 `s_region` 的球面覆蓋多邊形排序：中心在內且離邊界較遠優先，其次缺少覆蓋資料，已知中心在外最後。缺少或不支援的 footprint 不會直接判定無覆蓋。這是預篩與排序，不能代替最終 FITS 的 WCS／有效像素檢查。

不再固定只嘗試前五張：從這份結果中最多嘗試 10 個不同 Cutout URL，確認 WCS 越界後不再下載同一 URL。沒有為了更多候選反覆查詢 SIA，也不會因 `OVERFLOW` 無限擴大查詢。

`backend/app/nasa_requests.py` 集中設定請求預算：單次 preview 的 SIA 與 Cutout 合計最多 16 次下載嘗試，每個 URL 最多三次（初次＋兩次重試），僅對 HTTP 503 重試。退避為 1、2 秒；`Retry-After` 支援秒數與 HTTP 日期，等待較長者，切換候選也不能跳過同一次 preview 的 cooldown。若等待超過 15 秒或剩餘總預算，就停止本次 preview，不能截短 Retry-After 後提早重試。非 503 不自動重試。

共用 120 秒協作式 deadline，每次連線／socket timeout 最多 20 秒，下載以單次底層讀取並逐塊檢查期限。這不是能強制中斷 DNS、HTTP 標頭讀取或 OS 阻塞的硬性牆鐘上限；執行中的 I/O 可能超出剩餘期限，逾時後不再開始新請求。Cutout 上限 32 MiB，VOTable 上限 8 MiB，不自動下載完整影像。成功 metadata 增加 `candidate_source_index`（原 SIA 零基序號）、`footprint_margin_arcsec` 和 `nasa_request_count`，既有 API 欄位及錯誤 code 保留。

若 Cutout 越界，日誌還會提供 `parent_window`：在 alternate A 座標及 SIA 原曝光尺寸齊全時，列出 Cutout 在原曝光的起點、目標原像素座標與是否接觸原曝光邊界。資料不足則標明不可判定，不推測 NASA 格式有誤。

## CORS

啟動前可設定以逗號分隔的完整 origins，不能包含路徑或尾端斜線：

```powershell
$env:CORS_ORIGINS = 'http://localhost:5500,http://127.0.0.1:5500,https://YOUR_ACCOUNT.github.io'
```

未設定時允許 localhost:5500、127.0.0.1:5500、localhost:5173。使用明確允許清單與 `allow_credentials=False`；不使用萬用 origin。[FastAPI 官方 CORS 文件](https://fastapi.tiangolo.com/tutorial/cors/)

## 測試

在專案根目錄安裝測試依賴後執行。`requirements-dev.txt` 也會引用正式依賴；一般啟動只需 `requirements.txt`。

```powershell
.\research\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\research\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
$env:SPHEREX_LIVE = '1'
.\research\.venv\Scripts\python.exe -m unittest backend.tests.test_api.ApiTests.test_live_nasa -v
Remove-Item Env:SPHEREX_LIVE
```

預設測試不連線 NASA：使用 Phase 1 的真實 VOTable/FITS 回放，實際執行共用解析、WCS、轉圖及 PNG 端點，再與 Phase 1 PNG 像素比對；另測輸入、錯誤、CORS、快取與併發限制。QR3 fallback 測試使用刻意建立的測試 VOTable。真實檔案不存在時回放會 skip。live 測試才真正呼叫 NASA，結果寫至 `backend/test-results/`。測試採用 [FastAPI TestClient](https://fastapi.tiangolo.com/tutorial/testing/)。

## 共用程式碼

`research/spherex.py` 從成功的 `verify_spherex.py` 抽出 `fetch`、`query_images`、`build_cutout_url`、`render_cutout`；CLI 與後端皆呼叫同一份函式。保留原 SIA collection、查詢格式、3arcmin Cutout、HDU 檢查、百分位/asinh 與灰階反轉算法。後端不呼叫 CLI 的 `main()`，不覆寫 Phase 1 輸出或報告，也不使用可變全域座標／目錄處理請求。
