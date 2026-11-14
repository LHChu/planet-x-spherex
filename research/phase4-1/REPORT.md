# Phase 4.1：多時期資料探索與設計

調查日期：2026-11-14。座標：ICRS RA=127.69444°、Dec=−39.17760°；搜尋半徑 0.01°。本文件是調查與設計，沒有實作動畫、API 或前端變更。

## 1. 結論與證據範圍

這個座標確實有多時期 Spectral Image 候選資料。建議未來獨立新增「metadata 時間軸 → 使用者挑選少量影格 → WCS 對齊」流程，DR1 與 QR3 可合併探索，但每張影像須保留來源與處理版本，不能把 detector 切換當成時間變化。

| SIA collection | metadata 筆數 | 不同 obs_id | footprint 含目標的筆數／obs_id | 開始至結束 UTC（由 SIA MJD 換算，約值） |
|---|---:|---:|---:|---|
| spherex_dr1 | 414 | 210 | 410／208 | 2025-04-25 14:00:26 ～ 2026-05-14 06:52:22 |
| spherex_qr3 | 14 | 7 | 14／7 | 2026-05-21 03:27:20 ～ 05:13:35 |
| 合計 | 428 | 217 | 424／215 | 56 個有候選觀測的 UTC 日期 |

兩份新查詢均為 `QUERY_STATUS=OK`、`MAXREC=1000`，不是截斷的 50 筆。本次兩個 collection 的查詢範圍內 metadata 完整，不代表未來不再新增資料，也不涵蓋 `_deep` 或 cube collection。以上是 metadata 候選數，**不是已成功下載並可播放的影格數**。目前只重用 Phase 1 已成功的 1 張 Cutout 紀錄；其餘 WCS、品質遮罩、目標位置波長與有效像素尚未逐張驗證。

先讀取 `README.md`、`backend/app/` 全部模組、`research/spherex.py` 及前端 HTML／JS／CSS／設定，優先重用 `research/outputs/spherex_dr1.xml`、`metadata.json`。舊 XML 的 50 筆狀態是 `OVERFLOW`，故只補查兩次 SIA2 metadata：

```text
https://irsa.ipac.caltech.edu/SIA?COLLECTION=spherex_dr1&POS=CIRCLE+127.69444+-39.17760+0.01&MAXREC=1000
https://irsa.ipac.caltech.edu/SIA?COLLECTION=spherex_qr3&POS=CIRCLE+127.69444+-39.17760+0.01&MAXREC=1000
```

共約 0.95 MB XML，**新下載 FITS：0 張**。使用同一 IRSA SIA endpoint、collection、POS circle、VOTable 欄位語意，未更動正式 `query_images()`。因本機既有 Python 3.11 venv 指向已不存在的直譯器，離線整理改用 PowerShell XML parser 與 Node；未重建環境、未聲稱重新執行過 Python FITS/WCS 檢查。

## 2. 既有架構與設計影響

- `research/spherex.py::query_images()`：DR1 優先，有結果即停止，QR3 只是 fallback；`MAXREC=50`。適用單張預覽選候選，不適用完整時間序列。
- `backend/app/candidates.py`：以球面 footprint margin 排序；相交候選仍須 Cutout 的主 celestial WCS 與中心 finite-pixel 檢查。
- `service.py`：依序下載固定 3 arcmin Cutout，第一張成功即回傳。`render_cutout()` 使用 IMAGE 主 WCS（TAN-SIP）、原 detector 方向、垂直翻轉，以及每張各自 p1/p99 + asinh。直接連續播放既有 PNG 會有方向漂移與亮度閃爍。
- `main.py`：`POST /api/preview` 使用單一處理鎖；`cache.py` 只存黑白 PNG pair（最多 32 組／16 MiB／600 秒）。前端只有單張 result 狀態，沒有 epochs、影格生命週期或對齊邏輯。
- `nasa_requests.py`：120 秒共用 deadline、每次 socket 最多 20 秒、最多 16 次請求、10 個候選、每 URL 最多 3 次嘗試；目前只對 503 退避。這些是本專案限制，並非 NASA 公告配額。

未來新流程應另設模組及 endpoint，保持 `/api/preview` 的請求／回應與現有影像路徑相容。本輪沒有修改這些程式。

## 3. 時間、波段與重複資料

