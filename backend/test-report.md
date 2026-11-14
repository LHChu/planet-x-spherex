# Phase 2 測試狀態

2026-11-14 10:06:56 UTC 已實際嘗試使用現有 `research/.venv/Scripts/python.exe`：

| 操作 | 退出碼 | 結果 |
|---|---|---|
| 安裝 backend/requirements-dev.txt | 103 | Python 未啟動，未安裝 |
| unittest discover 離線測試 | 103 | Python 未啟動，沒有測試案例執行 |
| SPHEREX_LIVE=1 的真實 NASA API 測試 | 103 | Python 未啟動，沒有發出 NASA 請求 |

三次均回報：

```text
No Python at '"C:\Users\pearl\AppData\Local\Programs\Python\Python311\python.exe'
```

直接讀取該基礎執行檔也回報 `Access is denied`。虛擬環境存在，Phase 1 的成功紀錄與真實輸出也存在；但目前工具執行環境無法使用其指向的 Python 主程式。不能據此判定使用者本機的 Python 已遺失。

完整執行命令、例外與時間見 `test-attempts.json`。已人工檢查抽出的共用函式與後端呼叫、路由、錯誤分支，但 Python 語法、依賴、FastAPI 執行與 API 行為尚未通過執行驗證，不能宣稱測試通過。

請在能使用既有虛擬環境的本機終端，從專案根目錄依 `backend/README.md` 安裝依賴並執行離線測試，再執行 opt-in NASA live 測試。若本機也出現同樣錯誤，需先修復該虛擬環境指向的 Python；本次未修改或重建現有虛擬環境。

離線回放測試會真正解析 Phase 1 VOTable、讀取 FITS、執行 WCS 與轉圖，並比較 PNG 像素；其下載層以保存的檔案回放，因此不能代替 NASA live 測試。

## WCS／Windows 檔案占用修正驗證（2026-11-14 10:19:48 UTC）

已再次嘗試 py_compile、專項回歸測試與完整離線 API 測試；三者均在 Python 啟動前以退出碼 103 結束，未執行任何 Python 驗證。原始輸出見 `regression-test-attempts.json`，不能宣稱測試通過。

本次修正範圍：

- `research/spherex.py`：小型 Cutout 使用 `memmap=False`；保留 `with fits.open`。明確使用 IMAGE 的主 celestial WCS（保留 SIP），`skycoord_to_pixel(origin=0, mode="all")`。中心仍必須落在有效像素格範圍；零基像素中心為整數，因此邊界使用 `[-0.5, size-0.5)`，最近像素索引為 `floor(pixel+0.5)`。非有限座標及無效 WCS 不會被當作已確認的「目標在外」。
- `backend/app/service.py`：正常跳過 TargetOutsideImage，記錄含 pixel_xy、shape、CTYPE、CRPIX、CRVAL 的診斷（WARNING 級別，預設設定亦可見）；重試只保留逾時布林值，不保留例外 traceback 與影像引用。清理失敗會記錄完整錯誤並加註原例外，保留原本 PreviewError；沒有原始錯誤時，清理錯誤繼續拋出。不使用 ignore_cleanup_errors。
- `backend/tests/test_cutout_regressions.py`：新增九項離線回歸測試，包含 IMAGE/PRIMARY/alternate WCS 選擇、旋轉與 SIP、像素邊界、最近像素 NaN 判斷、真正越界、無效 WCS、保留 traceback 後刪除 FITS、失敗候選後重用同一檔名、成功與失敗下載的關閉、暫存目錄清理及原始錯誤保留。

已用 Node 讀取 Phase 1 保存的 metadata：成功影像 shape=(29,29)，目標 pixel_xy=(14.327577762368566,14.30554917316012)，原本中心判斷對這張成功影像成立。此檔案不是這次失敗的 candidate 0；目前沒有該候選 FITS，無法斷言該候選是實際不涵蓋目標或有異常 WCS。沒有修改 CRPIX 或關閉 SIP 來強行讓座標落入影像。

在專案根目錄使用現有虛擬環境驗證：

