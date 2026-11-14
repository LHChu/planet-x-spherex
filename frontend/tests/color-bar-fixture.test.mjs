import { test } from 'node:test';
import assert from 'node:assert/strict';
import { inflateSync } from 'node:zlib';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { epochsFixture } from '../tools/epochs-fixture.mjs';

const context = { window: {} };
vm.runInNewContext(readFileSync(new URL('../color-bar.js', import.meta.url), 'utf8'), context);
const cb = context.window.SpherexColorBar;
async function request(url, body, scenario) {
  const req = { url, method: body ? 'POST' : 'GET', async *[Symbol.asyncIterator]() { yield JSON.stringify(body); } };
  let result;
  const res = { writeHead(status) { assert.equal(status, 200); }, end(data) { result = data; } };
  assert.equal(await epochsFixture(req, res, scenario), true);
  return Buffer.isBuffer(result) ? result : JSON.parse(result);
}
function pngRows(png) {
  const chunks = [];
  for (let offset = 8; offset < png.length;) {
    const size = png.readUInt32BE(offset), type = png.toString('ascii', offset + 4, offset + 8);
    if (type === 'IDAT') chunks.push(png.subarray(offset + 8, offset + 8 + size));
    offset += size + 12;
  }
  return inflateSync(Buffer.concat(chunks));
}
for (const scenario of ['comparable', 'browse', 'browse-linear', 'missing-normalization']) {
  test(`offline browser fixture ${scenario} declares the actual PNG brightness mapping`, async () => {
    const search = await request('/api/epochs/search', { ra: 127.69444, dec: -39.1776 }, scenario);
    const sequence = await request('/api/epoch-frames', { search_id: search.search_id, product_ids: search.products.slice(0, 3).map(p => p.product_id) }, scenario);
    for (const frame of sequence.frames) {
      const scale = cb.epoch(sequence, frame);
      if (scenario === 'missing-normalization') { assert.equal(scale, null); continue; }
      assert.ok(scale);
      const rows = pngRows(await request(frame.image_url, null, scenario));
      for (let y = 0; y < 29; y++) for (let x = 0; x < 29; x++) {
        const at = y * 117 + 1 + x * 4;
        assert.equal(rows[y * 117], 0);
        if (x === y && x < 2) { assert.equal(rows[at + 3], 0); continue; }
        const value = .3 + 10 * Math.exp(-((x - 14 - frame.index) ** 2 + (y - 14) ** 2) / 5);
        assert.equal(rows[at], cb.gray(scale, value));
        assert.equal(rows[at + 3], 255);
      }
    }
    if (scenario === 'comparable') assert.deepEqual(cb.epoch(sequence, sequence.frames[0]), cb.epoch(sequence, sequence.frames[2]));
    if (scenario === 'browse-linear') assert.equal(cb.epoch(sequence, sequence.frames[1]).stretch, 'linear');
  });
}
