# 影像亮度與科學資料驗證（2026-11-14）

Phase 4 後續 API 與動畫開發暫停。本次保留工作區原有的 epochs 修改，未 Commit、Push 或部署。

## 檢查結果與實作

原流程：`create_preview()` 查 SIA → 依 footprint 排序 → 下載有大小上限的 3 arcmin FITS → `render_cutout()` → 暫存 PNG → FastAPI PNG cache → 前端 `<img>`。原本 `np.isfinite()` 正確排除 NaN/±Inf，也會排除 Astropy 由整數 FITS `BLANK` 解碼的 NaN；但 PNG 的 `nan_to_num()` 讓無效像素變黑，且原流程沒有讀取 FLAGS。

現在使用 `finite & quality_selected` 作為有效遮罩。有效零與負值保留，不依亮度正負判斷有效性，不將任意有限 sentinel（例如 -9999）自行視為無效。讀取 FLAGS，排除 bit 1 OVERFLOW、2 SUR_ERROR、6 NONFUNC、9 MISSING_DATA、15 NONLINEAR、19 OUTLIER；SOURCE（bit 21）不是壞像素。這是明確、保守的顯示品質規則，不是所有科學分析的完整品質選樣。其餘 flags 原值完整保留，可用橘色疊圖查看；疊圖預設關閉。沒有 FLAGS 時只做 finite 檢查，metadata 明確標示；FLAGS 尺寸或型別不符則拒絕該候選。

所有百分位和 histogram 僅使用上述有效、未拉伸的 IMAGE 值。histogram 使用 64 個等寬 bin、線性計數，涵蓋完整有效 min/max，總數等於 valid_pixels；不截掉百分位以外像素。BUNIT 僅接受 `MJy/sr`（可含空白），大小寫敏感，不將 mJy 誤認為 MJy；未知單位繼續提供 PNG，但不啟用 MJy/sr 控制。

`hi <= lo` 可能發生於全部像素相同、只有一個有效像素、量化影像或超過 98% 像素相同而離群值不足 1%。先退回原始 min/max；常數資料使用以常數為中心的小有限顯示範圍並標示 `fallback=constant`，不製造科學對比。空有效集、全無效品質遮罩或無法表示的有限範圍會清楚拋錯，沿用既有候選重試與 API error envelope。輸入空值、非有限值或 max ≤ min 時保留上一張有效顯示並提示，不送出新 NASA 請求。

前端新增 histogram、min/max slider、對應數字欄位、重設按鈕、linear/asinh 選項。互動顯示預設 linear；既有 PNG 端點保留 asinh(10x)、黑白反相與縮放。PNG 有無效像素時使用灰階加 alpha；反相只改灰階，透明度不變。前端同樣使用固定 valid mask，透明像素的視窗底色不是有效零值。品質規則改變會使舊 PNG 的百分位與部分亮度改變，這是修正；asinh 數學轉換另外對照既有實測 PNG，允許 8-bit 浮點捨入差 1。

IMAGE 使用原有主 celestial WCS + SIP、零起算與 pixel-cell 邊界檢查；不把 alternate A 當天空座標。新增 alternate W 波長資訊時，只從 header 的副本移除 celestial SIP，避免把天球畸變套進原始像素 wavelength lookup。FITS 本身不修改。目標中心若非有限，沿用原有候選拒絕行為；中心有排除品質旗標時回傳 `target_valid=false`，不把它畫成有效值。

## 檔案

- `research/spherex.py`：遮罩、顯示範圍、histogram、受限原始值、透明 PNG、觀測與光譜 WCS metadata。
- `backend/app/main.py`：preview 回應 `Cache-Control: no-store`；保留原有未提交 epochs 修改。
- `frontend/brightness.js`、`app.js`、`index.html`、`styles.css`：純顯示轉換與 UI。
- `backend/tests/test_brightness.py`、`test_api.py`、`frontend/tests/brightness.test.mjs`、`app.test.mjs`：資料不變、遮罩、控制項與 preview 回歸測試。
- `research/verify_brightness.py`：最多一份 SIA、一張 cutout 的 opt-in 驗證，可完全離線重播。
- `research/brightness-verification.json`：小型實測摘要；原始 FITS/XML 與詳細紀錄留在 gitignored `research/outputs/brightness-wise0855/`。

## 請求、快取與記憶體

選擇沿用 `/api/preview` 的 additive `metadata.display`，在瀏覽器重繪，不新增 Phase 4 API、不新增伺服器 render cache。

