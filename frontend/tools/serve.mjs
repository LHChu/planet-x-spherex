// Dependency-free local static server. Optional fixture API is TEST DATA ONLY.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { epochsFixture } from './epochs-fixture.mjs';
import { createStaticServer, projectPath } from './static-site.mjs';
const root = fileURLToPath(new URL('../', import.meta.url));
const repo = path.resolve(root, '..');
const fixture = process.argv.includes('--fixture');
const wcsFixture = process.argv.includes('--wcs-fixture');
const multiFixture = process.argv.includes('--epochs-fixture') || wcsFixture;
const python = process.argv.find(arg => arg.startsWith('--python='))?.slice(9) || path.join(repo, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const wcsData = wcsFixture ? JSON.parse(execFileSync(python, [path.join(root, 'tools/wcs_fixture.py')], { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024, windowsHide: true })) : null;
const scenario = process.argv.find(arg => arg.startsWith('--scenario='))?.split('=')[1] || 'failed';
const port = Number(process.argv.find(arg => arg.startsWith('--port='))?.split('=')[1] || 5500);
const fixturePort = Number(process.argv.find(arg => arg.startsWith('--fixture-port='))?.split('=')[1] || 8001);
const staticServer = createStaticServer(root);
staticServer.listen(port, '127.0.0.1', () => console.log(`Frontend: http://127.0.0.1:${port}${projectPath}`));
let api;
if (fixture || multiFixture) {
  api = http.createServer(async (req, res) => {
    res.setHeader('Access-Control-Allow-Origin', `http://127.0.0.1:${port}`);
    res.setHeader('Access-Control-Allow-Methods', 'POST, GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    if (req.method === 'OPTIONS') { res.writeHead(204).end(); return; }
    try {
      if (multiFixture && await epochsFixture(req, res, scenario, wcsData?.epochs)) return;
      if (req.url === '/api/preview' && req.method === 'POST') {
        let body = ''; for await (const chunk of req) body += chunk;
        const query = JSON.parse(body);
        const metadata = wcsData?.preview.metadata || JSON.parse(await readFile(path.join(repo, 'research/outputs/metadata.json'), 'utf8'));
        if (!wcsData) metadata.query = query;
        res.setHeader('Content-Type', 'application/json');
        res.end(JSON.stringify({ key: 'a'.repeat(32), image_url: `/api/images/${'a'.repeat(32)}.png`, inverted_image_url: `/api/images/${'a'.repeat(32)}-inverse.png`, expires_in_seconds: 600, metadata }));
      } else if (/^\/api\/images\/a{32}(-inverse)?\.png$/.test(req.url)) {
        res.setHeader('Content-Type', 'image/png');
        const image = req.url.includes('-inverse') ? 'white' : 'black';
        res.end(wcsData ? Buffer.from(wcsData.preview[image], 'base64') : await readFile(path.join(repo, 'research/outputs', `${image}-background.png`)));
      } else res.writeHead(404).end();
    } catch { res.writeHead(500).end(); }
  });
  api.listen(fixturePort, '127.0.0.1', () => console.log(`TEST FIXTURE ONLY: http://127.0.0.1:${fixturePort} (${multiFixture ? `synthetic epochs, scenario=${scenario}` : 'recorded Phase 1 data'}; NOT live NASA)`));
}
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { staticServer.close(); api?.close(); });
