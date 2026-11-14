# Phase 4.4：最小多時期影格 API

日期：2026-11-14。已閱讀 Phase 4.1／4.2 報告、研究程式／測試與 metadata 產物，Phase 4.3 報告及現有 backend 架構。僅完成本輪 API，未進入 Phase 4.5。

## 實作結果

- 新增 `POST /api/epoch-frames`，嚴格接受 `search_id` 與依序指定的 2～3 個不同 `product_id`。所有產品必須存在於尚未過期的伺服器搜尋 snapshot，且 detector 相同。拒絕額外 URL、座標或任意來源；重新核對來源 URL 白名單及 SHA-256 產品識別。不跟隨 HTTP redirect，避免 SSRF 與未計數下載。
- `app/epoch_frames.py` 負責逐張處理、身分／單位／品質核對、原始陣列保留、共同亮度政策與整組快取；`app/frame_math.py` 沿用 Phase 4.2 已驗證的雙線性插值、FLAGS OR、alternate W 波長插值、星點 centroid／殘差函式，另外防護非有限座標的 FLAGS 傳播。
- 每張對齊至搜尋中心的固定 29×29 ICRS TAN 格網、6.15 arcsec/pixel。保留 OBSID、UTC DATE-OBS（缺失則明示 SIA fallback）、detector、來源與版本、目標波長／bandwidth、旗標定義、校準 HISTORY、來源 FITS hash。
- PNG 以 alpha=0 呈現缺資料／無效值；另提供 NPZ，保留原始 IMAGE 數值／NaN／dtype、完整 FLAGS bit 值、原生品質 mask 與重投影 IMAGE／mask／有效權重／幾何權重／FLAGS OR。原始 FITS 不修改，不將 NaN 改成有效零值。
- WCS 數學閉合與星點對齊品質分開。所有成功影格兩兩比較，至少 3 對星點、median <0.5 pixel、maximum <1 pixel；不足為 unverified、超標為 failed，不自行剔除離群點或擬合偏移來宣稱成功。
- 所有已選影格皆成功且目標波長、校準、中心／對齊品質合格，才回 `comparable_visualization`，使用共同有效區的合併 p1/p99 + asinh(10x)。其他情況明確回 `observation_browse` 並標示逐張 stretch。`photometric_series=false`，不宣稱為光變序列。
- 單張失敗仍保留原順序與 error，不補其他曝光；HTTP 200 可包含部分或全部失敗，必須查看 counts、每個 slot 與 alignment。`complete` 僅表示全部指定影格完成重投影。
- 與 preview／metadata search 共用工作鎖，忙碌回 503。NASA 每組最多 16 次嘗試、120 秒協作期限、20 秒 socket 上限、每 URL 三次，429／503 遵守 Retry-After，跨 slot 不跳過等待。32 MiB 單檔下載上限、IMAGE／FLAGS 每軸 ≤128、波長表 ≤1 MiB，逐張關閉 HDU，不展開 EPSF。
- manifest、PNG 與 NPZ 整組快取／到期／淘汰：新增上限 8 MiB／16 組；與既有 PNG、metadata cache 合計最多 32 MiB 序列化 payload。全組重投影成功 TTL 600 秒，含失敗 slot 為 60 秒。完全相同選取命中不再查 NASA。不存在的 artifact 回 404，過期 search_id 回 410。

