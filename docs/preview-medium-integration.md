# Preview Small／Medium 安全整合

日期：2026-11-15。接續 [前輪尺寸研究](cutout-size-expansion-review.md)，僅整合 Preview；本輪未連線 NASA、未下載 FITS、未執行 Render 壓力測試、未 commit／push／部署。

## 結果與啟用範圍

本機工作目錄已整合可選用的 Preview Medium，離線 API、資源及真實 Chromium 驗收通過，沒有出現必須提高安全上限或停用 Medium 的測試結果。Small 仍是預設，舊 client 的請求與 3 arcmin 行為維持。這是**尚未部署、待正式驗收**的整合，不是正式服務／IRSA 成功率或 Render RAM 的保證。

本輪完全沒有編輯 `backend/app/epoch_frames.py`、`frontend/epochs.js` 或 epoch 科學規則。這些檔案在開始前已存在未提交修改，保持原狀；Multi-epoch 仍固定 29×29、原生 128 軸上限、2–3 影格。不新增 Large／128 選項，不改 `research/spherex.py` 科學處理、GitHub Actions、Render YAML、production start 或依賴清單。既有工作目錄修改保留。

## API 與 metadata

`POST /api/preview` 新增 `cutout_profile: Literal["small", "medium"] = "small"`。`backend/app/preview_size.py` 用不可變 allowlist 對應：

| profile | IRSA size 字串 | requested_cutout_arcmin |
|---|---|---:|
| small（預設） | `3arcmin` | 3.0 |
| medium | `6.5arcmin` | 6.5 |

拒絕 large、128、256、任意角度字串、null、數字、布林、物件及額外尺寸欄位；在呼叫 service／SIA 前回 422。service 也自行驗證白名單，不依賴 caller 善意。`radius_deg` 維持獨立 SIA circle radius，沒有因 profile 改動搜尋條件、候選排序、重試或 detector 選擇。

service 把同一 `cutout_size` 同時傳給 `build_cutout_url` 與 `render_cutout`，避免 request／metadata 記錄不同。舊 client 不帶 profile（或明帶 small）繼續用預設 Small。

metadata 保留原欄位，新增：

- `cutout_profile`、`requested_cutout_arcmin`：使用者要求的角度。
- `actual_shape_yx`：實際 IMAGE shape，不 resample、不強制 64×64。
- `wcs_field.available`、`horizontal_arcmin`、`vertical_arcmin`：實際回傳影像的天區跨度。
- `wcs_field.horizontal_samples`／`vertical_samples`：各 17 個零起算 pixel-cell 中心線取樣點及對應 ICRS RA／Dec。
- `wcs_field.corners`：四個 pixel-cell 外角的 pixel／ICRS 座標。
- `source`、`method`、`coverage_note`：明示完整 IMAGE celestial WCS／distortion、取樣定義，以及不保證覆蓋完整 requested field。

跨度算法：水平線從 `x=-0.5` 到 `width-0.5`，固定 `y=(height-1)/2`；垂直線相反。以 `pixel_to_skycoord(..., mode="all")` 包含 SIP 等現有可用 WCS distortion，再累加相鄰取樣點的球面 separation（arcmin），不直接相減 RA。這是**取樣的中心線球面路徑長度**，不是天球軸向 bounding box、精確全視野面積或 coverage 完整性驗證。不可驗證的 WCS 回 `available=false`，UI 顯示 unavailable，不猜測角度。

## UI

Preview panel 新增 Cutout Size：Small 3 arcmin、Medium 6.5 arcmin，無自由輸入／Large。說明 Medium 目標約 64×64，實際 shape 依 FITS／WCS／IRSA 裁切決定；實際瀏覽器驗收刻意用 **65×65**，證明不依賴精確 64 軸。

第一次選尺寸後按 Search；已有成功 Preview 時，改尺寸自動送一次新的 Preview。處理期間停用 selector，防止重複請求；失敗後可明確按 Search 重試。Small 為兼容舊 API 省略 profile，Medium 明傳 profile，不會在舊 API 拒絕 Medium 時悄悄降級成 Small。

