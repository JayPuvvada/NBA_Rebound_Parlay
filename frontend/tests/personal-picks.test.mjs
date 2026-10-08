import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

let server, lib, PersonalContext, MyPicks, SavePickControl;
before(async () => {
  server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null, ws: false }, appType: 'custom' });
  lib = await server.ssrLoadModule('/src/lib/personal-picks.ts');
  ({ PersonalContext } = await server.ssrLoadModule('/src/lib/personal-context.ts'));
  ({ MyPicks } = await server.ssrLoadModule('/src/components/ui/MyPicks.tsx'));
  ({ SavePickControl } = await server.ssrLoadModule('/src/components/ui/SavePickControl.tsx'));
});
after(async () => { await server?.close(); });
const data = { player: 'Nikola Jokic', opponent: 'LAL', date: '2026-10-20', projection: 13.3, prediction_eligible: true };
const metrics = { direction: 'OVER', actionable: true, line: 12.5, american_odds: -110, tier: 'PLAY' };
const state = { signedIn: true, picks: [], error: '', login: () => true, logout() {}, save() {}, remove() {}, grade() {} };
test('synthetic quote provenance always forces a sample snapshot', () => {
  const quote={market:'player_rebounds',player:'Jarrett Allen',team:'CLE',selection:'OVER',line:8.5,odds:-110,book:'fanduel',source:'synthetic-local-test'};
  const context={date:'2026-10-08',home:'CLE',away:'BOS',sport:'basketball_nba_preseason',demo:false};
  assert.equal(lib.buildSelectionSnapshot(quote,context).demo,true);
  assert.equal(lib.buildSelectionSnapshot({...quote,source:'the-odds-api'},context).demo,false);
});
test('note drafts follow saved changes without discarding unsaved edits', () => {
  const clean = {base:'old',value:'old',conflict:false};
  assert.deepEqual(lib.reconcileNoteDraft(clean,'remote'),{base:'remote',value:'remote',conflict:false});
  const editing = {base:'old',value:'draft',conflict:false};
  const acknowledged = lib.reconcileNoteDraft(editing,'draft');
  assert.deepEqual(acknowledged,{base:'draft',value:'draft',conflict:false});
  assert.deepEqual(lib.reconcileNoteDraft(acknowledged,'new remote'),{base:'new remote',value:'new remote',conflict:false});
  assert.deepEqual(lib.reconcileNoteDraft(editing,'remote'),{base:'remote',value:'draft',conflict:true});
  assert.equal(lib.reconcileNoteDraft(editing,'old'),editing);
});
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

test('saved-pick validation accepts real snapshots but demo storage remains demo-only', () => {
  const pick = lib.snapshotPick(data, metrics);
  assert.equal(lib.isSavedPick({ ...pick, demo: false }), true);
  assert.throws(() => lib.readPicks({ getItem: () => JSON.stringify([{ ...pick, demo: false }]) }));
  for (const changes of [{ player: ' ' }, { projection: -1 }, { line: -1 },
    { odds: 0 }, { result: 'Unknown' }, { demo: 'true' }]) {
    assert.equal(lib.isSavedPick({ ...pick, ...changes }), false);
  }
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
  assert.match(loggedOut, /Public signup is not available yet/);
  assert.match(loggedOut, /stored in the connected account database/);
  assert.doesNotMatch(loggedOut, /demo123|Test password|Test username/);
  const snapshot = lib.snapshotPick(data, metrics, false);
  assert.equal(snapshot.demo, false);
  const saved = render(MyPicks, {}, { ...account, picks: [snapshot] });
  assert.match(saved, /Saved model snapshot/);
  assert.doesNotMatch(saved, /Demo saved pick/);
  assert.equal(render(SavePickControl, { data, metrics }, { ...account, enabled: false }), '');
});

test('signup entry point appears only when the account provider enables it', () => {
  const account = { ...state, mode: 'account', enabled: true, signedIn: false, signup: async () => 'confirmation' };
  assert.match(render(MyPicks, {}, account), /New here\? Create an account/);
  assert.doesNotMatch(render(MyPicks, {}, { ...account, signup: undefined }), /New here/);
  assert.doesNotMatch(render(MyPicks, {}, { ...account, mode: 'demo' }), /New here/);
});

