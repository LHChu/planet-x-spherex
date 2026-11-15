# Planet X / SPHEREx Cutout 尺寸擴充：離線研究及最小原型

日期：2026-11-15。範圍：保留現有約 29×29 / 3 arcmin 預設；以合成 FITS 驗證 64，評估 128。沒有新增正式 API 尺寸參數、正式 UI 選項、部署設定、影格數或提高任何安全上限；沒有測試或開放 256 以上尺寸。

本輪僅新增測試、離線原型與報告，沒有編輯任何原有檔案。開始時工作目錄已有的未提交修改完整保留。沒有下載資料、連線 NASA、執行 Render 壓力測試、commit、push 或部署。

## 結論與支援範圍

| 尺寸 | Preview | Multi-epoch |
|---|---|---|
| 29×29 | 合成測試通過；維持現有預設 | 兩影格合成測試通過；維持正式固定輸出 |
| 64×64 | FITS→遮罩→PNG→JSON→顯示測試通過 | 原生輸入可由現有程式讀取，但正式仍輸出 29；**只有離線原型**的 64 共同網格通過 |
| 128×128 | 合成資料資源及顯示測試通過，尚不宜正式開放 | **只有離線原型**的 128 共同網格通過；原生任一軸 129 仍拒絕，13 arcmin 存在裁切邊界風險 |

建議：64 作為下一步受控 Preview 整合目標；本輪證據不足以直接宣告可在正式站全面開放。Multi-epoch 須獨立整合共同網格參數、快取及 coverage 判定，不能跟隨 Preview 自動啟用。128 繼續離線評估。正式網站本輪仍只有原來 3 arcmin 行為。

## 目前實際資料流程

1. `backend/app/main.py` 的 `/api/preview` 驗證 RA、Dec、`radius_deg` 和 detector，經共享處理鎖呼叫 `service.create_preview`。
2. `research/spherex.py:query_images` 向 IRSA `/SIA` 查詢 ObsCore metadata，`POS=CIRCLE ra dec radius_deg`；DR1/QR3、detector 及候選重試規則沿用現有程式。SIA 是找影像，並非產生裁切影像。
3. `service.py` 排序候選，以候選 `access_url` 建立 IRSA `/ibe/data/spherex/...` URL，附加 `center=ra,decdeg` 與 `size=3arcmin`。`build_cutout_url` 及 `render_cutout` 雖已有內部 `cutout_size` 引數，service 尚未傳遞可選尺寸。
4. 受限下載到暫存 FITS，`render_cutout` 讀 IMAGE／FLAGS，使用 IMAGE 完整 celestial WCS（含可用 distortion）定位目標，以有限值和 Preview 壞點 bit 產生遮罩及 PNG；FITS y 軸翻轉成 PNG。以同一 IMAGE WCS 產生座標刻度。
5. API 只把兩張 PNG 放入 `ImageCache`；完整 metadata／像素 JSON 隨 response 傳回，**不存入 Preview PNG cache**。暫存 FITS 清除。前端用 raw 值在 canvas 上重畫 Stretch、Histogram、Color Bar；Zoom／Fit 僅改顯示尺寸，不要求新天區。
6. Multi-epoch 另由 `/api/epochs/search` 產生 metadata snapshot，再由 `/api/epoch-frames` 選取 2–3 個同 detector 產品；每張仍請求 `3arcmin`。`inspect_frame` 驗證原生 IMAGE／FLAGS、ICRS、單位、產品身分及 WCS 共位，雙線性重投影到共同 TAN 網格，檢查遮罩、波長、相對峰值殘差、共同有效區域及校準相容性。結果的 manifest、PNG、原生／重投影 NPZ 原子存入另一個 cache。

## 角度和像素數

Multi-epoch 明定 `SCALE=6.15` arcsec/pixel、`SIZE=29`。3 arcmin / 6.15 = 29.268 像素，解釋約 29 軸的量級；Preview 本身沒有強制 29 軸，它採用回傳 FITS 實際 shape／WCS。

