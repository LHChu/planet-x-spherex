/* Bounded multi-epoch viewer. PNGs are fetched once per explicit Load frames. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  let context, snapshot = null, query = null, base = "", cursor = null, working = false;
  let products = [], selected = new Set(), slots = [], position = 0, timer = null;
  const active = () => $("explorer-mode").value === "epochs";
  const sources = p => (p.source_collections || [p.obs_collection]).filter(Boolean).join(", ") || "未提供";
  const mjdTime = p => Number.isFinite(p.t_min) ? new Date((p.t_min - 40587) * 86400000).toISOString() : "未提供時間";
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
    $("epoch-play").textContent = "播放"; $("epoch-play").setAttribute("aria-pressed", "false");
  }
  function clearFrames() {
    pause();
    for (const slot of slots) if (slot.url) URL.revokeObjectURL(slot.url);
    slots = []; position = 0;
    $("epoch-viewport").replaceChildren(); $("epoch-player").hidden = true;
  }
  function controls() {
    for (const id of ["search", "environment", "api-url", "detector", "explorer-mode", "ra", "dec", "radius"]) $(id).disabled = working;
    $("search").textContent = working ? "處理多時期資料中…" : active() ? "查詢觀測時期" : "搜尋 NASA 影像 ↗";
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
      for (const value of [date(p), p.detector == null ? "未知" : `D${p.detector}`, `${sources(p)} · ${p.obs_id || "未知曝光（無法選取）"} · ${p.product_id} · ${p.frame_status || "not_requested"} · ${p.calibration_status || ""} · ${(p.warnings || []).join(", ")}`]) {
        const td = document.createElement("td"); td.textContent = value; tr.append(td);
      }
      $("epoch-products").append(tr);
    }
    $("epoch-selection").textContent = `已選 ${selected.size} / 3；顯示 ${visible.length} 個可選曝光。每個曝光保留一筆代表產品，無法選取的候選已隱藏；取消勾選可顯示其他候選。快速選取依可見清單第一筆的 detector，重選前 2／3 張，不會自動載入。仍需按 Load frames 才更新播放器。`;
    $("epochs-more").hidden = !cursor;
  }
  async function request(path, body, png = false) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), png ? 30000 : 180000);
    try {
      const response = await fetch(base + path, { method: png ? "GET" : "POST", headers: png ? {} : { "Content-Type": "application/json" }, ...(png ? {} : { body: JSON.stringify(body) }), signal: controller.signal, credentials: "omit" });
      if (png && response.ok) return await response.blob();
      let data;
      try { data = await response.json(); } catch { throw Error(`API 未回傳有效 JSON（HTTP ${response.status}）。`); }
      if (!response.ok) {
        const code = data.error?.code || "request_failed", retry = response.headers.get("Retry-After");
        const error = Error(`${data.error?.message || "請求失敗"}（HTTP ${response.status} / ${code}）${retry ? `；Retry-After: ${retry}，請等待後手動重試。` : ""}`);
        error.code = code; throw error;
      }
      return data;
    } finally { clearTimeout(timeout); }
  }
  function message(error) {
    if (["search_expired", "invalid_cursor", "frame_not_found"].includes(error.code)) return `${error.message}；查詢或影格快取已失效，請重新查詢觀測時期，再選取產品並按 Load frames。`;
    if (error.name === "AbortError") return "等待逾時；後端工作可能仍在執行，請稍後手動重試。";
    if (error instanceof TypeError) return "無法連線 API，請檢查後端網址、網路與 CORS。";
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
      working = true; controls(); renderProducts(); status("查詢觀測時期 metadata；不下載 FITS…");
      const data = await request("/api/epochs/search", { ...query, ...(more ? { cursor } : {}) });
      if (!data.search_id || !Array.isArray(data.products) || (more && data.search_id !== snapshot)) throw Error("API 搜尋回應缺少產品或快照不一致，請重新查詢。");
      snapshot = data.search_id; cursor = data.pagination?.next_cursor || null;
      const merged = new Map(products.map(p => [p.product_id, p]));
      data.products.forEach(p => merged.set(p.product_id, p)); products = [...merged.values()];
      $("epochs-sources").textContent = `查詢快照：RA ${query.ra} / Dec ${query.dec} / radius ${query.radius_deg}° · ${base}。來源：${(data.collections || []).map(c => `${c.name}: ${c.status}${c.truncated ? " (truncated)" : ""}${c.error ? ` ${JSON.stringify(c.error)}` : ""}`).join("；")}。快照到期：${data.expires_at || "未提供"}。${data.complete === false ? "查詢不完整，僅顯示已取得的候選。" : ""}`;
      status(products.length ? `已取得 ${products.length} 個產品${cursor ? "，還有更多時期" : ""}；請手動選取。` : "此範圍沒有可用觀測產品。");
    } catch (error) {
      if (["search_expired", "invalid_cursor"].includes(error.code)) { snapshot = null; cursor = null; }
      status(message(error), true);
    } finally { working = false; renderProducts(); controls(); }
  }
  function describe(slot) {
    const f = slot.frame;
    return `slot ${f.index} · ${date(f)} UTC · ${f.time_source || "sia_t_min"} · D${f.detector} · λ ${f.target_wavelength_um ?? "未提供"} μm / bandwidth ${f.target_bandwidth_um ?? "未提供"} μm · ${sources(f)} · ${f.obs_id} · ${f.product_id} · ${f.status} · alignment: ${f.alignment?.status || "未評估"}${slot.error ? ` · ${slot.error}` : ""}`;
  }
  function zoom() {
    const factor = Number($("epoch-zoom").value);
    $("epoch-zoom-value").textContent = `${factor}×`;
    for (const slot of slots) if (slot.image) {
      slot.image.style.width = `${slot.image.naturalWidth * factor}px`;
      slot.image.style.height = `${slot.image.naturalHeight * factor}px`;
    }
  }
  function show(next) {
    if (!slots.length) return;
    position = (next + slots.length) % slots.length;
    $("epoch-time").value = String(position);
    $("epoch-position").textContent = `${position + 1} / ${slots.length} · ${date(slots[position].frame)}`;
    $("epoch-current").textContent = describe(slots[position]);
    $("epoch-viewport").replaceChildren(slots[position].image || slots[position].placeholder);
    zoom();
  }
  function play() {
    pause(); if (slots.length < 2 || !slots.some(s => s.image)) return;
    $("epoch-play").textContent = "暫停"; $("epoch-play").setAttribute("aria-pressed", "true");
    timer = setInterval(() => show(position + 1), Number($("epoch-speed").value));
  }
  async function loadPng(frame, sequenceId) {
    if (!frame.image_url) throw Error(`${frame.error?.code || "frame_failed"}: ${frame.error?.message || "此 slot 沒有 PNG"}`);
    const path = new URL(frame.image_url, base).pathname;
    if (path !== `/api/epoch-frames/${sequenceId}/${frame.index}.png` || !/^[0-9a-f]{32}$/.test(sequenceId)) throw Error("API 回傳無效的影格 PNG 路徑。");
    const blob = await request(path, null, true), url = URL.createObjectURL(blob), img = document.createElement("img");
    img.alt = `後端 WCS 重投影 PNG · ${date(frame)} · ${frame.obs_id}`;
    try {
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => { cleanup(); reject(Error("PNG 解碼逾時，請重新查詢。")); }, 30000);
        function cleanup() { clearTimeout(timeout); img.onload = null; img.onerror = null; }
        img.onload = () => { cleanup(); resolve(); };
        img.onerror = () => { cleanup(); reject(Error("PNG 無法解碼，請重新查詢。")); };
        img.src = url;
      });
      return { image: img, url };
    } catch (error) { URL.revokeObjectURL(url); throw error; }
  }
  async function load() {
    if (working || !snapshot || selected.size < 2 || selected.size > 3) return;
    const chosen = products.filter(p => selected.has(p.product_id)).sort(order);
    if (chosen.length !== selected.size || chosen.some(p => !eligible(p) || p.detector !== chosen[0].detector) || new Set(chosen.map(exposure)).size !== chosen.length) return;
    clearFrames(); working = true; controls(); renderProducts(); status("載入指定影格；後端可能需要數分鐘處理 FITS…");
    try {
      const data = await request("/api/epoch-frames", { search_id: snapshot, product_ids: chosen.map(p => p.product_id) });
      if (data.search_id !== snapshot || !Array.isArray(data.frames) || data.frames.length !== chosen.length || data.frames.some((f, i) => f.product_id !== chosen[i].product_id || f.index !== i)) throw Error("影格 API 回應與指定 slot 不一致，請重新查詢。");
      slots = await Promise.all(data.frames.map(async (frame, i) => {
        const slot = { frame: { ...chosen[i], ...frame } };
        try { Object.assign(slot, await loadPng(frame, data.sequence_id)); }
        catch (error) {
          slot.error = message(error); slot.placeholder = document.createElement("p");
          slot.placeholder.textContent = `此 slot 無法顯示：${slot.error}`;
        }
        return slot;
      }));
      slots.sort((a, b) => order(a.frame, b.frame));
      $("sequence-mode").textContent = data.mode === "comparable_visualization" ? "comparable_visualization · 後端判定可比較視覺化，共用亮度範圍；不是光度測量序列。" : "observation_browse · 逐張獨立亮度範圍，僅供觀測瀏覽；不可比較亮度或解讀為光變。";
      $("sequence-details").textContent = `影格快取到期：${data.expires_at || "未提供"}（可能提前淘汰）；已載入的 PNG 可繼續離線播放。Normalization: ${data.normalization?.policy || "未提供"}。`;
      $("epoch-raw").textContent = JSON.stringify(data, null, 2);
      $("epoch-slots").replaceChildren();
      slots.forEach(slot => { const li = document.createElement("li"); li.textContent = describe(slot); $("epoch-slots").append(li); });
      $("epoch-time").max = String(slots.length - 1); $("epoch-player").hidden = false;
      $("epoch-play").disabled = !slots.some(s => s.image); show(0);
      status(`保留 ${slots.length} 個 slot，${slots.filter(s => s.image).length} 張 PNG 已載入。播放／拖動不再發出請求。`);
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
