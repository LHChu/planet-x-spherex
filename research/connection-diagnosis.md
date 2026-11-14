# SPHEREx 502／503／DNS 連線診斷

本次僅新增獨立診斷工具，沒有修改正式後端、WCS 檢查、請求上限或重試設定。

## 已取得的證據

使用者回報：source index 40、42 最終為 HTTP 503；41、43、44、45、7、6、30、31 為 `URLError(gaierror(11001, 'getaddrinfo failed'))`。這些是本機 API 實測，不是下列工具執行環境的結果。

已實際執行 `research/diagnose_urls.ps1 -Probe`，產出 `research/outputs/connection-diagnostics.json`，逐筆保存十個候選的 access_url、Cutout URL、scheme、hostname、官方路徑檢查、DNS、代理主機、HTTP 狀態／redirect 資訊與錯誤。完整 URL 只存在此本機診斷檔，終端摘要不輸出查詢參數。

重要限制：工具使用的是 Phase 1 保存的 SIA snapshot，最後修改時間為 2026-11-14 09:55:29 UTC，SHA-256 為 `1994215CDEBEF7CC82AD884896E4D972638CAA32D80213931A3BC3418E050F9C`。source index 只有在同一份表格內才有意義；它未必與最新失敗的 API 請求完全一致。

| 候選 source index | 原始與 Cutout scheme／hostname | 原始路徑形式 | 本環境實際探測 |
|---|---|---|---|
| 40、42 | https / irsa.ipac.caltech.edu | SPHEREx DR1 level2 IBE FITS | DNS 成功，HTTPS ConnectFailure |
| 41、43、44、45、7、6、30、31 | https / irsa.ipac.caltech.edu | SPHEREx DR1 level2 IBE FITS | DNS 成功，HTTPS ConnectFailure |

十筆皆符合 `/ibe/data/spherex/dr1/level2/...fits`，加上 `center=RA,Decdeg&size=3arcmin` 的 URL 構造符合官方 Cutout 用法。PowerShell 的 `%2c` 與 Python 的 `%2C` 是相同逗號編碼，不是 hostname 改變。路徑形式正確不代表已確認檔案存在或服務可用。

本環境實際解析：`irsa.ipac.caltech.edu` 的 CNAME 為 `irsaproxy1.ipac.caltech.edu`，A 記錄為 `134.4.54.42`。CNAME 不是 HTTP redirect，不能將 CNAME 名稱當作最終 URL hostname。

十次 HTTPS 嘗試均在連線時被本機權限拒絕：`An attempt was made to access a socket in a way forbidden by its access permissions 134.4.54.42:443`。沒有收到 HTTP 回應、Location 或 Retry-After，因此 final_hostname 為 null／未確認。不能由此重現或解釋使用者電腦上的 11001。

本工具環境的 HTTP_PROXY／HTTPS_PROXY／ALL_PROXY 未設定，.NET 請求未使用代理；WinHTTP 設定也顯示 direct access。這不代表使用者啟動 FastAPI 的終端具有相同 proxy／DNS 設定，也不代表 .NET 與 Python urllib 一定走相同路徑。

## 尚未定位的部分

目前不能確認使用者的 DNS 失敗實際發生於：

1. 原始 IRSA hostname 的暫時性解析失敗；
2. HTTP redirect 的新 hostname；
3. Python urllib 採用的 proxy hostname。

`gaierror(11001)` 本身沒有指出傳入 getaddrinfo 的 hostname。503 表示某個 HTTP 回應端可達，但現有終末錯誤日誌沒有 final URL；因此不能斷言 503 與 DNS 錯誤來自不同主機。不能先改成 IP、改 DNS、取消代理或替換官方路徑作為修正。

## 精確定位 Python 實際 DNS 失敗主機

新增 `research/diagnose_connectivity.py`，僅在獨立診斷程序內包裝 `socket.getaddrinfo`、urllib redirect 與下載，不修改後端或全域系統設定。使用原有 RequestBudget 與原有 fetch/build_cutout_url，保留 Python urllib 預設代理設定。報告會保存：

