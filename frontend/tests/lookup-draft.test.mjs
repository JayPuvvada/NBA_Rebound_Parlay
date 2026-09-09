import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createServer } from 'vite';

let server, readLookupDraft, writeLookupDraft;
before(async () => {
  server = await createServer({ server: { middlewareMode: true, watch: null, ws: false }, appType: 'custom' });
  ({ readLookupDraft, writeLookupDraft } = await server.ssrLoadModule('/src/lib/lookup-draft.ts'));
});
after(async () => { delete globalThis.sessionStorage; await server?.close(); });

test('lookup draft survives remount reads without storing results or passwords', () => {
  let value;
  globalThis.sessionStorage = { getItem: () => value, setItem: (_key, next) => { value = next; } };
  writeLookupDraft({ player: 'Nikola Jokic', line: '12.5', venue: 'home' });
  assert.deepEqual(readLookupDraft(), { player: 'Nikola Jokic', line: '12.5', venue: 'home' });
  value = JSON.stringify({ player: 'A', password: 'do not restore', result: {}, line: 12, opponent: 'x'.repeat(201) });
  assert.deepEqual(readLookupDraft(), { player: 'A' });
});

test('invalid JSON and disabled session storage never break the form', () => {
  globalThis.sessionStorage = { getItem: () => '{' };
  assert.deepEqual(readLookupDraft(), {});
  globalThis.sessionStorage = {
    getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); },
  };
  assert.deepEqual(readLookupDraft(), {});
  assert.doesNotThrow(() => writeLookupDraft({ player: 'A' }));
});