### 3.1 metadata 整理

逐筆資料位於 `../outputs/phase4-1/rows.json`，包含 `obs_id`、`t_min`、`t_max`、換算 UTC、`date_obs`、detector、`energy_bandpassname`、`em_min`、`em_max`、`access_url`、處理版本／日期、footprint 判定與既有 WCS 驗證來源。曝光分組在 `epochs.json`，彙總與 XML SHA-256 在 `summary.json`。

| 欄位 | 調查結果與處理原則 |
|---|---|
| obs_id | 代表曝光／pointing 識別，不含 detector；同 obs_id 的 D1 與 D4 是不同產品，不是兩個時期 |
| t_min／t_max | SIA 單位為 MJD 日；保留原值。不能用發布日期或檔案處理日期替代 |
| DATE-OBS | 這兩份 SIA **沒有此欄位**。只從既有 FITS IMAGE header 得到 1 筆，其餘明確為 null，不把換算 UTC 假裝為 header |
| detector | 從 energy_bandpassname 的 SPHEREx-D1～D6 推導；未來下載時核對 FITS DETECTOR |
| em_min／em_max | SIA 單位公尺；是整個 detector 影像的波長覆蓋範圍，不能當作指定座標的實際窄波段 |
| access_url | 保留原始來源作溯源；未來客戶端只能提交伺服器產生的 product_id，不能提交任意 URL 讓後端下載 |

| Detector | energy_bandpassname | DR1／QR3 筆數 | footprint 含目標 | SIA em_min～em_max（µm） |
|---|---|---:|---:|---:|
| D1 | SPHEREx-D1 | 50／7 | 56 | 0.74550～1.11670 |
| D2 | SPHEREx-D2 | 101／0 | 98 | 1.10330～1.64990 |
| D3 | SPHEREx-D3 | 59／0 | 59 | 1.63010～2.43460 |
| D4 | SPHEREx-D4 | 46／7 | 53 | 2.40270～3.84730 |
| D5 | SPHEREx-D5 | 100／0 | 100 | 3.81130～4.43000 |
| D6 | SPHEREx-D6 | 58／0 | 58 | 4.41150～5.00960 |

所有 metadata `s_pixel_scale=6.15 arcsec/pixel`，母影像為 2040×2040。波長數字採實際 SIA 值，與官方文件的概略 detector 範圍並非完全相同。

D1 可作第一個探索預設：footprint 含目標的 56 筆中，2025-04 有 4 筆、05 有 19 筆、11 有 19 筆、12 有 7 筆，2026-05 的 QR3 有 7 筆。這是探索涵蓋，不保證 56 筆能形成同波長科學比較序列。

### 3.2 指定座標的時間例子

| obs_id | detector | t_min／t_max（MJD） | SIA 開始 UTC（約） |
|---|---|---|---|
| 2025W18_1B_0162_1 | D1 | 60794.593497／60794.594829 | 2025-04-29 14:14:38.140 |
| 2025W18_1B_0162_2 | D1 | 60794.594989／60794.596321 | 2025-04-29 14:16:47.049 |
| 2025W18_1B_0162_3 | D1 | 60794.596481／60794.597814 | 2025-04-29 14:18:55.958 |
| 2026W21_1A_0480_1 | D1、D4 | 61181.143987／61181.145320 | 2026-05-21 03:27:20.476 |
| 2026W21_1A_0491_3 | D1、D4 | 61181.216433／61181.217765 | 2026-05-21 05:11:39.811 |

QR3 的七次開始時間（UTC，秒四捨五入）：03:27:20、03:29:29、03:31:38、03:33:47、05:07:22、05:09:31、05:11:40，全部在 2026-05-21；並沒有本座標的 QR3 六波段完整矩陣。

Phase 1 已成功的 D1 `2025W18_1B_0162_3`：`DATE-OBS=2025-04-29T14:18:55.983`、`MJD-OBS=60794.596481285`，29×29 Cutout，目標像素約 (14.328,14.306)，BUNIT=`MJy / sr`。SIA 六位小數 MJD 的量化間距約 0.0864 秒，因此與 header 的約 0.025 秒差異不足以認定資料衝突。未來正式時間換算使用 Astropy Time 並保留 `time_source`／`time_scale`。

### 3.3 去重與曝光分組規則

