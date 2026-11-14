// No recursive copy: tests, fixtures, local data and backend files cannot enter.
import { copyFile, mkdir, readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { siteFiles } from './static-site.mjs';

const root = new URL('../', import.meta.url);
const output = new URL('../dist/', import.meta.url);
await mkdir(output, { recursive: true });
for (const file of await readdir(output)) {
  if (!siteFiles.includes(file)) throw Error(`Unexpected artifact entry: ${file}. Use an empty dist directory.`);
}
for (const file of siteFiles) await copyFile(new URL(file, root), new URL(file, output));
console.log(`Pages artifact: ${fileURLToPath(output)} (${siteFiles.length} static files)`);
