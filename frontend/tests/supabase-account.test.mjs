import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createServer } from 'vite';
let server, SupabaseAccount, pickInsert, supabaseConfig;
before(async () => {
  server = await createServer({ server: { middlewareMode: true, watch: null, ws: false }, appType: 'custom' });
  ({ SupabaseAccount, pickInsert } = await server.ssrLoadModule('/src/lib/supabase-account.ts'));
  ({ supabaseConfig } = await server.ssrLoadModule('/src/lib/supabase.ts'));
});
after(async () => { await server?.close(); });
const tick = () => new Promise(resolve => setTimeout(resolve, 10));
const pick = { id: 'quote', player: 'Jokic', opponent: 'LAL', date: '2026-10-20', projection: 13.3,
  direction: 'OVER', line: 12.5, odds: -110, bookmaker: 'Sample', demo: true, result: 'Pending', savedAt: 'now' };
function fakeClient() {
  let user = null, callback, hold, failure = null;
  const rows = new Map();
  const calls = [];
  const emit = id => { user = id ? { id, email: id + '@example.com' } : null; callback?.('SIGNED_IN', user ? { user } : null); };
  const client = {
    auth: {
      onAuthStateChange(fn) { callback = fn; fn('INITIAL_SESSION', user ? { user } : null); return { data: { subscription: { unsubscribe() { callback = null; } } } }; },
      async getSession() { return { data: { session: user ? { user } : null }, error: null }; },
      async signInWithPassword({ email, password }) {
        if (password !== 'valid') return { data: {}, error: { message: 'Invalid credentials' } };
        emit(email.split('@')[0]); return { data: { user }, error: null };
      },
      async signUp({ email }) {
        if (email === 'failure@example.com') return { data: {}, error: { message: 'Email delivery failed' } };
        if (email === 'immediate@example.com') {
          emit('immediate'); return { data: { user, session: { user } }, error: null };
        }
        return { data: { user: { id: 'pending', email }, session: null }, error: null };
      },
      async signOut() { emit(null); return { error: null }; },
    },
    from(table) {
      let operation = 'select', payload, filters = {}, first = 0, last = 499;
      const builder = {
        select() { return builder; }, eq(k,v) { filters[k] = v; return builder; }, order() { return builder; },
        range(a,b) { first=a;last=b;return builder; }, maybeSingle() { return builder; },
        insert(value) { operation='insert';payload=value;return builder; },
        update(value) { operation='update';payload=value;return builder; }, delete() { operation='delete';return builder; },
        then(resolve, reject) {
          calls.push({ table, operation, payload, filters });
          const owner = filters.user_id ?? payload?.user_id;
          if (failure) return Promise.resolve({ error: { message: failure }, data: null }).then(resolve, reject);
          if (table === 'app_pick_members') return Promise.resolve({ error: null, data: owner === 'blocked' ? null : { user_id: owner } }).then(resolve,reject);
          let records = rows.get(owner) ?? [];
          if (operation === 'insert') {
            if (records.some(p=>p.id===payload.id)) return Promise.resolve({ error: { code:'23505', message:'duplicate' } }).then(resolve,reject);
            records = [...records, { ...payload, result:'Pending', savedAt:'database-time' }]; rows.set(owner,records);
          }
          if (operation === 'update') rows.set(owner, records.map(p=>p.id===filters.id?{...p,...payload}:p));
          if (operation === 'delete') rows.set(owner, records.filter(p=>p.id!==filters.id));
          const result = { error: null, data: records.slice(first,last+1) };
          if (hold && operation==='select') { const promise=hold;hold=null;return promise.then(()=>result).then(resolve,reject); }
          return Promise.resolve(result).then(resolve,reject);
        },
      }; return builder;
    },
  };
  return { client, rows, calls, emit, hold: promise=>{hold=promise;}, fail: message=>{failure=message;} };
}
test('missing configuration disables account; frontend rejects privileged keys', () => {
  assert.equal(new SupabaseAccount(null, 'setup needed').getSnapshot().enabled, false);
  assert.ok(supabaseConfig('', '').error);
  assert.ok(supabaseConfig('https://test.supabase.co', 'sb_secret_dont-use').error);
  const token = role => 'x.' + Buffer.from(JSON.stringify({role})).toString('base64url') + '.x';
  assert.ok(supabaseConfig('https://test.supabase.co', token('service_role')).error);
  assert.equal(supabaseConfig('https://test.supabase.co', token('anon')).error, '');
  assert.equal(supabaseConfig('https://test.supabase.co', 'sb_publishable_test').error, '');
});
test('insert pins owner, excludes client result/time, and keeps synthetic label', () => {
  const payload=pickInsert({...pick,user_id:'attacker',result:'Win'},'owner');
  assert.equal(payload.user_id,'owner'); assert.equal(payload.demo,true);
  assert.equal(payload.savedAt,undefined); assert.equal(payload.result,undefined);
});
test('login, save, deduplicate, grade, logout/relogin and delete use database state', async () => {
  const fake=fakeClient(), account=new SupabaseAccount(fake.client);const stop=account.start();
  try {
    assert.equal(await account.save(pick),false);
    assert.equal(await account.login('alice@example.com','wrong'),false);
    assert.equal(await account.login('alice@example.com','valid'),true);
    await account.save(pick);await account.grade(pick.id,'Win');await account.save(pick);
    assert.equal(account.getSnapshot().picks.length,1);
    assert.equal(account.getSnapshot().picks[0].result,'Win');
    await account.logout();assert.equal(account.getSnapshot().picks.length,0);
    await account.login('alice@example.com','valid');assert.equal(account.getSnapshot().picks[0].result,'Win');
    await account.remove(pick.id);assert.equal(account.getSnapshot().picks.length,0);
    assert.ok(fake.calls.filter(c=>c.table==='app_saved_picks'&&c.operation==='select').every(c=>c.filters.user_id==='alice'));
  } finally {stop();}
});
test('late response from a previous account cannot display its picks after account switch', async () => {
  const fake=fakeClient(), account=new SupabaseAccount(fake.client);const stop=account.start();
  try {
    await account.login('alice@example.com','valid');await account.save(pick);
    let release;fake.hold(new Promise(resolve=>{release=resolve;}));
    const pending=account.refresh();await tick();fake.emit('bob');await tick();release();await pending;
    assert.equal(account.getSnapshot().username,'bob@example.com');
    assert.deepEqual(account.getSnapshot().picks,[]);
  } finally {stop();}
});
test('unapproved member and database outages fail visibly without browser fallback', async () => {
  const fake=fakeClient(), account=new SupabaseAccount(fake.client);const stop=account.start();
  try {
    await account.login('blocked@example.com','valid');assert.match(account.getSnapshot().error,/not been granted access/);
    await account.login('alice@example.com','valid');await account.save(pick);
    fake.fail('Database unavailable');await account.refresh();
    assert.match(account.getSnapshot().error,/Database unavailable/);
    assert.deepEqual(account.getSnapshot().picks,[]);
  } finally {stop();}
});
test('reads every page instead of silently limiting a users saved picks', async () => {
  const fake=fakeClient();fake.rows.set('alice',Array.from({length:501},(_,i)=>({...pick,id:String(i)})));
  const account=new SupabaseAccount(fake.client);const stop=account.start();
  try {await account.login('alice@example.com','valid');assert.equal(account.getSnapshot().picks.length,501);} finally {stop();}
});

