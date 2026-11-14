# Phase 4.3 metadata API 實作與離線驗證

日期：2026-11-14。

已閱讀 Phase 4.1／4.2 的報告、研究程式、測試及摘要，沿用 Wide DR1+QR3 查詢、obs_id 曝光分組、球面 footprint 預篩及 Astropy UTC 換算。新增 `POST /api/epochs/search`，實作細節及請求／回應契約見 [README](README.md#phase-43多時期-metadata-api)。

程式位於 `app/epochs.py`，endpoint 與嚴格輸入模型位於 `app/main.py`。未變更 preview handler、研究共用查詢／轉圖函式或 PNG cache。新搜尋與 preview 共用既有工作鎖，snapshot cache 另外有 TTL／筆數／位元組上限。

## 離線驗證

```powershell
$env:SPHEREX_LIVE = '0'
.\research\.venv\Scripts\python.exe -m unittest discover -s backend/tests
```

最終結果：51 項測試，50 通過、1 項 opt-in live NASA 測試跳過。新 `test_epochs.py` 含 17 項測試，合成 VOTable 的核心測試不依賴本機研究檔。另有本機 Phase 4.1 XML 回放，已實際重現 **428 個產品／217 次曝光／215 個 metadata 中心覆蓋曝光**。既有 Phase 1 FITS／PNG 離線回放及 preview 輸入、錯誤、鎖、快取、WCS／清理回歸皆通過。

覆蓋：兩來源合併、不同 detector 同曝光、微小時間差不拆曝光、URL 去重與版本保留、未知時間與 obs_id、時間區間相交、嚴格輸入與白名單、未知／在外 footprint、OVERFLOW、單來源失敗、全部失敗／逾時、無效 XML／來源 URL、穩定產品 ID、曝光分頁、cursor 簽章／查詢綁定／到期／重啟、快取命中零新請求、TTL／容量淘汰、共享鎖、429／503／Retry-After、重試／請求數／deadline 上限。

補測容量淘汰時，最初設定的測試容量仍放得下兩筆測試 snapshot；將 fixture 容量調整為能放一筆的 500 bytes 後，淘汰測試與全套回歸通過。套件另輸出既有 Starlette/httpx deprecation warning，本輪未更新依賴。

## 範圍與限制

- 本輪沒有連線 NASA，沒有下載新 FITS、實作影格／動畫／前端時間軸，也沒有 Commit、Push 或部署。
- 目標位置波長、FITS DATE-OBS、WCS、品質與 alignment 均不從 metadata 推定；API 明確回傳未知／未驗證。
- 單一來源最多 1000 筆，OVERFLOW 不會無界補查；可縮小時間範圍後重查。部分結果完整揭露且只快取 60 秒。
- 不同 URL／版本保守保留，不猜測 publisher DID 鏡像或自動挑選最新校準；未知版本與未檢查 header 的狀態分開。
- 快取僅於單 worker 程序有效；8 MiB 是序列化 metadata 大小限制，未做 512 MB 容器或實際服務負載驗證。重啟／淘汰需重新查詢。
- metadata 的 429／503 cooldown 於同次搜尋跨 collection 共用；跨 endpoint／跨請求持久 cooldown 尚未實作，preview 的既有 retry 政策不變。
