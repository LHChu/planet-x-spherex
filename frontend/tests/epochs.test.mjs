import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const sid = 'a'.repeat(32);
const product = (id, day, detector = 1, obs = id) => ({ product_id: id, obs_id: obs, detector, t_min: 60000 + day, source_collections: ['spherex_dr1'], frame_status: 'not_requested' });
const candidates = [product('late', 4), product('early', 0), product('middle', 1), product('fourth', 2), product('d2', 3, 2), product('alternative', 4, 1, 'late')];
function setup({ apiError, pngError = false, failed = false, allFailed = false, mode = 'observation_browse', malformed = false, network = false, hang = false, page = false, reverseDates = false, available = candidates } = {}) {
  const elements = {}, calls = [], intervals = new Map(), timeouts = new Map(), urls = [], revoked = [];
  let serial = 0;
  class Element {
    constructor() { this.value = ''; this.children = []; this.events = {}; this.attrs = {}; this.style = {}; this.dataset = {}; this.naturalWidth = this.naturalHeight = 29; this.classList = { toggle() {}, remove() {} }; }
    addEventListener(name, fn) { this.events[name] = fn; }
    setAttribute(k, v) { this.attrs[k] = v; }
    replaceChildren(...items) { this.children = items; }
    append(...items) { this.children.push(...items); }
    set src(value) { this.url = value; queueMicrotask(() => this.onload?.()); }
  }
  for (const [, id] of html.matchAll(/id="([^"]+)"/g)) elements[id] = new Element();
  Object.entries({ ra: '127.69444', dec: '-39.17760', radius: '0.01', zoom: '12', 'epoch-zoom': '12', 'epoch-speed': '1000', 'explorer-mode': 'preview' }).forEach(([id, value]) => elements[id].value = value);
  class MockURL extends URL {
    static createObjectURL() { const url = `blob:frame-${urls.length}`; urls.push(url); return url; }
    static revokeObjectURL(url) { revoked.push(url); }
  }
  const ok = data => ({ ok: true, status: 200, json: async () => data });
  const environment = {
    document: { getElementById: id => { assert.ok(elements[id], id); return elements[id]; }, createElement: () => new Element() },
    window: {}, URL: MockURL, AbortController, TypeError, location: { hostname: '127.0.0.1', protocol: 'http:' }, localStorage: { getItem() {}, setItem() {} },
    setTimeout: (fn, ms) => { const id = ++serial; timeouts.set(id, { fn, ms }); return id; }, clearTimeout: id => timeouts.delete(id),
    setInterval: (fn, ms) => { const id = ++serial; intervals.set(id, { fn, ms }); return id; }, clearInterval: id => intervals.delete(id),
    fetch: async (url, options) => {
      calls.push({ url, ...options });
      if (network) throw new TypeError('network');
      if (hang) return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => { const e = Error(); e.name = 'AbortError'; reject(e); }));
      if (malformed) return { ok: true, status: 200, json: async () => { throw Error(); } };
      if (url.endsWith('/api/epochs/search')) return ok({ search_id: sid, products: page && !JSON.parse(options.body).cursor ? available.slice(0, 2) : available, collections: [{ name: 'spherex_dr1', status: 'partial', truncated: true }], complete: false, pagination: { next_cursor: page && !JSON.parse(options.body).cursor ? 'cursor' : null } });
      if (apiError || pngError && options.method === 'GET') return { ok: false, status: 410, headers: { get: () => '5' }, json: async () => ({ error: { code: apiError || 'frame_not_found', message: 'test failure' } }) };
      if (options.method === 'GET') return { ok: true, blob: async () => ({}) };
      const ids = JSON.parse(options.body).product_ids;
      return ok({ search_id: sid, sequence_id: sid, mode, normalization: { policy: 'mock-policy' }, frames: ids.map((id, index) => ({ ...available.find(p => p.product_id === id), index, observation_utc: `2025-01-0${reverseDates ? ids.length - index : index + 1}T00:00:00Z`, time_source: 'FITS_DATE-OBS', status: allFailed || failed && index === 1 ? 'failed' : 'alignment_unqualified', alignment: { status: 'unverified' }, image_url: allFailed || failed && index === 1 ? null : `http://internal/api/epoch-frames/${sid}/${index}.png`, error: { code: 'cutout_failed', message: 'kept failure slot' }, target_wavelength_um: .86, target_bandwidth_um: .021 })) });
    }
  };
  for (const file of ['epochs.js', 'app.js']) vm.runInNewContext(readFileSync(new URL(`../${file}`, import.meta.url), 'utf8'), environment);
  const e = elements;
  e['explorer-mode'].value = 'epochs'; e['explorer-mode'].events.change();
  const submit = () => e['search-form'].events.submit({ preventDefault() {} });
  const check = id => e['epoch-products'].children.find(row => row.children[3].textContent.split(' · ')[2] === id)?.children[0].children[0];
  const visibleIds = () => e['epoch-products'].children.map(row => row.children[3].textContent.split(' · ')[2]);
  const choose = id => { const c = check(id); c.checked = !c.checked; c.events.change(); };
  return { e, calls, intervals, timeouts, urls, revoked, submit, check, visibleIds, choose, quick: count => e['select-first-' + count].events.click(), load: () => e['load-frames'].events.click() };
}
test('search uses shared coordinates and detectors array, never loads FITS automatically', async () => {
  const s = setup(); s.e.detector.value = '6'; await s.submit();
  assert.deepEqual(JSON.parse(s.calls[0].body), { ra: 127.69444, dec: -39.1776, radius_deg: .01, detectors: [6], limit: 100 });
  assert.equal(s.calls.length, 1); assert.match(s.calls[0].url, /epochs\/search$/);
  assert.match(s.e['epochs-sources'].textContent, /partial.*truncated.*查詢不完整/);
  assert.match(s.e['epoch-products'].children[0].children[1].textContent, /2023-/);
  assert.match(s.e['epoch-products'].children[0].children[3].textContent, /early.*not_requested/);
  assert.equal(s.e['preview-panel'].hidden, true);
});
test('2–3 products: same detector, distinct exposures, alternatives and fourth hidden', async () => {
  const s = setup(); await s.submit(); s.choose('late');
  assert.equal(s.check('d2'), undefined); assert.equal(s.check('alternative'), undefined);
  assert.equal(s.e['load-frames'].disabled, true);
  s.choose('early'); assert.equal(s.e['load-frames'].disabled, false); s.choose('middle');
  assert.equal(s.check('fourth'), undefined);
  await s.load(); assert.deepEqual(JSON.parse(s.calls[1].body), { search_id: sid, product_ids: ['early', 'middle', 'late'] });
  assert.equal(s.calls.filter(c => c.method === 'GET').length, 3);
  assert.match(s.e['epoch-current'].textContent, /2025-01-01.*FITS_DATE-OBS.*0.86.*0.021.*spherex_dr1.*unverified/);
});
test('play, pause, speed, slider and zoom reuse loaded PNG nodes with zero extra fetches', async () => {
  const s = setup(); await s.submit(); s.choose('late'); s.choose('early'); await s.load();
  const count = s.calls.length, nodes = [...s.urls];
  s.e['epoch-play'].events.click(); assert.equal(s.intervals.size, 1);
  s.intervals.values().next().value.fn(); assert.match(s.e['epoch-current'].textContent, /slot 1/);
  s.e['epoch-speed'].value = '500'; s.e['epoch-speed'].events.change(); assert.equal(s.intervals.values().next().value.ms, 500);
  s.e['epoch-play'].events.click(); assert.equal(s.intervals.size, 0);
  s.e['epoch-play'].events.click(); s.e['epoch-time'].value = '0'; s.e['epoch-time'].events.input(); assert.equal(s.intervals.size, 0);
  s.e['epoch-next'].events.click(); s.e['epoch-prev'].events.click();
  s.e['epoch-zoom'].value = '20'; s.e['epoch-zoom'].events.input();
  assert.equal(s.e['epoch-viewport'].children[0].style.width, '580px');
  assert.equal(s.calls.length, count); assert.deepEqual(s.urls, nodes);
  assert.match(s.e['sequence-mode'].textContent, /observation_browse.*不可比較亮度/);
  s.e['epoch-play'].events.click(); s.e['explorer-mode'].value = 'preview'; s.e['explorer-mode'].events.change();
  assert.equal(s.intervals.size, 0); assert.equal(s.e['preview-panel'].hidden, false);
  assert.equal(s.timeouts.size, 0);
});
test('failed slot retains index/date/reason and is visited during playback', async () => {
  const s = setup({ failed: true }); await s.submit(); s.choose('early'); s.choose('late'); await s.load();
  assert.equal(s.e['epoch-slots'].children.length, 2);
  s.e['epoch-play'].events.click(); s.intervals.values().next().value.fn();
  assert.match(s.e['epoch-current'].textContent, /slot 1.*2025-01-02.*cutout_failed.*kept failure slot/);
  assert.match(s.e['epoch-viewport'].children[0].textContent, /無法顯示/);
  assert.equal(s.calls.length, 3);
});
test('all failed slots stay visible and playback disabled', async () => {
  const s = setup({ allFailed: true }); await s.submit(); s.choose('early'); s.choose('late'); await s.load();
  assert.equal(s.e['epoch-slots'].children.length, 2); assert.equal(s.e['epoch-play'].disabled, true); assert.equal(s.calls.length, 2);
});
test('comparable visualization remains explicitly non-photometric', async () => {
  const s = setup({ mode: 'comparable_visualization' }); await s.submit(); s.choose('early'); s.choose('late'); await s.load();
  assert.match(s.e['sequence-mode'].textContent, /comparable_visualization.*共用亮度範圍.*不是光度測量/);
});
test('expired search disables loading and instructs explicit fresh search', async () => {
  const s = setup({ apiError: 'search_expired' }); await s.submit(); s.choose('early'); s.choose('late'); await s.load();
  assert.match(s.e['epochs-status'].textContent, /search_expired.*重新查詢/); assert.equal(s.e['load-frames'].disabled, true); assert.equal(s.calls.length, 2);
});
test('missing cached PNG keeps slots and asks for requery without automatic retries', async () => {
  const s = setup({ pngError: true }); await s.submit(); s.choose('early'); s.choose('late'); await s.load();
  assert.match(s.e['epoch-current'].textContent, /frame_not_found.*重新查詢/); assert.equal(s.e['epoch-slots'].children.length, 2); assert.equal(s.calls.length, 4);
});
test('pagination keeps snapshot query even when form changed; fresh search revokes blob URLs', async () => {
  const s = setup({ page: true }); await s.submit(); s.choose('early'); s.choose('late'); await s.load();
  s.e.ra.value = '10'; await s.e['epochs-more'].events.click();
  assert.equal(JSON.parse(s.calls.at(-1).body).ra, 127.69444); assert.equal(JSON.parse(s.calls.at(-1).body).cursor, 'cursor');
  await s.submit(); assert.equal(s.revoked.length, 2); assert.match(s.e['epoch-selection'].textContent, /已選 0/);
});
for (const [options, pattern] of [[{ malformed: true }, /JSON/], [{ network: true }, /CORS/]]) {
  test(`search error ${pattern} releases controls`, async () => { const s = setup(options); await s.submit(); assert.match(s.e['epochs-status'].textContent, pattern); assert.equal(s.e.search.disabled, false); assert.equal(s.timeouts.size, 0); });
}
test('API timeout is bounded and releases controls', async () => {
  const s = setup({ hang: true }); const pending = s.submit(); s.timeouts.values().next().value.fn(); await pending;
  assert.match(s.e['epochs-status'].textContent, /逾時/); assert.equal(s.e.search.disabled, false); assert.equal(s.timeouts.size, 0);
});
test('invalid coordinates issue no requests', async () => { const s = setup(); s.e.ra.value = '360'; await s.submit(); assert.equal(s.calls.length, 0); assert.match(s.e['epochs-status'].textContent, /座標/); });
test('timeline sorts actual FITS UTC dates while retaining original backend slot identity', async () => {
  const s = setup({ reverseDates: true }); await s.submit(); s.choose('early'); s.choose('middle'); s.choose('late'); await s.load();
  assert.match(s.e['epoch-current'].textContent, /slot 2.*2025-01-01.*late/);
  s.e['epoch-next'].events.click(); assert.match(s.e['epoch-current'].textContent, /slot 1.*2025-01-02.*middle/);
  s.e['epoch-next'].events.click(); assert.match(s.e['epoch-current'].textContent, /slot 0.*2025-01-03.*early/);
  assert.equal(s.calls.length, 5);
});
test('busy error exposes Retry-After and never automatically retries', async () => {
  const s = setup({ apiError: 'busy' }); await s.submit(); s.choose('early'); s.choose('late'); await s.load();
  assert.match(s.e['epochs-status'].textContent, /busy.*Retry-After: 5/); assert.equal(s.calls.length, 2); assert.equal(s.e['load-frames'].disabled, false);
});

