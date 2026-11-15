# Dashboard UI/UX - Round 3

Date: 2026-11-15. This round changes frontend presentation and tests only. Existing uncommitted changes were preserved. No backend, NASA query, FITS, WCS math, normalization, science calculation, dependency, GitHub Actions or deployment changes. No NASA connection, new FITS download, commit, push or deployment.

## Results

- `node frontend/tools/test.mjs`: **111 passed, 0 failed** (106 previous tests plus 5 new tests; existing presentation assertions updated).
- `node frontend/tests/browser-layout.mjs`: **12 real Chromium layout checks passed**, covering both Preview and Multi-epoch at 1920x1080, 1536x864, 1440x900, 1366x768, 768x1024 and 390x844.
- Actual browser interactions passed for expanded Brightness, Asinh / FLAGS, failed slots, playback / Timeline, manual 32x, manual scale persistence after resize, return to Fit, and no additional API fetches during those interactions.
- Both modes at 1536x500 retain the minimum readable viewport and allow normal page scrolling.
- `git diff --check`: passed.

## Desktop first-screen evidence

Measured viewer card bottom in CSS pixels; all include the complete fitted image, WCS and Color Bar. The Multi-epoch card also includes its player and Timeline. Search buttons remain above 436px.

| Viewport | Preview card bottom | Multi-epoch card bottom |
| --- | ---: | ---: |
| 1920x1080 | 1063 | 1063 |
| 1536x864 | 847 | 847 |
| 1440x900 | 883 | 883 |
| 1366x768 | 751 | 751 |

All 12 layouts have full Fit-stage containment, no Fit scrollbars and no page-level horizontal overflow. Tablet / phone use normal page scrolling. Very short desktop windows, expanded help or unusually long scientific warnings may also require page scrolling; content is not cut off.

## Implementation

- `index.html`: compact English heading, NASA SPACE APPS 2026 badge, collapsed brightness explanation and Viewer help, readable Advanced Metadata instead of raw JSON.
- `styles.css`: compact header / search spacing, independently sized columns, measured desktop viewport height, tablet stacking and touch-sized phone buttons.
- `app.js`: subtract actual viewer chrome from the document-position-based height budget; preserve manual zoom; format text to six significant digits while retaining full input / slider / histogram / science precision; render readable metadata fields.
- `epochs.js`: readable candidate, frame and sequence fields; preserve identifiers, UTC, collection, exposure, WCS, calibration, alignment, errors and warnings; keep cached player behavior and failed slots.
- `color-bar.js`: readable tick formatting with additional precision when needed to distinguish close endpoints. Narrow fitted viewers put the same scientific scale below the WCS instead of shrinking annotation text; manual zoom retains the side-by-side stage. Pixel values, scale mapping and WCS positions are unchanged.
- `tests/app.test.mjs`, `tests/epochs.test.mjs`, `tests/dashboard.test.mjs`: updated metadata assertions and added height-budget, disclosure, precision and narrow-stage checks.
- `tests/browser-layout.mjs`: optional dependency-free real Chromium acceptance test. It is separate from the portable unit suite and requires a locally installed Chromium browser.

## Reproduce browser acceptance

```powershell
node frontend/tools/serve.mjs --wcs-fixture --port=5507 --fixture-port=8007
node frontend/tests/browser-layout.mjs
```

The fixture replays the existing local FITS and synthetic epoch frames. The browser test adds a temporary loopback-only presentation harness on port 5508. On this managed Windows environment Chromium's rendering subprocess required running this browser test outside the filesystem sandbox; the application itself requires no permission changes.

Screenshots and metrics are local ignored artifacts under `frontend/coverage/round3/`: twelve viewport screenshots, scrolled 390px viewer screenshots, `preview-brightness.png`, and `metrics.json`. Representative desktop, tablet, phone, expanded-brightness and scrolled-phone screenshots were visually inspected after capture. This is real headless Chromium verification, not only DOM mocks.

## Remaining manual checks

