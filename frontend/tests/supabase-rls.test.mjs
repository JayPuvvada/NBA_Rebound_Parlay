import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';

test('PostgreSQL policies isolate users, block unapproved/anonymous access, and protect snapshots', async () => {
  const db = new PGlite();
  const alice = '00000000-0000-4000-8000-000000000001';
  const bob = '00000000-0000-4000-8000-000000000002';
  const outsider = '00000000-0000-4000-8000-000000000003';
  try {
    // Supabase supplies these roles/schema/function. Emulate only that boundary;
    // execute the actual migration unchanged with PostgreSQL RLS enabled.
    await db.exec(`create role anon; create role authenticated;
      create schema auth;
      create table auth.users(id uuid primary key);
      create function auth.uid() returns uuid language sql stable as
      $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
      grant usage on schema auth, public to anon, authenticated;
      grant execute on function auth.uid() to anon, authenticated;
      insert into auth.users values ('${alice}'), ('${bob}'), ('${outsider}');`);
    await db.exec(await readFile(new URL('../../supabase/migrations/202609070001_saved_picks.sql', import.meta.url), 'utf8'));
    await db.query('insert into public.app_pick_members values ($1),($2)', [alice, bob]);
    const asUser = async (id, role = 'authenticated') => {
      await db.exec('reset role');
      await db.query("select set_config('request.jwt.claim.sub', $1, false)", [id]);
      await db.exec(`set role ${role}`);
    };
    const insert = (owner, id = 'same-quote') => db.query(`insert into public.app_saved_picks
      (user_id,id,player,opponent,date,projection,direction,line,odds,bookmaker,demo)
      values ($1,$2,'Jokic','LAL','2026-10-20',13.3,'OVER',12.5,-110,'Sample sportsbook',true)`, [owner,id]);
    await asUser(alice);
    await insert(alice);
    await assert.rejects(insert(bob, 'forged-owner'), /row-level security/);
    await assert.rejects(db.query('insert into public.app_pick_members values ($1)', [outsider]), /permission denied/);
    await assert.rejects(db.query("update public.app_saved_picks set odds=-115"), /permission denied/);
    await assert.rejects(db.query('update public.app_saved_picks set user_id=$1', [bob]), /permission denied/);
    await db.exec("update public.app_saved_picks set result='Win'");
    await assert.rejects(insert(alice), /duplicate key/);
    assert.equal((await db.query('select result from public.app_saved_picks')).rows[0].result, 'Win');
    await asUser(bob);
    assert.equal((await db.query('select * from public.app_saved_picks')).rows.length, 0);
    await db.query('delete from public.app_saved_picks where user_id=$1', [alice]);
    await db.query("update public.app_saved_picks set result='Loss' where user_id=$1", [alice]);
    await insert(bob); // Same quote in a different account is allowed.
    assert.equal((await db.query('select * from public.app_saved_picks')).rows.length, 1);
    await asUser(alice);
    assert.equal((await db.query('select result from public.app_saved_picks')).rows[0].result, 'Win');
    await asUser(outsider);
    assert.equal((await db.query('select * from public.app_saved_picks')).rows.length, 0);
    await assert.rejects(insert(outsider), /row-level security/);
    await asUser('', 'anon');
    await assert.rejects(db.query('select * from public.app_saved_picks'), /permission denied/);
    await asUser(alice);
    await db.exec('delete from public.app_saved_picks');
    assert.equal((await db.query('select * from public.app_saved_picks')).rows.length, 0);
    await asUser(bob);
    assert.equal((await db.query('select * from public.app_saved_picks')).rows.length, 1);
  } finally { await db.close(); }
});

test('public signup enrolls only confirmed non-anonymous users, preserves revocation and keeps picks private', async () => {
  const db = new PGlite();
  const alice = '00000000-0000-4000-8000-000000000001';
  const bob = '00000000-0000-4000-8000-000000000002';
  const anon = '00000000-0000-4000-8000-000000000003';
  try {
    await db.exec(`create role anon; create role authenticated; create schema auth;
      create table auth.users(id uuid primary key, email_confirmed_at timestamptz, is_anonymous boolean default false);
      create function auth.uid() returns uuid language sql stable as
      $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
      grant usage on schema auth, public to anon, authenticated;
      grant execute on function auth.uid() to anon, authenticated;`);
    for (const file of ['202609070001_saved_picks.sql','202609080001_public_signup.sql']) {
      await db.exec(await readFile(new URL('../../supabase/migrations/' + file, import.meta.url), 'utf8'));
    }
    await db.query('insert into auth.users(id) values ($1)',[alice]);
    assert.equal((await db.query('select * from public.app_pick_members')).rows.length,0);
    await db.query('update auth.users set email_confirmed_at=now() where id=$1',[alice]);
    await db.query('insert into auth.users values ($1,now(),false),($2,now(),true)',[bob,anon]);
    assert.equal((await db.query('select * from public.app_pick_members')).rows.length,2);
    const asUser = async id => {
      await db.exec('reset role');
      await db.query("select set_config('request.jwt.claim.sub',$1,false)",[id]);
      await db.exec('set role authenticated');
    };
    const insert = owner => db.query(`insert into public.app_saved_picks
      (user_id,id,player,opponent,date,projection,direction,line,odds,bookmaker,demo)
      values ($1,'quote','Jokic','LAL','2026-10-20',13.3,'OVER',12.5,-110,'Sample',true)`,[owner]);
    await asUser(alice); await insert(alice);
    await assert.rejects(insert(bob),/row-level security/);
    await assert.rejects(db.exec('select public.enroll_confirmed_pick_user()'),/permission denied/);
    await asUser(bob);
    assert.equal((await db.query('select * from public.app_saved_picks')).rows.length,0);
    await insert(bob);
    await db.exec("update public.app_saved_picks set result='Win'");
    await asUser(alice);
    assert.equal((await db.query('select result from public.app_saved_picks')).rows[0].result,'Pending');
    await asUser(anon); await assert.rejects(insert(anon),/row-level security/);
    await db.exec('reset role');
    await db.query('delete from public.app_pick_members where user_id=$1',[alice]);
    await db.query('update auth.users set email_confirmed_at=now() where id=$1',[alice]);
    assert.equal((await db.query('select * from public.app_pick_members where user_id=$1',[alice])).rows.length,0);
    await asUser(alice);
    assert.equal((await db.query('select * from public.app_saved_picks')).rows.length,0);
  } finally {await db.close();}
});