本次 428 筆中，相同 access_url 重複數=0，相同 `(obs_id, detector)` 重複數=0，DR1／QR3 的 obs_id 交集=0。不同 detector 的 428 個產品對應 217 次曝光。配對分布：D1+D4 共 53 次、D2+D5 共 100 次、D3+D6 共 58 次，其餘只有 D1 的 4 次、只有 D2 的 1 次、只有 D3 的 1 次。

若按 `(t_min,t_max)` 完全相等分組會得到 **221** 組：4 次曝光的 detector 時間端點相差 0.000001 日（約 0.0864 秒）。應以 obs_id 為曝光主鍵、保留每個產品時間，時間容差只作一致性檢查；無 obs_id 時標示無法確認，不能僅憑相近時間合併。

未來去重分三層：

1. 同一實體 URL／publisher DID 的相同記錄：合併來源紀錄，勿把 on-prem/cloud 鏡像當新曝光；URL 正規化不可任意移除會影響產品內容的參數。
2. `(obs_id, detector, product_type)` 相同但版本不同：屬重新處理，選一個經確認相容的版本，記錄 alternatives／superseded_by。相同曝光不同 detector 必須保留。
3. `obs_id` 不同：保留不同曝光，即使同日、同 detector 或指向相近；日級 UI 分組不能抹去原始時間點。

四筆 footprint 不含目標：`2025W18_2B_0529_4/D2`、`2025W19_2B_0293_4/D2`、`2025W45_1A_0228_1/D1`、`2025W46_2A_0288_2/D2`，距邊界約 −7.01、−8.28、−24.65、−2.09 arcsec。它們與半徑 36 arcsec 搜尋圓相交仍可被回傳。這是 metadata 預篩，不能代替完整 3 arcmin 視窗的 WCS／有效像素檢查；中心在內也可能缺角或含壞像素。

## 4. DR1 與 QR3 合併政策

IRSA 2026-11-12 的[資料發布說明](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-releases/)指出，DR1 為 Survey 1、2 的重新處理，使用與 QR3 相同改良 pipeline／calibrations；QR3 為 Survey 3、4，兩者共同取代 QR2。[資料存取文件](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/)亦建議同時搜尋兩者取得現行 Spectral Images。因此推薦**合併 metadata 查詢，分別回報狀態**；不沿用「DR1 非空就不查 QR3」的單張策略。

本次全部檔案產品版本為 v27。DR1 的處理日期為 2026 年第 196～247 日中的 13 個日期；QR3 為 2026-268。一筆 DR1 路徑使用 `l2b_retry-v27-2026-197`，解析器不能只接受 `l2b-v…`。`v27` 是產品版本，Phase 1 PRIMARY header 的 `VERSION=7.0.5` 是 pipeline 軟體版本，兩者不能混用。

處理日期不同不等於校準不相容；同 v27 也不能證明所有校準檔逐一相同。未來少量下載時核對 header VERSION、HISTORY 校準 provenance、BUNIT、WCS 與 flags；metadata 不足時標示 `calibration_status=release_compatible_header_unverified`。跨 release 真有同曝光時按已確認的校準政策選擇，不能一律 QR3 優先或只看檔名日期最新。遇不明版本隔離為另一組，不混入共同正規化。

MVP 預設只查 Wide Survey 的兩個 collection；`_deep` 是另一個明確選項，cube 是跨曝光合成產品，不能當成另一個單次曝光時間點。QR3 會持續加入資料，應顯示查詢時間；SIA ingest 亦可能有延遲，不把「未回傳」解讀為「未觀測」。

## 5. 未來 API 與前端時間軸契約（提案，尚未實作）

第一層 `POST /api/epochs/search` 只查 metadata。請求包含既有 `ra/dec/radius_deg`，可選 `collections`（白名單）、`detectors`、`time_range_mjd`、`limit`。座標沿用既有邊界。上游 `MAXREC` 與 API 分頁 limit 分離；先取得有界 metadata snapshot，再以穩定 `(t_min,obs_id,detector,product_id)` 排序提供 cursor。SIA 不假設存在 OFFSET 分頁。

回應結構示意如下；省略號不屬於實際 JSON，數字為本次調查統計。products 清單內保留所有產品，而不是只放一張最佳預覽：

