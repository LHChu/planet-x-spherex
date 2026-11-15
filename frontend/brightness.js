/* Pure display transforms. Input science arrays are never mutated. */
(function (root) {
  "use strict";
  function rgba(display, lo, hi, method = "linear", inverse = false, overlay = true) {
    if (![lo, hi, hi - lo].every(Number.isFinite) || hi <= lo) throw Error("The maximum must exceed the minimum, and the range must be finite.");
    if (!["linear", "asinh", "log", "sqrt"].includes(method)) throw Error("Unknown stretch method.");
    const [height, width] = display.shape;
    const output = new Uint8ClampedArray(width * height * 4);
    for (let i = 0; i < display.values.length; i++) {
      const j = ((height - 1 - Math.floor(i / width)) * width + i % width) * 4;
      const value = display.values[i];
      if (!display.valid[i] || !Number.isFinite(value)) continue; // transparent, including after inversion
      let v = (Math.max(lo, Math.min(hi, value)) - lo) / (hi - lo);
      if (method === "asinh") v = Math.asinh(10 * v) / Math.asinh(10);
      if (method === "log") v = Math.log1p(1000 * v) / Math.log1p(1000);
      if (method === "sqrt") v = Math.sqrt(v);
      const gray = Math.round(v * 255);
      output[j] = output[j + 1] = output[j + 2] = inverse ? 255 - gray : gray;
      output[j + 3] = 255;
      if (overlay && display.flags?.[i]) { output[j] = 255; output[j + 1] = Math.round(output[j + 1] / 2); output[j + 2] = 80; }
    }
    return output;
  }
  // Histogram axes always describe untransformed science values.
  function histogramModel(histogram, width = 640) {
    const { counts, edges } = histogram, peak = Math.max(1, ...counts);
    const lo = edges[0], hi = edges.at(-1), divisions = width < 450 ? 2 : 4;
    const precision = Math.min(15, Math.max(3, Math.ceil(Math.log10(Math.max(Math.abs(lo), Math.abs(hi)) || 1) - Math.log10((hi - lo) / divisions || 1)) + 2));
    const format = v => Number(v.toPrecision(precision)).toString();
    return { peak, total: counts.reduce((a, b) => a + b, 0),
      x: Array.from({ length: divisions + 1 }, (_, i) => format(lo + (hi - lo) * i / divisions)),
      y: [String(peak), String(Math.floor(peak / 2)), "0"] };
  }
  function histogram(canvas, display, xHost, yHost) {
    const { counts } = display.histogram, model = histogramModel(display.histogram, canvas.clientWidth || 320);
    const context = canvas.getContext("2d"), w = canvas.width / counts.length;
    context.clearRect(0, 0, canvas.width, canvas.height); context.fillStyle = "#63c9da";
    counts.forEach((n, i) => context.fillRect(i * w, canvas.height - n / model.peak * canvas.height, Math.max(1, w - 1), n / model.peak * canvas.height));
    for (const [host, ticks] of [[xHost, model.x], [yHost, model.y]]) {
      host.replaceChildren();
      for (const text of ticks) { const tick = document.createElement("span"); tick.textContent = text; host.append(tick); }
    }
    return model;
  }
  root.SpherexBrightness = Object.freeze({ rgba, histogramModel, histogram });
})(typeof window === "undefined" ? globalThis : window);