回傳後在影像旁顯示 requested size、FITS y×x 與 WCS span。Search Radius 改用清楚的 label；Zoom／Fit 註明只改倍率。Stretch／反色／Histogram／Color Bar／Zoom／Fit 保留，皆不新增上游請求。Preview selector 位於 Preview 專屬 panel，Multi-epoch 不使用此欄位。

## 安全與快取

所有原有限制未更動：download 32 MiB、IMAGE 262144 pixels、client 65536 pixels／4 MiB display JSON、PNG cache 16 MiB／32 組／600 秒、共享處理鎖、10 candidates、16 requests、20 秒 per request、120 秒 total upstream deadline、3 attempts、15 秒 wait cap。4 MiB 是 display payload 的既有限制，不是整個 API response 上限。

Preview cache 仍只存兩 PNG、不存 raw arrays／metadata，隨機 key 讓 Small／Medium 不會錯誤共用同張影像，無須新增 query cache key 或提高容量。測試驗證 profile isolation、容量淘汰、成組 PNG 取回與過期後 404。尺寸選項不是更改 pixel／JSON safety cap 的理由。

## 測試結果

後端 **107 項：106 通過、1 項 live NASA skip**。`backend.tests.run_offline` audit hook 禁止外部連線，沒有回報外部連線嘗試。既有本機資料 replay 仍照舊執行；本輪新增尺寸證據全部由人工生成 FITS 取得。

新增 `test_preview_medium.py` 覆蓋：

- 真實 service／API pipeline：mock SIA／download，保留 URL 組裝、renderer、WCS、JSON、PNG 與 cache；Small 舊請求、明傳 Small、Medium 都驗證 URL size＝renderer size＝metadata。
- API invalid enum／任意 size 欄位拒絕、OpenAPI enum／default、搜尋半徑獨立、epoch API 不接受新欄位。
- 64×64 SIP／RA 跨 0°、63×65 float64／+85°、65×64 int16／−85°、32×61 int32／SIP／目標近裁切邊界；23° 旋轉、非方形資料、NaN／±Inf／integer BLANK／負值／零及高熵背景／密集 FLAGS。
- 從獨立 fixture WCS 逐點核對 metadata 的 sky samples，球面角距驗證 span，並證明移除 SIP 後座標有差異；RA 跨界原始差可超 359°，實際跨度仍小於 7 arcmin。
- Histogram count 與 Preview valid mask 一致，無效像素透明；WCS 缺失不虛構 span；cache eviction／expiry／profile isolation／busy lock 與原有限制。

更新既有 candidate／detector 測試 mock 接收新增 renderer 尺寸引數，仍斷言原有 Small＝3 arcmin。更新 `test_deployment.py` 驗證 Small／Medium 的 production origin CORS、HTTPS image URLs／cache retrieval、invalid Large、既有 Free 設定及單 worker 啟動。clean-source server 測試不攜帶 fixtures／下載資料也能啟動，會包含新增 runtime module。

前端 **149/149 通過、無 skip**（包含前輪已產生的 29／64／128 離線 fixtures 測試；128 仍僅是測試資料，並非正式選項）。新增尺寸切換、無效選擇、loading 排他、requested／actual metadata 顯示及 epoch 不接收 Preview profile 的測試；既有 four stretches／WCS／Color Bar 等回歸全部通過。Pages artifact 測試驗證 root／project path、相對 assets 及公開檔案邊界，未新增對外發布的測試資料。

新增 `browser-preview-medium.mjs` 真實 Chromium 驗收 **1366×768、768×1024、390×844 全通過**：每次 Small→Medium 恰有兩次 API POST 總計，PNG 由實際合成 FITS pipeline 產生；65×65 natural dimensions、metadata、四種 Stretch、NaN alpha、Fit 內含 axes／Color Bar、Zoom 及頁面不橫向溢出皆通過。截圖已人工檢視，產物位於 gitignore 的 `frontend/coverage/preview-medium/`。

測試 browser 使用獨立 temporary profile、只服務 repository HTML 與 loopback 合成 API；CSP 限制連線同源，host resolver 拒絕外部解析。受 Windows 執行環境限制，headless 測試使用 in-process GPU／no-sandbox flags；這些只在測試腳本，不是網站或正式瀏覽器設定，亦不代表已驗收一般桌面／行動裝置 GPU 環境。

