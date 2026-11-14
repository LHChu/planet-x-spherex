/* Existing preview/PNG endpoints plus bounded raw-pixel display metadata. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const localPage = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  const defaults = { local: "http://127.0.0.1:8000", render: window.SPHEREX_CONFIG?.renderApiBase || "" };
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("spherex-api-v1")) || {}; } catch { /* Storage may be unavailable. */ }
  let environment = localPage && saved.environment === "local" ? "local" : localPage && !saved.environment ? "local" : "render";
  const bases = { ...defaults, ...saved.bases };
  let result = null, mode = "black", busy = false, scienceDisplay = null, wcsAxes = null, previewMetadata = null, colorScale = null;
  function colorBar() {
    const axes = window.SpherexAxes.layout(wcsAxes, $("preview").naturalWidth, $("preview").naturalHeight, Number($("zoom").value));
    const size = window.SpherexColorBar.render($("preview-colorbar"), colorScale, axes,
      "Transparent/masked pixels excluded. Orange FLAGS: quality only.");
    $("preview-stage").style.width = `${size.width}px`; $("preview-stage").style.height = `${size.height}px`;
  }
  function redrawBrightness() {
    if (!scienceDisplay) return;
    try {
      const loText = $("minimum-number").value.trim(), hiText = $("maximum-number").value.trim();
      if (!loText || !hiText) throw Error("Enter a minimum and maximum.");
      const lo = Number(loText), hi = Number(hiText);
      const pixels = window.SpherexBrightness.rgba(scienceDisplay, lo, hi, $("stretch").value, mode === "white", $("quality-overlay").checked);
      const canvas = document.createElement("canvas");
      [canvas.height, canvas.width] = scienceDisplay.shape;
      const context = canvas.getContext("2d"), frame = context.createImageData(canvas.width, canvas.height);
      frame.data.set(pixels); context.putImageData(frame, 0, 0);
      $("preview").src = canvas.toDataURL("image/png");
      for (const id of ["minimum", "maximum"]) {
        $(id).min = Math.min(scienceDisplay.min, scienceDisplay.lo, lo);
        $(id).max = Math.max(scienceDisplay.max, scienceDisplay.hi, hi);
      }
      $("minimum").value = lo; $("maximum").value = hi;
      $("brightness-status").textContent = `${$("stretch").value} · ${lo} – ${hi} MJy/sr`;
      colorScale = window.SpherexColorBar.preview(previewMetadata, { lo, hi, stretch: $("stretch").value }, mode === "white");
      colorBar();
      return true;
    } catch (error) { $("brightness-status").textContent = error.message; return false; }
  }
  function resetBrightness() {
    if (!scienceDisplay) return;
    $("minimum-number").value = String(scienceDisplay.lo);
    $("maximum-number").value = String(scienceDisplay.hi);
    $("stretch").value = "linear";
    redrawBrightness();
  }
  function setupBrightness(display) {
    scienceDisplay = display?.available && window.SpherexBrightness ? display : null;
    $("brightness").hidden = !scienceDisplay;
    $("display-note").textContent = scienceDisplay ? "Invalid pixels are transparent. The viewport background does not represent a valid zero value." : display?.reason || "This API provides a PNG preview only.";
    if (!scienceDisplay) {
      colorScale = window.SpherexColorBar.preview(previewMetadata, null, mode === "white"); colorBar(); return;
    }
    const { counts, edges } = display.histogram;
    const canvas = $("histogram"), context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    const peak = Math.max(1, ...counts), w = canvas.width / counts.length;
    context.fillStyle = "#63c9da";
    counts.forEach((n, i) => context.fillRect(i * w, canvas.height - n / peak * canvas.height, Math.max(1, w - 1), n / peak * canvas.height));
    $("histogram-range").textContent = `Horizontal: ${edges[0]} – ${edges.at(-1)} MJy/sr; vertical: 0 – ${peak} pixels; total ${counts.reduce((a, b) => a + b, 0)}. ${display.fallback ? `Range safeguard: ${display.fallback}` : ""}`;
    resetBrightness();
  }
  for (const id of ["minimum", "maximum"]) $(id).addEventListener("input", () => { $(id + "-number").value = $(id).value; redrawBrightness(); });
  for (const id of ["minimum-number", "maximum-number", "stretch", "quality-overlay"]) $(id).addEventListener("change", redrawBrightness);
  $("reset-brightness").addEventListener("click", resetBrightness);
  $("environment").value = environment;
  $("api-url").value = bases[environment] || "";

  function persist() {
    bases[environment] = $("api-url").value.trim();
    try { localStorage.setItem("spherex-api-v1", JSON.stringify({ environment, bases })); } catch { /* The form still works. */ }
  }
  $("api-url").addEventListener("change", persist);
  $("environment").addEventListener("change", () => {
    persist(); environment = $("environment").value;
    $("api-url").value = bases[environment] || ""; persist();
  });
  function status(message, state = "idle") {
    $("status").textContent = message;
    $("status").dataset.state = state;
  }
  function apiBase() {
    const raw = $("api-url").value.trim();
    if (!raw) throw new Error("Enter the HTTPS URL of your Render backend.");
    let url;
    try { url = new URL(raw); } catch { throw new Error("Invalid API URL. Enter a complete http(s) URL."); }
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || !/^\/*$/.test(url.pathname)) {
      throw new Error("Enter an http(s) API base URL without a path, credentials, or query parameters.");
    }
    const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if (!localPage && loopback) throw new Error("A public frontend cannot use your local backend. Use a Render HTTPS URL.");
    if ((environment === "render" || location.protocol === "https:") && url.protocol !== "https:") {
      throw new Error("Render and HTTPS frontends require an HTTPS API to avoid mixed-content blocking.");
    }
    return url.origin;
  }
  function payload() {
    const values = ["ra", "dec", "radius"].map(id => $(id).value.trim());
    const [ra, dec, radius_deg] = values.map(Number);
    if (values.some(v => !v) || ![ra, dec, radius_deg].every(Number.isFinite) || ra < 0 || ra >= 360 || dec < -90 || dec > 90 || radius_deg <= 0 || radius_deg > 5 / 60) {
      throw new Error("Check coordinates: 0 ≤ RA < 360 and −90 ≤ Dec ≤ 90. The radius must be greater than 0 and at most 5/60 degrees.");
    }
    const detector = $("detector").value;
    if (detector && !/^[1-6]$/.test(detector)) throw new Error("Select Auto or D1–D6.");
    return detector ? { ra, dec, radius_deg, detector: Number(detector) } : { ra, dec, radius_deg };
  }
  function controls() {
    $("brightness").disabled = busy || !scienceDisplay;
    for (const id of ["black", "white", "zoom"]) $(id).disabled = busy || !result;
    for (const id of ["search", "environment", "api-url", "detector", "explorer-mode"]) $(id).disabled = busy;
    $("search").textContent = busy ? "Fetching NASA images…" : "Search NASA images ↗";
    $("viewport").setAttribute("aria-busy", String(busy));
  }
  function zoom() {
    const factor = Number($("zoom").value);
    $("zoom-value").textContent = `${factor}×`;
    $("preview").style.width = `${$("preview").naturalWidth * factor}px`;
    $("preview").style.height = `${$("preview").naturalHeight * factor}px`;
    const axes = window.SpherexAxes.render($("preview-axes"), wcsAxes, $("preview").naturalWidth, $("preview").naturalHeight, factor);
    $("preview").style.left = `${axes.margin.left}px`; $("preview").style.top = `${axes.margin.top}px`;
    colorBar();
  }
  $("zoom").addEventListener("input", zoom);
  function imageUrl(base, value) {
    // Keep image requests on the chosen API. Reverse proxies may return an
    // internal HTTP hostname; only the endpoint path is needed by this client.
    const url = new URL(value, base);
    if (!/^\/api\/images\/[0-9a-f]{32}(?:-inverse)?\.png$/.test(url.pathname)) throw new Error("The API returned an invalid PNG path.");
    return base + url.pathname;
  }
  function loadImage(url) {
    return new Promise((resolve, reject) => {
      const img = $("preview");
      const timer = setTimeout(() => { clean(); img.removeAttribute("src"); reject(new Error("PNG loading timed out. Search again.")); }, 30000);
      function clean() { clearTimeout(timer); img.onload = null; img.onerror = null; }
      img.onload = () => { clean(); resolve(); };
      img.onerror = () => { clean(); reject(new Error("Could not load the PNG. The cache may have expired or the backend may have restarted. Search again.")); };
      img.src = url;
    });
  }
  function metadata(data) {
    const m = data.metadata, sia = m.sia || {};
    const rows = [
      ["Observation start (UTC)", m.t_min_utc], ["Observation end (UTC)", m.t_max_utc],
      ["Observation time (MJD)", `${sia.t_min ?? "—"} → ${sia.t_max ?? "—"}`],
      ["Detector", m.detector ?? sia.detector], ["Observation ID", sia.obs_id],
      ["Requested Detector", m.requested_detector == null ? "Auto" : `D${m.requested_detector}`],
      ["FITS observation start (UTC)", m.observation?.["DATE-OBS"]],
      ["Band", sia.energy_bandpassname],
      ["Band range (μm)", sia.em_min != null && sia.em_max != null ? `${sia.em_min * 1e6} – ${sia.em_max * 1e6}` : null],
      ["WCS target position (zero-based FITS pixels)", m.target_pixel_xy?.join(", ")],
      ["Target pixel wavelength / bandwidth (μm)", m.target_spectral?.available && m.target_spectral.units?.every(u => u === "um") ? `${m.target_spectral.wavelength} / ${m.target_spectral.bandwidth}` : null],
      ["Valid / Finite pixels", m.valid_pixels == null ? null : `${m.valid_pixels} / ${m.finite_pixels}`],
      ["Collection", sia.obs_collection], ["Exposure time", sia.t_exptime == null ? null : `${sia.t_exptime} s`],
      ["Query coordinates (degrees)", `RA ${m.query?.ra ?? "—"} / Dec ${m.query?.dec ?? "—"}`],
      ["Image dimensions", `${$("preview").naturalWidth} × ${$("preview").naturalHeight} px`],
      ["Cutout side length", m.cutout_size], ["Original PNG stretch", m.stretch?.method],
      ["Processing version", m.version], ["Image orientation", m.orientation],
      ["Search truncated", m.truncated == null ? null : m.truncated ? "Yes; only some candidates are shown" : "No"],
      ["Cache lifetime", `${data.expires_in_seconds ?? "—"} seconds; may be evicted early. Search again after expiry`]
    ];
    $("metadata").replaceChildren();
    for (const [label, value] of rows) {
      const dt = document.createElement("dt"), dd = document.createElement("dd");
      dt.textContent = label; dd.textContent = value ?? "Not available";
      $("metadata").append(dt, dd);
    }
    $("raw-metadata").textContent = JSON.stringify(m, null, 2);
    $("info").hidden = false;
  }
  function display() {
    if (!scienceDisplay) colorScale = window.SpherexColorBar.preview(previewMetadata, null, mode === "white");
    $("preview-stage").hidden = false;
    $("preview").hidden = false; $("placeholder").hidden = true;
    $("viewport").classList.toggle("light", mode === "white");
    $("black").setAttribute("aria-pressed", String(mode === "black"));
    $("white").setAttribute("aria-pressed", String(mode === "white"));
    $("image-size").textContent = `PNG · ${$("preview").naturalWidth} × ${$("preview").naturalHeight}`;
    zoom();
  }
  async function switchMode(next) {
    if (!result || busy || next === mode) return;
    if (scienceDisplay) { const previous = mode; mode = next; if (redrawBrightness()) display(); else mode = previous; return; }
    busy = true; controls(); $("preview").hidden = true;
    status("Switching PNG…", "loading");
    try { await loadImage(next === "black" ? result.black : result.white); mode = next; display(); status("Image loaded. Switch display modes or adjust zoom.", "success"); }
    catch (e) { result = null; $("preview-stage").hidden = true; $("info").hidden = true; $("placeholder").hidden = false; $("image-size").textContent = "PNG · —"; status(e.message, "error"); }
    finally { busy = false; controls(); }
  }
  $("black").addEventListener("click", () => switchMode("black"));
  $("white").addEventListener("click", () => switchMode("white"));
  $("search-form").addEventListener("submit", async event => {
    event.preventDefault(); if (busy) return;
    if (window.SpherexEpochs?.active()) return window.SpherexEpochs.search();
    let base, body;
    try { base = apiBase(); body = payload(); persist(); } catch (e) { status(e.message, "error"); return; }
    busy = true; result = null; scienceDisplay = null; $("brightness").hidden = true; $("display-note").textContent = ""; controls();
    wcsAxes = null; $("preview-stage").hidden = true; $("preview-axes").replaceChildren();
    previewMetadata = null; colorScale = null; $("preview-colorbar").replaceChildren();
    $("preview").hidden = true; $("info").hidden = true; $("placeholder").hidden = false;
    $("viewport").classList.remove("light"); $("image-size").textContent = "PNG · —";
    status("Querying NASA and generating a PNG. This may take a few minutes; a Render cold start may add to the wait.", "loading");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 180000);
    try {
      const response = await fetch(`${base}/api/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: controller.signal, credentials: "omit" });
      let data;
      try { data = await response.json(); } catch { throw new Error(`The API returned invalid JSON (HTTP ${response.status}). Check the URL and service status.`); }
      if (!response.ok) {
        const code = data.error?.code;
        if (code === "no_images") { status("No images found in this search area. Adjust the coordinates or radius and try again.", "empty"); return; }
        const retry = response.headers.get("Retry-After");
        const hint = code === "busy" ? `The backend is busy. ${retry ? `Wait as specified by Retry-After (${retry})` : "Wait a moment"}, then retry manually.` : data.error?.message || "API request failed";
        throw new Error(`${hint} (HTTP ${response.status}${code ? ` / ${code}` : ""})`);
      }
      if (!data.metadata || typeof data.metadata !== "object" || !data.image_url || !data.inverted_image_url) throw new Error("The API response is missing images or metadata.");
      const images = { black: imageUrl(base, data.image_url), white: imageUrl(base, data.inverted_image_url) };
      await loadImage(mode === "black" ? images.black : images.white);
      wcsAxes = data.metadata.wcs_axes;
      previewMetadata = data.metadata;
      result = images; $("preview").alt = `SPHEREx infrared observation at RA ${body.ra}°, Dec ${body.dec}°`;
      display(); metadata(data); setupBrightness(data.metadata.display); status("Image loaded. Switch display modes or adjust zoom.", "success");
    } catch (e) {
      status(e.name === "AbortError" ? "The API did not respond within 180 seconds. Retry later; backend processing may still be running." : e instanceof TypeError ? "Could not connect to the API. Check that the backend is running, the URL is correct, and CORS_ORIGINS allows this frontend origin." : e.message, "error");
    } finally { clearTimeout(timer); busy = false; controls(); }
  });
  window.SpherexEpochs?.mount({ apiBase, payload, persist });
})();