test('signup waits for email confirmation and never treats a pending user as signed in', async () => {
  const fake=fakeClient(), account=new SupabaseAccount(fake.client);const stop=account.start();
  try {
    assert.equal(await account.signup('new@example.com','short'),false);
    assert.match(account.getSnapshot().error,/at least 12/);
    assert.equal(await account.signup('new@example.com','a-long-test-password'),'confirmation');
    assert.equal(account.getSnapshot().signedIn,false);
    assert.deepEqual(account.getSnapshot().picks,[]);
    assert.equal(account.getSnapshot().busy,false);
    assert.equal(await account.save(pick),false);
    assert.equal(await account.signup('failure@example.com','a-long-test-password'),false);
    assert.match(account.getSnapshot().error,/Email delivery failed/);
  } finally {stop();}
});

test('auto-confirm signup loads the new account and saves without an email roundtrip', async () => {
  const fake=fakeClient(), account=new SupabaseAccount(fake.client);const stop=account.start();
  try {
    assert.equal(await account.signup('immediate@example.com','a-long-test-password'),'signed-in');
    assert.equal(account.getSnapshot().signedIn,true);
    assert.equal(account.getSnapshot().username,'immediate@example.com');
    assert.equal(await account.save(pick),true);
    assert.equal(account.getSnapshot().picks.length,1);
    await account.logout();
    await account.login('immediate@example.com','valid');
    assert.equal(account.getSnapshot().picks.length,1);
  } finally {stop();}
});
