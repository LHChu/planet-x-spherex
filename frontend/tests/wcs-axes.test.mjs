import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { axesFixture } from './axes-fixture.mjs';

class Element {
  constructor() { this.style = {}; this.children = []; this.attrs = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  setAttribute(k, v) { this.attrs[k] = v; }
}
const context = { window: {}, document: { createElement: () => new Element() } };
vm.runInNewContext(readFileSync(new URL('../wcs-axes.js', import.meta.url), 'utf8'), context);
const { layout, render } = context.window.SpherexAxes;

test('non-square FITS centres and cell boundaries map to vertically flipped PNG exactly', () => {
  const metadata = axesFixture(29, 17), original = JSON.stringify(metadata);
  for (const zoom of [1, 12, 32]) {
    const model = layout(metadata, 29, 17, zoom);
    assert.equal(model.available, true);
    assert.deepEqual(Array.from(model.ra, t => t.position), [0, .5 * zoom, 14.5 * zoom, 28.5 * zoom, 29 * zoom]);
    assert.deepEqual(Array.from(model.dec, t => t.position), [17 * zoom, 16.5 * zoom, 8.5 * zoom, .5 * zoom, 0]);
    assert.equal(model.width, 29 * zoom); assert.equal(model.height, 17 * zoom);
    assert.equal(model.ra[3].degrees, 359.981);
  }
  assert.equal(JSON.stringify(metadata), original);
});

test('missing, invalid or mismatched WCS displays unavailable without guessed ticks', () => {
  for (const metadata of [null, {}, { available: false }, { ...axesFixture(), png_y_flipped: false },
    { ...axesFixture(), pixel_origin: 1 }, { ...axesFixture(), frame: 'FK5' },
    { ...axesFixture(), shape_yx: [17, 29] }, { ...axesFixture(), ra_ticks: [{ pixel: -1, degrees: 4 }] },
    { ...axesFixture(), dec_ticks: [{ pixel: 1, degrees: NaN }] },
    { ...axesFixture(), ra_ticks: [{ pixel: 1, degrees: '<script>bad</script>' }] }]) {
    const host = new Element();
    const model = render(host, metadata, 29, 29, 12);
    assert.equal(model.available, false);
    assert.equal(host.children.length, 1);
    assert.equal(host.children[0].textContent, 'WCS unavailable');
  }
});

test('rendered ticks and labels share the image offset; zoom changes positions only', () => {
  const metadata = axesFixture(29, 17), host = new Element();
  for (const zoom of [1, 12, 32]) {
    const model = render(host, metadata, 29, 17, zoom);
    const xTicks = host.children.filter(n => n.className === 'wcs-x-tick');
    const yTicks = host.children.filter(n => n.className === 'wcs-y-tick');
    for (const node of xTicks) assert.ok(model.ra.some(t => `${model.margin.left + t.position}px` === node.style.left && Number(node.children[0].textContent) === Number(t.degrees.toFixed(6))));
    for (const node of yTicks) assert.ok(model.dec.some(t => `${model.margin.top + t.position}px` === node.style.top && Number(node.children[0].textContent) === Number(t.degrees.toFixed(6))));
    assert.ok(host.children.some(n => n.textContent === 'Right Ascension (RA) · degrees'));
    assert.ok(host.children.some(n => n.textContent === 'Declination (Dec) · degrees'));
    assert.ok(xTicks.length >= 1); assert.ok(yTicks.length >= 1);
    if (zoom === 1) assert.equal(xTicks.length, 1);
  }
});