64×6.15/60 = 6.56 arcmin；128×6.15/60 = 13.12 arcmin。6.5 arcmin 約 63.41 像素，13 arcmin 約 126.83 像素，不能將標籤寫成保證精確 64／128。

這是採用現有 scale 的推算，並非本輪向 IRSA 實測。原生 scale、旋轉、SIP、目標位置、切邊和像素取整都可能影響實際 shape／涵蓋區域。將來應回傳 WCS 取樣的實際天球邊界／角跨度及 shape，不只顯示 request size。裁切天區與共同輸出網格的有效覆蓋區域也須分開。

## 安全限制與尺寸假設

| 位置 | 現有限制 | 性質與本輪判定 |
|---|---|---|
| Preview download | `LIMIT=32 MiB` | 下載安全限制，未改 |
| Preview IMAGE | `MAX_IMAGE_PIXELS=262144` | 讀取工作陣列之前的像素數安全限制；不是 128 軸限制，未改 |
| Preview raw JSON | `MAX_CLIENT_PIXELS=65536`、`MAX_CLIENT_BYTES=4 MiB` | display payload 上限；超限降級 PNG，未改；4 MiB 並非整個 API response 的上限 |
| Preview FLAGS | 必須和 IMAGE shape 相符、整數型別 | 排除 bits 1,2,6,9,15,19；不能套用 epoch 的不同品質政策 |
| Preview cache | 16 MiB / 32 entries / TTL 600 s | 計算兩 PNG bytes，整組淘汰，不含 raw JSON |
| Metadata snapshot cache | 8 MiB / 32 entries | TTL 一般 3600 s、empty 300 s、partial 60 s；大 cutout 不需放進 SIA metadata cache |
| Epoch 原生 IMAGE | 2D、最小軸 2、最大軸 128 | 在讀 data 前的安全限制；FLAGS 同 shape、整數，另檢查 WCS 共位；未改 |
| Epoch FLAGS | 只允許 SOURCE／FULLSAMPLE | 其他含未知 bit 全排除；比 Preview 嚴格，未改 |
| Epoch 共同輸出 | `SIZE=29`、`SCALE=6.15` | 固定尺寸邏輯，非讀取安全上限；影響 CRPIX、indices、中心檢查、empty mask、grid metadata、WCS axes、NPZ grid header |
| Epoch frame count | API 2–3 張 | 安全／工作量限制，未改；本輪原型以兩張驗證 |
| Epoch cache | 8 MiB / 16 sequences / TTL 600 s，partial 60 s | manifest JSON + PNG + NPZ 合計、原子淘汰；不等於處理時 RAM |
| Frontend | shape／PNG natural dimensions 決定 canvas 與 axes | 沒有另設等同後端的 pixel／JSON byte 上限；信任後端 bounded display。`epochs.js` 的 `[29,29]` 僅是缺影像及 WCS 時 fallback，仍需在尺寸整合時審查 |

三個 cache 的序列化容量合計 32 MiB，並不是整個程序 RAM 上限。Python 物件、暫存陣列及回應序列化另需記憶體。現有安全像素上限雖容納更大資料，不代表 API 已授權任何尺寸。

## 離線原型與測試證據

新增 `backend/tests/cutout_size_probe.py`：用既有合成 spectral metadata 建立 IMAGE、FLAGS、ICRS TAN、WCS-WAVE 與人工星源；各尺寸／模式以獨立子程序量測，audit hook 禁止 socket DNS／連線。所有 FITS 都在 TemporaryDirectory 產生並清除，不讀真實下載 FITS 作為本輪尺寸證據。

Multi-epoch 原型在 worker 內用 scoped mock 暫時將 `epochs.SIZE` 改為 29／64／128，直接執行 production `create_frames`，結束即還原；**這不是 production 支援尺寸的實作**。獨立驗證兩張影像，其中一張 WCS 旋轉 12°，星源以同一共同天球網格定義。

通過項目：

