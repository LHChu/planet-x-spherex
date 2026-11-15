import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { axesFixture } from './axes-fixture.mjs';
const script = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
function setup({ host = '127.0.0.1', protocol = host === '127.0.0.1' ? 'http:' : 'https:', stored = null, search = "", response, imageFail = false, fetchFail = false, storageFail = false, hang = false } = {}) {
  const elements = {}, observers = [];
  class Element {
    constructor() { this.clientWidth = 900; this.clientHeight = 600; this.value = ''; this.hidden = false; this.disabled = false; this.dataset = {}; this.style = {}; this.attrs = {}; this.children = []; this.events = {}; this.naturalWidth = 29; this.naturalHeight = 29; this.classList = { toggle() {}, remove() {} }; }
    getBoundingClientRect() { return { left:0, top:0, width:parseFloat(this.style.width)||this.clientWidth, height:parseFloat(this.style.height)||this.clientHeight }; }
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
  for (const [id, value] of Object.entries({ ra: '127.69444', dec: '-39.17760', radius: '0.6', zoom: '12' })) elements[id].value = value;
  const calls = [], timers = new Map(); let timerId = 0;
  const environment = {
    document: { getElementById: id => { assert.ok(elements[id], `Missing HTML ID ${id}`); return elements[id]; }, createElement: () => new Element() },
    location: { hostname: host, protocol, search }, window: { ResizeObserver: class { constructor(fn) { this.fn = fn; observers.push(this); } observe(host) { this.host = host; } } }, URL, URLSearchParams, AbortController, TypeError,
    localStorage: { getItem: () => { if (storageFail) throw Error(); return stored; }, setItem() {} },
    setTimeout: (fn, ms) => { timers.set(++timerId, { fn, ms }); return timerId; }, clearTimeout: id => timers.delete(id),
    fetch: async (...args) => { calls.push(args); if (hang) return new Promise((resolve, reject) => args[1].signal.addEventListener('abort', () => { const error = new Error(); error.name = 'AbortError'; reject(error); })); if (fetchFail) throw new TypeError('network'); return response || success(); }
  };
  vm.runInNewContext(readFileSync(new URL('../config.js', import.meta.url), 'utf8'), environment);
  vm.runInNewContext(readFileSync(new URL('../brightness.js', import.meta.url), 'utf8'), environment);
  vm.runInNewContext(readFileSync(new URL('../wcs-axes.js', import.meta.url), 'utf8'), environment);
  vm.runInNewContext(readFileSync(new URL('../color-bar.js', import.meta.url), 'utf8'), environment);
  vm.runInNewContext(script, environment);
  return { e: elements, calls, timers, resize: () => observers.forEach(o => o.fn()), submit: () => elements['search-form'].events.submit({ preventDefault() {} }) };
}
const success = () => ({ ok: true, status: 200, json: async () => ({ image_url: `http://internal:8000/api/images/${'a'.repeat(32)}.png`, inverted_image_url: `/api/images/${'a'.repeat(32)}-inverse.png`, expires_in_seconds: 600, metadata: { detector: 1, t_min_utc: '2025-04-29T14:18:55.958', sia: { obs_id: '<script>unsafe</script>' }, query: { ra: 127.69444, dec: -39.1776 } } }) });
test('POST numeric payload, proxy PNG rebasing, metadata, zoom and inversion', async () => {
  const { e, calls, submit, timers } = setup();
  const pending = submit(); assert.equal(e.search.disabled, true); assert.equal(e.status.dataset.state, 'loading');
  await pending;
  assert.equal(calls[0][0], 'http://127.0.0.1:8015/api/preview');
  assert.deepEqual(JSON.parse(calls[0][1].body), { ra: 127.69444, dec: -39.1776, radius_deg: .01 });
  assert.match(e.preview.url, /^http:\/\/127.0.0.1:8015\/api\/images\//);
  assert.match(e['zoom-value'].textContent, /^Fit/); assert.equal(e.info.hidden, false);
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
  assert.match(text, /Observation ID/);
  assert.doesNotMatch(text, /Not available/);
  assert.match(s.e["preview-warnings"].textContent, /Search incomplete/);
  assert.doesNotMatch(text, /600 seconds|Cache|SHA256|Search ID/);
  assert.doesNotMatch(text, /\p{Script=Han}/u);
  assert.ok(s.e['observation-summary'].children.some(n => n.textContent === '2025-04-29T14:18:55.958'));
  assert.equal(s.e['raw-metadata'], undefined);
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
  s.e['fit-view'].events.click(); assert.equal(annotation(), before);
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
  assert.match(s.e['preview-scale-note'].textContent, /Asinh \(10x\)/);
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
for (const [field, value] of [['ra', '360'], ['ra', '-1'], ['dec', '91'], ['dec', '-91'], ['radius', '0'], ['radius', '5.000001'], ['ra', ''], ['ra', 'NaN']]) {
  test(`reject invalid ${field}=${value}`, async () => { const s = setup(); s.e[field].value = value; await s.submit(); assert.equal(s.calls.length, 0); assert.equal(s.e.status.dataset.state, 'error'); });
}
test('coordinate boundaries accepted', async () => { const s = setup(); s.e.ra.value = '0'; s.e.dec.value = '-90'; s.e.radius.value = '5'; await s.submit(); assert.equal(s.calls.length, 1); });

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
test('public pages ignore legacy storage and developer overrides and always use Render', async () => {
  for (const stored of [null, '{bad json', JSON.stringify({ environment: 'local', bases: { local: 'http://localhost:9999', render: 'https://old.example.com' } })]) {
    const s = setup({ host: 'zo4j433.github.io', stored, search: '?devApiOrigin=http://localhost:9999' });
    await s.submit();
    assert.equal(s.calls[0][0], 'https://planet-x-spherex.onrender.com/api/preview');
    assert.match(s.e.preview.url, /^https:\/\/planet-x-spherex.onrender.com\/api\/images\//);
    assert.equal(s.e['api-url'], undefined); assert.equal(s.e.environment, undefined);
  }
});

test('loopback pages default to port 8015 regardless of legacy settings', async () => {
  for (const host of ['localhost', '127.0.0.1', '[::1]']) {
    const s = setup({ host, protocol: 'http:', stored: JSON.stringify({ environment: 'render', bases: { local: 'http://localhost:9999', render: 'https://old.example.com' } }) });
    await s.submit(); assert.equal(s.calls[0][0], 'http://127.0.0.1:8015/api/preview');
  }
});

test('localhost supports explicit fixture override with origin validation', async () => {
  const s = setup({ search: '?devApiOrigin=http://127.0.0.1:8007' });
  await s.submit(); assert.equal(s.calls[0][0], 'http://127.0.0.1:8007/api/preview');
  for (const origin of ['not a url', 'https://example.com/path', 'https://user:password@example.com', 'file:///tmp', 'https://example.com/?key=value', 'https://example.com/#fragment']) {
    const invalid = setup({ search: '?devApiOrigin=' + encodeURIComponent(origin) });
    await invalid.submit(); assert.equal(invalid.calls.length, 0); assert.equal(invalid.e.status.dataset.state, 'error');
  }
  const https = setup({ host: 'localhost', protocol: 'https:', search: '?devApiOrigin=http://127.0.0.1:8015' });
  await https.submit(); assert.equal(https.calls.length, 0); assert.match(https.e.status.textContent, /HTTPS/);
});
for (const [code, state] of [['no_images', 'empty'], ['busy', 'error'], ['upstream_timeout', 'error'], ['cutout_failed', 'error'], ['invalid_input', 'error'], ['internal_error', 'error']]) {
  test(`API ${code} clears stale results and enables retry`, async () => { const s = setup({ response: { ok: false, status: code === 'no_images' ? 404 : 503, headers: { get: () => '5' }, json: async () => ({ error: { code, message: 'Test error' } }) } }); await s.submit(); assert.equal(s.e.status.dataset.state, state); assert.equal(s.e.preview.hidden, true); assert.equal(s.e.info.hidden, true); assert.equal(s.e.search.disabled, false); assert.doesNotMatch(s.e.status.textContent, /\p{Script=Han}/u); if (code === 'busy') assert.match(s.e.status.textContent, /Retry-After \(5\).*retry manually/); });
}
test('network/CORS error', async () => { const s = setup({ fetchFail: true }); await s.submit(); assert.match(s.e.status.textContent, /Check your connection.*may be starting up or temporarily unavailable/); assert.equal(s.calls.length, 1); });
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

test('Preview defaults to Fit, resizes without requests, and preserves manual zoom until Fit is selected', async () => {
  const data = await success().json(); data.metadata.wcs_axes = axesFixture();
  const s = setup({ response: { ok: true, status: 200, json: async () => data } }); await s.submit();
  const { e } = s, pixels = () => parseFloat(e.preview.style.width);
  const aligned = (stacked = false) => {
    const edge = e['preview-axes'].children.find(n => n.className === 'wcs-x-line');
    assert.equal(edge.style.left, e.preview.style.left);
    assert.equal(edge.style.width, e.preview.style.width);
    if (stacked) assert.ok(parseFloat(e['preview-colorbar'].style.top) > parseFloat(e.preview.style.top) + pixels() + 70);
    else assert.ok(Math.abs(parseFloat(e['preview-colorbar'].style.left) - parseFloat(e.preview.style.left) - pixels() - 30) < 1e-9);
  };
  assert.equal(e['fit-view'].attrs['aria-pressed'], 'true');
  assert.ok(parseFloat(e['preview-frame'].style.width) <= e.viewport.clientWidth);
  assert.ok(parseFloat(e['preview-frame'].style.height) <= e.viewport.clientHeight);
  aligned();
  const initial = pixels(), source = e.preview.url;
  e.viewport.clientWidth = 500; e.viewport.clientHeight = 400; s.resize();
  assert.ok(pixels() < initial); aligned(true);
  assert.equal(e.preview.url, source);
  e.zoom.value = '32'; e.zoom.events.input();
  aligned();
  const manualAxes = JSON.stringify(e['preview-axes'].children);
  assert.equal(pixels(), 29 * 32);
  assert.equal(e['fit-view'].attrs['aria-pressed'], 'false');
  e.viewport.clientWidth = 320; s.resize();
  assert.equal(pixels(), 29 * 32);
  assert.equal(JSON.stringify(e['preview-axes'].children), manualAxes);
  e['fit-view'].events.click();
  assert.equal(e['fit-view'].attrs['aria-pressed'], 'true');
  assert.ok(parseFloat(e['preview-frame'].style.width) <= 320);
  aligned(true);
  assert.equal(e.viewport.scrollLeft, 0);
  assert.equal(s.calls.length, 1);
});

test('Preview summary contains only key observation fields while Observation Details filters diagnostics', async () => {
  const data = await success().json();
  Object.assign(data.metadata, { valid_pixels: 0, truncated: true,
    target_spectral: { available: true, wavelength: .86, units: ['um','um'] },
    calibration: { status: 'unverified', warning: 'Retain calibration caveat' } });
  const original = JSON.stringify(data);
  const s = setup({ response: { ok: true, status: 200, json: async () => data } }); await s.submit();
  const fields = s.e['observation-summary'].children.map(n => n.textContent);
  assert.deepEqual(fields, ['Observation UTC',data.metadata.t_min_utc,'Detector','1','Wavelength (μm)','0.86','Valid pixel count','0','Status','No valid pixels']);
  assert.doesNotMatch(fields.join(' '), /Cache|WCS target|unsafe|Calibration/);
  assert.ok(s.e['observation-summary'].children.some(n => n.textContent === '2025-04-29T14:18:55.958'));
  assert.equal(s.e['raw-metadata'], undefined);
  assert.equal(JSON.stringify(data), original);
  assert.equal(s.calls.length, 1);
});

test('brightness labels use six significant digits while numeric inputs and source ranges retain full precision', async () => {
  const data = await success().json(), lo = .123456789012345, hi = 9.87654321098765;
  data.metadata.display = { available: true, unit: 'MJy/sr', shape: [1,2], values: [lo,hi], valid: [true,true], flags: [0,0], min: lo, max: hi, lo, hi, histogram: { counts: [1,1], edges: [lo,hi] } };
  const before = JSON.stringify(data);
  const s = setup({ response: { ok:true,status:200,json:async()=>data } }); await s.submit();
  assert.equal(s.e['minimum-number'].value,String(lo));
  assert.equal(s.e['maximum-number'].value,String(hi));
  assert.equal(s.e.minimum.value,lo);
  assert.equal(s.e.maximum.value,hi);
  assert.match(s.e['brightness-status'].textContent,/0\.123457.*9\.87654/);
  assert.match(s.e['histogram-range'].textContent,/0\.123457.*9\.87654/);
  s.e.stretch.value='asinh';s.e.stretch.events.change();
  assert.equal(s.e['minimum-number'].value,String(lo));
  assert.equal(s.e['maximum-number'].value,String(hi));
  assert.equal(JSON.stringify(data),before);
  assert.equal(s.calls.length,1);
});

for (const [radius, expected] of [['0.6', .01], ['5', 5/60], ['0.000001', .000001/60]]) test(`arcmin ${radius} converts to degrees without changing cutout policy`, async () => {
  const s = setup(); s.e.radius.value = radius; await s.submit();
  assert.equal(JSON.parse(s.calls[0][1].body).radius_deg, expected);
  assert.equal(JSON.parse(s.calls[0][1].body).cutout_size, undefined);
});

test('Preview details filter internal diagnostics and retain scientific caveats without mutating metadata', async () => {
  const data=await success().json();Object.assign(data.metadata,{sha256:'secret-checksum',product_id:'secret-product',wcs_header:{CRVAL1:'secret-wcs'},calibration:{status:'unverified',warning:'Calibration caveat',history:['secret-uuid']},warnings:['Scientific warning'],alignment:{status:'unverified',reason:'Few matched stars'}});
  const before=JSON.stringify(data),s=setup({response:{ok:true,status:200,json:async()=>data}});await s.submit();
  const text=['metadata','technical-metadata','preview-warnings'].map(id=>s.e[id].textContent||s.e[id].children.map(n=>n.textContent).join(' ')).join(' ');
  assert.doesNotMatch(text,/secret-|CRVAL1|sha256|history/);assert.match(text,/Calibration caveat/);assert.match(text,/Scientific warning/);assert.match(text,/Few matched stars/);assert.equal(JSON.stringify(data),before);
});
test('Preview click zoom synchronizes slider, anchors scrolling, stops at 32 and Fit restores without requests', async () => {
  const s=setup();await s.submit();const e=s.e,v=e.viewport,image=e.preview,count=s.calls.length;
  v.scrollLeft=v.scrollTop=0;
  const click=()=>v.events.click({target:image,clientX:parseFloat(image.style.width)*.8,clientY:parseFloat(image.style.height)*.8});
  const fit=Number(e.zoom.value);assert.equal(image.style.cursor,'zoom-in');
  v.events.click({target:e['preview-axes']});assert.equal(Number(e.zoom.value),fit);
  click();assert.ok(Math.abs(Number(e.zoom.value)-Math.min(32,fit*1.5))<1e-9);assert.equal(e['zoom-value'].textContent, e.zoom.value+'×');assert.ok(v.scrollLeft>0);
  for(let i=0;i<30;i++)click();assert.equal(Number(e.zoom.value),32);assert.equal(image.style.cursor,'default');
  s.resize();assert.equal(Number(e.zoom.value),32);e['fit-view'].events.click();assert.match(e['zoom-value'].textContent,/Fit/);assert.equal(v.scrollLeft,0);assert.equal(s.calls.length,count);
});


test('Preview hides absent optional fields and limitations but retains core unknowns', async () => {
  const s = setup(); await s.submit();
  const text = s.e.metadata.children.map(n => n.textContent).join(' ');
  assert.doesNotMatch(text, /Alignment|compatibility|Warnings|Failure reason|Not available/);
  assert.equal(s.e['technical-metadata'].hidden, true);
  assert.equal(s.e['scientific-limitations'].hidden, true);
  assert.equal(s.e['preview-warnings'].hidden, true);
  const summary = s.e['observation-summary'].children.map(n => n.textContent).join(' ');
  assert.match(summary, /Wavelength.*Not available/); assert.doesNotMatch(summary, /Valid pixel count/);
});

test('Preview keeps real scientific caveats once and hides inapplicable compatibility results', async () => {
  const data = await success().json();
  Object.assign(data.metadata, { truncated: true, wavelength_compatible: false, calibration_compatible: false,
    alignment: { status: 'failed', reason: 'Few matched stars' },
    warnings: ['Search incomplete; only retrieved candidates are shown.', 'Different wavelengths cannot be compared directly.'],
    display: { available: false, reason: 'No raw pixel display' }, wcs_axes: { available: false } });
  const s = setup({ response: { ok: true, status: 200, json: async () => data } }); await s.submit();
  const details = s.e.metadata.children.map(n => n.textContent).join(' ');
  assert.doesNotMatch(details, /Alignment status|compatibility|Warnings/);
  assert.equal((s.e['preview-warnings'].textContent.match(/Search incomplete/g) || []).length, 1);
  assert.match(s.e['preview-warnings'].textContent, /Different wavelengths.*Few matched stars/);
  assert.equal(s.e['scientific-limitations'].hidden, false);
  assert.match(s.e['technical-metadata'].children.map(n => n.textContent).join(' '), /Data quality.*No raw pixel display.*WCS status.*WCS unavailable/);
});
