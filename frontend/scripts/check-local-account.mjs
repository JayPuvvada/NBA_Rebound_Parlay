// Real local Auth/REST acceptance. Never targets a hosted project or prints keys.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { randomUUID, randomBytes } from 'node:crypto';
import { createClient } from '@supabase/supabase-js';
import { createServer } from 'vite';
import WebSocket from 'ws';
import { chromium } from '@playwright/test';

const cli = process.env.LOCAL_SUPABASE_CLI || 'supabase';
const config = JSON.parse(execFileSync(cli, ['status', '--output', 'json'], { cwd: '..', encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }));
const url = config.API_URL;
assert.ok(url && ['localhost', '127.0.0.1'].includes(new URL(url).hostname), 'Only a local Supabase URL is allowed');
const options = { auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false }, realtime: { transport: WebSocket } };
const admin = createClient(url, config.SERVICE_ROLE_KEY, options);
const client = () => createClient(url, config.ANON_KEY, options);
const server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null, ws: false }, appType: 'custom' });
const { SupabaseAccount, pickInsert } = await server.ssrLoadModule('/src/lib/supabase-account.ts');
const { buildSelectionSnapshot } = await server.ssrLoadModule('/src/lib/personal-picks.ts');
const users = [], stores = [], clients = [];
let browser;
async function account() {
  const email = `local-check-${randomUUID()}@example.test`, password = randomBytes(24).toString('hex');
  const sdk = client(); clients.push(sdk);
  const created = await sdk.auth.signUp({ email, password });
  assert.ifError(created.error); users.push(created.data.user.id);
  assert.ok(created.data.session, 'Existing local auto-confirm signup should return a session');
  const store = new SupabaseAccount(sdk); stores.push(store.start());
  assert.equal(await store.login(email, password), true);
  return { email, password, id: created.data.user.id, sdk, store };
}
try {
  const alice = await account(), bob = await account();
  const snapshot = buildSelectionSnapshot({ market: 'h2h', selection: 'DEN', team: 'DEN', line: null, odds: -110, book: 'fanduel', source: 'manual' }, { date: '2026-10-05', home: 'DEN', away: 'UTA', sport: 'basketball_nba_preseason' });
  assert.equal(await alice.store.save(snapshot), true);
  assert.equal(alice.store.getSnapshot().picks.length, 1);
  assert.equal(await alice.store.save({ ...snapshot, id: randomUUID() }), true);
  assert.equal(alice.store.getSnapshot().picks.length, 1, 'duplicate prevented');
  await alice.store.logout();
  const freshSDK = client(); clients.push(freshSDK);
  const fresh = new SupabaseAccount(freshSDK); stores.push(fresh.start());
  assert.equal(await fresh.login(alice.email, alice.password), true);
  assert.equal(fresh.getSnapshot().picks[0].odds, -110, 'record survives new browser-equivalent client');
  assert.equal(await fresh.notes(snapshot.id, 'Local acceptance note'), true);
  assert.equal(await fresh.grade(snapshot.id, 'Void'), true);
  assert.equal(fresh.getSnapshot().picks[0].notes, 'Local acceptance note');
  assert.equal(fresh.getSnapshot().picks[0].result, 'Void');
  const foreign = await bob.sdk.from('app_saved_picks').select('id').eq('user_id', alice.id);
  assert.ifError(foreign.error); assert.deepEqual(foreign.data, []);
  assert.ok((await bob.sdk.from('app_saved_picks').insert(pickInsert({ ...snapshot, id: randomUUID() }, alice.id))).error, 'cross-user insert denied');
  assert.ok((await freshSDK.from('app_saved_picks').update({ odds: -115 }).eq('id', snapshot.id)).error, 'immutable price enforced');
  const anonymous = client(); clients.push(anonymous);
  assert.ok((await anonymous.from('app_saved_picks').select('id')).error, 'anonymous read denied');
  if (process.env.LOCAL_ACCOUNT_BROWSER_URL) {
    const preview = new URL(process.env.LOCAL_ACCOUNT_BROWSER_URL);
    const synthetic = process.env.LOCAL_ACCOUNT_SYNTHETIC === '1';
    assert.ok(['127.0.0.1', 'localhost'].includes(preview.hostname) && preview.port === (synthetic ? '5175' : '5174'), 'Use only the dedicated local-account preview');
    browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    page.on('request', request => {
      if (request.url().includes('/auth/v1/') || request.url().includes('/rest/v1/')) assert.ok(request.url().startsWith(url), 'Account requests must stay local');
    });
    const live = process.env.LOCAL_ACCOUNT_LIVE_MARKETS === '1';
    let savedSubject = 'Stephen Curry';
    if (synthetic) {
      page.setDefaultTimeout(85000);
      savedSubject = 'Jarrett Allen';
      // Narrow the real request for a bounded test; no response/history is mocked.
      await page.route('**/generate-picks', route => route.continue({postData:JSON.stringify({
        ...route.request().postDataJSON(), players:[savedSubject], minutes:{[savedSubject]:24}
      })}));
      await page.goto(`${preview.origin}/#edge?date=2026-10-08&home=CLE&away=BOS&book=fanduel`);
      await page.getByText(/Local test mode: synthetic odds/).waitFor();
      await page.getByRole('button',{name:/Generate rebound picks/}).click();
      const card = page.locator('.pick-card').filter({has:page.getByRole('heading',{name:savedSubject,exact:true})});
      await card.getByText('Sample analysis',{exact:true}).waitFor();
      await card.getByText('Advanced analysis',{exact:true}).click();
      await card.getByRole('img',{name:/Estimated rebounds/}).waitFor();
      await card.getByRole('button',{name:/Inspect player/}).click();
      await page.getByRole('heading',{name:'Prior regular season',exact:true}).waitFor();
      await page.getByRole('tab',{name:'Picks & Lines',exact:true}).click();
      await card.getByRole('button',{name:'Save sample analysis',exact:true}).click();
    } else if (!live) {
    await page.route('**/games?*', route => route.fulfill({ json: { date: '2026-10-05', games: [{ id: 'acceptance-fixture', date: '2026-10-05', home: 'LAC', away: 'GSW', status: 1, is_preseason: true }] } }));
    await page.route('**/markets?*', route => route.fulfill({ json: { status: 'available', date: '2026-10-05', game: { home: 'LAC', away: 'GSW' }, sport: 'basketball_nba_preseason', coverage: { fanduel: { player_rebounds: 'available' } }, quotes: [{ market: 'player_rebounds', player: 'Stephen Curry', team: 'GSW', selection: 'OVER', line: 4.5, odds: -110, book: 'fanduel', freshness: 'unknown', updated_at: null, source: 'acceptance-fixture', sport: 'basketball_nba_preseason' }] } }));
    await page.goto(`${preview.origin}/#edge?date=2026-10-05`);
    await page.getByRole('button', { name: 'Save Stephen Curry OVER 4.5 at FanDuel' }).click();
    } else {
      await page.goto(`${preview.origin}/#edge?date=2026-10-05&home=ATL&away=MEM&book=fanduel&market=h2h`);
      const save = page.getByRole('button', { name: /^Save .* at FanDuel$/ }).first();
      await save.waitFor({ timeout: 35000 });
      await save.click();
      savedSubject = 'ATL';
    }
    const login = async () => {
      await page.getByLabel('Email', { exact: true }).fill(alice.email);
      await page.getByLabel('Password', { exact: true }).fill(alice.password);
      await page.locator('form').getByRole('button', { name: 'Sign in', exact: true }).click();
      await page.getByRole('button', { name: 'Sign out' }).waitFor();
    };
    await login();
    await page.getByRole('button', { name: 'Save reviewed selection' }).click();
    await page.getByLabel(`Notes for ${savedSubject}`, { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Sign out' }).click();
    await page.getByLabel('Email', { exact: true }).waitFor();
    await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
    await page.reload(); await login();
    await page.getByLabel(`Notes for ${savedSubject}`, { exact: true }).fill('Real local browser persistence check');
    await page.getByLabel(`Notes for ${savedSubject}`, { exact: true }).locator('..').locator('..').getByRole('button', { name: 'Save notes', exact: true }).click();
    await page.getByLabel(`Result for ${savedSubject}`, { exact: true }).selectOption('Void');
    await page.reload();
    await page.getByLabel(`Result for ${savedSubject}`, { exact: true }).waitFor();
    assert.equal(await page.getByLabel(`Result for ${savedSubject}`, { exact: true }).inputValue(), 'Void');
    assert.equal(await page.getByLabel(`Notes for ${savedSubject}`, { exact: true }).inputValue(), 'Real local browser persistence check');
    console.log(`PASS: real local mobile browser sign-in/save, browser-data clearing/relogin, notes/Void persistence (${synthetic ? 'real schedule/history and synthetic odds' : live ? 'actual backend markets; cached quotes may be stale' : 'market fixture only'}; Auth/REST not mocked)`);
    await fresh.refresh();
    if (synthetic) {
      const sample = fresh.getSnapshot().picks.find(pick => pick.player === savedSubject);
      assert.ok(sample && sample.demo === true && sample.source === 'synthetic-local-test');
      assert.equal(sample.profile, 'preseason');
      assert.ok(sample.projection > 0 && sample.assumptions && sample.analysis);
      console.log('PASS: real history → synthetic generation → visual explanation → research → sample snapshot persistence');
    }
    for (const pick of fresh.getSnapshot().picks.filter(pick => pick.id !== snapshot.id)) assert.equal(await fresh.remove(pick.id), true);
  }
  assert.equal(await fresh.remove(snapshot.id), true);
  assert.equal(fresh.getSnapshot().picks.length, 0);
  console.log('PASS: real local Auth, save/relogin, duplicate prevention, notes/Void, ownership, immutable price, anonymous denial and deletion');
} finally {
  await browser?.close();
  stores.forEach(stop => stop());
  for (const sdk of clients) await sdk.auth.signOut({ scope: 'local' }).catch(() => {});
  for (const id of users) {
    const result = await admin.auth.admin.deleteUser(id);
    if (result.error) throw Error('Local test-user cleanup failed');
  }
  await server.close();
  console.log('Temporary local users and their test records removed; hosted accounts untouched');
}