- 原 NASA FITS 下載上限仍 32 MiB；SIA 單次 8 MiB；原本 request/deadline/retry budget 與單一處理鎖保留。
- 解壓 IMAGE 前檢查二維與最多 262,144 像素，FLAGS 邏輯尺寸必須匹配；工作陣列使用有界 float64 副本。此上限適用小 cutout，不支援直接渲染整張 detector。
- 最多 65,536 個原始像素；JSON display payload 最多 4 MiB。超過任一上限就移除 values/valid/flags、提供原因，保留 histogram metadata 與原有 PNG。4 MiB 是 display 部分上限，整個回應另含 FITS headers/SIA metadata。
- values 保留 finite 原始值（品質排除仍可保留數值以供檢查），NaN/Inf 編碼為 null；valid 是獨立布林遮罩，flags 是完整整數。沒有 float32 再量化、預先拉伸、重採樣、ZODI 扣除或 FITS 回寫。
- 伺服器 PNG cache 仍為 process-local，TTL 600 秒、32 entries、總 16 MiB，只存兩張 PNG，不保留 FITS/raw arrays。preview 與 PNG 均 no-store；已載入瀏覽器的資料可在 PNG TTL 過後繼續調整，重新搜尋時釋放前端參照。
- 本次 display payload 27,906 bytes；離線驗證整個 Python 程序（含 imports）的 peak working set 75,821,056 bytes，約 72.3 MiB。不是併發 API、最大尺寸或瀏覽器記憶體壓力測試。Python JSON 物件與序列化會有暫時副本，4 MiB 不能視為程序總記憶體上限。
- 未選伺服器每次重新渲染：否則須保存原始資料、共用容量/TTL 限制、限制 min/max/method 與回應大小、加入 render 併發控制，避免每次拖動重抓 NASA。此次有界小 cutout 在瀏覽器處理較適合驗證。

## WISE 0855：已實測

指定 ICRS RA=133.79513、Dec=-7.24515，radius=0.01 deg。初次 live 共 **2 次** NASA 請求，無重試：一份 DR1 SIA（MAXREC=50）及一張 3 arcmin cutout；後續全部重播本機資料。

- SIA 50 筆、QUERY_STATUS=OVERFLOW：結果不完整，沒有擴大下載、沒有 QR3 查詢。驗證腳本在回傳候選中優先 D6，以便檢查較長波長；正式 preview 仍使用原排序，不保證預設選到同一張 D6。
- Observation ID `2025W19_1B_0138_1`，SIA 與 FITS detector 均為 6。
- SIA detector 波段 4.4115–5.0096 μm；目標像素 alternate W 波長 **4.8609341964 μm**、頻寬 **0.0379674425 μm**。不能把 detector 整段波長範圍當作單像素通帶。
- FITS `DATE-OBS/DATE-BEG` **2025-05-05T20:01:35.430 UTC**、`DATE-END` **20:03:30.548 UTC**。SIA t_min/t_max 轉為 20:01:35.443–20:03:30.528（與 header 差約 13–20 ms）；產品 `DATE=2026-07-17T07:07:33.614` 是建立時間，不是觀測時間。
- 29×29 IMAGE；有限 840，品質選擇後 827。輸入座標 FITS 零起算落點 **(13.6256103159, 13.5176887738)**，最近像素有效；天空座標往返為 (133.79513000000605, -7.245150000014044)。
- FITS 大小 3,962,880 bytes；渲染、不同 stretch 後 SHA-256 仍為 `bcbe6da84fdc2b1727974ec2fabb6f7d048d79fbf525c7096e724a8a86b58d1d`。
- 另外透過 FastAPI TestClient 離線重播該 FITS，確認 preview metadata、正反 PNG、實際日期、detector、光譜 WCS 與有效像素數。

**沒有宣稱辨識出 WISE 0855。** 提供座標缺少參考 epoch；該天體自行運動約 8.1 arcsec/year，跨十年可偏移約 81 arcsec，已接近 3 arcmin cutout 的半寬。尚未做可靠的自行運動與視差傳播、source identification、測光、可見性或 S/N 判斷。

## 測試與未驗證

執行 `.venv/Scripts/python.exe -m unittest discover -s backend/tests -v` 與 `node --test frontend/tests/*.test.mjs`。前端 26 項通過；後端 57 項中 56 項通過、1 項一般 live NASA 測試刻意略過。涵蓋 NaN/Inf、FITS BLANK、全無效、品質 mask、零/負值、退化百分位、常數、輸入範圍、單位大小寫、payload 限制、透明度/反相、FITS checksum、不修改 JS 原始陣列、固定 histogram、互動不增加 fetch、舊 preview/縮放/CORS/快取/候選重試，以及現有 epochs 回歸。

未做真實瀏覽器視覺/行動裝置驗收、最大尺寸與併發壓力測試、其他 detectors/日期的 FITS 實測，也未進行完整所有品質 bits 的科學適用性審核。一般 live NASA unittest 刻意略過，避免再次下載；本次只採上述兩次限定 NASA 請求。

參考：[IRSA IMAGE/FLAGS/WCS 說明](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/)、[WISE 0855 發現論文及自行運動](https://arxiv.org/abs/1404.6501)。
