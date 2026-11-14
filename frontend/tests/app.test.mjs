import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
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
    set src(value) { this.url = value; queueMicrotask(() => imageFail ? this.onerror?.() : this.onload?.()); }
  }
  for (const [, id] of html.matchAll(/id="([^"]+)"/g)) elements[id] = new Element();
  for (const [id, value] of Object.entries({ ra: '127.69444', dec: '-39.17760', radius: '0.01', zoom: '12' })) elements[id].value = value;
  const calls = [], timers = new Map(); let timerId = 0;
  vm.runInNewContext(script, {
    document: { getElementById: id => { assert.ok(elements[id], `Missing HTML ID ${id}`); return elements[id]; }, createElement: () => new Element() },
    location: { hostname: host, protocol: host === '127.0.0.1' ? 'http:' : 'https:' }, window: {}, URL, AbortController, TypeError,
    localStorage: { getItem: () => { if (storageFail) throw Error(); return stored; }, setItem() {} },
    setTimeout: (fn, ms) => { timers.set(++timerId, { fn, ms }); return timerId; }, clearTimeout: id => timers.delete(id),
    fetch: async (...args) => { calls.push(args); if (hang) return new Promise((resolve, reject) => args[1].signal.addEventListener('abort', () => { const error = new Error(); error.name = 'AbortError'; reject(error); })); if (fetchFail) throw new TypeError('network'); return response || success(); }
  });
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
for (const [field, value] of [['ra', '360'], ['ra', '-1'], ['dec', '91'], ['dec', '-91'], ['radius', '0'], ['radius', '.084'], ['ra', ''], ['ra', 'NaN']]) {
  test(`reject invalid ${field}=${value}`, async () => { const s = setup(); s.e[field].value = value; await s.submit(); assert.equal(s.calls.length, 0); assert.equal(s.e.status.dataset.state, 'error'); });
}
test('coordinate boundaries accepted', async () => { const s = setup(); s.e.ra.value = '0'; s.e.dec.value = '-90'; s.e.radius.value = String(5 / 60); await s.submit(); assert.equal(s.calls.length, 1); });
test('public page defaults to Render and blocks loopback', async () => { const s = setup({ host: 'example.github.io', stored: JSON.stringify({ environment: 'local' }) }); assert.equal(s.e.environment.value, 'render'); await s.submit(); assert.equal(s.calls.length, 0); s.e['api-url'].value = 'http://localhost:8000'; await s.submit(); assert.match(s.e.status.textContent, /公開前端/); });
test('Render HTTPS, URL validation and environment persistence', async () => {
  const s = setup(); s.e.environment.value = 'render'; s.e.environment.events.change();
  for (const url of ['http://foo.onrender.com', 'https://foo.onrender.com/path', 'https://user:password@foo.onrender.com', 'not a url']) { s.e['api-url'].value = url; await s.submit(); assert.equal(s.calls.length, 0); }
  s.e['api-url'].value = 'https://foo.onrender.com/'; await s.submit(); assert.equal(s.calls[0][0], 'https://foo.onrender.com/api/preview');
});
for (const [code, state] of [['no_images', 'empty'], ['busy', 'error'], ['upstream_timeout', 'error'], ['cutout_failed', 'error'], ['invalid_input', 'error'], ['internal_error', 'error']]) {
  test(`API ${code} clears stale results and enables retry`, async () => { const s = setup({ response: { ok: false, status: code === 'no_images' ? 404 : 503, headers: { get: () => '5' }, json: async () => ({ error: { code, message: '測試錯誤' } }) } }); await s.submit(); assert.equal(s.e.status.dataset.state, state); assert.equal(s.e.preview.hidden, true); assert.equal(s.e.info.hidden, true); assert.equal(s.e.search.disabled, false); });
}
test('network/CORS error', async () => { const s = setup({ fetchFail: true }); await s.submit(); assert.match(s.e.status.textContent, /CORS/); });
test('malformed JSON', async () => { const s = setup({ response: { status: 502, json: async () => { throw Error(); } } }); await s.submit(); assert.match(s.e.status.textContent, /JSON/); });
test('expired PNG', async () => { const s = setup({ imageFail: true }); await s.submit(); assert.match(s.e.status.textContent, /快取/); assert.equal(s.e.black.disabled, true); });
test('storage unavailable still works', async () => { const s = setup({ storageFail: true }); await s.submit(); assert.equal(s.e.status.dataset.state, 'success'); });
test('API timeout releases form', async () => { const s = setup({ hang: true }); const task = s.submit(); s.timers.values().next().value.fn(); await task; assert.equal(s.e.search.disabled, false); assert.match(s.e.status.textContent, /180 秒/); assert.equal(s.timers.size, 0); });
