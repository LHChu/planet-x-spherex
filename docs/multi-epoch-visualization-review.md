# Multi-epoch usability and scientific visualization review

Date: 2026-11-15. Scope: Parts A–C implementation; Part D analysis only.

## Implementation and file list

The existing uncommitted dashboard work was retained. No commits, pushes,
deployments, configuration changes, capacity increases or new FITS downloads
were performed. Only official documentation was accessed externally.

| Part | Changes | Files changed in this round |
| --- | --- | --- |
| A | Native Select Observations dialog, automatic opening after populated search, UTC/Detector/status/Details, quick selection, Clear, pagination, visible search warnings, local reopening | `frontend/index.html`, `frontend/styles.css`, `frontend/epochs.js` |
| B | Change Selection beside viewer; cached candidates and selections; identical product sets skip all loading; replacement staged before old images are revoked; cancellation also prevents a pending replacement from replacing the old player; failures and expiry remain explicit | `frontend/epochs.js`, `frontend/tests/epochs.test.mjs` |
| C1 | Linear/Asinh/Log in Preview and epochs, physical Color Bar, shared comparison range versus independent browse ranges | `frontend/brightness.js`, `frontend/color-bar.js`, `frontend/app.js`, `frontend/epochs.js`, `frontend/index.html` |
| C2 | Radius UI default 0.6 arcmin, upper bound 5 arcmin, convert once to degrees in shared payload | `frontend/index.html`, `frontend/app.js`, `frontend/tests/app.test.mjs` |
| C3 | Physical brightness ticks and Pixel Count labels, adaptive tick density; native valid-pixel statistics do not depend on stretch or selected limits | `frontend/brightness.js`, `frontend/app.js`, `frontend/epochs.js`, `frontend/styles.css`, `frontend/index.html` |
| C4 | Expandable English FLAGS table and separate Preview/epoch policies | `frontend/index.html` |
| C5 | RA and Dec degree labels; WCS titles explicitly include degree symbols; WCS mathematics untouched | `frontend/index.html`, `frontend/wcs-axes.js`, `frontend/tests/wcs-axes.test.mjs` |
| C6/D | Source/cutout explanation and capacity assessment | `README.md`, this report |
| Scientific display payload | Add aligned values, existing validity mask, and native IMAGE histogram to frame manifest, using arrays already in memory | `backend/app/epoch_frames.py`, `backend/tests/test_epoch_frames.py` |
| Verification | Numeric/display, modal/cancellation, unit, HTML structure and publication regression checks; browser acceptance extension | `frontend/tests/brightness.test.mjs`, `frontend/tests/color-bar.test.mjs`, `frontend/tests/dashboard.test.mjs`, `frontend/tests/pages.test.mjs`, `frontend/tests/browser-layout.mjs` |

The only backend behavior addition is bounded display metadata. Previously the
browser received only stretched PNGs and NPZ URLs. A PNG cannot recover negative
or full-precision MJy/sr values, so adding controls by transforming PNG grayscale
would be scientifically incorrect. The additive manifest fields avoid NPZ parsing
dependencies or additional artifact requests. The PNG and NPZ generation,
selection validation, FLAGS masking, reprojection, normalization decisions,
limits, URLs and deployment settings remain unchanged. Old cached manifests
without display arrays still show their original PNGs and Color Bars; new epoch
brightness controls stay hidden for those frames.

## Scientific details

Log uses `log1p(1000*t)/log1p(1000)`, where
`t = clip((value - lo)/(hi - lo), 0, 1)`. This operates on a display fraction;
negative and zero physical brightness values remain valid. Non-finite and masked
pixels stay transparent. Input arrays are never mutated. The Color Bar uses the
same mapping, and its ticks remain physical MJy/sr.

Preview retains its existing valid native IMAGE histogram. Epochs display a
histogram of valid native IMAGE values **before reprojection**, while brightness
controls and the Color Bar apply to aligned pixels in MJy/sr. This distinction
appears in the interface. Neither Min/Max nor Stretch recalculates the histogram.
Comparison mode shares ranges across all frames; browse mode retains each frame's
own range. Failed slots are still visited and explained during playback.

