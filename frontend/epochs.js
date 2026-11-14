/* Bounded multi-epoch viewer. PNGs are fetched once per explicit Load frames. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  let context, snapshot = null, query = null, base = "", cursor = null, working = false;
  let products = [], selected = new Set(), slots = [], position = 0, timer = null, wcsAxes = null, sequenceDisplay = null;
  const active = () => $("explorer-mode").value === "epochs";
  const sources = p => (p.source_collections || [p.obs_collection]).filter(Boolean).join(", ") || "Not available";
  const mjdTime = p => Number.isFinite(p.t_min) ? new Date((p.t_min - 40587) * 86400000).toISOString() : "Time not available";
  const date = p => p.observation_utc || mjdTime(p);
  const order = (a, b) => {
    const time = p => Number.isFinite(Date.parse(p.observation_utc)) ? Date.parse(p.observation_utc) : Number.isFinite(p.t_min) ? (p.t_min - 40587) * 86400000 : Infinity;
    return time(a) - time(b) || a.product_id.localeCompare(b.product_id);
  };
  const exposure = p => typeof p.obs_id === "string" ? p.obs_id.trim() : "";
  const eligible = p => [1, 2, 3, 4, 5, 6].includes(p.detector)
    && typeof p.product_id === "string" && p.product_id.trim()
    && exposure(p) && !/^(unknown(?:[-_ ].*)?|未知|n\/a|null|none|undefined)$/i.test(exposure(p));
  function visibleProducts() {
    if (!snapshot) return [];
    const chosen = products.filter(p => selected.has(p.product_id));
    const compatible = products.filter(p => eligible(p) && (!chosen.length || p.detector === chosen[0].detector));
    const representatives = new Map();
    // Preserve a selected representative across pagination; otherwise use the
    // first returned product, without implying scientific version preference.
    for (const p of [...compatible.filter(p => selected.has(p.product_id)), ...compatible]) {
      if (!representatives.has(exposure(p))) representatives.set(exposure(p), p);
    }
    return [...representatives.values()].filter(p => selected.has(p.product_id) || chosen.length < 3).sort(order);
  }
  function firstProducts(count) {
    const visible = visibleProducts();
    return visible.filter(p => p.detector === visible[0]?.detector).slice(0, count);
  }
  function selectFirst(count) {
    if (working || !snapshot) return;
    const first = firstProducts(count);
    if (first.length !== count) return;
    selected = new Set(first.map(p => p.product_id));
    renderProducts(); controls();
  }
  function status(message, error = false) {
    $("epochs-status").textContent = message;
    $("epochs-status").dataset.state = error ? "error" : "idle";
  }
  function pause() {
    clearInterval(timer); timer = null;
    $("epoch-play").textContent = "Play"; $("epoch-play").setAttribute("aria-pressed", "false");
  }
  function clearFrames() {
    pause();
    for (const slot of slots) if (slot.url) URL.revokeObjectURL(slot.url);
    slots = []; position = 0;
    wcsAxes = null; $("epoch-image").replaceChildren(); $("epoch-axes").replaceChildren(); $("epoch-player").hidden = true;
    sequenceDisplay = null; $("epoch-colorbar").replaceChildren();
  }
  function controls() {
    for (const id of ["search", "environment", "api-url", "detector", "explorer-mode", "ra", "dec", "radius"]) $(id).disabled = working;
    $("search").textContent = working ? "Processing multi-epoch data…" : active() ? "Search epochs" : "Search NASA images ↗";
    $("load-frames").disabled = working || !snapshot || selected.size < 2;
    $("epochs-more").disabled = working || !cursor;
    for (const count of [2, 3]) $("select-first-" + count).disabled = working || firstProducts(count).length !== count;
    $("epoch-products").setAttribute("aria-busy", String(working));
  }
  function renderProducts() {
    $("epoch-products").replaceChildren();
    const visible = visibleProducts();
    for (const p of visible) {
      const tr = document.createElement("tr"), cell = document.createElement("td"), check = document.createElement("input");
      check.type = "checkbox"; check.checked = selected.has(p.product_id);
      check.setAttribute("aria-label", `${date(p)} D${p.detector} ${p.obs_id || p.product_id}`);
      check.disabled = working;
      check.addEventListener("change", () => {
        if (working || check.disabled) return;
        if (check.checked) selected.add(p.product_id); else selected.delete(p.product_id);
        renderProducts(); controls();
      });
      cell.append(check); tr.append(cell);
      for (const value of [date(p), p.detector == null ? "Unknown" : `D${p.detector}`, `${sources(p)} · ${p.obs_id || "Unknown exposure (unavailable for selection)"} · ${p.product_id} · ${p.frame_status || "not_requested"} · ${p.calibration_status || ""} · ${(p.warnings || []).join(", ")}`]) {
        const td = document.createElement("td"); td.textContent = value; tr.append(td);
      }
      $("epoch-products").append(tr);
    }
    $("epoch-selection").textContent = `Selected ${selected.size} / 3; showing ${visible.length} available exposures. One product represents each exposure. Unavailable candidates are hidden; deselect a product to show other candidates. Quick selection replaces the selection with the first 2 or 3 exposures on the first visible product’s Detector. Select Load frames to update the player.`;
    $("epochs-more").hidden = !cursor;
  }
  async function request(path, body, png = false) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), png ? 30000 : 180000);
    try {
      const response = await fetch(base + path, { method: png ? "GET" : "POST", headers: png ? {} : { "Content-Type": "application/json" }, ...(png ? {} : { body: JSON.stringify(body) }), signal: controller.signal, credentials: "omit" });
      if (png && response.ok) return await response.blob();
      let data;
      try { data = await response.json(); } catch { throw Error(`The API returned invalid JSON (HTTP ${response.status}).`); }
      if (!response.ok) {
        const code = data.error?.code || "request_failed", retry = response.headers.get("Retry-After");
        const error = Error(`${data.error?.message || "Request failed"} (HTTP ${response.status} / ${code})${retry ? `; Retry-After: ${retry}. Wait, then retry manually.` : ""}`);
        error.code = code; throw error;
      }
      return data;
    } finally { clearTimeout(timeout); }
  }
  function message(error) {
    if (["search_expired", "invalid_cursor", "frame_not_found"].includes(error.code)) return `${error.message}; the search or frame cache has expired. Search epochs again, select products, then select Load frames.`;
    if (error.name === "AbortError") return "The request timed out. Backend processing may still be running. Retry manually later.";
    if (error instanceof TypeError) return "Could not connect to the API. Check the backend URL, network, and CORS settings.";
    return error.message;
  }
  async function search(more = false) {
    if (working) return;
    pause();
    if (!more) {
      clearFrames(); snapshot = null; cursor = null; products = []; selected.clear();
      $("epochs-sources").textContent = "";
    }
    try {
      if (!more) {
        base = context.apiBase(); const { detector, ...coordinates } = context.payload();
        query = { ...coordinates, ...(detector ? { detectors: [detector] } : {}), limit: 100 }; context.persist();
      }
      working = true; controls(); renderProducts(); status("Searching epoch metadata without downloading FITS…");
      const data = await request("/api/epochs/search", { ...query, ...(more ? { cursor } : {}) });
      if (!data.search_id || !Array.isArray(data.products) || (more && data.search_id !== snapshot)) throw Error("The API search response is missing products or has an inconsistent snapshot. Search again.");
      snapshot = data.search_id; cursor = data.pagination?.next_cursor || null;
      const merged = new Map(products.map(p => [p.product_id, p]));
      data.products.forEach(p => merged.set(p.product_id, p)); products = [...merged.values()];
      $("epochs-sources").textContent = `Search snapshot: RA ${query.ra} / Dec ${query.dec} / radius ${query.radius_deg}° · ${base}. Sources: ${(data.collections || []).map(c => `${c.name}: ${c.status}${c.truncated ? " (truncated)" : ""}${c.error ? ` ${JSON.stringify(c.error)}` : ""}`).join("; ")}. Snapshot expires: ${data.expires_at || "Not available"}. ${data.complete === false ? "Search incomplete; only retrieved candidates are shown." : ""}`;
      status(products.length ? `Found ${products.length} products${cursor ? "; more epochs are available" : ""}. Select products manually.` : "No observation products are available in this area.");
    } catch (error) {
      if (["search_expired", "invalid_cursor"].includes(error.code)) { snapshot = null; cursor = null; }
      status(message(error), true);
    } finally { working = false; renderProducts(); controls(); }
  }
  function describe(slot) {
    const f = slot.frame;
    return `slot ${f.index} · ${date(f)} UTC · ${f.time_source || "sia_t_min"} · D${f.detector} · λ ${f.target_wavelength_um ?? "Not available"} μm / bandwidth ${f.target_bandwidth_um ?? "Not available"} μm · ${sources(f)} · ${f.obs_id} · ${f.product_id} · ${f.status} · alignment: ${f.alignment?.status || "Not assessed"}${slot.error ? ` · ${slot.error}` : ""}`;
  }
  function zoom() {
    const factor = Number($("epoch-zoom").value);
    $("epoch-zoom-value").textContent = `${factor}×`;
    for (const slot of slots) if (slot.image) {
      slot.image.style.width = `${slot.image.naturalWidth * factor}px`;
      slot.image.style.height = `${slot.image.naturalHeight * factor}px`;
    }
    const current = slots[position];
    if (current) {
      const [height, width] = current.image ? [current.image.naturalHeight, current.image.naturalWidth] : wcsAxes?.shape_yx || [29, 29];
      $("epoch-image").style.width = `${width * factor}px`; $("epoch-image").style.height = `${height * factor}px`;
      const axes = window.SpherexAxes.render($("epoch-axes"), wcsAxes, width, height, factor);
      $("epoch-image").style.left = `${axes.margin.left}px`; $("epoch-image").style.top = `${axes.margin.top}px`;
      const scale = current.image ? window.SpherexColorBar.epoch(sequenceDisplay, current.frame) : null;
      const note = sequenceDisplay?.mode === "comparable_visualization"
        ? "Shared mapping; visual comparison only, not photometry. Transparent/masked pixels excluded."
        : "Per-frame mapping; do not compare brightness between frames. Transparent/masked pixels excluded.";
      const size = window.SpherexColorBar.render($("epoch-colorbar"), scale, axes, note);
      $("epoch-stage").style.width = `${size.width}px`; $("epoch-stage").style.height = `${size.height}px`;
    }
  }
  function show(next) {
    if (!slots.length) return;
    position = (next + slots.length) % slots.length;
    $("epoch-time").value = String(position);
    $("epoch-position").textContent = `${position + 1} / ${slots.length} · ${date(slots[position].frame)}`;
    $("epoch-current").textContent = describe(slots[position]);
    $("epoch-image").replaceChildren(slots[position].image || slots[position].placeholder);
    zoom();
  }
  function play() {
    pause(); if (slots.length < 2 || !slots.some(s => s.image)) return;
    $("epoch-play").textContent = "Pause"; $("epoch-play").setAttribute("aria-pressed", "true");
    timer = setInterval(() => show(position + 1), Number($("epoch-speed").value));
  }
  async function loadPng(frame, sequenceId) {
    if (!frame.image_url) throw Error(`${frame.error?.code || "frame_failed"}: ${frame.error?.message || "No PNG is available for this slot"}`);
    const path = new URL(frame.image_url, base).pathname;
    if (path !== `/api/epoch-frames/${sequenceId}/${frame.index}.png` || !/^[0-9a-f]{32}$/.test(sequenceId)) throw Error("The API returned an invalid frame PNG path.");
    const blob = await request(path, null, true), url = URL.createObjectURL(blob), img = document.createElement("img");
    img.alt = `PNG reprojected to WCS by the backend · ${date(frame)} · ${frame.obs_id}`;
    try {
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => { cleanup(); reject(Error("PNG decoding timed out. Search again.")); }, 30000);
        function cleanup() { clearTimeout(timeout); img.onload = null; img.onerror = null; }
        img.onload = () => { cleanup(); resolve(); };
        img.onerror = () => { cleanup(); reject(Error("Could not decode the PNG. Search again.")); };
        img.src = url;
      });
      return { image: img, url };
    } catch (error) { URL.revokeObjectURL(url); throw error; }
  }
  async function load() {
    if (working || !snapshot || selected.size < 2 || selected.size > 3) return;
    const chosen = products.filter(p => selected.has(p.product_id)).sort(order);
    if (chosen.length !== selected.size || chosen.some(p => !eligible(p) || p.detector !== chosen[0].detector) || new Set(chosen.map(exposure)).size !== chosen.length) return;
    clearFrames(); working = true; controls(); renderProducts(); status("Loading selected frames. FITS processing may take a few minutes…");
    try {
      const data = await request("/api/epoch-frames", { search_id: snapshot, product_ids: chosen.map(p => p.product_id) });
      if (data.search_id !== snapshot || !Array.isArray(data.frames) || data.frames.length !== chosen.length || data.frames.some((f, i) => f.product_id !== chosen[i].product_id || f.index !== i)) throw Error("The frame API response does not match the selected slots. Search again.");
      wcsAxes = data.wcs_axes;
      sequenceDisplay = data;
      slots = await Promise.all(data.frames.map(async (frame, i) => {
        const slot = { frame: { ...chosen[i], ...frame } };
        try { Object.assign(slot, await loadPng(frame, data.sequence_id)); }
        catch (error) {
          slot.error = message(error); slot.placeholder = document.createElement("p");
          slot.placeholder.textContent = `Cannot display this slot: ${slot.error}`;
        }
        return slot;
      }));
      slots.sort((a, b) => order(a.frame, b.frame));
      $("sequence-mode").textContent = data.mode === "comparable_visualization" ? "comparable_visualization · The backend permits visual comparison using a shared brightness range. This is not a photometric sequence." : "observation_browse · Each frame uses its own brightness range. For observation browsing only; do not compare brightness or infer variability.";
      $("sequence-details").textContent = `Frame cache expires: ${data.expires_at || "Not available"} (may be evicted early). Loaded PNGs remain available for offline playback. Normalization: ${data.normalization?.policy || "Not available"}.`;
      $("epoch-raw").textContent = JSON.stringify(data, null, 2);
      $("epoch-slots").replaceChildren();
      slots.forEach(slot => { const li = document.createElement("li"); li.textContent = describe(slot); $("epoch-slots").append(li); });
      $("epoch-time").max = String(slots.length - 1); $("epoch-player").hidden = false;
      $("epoch-play").disabled = !slots.some(s => s.image); show(0);
      status(`Retained ${slots.length} slots; loaded ${slots.filter(s => s.image).length} PNGs. Playback and scrubbing make no additional requests.`);
    } catch (error) {
      if (error.code === "search_expired") { snapshot = null; cursor = null; }
      status(message(error), true);
    } finally { working = false; controls(); renderProducts(); }
  }
  function mount(shared) {
    context = shared;
    $("explorer-mode").addEventListener("change", () => {
      pause(); $("preview-panel").hidden = active(); $("epochs-panel").hidden = !active(); controls();
    });
    $("load-frames").addEventListener("click", load);
    for (const count of [2, 3]) $("select-first-" + count).addEventListener("click", () => selectFirst(count));
    $("epochs-more").addEventListener("click", () => search(true));
    $("epoch-prev").addEventListener("click", () => { pause(); show(position - 1); });
    $("epoch-next").addEventListener("click", () => { pause(); show(position + 1); });
    $("epoch-time").addEventListener("input", () => { pause(); show(Number($("epoch-time").value)); });
    $("epoch-play").addEventListener("click", () => timer === null ? play() : pause());
    $("epoch-speed").addEventListener("change", () => { if (timer !== null) play(); });
    $("epoch-zoom").addEventListener("input", zoom);
  }
  window.SpherexEpochs = { mount, active, search: () => search(false) };
})();
