import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const context = vm.createContext({});
vm.runInContext(readFileSync(new URL('../brightness.js', import.meta.url), 'utf8'), context);
const { rgba } = context.SpherexBrightness;

test('linear/asinh operate on raw values, flip FITS y, preserve null and quality masks', () => {
  const data = { shape: [2, 3], values: [-5, 0, 5, null, 100, 2], valid: [true, true, true, false, false, true], flags: [0, 0, 1 << 21, 0, 64, 0] };
  const original = JSON.stringify(data);
  const linear = rgba(data, -5, 5, 'linear', false, false);
  assert.equal(linear[3], 0); assert.equal(linear[7], 0);
  assert.equal(linear[12], 0); assert.equal(linear[16], 128); assert.equal(linear[20], 255);
  const inverse = rgba(data, -5, 5, 'linear', true, false);
  assert.equal(inverse[3], 0); assert.equal(inverse[7], 0);
  assert.equal(inverse[12], 255); assert.equal(inverse[16], 127);
  assert.ok(rgba(data, -5, 5, 'asinh', false, false)[16] > linear[16]);
  const overlay = rgba(data, -5, 5, 'linear', false, true);
  assert.equal(overlay[22], 80);
  assert.equal(JSON.stringify(data), original);
});

test('invalid ranges cannot replace the last good display', () => {
  for (const [lo, hi] of [[0, 0], [1, 0], [NaN, 1], [0, Infinity]]) {
    assert.throws(() => rgba({ shape: [1, 1], values: [0], valid: [true] }, lo, hi));
  }
});
