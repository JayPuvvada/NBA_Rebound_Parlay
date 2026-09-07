import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

let server, lib, PersonalContext, MyPicks, SavePickControl;
before(async () => {
  server = await createServer({ server: { middlewareMode: true, watch: null, ws: false }, appType: 'custom' });
  lib = await server.ssrLoadModule('/src/lib/personal-picks.ts');
  ({ PersonalContext } = await server.ssrLoadModule('/src/lib/personal-context.ts'));
  ({ MyPicks } = await server.ssrLoadModule('/src/components/ui/MyPicks.tsx'));
  ({ SavePickControl } = await server.ssrLoadModule('/src/components/ui/SavePickControl.tsx'));
});
after(async () => { await server?.close(); });
const data = { player: 'Nikola Jokic', opponent: 'LAL', date: '2026-10-20', projection: 13.3, prediction_eligible: true };
const metrics = { direction: 'OVER', actionable: true, line: 12.5, american_odds: -110, tier: 'PLAY' };
const state = { signedIn: true, picks: [], error: '', login: () => true, logout() {}, save() {}, remove() {}, grade() {} };
function render(component, props, value = state) {
  return renderToStaticMarkup(createElement(PersonalContext.Provider, { value }, createElement(component, props)));
}

test('test profile requires an explicit flag and loopback hostname', () => {
  assert.equal(lib.demoEnabled('true', '127.0.0.1'), true);
  assert.equal(lib.demoEnabled('true', 'localhost'), true);
  assert.equal(lib.demoEnabled(undefined, 'localhost'), false);
  assert.equal(lib.demoEnabled('true', 'example.onrender.com'), false);
  assert.equal(lib.demoEnabled('true', 'localhost.example.com'), false);
});
test('only public test credentials work', () => {
  assert.equal(lib.demoCredentials('jay', 'demo123'), true);
  assert.equal(lib.demoCredentials('jay', 'wrong'), false);
  assert.equal(lib.demoCredentials('someone', 'demo123'), false);
});
test('saved snapshot preserves the quote and has stable duplicate identity', () => {
  const pick = lib.snapshotPick(data, metrics);
  assert.equal(pick.odds, -110);
  assert.equal(pick.result, 'Pending');
  assert.equal(pick.demo, true);
  assert.equal(pick.id, lib.snapshotPick({ ...data, generated_at: 'later' }, metrics).id);
  assert.notEqual(pick.id, lib.snapshotPick(data, { ...metrics, american_odds: -115 }).id);
  assert.equal(metrics.result, undefined);
});
test('NO BET, degraded, missing date and missing price cannot be saved', () => {
  for (const [d, m] of [[data, { ...metrics, actionable: false }], [{ ...data, prediction_eligible: false }, metrics], [{ ...data, date: undefined }, metrics], [data, { ...metrics, american_odds: null }]]) {
    assert.throws(() => lib.snapshotPick(d, m));
    assert.equal(render(SavePickControl, { data: d, metrics: m }), '');
  }
});
test('browser persistence roundtrips manual results and refuses signed-out writes', () => {
  const memory = new Map();
  const storage = { getItem: key => memory.get(key) ?? null, setItem: (key, value) => memory.set(key, value) };
  assert.deepEqual(lib.readPicks(storage), []);
  const pick = lib.snapshotPick(data, metrics);
  assert.throws(() => lib.writePicks(storage, [pick], false));
  lib.writePicks(storage, [{ ...pick, result: 'Win' }], true);
  assert.equal(lib.readPicks(storage)[0].result, 'Win');
  lib.writePicks(storage, [], true);
  assert.deepEqual(lib.readPicks(storage), []);
});
test('corrupt or unavailable storage fails explicitly, not as an empty ledger', () => {
  for (const raw of ['not json', '{}', '[{"id":"bad"}]']) assert.throws(() => lib.readPicks({ getItem: () => raw }));
  assert.throws(() => lib.writePicks({ setItem() { throw Error('quota'); } }, [], true));
});
test('saving is absent without demo context and asks signed-out users to sign in', () => {
  assert.equal(renderToStaticMarkup(createElement(SavePickControl, { data, metrics })), '');
  assert.match(render(SavePickControl, { data, metrics }, { ...state, signedIn: false }), /Sign in to the test profile/);
  const markup = render(SavePickControl, { data, metrics }, { ...state, picks: [lib.snapshotPick(data, metrics)] });
  assert.match(markup, /Saved to My Picks/);
  assert.match(markup, /disabled/);
});
test('My Picks hides snapshots when signed out and labels demo/manual results', () => {
  const picks = [lib.snapshotPick(data, metrics)];
  const loggedOut = render(MyPicks, {}, { ...state, picks, signedIn: false });
  assert.doesNotMatch(loggedOut, /Nikola Jokic/);
  assert.match(loggedOut, /not real account security/);
  const loggedIn = render(MyPicks, {}, { ...state, picks });
  assert.match(loggedIn, /Nikola Jokic/);
  assert.match(loggedIn, /Manual test result/);
  assert.match(loggedIn, /Demo saved pick/);
});

test('real account UI contains no demo credentials and marks database storage', () => {
  const account = { ...state, mode: 'account', username: 'owner', enabled: true };
  const loggedOut = render(MyPicks, {}, { ...account, signedIn: false });
  assert.match(loggedOut, /no public registration/);
  assert.match(loggedOut, /database/);
  assert.doesNotMatch(loggedOut, /demo123|Test password|Test username/);
  const snapshot = lib.snapshotPick(data, metrics, false);
  assert.equal(snapshot.demo, false);
  const saved = render(MyPicks, {}, { ...account, picks: [snapshot] });
  assert.match(saved, /Saved model snapshot/);
  assert.doesNotMatch(saved, /Demo saved pick/);
  assert.equal(render(SavePickControl, { data, metrics }, { ...account, enabled: false }), '');
});
