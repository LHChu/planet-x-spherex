# Phase 5.1 部署準備驗證報告

日期：2026-11-15。範圍為本機 Windows、Python 3.12.14 的部署準備與離線驗證。

## 變更

新增根目錄 `.python-version`、`render.yaml`，以及 `backend/start.py`、`backend/requirements-render.txt`、`backend/DEPLOYMENT.md`、`backend/tests/run_offline.py`、`backend/tests/test_deployment.py`；兩份 README 補上部署文件入口。

沒有修改 `backend/app/`、`research/spherex.py`、原有 requirements 範圍、API schema、科學演算法、前端與 GitHub Pages。沒有連線 NASA、下載新資料、Commit、Push 或部署。

## 驗證結果

| 檢查 | 結果 |
| --- | --- |
| `python -m backend.tests.run_offline` | 99 項測試，98 通過、1 skip（真實 NASA opt-in 測試），10.931 秒，exit 0；沒有外部 DNS/socket 嘗試。 |
| 套件相依 | `pip check` 通過，無損壞相依。 |
| 部署套件版本 | `pip install --dry-run --no-index -r backend/requirements-render.txt` 通過，本機已安裝版本滿足範圍與固定版本；不代表 Linux 新環境安裝成功。 |
| 正式啟動參數 | mock 確認 PORT、自訂 port、0.0.0.0、workers=1、reload=False；即使 WEB_CONCURRENCY=8 也不會增加 worker；無效 port 拒絕啟動。 |
| 不含本機資料的實際啟動 | 僅複製 runtime `.py` 到新的系統暫存目錄，不包含 outputs、FITS、venv 或測試 fixture；真正啟動 Uvicorn，使用獨立 port 回應 `/health`。 |
| 啟動時間與 RAM | 上述乾淨原始碼啟動至 health 約 1.72 秒；Windows process tree idle RSS 約 85.3 MiB，包含可能的 venv launcher。這不是科學運算尖峰或 Linux/Render 冷啟動數值。 |
| HTTPS / CORS | 真正 HTTP 請求搭配 X-Forwarded-Proto=https 後，slash redirect 使用 HTTPS；TestClient 確認 artifact URL 使用 HTTPS、正式 origin preflight 成功、未授權 origin 拒絕、帶路徑 origin 設定拒絕。 |
| 清理 | 新增例外路徑暫存清理測試；既有清理、快取容量、busy lock、NASA retry/timeout、frame 限制與科學回歸測試均通過。 |

測試會使用已存在的可選本機回放資料，但不下載；乾淨原始碼啟動測試與合成 FITS/VOTable 測試不需要這些檔案。完整原始測試 log 在本機 `backend/test-results/phase5-1-offline.txt`（沿用既有 gitignore，未納入版本控制）。

既有測試有 Astropy SIP header 說明與 Starlette TestClient/httpx 棄用警告，沒有造成失敗。本輪沒有改科學處理來消除警告；未來升級測試相依時需注意 httpx 支援變動。

## 尚未驗證與決策

- 未做 Render/Linux 全新 build、平台 Blueprint 驗證、真實公開 TLS/CORS、休眠再喚醒與部署後 health；本機 YAML 解析不等於 Render 平台接受。
- 未測 NASA 的 Render 出口可達性、真實下載/解碼/影格運算的 RAM 尖峰及 CPU 耗時，不能由 85.3 MiB idle 推論一定符合 512 MB。
- 前端 API 等待 180 秒，冷啟動約一分鐘 + NASA 合作式預算 120 秒 + 運算可能超時；本輪未改 timeout。DNS、OS I/O 與 CPU 計算無法由現有合作式 deadline 強制中止。
- 既有快取 payload 上限合計約 32 MiB，不包含 Python 物件與運算工作集；沒有跨請求速率配額與 request body cap，仍有公開負載風險。
- 休眠/重啟會使所有 process-local cache 消失，使用者需重新搜尋；正式 Pages origin 尚未發布驗證。

結論：可供使用者審閱並進行後續小量部署驗證；Render Free 尚未被證明符合穩定公開服務需求。若真實工作發生 OOM、重啟、health timeout 或頻繁超時，應評估更多 RAM/CPU 與另期工作流程設計。詳細官方限制與操作步驟見 [DEPLOYMENT.md](DEPLOYMENT.md)。