- Physical touch interaction, operating-system font scaling and browser zoom above 100%.
- Firefox / Safari / other browser rendering and different display scaling factors.
- Live Render / GitHub Pages integration and fresh NASA observations were intentionally not exercised. Synthetic epoch fixtures do not establish scientific alignment or photometric comparability.

---

Historical Round 2 results below describe the earlier state, including its then-pending browser checks.

# Dashboard UI/UX - Round 2

Date: 2026-11-15. No backend, API contract, FITS, WCS math, normalization, FLAGS calculation, dependency, deployment or GitHub Actions changes. No NASA connection, new FITS download, commit, push or deployment.

## Results

- `node frontend/tools/test.mjs`: **106 passed, 0 failed**.
- `git diff --check`: passed.
- Offline HTTP smoke: updated frontend at `/planet-x-spherex/` returned 200; the local fixture Preview API returned 200 with real WCS annotations and its OFFLINE REPLAY marker.
- Added regression coverage: compact five-field Preview and epoch summaries, complete Advanced Metadata retention, full candidate Details including long IDs / calibration / alignment / errors / warnings, player controls inside the Viewer, collapsed disclosures, no fixed sidebar scrolling, and more image area after moving scale explanations outside Fit.
- Existing coverage remains: brightness / FLAGS / histogram, Color Bar values, true WCS positions, aspect ratio and Fit containment, manual zoom and resize, failed slots, selection logic, cached playback, zero additional interaction fetches, API switching and GitHub Pages subpaths.

No screenshot was attached to the request. Browser discovery still reported `The browser access host is unavailable`; actual visual verification was not performed. Static layout assertions and DOM mocks do not prove browser rendering correctness.

## Browser acceptance checklist (pending)

The offline fixture server is available at `http://127.0.0.1:5515/planet-x-spherex/`. If it has stopped, run:

```powershell
node frontend/tools/serve.mjs --wcs-fixture --scenario=failed --port=5515 --fixture-port=8015
```

Open **API connection settings**, select **Local (localhost)** and set API base URL to `http://127.0.0.1:8015` before searching. This fixture uses existing local data only.

1. At 1440x900 and 1024x768, confirm RA / Dec / Radius / Detector / Search are easy to see, and the sidebar has no internal scrollbar. Expand Histogram and brightness; the page should scroll without introducing a sidebar scroll pane.
2. Search Preview. Confirm more space is used by the image; the whole image, WCS labels and Color Bar remain visible. Scale explanations should appear below the viewport. Try Fit, 1x, 12x, 32x and resize; only the image viewport should scroll during manual enlargement.
3. Confirm the default summary has only Observation UTC, Detector, Wavelength, Valid pixel count and Status. Expand Advanced Metadata to inspect all previous fields and the raw metadata.
4. Switch to Multi-epoch, Search epochs, Select first 3 and Load frames. Play / Pause / Previous / Next / speed / Timeline should be immediately below the image. Visit the failed slot and confirm the full failure reason remains visible there. Check the compact frame summary and expanded slot diagnostics.
5. Confirm candidate rows show only selection, UTC, Detector and concise status alongside a Details disclosure. Open Details to inspect full IDs, sources, calibration / alignment / warnings / errors. Confirm Select first 2 / 3 still selects the same legal exposures.
6. Record Network count after loading frames; playback, timeline dragging, Fit, manual zoom and resize must add no API requests. Repeat under the project subpath and `/`.
7. At 768x1024, 390x844 and 320x740, check control readability, responsive stacking, no page-level horizontal overflow, and touch access to playback. The candidate table may scroll horizontally inside its own container on mobile; expanded metadata should not create nested vertical scroll panes.

## Remaining limitations

- Actual screenshots, label readability at narrow widths, page overflow and touch usability remain unverified in a browser.
- Missing per-frame valid pixel counts are shown as **Not available**. The UI does not substitute a common-grid count or compute a new one.
- Live Render / GitHub Pages integration was not tested.

---

Historical Round 1 results follow.

# Dashboard / Fit to View - Phase 1

Date: 2026-11-15. Frontend changes only; no NASA calls, FITS downloads, commits, pushes or deployment.

