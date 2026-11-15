import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { axesFixture } from './axes-fixture.mjs';

class Element {
  constructor() { this.children = []; this.style = {}; this.attrs = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getContext() { return { createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }), putImageData: image => { this.image = image; } }; }
}
const context = { window: {}, document: { createElement: () => new Element() } };
for (const script of ['brightness.js', 'wcs-axes.js', 'color-bar.js']) vm.runInNewContext(readFileSync(new URL(`../${script}`, import.meta.url), 'utf8'), context);
const cb = context.window.SpherexColorBar;
const normal = (overrides = {}) => ({ lo: -2, hi: 6, denominator: 8, stretch: 'asinh', a: 10, rounding: 'nearest_even', ...overrides });
const scale = (overrides = {}) => cb.mapping({ ...normal(), unit: 'MJy/sr', ...overrides });

test('Linear and Asinh Color Bars match every displayed Preview gray level, including inversion', () => {
  for (const stretch of ['linear', 'asinh', 'log', 'sqrt']) for (const inverse of [false, true]) {
    const s = scale({ stretch, inverse, rounding: 'half_up' });
    const values = Array.from({ length: 257 }, (_, i) => -2 + 8 * i / 256);
    const display = { shape: [1, values.length], values, valid: values.map(() => true) };
    const pixels = context.window.SpherexBrightness.rgba(display, -2, 6, stretch, inverse, false);
    values.forEach((value, i) => assert.equal(cb.gray(s, value), pixels[i * 4]));
    const ramp = cb.ramp(s);
    assert.equal(ramp[0], inverse ? 0 : 255);
    assert.equal(ramp.at(-4), inverse ? 255 : 0);
  }
  assert.ok(cb.gray(scale(), 2) > cb.gray(scale({ stretch: 'linear' }), 2));
});

test('backend denominator floor and nearest-even quantization are respected', () => {
  const s = scale({ lo: 1, hi: 1 + 1e-10, denominator: 1e-8 });
  assert.ok(cb.gray(s, s.hi) < 255);
  assert.equal(cb.ramp(s)[0], cb.gray(s, s.hi));
  const even = scale({ lo: 0, hi: 1, denominator: 1, stretch: 'linear' });
  const up = scale({ lo: 0, hi: 1, denominator: 1, stretch: 'linear', rounding: 'half_up' });
  assert.equal(cb.gray(even, .5 / 255), 0);
  assert.equal(cb.gray(up, .5 / 255), 1);
});

test('invalid units, ranges, transforms and missing metadata never invent a scale', () => {
  for (const overrides of [{ unit: undefined }, { unit: 'mJy/sr' }, { unit: 'Jy/sr' }, { lo: null },
    { hi: NaN }, { hi: Infinity }, { hi: -2 }, { hi: -3 }, { denominator: undefined }, { denominator: 0 },
    { denominator: 1 }, { stretch: 'unknown' }, { a: null }, { a: 0 }, { rounding: 'unknown' }]) assert.equal(scale(overrides), null);
  assert.equal(cb.preview({}), null);
  assert.equal(cb.gray(scale(), NaN), null);
  assert.equal(cb.gray(scale(), null), null);
  assert.equal(cb.epoch({}, {}), null);
});

test('Preview uses applied physical limits, never NaN or masked outliers, and preserves source data', () => {
  const metadata = { display: { available: true, unit: 'MJy/sr', values: [0, null, NaN, 1e30], valid: [true, false, true, false], flags: [1 << 21, 0, 0, 64] } };
  const original = JSON.stringify(metadata);
  const s = cb.preview(metadata, { lo: -2, hi: 6, stretch: 'asinh' });
  assert.equal(s.lo, -2); assert.equal(s.hi, 6); assert.equal(s.a, 10);
  assert.equal(JSON.stringify(metadata), original);
  metadata.display.valid[0] = false;
  assert.equal(cb.preview(metadata, { lo: -2, hi: 6, stretch: 'linear' }), null);
  metadata.display.valid[1] = true; // null is never a finite zero.
  assert.equal(cb.preview(metadata, { lo: -2, hi: 6, stretch: 'linear' }), null);
});

test('PNG-only Preview uses the declared PNG stretch rather than the client Linear default', () => {
  const metadata = { display: { available: false, unit: 'MJy/sr' }, stretch: { p1: -3, p99: 9, method: 'asinh(10x)' } };
  const s = cb.preview(metadata, null, true);
  assert.equal(s.stretch, 'asinh'); assert.equal(s.lo, -3); assert.equal(s.hi, 9);
  assert.equal(s.inverse, true); assert.equal(s.rounding, 'nearest_even');
  metadata.stretch.method = 'unknown'; assert.equal(cb.preview(metadata), null);
});

test('common sequence validates every delivered frame; browse uses each explicit frame mapping', () => {
  const frames = [0, 1, 2].map(i => ({ image_url: `/${i}.png`, normalization: normal() }));
  const sequence = { mode: 'comparable_visualization', normalization: { bunit: 'MJy/sr', lo: -2, hi: 6 }, frames };
  const first = cb.epoch(sequence, frames[0]);
  for (const frame of frames) assert.deepEqual(cb.epoch(sequence, frame), first);
  frames[2].normalization.hi = 7;
  assert.equal(cb.epoch(sequence, frames[0]), null);
  sequence.mode = 'observation_browse';
  frames[2].normalization = normal({ lo: 0, hi: 4, denominator: 4, stretch: 'linear' });
  assert.equal(cb.epoch(sequence, frames[2]).stretch, 'linear');
  assert.equal(cb.epoch(sequence, frames[2]).hi, 4);
  delete frames[2].normalization.denominator; assert.equal(cb.epoch(sequence, frames[2]), null);
});

test('Color Bar ticks are physical values and never alter WCS geometry at any zoom', () => {
  const s = scale({ lo: -3, hi: 9, denominator: 12 });
  for (const zoom of [1, 12, 32]) {
    const axes = context.window.SpherexAxes.layout(axesFixture(), 29, 29, zoom);
    const before = JSON.stringify(axes), host = new Element();
    const size = cb.render(host, s, axes, 'Grayscale only.');
    assert.equal(JSON.stringify(axes), before);
    assert.ok(parseFloat(host.style.left) > axes.margin.left + axes.width);
    assert.ok(size.width >= parseFloat(host.style.left) + 195);
    const body = host.children.find(n => n.className === 'colorbar-body');
    const ticks = body.children.filter(n => n.className === 'colorbar-tick');
    assert.deepEqual(ticks.map(n => n.textContent), ['-3', '0', '3', '6', '9']);
    assert.equal(body.children[0].image.data[0], cb.gray(s, 9));
    assert.equal(host.children[0].textContent, 'Surface Brightness (MJy/sr)');
  }
  const host = new Element(); cb.render(host, null, context.window.SpherexAxes.layout(null, 29, 29, 12), '');
  assert.equal(host.children.length, 2); assert.equal(host.children[1].textContent, 'Color Bar unavailable');
  const tiny = new Element();
  cb.render(tiny, scale({ lo: 1, hi: 1 + 1e-10, denominator: 1e-8 }), context.window.SpherexAxes.layout(null, 29, 29, 12), '');
  const labels = tiny.children.find(n => n.className === 'colorbar-body').children.filter(n => n.className === 'colorbar-tick').map(n => n.textContent);
  assert.equal(new Set(labels).size, 5);
});
