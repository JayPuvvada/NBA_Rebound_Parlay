-- Public signup enrollment. Apply AFTER the saved-picks migration.
-- Existing RLS/column grants remain unchanged; users only access their own rows.
begin;
create or replace function public.enroll_confirmed_pick_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.email_confirmed_at is not null and not coalesce(new.is_anonymous, false) then
    if tg_op = 'INSERT' then
      insert into public.app_pick_members(user_id) values (new.id) on conflict do nothing;
    elsif old.email_confirmed_at is null then
      insert into public.app_pick_members(user_id) values (new.id) on conflict do nothing;
    end if;
  end if;
  return new;
end;
$$;
revoke all on function public.enroll_confirmed_pick_user() from public, anon, authenticated;
create trigger enroll_confirmed_pick_user
after insert or update of email_confirmed_at on auth.users
for each row execute function public.enroll_confirmed_pick_user();

-- Deliberately do not backfill: preserve existing approvals and revocations.
-- New email/password signups enroll only once their email is confirmed.
commit;
