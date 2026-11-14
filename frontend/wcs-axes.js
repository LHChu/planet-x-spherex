/* Display-only annotations: the backend evaluates the full celestial WCS. */
(() => {
  "use strict";
  function layout(metadata, width, height, zoom) {
    const size = { width: width * zoom, height: height * zoom };
    const margin = { left: Math.max(106, 125 - size.width / 2), top: Math.max(16, 110 - size.height / 2),
      right: Math.max(20, 125 - size.width / 2), bottom: Math.max(70, 110 - size.height / 2) };
    const validTicks = (ticks, length, ra) => Array.isArray(ticks) && ticks.length > 0 && ticks.length <= 20
      && ticks.every(t => Number.isFinite(t.pixel) && t.pixel >= -.5 && t.pixel <= length - .5
        && Number.isFinite(t.degrees) && (ra ? t.degrees >= 0 && t.degrees < 360 : Math.abs(t.degrees) <= 90));
    const available = Number.isFinite(zoom) && zoom > 0 && width > 0 && height > 0
      && metadata?.available === true && metadata.frame === "ICRS" && metadata.unit === "deg"
      && metadata.pixel_origin === 0 && metadata.png_y_flipped === true
      && metadata.ra_edge === "bottom" && metadata.dec_edge === "left"
      && metadata.shape_yx?.[0] === height && metadata.shape_yx?.[1] === width
      && validTicks(metadata.ra_ticks, width, true) && validTicks(metadata.dec_ticks, height, false);
    if (!available) return { available: false, ...size, margin, ra: [], dec: [] };
    // FITS centre (x,y) -> PNG cell position (x+.5, H-.5-y), then CSS zoom.
    const ra = metadata.ra_ticks.map(t => ({ ...t, position: (t.pixel + .5) * zoom }));
    const dec = metadata.dec_ticks.map(t => ({ ...t, position: (height - .5 - t.pixel) * zoom }));
    return { available: true, ...size, margin, ra, dec };
  }
  function spaced(ticks, gap) {
    const sorted = [...ticks].sort((a, b) => a.position - b.position);
    if (sorted.length > 1 && sorted.at(-1).position - sorted[0].position < gap) return [sorted[Math.floor(sorted.length / 2)]];
    const kept = [];
    for (const tick of sorted) if (!kept.length || tick.position - kept.at(-1).position >= gap) kept.push(tick);
    return kept;
  }
  const degrees = value => {
    // Keep RA inside [0,360) even if rounding a wrapped value to six decimals.
    const rounded = Number(value.toFixed(6));
    return (rounded === 360 ? 0 : rounded).toFixed(6);
  };
  function render(host, metadata, width, height, zoom) {
    const model = layout(metadata, width, height, zoom);
    const { margin } = model;
    host.style.width = `${model.width + margin.left + margin.right}px`;
    host.style.height = `${model.height + margin.top + margin.bottom}px`;
    host.replaceChildren();
    host.setAttribute("aria-label", "Celestial coordinates (ICRS). RA ticks follow the bottom image edge; Dec ticks follow the left image edge.");
    const add = (className, text, left, top) => {
      const node = document.createElement("span"); node.className = className;
      if (text !== null) node.textContent = text;
      node.style.left = `${left}px`; node.style.top = `${top}px`;
      host.append(node); return node;
    };
    if (!model.available) {
      add("wcs-unavailable", "WCS unavailable", margin.left, margin.top + model.height + 12);
      return model;
    }
    const bottom = margin.top + model.height;
    const xLine = add("wcs-x-line", null, margin.left, bottom); xLine.style.width = `${model.width}px`;
    const yLine = add("wcs-y-line", null, margin.left, margin.top); yLine.style.height = `${model.height}px`;
    for (const tick of spaced(model.ra, 88)) {
      const mark = add("wcs-x-tick", null, margin.left + tick.position, bottom);
      const label = document.createElement("span"); label.textContent = degrees(tick.degrees); mark.append(label);
    }
    for (const tick of spaced(model.dec, 24)) {
      const mark = add("wcs-y-tick", null, margin.left - 5, margin.top + tick.position);
      const label = document.createElement("span"); label.textContent = degrees(tick.degrees); mark.append(label);
    }
    add("wcs-x-title", "Right Ascension (RA) · degrees", margin.left + model.width / 2, bottom + 38);
    add("wcs-y-title", "Declination (Dec) · degrees", 18, margin.top + model.height / 2);
    return model;
  }
  window.SpherexAxes = Object.freeze({ layout, render });
})();
