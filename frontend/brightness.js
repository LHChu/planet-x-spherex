/* Pure display transforms. Input science arrays are never mutated. */
(function (root) {
  "use strict";
  function rgba(display, lo, hi, method = "linear", inverse = false, overlay = true) {
    if (![lo, hi, hi - lo].every(Number.isFinite) || hi <= lo) throw Error("最大值必須大於最小值，且範圍必須有限。");
    if (!["linear", "asinh"].includes(method)) throw Error("未知的 stretch。");
    const [height, width] = display.shape;
    const output = new Uint8ClampedArray(width * height * 4);
    for (let i = 0; i < display.values.length; i++) {
      const j = ((height - 1 - Math.floor(i / width)) * width + i % width) * 4;
      const value = display.values[i];
      if (!display.valid[i] || !Number.isFinite(value)) continue; // transparent, including after inversion
      let v = (Math.max(lo, Math.min(hi, value)) - lo) / (hi - lo);
      if (method === "asinh") v = Math.asinh(10 * v) / Math.asinh(10);
      const gray = Math.round(v * 255);
      output[j] = output[j + 1] = output[j + 2] = inverse ? 255 - gray : gray;
      output[j + 3] = 255;
      if (overlay && display.flags?.[i]) { output[j] = 255; output[j + 1] = Math.round(output[j + 1] / 2); output[j + 2] = 80; }
    }
    return output;
  }
  root.SpherexBrightness = Object.freeze({ rgba });
})(typeof window === "undefined" ? globalThis : window);
