// Separate preview; never overwrite hosted .env settings or expose admin keys.
import { execFileSync, spawn } from 'node:child_process';
import assert from 'node:assert/strict';
const cli = process.env.LOCAL_SUPABASE_CLI || 'supabase';
const config = JSON.parse(execFileSync(cli, ['status', '--output', 'json'], { cwd: '..', encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }));
assert.ok(['localhost', '127.0.0.1'].includes(new URL(config.API_URL).hostname));
const port = process.env.VITE_SYNTHETIC_ODDS === 'true' ? '5175' : '5174';
const child = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', port, '--strictPort'], {
  stdio: 'inherit', env: { ...process.env, NBA_BACKEND_URL: process.env.NBA_BACKEND_URL || 'http://127.0.0.1:5002', VITE_SUPABASE_URL: config.API_URL, VITE_SUPABASE_PUBLISHABLE_KEY: config.PUBLISHABLE_KEY || config.ANON_KEY, VITE_PERSONAL_DEMO: 'false' },
});
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('exit', code => { process.exitCode = code || 0; });
