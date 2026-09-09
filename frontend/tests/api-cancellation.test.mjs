import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createServer } from 'vite';

let server, fetchJson, unwrapCheatSheet;
const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
before(async () => {
  server = await createServer({ server: { middlewareMode: true, watch: null, ws: false }, appType: 'custom' });
  ({ fetchJson, unwrapCheatSheet } = await server.ssrLoadModule('/src/lib/api.ts'));
  globalThis.window = { setTimeout, clearTimeout };
});
after(async () => {
  globalThis.fetch = originalFetch;
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
  await server?.close();
});

test('late successful body after cancellation is rejected', async () => {
  const controller = new AbortController();
  globalThis.fetch = async () => ({ ok: true, status: 200, text: async () => {
    controller.abort();
    return '{"projection":12}';
  } });
  await assert.rejects(fetchJson('/predict', { signal: controller.signal }), error => error.kind === 'aborted');
});

test('valid non-cancelled response still returns parsed data', async () => {
  globalThis.fetch = async () => ({ ok: true, status: 200, text: async () => '{"projection":12}' });
  assert.deepEqual(await fetchJson('/predict'), { projection: 12 });
});

test('already cancelled requests do not start fetch', async () => {
  const controller = new AbortController();
  controller.abort();
  let calls = 0;
  globalThis.fetch = async () => { calls++; throw new Error('must not run'); };
  await assert.rejects(fetchJson('/predict', { signal: controller.signal }), error => error.kind === 'aborted');
  assert.equal(calls, 0);
});

test('structured server errors use a readable fallback', async () => {
  globalThis.fetch = async () => ({ ok: false, status: 503, statusText: 'Unavailable',
    text: async () => JSON.stringify({ error: { internal: 'details' } }),
  });
  await assert.rejects(fetchJson('/predict'), error => error.kind === 'http' && error.message === 'Server returned 503 Unavailable.');
});

test('quote timestamp never substitutes a newer download timestamp', () => {
  const response = { projections: [{ player: 'A', projection: 7 }], odds: {
    updated_at: '2026-01-01T12:00:00Z', fetched_at: '2026-01-01T13:00:00Z',
  } };
  assert.equal(unwrapCheatSheet(response).rows[0].odds_updated_at, response.odds.updated_at);
  delete response.odds.updated_at;
  assert.equal(unwrapCheatSheet(response).rows[0].odds_updated_at, undefined);
});

test('malformed slate rows produce recoverable API errors instead of render crashes', () => {
  for (const payload of [null, {}, { projections: [null] }, [null],
    { projections: [{ player: 'A', projection: '7' }] },
    { projections: [{ player: '', projection: 7 }] },
    { projections: [{ player: 'A', projection: -1 }] }]) {
    assert.throws(() => unwrapCheatSheet(payload), error => error.kind === 'invalid-response');
  }
  assert.deepEqual(unwrapCheatSheet({ projections: [] }).rows, []);
});