Radius was previously `0.01 degrees`, with `0 < radius_deg <= 5/60`.
The UI now starts at `0.6 arcmin` and permits up to `5 arcmin`.
The old HTML minimum is multiplied by 60. The API still accepts `radius_deg`.
No radius is persisted in local storage or parsed from URL parameters by the
current application; saved API origins are unaffected. Existing backend URLs,
replay metadata and fixtures continue to express query radius in degrees.

### FLAGS evidence and unchanged policies

Definitions were read from the [official IRSA image tutorial](https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/)
and [official IRSA Help](https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html),
then cross-checked with the saved `research/outputs/metadata.json` FLAGS header.
Every table name and numerical mask was checked against its `MSKNnnnn` and
`MSKMnnnn` header entries; explanations were compared with `MSKDnnnn` and the
official tutorial. Search snippets were not used as the sole evidence.

Preview excludes Bit indices 1, 2, 6, 9, 15 and 19, corresponding to masks 2, 4,
64, 512, 32768 and 524288. Other set bits remain quality information, and valid
flagged pixels may be highlighted in orange. This is a project display policy,
not an official recommendation for photometric selection.

Epochs inspect actual FITS definitions and allow only masks named SOURCE and
FULLSAMPLE; all other set bits, including unknown ones, reject a native pixel.
The reference header identifies SOURCE as Bit 21 / mask 2097152 and FULLSAMPLE as
Bit 12 / mask 4096. The current implementation trusts the masks declared in the
individual header, rather than using the reference table to redefine them.
`flags_or` must be interpreted with the independent validity mask and weights.

Pending scientific confirmation: definitions in later releases, unlisted bits,
or missing/inconsistent header definitions must be checked against that release's
FITS header and official documentation. No new science-quality policy was inferred
and no masking logic was changed. The interface lists each frame's definitions
under Advanced Metadata.

## Verification

First A/B batch: **117/117 frontend offline tests passed**.

Final frontend suite: **126/126 passed**, no skips, using
`node frontend/tools/test.mjs`. See `frontend/phase6-tests.txt`.
Coverage includes:

- Populated/empty search, automatic opening, X/Cancel/Escape handlers, focus
  restoration and scroll-lock cleanup in the DOM harness, Clear, reopening,
  same-Detector/distinct-exposure/unique-ID and 2–3 selection behavior.
- No new search on Change Selection; identical sets make no manifest or PNG
  requests; changed sets follow the existing frame endpoint.
- Cancel while replacing prevents installing a late manifest and avoids starting
  its PNG downloads; closing without Load preserves the running player.
- API failure, expiry and all-failed replacement preserve successful old images.
  All-failed replacement diagnostics are listed explicitly in Advanced Metadata.
- Locally known expired snapshots never reach the frame API; server-reported
  expiry disables loading and requests an explicit new search.
- Log with negative/zero/nonfinite/null/flag-masked values, endpoints and clipping;
  Color Bar agreement for all three stretches and inversion.
- Shared and independent epoch ranges, unchanged Histogram across controls,
  invalid range preservation, unit conversion and boundaries.
- English UI, responsive dialog CSS structure, WCS alignment, and local Pages
  artifact tests. The external documentation anchor is verified but never fetched
  by offline tests.

Backend: **100 tests run: 99 passed, one existing live NASA test skipped**;
`python -m backend.tests.run_offline` exited 0 with external socket access denied.
See `backend/phase6-tests.txt`. New coverage compares manifest values/masks to NPZ,
native histogram counts/edges to NumPy, shared limits, and request counts on cache
reuse. Existing PNG, WCS, FLAGS, selection, capacity and failure tests passed.
Existing Astropy SIP/BLANK and Starlette deprecation warnings remain; they were
not suppressed or addressed by changing scientific calculations.

### Browser acceptance status

The extended `frontend/tests/browser-layout.mjs` is provided for six viewport sizes
(1920, 1536, 1440, 1366, 768 and 390 pixels wide), long modal lists, centering,
Tab/Shift+Tab containment, Escape, focus return, scroll locking and reopening with
zero interaction requests. **These real-browser checks did not complete in this
environment**: both Chromium engines timed out at `Runtime.enable`, before page
interaction. No screenshots from this round establish a visual pass.

