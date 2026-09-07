-- Run once in your Supabase project's SQL Editor. No paid extensions required.
begin;
-- Explicit membership protects app data even if signup is accidentally enabled.
create table public.app_pick_members (
  user_id uuid primary key references auth.users(id) on delete cascade
);
alter table public.app_pick_members enable row level security;
revoke all on public.app_pick_members from public, anon, authenticated;
grant select on public.app_pick_members to authenticated;
create policy "Members can see only their own membership"
  on public.app_pick_members for select to authenticated
  using (user_id = (select auth.uid()));

create table public.app_saved_picks (
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  id text not null check (length(id) between 1 and 1000),
  player text not null check (length(trim(player)) between 1 and 100),
  opponent text not null check (length(trim(opponent)) between 1 and 100),
  date date not null,
  projection double precision not null check (projection between 0 and 100),
  direction text not null check (direction in ('OVER', 'UNDER')),
  line double precision not null check (line between 0 and 100),
  odds integer not null check (abs(odds::bigint) between 100 and 100000),
  bookmaker text not null check (length(trim(bookmaker)) between 1 and 100),
  "savedAt" timestamptz not null default now(),
  result text not null default 'Pending' check (result in ('Pending', 'Win', 'Loss', 'Push')),
  demo boolean not null,
  primary key (user_id, id)
);
create index app_saved_picks_user_time on public.app_saved_picks (user_id, "savedAt" desc);
alter table public.app_saved_picks enable row level security;
revoke all on public.app_saved_picks from public, anon, authenticated;
grant select, delete on public.app_saved_picks to authenticated;
-- RLS enforces ownership. Initial result/time are defaults; quotes are immutable.
grant insert (user_id, id, player, opponent, date, projection, direction, line, odds, bookmaker, demo)
  on public.app_saved_picks to authenticated;
grant update (result) on public.app_saved_picks to authenticated;
create policy "Approved users own their picks"
  on public.app_saved_picks for all to authenticated
  using (
    user_id = (select auth.uid()) and exists (
      select 1 from public.app_pick_members where user_id = (select auth.uid())
    )
  )
  with check (
    user_id = (select auth.uid()) and exists (
      select 1 from public.app_pick_members where user_id = (select auth.uid())
    )
  );
commit;

-- NEXT: turn OFF public signup and anonymous sign-ins in Authentication settings.
-- Add your email/password user in Authentication > Users (auto-confirm email).
-- Then run this separately, replacing the example with your actual email:
-- insert into public.app_pick_members(user_id)
-- select id from auth.users where lower(email) = lower('your-email@example.com')
-- on conflict do nothing;