- 每個候選的原始 URL 與實際共用函式產生的 Cutout URL。
- 每次請求的初始、redirect 與確認收到回應的最終 hostname／scheme。
- 實際傳入 getaddrinfo 的 hostname；若拋出錯誤，記為 `dns_failure_hostname` 與 errno。
- HTTP status、Retry-After、每個候選實際嘗試次數、等待秒數與總預算。

此 Python 工具已嘗試啟動，但本工具環境的既有虛擬環境仍無法存取其 Python 主程式，未能執行，沒有宣稱 Python 診斷已通過。

請從專案根目錄，在**啟動 FastAPI 的同一個本機終端環境**執行：

```powershell
.\research\.venv\Scripts\python.exe -m research.diagnose_connectivity
```

報告位置為 `research/outputs/python-connection-diagnostics.json`。查看關鍵欄位，不必公開完整 URL：

```powershell
$r = Get-Content research/outputs/python-connection-diagnostics.json -Raw -Encoding UTF8 | ConvertFrom-Json
$r.attempts | Select-Object candidate_source_index,status,retry_after,dns_failure_hostname,initial_endpoint,last_requested_endpoint,final_endpoint
$r.attempt_counts
$r.waits
$r.python_proxy_hosts
```

如果需要重查當前 SIA，使用 `--refresh`，不提高預算，並保留該次查詢的精確表格（`python-connection-diagnostics.votable.xml`）：

```powershell
.\research\.venv\Scripts\python.exe -m research.diagnose_connectivity --refresh
```

新查詢的 source index 可能與先前不同，應比較 access_url 的檔案識別，而非只比較數字。

## 不使用 Python 的 PowerShell 路徑

```powershell
# 先檢查 URL，零 HTTP 請求。
.\research\diagnose_urls.ps1

# 最多 16 次 HTTP hops、每個 URL 最多三個 hops，沒有自動 503 重試。
# GET 只取得回應資訊，不讀取 FITS body；會關閉回應。
.\research\diagnose_urls.ps1 -Probe

# 如有原失敗請求保存的 VOTable，應使用該檔案。
.\research\diagnose_urls.ps1 -VotablePath '.\research\outputs\spherex_dr1.xml' -Probe

Resolve-DnsName irsa.ipac.caltech.edu
```

PowerShell 會手動追蹤至多三個 HTTPS hops，分別記錄 redirect hostname、.NET proxy hostname，以及 NameResolutionFailure／ProxyNameResolutionFailure 的對應 hostname。HTTP 503 的 Retry-After 也會控制後續探測的等待；若需等待超過 15 秒或剩餘 120 秒協作式預算，就停止，不提早切換 URL。DNS／OS 阻塞不是可強制中斷的硬性期限。

這條路徑已在本工具環境實際執行，但它使用 .NET，而非 Python urllib；若兩者結果不同，應以 Python 工具記錄的 `dns_failure_hostname` 判讀原 API 的 DNS 失敗來源。

## 503 重試檢查

正式程式仍為每個 URL 最多三次（初次＋兩次），1、2 秒退避，使用與 Retry-After 較長者，跨候選沿用 cooldown；等待過長就停止。既有單元測試已由使用者確認通過，支持此程式分支的行為；但現有終末日誌不足以確認該次 NASA 回應的 Retry-After 值或每次嘗試。

若兩個候選都完整嘗試三次，另八個 DNS 失敗各嘗試一次，加上一個 SIA 查詢，共為 15 次，符合 16 次預算。這是與日誌相容的計算，不是已觀測的請求數。應以 Python 診斷的 attempt_counts、waits、retry_after 確認實際情況。

本輪不提出猜測性的正式程式修正；先取得失敗 hostname 與 redirect／proxy 證據，再決定應處理 URL、代理或解析器哪一層。

官方參考：[IRSA Cutout Service](https://irsa.ipac.caltech.edu/ibe/cutouts.html)。
