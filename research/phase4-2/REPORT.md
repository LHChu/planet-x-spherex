# Phase 4.2：少量 FITS、WCS 對齊與波長驗證

實際執行日期：2026-11-14。目標 ICRS：RA=127.69444°、Dec=−39.17760°。本階段僅新增獨立研究程式，未修改正式 FastAPI、前端、Phase 1～3 程式或原始 FITS，未 Commit／Push／部署。

## 結果

已驗證 **4 個不同日期的 D1 Cutout**：重用 Phase 1 一張，新下載成功三張。另一張候選下載三次均為 503，保留為失敗 slot，沒有更換成其他曝光冒充成功。

| 日期 UTC | obs_id | 來源／結果 | 目標 wavelength（µm） | bandwidth（µm） | 對齊後有效比例 |
|---|---|---|---:|---:|---:|
| 2025-04-29 14:18:55.983 | 2025W18_1B_0162_3 | Phase 1 重用；重投影成功 | 0.769980 | 0.019064 | 76.93% |
| 2025-05-22（SIA 候選日期） | 2025W21_1B_0582_1 | 503，三次皆失敗 | 未取得 | 未取得 | 未取得 |
| 2025-11-03 13:32:22.030 | 2025W45_1A_0121_1 | 新 Cutout；重投影成功 | 0.861452 | 0.021362 | 82.05% |
| 2025-12-02 18:22:40.111 | 2025W49_1A_0391_1 | 新 Cutout；重投影成功 | 0.861534 | 0.021361 | 81.93% |
| 2026-05-21 03:27:20.505 | 2026W21_1A_0480_1 | QR3 新 Cutout；重投影成功 | 0.965633 | 0.025219 | 72.53% |

**不能將四張視為同波段的光變序列。** 只有 11 月／12 月這一對通過本輪「目標波長近似相容」篩選；仍是視覺驗證候選，並未證明整個視場的每個像素波段一致，也未做精密光度量測。

人工檢查：

- [對齊前後與 independent/shared stretch 比較 PNG](../outputs/phase4-2/comparison.png)：四欄依序為 native 個別 stretch、aligned 個別 stretch、native 共用 stretch、aligned 共用 stretch。跨波長的共用 stretch 只作顯示診斷；紫色為缺資料／品質拒絕，不能解讀成低亮度。
- [11 月／12 月候選波段配對 PNG](../outputs/phase4-2/candidate-band-pair-1.png)：共同亮度範圍，同一 WCS 格網，非光變曲線。
- [完整 validation.json](../outputs/phase4-2/validation.json)、[每次上游請求 requests.json](../outputs/phase4-2/requests.json)、[候選 selection.json](../outputs/phase4-2/selection.json)。
- [摘要快照](snapshot-summary.json)保留數值、版本、FITS hash、殘差、請求總計，供沒有大型本機產物時核對。

## 環境與重用

先讀取 Phase 4.1 完整報告、`rows.json`、`summary.json` 及既有 FITS headers，再沿用 Phase 4.1 的 428 筆 metadata；**本輪 SIA 查詢數為零**。新候選由四個月份／日期區間各選 footprint margin 最大的 D1，選擇前尚不知道各自目標波長，沒有事後以亮度挑圖。

Python 3.11.1、Astropy 6.1.7、NumPy 2.0.2、Pillow 11.3.0、psutil 7.2.2 均可使用；不需安裝或更新套件。本機既有 venv 的直譯器路徑需要沙箱外檔案存取權，取得後可正常執行。這修正 Phase 4.1 的環境推論：先前啟動失敗**不能證明直譯器遺失**。未更改 venv 設定，也未改寫舊報告。

重用的 `research/outputs/cutout.fits` SHA-256 在執行前後一致：

```text
5ac314abbe6729c1cf2e404aa3e6c0a847b260f27f3d7cef4ee443ab30ac4adf
```

該檔 IMAGE／FLAGS／VARIANCE／ZODI 皆為 29×29，另外包含 EPSF 與 WCS-WAVE。研究程式僅讀需要的 IMAGE、FLAGS、波長表與 headers，沒有展開 EPSF 陣列，也沒有改寫來源檔。

## 上游請求與失敗紀錄

使用既有 `build_cutout_url()` 與 `fetch()`，繼承既有 RequestBudget 的 120 秒期限、20 秒單次 socket 上限、16 次請求、每 URL 最多三次與最多等待 15 秒。獨立研究子類另外處理 429；host cooldown 在候選之間共用，且保存至 ledger，重跑時不重置已用嘗試次數。

每個新請求均為同一座標、`size=3arcmin`；未下載母影像，實際三張新 FITS 的 IMAGE 皆為 29×29。每檔 3,965,760 bytes，合計 11,897,280 bytes（約 11.35 MiB）；檔案的大部分仍可能是未裁切的 EPSF，不能僅依 IMAGE 尺寸估算網路量。

