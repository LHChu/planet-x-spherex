# Phase 5.1：Render FastAPI 部署準備

本輪僅做設定與離線驗證，沒有 Commit、Push 或實際部署，也未修改科學運算、API 契約、前端與 GitHub Pages。免費方案目前只能視為低流量展示候選環境，尚未證明能穩定處理真實 NASA 工作負載。

## 部署檔案與相容性

- 根目錄 `render.yaml`：Python Web Service、Free、`/health`、自動部署 Off。
- 根目錄 `.python-version`：`3.12.14`，與本機驗證版本一致。Render 預設 Python 會變動，不能直接沿用預設；Astropy `<7`、NumPy `<2.1` 也不宜直接搭配新 Python 主次版本。
- `backend/requirements-render.txt`：保留原有 requirements 範圍，另外固定本機已驗證的 runtime 套件及相依版本。它是版本快照，沒有 wheel hashes；未驗證 Linux 全新安裝與 wheel 可取得性。日後更新應重新跑離線測試。
- `backend/start.py`：以 `python -m backend.start` 啟動。固定 `workers=1`、`reload=False`、`host=0.0.0.0`；讀取 `PORT`，本機預設 10000。`WEB_CONCURRENCY` 無法把這個入口改成多 worker。
- 原生 NumPy/BLAS 執行緒設定為 1，減少免費方案 CPU 爭用；這不等同於整個服務只有一條 thread。

工作目錄必須是 **repository 根目錄**，Render 的 Root Directory 留白。後端匯入已受 Git 管理的 `research/spherex.py`，因此不能只上傳 backend 資料夾。執行用原始碼不讀取 `research/outputs`、Windows 絕對路徑或預存 FITS；研究 CLI 與部分可選回放測試仍可使用本機 outputs，但不會在啟動時執行。

Render 在入口終止 TLS。啟動程式信任其 forwarded headers，以便產生 HTTPS artifact URL；`forwarded_allow_ips="*"` 的前提是服務只透過可信任的 Render ingress 對外。若移到其他直接公開 port 的環境，應重新限定代理來源。

## 免費方案限制與可行性

以下為 2026-11-15 查閱的官方文件，部署前應再確認帳戶 Dashboard：

| 項目 | 限制與本專案影響 |
| --- | --- |
| CPU / RAM | Free 為 0.1 CPU、512 MB。32 MiB 快取 payload 上限不代表 RSS 上限；Python 物件、JSON、Astropy、FITS 解壓縮、WCS 與回應複製均額外使用 RAM。 |
| 休眠 | 15 分鐘沒有流量會休眠，下一次請求約需一分鐘喚醒；可能先回傳 Render loading page。不能保證 API client 一定收到 JSON。 |
| 啟動 | Render start command 上限 15 分鐘；本程式啟動不查 NASA，`/health` 僅確認程式可回應，不能代表 NASA 可用。 |
| HTTP request | 官方一般 Web Service 說明允許回應最長 100 分鐘，不能解讀成免費方案的延遲保證。現有前端 API 等待 180 秒，PNG 等待 30 秒；冷啟動 + NASA 120 秒預算 + 科學運算可能超時。Uvicorn 的 5 秒 keep-alive 是閒置連線設定，並非 request 執行期限。 |
| 檔案 | 檔案系統為暫存，重啟、部署、休眠都會遺失寫入資料；Free 無 persistent disk。FITS/下載檔寫入系統 TemporaryDirectory，正常與例外路徑均清除，未使用 repository outputs。強制終止可能來不及執行 cleanup。 |
| 狀態 | 圖片、snapshot、sequence 全為 process-local RAM；重啟或休眠後 key、cursor、search_id、sequence_id 失效，需重新搜尋。 |
| 用量 | 每 workspace 每月共用 750 Free instance hours；另有 outbound bandwidth 與 build pipeline 用量。免費服務可能因異常大量對外請求而被暫停；本服務對 NASA 的請求會納入對外流量考量。 |

