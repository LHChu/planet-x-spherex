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
    assert.throws(() => rgba({ shape: [1, 1], values: [0], valid: [true] }, lo, hi), /maximum must exceed the minimum.*finite/);
  }
  assert.throws(() => rgba({ shape: [1, 1], values: [0], valid: [true] }, 0, 1, 'unsupported'), /Unknown stretch method/);
});


test('Log safely maps negative, zero, masked and nonfinite science values without changing input', () => {
  const d = { shape: [1, 9], values: [-10, -5, 0, 5, 10, NaN, Infinity, null, 1e30], valid: [true,true,true,true,true,true,true,true,false] };
  const copy = [...d.values], pixels = rgba(d, -5, 5, 'log', false, false);
  assert.equal(pixels[0], 0); assert.equal(pixels[4], 0);
  assert.equal(pixels[8], Math.round(Math.log1p(500) / Math.log1p(1000) * 255));
  assert.equal(pixels[12], 255); assert.equal(pixels[16], 255);
  for (const i of [5,6,7,8]) assert.equal(pixels[i*4+3], 0);
  assert.deepEqual(d.values, copy);
});

test('Histogram ticks remain physical, adapt density, and never alter counts', () => {
  const h = { counts: [0,2,5,1], edges: [-10,-5,0,5,10] }, copy = JSON.stringify(h);
  const { histogramModel } = context.SpherexBrightness;
  const wide = histogramModel(h,640), narrow = histogramModel(h,300);
  assert.equal(wide.total,8); assert.equal(wide.peak,5);
  assert.deepEqual(Array.from(wide.x), ['-10','-5','0','5','10']);
  assert.equal(narrow.x.length,3); assert.equal(JSON.stringify(h),copy);
  for (const edges of [[-1e-8,1e-8], [1e9,1e9+1], [0,1]]) {
    const model = histogramModel({ counts:[1], edges });
    assert.ok(model.x.every(x => Number.isFinite(Number(x))));
    assert.equal(new Set(model.x).size, model.x.length);
  }
});

test('Sqrt normalizes before rooting, clips endpoints, preserves masks and inversion across stretch switches', () => {
  const d = {shape:[1,10], values:[-8,-4,-2,0,4,8,NaN,Infinity,null,1], valid:[true,true,true,true,true,true,true,true,true,false],flags:[0,0,0,1,0,0,0,0,0,64]};
  const before = [...d.values];
  for (const inverse of [false,true]) {
    const result = rgba(d,-4,4,'sqrt',inverse,false);
    for (const [i,t] of [[0,0],[1,0],[2,.25],[3,.5],[4,1],[5,1]]) {
      const expected=Math.round(Math.sqrt(t)*255);
      assert.equal(result[i*4],inverse?255-expected:expected);assert.equal(result[i*4+3],255);
    }
    for(const i of [6,7,8,9])assert.equal(result[i*4+3],0);
  }
  assert.equal(rgba(d,-4,4,'sqrt',false,true)[14],80,'FLAGS overlay remains quality only');
  const original=rgba(d,-4,4,'linear',false,false);
  for(const method of ['sqrt','asinh','log','linear']) rgba(d,-4,4,method);
  assert.deepEqual(rgba(d,-4,4,'linear',false,false),original);assert.deepEqual(d.values,before);
});
