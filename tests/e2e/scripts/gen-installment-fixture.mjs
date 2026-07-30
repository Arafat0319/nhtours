import { execFileSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const e2eRoot = path.resolve(__dirname, '..');
const flaskRoot = path.resolve(e2eRoot, '../../flask-app');
const outDir = path.join(e2eRoot, '.cache');
const outFile = path.join(outDir, 'installment-fixture.json');
const slug = process.env.E2E_TRIP_SLUG || 'qa-payment-trip-2026';

fs.mkdirSync(outDir, { recursive: true });

const pyCandidates = [
  process.env.E2E_PYTHON,
  'python',
  'py',
].filter(Boolean);

let lastErr;
for (const bin of pyCandidates) {
  try {
    const args =
      bin === 'py' || String(bin).toLowerCase().endsWith('py.exe')
        ? ['-3', 'scripts/e2e_installment_fixture.py', slug]
        : ['scripts/e2e_installment_fixture.py', slug];
    const out = execFileSync(bin, args, {
      cwd: flaskRoot,
      env: { ...process.env, PYTHONPATH: flaskRoot },
      encoding: 'utf8',
      timeout: 60_000,
    });
    const line = out
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter((l) => l.startsWith('{'))
      .pop();
    if (!line) continue;
    const json = JSON.parse(line);
    if (json.error) {
      lastErr = json.error;
      continue;
    }
    fs.writeFileSync(outFile, JSON.stringify(json, null, 2), 'utf8');
    console.log('Wrote', outFile);
    process.exit(0);
  } catch (e) {
    lastErr = e;
  }
}

console.warn('Could not generate installment fixture:', lastErr);
// Non-fatal: installment token tests will skip
process.exit(0);