來源：[Free 限制](https://render.com/docs/free)、[Blueprint 資源規格](https://render.com/docs/blueprint-spec)、[部署時限](https://render.com/docs/deploys)、[HTTP 回應時限](https://render.com/docs/render-vs-heroku-comparison)、[Python 版本選擇](https://render.com/docs/python-version)、[Port binding](https://render.com/docs/web-services#port-binding)。

## 既有資源限制檢查

本輪保留以下既有政策，沒有變更科學運算：

| 範圍 | 現有限制 |
| --- | --- |
| 重工作 | preview、未快取 metadata 搜尋、frame 處理共用一把 nonblocking lock；重疊工作回 503 busy 與 Retry-After: 5。健康檢查與快取讀取仍可執行。 |
| NASA 請求 | 每個工作共享最多 16 次 HTTP 嘗試、每 URL 最多 3 次、單次 socket timeout 最多 20 秒、合作式總預算 120 秒、等待最多 15 秒。Preview 最多嘗試 10 個候選。metadata/frame 處理 429/503；既有 preview 僅重試 503。 |
| 下載 | Cutout 上限 32 MiB，SIA VOTable 上限 8 MiB。metadata 每 collection MAXREC=1000，最多兩個 collection。串流下載並檢查 deadline。 |
| 影像 | Preview IMAGE 讀取前限制 262144 pixels；傳給前端的資料最多 65536 pixels、4 MiB JSON。frame 一次 2–3 張，逐張處理；IMAGE/FLAGS 最大 128×128，輸出 grid 29×29。 |
| 快取 | PNG 最多 32 組 / 16 MiB / 600 秒；metadata 最多 32 組 / 8 MiB 序列化資料，完整 TTL 3600 秒、空結果 300 秒、部分結果 60 秒；sequence 最多 16 組 / 8 MiB，完整 TTL 600 秒、部分失敗 60 秒。FIFO 淘汰，讀寫時清除過期內容。 |

限制的邊界：120 秒並非可強制中斷 DNS、OS I/O、FITS 解碼與 CPU 計算的總 request wall-clock 上限。下載 byte cap 也不是 FITS 所有 HDU 解壓後的 RAM 上限。沒有跨請求的 NASA 速率配額、使用者配額或跨工作 cooldown；CORS 是瀏覽器來源規則，不是 API 存取控制，外部程式仍能連續呼叫。沒有新增公開 request body 大小上限，因此大量流量或巨大 JSON 仍可能耗盡資源。免費服務不適合目前直接承諾多人長期使用。

若實際看到 OOM/restart、頻繁 503、健康檢查不穩或超過 180 秒，應先停止公開推廣，再評估更多 RAM/CPU 或另期設計非同步工作、流量限制；不能單靠加長 timeout 或增加 workers 解決。

## Render 介面操作（由使用者在後續部署階段執行）

1. 確認要發布的變更已由使用者審閱並自行 Commit / Push 到 GitHub。Render 讀取遠端 branch，無法讀取本機未提交的部署檔案。
2. New → Web Service，連接 `zo4j433/planet-x-spherex`，選正確 branch、Python runtime、Free instance 與適合 region。Root Directory **留白**。
3. Build Command：`python -m pip install -r backend/requirements-render.txt`。
4. Start Command：`python -m backend.start`；Health Check Path：`/health`；Auto-Deploy：Off。
5. 依下表設定環境變數。不要加入 NASA API key 或 FITS 檔案；目前使用的公開 IRSA 請求不需要 key。
6. 最後點 Create Web Service 才會開始真正 build/deploy。本輪沒有執行這一步。也可改用 New → Blueprint 讀取根目錄 `render.yaml`；它同樣會在建立時部署，`autoDeployTrigger: off` 只停用後續自動部署。
7. 觀察 build log 的 Python 與套件版本，startup log 應只出現單一 server worker，監聽 `0.0.0.0:<PORT>`，沒有 reloader。
8. 先只檢查公開 HTTPS `/health` 回傳 `{"status":"ok"}`；確認允許與拒絕來源的 CORS preflight。這不需要 NASA。
9. 後續另行授權少量 NASA 實測：單次 Preview、metadata、2–3 張 frame，檢查 HTTPS artifact URL、記憶體尖峰、health responsiveness、耗時與快取失效。不要把未做的 NASA/Linux 實測記為通過。

| 變數 | 值 / 操作 |
| --- | --- |
| `CORS_ORIGINS` | 正式來源先規劃 `https://zo4j433.github.io`。不能填 `/planet-x-spherex/` 路徑或結尾 `/`；自訂網域時改成真實 origin。多來源以逗號分隔；正式環境不必包含 localhost。Blueprint 會要求手填。 |
| `WEB_CONCURRENCY` | `1`，入口仍明確固定單 worker。 |
| `OMP_NUM_THREADS` | `1` |
| `OPENBLAS_NUM_THREADS` | `1` |
| `MKL_NUM_THREADS` | `1` |
| `PYTHONUNBUFFERED` | `1`，即時輸出 log。 |
| `PYTHON_VERSION` | 通常不設定，使用根目錄 `.python-version` 的 3.12.14。若 Render 環境已有此變數，移除或同樣設為 `3.12.14`，因其優先於檔案。 |
| `PORT` | Render 自動提供，勿寫死；本機可自行指定。 |
| `TMPDIR` | 通常不設定，使用系統可寫入的暫存目錄；不設為 outputs 或持久儲存路徑。 |

目前 Git remote 推得的 GitHub Pages origin 尚未實際發布驗證。本輪未修改 Pages、前端 API URL 或網域設定。

## 本機重現與測試

從 repository 根目錄執行：

```powershell
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -m pip install --dry-run --no-index -r backend/requirements-render.txt
.venv/Scripts/python.exe -m backend.tests.run_offline

$env:PORT = '10000'
$env:CORS_ORIGINS = 'https://zo4j433.github.io'
.venv/Scripts/python.exe -m backend.start
# 另一個 Terminal，只測 health，不觸發 NASA：
Invoke-RestMethod http://127.0.0.1:10000/health
```

新的 `run_offline` 強制 `SPHEREX_LIVE=0`，拒絕外部 DNS/socket 連線，若有嘗試即使被程式捕捉仍會令整體失敗。Loopback 供本機 HTTP 與 Windows asyncio 使用。既有真實資料回放只讀取已存在的可選 fixtures，不下載；缺少 fixtures 的測試會 skip。

`test_deployment.py` 驗證 PORT、單 worker、不 reload、正式 CORS、HTTPS artifact URL、暫存清理；另把 runtime 原始碼複製至無 outputs/FITS 的暫存目錄，啟動真正 Uvicorn，測 `/health` 與 forwarded HTTPS redirect。測得的 Windows 啟動與 idle RSS 僅代表本機健康檢查，不代表 Render 冷啟動或科學運算尖峰。

驗證結果與未驗證項目見 [Phase 5.1 報告](phase5-1-report.md)。