```json
{
  "schema_version": "1.0",
  "search_id": "opaque-snapshot-id",
  "query": {"ra":127.69444,"dec":-39.17760,"radius_deg":0.01},
  "time_scale": "utc",
  "collections": [
    {"name":"spherex_dr1","status":"ok","returned_rows":414,"truncated":false},
    {"name":"spherex_qr3","status":"ok","returned_rows":14,"truncated":false}
  ],
  "complete": true,
  "counts": {"products":428,"exposures":217,"metadata_center_covered_exposures":215},
  "pagination": {"next_cursor":null},
  "epochs": [
    {
      "epoch_id":"2025W18_1B_0162_3",
      "obs_id":"2025W18_1B_0162_3",
      "start_mjd":60794.596481,
      "end_mjd":60794.597814,
      "start_utc":"2025-04-29T14:18:55.958Z",
      "time_source":"sia",
      "product_ids":["opaque-product-id"]
    }
  ],
  "products": [
    {
      "product_id":"opaque-product-id",
      "epoch_id":"2025W18_1B_0162_3",
      "obs_collection":"spherex_dr1",
      "detector":1,
      "energy_bandpassname":"SPHEREx-D1",
      "t_min":60794.596481,
      "t_max":60794.597814,
      "date_obs":null,
      "date_obs_source":null,
      "em_min":7.455e-7,
      "em_max":1.1167e-6,
      "em_unit":"m",
      "target_wavelength_um":null,
      "target_bandwidth_um":null,
      "target_wavelength_status":"not_evaluated",
      "access_url":"validated IRSA source URL",
      "processing":{"flavor":"l2b","product_version":"27","processing_date":"2026-196","pipeline_software_version":null},
      "calibration_status":"release_compatible_header_unverified",
      "coverage":{"center":"metadata_contains_target","wcs_verified":false,"valid_fraction":null},
      "native_pixel_scale_arcsec":6.15,
      "frame_status":"not_requested",
      "image_url":null,
      "warnings":[]
    }
  ],
  "warnings":[]
}
```

