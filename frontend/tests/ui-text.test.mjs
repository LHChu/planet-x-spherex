import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');

test('page declares English and contains no Chinese UI or accessibility text', () => {
  const html = read('../index.html');
  assert.match(html, /<html lang="en">/);
  assert.doesNotMatch(html, /\p{Script=Han}/u);
  for (const term of ['NASA', 'SPHEREx', 'RA', 'Dec', 'WCS', 'Detector', 'MJy/sr', 'UTC', 'SIA', 'FITS', 'Linear', 'Asinh']) {
    assert.ok(html.includes(term), `Missing scientific term: ${term}`);
  }
});

test('dynamic UI and API error messages contain no untranslated Chinese', () => {
  for (const path of ['../app.js', '../epochs.js', '../brightness.js', '../wcs-axes.js', '../color-bar.js', '../../backend/app/main.py', '../../backend/app/service.py', '../../backend/app/wcs_axes.py']) {
    const source = read(path)
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/^\s*(?:\/\/|#).*$/gm, '')
      .replace(/\|\u672a\u77e5\|/g, '|');
    assert.doesNotMatch(source, /\p{Script=Han}/u, path);
  }
});