| 項目 | 實際值 |
|---|---:|
| 測試的新 Cutout URL | 4（低於最多 5） |
| HTTP 嘗試 | 7（低於 16） |
| HTTP 200 | 3 |
| HTTP 503 | 4 |
| 下載區間 | 12:17:30.907～12:18:31.825 UTC，約 60.9 秒 |
| 最大成功單次下載耗時 | 約 19.68 秒 |

`2025W21_1B_0582_1` 的三次回應全為 503，`Retry-After: 5`；`2025W45_1A_0121_1` 第一次亦為 503，等待後第二次成功。逐次來源 URL、目的路徑、開始／結束 UTC、attempt、HTTP 狀態、位元組、耗時、錯誤與 cooldown 均在 ledger；離線重跑仍保留失敗 slot 的原因。其後未再嘗試這些失敗 URL，也沒有使用剩餘額度多下載。

## WCS 與品質驗證

固定輸出為 29×29 的 ICRS TAN 格網：CRVAL=(127.69444,−39.17760)、FITS CRPIX=(15,15)、CDELT=(−6.15/3600,+6.15/3600) 度／pixel。目標為零基像素 (14,14)。PNG 僅在最後垂直翻轉，因此北上、東左；沒有靠 PNG 旋轉或 resize 對齊。

逐張使用 IMAGE **主要 celestial WCS**（TAN-SIP）將輸出格點轉回輸入 pixel，再以雙線性插值重投影。要求所有非零權重的輸入 pixels 均在範圍內且有效；不對缺角外插，不把 NaN 填成有效黑色。原始數值單位保留 MJy/sr。這是表面亮度的視覺重採樣，未聲稱保存點源測光積分或傳播完整 variance。

四張均通過：

- FITS OBSID 與已選 metadata 相符，DETECTOR=1，且尺寸為小 Cutout。
- 目標在 IMAGE 像素單元範圍內；最近中心 pixel 是 finite，並通過品質政策。
- FLAGS 與 IMAGE shape 相同，抽樣 celestial WCS 分離為 0 arcsec，可直接套用遮罩。
- 從 FLAGS header 的 `MSKNnnnn/MSKMnnnn/MSKDnnnn` 讀取旗標定義，不假定 `flags==0` 才有效。SOURCE (bit 21) 與 FULLSAMPLE 為本輪允許資訊位，其餘所有已知／未知 bits 採保守拒絕。
- 四張中心旗標均為 2097152（SOURCE），不能因它不是零就刪除目標。原圖品質接受比例約 95.60%～98.93%。重投影後 FLAGS 採所有有貢獻 pixel 的 bitwise OR，另存有效權重與獨立 mask。

這項研究品質政策刻意保守，不代表官方測光管線的完整旗標政策。[IRSA 入門教學](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/)說明 FLAGS header 的自描述欄位；所有實際 bit 定義與各張 counts 已保存於 metadata，後續 API 應將政策版本化。

metadata 標稱尺度是 6.15 arcsec/pixel；含 SIP 的目標附近實測局部尺度約 6.148～6.185 arcsec/pixel。相同 detector／標稱尺度不足以直接逐像素疊圖。

輸出完整幾何覆蓋約 80.98%～85.02%，再計入品質與插值支撐後有效約 72.53%～82.05%。原因包括原 3arcmin 正方形在不同方向旋轉後缺角，以及壞像素鄰域被保守遮罩。中心皆有效，但不能宣稱視窗全滿。未來可評估稍大的有界原 Cutout（例如約 4.4 arcmin，仍遠小於全圖）供同一 3arcmin 輸出使用；本輪沒有為此額外下載。

## 對齊殘差：數學閉合與影像實測分開

WCS output→input→sky→output 的最大數學閉合誤差約 2.6×10⁻¹¹～9.9×10⁻¹¹ pixel。這只能證明轉換數值自洽，**不能當作星點對齊精度**。

影像實測另以 aligned image 獨立偵測星點：峰值須高於影像 median + 5×MAD noise、以完整有效的 5×5 patch 扣除邊界背景計算 centroid、排除過近候選，再以互為最近且距離 ≤1.5 pixel 配對；沒有事後平移、旋轉或剔除離群點來改善殘差。

本輪門檻預設為至少 3 對、median <0.5 pixel、maximum <1.0 pixel。配對與 centroid 座標全部保存，不只存通過結果。

| 比較 | 配對星點 | median（pixel／arcsec） | maximum（pixel） | 結果 |
|---|---:|---:|---:|---|
| 11 月 vs 4 月參考 | 7 | 0.178／1.095 | 0.300 | 通過 |
| 12 月 vs 4 月參考 | 5 | 0.209／1.285 | **1.083** | **超出門檻** |
| 2026-05 vs 4 月參考 | 6 | 0.207／1.274 | 0.284 | 通過 |
| 12 月 vs 11 月（近似波段配對） | 5 | 0.201／1.239 | 0.902 | 通過，最大殘差仍接近門檻 |

