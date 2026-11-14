// Synthetic UI fixture only: never queries NASA and does not validate WCS science.
import { deflateSync } from 'node:zlib';
const searchId = 'b'.repeat(32), sequenceId = 'c'.repeat(32);
const products = [0, 1, 2, 3, 4, 5].map(i => ({
  product_id: `fixture-product-${i}`, obs_id: i === 5 ? 'fixture-exposure-0' : `fixture-exposure-${i}`,
  detector: i === 4 ? 2 : 1, t_min: 60794 + [0, 2, 8, 16, 20, 0][i], t_max: 60794 + [0, 2, 8, 16, 20, 0][i] + .001,
  source_collections: ['SYNTHETIC_UI_FIXTURE'], obs_collection: 'SYNTHETIC_UI_FIXTURE', frame_status: 'not_requested',
  calibration_status: 'synthetic_unverified', warnings: ['TEST DATA ONLY; no scientific alignment validation']
}));
const utc = mjd => new Date((mjd - 40587) * 86400000).toISOString();
function crc32(bytes) {
  let crc = -1;
  for (const byte of bytes) { crc ^= byte; for (let b = 0; b < 8; b++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0); }
  return (crc ^ -1) >>> 0;
}
function chunk(type, data) {
  const body = Buffer.concat([Buffer.from(type), data]), size = Buffer.alloc(4), crc = Buffer.alloc(4);
  size.writeUInt32BE(data.length); crc.writeUInt32BE(crc32(body)); return Buffer.concat([size, body, crc]);
}
function normalization(index, scenario) {
  const lo = scenario === 'comparable' ? 0 : index * .2;
  const hi = scenario === 'comparable' ? 12 : 10 + index * 2;
  return { lo, hi, denominator: Math.max(hi - lo, 1e-8), stretch: scenario === 'browse-linear' && index === 1 ? 'linear' : 'asinh', a: 10, rounding: 'nearest_even' };
}
function png(index, scenario) {
  const header = Buffer.alloc(13); header.writeUInt32BE(29, 0); header.writeUInt32BE(29, 4); header[8] = 8; header[9] = 6;
  const pixels = Buffer.alloc(29 * (1 + 29 * 4));
  for (let y = 0; y < 29; y++) for (let x = 0; x < 29; x++) {
    const at = y * 117 + 1 + x * 4;
    const n = normalization(index, scenario);
    const value = .3 + 10 * Math.exp(-((x - 14 - index) ** 2 + (y - 14) ** 2) / 5);
    const fraction = Math.max(0, Math.min(1, (value - n.lo) / n.denominator));
    const scaled = 255 * (n.stretch === 'linear' ? fraction : Math.asinh(n.a * fraction) / Math.asinh(n.a));
    const lower = Math.floor(scaled), v = scaled - lower === .5 ? lower + lower % 2 : Math.round(scaled);
    pixels[at] = pixels[at + 1] = pixels[at + 2] = v; pixels[at + 3] = x === y && x < 2 ? 0 : 255;
  }
  return Buffer.concat([Buffer.from('89504e470d0a1a0a', 'hex'), chunk('IHDR', header), chunk('IDAT', deflateSync(pixels)), chunk('IEND', Buffer.alloc(0))]);
}
export async function epochsFixture(req, res, scenario = 'failed', coordinates = {}) {
  const send = (data, status = 200) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(data)); };
  if (req.method === 'POST' && req.url === '/api/epochs/search') {
    let body = ''; for await (const part of req) body += part;
    const query = JSON.parse(body), filtered = products.filter(p => !query.detectors || query.detectors.includes(p.detector));
    send({ search_id: searchId, query, complete: true, products: filtered, epochs: [], collections: [{ name: 'SYNTHETIC_UI_FIXTURE', status: 'ok' }], pagination: { next_cursor: null }, expires_at: new Date(Date.now() + 3600000).toISOString() }); return true;
  }
  if (req.method === 'POST' && req.url === '/api/epoch-frames') {
    let body = ''; for await (const part of req) body += part;
    const input = JSON.parse(body);
    if (scenario === 'expired') { send({ error: { code: 'search_expired', message: 'Synthetic expired snapshot' } }, 410); return true; }
    if (input.search_id !== searchId || !Array.isArray(input.product_ids) || input.product_ids.length < 2 || input.product_ids.length > 3 || input.product_ids.some(id => !products.some(p => p.product_id === id))) {
      send({ error: { code: 'invalid_input', message: 'Invalid fixture request' } }, 422); return true;
    }
    const frames = input.product_ids.map((id, index) => {
      const p = products.find(p => p.product_id === id), failed = scenario === 'all-failed' || scenario === 'failed' && index === 1;
      return { ...p, index, status: failed ? 'failed' : scenario === 'comparable' ? 'ready' : 'alignment_unqualified', alignment: { status: scenario === 'comparable' ? 'pass' : 'unverified' }, observation_utc: utc(p.t_min), time_source: 'sia_t_min', target_wavelength_um: failed ? null : .86, target_bandwidth_um: failed ? null : .021, normalization: failed || scenario === 'missing-normalization' ? null : normalization(index, scenario), image_url: failed ? null : `/api/epoch-frames/${sequenceId}/${index}.png`, error: failed ? { code: 'synthetic_failure', message: 'Intentional UI test failure; original exposure retained' } : null };
    });
    send({ search_id: searchId, sequence_id: sequenceId, ...coordinates, mode: scenario === 'comparable' ? 'comparable_visualization' : 'observation_browse', photometric_series: false, frames, normalization: { policy: 'SYNTHETIC_UI_FIXTURE_ONLY', bunit: 'MJy/sr', lo: scenario === 'comparable' ? 0 : null, hi: scenario === 'comparable' ? 12 : null }, expires_at: new Date(Date.now() + 600000).toISOString() }); return true;
  }
  const match = req.url.match(new RegExp(`^/api/epoch-frames/${sequenceId}/([0-2])\\.png$`));
  if (req.method === 'GET' && match) {
    if (scenario === 'cache-miss') send({ error: { code: 'frame_not_found', message: 'Synthetic missing PNG cache' } }, 404);
    else { res.writeHead(200, { 'Content-Type': 'image/png' }); res.end(png(Number(match[1]), scenario)); }
    return true;
  }
  return false;
}
