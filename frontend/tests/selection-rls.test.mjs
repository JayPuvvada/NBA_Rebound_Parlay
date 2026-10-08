import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { PGlite } from '@electric-sql/pglite';

test('v2 migration preserves legacy results, isolates users, and enforces immutable quote snapshots', async () => {
  const db=new PGlite();
  const alice='00000000-0000-4000-8000-000000000001', bob='00000000-0000-4000-8000-000000000002', outsider='00000000-0000-4000-8000-000000000003';
  try {
    await db.exec(`create role anon; create role authenticated; create schema auth;
      create table auth.users(id uuid primary key,email_confirmed_at timestamptz,is_anonymous boolean default false);
      create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
      grant usage on schema auth,public to anon,authenticated;
      grant execute on function auth.uid() to anon,authenticated;
      insert into auth.users(id) values ('${alice}'),('${bob}'),('${outsider}');`);
    for(const file of ['202609070001_saved_picks.sql','202609080001_public_signup.sql']) await db.exec(await readFile(new URL('../../supabase/migrations/'+file,import.meta.url),'utf8'));
    await db.query('insert into public.app_pick_members values ($1),($2)',[alice,bob]);
    await db.query(`insert into public.app_saved_picks(user_id,id,player,opponent,date,projection,direction,line,odds,bookmaker,demo,result)
      values ($1,'legacy-identity','Jokic','LAL','2026-10-05',13,'OVER',12.5,-110,'FanDuel',false,'Win')`,[alice]);
    await db.exec(await readFile(new URL('../../supabase/migrations/20261004232411_selection_snapshots_v2.sql',import.meta.url),'utf8'));
    const asUser=async(id,role='authenticated')=>{await db.exec('reset role');await db.query("select set_config('request.jwt.claim.sub',$1,false)",[id]);await db.exec(`set role ${role}`);};
    const insert=async(owner,id,market='h2h',line=null,extra={})=>{
      const p={user_id:owner,id,version:2,kind:'manual_pick',fingerprint:id,sport:'basketball_nba',event_id:'game',home:'Denver',away:'LA',market,selection:'Denver',player:null,opponent:'LA @ Denver',date:'2026-10-05',projection:null,direction:null,line,odds:-110,bookmaker:'FanDuel',demo:false,...extra};
      return db.query(`insert into public.app_saved_picks (${Object.keys(p).map(k=>`"${k}"`).join(',')}) values (${Object.keys(p).map((_,i)=>'$'+(i+1)).join(',')})`,Object.values(p));
    };
    const id='11111111-1111-4111-8111-111111111111',id2='22222222-2222-4222-8222-222222222222';
    await asUser(alice);
    const old=(await db.query("select id,result,version from public.app_saved_picks where id='legacy-identity'")).rows[0];
    assert.deepEqual(old,{id:'legacy-identity',result:'Win',version:1});
    await insert(alice,id);
    await insert(alice,id2,'spreads',-4.5);
    await insert(alice,'55555555-5555-4555-8555-555555555555','totals',225.5,{selection:'UNDER',direction:'UNDER'});
    await insert(alice,'66666666-6666-4666-8666-666666666666','player_rebounds',12.5,{kind:'model_pick',player:'Jokic',selection:'OVER',direction:'OVER',projection:13.3,model_version:'v7',profile:'regular_season',assumptions:{minutes:34}});
    await assert.rejects(insert(bob,id),/row-level security/);
    await assert.rejects(insert(alice,'33333333-3333-4333-8333-333333333333','h2h',null,{fingerprint:id}),/duplicate key/);
    for(const [field,value] of [['odds','-115'],['projection','13'],['kind',"'model_pick'"],['assumptions',"'{}'"],['fingerprint',"'changed'"],['version','1'],['"savedAt"','now()'],['user_id',`'${bob}'`]]) {
      await assert.rejects(db.exec(`update public.app_saved_picks set ${field}=${value}`),/permission denied/);
    }
    await assert.rejects(insert(alice,'33333333-3333-4333-8333-333333333333','h2h',null,{result:'Win'}),/permission denied/);
    await assert.rejects(insert(alice,'33333333-3333-4333-8333-333333333333','h2h',null,{savedAt:'2020-01-01'}),/permission denied/);
    for(const [market,line,extra] of [['h2h',3,{}],['totals',null,{}],['totals',-3,{}],['player_rebounds',8.5,{}],['h2h',null,{projection:3}],['h2h',null,{version:99}],['h2h',null,{kind:null}],['h2h',null,{sport:null}],['h2h',null,{selection:'Boston'}],['totals',225,{selection:'OVER',direction:null}],['player_rebounds',8.5,{player:'Jokic',selection:'OVER',direction:'OVER',kind:'model_pick',projection:10,model_version:null,profile:'regular_season'}]]) {
      await assert.rejects(insert(alice,'33333333-3333-4333-8333-333333333333',market,line,extra),/check constraint/);
    }
    await db.query("update public.app_saved_picks set result='Void',notes='Weather cancellation' where id=$1",[id]);
    await asUser(bob);
    assert.equal((await db.query('select * from public.app_saved_picks')).rows.length,0);
    await insert(bob,id); // Owner scopes both IDs and fingerprints.
    await db.query("update public.app_saved_picks set result='Loss' where user_id=$1",[alice]);
    await db.query('delete from public.app_saved_picks where user_id=$1',[alice]);
    await asUser(alice);
    assert.equal((await db.query('select result from public.app_saved_picks where id=$1',[id])).rows[0].result,'Void');
    await asUser(outsider);
    assert.equal((await db.query('select * from public.app_saved_picks')).rows.length,0);
    await assert.rejects(insert(outsider,id),/row-level security/);
    await asUser('','anon');
    await assert.rejects(db.exec('select * from public.app_saved_picks'),/permission denied/);
    await assert.rejects(insert(alice,id),/permission denied/);
    await db.exec('reset role'); await db.query('delete from public.app_pick_members where user_id=$1',[alice]);
    await asUser(alice);
    assert.equal((await db.query('select * from public.app_saved_picks')).rows.length,0);
    await assert.rejects(insert(alice,'44444444-4444-4444-8444-444444444444'),/row-level security/);
  } finally {await db.close();}
});