12 月雖然重投影與中心驗證成功，**不能標示為對所有參考都對齊成功**。該離群星點可能受不同波長、混合源或 PSF 影響，原因尚未確認，本輪不自行排除。配對數少、沒有外部星表或 PSF 擬合，結果屬小視場相對視覺驗證，不是絕對 astrometry 認證；搜尋半徑外未配對的星點也未被計入殘差。

## WCS-WAVE 波長與 bandwidth

讀取 alternate W 的線性 CRPIX／PC／CDELT／CRVAL，明確從 Python 零基中心座標轉成 FITS 一基座標，再定位 WCS-WAVE 的 X、Y 控制格點，以 VALUES[...,0:2] 雙線性插值；超出控制網格即失敗，不外插。[IRSA Data Products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products/)將此表定位為視覺近似，精密分析仍需 CWAVE／CBAND 校準產品；本輪未下載額外校準檔。

關鍵陷阱：`WCS(IMAGE_header, key='W', fobj=hdul).all_pix2world()` 會受到同一 header 的空間 SIP 影響。既有影像直接這樣呼叫約得到 0.768133 µm，而隔離空間 SIP 的正確 alternate W 核心計算是約 **0.769980 µm**。研究程式使用手動控制格點插值，另以 WCSLIB `wcs_pix2world()` 核心 `-TAB` 交叉檢查（不套 spatial SIP）；四張 wavelength／bandwidth 的最大差異皆 ≤2.3×10⁻¹⁶ µm。這是實作一致性，不代表天文校準有如此高精度。

近似波段篩選規則（工程政策，不是物理等價證明）：

```text
abs(lambda_a-lambda_b) <= 0.1 * min(bandwidth_a,bandwidth_b)
abs(bandwidth_a-bandwidth_b) / min(bandwidth_a,bandwidth_b) <= 0.1
```

11 月／12 月的 Δλ 約 0.00008208 µm（0.0821 nm），為較窄 bandwidth 的 0.384%；bandwidth 相差約 0.0041%。可作目標位置的近似同波段視覺配對。此 Δλ 已小於波長表本身約 nm 級的視覺精度，不能過度解讀其小數位。4 月、2026-05 與這對的差異大，均為 `different_bandpass`。

四張 `VERSION=7.0.5`，來源產品版本皆為 v27，單位相同，保存的 `[CALIB]` HISTORY 序列亦一致。這支持本小樣本可一起做視覺探索，仍不保證 PSF、背景與每個像素有效 bandpass 相同；未以檔名日期代替校準 provenance。

## 共同亮度正規化

保留原始 MJy/sr，不除以曝光秒數，不將不同波長差異當時間亮度差異。PNG 有兩種診斷輸出：

1. 每張各自 p1/p99 + asinh(10x)，只用來顯示逐張拉伸如何改變視覺尺度。
2. 所有張共同數值範圍（lo=0.219578、hi=6.154711 MJy/sr），但整張 contact sheet 已明示跨波長，**不是同波段時間比較**。

11 月／12 月的 individual aligned hi 分別約 5.139901 與 6.004378 MJy/sr，即使使用相同百分位規則，兩張仍會套用不同亮度增益。因此候選波段配對改取共同有效區的 **650 pixels**，合併統計後固定 lo=0.237902、hi=5.704328 MJy/sr，同時套用相同 asinh 參數。

共同 stretch 避免每張自動改變顯示增益，但不能消除 zodiacal light、背景漂移、PSF、重採樣、像素內 bandpass 差異或雜訊。本輪未扣 ZODI、未做背景擬合、PSF matching、variance propagation、差分或測光；不報告任何目標光變值。配對只核對目標位置波長，整個視場共同 stretch 仍僅供人工診斷。

## 實作與驗證產物

`verify_epochs.py` 預設完全離線，僅 `--download` 才會抓已選 metadata 的缺檔。來源 URL 由既有白名單 URL builder 產生，最多五個不同的新 Cutout，ledger 跨重跑保留每 URL 三次及總請求數；不提供任意 URL 輸入，不呼叫 preview／SIA，不以全圖 fallback。

每個成功曝光資料夾內包含：

- `metadata.json`：來源 metadata／hash、DATE-OBS、品質旗標、波長與核對誤差、WCS／尺度、殘差、顯示範圍。
- `aligned.fits`：固定 WCS 的 IMAGE、VALID_WEIGHT、VALID_MASK、FLAGS_OR；FLAGS_OR 不代表幾何覆蓋，必須一起看 VALID_MASK。
- `arrays.npz`：native 數值／mask、aligned float32、有效／幾何權重與傳播旗標，方便離線重新評估。
- 四張 native/aligned × individual/shared PNG。原始新 Cutout 保存於各自資料夾，Phase 1 原始檔只讀。