The computer-use browser host was also unavailable. Automatic approval review
rejected inspecting an existing Chrome window on an unrelated page because of
possible access to private content. That operation was stopped. An authorized
dedicated local test window, or a working headless browser connection, is needed
to finish the visual/keyboard acceptance checks. Native `<dialog>` supplies modal
focus containment and background inertness; DOM tests do not substitute for a
real keyboard or assistive-technology check.

Remaining manual checks: keyboard and screen-reader behavior across target
browsers, 390px and tablet long-table readability, reopening from the viewer,
and actual NASA release-specific pixel/mask/WCS confirmation after separate
authorization. No NASA service was queried for data during this round.

## Larger cutouts and additional epochs: analysis only

### Current independent limits

- Preview `MAX_IMAGE_PIXELS = 262144` checks IMAGE dimensions before reading the
  array. It allows at most 512x512 for square IMAGE data, not a full 2040x2040
  detector image. This is not a bound on all HDUs, RSS or decompression buffers.
- Preview client arrays are limited separately to 65536 pixels and 4 MiB JSON;
  otherwise PNG-only fallback remains available.
- Epoch native IMAGE/FLAGS must match and be <=128 pixels on each axis.
  This is independent of Preview's MAX_IMAGE_PIXELS. Epoch output remains a fixed
  29x29 grid at 6.15 arcsec/pixel.
- Frame request validation remains 2–3 products. Processing is sequential, while
  completed arrays are retained for pair diagnostics/common normalization.
- Downloads retain 32 MiB per cutout, 16 total HTTP attempts, three attempts per
  URL, 20-second socket timeout and cooperative 120-second work budget.
- Serialized caches: preview PNGs 16 MiB, metadata 8 MiB, sequences 8 MiB.
  Sequence manifests plus PNG and NPZ blobs share the 8 MiB/16-entry bound and
  atomic eviction. Full/failed sequence TTLs remain 600/60 seconds.

### Candidate sizes

The approximate angular side is `pixels * 6.15 / 60` arcmin at the current output
scale. Source WCS/distortion, detector edges and IRSA rounding affect native size.
The table is analytical, not a benchmark or a proposed limit change.

| Square size | Approximate side | Preview dimension/client-pixel limits | Epoch implications |
| --- | ---: | --- | --- |
| 64x64 | 6.56 arcmin | Within both pixel limits; JSON byte cap still applies | Native axes within 128; request side and output grid would both need deliberate changes |
| 128x128 | 13.12 arcmin | Within both pixel limits; JSON byte cap still applies | At native axis limit; rounding can exceed it; current output stays 29x29 |
| 256x256 | 26.24 arcmin | At client pixel limit; JSON may exceed 4 MiB | Rejected by native axis cap; cannot be enabled by changing MAX_IMAGE_PIXELS alone |

Increasing Radius alone changes none of these sizes. None of the sizes in this
table were requested from NASA, and no dimensional or download cap was raised.

### Memory costs from the actual array types

Let N be native pixels and M aligned output pixels. The retained NPZ arrays use
approximately `13*N + 29*M` bytes when native IMAGE is float32:

| Arrays | Bytes per pixel |
| --- | ---: |
| native IMAGE / FLAGS / valid | 4 / 8 / 1 per N |
| aligned IMAGE / valid_mask | 4 / 1 per M |
| valid_weight / geometric_weight / flags_or | 8 / 8 / 8 per M |
| decoded PNG RGBA | additional 4 per M |

Float64 native images add another 4*N. Unicode WCS headers, dictionary/object
overhead, JSON values/masks, compression workspaces, FITS read copies and the
Astropy baseline are extra. Bilinear interpolation and WCS create multiple
float64 coordinate/result/weight arrays plus integer indices and masks. They are
temporary but can dominate the retained arrays. No static multiplier here is a
guaranteed peak-RSS bound. The implementation reads only required IMAGE/FLAGS and
spectral tables, not the complete EPSF array; the downloaded FITS file can still
contain additional HDUs. File-byte and IMAGE-pixel caps are not total RAM caps.