- Preview 29、64、128 的讀取、FLAGS、NaN／±Inf、負值／零、直方圖有效樣本數、PNG 尺寸、y 翻轉、透明壞點、JSON 非有限值轉 null，以及兩 PNG cache roundtrip。
- IMAGE WCS 的實際 RA／Dec 取樣刻度與 pixel-cell 邊界核對。
- Multi-epoch 三種輸出尺寸的 WCS 重投影 closure、共同網格、相對峰值殘差、波長 lookup crosscheck、共同 normalization、NPZ 與 display 值一致、PNG、sequence cache roundtrip。Histogram 明確是**原生有效像素**，不是 aligned 有效像素；旋轉後有效像素數不同是正常結果。
- 未變更的 epoch 政策可以讀取原生 64／128，但輸出仍為 29。原型能處理 63×65、65×64；Preview 另通過 127×129、129×128，epoch 對 129 軸照舊拒絕。
- 64／128 的全 NaN、全壞點、FLAGS shape 不合、未知 BUNIT、目標位於 IMAGE 外、損壞 FITS；Preview 拒絕無有效值／錯誤 shape／越界，未知單位保留 PNG 並停用物理值控制；epoch 拒絕錯誤 shape／單位／越界，無有效影像不會標成 center valid。

新增 `frontend/tests/cutout-sizes.test.mjs`，讀取上述真實 production 函式產生的合成 JSON，重用現有 DOM mocks。29、64、128 各通過 Linear／Asinh／Log／Sqrt、正反色、每個有效像素與 Color Bar 灰階一致、遮罩透明、Histogram、窄／寬 Fit、手動 Zoom、RA／Dec 刻度位置、Preview submit 和兩影格切換；顯示操作沒有追加網路請求。

前端是 Node VM／DOM 模擬及幾何測試，**沒有新增尺寸的真實瀏覽器 raster／視覺／行動裝置效能驗收**。本輪也沒有完整涵蓋大尺寸 SIP、RA wrap、高赤緯、壓縮 FITS、不同 bit depth 和複雜查表 distortion；既有小尺寸相關回歸測試不能取代這些驗證。

## 資源量測

原始資料：`docs/cutout-size-measurements.json`。Windows 11、Python 3.12.14、NumPy 2.0.2、Astropy 6.1.7、Pillow 11.3.0。每 case 一次獨立程序，時間包含 tracemalloc 開銷，不含網路／冷啟動 import／瀏覽器；epoch 時間還包含兩張測試 FITS 的生成。不可當作正式站 latency benchmark 或容量保證。

| 尺寸／模式 | 處理秒數 | 程序 peak working set (MiB) | tracemalloc peak (MiB) | metadata JSON (KiB) | cache (KiB) |
|---|---:|---:|---:|---:|---:|
| 29 Preview | 0.804 | 85.8 | 1.64 | 40.9 | 1.06 |
| 29 Epoch ×2 | 1.707 | 89.6 | 1.36 | 52.4 | 74.2 |
| 64 Preview | 0.585 | 88.9 | 2.70 | 153.1 | 1.77 |
| 64 Epoch ×2 | 4.016 | 91.5 | 1.90 | 215.6 | 253.2 |
| 128 Preview | 1.689 | 100.3 | 6.74 | 577.2 | 3.12 |
| 128 Epoch ×2 | 6.608 | 97.7 | 4.31 | 833.5 | 917.5 |

程序 peak 是 Windows `GetProcessMemoryInfo.PeakWorkingSetSize`，含 Python／native library 基線；不是單一 cutout 的增量。原始 JSON 同時記錄處理前 peak，兩者之差也不是精確 live allocation。tracemalloc 用來補充可追蹤配置，不能取代 native-inclusive RSS。Preview cache 為兩 PNG 合計；epoch cache 含插入後 manifest 和兩影格所有 PNG／NPZ。

本合成場景背景平滑、少量星源，壓縮比偏佳，cache 數字不能當 worst case。後續須用高熵背景、密集 FLAGS、不同 dtype、最大允許 3 影格、cache 接近容量與回應序列化量測，而不提高影格上限。本輪無長時間 RSS 取樣、併發或 Render 壓力測試。