這是一般未下載情境的 schema 範例；本次研究輸出另外重用了 Phase 1 的 DATE-OBS，正式新 search 不應假定有那些本機紀錄。`queried_at`、`expires_at`、每 collection 的錯誤／請求數與 `truncated`、`superseded_product_ids` 亦納入正式契約。單一 collection 失敗時可回傳另一份資料，但必須 `complete=false`、來源狀態為 error，不能把失敗當成零筆；全部失敗回既有風格的 upstream error。`OVERFLOW` 時標示 partial、提示縮小時間範圍，不默默顯示為完整覆蓋；若以 TIME 分段補查，要去除區間邊界重複並限制段數與請求數。[IRSA SIA2 文件](https://irsa.ipac.caltech.edu/ibe/sia.html)定義 TIME 使用 MJD，BAND 是覆蓋相交條件，不能保證目標位置同波長。

第二層未來另設 `POST /api/epoch-frames`：傳 `search_id`、最多 8 個 product_id、固定 grid 設定及 display policy，只接受 snapshot 中白名單來源，按序處理。回傳 `sequence_id`、`grid`、`normalization`、每個已選產品的 frame 結果、計數與 `expires_at`；可重用 PNG serving 形式，但不改 preview 回應。失敗也保留該 slot 與 `reason_code`，不會拿另一曝光替補而不告知。

時間軸需要：epoch_id／product_id、UTC label、數值 MJD／midpoint 供排序與間隔、detector 與目標波長狀態、來源 release／版本、coverage／quality／frame status、image URL／到期時間、失敗原因與時間缺口。先顯示觀測日期群組，展開看個別曝光；未來播放採等間距索引、同步顯示真實 Δt，明確告知非等時間採樣。波段選單與時間游標獨立；切換 detector 重新建立可用影格清單，不能偷偷補不同波段。

## 6. 影像對齊、亮度與缺失影格

| 問題 | 未來處理方案／本輪驗證界限 |
|---|---|
| WCS 方向、偏移、畸變 | 保留既有 IMAGE 主 celestial TAN-SIP；alternate A 只作母像素診斷，W 是波長。將每張重新投影到同一 ICRS TAN grid：相同 RA/Dec 中心、北上東左、6.15 arcsec/pixel、29×29（約 178.35 arcsec）。顯示視窗約 3 arcmin；若需插值支撐像素，另取小邊界且限尺寸，不假定原 3arcmin Cutout 的角落完整 |
| 像素尺度 | metadata 全為 6.15，但相同尺度不代表像素格點、轉角與 SIP 一致。既有 IMAGE 的 CDELT1/2=1，尺度資訊在 PC 矩陣，不能只讀 CDELT 就認定 1°/pixel。正式檢查 local WCS Jacobian、目標 pixel、參考恆星殘差；本輪未驗證多張影像配準精度 |
| 重採樣 | 小輸出格點可採逐張雙線性插值作視覺 MVP，回傳 footprint／有效權重；FLAGS 用 nearest 或保守旗標傳播。不得用 PNG resize 取代 WCS。此插值不是精密光度量測流程；是否採用 reproject 套件需在下一階段評估依賴與 RSS |
| 真正的波長一致性 | SPHEREx LVF 的波長隨 detector 像素改變；用 WCS-WAVE 在目標像素求波長與 bandwidth，保留每張值，再依目標 bandwidth 制定匹配容差。若無至少 2 張匹配影格，只顯示標有波長的觀測瀏覽，不能宣稱同波段亮度變化。精密分析需額外 CWAVE／CBAND 校準產品，MVP 不下載它們 |
| 亮度與背景 | 同一經波長確認的序列，先排除無效／嚴重旗標像素，在有共同覆蓋的區域統計全序列共同 p1/p99 + asinh；將同一 lo/hi、單位與方法套用每張，不沿用逐張 stretch。未知／不相容校準不能共用。保留原 IMAGE，另可選局部背景扣除並回報數值，不能把背景漂移當光變 |
| ZODI／PSF | IMAGE 並未扣 zodiacal light，背景與 PSF 變動仍可造成假訊號；MVP 是視覺探索，不提供光變曲線、差分或 Planet X 偵測結論。日後定量比較才做背景模型、PSF 匹配與不確定度傳播 |
| 缺失影格 | 分開記錄未觀測／該 detector 無資料、中心不覆蓋、波長不匹配、品質拒絕、下載失敗、超過預算與快取到期。NaN／無覆蓋用 mask，不填成有效黑色。缺 detector 不複製鄰近影格；缺數月觀測不插值成假曝光 |

[IRSA Data Products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)說明 LVF、IMAGE／FLAGS／VARIANCE／ZODI／WCS-WAVE 與校準產品的不同用途。以上是後續設計與必要驗證，不是本輪已證實多張 FITS 可配準或同波長。

## 7. Render 與 NASA 請求／快取預算

[Render 定價](https://render.com/pricing)目前 Free web service 為 512 MB RAM；[免費方案文件](https://render.com/docs/free)指出閒置 15 分鐘休眠，重啟／休眠會遺失記憶體與暫存檔，且不能附加 persistent disk。規劃以單 worker、單一影像處理工作為基礎，與 preview 共用資源仲裁，避免新增 endpoint 繞過原鎖。

- metadata search：先查兩個 Wide collections，各最多 1000 筆、每份維持現有 8 MiB 上限；只保留必要欄位。若超出，不在免費服務無界拆分查詢。metadata TTL 建議 1 小時、空結果 5 分鐘；容量上限建議 8 MiB、最多 32 個查詢，兩者先到先淘汰。
- cache key：精確正規化的 RA/Dec、radius、collections、時間範圍、filters、版本政策與 schema version；不任意四捨五入造成邊界共用錯誤。相同查詢／影格同時請求合併工作。明示 snapshot 與到期，避免混入查詢後的新 ingestion。
- rendering：MVP 最多 8 張，逐張 3 arcmin Cutout，不下載 2040×2040 全圖，不在記憶體堆疊完整 FITS。沿用 32 MiB 下載上限不是 RAM 保證；Cutout 還可能帶較大的 PSF/ePSF HDU。只解開需要的 IMAGE／FLAGS 與波長資訊，不讀取所有 PSF；記錄峰值 RSS。
- PNG 維持約 16 MiB 有界快取，metadata 另有上限；新增資料與既有 cache 合計計算。小型 float32 輸出影格可以暫存供共同 stretch，但不得保留所有 HDU 物件。建議完成階段驗證峰值 RSS <350 MiB；這是初始工程驗收目標，尚未量測，也不是宣稱已適用 512 MB。
- NASA host-wide 預算：每個有界操作仍最多 16 次上游嘗試／120 秒；初始 2 次 metadata + 8 張 Cutout 在無重試時共 10 次。重試會消耗預算，耗盡時回 partial slots，不保證全數成功。保留 20 秒 socket 上限、Retry-After、退避；後續新流程補上 429 處理及跨 endpoint 共用 cooldown，不擅自改動現有 preview。
- 快取命中不查 NASA；序列 PNG key 應含產品版本、grid、波長政策及**整組 normalization id**。共同 stretch 的影格不能只按 product_id 共用。切換黑白模式、拖時間軸與播放都只用已載入影格，零 NASA 呼叫。
- 不對每次播放定時重新搜尋。host cooldown／錯誤短期快取阻止反覆點擊轟炸；前端 abort 不代表後端已停止，應維持忙碌狀態／明確手動重試。免費方案不依賴會跨休眠存活的背景任務；需持久佇列時另做架構決策。

本次查閱 IRSA 文件未找到可直接引用的固定「每分鐘 N 次」SIA／Cutout 配額，不捏造數字，也不套用 api.nasa.gov DEMO_KEY 的限制。既有 run.json 已有 503 紀錄；官方[一般問題](https://irsa.ipac.caltech.edu/docs/knowledgebase/general.html)也提醒大量下載會影響其他使用者。本方案以保守的本地預算及上游回應為準。

## 8. 推薦 MVP 與進入後續階段的條件

推薦 MVP 為「兩資料集 metadata 時間軸 + 單 detector、最多 8 張、可驗證的對齊觀測瀏覽」。預設 D1、以時間分布取樣而非直接取前 8 筆；先列候選與波長未知狀態，使用者確定選擇後才取少量 Cutout。下載後若能形成至少 2 張目標波長相容的影格，才開放共同 stretch 的可比序列；否則清楚標示不同波長的觀測瀏覽，或提示沒有可比較序列。前端日後才加入上一張／下一張、slider、播放／暫停與速度，使用本地快取影格。

不納入 MVP：六 detector 混播、影格補值、完整 102-channel cube、整片天區批次下載、光變量測、影像差分、移動天體辨識、伺服器產生 GIF／影片或持久背景佇列。

後續實作前需滿足：

1. metadata 分組能重現本次 428 產品／217 曝光，保留 detector、版本與缺失值；OVERFLOW、單一來源失敗不會被隱藏。
2. 用少量不同日期 Cutout 驗證主 WCS、中心有效像素、目標波長與共同格點；參考恆星殘差可訂初始 <0.5 輸出 pixel，失敗就標示未對齊，不宣稱可用動畫。
3. 模擬波段缺失、503／429、Retry-After、預算用盡、快取淘汰／重啟，確保保留 slot 與錯誤原因、不中途換曝光。
4. 在 512 MB 等效環境量測 RSS／處理時間；確認重複查詢及播放零新增 NASA 請求；回歸驗證既有 `/api/preview`。

本輪停在 Phase 4.1，沒有進入上述實作或下載驗證。

## 9. 產物與重現方式

- 本報告與 `extract.ps1`、`summarize.mjs` 是獨立研究檔，非正式程式碼。
- `../outputs/phase4-1/` 內原始兩份 XML、`input.json`（完整欄位）、`rows.json`（整理後逐筆）、`epochs.json`（逐曝光）、`summary.json`（統計與 hash）均只保存在本機，沿用既有 `research/outputs/` Git ignore。
- `snapshot-summary.json` 保存本次統計與原始 XML hash，方便報告離開本機後仍可核對摘要；完整下載資料未納入正式碼。
- 重現離線整理：在專案根目錄執行 `& research/phase4-1/extract.ps1`。需要上述既有輸出與新 XML；腳本本身**不連 NASA**，不下載任何 FITS。
- `summarize.mjs` 的球面凸多邊形預篩依照 `candidates.py` 演算法轉寫，僅供研究；UTC 換算為本批日期的視覺約值，未來正式服務仍採 Astropy。

未 Commit、Push 或部署。未改動 Phase 1～3 正式程式碼；未重新呼叫 `/api/preview`，避免為本輪調查額外下載 FITS。