test('empty picks copy distinguishes loading and failure from an empty account', () => {
  const account = { ...state, mode: 'account', enabled: true };
  const loading = render(MyPicks, {}, { ...account, busy: true });
  assert.match(loading, /Loading saved picks/);
  assert.doesNotMatch(loading, /No saved picks yet/);
  const failed = render(MyPicks, {}, { ...account, error: 'Database unavailable' });
  assert.match(failed, /does not mean your account is empty/);
  assert.doesNotMatch(failed, /No saved picks yet/);
  assert.match(render(MyPicks, {}, account), /No saved picks yet/);
});

const quote = {market:'h2h',selection:'Denver Nuggets',line:null,odds:-120,book:'FanDuel',fetched_at:'2026-10-04T12:00:00Z'};
const context = {date:'2026-10-05',home:'Denver Nuggets',away:'Los Angeles Lakers',sport:'basketball_nba',event_id:'game-1'};
test('general manual snapshots preserve null h2h line and signed spreads without inventing a model', () => {
  const p = lib.buildSelectionSnapshot(quote,context);
  assert.equal(p.version,2); assert.equal(p.kind,'manual_pick'); assert.equal(p.projection,null); assert.equal(p.player,null);
  assert.equal(p.line,null); assert.equal(p.direction,null); assert.equal(p.demo,false);
  assert.equal(lib.isSavedPick(p),true);
  const spread = lib.buildSelectionSnapshot({...quote,market:'spreads',line:-5.5},context);
  assert.equal(spread.line,-5.5);
  for(const bad of [{...quote,market:'totals',line:null},{...quote,odds:0},{...quote,market:'player_rebounds',line:8.5},{...quote,book:''}]) assert.throws(()=>lib.buildSelectionSnapshot(bad,context));
});
test('duplicate fingerprint ignores clocks but changes for material assumptions and quote changes', () => {
  const quote={market:'player_rebounds',selection:'OVER',player:'Jokic',line:12.5,odds:-110,book:'FanDuel'};
  const assessment={projection:13.3,model_version:'v7',profile:'preseason',assumptions:{minutes:25,pace:101},generated_at:'2026-10-04T12:00:00Z'};
  const a=lib.buildSelectionSnapshot(quote,context,assessment);
  const b=lib.buildSelectionSnapshot({...quote,fetched_at:'2026-10-04T13:00:00Z',updated_at:'2026-10-04T13:00:00Z'},context,{...assessment,generated_at:'2026-10-04T13:00:00Z',assumptions:{pace:101,minutes:25}});
  assert.notEqual(a.id,b.id); assert.equal(a.fingerprint,b.fingerprint);
  assert.equal(a.kind,'experimental_model_pick');
  assert.notEqual(a.fingerprint,lib.buildSelectionSnapshot(quote,context,{...assessment,assumptions:{minutes:30,pace:101}}).fingerprint);
  assert.notEqual(a.fingerprint,lib.buildSelectionSnapshot({...quote,odds:-125},context,assessment).fingerprint);
  assessment.assumptions.minutes=5; assert.equal(a.assumptions.minutes,25);
});
test('mixed-version decoder preserves legacy IDs and results while skipping unknown rows', () => {
  const old={...lib.snapshotPick(data,metrics),result:'Win'};
  const current=lib.buildSelectionSnapshot(quote,context);
  const decoded=lib.decodePicks([old,current,{...current,version:99},null]);
  assert.equal(decoded.skipped,2); assert.equal(decoded.picks[0].id,old.id); assert.equal(decoded.picks[0].result,'Win');
});
test('CSV neutralizes formulas and renders a general quote journal without fabricated projection', () => {
  const p={...lib.buildSelectionSnapshot(quote,context),notes:'=HYPERLINK("bad")',result:'Void'};
  const csv=lib.picksCsv([p]);
  assert.ok(csv.includes("'=HYPERLINK")); assert.ok(csv.includes('"\'\-120"')); assert.match(csv,/Void/);
  const markup=render(MyPicks,{}, {...state,mode:'account',picks:[p],notes(){}});
  assert.match(markup,/Saved manual pick/); assert.match(markup,/Export filtered CSV/); assert.match(markup,/Save notes/);
  assert.doesNotMatch(markup,/Projection: null|Projected rebounds/);
});