## 資源量測

詳見 [原始三次獨立程序量測](preview-medium-measurements.json)。Windows 11／Python 3.12.14，現有鎖定科學依賴。以實際 Preview API、float64 高熵背景、SIP、+80° 高赤緯、密集 FLAGS 測試；Medium 故意使用 65×65。每個 profile 三次獨立程序，含合成 FITS 生成、URL／render、metadata、JSON response serialization、cache put、兩 PNG retrieval 與 tracemalloc 開銷；不含 network latency／import 冷啟動，非遠端效能測試。

| profile | shape | 秒數範圍（中位數） | 程序 peak RSS 最大值 | tracemalloc peak 最大值 | response 約 | PNG cache |
|---|---|---:|---:|---:|---:|---:|
| Small | 29×29 | 0.316–0.436（0.381） | 90.2 MiB | 1.84 MiB | 36.3 KiB | 2.45 KiB |
| Medium | 65×65 | 0.482–0.752（0.497） | 93.2 MiB | 2.89 MiB | 132.2 KiB | 11.29 KiB |

RSS 是 Windows PeakWorkingSetSize，包含 interpreter／native libraries，不能視為單張 cutout allocation；tracemalloc 不能取代 native-inclusive RSS。這輪高熵資料的 cache 大於前輪平滑星場，仍遠低於原 cache 上限。沒有將「每張資料大小」誤當全部 cache 填滿時的程序記憶體，也沒有做長時間／併發容量保證。

Render 官方 [Compute Plans](https://render.com/docs/compute-plans) 確認 Free 為 **512 MB RAM／0.1 CPU**（2026-11-15 查閱）；本機 `render.yaml` 是 `plan: free`，`backend/start.py` 強制 `workers=1`、reload false，單 worker 測試通過。此處僅查公開 Render 文件與本機設定，沒有向 Render app 發送測試。Windows 本機 93.2 MiB 峰值支持現有 cap 下進行 Medium 整合，但不是 Linux／Render 512 MB 容量或 CPU deadline 的實測證明。

## 正式開放前的剩餘驗收

1. 本輪禁止 NASA 連線，因此尚未驗證 IRSA 對真實 SPHEREx 6.5 arcmin request 的 shape／裁切／壓縮 HDU／較複雜 lookup distortion／實際品質與候選成功率。需另行授權後做小量功能驗收，核對 URL、requested、actual shape／WCS／邊界，不保證精確 64×64。
2. 在 Linux、既有 pinned requirements 與單 worker 下重跑本機離線 suite／資源 probe；如需正式環境健康與功能驗收，須由維護者另行執行，不能把本機結果當成 Render RAM／cold start／0.1 CPU deadline 保證。不建議在未驗收前直接部署。
3. 實際 Safari／Firefox／手機裝置、一般 GPU sandbox 環境及長時間互動未涵蓋；Chromium 三個尺寸驗收不能完全取代跨瀏覽器測試。
4. 所有 cache 接近容量的長時間 RSS、真實高密度噪聲／headers、實際上游 retries 同時影響的資源情況未做壓力測試。若後續無法在原 cap 內可靠完成，應停用 Medium，不提高限制來掩蓋問題。
5. 先審核並驗收 backend API 支援，再由維護者安排 frontend 發布；先發布 Medium 前端到舊 backend 會收到明確 422，不會靜默回傳 Small。此為發布順序建議，本輪沒有修改或觸發部署。

## 重跑方式

```powershell
.\.venv\Scripts\python.exe -m backend.tests.preview_medium_probe
node frontend/tests/browser-preview-medium.mjs
node frontend/tools/test.mjs
.\.venv\Scripts\python.exe -m backend.tests.run_offline
```

browser runner 可傳入 Chromium executable 路徑，預設 Windows Chrome。舊 `cutout-sizes.test.mjs` 的 fixtures 若不存在，需先用前輪 `backend.tests.cutout_size_probe` 產生；本輪執行時已有 fixtures，149 個前端 tests 無 skip。所有合成 FITS 暫存後清除，JSON／PNG fixtures 與完整 logs 皆在被 gitignore 的 test-results／coverage 下，沒有放入 Pages artifact。