test('main list hides invalid candidates and keeps one representative per exposure', async () => {
  const invalid = [product('unknown-detector', -1, null), product('missing-obs', -1, 1, null), product('empty-obs', -1, 1, ''), product('whitespace-obs', -1, 1, '  '), product('unknown-obs', -1, 1, 'UNKNOWN'), product('unknown-epoch', -1, 1, 'unknown-product'), product('missing-product', -1)];
  invalid.at(-1).product_id = '';
  const s = setup({ available: [...invalid, ...candidates] }); await s.submit();
  assert.deepEqual(s.visibleIds(), ['early', 'middle', 'fourth', 'd2', 'late']);
  assert.ok(s.e['epoch-products'].children.every(row => !row.children[0].children[0].disabled));
  s.choose('late'); assert.deepEqual(s.visibleIds(), ['early', 'middle', 'fourth', 'late']);
  s.choose('early'); s.choose('middle'); assert.deepEqual(s.visibleIds(), ['early', 'middle', 'late']);
  s.choose('late'); assert.ok(s.check('fourth')); assert.equal(s.check('d2'), undefined);
  s.choose('early'); s.choose('middle'); assert.ok(s.check('d2'));
  assert.equal(s.calls.length, 1);
});

for (const count of [2, 3]) {
  test(`Select first ${count} selects only legal visible products and Load frames sends exactly those IDs`, async () => {
    const s = setup(); await s.submit(); s.quick(count);
    const expected = ['early', 'middle', 'fourth'].slice(0, count);
    assert.deepEqual(s.visibleIds().filter(id => s.check(id).checked), expected);
    assert.equal(s.check('d2'), undefined); assert.equal(s.check('alternative'), undefined);
    assert.equal(s.calls.length, 1); // Quick selection itself never loads frames.
    await s.load(); assert.deepEqual(JSON.parse(s.calls[1].body), { search_id: sid, product_ids: expected });
    const fetches = s.calls.length;
    s.e['epoch-play'].events.click(); s.intervals.values().next().value.fn();
    s.e['epoch-time'].value = '0'; s.e['epoch-time'].events.input();
    s.e['epoch-next'].events.click(); s.e['epoch-prev'].events.click();
    s.e['explorer-mode'].value = 'preview'; s.e['explorer-mode'].events.change();
    s.e['explorer-mode'].value = 'epochs'; s.e['explorer-mode'].events.change();
    assert.equal(s.calls.length, fetches);
  });
}

