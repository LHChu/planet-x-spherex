import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { axesFixture } from './axes-fixture.mjs';
const script = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
function setup({ host = '127.0.0.1', stored = null, response, imageFail = false, fetchFail = false, storageFail = false, hang = false } = {}) {
  const elements = {};
  class Element {
    constructor() { this.value = ''; this.hidden = false; this.disabled = false; this.dataset = {}; this.style = {}; this.attrs = {}; this.children = []; this.events = {}; this.naturalWidth = 29; this.naturalHeight = 29; this.classList = { toggle() {}, remove() {} }; }
    addEventListener(name, fn) { this.events[name] = fn; }
    setAttribute(k, v) { this.attrs[k] = v; }
    removeAttribute(k) { delete this.attrs[k]; }
    replaceChildren() { this.children = []; }
    append(...items) { this.children.push(...items); }
    getContext() { return { clearRect() {}, fillRect() {}, createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }), putImageData: frame => { this.frame = frame; } }; }
    toDataURL() { return 'data:image/png;base64,local-display'; }
    set src(value) { this.url = value; queueMicrotask(() => imageFail ? this.onerror?.() : this.onload?.()); }
  }
  for (const [, id] of html.matchAll(/id="([^"]+)"/g)) elements[id] = new Element();
  for (const [id, value] of Object.entries({ ra: '127.69444', dec: '-39.17760', radius: '0.01', zoom: '12' })) elements[id].value = value;
  const calls = [], timers = new Map(); let timerId = 0;
  const environment = {
    document: { getElementById: id => { assert.ok(elements[id], `Missing HTML ID ${id}`); return elements[id]; }, createElement: () => new Element() },
    location: { hostname: host, protocol: host === '127.0.0.1' ? 'http:' : 'https:' }, window: {}, URL, AbortController, TypeError,
    localStorage: { getItem: () => { if (storageFail) throw Error(); return stored; }, setItem() {} },
    setTimeout: (fn, ms) => { timers.set(++timerId, { fn, ms }); return timerId; }, clearTimeout: id => timers.delete(id),
    fetch: async (...args) => { calls.push(args); if (hang) return new Promise((resolve, reject) => args[1].signal.addEventListener('abort', () => { const error = new Error(); error.name = 'AbortError'; reject(error); })); if (fetchFail) throw new TypeError('network'); return response || success(); }
  };
  vm.runInNewContext(readFileSync(new URL('../brightness.js', import.meta.url), 'utf8'), environment);
  vm.runInNewContext(readFileSync(new URL('../wcs-axes.js', import.meta.url), 'utf8'), environment);
  vm.runInNewContext(readFileSync(new URL('../color-bar.js', import.meta.url), 'utf8'), environment);
  vm.runInNewContext(script, environment);
  return { e: elements, calls, timers, submit: () => elements['search-form'].events.submit({ preventDefault() {} }) };
}
const success = () => ({ ok: true, status: 200, json: async () => ({ image_url: `http://internal:8000/api/images/${'a'.repeat(32)}.png`, inverted_image_url: `/api/images/${'a'.repeat(32)}-inverse.png`, expires_in_seconds: 600, metadata: { detector: 1, t_min_utc: '2025-04-29T14:18:55.958', sia: { obs_id: '<script>unsafe</script>' }, query: { ra: 127.69444, dec: -39.1776 } } }) });
test('POST numeric payload, proxy PNG rebasing, metadata, zoom and inversion', async () => {
  const { e, calls, submit, timers } = setup();
  const pending = submit(); assert.equal(e.search.disabled, true); assert.equal(e.status.dataset.state, 'loading');
  await pending;
  assert.equal(calls[0][0], 'http://127.0.0.1:8000/api/preview');
  assert.deepEqual(JSON.parse(calls[0][1].body), { ra: 127.69444, dec: -39.1776, radius_deg: .01 });
  assert.match(e.preview.url, /^http:\/\/127.0.0.1:8000\/api\/images\//);
  assert.equal(e.preview.style.width, '348px'); assert.equal(e.info.hidden, false);
  assert.ok(e.metadata.children.some(x => x.textContent === '<script>unsafe</script>'));
  await e.white.events.click(); assert.match(e.preview.url, /-inverse.png$/); assert.equal(e.white.attrs['aria-pressed'], 'true');
  e.zoom.value = '32'; e.zoom.events.input(); assert.equal(e.preview.style.width, '928px');
  assert.equal(e.search.disabled, false); assert.equal(timers.size, 0);
});

test('English loading, success and metadata text preserves the raw API response', async () => {
  const data = await success().json();
  data.metadata.truncated = true;
  const s = setup({ response: { ok: true, status: 200, json: async () => data } });
  const pending = s.submit();
  assert.equal(s.e.search.textContent, 'Fetching NASA images…');
  assert.match(s.e.status.textContent, /Querying NASA/);
  await pending;
  assert.equal(s.e.search.textContent, 'Search NASA images ↗');
  assert.match(s.e.status.textContent, /Image loaded/);
  assert.match(s.e.preview.alt, /SPHEREx infrared observation at RA .*°, Dec .*°/);
  const text = s.e.metadata.children.map(item => item.textContent).join('\n');
  assert.match(text, /Observation start \(UTC\)/);
  assert.match(text, /Not available/);
  assert.match(text, /Yes; only some candidates are shown/);
  assert.match(text, /600 seconds/);
  assert.doesNotMatch(text, /\p{Script=Han}/u);
  assert.deepEqual(JSON.parse(s.e['raw-metadata'].textContent), data.metadata);
  assert.equal(s.calls.length, 1);
});

test('Preview WCS survives inversion, brightness and zoom without more API requests', async () => {
  const data = await success().json();
  data.metadata.wcs_axes = axesFixture();
  data.metadata.display = { available: true, shape: [29, 29], values: Array(841).fill(1), valid: Array(841).fill(true),
    min: 0, max: 2, lo: 0, hi: 2, histogram: { counts: [841], edges: [0, 2] } };
  const s = setup({ response: { ok: true, status: 200, json: async () => data } });
  await s.submit();
  const annotation = () => JSON.stringify(s.e['preview-axes'].children);
  const before = annotation();
  await s.e.white.events.click();
  assert.equal(annotation(), before);
  s.e.stretch.value = 'asinh'; s.e.stretch.events.change();
  assert.equal(annotation(), before);
  s.e.zoom.value = '32'; s.e.zoom.events.input();
  assert.notEqual(annotation(), before);
  assert.equal(s.e.preview.style.width, '928px');
  s.e.zoom.value = '12'; s.e.zoom.events.input(); assert.equal(annotation(), before);
  assert.equal(s.calls.length, 1); assert.equal(s.e['preview-stage'].hidden, false);
});

test('legacy Preview without WCS still loads, and a fresh search clears stale axes', async () => {
  const s = setup(); await s.submit();
  assert.equal(s.e['preview-axes'].children[0].textContent, 'WCS unavailable');
  const pending = s.submit();
  assert.equal(s.e['preview-stage'].hidden, true);
  assert.equal(s.e['preview-axes'].children.length, 0);
  await pending; assert.equal(s.e['preview-stage'].hidden, false);
});

test('Preview Color Bar follows applied min/max, Asinh, inversion and reset without changing science or WCS', async () => {
  const data = await success().json();
  data.metadata.wcs_axes = axesFixture();
  data.metadata.display = { available: true, unit: 'MJy/sr', shape: [29, 29], values: Array(841).fill(1),
    valid: Array(841).fill(true), flags: Array(841).fill(1 << 21), min: -2, max: 6, lo: -2, hi: 6,
    histogram: { counts: [841], edges: [-2, 6] } };
  const original = JSON.stringify(data.metadata);
  const s = setup({ response: { ok: true, status: 200, json: async () => data } }); await s.submit();
  const bar = () => s.e['preview-colorbar'].children.find(n => n.className === 'colorbar-body');
  const shades = () => Array.from(bar().children[0].frame.data);
  const ticks = () => bar().children.filter(n => n.className === 'colorbar-tick').map(n => n.textContent);
  const axes = JSON.stringify(s.e['preview-axes'].children), histogram = s.e['histogram-range'].textContent;
  assert.deepEqual(ticks(), ['-2', '0', '2', '4', '6']);
  const linear = shades();
  s.e.stretch.value = 'asinh'; s.e.stretch.events.change();
  const asinh = shades(); assert.notDeepEqual(asinh, linear);
  await s.e.white.events.click();
  const inverse = shades();
  asinh.forEach((v, i) => assert.equal(inverse[i], i % 4 === 3 ? 255 : 255 - v));
  assert.equal(JSON.stringify(s.e['preview-axes'].children), axes);
  s.e['minimum-number'].value = '0'; s.e['minimum-number'].events.change();
  s.e['maximum-number'].value = '4'; s.e['maximum-number'].events.change();
  assert.deepEqual(ticks(), ['0', '1', '2', '3', '4']);
  const good = shades();
  s.e['minimum-number'].value = '9'; s.e['minimum-number'].events.change(); assert.deepEqual(shades(), good);
  s.e['reset-brightness'].events.click(); assert.deepEqual(ticks(), ['-2', '0', '2', '4', '6']);
  const reset = shades();
  s.e['quality-overlay'].checked = true; s.e['quality-overlay'].events.change(); assert.deepEqual(shades(), reset);
  s.e.zoom.value = '32'; s.e.zoom.events.input(); assert.deepEqual(shades(), reset);
  assert.equal(s.e['histogram-range'].textContent, histogram);
  assert.equal(JSON.stringify(data.metadata), original); assert.equal(s.calls.length, 1);
});

test('PNG-only Preview Color Bar uses the backend stretch, follows inversion and clears on search', async () => {
  const data = await success().json();
  data.metadata.display = { available: false, unit: 'MJy/sr' };
  data.metadata.stretch = { p1: -3, p99: 9, method: 'asinh(10x)' };
  const s = setup({ response: { ok: true, status: 200, json: async () => data } }); await s.submit();
  const bar = () => s.e['preview-colorbar'].children.find(n => n.className === 'colorbar-body');
  const shades = Array.from(bar().children[0].frame.data);
  assert.match(s.e['preview-colorbar'].children.at(-1).textContent, /Asinh \(10x\)/);
  await s.e.white.events.click();
  const inverse = bar().children[0].frame.data;
  shades.forEach((v, i) => assert.equal(inverse[i], i % 4 === 3 ? 255 : 255 - v));
  const pending = s.submit(); assert.equal(s.e['preview-colorbar'].children.length, 0); await pending;
  assert.equal(s.calls.length, 2);
});

test('legacy Preview with insufficient mapping metadata explicitly shows Color Bar unavailable', async () => {
  const s = setup(); await s.submit();
  assert.equal(s.e['preview-colorbar'].children[1].textContent, 'Color Bar unavailable');
  assert.equal(s.e.status.dataset.state, 'success');
});
for (const [field, value] of [['ra', '360'], ['ra', '-1'], ['dec', '91'], ['dec', '-91'], ['radius', '0'], ['radius', '.084'], ['ra', ''], ['ra', 'NaN']]) {
  test(`reject invalid ${field}=${value}`, async () => { const s = setup(); s.e[field].value = value; await s.submit(); assert.equal(s.calls.length, 0); assert.equal(s.e.status.dataset.state, 'error'); });
}
test('coordinate boundaries accepted', async () => { const s = setup(); s.e.ra.value = '0'; s.e.dec.value = '-90'; s.e.radius.value = String(5 / 60); await s.submit(); assert.equal(s.calls.length, 1); });

test('D1–D6 are numeric backend filters; Auto omits the optional field', async () => {
  for (let detector = 1; detector <= 6; detector++) {
    const s = setup(); s.e.detector.value = String(detector);
    const pending = s.submit(); assert.equal(s.e.detector.disabled, true); await pending;
    assert.equal(JSON.parse(s.calls[0][1].body).detector, detector);
    assert.equal(s.e.detector.disabled, false);
  }
  const s = setup(); await s.submit();
  assert.equal('detector' in JSON.parse(s.calls[0][1].body), false);
  s.e.detector.value = '7'; await s.submit(); assert.equal(s.calls.length, 1);
});

for (const [code, message] of [['detector_not_found', 'No D6 candidates in the complete search'], ['detector_search_incomplete', 'SIA results are truncated; D6 availability is unconfirmed'], ['detector_cutout_failed', 'D6 Cutout failed validation']]) {
  test(`detector error ${code} is shown without automatic fallback`, async () => {
    const s = setup({ response: { ok: false, status: 503, headers: { get: () => null }, json: async () => ({ error: { code, message } }) } });
    s.e.detector.value = '6'; await s.submit();
    assert.equal(s.calls.length, 1); assert.equal(s.e.detector.value, '6');
    assert.match(s.e.status.textContent, new RegExp(message));
    assert.equal(s.e.status.dataset.state, 'error'); assert.equal(s.e.preview.hidden, true);
  });
}
test('public page defaults to Render and blocks loopback', async () => { const s = setup({ host: 'example.github.io', stored: JSON.stringify({ environment: 'local' }) }); assert.equal(s.e.environment.value, 'render'); await s.submit(); assert.equal(s.calls.length, 0); s.e['api-url'].value = 'http://localhost:8000'; await s.submit(); assert.match(s.e.status.textContent, /public frontend/); });
test('Render HTTPS, URL validation and environment persistence', async () => {
  const s = setup(); s.e.environment.value = 'render'; s.e.environment.events.change();
  for (const url of ['http://foo.onrender.com', 'https://foo.onrender.com/path', 'https://user:password@foo.onrender.com', 'not a url']) { s.e['api-url'].value = url; await s.submit(); assert.equal(s.calls.length, 0); }
  s.e['api-url'].value = 'https://foo.onrender.com/'; await s.submit(); assert.equal(s.calls[0][0], 'https://foo.onrender.com/api/preview');
});
for (const [code, state] of [['no_images', 'empty'], ['busy', 'error'], ['upstream_timeout', 'error'], ['cutout_failed', 'error'], ['invalid_input', 'error'], ['internal_error', 'error']]) {
  test(`API ${code} clears stale results and enables retry`, async () => { const s = setup({ response: { ok: false, status: code === 'no_images' ? 404 : 503, headers: { get: () => '5' }, json: async () => ({ error: { code, message: 'Test error' } }) } }); await s.submit(); assert.equal(s.e.status.dataset.state, state); assert.equal(s.e.preview.hidden, true); assert.equal(s.e.info.hidden, true); assert.equal(s.e.search.disabled, false); assert.doesNotMatch(s.e.status.textContent, /\p{Script=Han}/u); if (code === 'busy') assert.match(s.e.status.textContent, /Retry-After \(5\).*retry manually/); });
}
test('network/CORS error', async () => { const s = setup({ fetchFail: true }); await s.submit(); assert.match(s.e.status.textContent, /CORS/); });
test('malformed JSON', async () => { const s = setup({ response: { status: 502, json: async () => { throw Error(); } } }); await s.submit(); assert.match(s.e.status.textContent, /JSON/); });
test('expired PNG', async () => { const s = setup({ imageFail: true }); await s.submit(); assert.match(s.e.status.textContent, /cache/); assert.equal(s.e.black.disabled, true); });
test('storage unavailable still works', async () => { const s = setup({ storageFail: true }); await s.submit(); assert.equal(s.e.status.dataset.state, 'success'); });
test('API timeout releases form', async () => { const s = setup({ hang: true }); const task = s.submit(); s.timers.values().next().value.fn(); await task; assert.equal(s.e.search.disabled, false); assert.match(s.e.status.textContent, /180 seconds/); assert.equal(s.timers.size, 0); });

test('raw controls default linear, keep histogram/science fixed and never request NASA again', async () => {
  const data = await success().json();
  data.metadata.display = { available: true, shape: [1, 3], unit: 'MJy/sr', values: [-1, null, 5], valid: [true, false, true], flags: [0, 0, 2097152], min: -1, max: 5, lo: -1, hi: 5, histogram: { counts: [1, 1], edges: [-1, 2, 5] } };
  const original = JSON.stringify(data.metadata.display);
  const s = setup({ response: { ok: true, status: 200, json: async () => data } });
  await s.submit();
  assert.equal(s.e.brightness.hidden, false);
  assert.equal(s.e.stretch.value, 'linear');
  assert.match(s.e.preview.url, /^data:image\/png/);
  assert.match(s.e['histogram-range'].textContent, /total 2/);
  s.e.minimum.value = '0'; s.e.minimum.events.input();
  assert.equal(s.e['minimum-number'].value, '0');
  s.e['maximum-number'].value = '10'; s.e['maximum-number'].events.change();
  assert.equal(s.e.maximum.value, 10);
  s.e.stretch.value = 'asinh'; s.e.stretch.events.change();
  await s.e.white.events.click();
  assert.equal(s.e.white.attrs['aria-pressed'], 'true');
  s.e['minimum-number'].value = '20'; s.e['minimum-number'].events.change();
  assert.match(s.e['brightness-status'].textContent, /maximum must exceed/);
  s.e['reset-brightness'].events.click();
  assert.equal(s.e['minimum-number'].value, '-1');
  assert.equal(s.e.stretch.value, 'linear');
  assert.equal(JSON.stringify(data.metadata.display), original);
  assert.equal(s.calls.length, 1);
});