離線數值檢查 **8 項通過**：線性平面插值、壞像素支撐、邊界不外插、固定格網中心及方向、旋轉合成星點重投影、旗標 OR、alternate W 一基／零基轉換且不套 SIP、殘差最少配對數、429 Retry-After 阻止下一次請求（部分情境合併在同一測試）。合成影像只用於測試，不混入 NASA 研究結果。

最終離線重算程序的 peak working set 為 78,323,712 bytes（約 74.7 MiB）；這是 Windows 本機程序，**沒有在 512 MB Render 限制環境中驗證**。本次小型 float32 輸出且避免 EPSF 展開，不能推論更大視場或更多影格同樣安全。

重現（從專案根目錄；需既有 Python 與本輪已保存檔案）：

```powershell
# 離線，重用所有已保存 FITS；不新增 NASA 請求
.\research\.venv\Scripts\python.exe research/phase4-2/verify_epochs.py
.\research\.venv\Scripts\python.exe research/phase4-2/test_verify_epochs.py
```

這次實際下載使用過一次 `--download`；不需要為查看輸出再次執行下載。本機 outputs 已沿用既有 Git ignore；研究程式、測試、報告與小型摘要是獨立新增檔。

## 下一階段 API 的必要資料結構與待解問題

不能用單一 `success=true` 混合下載、中心有效、重投影、星點殘差與波長相容。建議沿用 Phase 4.1 的 exposure/product 識別，新增以下結構：

```json
{
  "product_id": "server-owned-source-id",
  "obs_id": "2025W49_1A_0391_1",
  "date_obs": "2025-12-02T18:22:40.111",
  "download": {"status":"cached","source_url":"validated IRSA URL","sha256":"...","request_log_id":"..."},
  "identity": {"detector":1,"product_version":"27","pipeline_version":"7.0.5","bunit":"MJy/sr","calibration_signature":"..."},
  "center": {"inside":true,"finite":true,"quality_accepted":true,"flags":2097152},
  "quality": {"policy_id":"strict-except-source-fullsample-v1","valid_fraction":0.819263,"mask_url":"..."},
  "reprojection": {"status":"reprojected","grid_id":"...","image_url":"...","interpolation":"bilinear-complete-support"},
  "alignment": {"reference_product_id":"April-reference","status":"residual_exceeds_threshold","matched_stars":5,"median_pixels":0.20893,"max_pixels":1.08260},
  "spectral": {"status":"pass","wavelength_um":0.861534,"bandwidth_um":0.021361,"source":"WCS-WAVE","scope":"target-position-visualization"},
  "normalization_id": null,
  "warnings": ["Global-reference residual exceeded threshold"]
}
```

共同部分另存：

- `grid`：ICRS frame、TAN header、center、shape、scale、orientation、grid version／hash。
- `spectral_pair/group`：成員、波長政策與 delta、相容狀態、**該 pair 自己的 reference／殘差結果**；不能因 12 月對 11 月通過，就抹去它對 4 月的失敗。
- `normalization`：明確成員、共同 footprint、mask policy、單位、lo／hi／asinh、背景政策與版本；整組 normalization id 納入 PNG cache key。
- `request_budget`：attempt count、deadline、host cooldown、Retry-After；失敗 slot 必須保留 product_id、失敗階段／原因、是否可手動重試，不能靜默補其他曝光。
- `provenance`：來源 release／檔案版本／calibration signature、查詢 snapshot、原始 FITS hash；blob 與 metadata 的到期時間分開。

API 實作前尚需決定：

1. 星點配對是否改用更穩健的 PSF／blend 篩選與外部星表；目前 12 月離群星點原因未解，不可默認通過。
2. 波段容差如何版本化，以及目標位置相容與全視場相容如何分開；定量光變仍需較完整校準與誤差傳播。
3. 是否以稍大有界 Cutout 補足旋轉角落，或接受固定 mask；此決策會影響請求量、共同有效範圍與 cache key。
4. 是否採用本輪保守旗標政策，如何向前端呈現品質拒絕與缺角，且不將 SOURCE 當作壞像素。
5. 確定共同背景／正規化政策、部分成功回應、同組 PNG 一致到期及 cache 淘汰語意。
6. 在受限容器驗證 RSS、工作鎖與與既有 preview 共用的上游 cooldown；本輪沒有對正式 API 做實作或新增 FITS 回歸請求。

本輪完成研究所需的少量影像驗證、產物與限制揭露，未開始動畫、正式 API 或前端實作。