test('quick selection uses the visible detector and cannot mix or select too few exposures', async () => {
  const s = setup(); await s.submit(); s.choose('d2');
  assert.deepEqual(s.visibleIds(), ['d2']);
  assert.equal(s.e['select-first-2'].disabled, true); assert.equal(s.e['select-first-3'].disabled, true);
  s.quick(2); s.quick(3); assert.equal(s.check('d2').checked, true); assert.equal(s.e['load-frames'].disabled, true);
  s.choose('d2'); s.choose('late'); s.quick(3);
  assert.deepEqual(s.visibleIds(), ['early', 'middle', 'fourth']);
  s.quick(2); assert.deepEqual(s.visibleIds().filter(id => s.check(id).checked), ['early', 'middle']);
  assert.ok(s.check('late')); assert.equal(s.calls.length, 1);
});

test('quick selection is unavailable without candidates, while loading, and after search expiry', async () => {
  const empty = setup({ available: [] }); await empty.submit();
  assert.deepEqual(empty.visibleIds(), []); assert.equal(empty.e['select-first-2'].disabled, true); assert.equal(empty.e['select-first-3'].disabled, true);
  const s = setup({ apiError: 'search_expired' }); await s.submit(); s.quick(2);
  const pending = s.load();
  assert.equal(s.e['select-first-2'].disabled, true); assert.equal(s.e['select-first-3'].disabled, true);
  s.quick(3); await pending;
  assert.deepEqual(JSON.parse(s.calls[1].body).product_ids, ['early', 'middle']);
  assert.deepEqual(s.visibleIds(), []); assert.equal(s.e['select-first-2'].disabled, true); assert.equal(s.e['select-first-3'].disabled, true);
});