```powershell
.\research\.venv\Scripts\python.exe -m unittest backend.tests.test_cutout_regressions -v
.\research\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

專項測試會建立小型合成 FITS；它們是回歸測試資料，並非 NASA 成功下載的證據。Windows 上的 rename/unlink 測試會直接檢查是否仍有占用，不依賴 gc.collect、重試刪除或忽略清理錯誤。既有 API 回放測試仍使用保存的真實 Phase 1 FITS。

本機重試原本 POST 時，建議加入 `--log-level info` 啟動 Uvicorn，以查看跳過候選的診斷訊息：

```powershell
.\research\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1 --log-level info
```

參考：[Astropy FITS memory mapping 與檔案關閉](https://docs.astropy.org/en/stable/io/fits/index.html#working-with-large-files)、[skycoord_to_pixel 的 origin/mode 定義](https://docs.astropy.org/en/stable/api/astropy.wcs.utils.skycoord_to_pixel.html)。

## 候選排序與 503 重試修正（2026-11-14 10:34:05 UTC）

使用者本機回報：Candidate 0 為 shape_yx=(13,29)，pixel_xy=(14.0545857,14.4063788)；其餘四個候選 HTTP 503，最終 502 cutout_failed，WinError 32 未再出現。這是使用者提供的實測，不是本工具環境執行的結果。

13 列影像的零基像素格只涵蓋 y∈[-0.5,12.5)，目標高於上界約 1.906 像素。下載成功不代表中心在影像內；搜尋半徑 0.01 度為 36 角秒，可能與目標中心在曝光外的邊緣影像相交。3arcmin 約為原本 29 像素邊長，但裁切後可只剩 13 列。官方服務說明允許只回傳交集，即使中心在原曝光之外。

這與原曝光邊緣裁短一致，但失敗 Candidate 0 的 FITS／alternate A header 未保存在目前目錄，仍不能把「推測的裁短原因」寫成已獨立確認。新增的 `parent_window` 日誌使用官方 alternate A 的映射 `original_zero_based = 1 + cutout_zero_based - CRPIXnA`；若起點加上 13 列等於原曝光高度，且目標原像素超出該高度，就能支持原曝光高 y 邊界裁短的判斷。回歸測試包含此種合成案例；不下載整張原曝光來推測邊緣。

本次修改：

- 新增 `backend/app/candidates.py`：僅在小型 SIA metadata 上計算凸球面多邊形的中心覆蓋與距邊界估計；處理 RA 跨 0 度、極區及頂點反向。缺少、非凸或不支援的 footprint 保守視為未知。保留下載後的 WCS 檢查。
- 新增 `backend/app/nasa_requests.py`：將 SIA 與 Cutout 的 503 重試／指數退避、Retry-After、16 次請求總量、120 秒協作式 deadline、20 秒 socket timeout 與最多 15 秒單次等待集中於一份 preview 預算。
- 修改 `backend/app/service.py`：先排序，最多嘗試 10 個不同 URL；越界候選不重複下載；超出預算就停止；既有錯誤 code 與輸出欄位保留，附加成功結果的排序與請求計數 metadata。
- 修改 `research/spherex.py`：既有下載函式增加選用的 timeout/deadline，逐塊檢查期限並關閉 HTTPError 回應；query_images 可注入同一預算下載函式。沿用 Cutout／轉圖算法與 memmap=False。越界訊息增加原曝光邊界診斷。
- 新增 `backend/tests/test_candidates_and_retry.py`：13 項單元測試，覆蓋排序、球面幾何、缺少 metadata、裁短診斷、第六個候選、越界去重、候選上限、有限 503 次數、指數退避、Retry-After 秒／日期、超長等待、跨候選 cooldown、非 503、請求及期限上限。網路與睡眠皆 mock。
- 調整既有 `test_api.py` 的真實檔案回放與 `test_cutout_regressions.py` 的下載 mock，以相容新增 timeout/deadline 參數。影像回放刻意保留原順序並略過睡眠；排序／退避由新單元測試獨立覆蓋。

本次實際嘗試 py_compile、候選／重試專項測試、完整離線測試，均因既有虛擬環境無法啟動 Python，退出碼 103，沒有執行任何測試案例。紀錄見 `candidate-test-attempts.json`。沒有宣稱排序、重試或新 NASA 請求已驗證成功。

本機執行：

```powershell
.\research\.venv\Scripts\python.exe -m unittest backend.tests.test_candidates_and_retry -v
.\research\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

再重啟後端並重送原 POST，核對新的 `candidate_source_index`、`footprint_margin_arcsec`、`nasa_request_count` 或失敗時的 `parent_window` 診斷。若所有候選依然失敗，仍會回傳既有 502／504 格式，不回傳缺少中心的影像。

參考：[IRSA 邊緣裁切與非中心交集說明](https://irsa.ipac.caltech.edu/ibe/cutouts.html)、[HTTP Retry-After](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3)、[SPHEREx 原像素座標映射](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)。

研究目錄的成功報告與 `outputs/` 保持原狀。未啟動伺服器、未製作前端、未新增 Render 部署設定。
