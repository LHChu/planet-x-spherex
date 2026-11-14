/* Uses only the existing preview and PNG endpoints; no NASA/FITS processing. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const localPage = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  const defaults = { local: "http://127.0.0.1:8000", render: window.SPHEREX_CONFIG?.renderApiBase || "" };
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("spherex-api-v1")) || {}; } catch { /* Storage may be unavailable. */ }
  let environment = localPage && saved.environment === "local" ? "local" : localPage && !saved.environment ? "local" : "render";
  const bases = { ...defaults, ...saved.bases };
  let result = null, mode = "black", busy = false;
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
    if (!raw) throw new Error("請先填入 Render 後端的 HTTPS 網址。");
    let url;
    try { url = new URL(raw); } catch { throw new Error("API 網址格式無效，請輸入完整 http(s) 網址。"); }
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || !/^\/*$/.test(url.pathname)) {
      throw new Error("API 請填入不含路徑、帳密或查詢參數的 http(s) 基底網址。");
    }
    const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if (!localPage && loopback) throw new Error("公開前端無法使用你的本機後端，請改用 Render HTTPS 網址。");
    if ((environment === "render" || location.protocol === "https:") && url.protocol !== "https:") {
      throw new Error("Render／HTTPS 前端必須使用 HTTPS API，避免瀏覽器封鎖混合內容。");
    }
    return url.origin;
  }
  function payload() {
    const values = ["ra", "dec", "radius"].map(id => $(id).value.trim());
    const [ra, dec, radius_deg] = values.map(Number);
    if (values.some(v => !v) || ![ra, dec, radius_deg].every(Number.isFinite) || ra < 0 || ra >= 360 || dec < -90 || dec > 90 || radius_deg <= 0 || radius_deg > 5 / 60) {
      throw new Error("請檢查座標：0 ≤ RA < 360、−90 ≤ Dec ≤ 90，半徑須大於 0 且不超過 5/60 度。");
    }
    return { ra, dec, radius_deg };
  }
  function controls() {
    for (const id of ["black", "white", "zoom"]) $(id).disabled = busy || !result;
    for (const id of ["search", "environment", "api-url"]) $(id).disabled = busy;
    $("search").textContent = busy ? "正在取得 NASA 影像…" : "搜尋 NASA 影像 ↗";
    $("viewport").setAttribute("aria-busy", String(busy));
  }
  function zoom() {
    const factor = Number($("zoom").value);
    $("zoom-value").textContent = `${factor}×`;
    $("preview").style.width = `${$("preview").naturalWidth * factor}px`;
    $("preview").style.height = `${$("preview").naturalHeight * factor}px`;
  }
  $("zoom").addEventListener("input", zoom);
  function imageUrl(base, value) {
    // Keep image requests on the chosen API. Reverse proxies may return an
    // internal HTTP hostname; only the endpoint path is needed by this client.
    const url = new URL(value, base);
    if (!/^\/api\/images\/[0-9a-f]{32}(?:-inverse)?\.png$/.test(url.pathname)) throw new Error("API 回傳無效的 PNG 路徑。");
    return base + url.pathname;
  }
  function loadImage(url) {
    return new Promise((resolve, reject) => {
      const img = $("preview");
      const timer = setTimeout(() => { clean(); img.removeAttribute("src"); reject(new Error("PNG 載入逾時，請重新搜尋。")); }, 30000);
      function clean() { clearTimeout(timer); img.onload = null; img.onerror = null; }
      img.onload = () => { clean(); resolve(); };
      img.onerror = () => { clean(); reject(new Error("PNG 無法載入，快取可能已到期或後端已重啟，請重新搜尋。")); };
      img.src = url;
    });
  }
  function metadata(data) {
    const m = data.metadata, sia = m.sia || {};
    const rows = [
      ["觀測開始（UTC）", m.t_min_utc], ["觀測結束（UTC）", m.t_max_utc],
      ["觀測時間（MJD）", `${sia.t_min ?? "—"} → ${sia.t_max ?? "—"}`],
      ["Detector", m.detector ?? sia.detector], ["Observation ID", sia.obs_id],
      ["資料集", sia.obs_collection], ["曝光時間", sia.t_exptime == null ? null : `${sia.t_exptime} s`],
      ["查詢座標（度）", `RA ${m.query?.ra ?? "—"} / Dec ${m.query?.dec ?? "—"}`],
      ["影像尺寸", `${$("preview").naturalWidth} × ${$("preview").naturalHeight} px`],
      ["Cutout 邊長", m.cutout_size], ["亮度拉伸", m.stretch?.method],
      ["處理版本", m.version], ["影像方向", m.orientation],
      ["查詢截斷", m.truncated == null ? null : m.truncated ? "是，僅顯示部分候選結果" : "否"],
      ["快取有效期", `${data.expires_in_seconds ?? "—"} 秒；可能提前淘汰，到期請重新搜尋`]
    ];
    $("metadata").replaceChildren();
    for (const [label, value] of rows) {
      const dt = document.createElement("dt"), dd = document.createElement("dd");
      dt.textContent = label; dd.textContent = value ?? "未提供";
      $("metadata").append(dt, dd);
    }
    $("raw-metadata").textContent = JSON.stringify(m, null, 2);
    $("info").hidden = false;
  }
  function display() {
    $("preview").hidden = false; $("placeholder").hidden = true;
    $("viewport").classList.toggle("light", mode === "white");
    $("black").setAttribute("aria-pressed", String(mode === "black"));
    $("white").setAttribute("aria-pressed", String(mode === "white"));
    $("image-size").textContent = `PNG · ${$("preview").naturalWidth} × ${$("preview").naturalHeight}`;
    zoom();
  }
  async function switchMode(next) {
    if (!result || busy || next === mode) return;
    busy = true; controls(); $("preview").hidden = true;
    status("正在切換 PNG…", "loading");
    try { await loadImage(next === "black" ? result.black : result.white); mode = next; display(); status("影像已載入，可切換顯示模式或調整縮放。", "success"); }
    catch (e) { result = null; $("info").hidden = true; $("placeholder").hidden = false; $("image-size").textContent = "PNG · —"; status(e.message, "error"); }
    finally { busy = false; controls(); }
  }
  $("black").addEventListener("click", () => switchMode("black"));
  $("white").addEventListener("click", () => switchMode("white"));
  $("search-form").addEventListener("submit", async event => {
    event.preventDefault(); if (busy) return;
    let base, body;
    try { base = apiBase(); body = payload(); persist(); } catch (e) { status(e.message, "error"); return; }
    busy = true; result = null; controls();
    $("preview").hidden = true; $("info").hidden = true; $("placeholder").hidden = false;
    $("viewport").classList.remove("light"); $("image-size").textContent = "PNG · —";
    status("正在查詢 NASA 並產生 PNG，可能需要數分鐘；Render 冷啟動也可能增加等待時間。", "loading");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 180000);
    try {
      const response = await fetch(`${base}/api/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: controller.signal, credentials: "omit" });
      let data;
      try { data = await response.json(); } catch { throw new Error(`API 未回傳有效 JSON（HTTP ${response.status}），請檢查網址或服務狀態。`); }
      if (!response.ok) {
        const code = data.error?.code;
        if (code === "no_images") { status("此座標與搜尋範圍內查無影像，請調整座標或半徑後重試。", "empty"); return; }
        const retry = response.headers.get("Retry-After");
        const hint = code === "busy" ? `後端忙碌，請${retry ? `依 Retry-After（${retry}）等待` : "稍候"}再手動重試。` : data.error?.message || "API 請求失敗";
        throw new Error(`${hint}（HTTP ${response.status}${code ? ` / ${code}` : ""}）`);
      }
      if (!data.metadata || typeof data.metadata !== "object" || !data.image_url || !data.inverted_image_url) throw new Error("API 回應缺少影像或 metadata。");
      const images = { black: imageUrl(base, data.image_url), white: imageUrl(base, data.inverted_image_url) };
      await loadImage(mode === "black" ? images.black : images.white);
      result = images; $("preview").alt = `SPHEREx：RA ${body.ra}°、Dec ${body.dec}° 的紅外線觀測影像`;
      display(); metadata(data); status("影像已載入，可切換顯示模式或調整縮放。", "success");
    } catch (e) {
      status(e.name === "AbortError" ? "等待 API 超過 180 秒，請稍後重試；後端工作可能仍在執行。" : e instanceof TypeError ? "無法連線 API。請確認後端已啟動、網址正確，且 CORS_ORIGINS 允許此前端來源。" : e.message, "error");
    } finally { clearTimeout(timer); busy = false; controls(); }
  });
})();