- `node frontend/tools/test.mjs`: **100 passed, 0 failed** (80 existing tests, 20 added).
- `git diff --check`: passed.
- Coverage: Preview / Multi-epoch, detectors, raw brightness and FLAGS, Color Bar mapping, real WCS tick placement, failed slots, timeline ordering, cached playback, API validation, and GitHub Pages root / project-path assets.
- Added coverage: full stage containment for square / rectangular images in 280-1400 px containers; constant aspect ratio; fractional WCS positions; Color Bar adjacency; Fit resize; manual zoom persistence; mode switches; zero additional fetches during Fit / zoom / playback / scrubbing.
- Responsive CSS rules are checked statically. DOM mocks and display geometry tests do **not** establish browser rendering correctness.

Browser verification remains pending: the browser host was unavailable, and Windows Computer Use stopped because it could not reliably identify the Chrome URL. No screenshot or successful browser interaction was obtained. Live Render / GitHub Pages integration was not exercised.

## Offline browser acceptance

From the repository root, run (unless this test server is already running):

```powershell
node frontend/tools/serve.mjs --wcs-fixture --scenario=failed --port=5515 --fixture-port=8015
```

This reads the existing local FITS and produces synthetic epoch fixtures; it makes no NASA requests.

1. Open `http://127.0.0.1:5515/planet-x-spherex/`. Choose **Local (localhost)** and set API base URL to `http://127.0.0.1:8015` before searching.
2. In Preview, search and verify the complete image, RA / Dec axes and Color Bar fit inside the viewport. Check inversion, Linear / Asinh, Min / Max, FLAGS, histogram and expandable metadata.
3. Select manual zoom at 1x, 12x and 32x. Verify aspect ratio and axis / Color Bar alignment. Overflow should scroll inside the image viewer. Resize: manual zoom stays fixed; selecting **Fit to View** restores full containment and reacts to further resize.
4. Switch to Multi-epoch, Search epochs, Select first 3, and Load frames. Verify playback, pause, speed, timeline, individual slots, the failed slot and full sequence metadata. The central image and lower information panel should switch together.
5. After frames load, record the browser Network count. Playback, scrubbing, Fit, manual zoom and resize must add no requests. Preview brightness / zoom / Fit must add no requests; legacy PNG inversion may request its existing cached inverse endpoint.
6. Repeat at 1440x900, 1024x768, 768x1024, 390x844 and 320x740. Confirm desktop / tablet columns, mobile stacking, readable controls, full Fit containment and no page-level horizontal scroll. Also check `/` as well as the project subpath.

On narrow screens Fit uniformly shrinks annotation gutters with the image; label readability and touch usability still need visual acceptance. Fixtures do not validate fresh observations or live hosting.

---

The following is a historical Phase 3 record; its environment findings are not current validation results.

# Phase 3 本機測試紀錄

日期：2026-11-14。未部署、未修改 `backend/` 或 `research/`。

## 已通過

- `node --test frontend/tests/app.test.mjs`：23 項通過，0 失敗。
- `node --check frontend/app.js`、`node --check frontend/tools/serve.mjs`：語法檢查通過。
- 本機 HTTP：`/`、`/planet-x/` 與子路徑下 `styles.css`、`config.js`、`app.js` 均回傳 200。
- 獨立 fixture API：POST 使用 Phase 1 真實已存 metadata，兩個 PNG URL 均可下載，PNG IHDR 尺寸皆為 29×29；OPTIONS 204 與指定 CORS origin 正常。

自動測試涵蓋：數值 POST、RA／Dec／半徑邊界、公開網站禁用 localhost、Render HTTPS、拒絕無效 URL、代理內部影像 URL 重設 origin、觀測欄位、metadata 安全文字呈現、12 倍與 32 倍縮放、反相切換、no_images、busy、upstream_timeout、cutout_failed、invalid_input、internal_error、網路／CORS 失敗、無效 JSON、PNG 失敗、localStorage 不可用及 180 秒中止後恢復表單。

## 未完成的環境驗證