API 請求、完整回應語意、PowerShell 實際呼叫與 NPZ 讀取方式見 [README Phase 4.4](README.md#phase-44多時期影格-api)。主要檔案為 `app/main.py`、`app/epoch_frames.py`、`app/frame_math.py`；`app/epochs.py` 僅新增內部 snapshot 讀取方法。既有 preview／epochs search handler 與對外契約未更動。

## 離線測試結果

```powershell
$env:SPHEREX_LIVE = '0'
.\research\.venv\Scripts\python.exe -m unittest backend.tests.test_epoch_frames -v
.\research\.venv\Scripts\python.exe -m unittest discover -s backend/tests
```

最終 backend 全套 **88 項，87 通過、1 項 opt-in live NASA 測試跳過**；執行時間約 12.30 秒。新 `test_epoch_frames.py` 共 20 項，核心使用合成 FITS，不依賴研究輸出；另有 optional 本機 Phase 4.2 真實 FITS 回放，此次確實執行且通過。全套包含既有 preview／epochs search 回歸。

新測試覆蓋：

- 固定 WCS 中心／方向、旋轉合成星點重投影、IMAGE／FLAGS WCS 不符、過大陣列與錯誤 OBSID 拒絕。
- NaN／壞像素保留、SOURCE 資訊位接受、FLAGS OR、mask／PNG 透明度、原始 NPZ 數值；相容與不相容波長／bandwidth、波長求值失敗、未知校準、星點不足／超標及中心品質拒絕。
- 輸入筆數／重複／格式／額外欄位、其他產品與 search 綁定、detector 不符、任意 URL 與 redirect 拒絕。
- 共用鎖 503／Retry-After、HTTP 503 重試耗盡與部分成功、429／503 長 Retry-After 阻止後續下載、request limit／deadline、下載 bytes／timeout 清理。
- search TTL／淘汰／重啟、序列 TTL／整組淘汰／容量不足、同組快取命中零新請求、部分失敗保留原 slot／原因且不替換。

真實 FITS 回放重用 4 月、11 月、12 月既有檔案，沒有新增 SIA 或 NASA 下載：

| 情境 | 驗證結果 |
|---|---|
| 11 月／12 月 D1 | 目標波長相容、星點殘差通過，mode=comparable_visualization |
| 共同有效區 | 650 pixels，與 Phase 4.2 相同 |
| 共用亮度範圍 | lo≈0.237902、hi≈5.704328 MJy/sr，與 Phase 4.2 相同 |
| 11 月目標波長 | 約 0.861452 µm，重現研究值 |
| 加入 4 月影格 | mode=observation_browse；12 月相對 4 月殘差超標，alignment=failed |
| 原始 FITS 完整性 | 三個來源檔案執行前後 SHA-256 相同 |

同一 Windows 本機離線全套程序的 peak working set 為 **109,092,864 bytes（約 104.0 MiB）**，包含既有 preview 回歸；不是 Render／512 MB 容器測量。`git diff --check` 通過。既有 Starlette/httpx deprecation warning、測試 FITS BLANK warning 仍可見；alternate W 建構也有 Astropy SIP 提示，實際交叉核對明確呼叫不套 SIP 的 `wcs_pix2world` 核心，真實 FITS 回放數值通過。

## 尚未驗證與界限

- 本輪未連線 NASA、未啟動本機網站做 live 實測。真實 HTTP 服務的最新行為、redirect 情形與網路耗時尚未驗證；遇 redirect 會明確使該 slot 失敗，不自動放寬來源。
- 未在 Render 512 MB 容器、長時間連續請求或多 worker 環境測量。快取的 bytes 上限不等於 Python RSS；目前僅支援單 worker 記憶體快取與鎖，服務重啟需重搜。
- 真實研究回放僅 D1、小視場與上述日期，未驗證 D2～D6 的實際多時期 FITS；其未知格式會保守標示失敗／不可比較，不猜測成功。
- 沒有跨請求／跨 endpoint 的持久 NASA cooldown；同次序列內跨 slot 共用預算與等待，既有 preview retry 行為不變。不同選取與到期後重試仍會發出新請求。
- 共同格網仍可能缺角；參考星點診斷不等於外部星表 astrometry 認證。波長僅核對目標位置，沒有證明整個視場波段一致。
- 保守校準與 FLAGS 政策是版本化工程篩選，不是科學等價證明。未扣 ZODI／背景、匹配 PSF、傳播 variance 或提供測光／光變曲線／移動天體判定。
- 前端、時間軸、動畫、英文介面、WCS 座標軸、color bar、Gaia 與 Phase 4.5 均未實作。沒有 Commit、Push 或部署。
