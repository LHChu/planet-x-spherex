// One explicit publication boundary, shared by packaging and local serving.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

export const siteFiles = Object.freeze([
  'index.html', 'styles.css', 'config.js', 'brightness.js',
  'wcs-axes.js', 'color-bar.js', 'epochs.js', 'app.js',
]);
export const projectPath = '/planet-x-spherex/';

export function createStaticServer(root) {
  return http.createServer(async (req, res) => {
    try {
      const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
      if (pathname === projectPath.slice(0, -1)) {
        res.writeHead(301, { Location: projectPath }).end(); return;
      }
      // Preserve the previously documented local alias.
      const relative = pathname.replace(/^\/(?:planet-x-spherex|planet-x)\//, '/').replace(/^\//, '') || 'index.html';
      if (!siteFiles.includes(relative)) { res.writeHead(404).end(); return; }
      const content = await readFile(path.join(root, relative));
      const type = relative.endsWith('.html') ? 'text/html; charset=utf-8'
        : relative.endsWith('.css') ? 'text/css' : 'text/javascript';
      res.writeHead(200, { 'Content-Type': type }); res.end(content);
    } catch { res.writeHead(404).end(); }
  });
}