If native and output shapes were both enlarged, the retained numeric arrays alone
would be approximately:

| Size | Per frame (42 bytes/pixel) | Five frames |
| --- | ---: | ---: |
| 64x64 | 0.164 MiB | 0.820 MiB |
| 128x128 | 0.656 MiB | 3.281 MiB |
| 256x256 | 2.625 MiB | 13.125 MiB |

NPZ uses compression, so actual cache bytes depend on data entropy and headers.
Five 256x256 frames already exceed the sequence cache on an uncompressed numeric
estimate, before manifests/PNGs; compression cannot be assumed to rescue it.

A bounded **two-frame 29x29 synthetic** sample was measured (no stress test):
35,322 numeric bytes/frame, 34,560 Unicode WCS-header bytes/frame, NPZ 5,103/5,104
bytes, PNG 332 bytes each, and approximately 56 KB of JSON manifest including new
display data. See `backend/phase6-memory-sample.json`. This smooth synthetic image
compresses unusually well and is not a prediction for real FITS or larger fields.
These are artifact and array sizes, not measured peak process RSS.

### More epochs, Render Free and frontend

Under the supplied 512 MB RAM / single-worker constraint, cached serialized bytes
do not describe available working memory. Python/Astropy baseline, simultaneous
cached sequences, JSON encoding/copies and transient WCS arrays all consume RAM.
One heavy-work lock protects processing, but does not eliminate other request or
response memory. More workers would duplicate baseline memory and process-local
caches; this is not a safe route to expanding the current workload.

Going from three to five frames increases retained image/display data and typical
downloads by about 5/3. Pair comparisons grow from three to ten pairs, with
`k*(k-1)/2` scaling; larger grids also increase peak finding and interpolation
work. Shared normalization concatenates accepted samples. Keeping the current
120-second/16-attempt budget means more failure slots under slow upstream or
retry conditions; raising the frame count alone cannot promise five successes.
Cold start, upstream latency, CPU and the frontend's 180-second wait all matter.

Frontend memory includes the manifest's ordinary JS arrays, decoded PNGs, blobs,
canvas RGBA buffers and data URLs. Replacement temporarily retains both old and
new sequences so failure can preserve the old view. Playback performs no network
requests, but applying a changed stretch creates a canvas rendering when a frame
is shown. Five or larger frames would need measured caching of transformed frames
and explicit byte budgets. Failed slots must remain visible; expired artifacts
must continue to require explicit recovery instead of silent retry loops.

### Safe follow-up method

1. Start with generated finite/noisy/constant/NaN/masked FITS at 64, 128 and 256
   square pixels in an isolated test process. Test rejection boundaries separately
   from any experimental processing branch. Do not change production limits.
2. Measure process baseline and peak RSS (including native allocations), elapsed
   download/decode/reproject/PNG/NPZ/JSON times and artifact sizes. Python
   `tracemalloc` alone does not capture all NumPy/Astropy/native allocations.
3. Test 2, 3 and experimental 5-frame processing separately: shared/browse modes,
   pair checks, common masks, partial/all failures, cancellation, busy responses,
   deadline exhaustion and atomic cache eviction. Use incompressible noise as
   well as smooth images. Test old-plus-pending frontend memory explicitly.
4. Verify health responsiveness and memory headroom under a single 512 MB worker;
   include populated caches and JSON response serialization in the measurement.
   Determine an explicit margin below OOM from measured peaks, not array sums.
5. Only after offline measurements and review, authorize a small number of live
   cutout requests to verify real response sizes, HDU layouts, rounding and actual
   latency. Do not start with broad FITS downloads or load tests on Render Free.

Recommendation: retain 29x29/three frames for the deployed path for now. Evaluate
64x64 first, then 128x128 only with measured headroom. Treat 256x256 and five or
more epochs as separate capacity/science-policy work, potentially requiring a
larger service or queued jobs rather than changing constants.