## 後續 API、前端與快取方案（尚未啟用）

Preview 可新增 `cutout_profile` enum：`small`（預設 3 arcmin）、`medium`（約 6.5 arcmin），`large`（約 13 arcmin）先拒絕。禁止自由輸入尺寸，禁止 256 以上選項。由 server allowlist 映射成角度，service 同時傳入 `build_cutout_url` 與 `render_cutout`，避免 URL 與 metadata 不一致。舊 client 不帶參數仍為 3 arcmin；`radius_deg` 保持 SIA Search Radius。加入 API 層 reject 未開放值／任意字串的測試。

回傳 `requested_cutout_arcmin`、`actual_shape_yx`、實際 WCS scale／edge footprint／角跨度；若 clipped、目標或共同區域不完整要明示。UI 可顯示「實際天區 Cutout Size」與「顯示倍率 Zoom」兩組獨立控制，選尺寸才重新請求，Zoom／Stretch 不重新裁切。說明「像素數依 FITS WCS 與邊界變動」；Small 3′／Medium 約 6.5′／Large 約 13′（未開放），不顯示保證 64×64 的文字。

Preview `ImageCache` 是隨機 key，已無 query dedup，不需為新 profile 直接提高容量；metadata 需記錄 request profile，評估接近容量時淘汰及完整 JSON 上限。任何未來以座標去重的快取 key 必須包含 profile 及 render policy。

Multi-epoch 另行設計 request 的 cutout profile 與 output grid size。把全域 `SIZE` 改為有驗證的顯式 grid spec，逐處傳遞 shape／CRPIX／center index／空 mask／metadata／NPZ／axes；偶數網格的中心在像素之間，需明定中心有效性採樣政策，不能直接沿用 `SIZE//2` 當精確 target。

其 cache selection 目前是 `(POLICY, search_id, product_ids)`；新網格／尺寸／scale 必須加入 key 並更新 policy version，否則會重用錯誤序列。維持原生 128 軸 cap；特別是 13′ 可能回 129 軸，不能只放大輸出網格就宣稱可用。原生天區對旋轉後共同方形的覆蓋、有效區域比例、邊緣透明範圍要有明確產品規則。

## 開放前仍需完成

64 Preview：完成 bounded API／UI 整合、實際 footprint metadata、真實瀏覽器驗收、大尺寸 SIP／wrap／高赤緯／不同 dtype 和高熵 cache 測試；後續取得另行授權後才做上游真實角度／shape／裁切契約驗證。本輪不連線 NASA，這部分未做。

64 Multi-epoch：另完成 grid spec 實作、偶數中心政策、cache key、coverage 門檻、現有最多 3 影格驗證及真實瀏覽器切換驗收。

128：除以上項目，還需釐清 129 軸邊界的安全處理政策、native cap 保持下的失敗 UX、較複雜 WCS 的天區覆蓋、代表性高熵資料和 cache／序列化工作記憶體。現在不建議正式開放 Large。

## 重跑

在專案根目錄依序執行：

```powershell
.\.venv\Scripts\python.exe -m backend.tests.cutout_size_probe
node --test frontend/tests/cutout-sizes.test.mjs
node frontend/tools/test.mjs
.\.venv\Scripts\python.exe -m backend.tests.run_offline
```

合成 JSON fixture 在被 gitignore 的 `backend/test-results/cutout-sizes/`；前端新增測試在 fixtures 缺少時明確 skip，因此正式驗證必須先跑 probe 並確認三個 case 沒有 skip。probe 的 assert 必須以一般 Python 執行，勿加 `-O`。

本輪回歸：前端 145/145 通過，含 3 個尺寸 case，沒有 skip；後端執行 100 tests，99 通過、1 個 live NASA 測試 skip。後端既有套件含本機既存資料 replay 和本機 clean-source server 啟動檢查，沒有下載真實 FITS，也沒有執行遠端 Render 測試。尺寸結論僅來自新增合成 probe。