- 真實 FastAPI／NASA 串接：本次環境未發現 8000 listener；`research/.venv/Scripts/python.exe` 指向已不存在的 Python 3.11 執行檔。`py -0p` 僅列出 Python 3.9。未變更使用者 Python 安裝或後端環境。
- 真實瀏覽器視覺、互動、窄螢幕與 CORS enforcement：瀏覽器自動化 host unavailable；原生 Chrome 介面存取核准等待逾時。未取得瀏覽器畫面，因此無法宣稱視覺驗收通過。
- Render 串接：尚未提供真實 Render 網址。

回放 API 與 DOM 替身測試並非真實 NASA、FastAPI 或瀏覽器端對端測試。後端環境修復後，請依根目錄 README 啟動前後端，實際搜尋範例座標，確認 PNG、UTC、detector、反相與縮放，再檢查無資料／斷線／快取到期與手機尺寸。Render URL 可用後，再從本機前端選 Render 驗證 HTTPS 與 CORS，通過後才部署。


## Multi-epoch modal and visualization update (2026-11-15)

- A/B implementation batch: 117/117 offline frontend tests passed.
- Final suite: 126/126 passed, no skips. UTF-8 output: `phase6-tests.txt`.
- Includes Change Selection request counts, unchanged selections, expiry,
  cancellation during processing, failed replacements, Log transforms and Color
  Bar agreement, shared/individual ranges, native Histogram invariance, arcmin
  conversion, WCS and responsive dialog structure regression checks.
- Backend: 100 run, 99 passed, one existing live test skipped, external sockets
  denied. No NASA data requests or FITS downloads.
- Real Chromium/Edge acceptance did not reach the page: Runtime.enable timed out.
  The native computer-use browser host was unavailable; inspecting an unrelated
  existing Chrome window was rejected by automatic approval review. No visual
  or real-keyboard pass is claimed for this round.
- Full file list, science evidence, manual acceptance checklist and capacity
  analysis: [review](../docs/multi-epoch-visualization-review.md).

## UI integration round 4 — 2026-11-15

This section records the current round; earlier results above are historical.

- `node frontend/tools/test.mjs`: **136 passed, 0 failed, 0 skipped**.
  Complete output: [round4-tests.txt](round4-tests.txt).
- `node frontend/tests/browser-layout.mjs`: **12 Chromium layouts passed**:
  Preview and Multi-epoch at 1920×1080, 1536×864, 1440×900,
  1366×768, 768×1024 and 390×844. Output:
  [round4-browser-tests.txt](round4-browser-tests.txt).
- Browser acceptance uses the local Synthetic Fixture, not NASA. It checks
  image-only zoom cursor/clicks, synchronized slider/output, 32× cap, WCS edge
  alignment at 32×, Fit, resize, internal scrolling, playback and failed slots,
  horizontal toolbar buttons, modal keyboard focus/close/reopen, unchanged
  selections and zero additional interaction requests. No runtime exceptions.
- Screenshots and metrics: `frontend/coverage/round4/` (generated, ignored).
  Visually inspected desktop and phone Viewer, phone Modal, expanded desktop
  Preview details, phone sequence details and phone Footer. No page horizontal
  overflow. Short desktop windows retain the existing 300px minimum viewport
  and allow normal page scrolling.
- Offline numeric tests cover Sqrt endpoints, negative and zero values,
  nonfinite/null/invalid pixels, FLAGS overlay, inversion and stretch switching.
  All four Color Bar mappings match the image over 257 sample values in both
  polarities. Shared/per-frame Sqrt semantics and unchanged native Histogram
  statistics are covered in the Multi-epoch integration tests. The browser
  sequence fixture supplies PNGs without raw display arrays, so browser
  Multi-epoch Sqrt rendering still needs a raw-array fixture or manual review.

Changes in this round:

- `index.html`, `styles.css`: compact Observation Details, visible caveats,
  removal of the standalone search card, grouped selection/Fit controls,
  Sqrt options and official resource links.
- `app.js`: explicit scientific-field projection, current brightness details,
  shared click-to-zoom geometry, Fit/slider synchronization and zoom cap.
