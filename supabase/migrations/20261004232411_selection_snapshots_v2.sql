-- Add general quote snapshots without changing legacy IDs, results or membership.
begin;
alter table public.app_saved_picks
  add column version integer not null default 1,
  add column kind text,
  add column fingerprint text,
  add column sport text,
  add column event_id text,
  add column home text,
  add column away text,
  add column market text,
  add column selection text,
  add column team text,
  add column quote_updated_at timestamptz,
  add column quote_fetched_at timestamptz,
  add column source text,
  add column model_version text,
  add column profile text,
  add column assumptions jsonb,
  add column analysis jsonb,
  add column model_generated_at timestamptz,
  add column notes text not null default '';

alter table public.app_saved_picks
  alter column player drop not null,
  alter column projection drop not null,
  alter column direction drop not null,
  alter column line drop not null,
  drop constraint app_saved_picks_line_check,
  drop constraint app_saved_picks_projection_check,
  drop constraint app_saved_picks_result_check;

alter table public.app_saved_picks
  add constraint app_saved_picks_version_check check (version in (1,2)),
  add constraint app_saved_picks_result_check check (result in ('Pending','Win','Loss','Push','Void')),
  add constraint app_saved_picks_notes_check check (length(notes) <= 5000),
  add constraint app_saved_picks_projection_check check (projection is null or projection between 0 and 10000),
  add constraint app_saved_picks_version_shape check (
    (version = 1 and player is not null and projection between 0 and 100
      and projection is not null and direction is not null and line between 0 and 100 and line is not null)
    or
    (version = 2 and
      id ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' and
      kind is not null and kind in ('manual_pick','model_pick','experimental_model_pick') and
      fingerprint is not null and length(fingerprint) between 1 and 100000 and
      sport is not null and length(trim(sport)) between 1 and 100 and
      home is not null and length(trim(home)) between 1 and 100 and
      away is not null and length(trim(away)) between 1 and 100 and
      market is not null and market in ('h2h','spreads','totals','player_rebounds') and
      selection is not null and length(trim(selection)) between 1 and 200 and
      (case when market = 'h2h' then line is null
        when market = 'spreads' then line is not null and line between -10000 and 10000
        else line is not null and line between 0 and 10000 end) and
      (market <> 'player_rebounds' or (player is not null and direction is not null)) and
      (case when market in ('h2h','spreads') then selection in (home,away) and direction is null
        else selection in ('OVER','UNDER') and direction is not null and direction = selection end) and
      (case when kind = 'manual_pick' then projection is null
        else market = 'player_rebounds' and projection is not null
          and model_version is not null and length(trim(model_version)) between 1 and 200
          and profile is not null and length(trim(profile)) between 1 and 200 end)
    )
  );

-- The index stays compact even for detailed scenario assumptions. It is per owner.
create unique index app_saved_picks_user_fingerprint
  on public.app_saved_picks (user_id, md5(fingerprint)) where version = 2;

-- Existing RLS retains BOTH ownership and approved membership predicates.
-- No client may change quote/model metadata or supply savedAt/result/notes on insert.
revoke all on public.app_saved_picks from public, anon, authenticated;
-- Column grants survive table-level REVOKE, so explicitly reset prior column grants.
revoke insert (user_id,id,player,opponent,date,projection,direction,line,odds,bookmaker,demo)
  on public.app_saved_picks from authenticated;
revoke update (result) on public.app_saved_picks from authenticated;
grant select, delete on public.app_saved_picks to authenticated;
grant insert (user_id,id,player,opponent,date,projection,direction,line,odds,bookmaker,demo,
  version,kind,fingerprint,sport,event_id,home,away,market,selection,team,
  quote_updated_at,quote_fetched_at,source,model_version,profile,assumptions,analysis,model_generated_at)
  on public.app_saved_picks to authenticated;
grant update (result,notes) on public.app_saved_picks to authenticated;
commit;
