// Expand test paths without depending on shell glob behavior (Windows/Linux).
import { readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const directory = new URL('../tests/', import.meta.url);
const files = readdirSync(directory).filter(name => name.endsWith('.test.mjs')).sort();
const result = spawnSync(process.execPath, ['--test', ...files.map(name => fileURLToPath(new URL(name, directory)))], { stdio: 'inherit', windowsHide: true });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