- `epochs.js`: existing-result selection entry, retained failure/search states,
  compact frame/sequence details and modal Tab/Shift+Tab containment.
- `brightness.js`, `color-bar.js`: display-only Sqrt mapping.
- Tests: `app.test.mjs`, `epochs.test.mjs`, `brightness.test.mjs`,
  `color-bar.test.mjs`, `dashboard.test.mjs`, `pages.test.mjs`,
  `browser-layout.mjs`.

Manual follow-up: actual touchscreen and screen-reader behavior; other browser
engines; real observation scientific review and raw-array Multi-epoch Sqrt
visual inspection. Official resource URLs are asserted offline and were not
opened. No live NASA requests or new FITS downloads were performed.

Existing uncommitted changes were preserved. This round changes no backend,
API schema, cache policy, FITS values, WCS solution, FLAGS policy, normalization,
deployment configuration or dependencies. The existing Pages artifact test
passes at both root and project paths. No commit, push or deployment.


## Observation UI cleanup and API origin isolation (2026-11-15)

- Baseline: 136/136 offline frontend tests passed before edits. Existing uncommitted changes were preserved.
- Final: `node frontend/tools/test.mjs` passed 142/142 tests, including public Pages artifact/root/project-path checks. Full output: `frontend/ui-ux-tests.txt`; baseline: `frontend/ui-ux-baseline-tests.txt`.
- Browser: `node frontend/tests/browser-layout.mjs` passed 12 real Chromium layouts: Preview and Multi-epoch at 1920x1080, 1536x864, 1440x900, 1366x768, 768x1024, and 390x844. Output: `frontend/ui-ux-browser-tests.txt`; screenshots and metrics: `frontend/coverage/round4/`.
- Browser tooling: interactive browser host was unavailable; sandboxed Chromium initialization timed out. The same existing offline layout suite succeeded outside the sandbox against localhost fixture servers. No production service was contacted.
- Visually inspected desktop/mobile modal screenshots and Preview/Multi-epoch detail screenshots. Cancel is left, mint Load frames is right with content width, and the long-list footer remains visible. Automated checks also confirm button bounds, same-row placement, and footer visibility after scrolling.
- Modal checks: Load selection validation, disabled/busy behavior, X/Cancel/Escape, focus return, Tab/Shift+Tab containment, scroll lock, retained selection/player, and unchanged Load without requests. Existing Preview/Multi-epoch, Change Selection, Fit, click/slider Zoom, brightness, playback, and failed-slot regression checks pass.
- Missing optional metadata/empty warnings/failure reasons are hidden without blank rows. Preview alignment/compatibility fields are omitted. Missing core fields can retain Not available. Actual Multi-epoch alignment, compatibility (including false), zero counts, quality, failed slots, non-photometric/different-wavelength caveats, and incomplete searches remain visible. Missing values are never interpreted as Pass, Compatible, or No warnings. Empty Scientific limitations is hidden; actual quality/WCS limitations remain.
- Public frontend has no API-origin controls and always uses https://planet-x-spherex.onrender.com. Loopback pages default to http://127.0.0.1:8015. Explicit localhost-only `devApiOrigin` supports existing fixture/custom-port workflows; public pages ignore it. Legacy spherex-api-v1 storage is never read or written. HTTP(S) origin validation and HTTPS mixed-content protection remain. Connection/unexpected-response messages provide English manual-retry guidance and acknowledge possible startup or temporary unavailability without assuming a cause.
- Round-specific source edits: frontend/app.js, frontend/epochs.js, frontend/index.html, frontend/styles.css. Tests: frontend/tests/app.test.mjs, frontend/tests/epochs.test.mjs, frontend/tests/dashboard.test.mjs, frontend/tests/browser-layout.mjs. Documentation: README.md and this report.
- Not verified: physical mobile/touch devices, screen readers, Firefox/Safari, live Render startup/errors, and live NASA observations. Mobile testing uses Chromium viewport emulation. Scientific warnings and API routing use offline fixtures/mocks. No NASA requests or FITS downloads, backend/science/deployment/workflow changes, dependencies, commit, push, or deployment.
