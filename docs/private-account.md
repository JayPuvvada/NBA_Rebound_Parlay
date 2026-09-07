# Supabase Free: local sample picks, real private accounts

## Current local setup status

This checkout is now connected to the existing project in the `nba-picks`
organization. The schema below is installed, exactly one existing confirmed user
is approved, public signup/anonymous sign-in are disabled, and the local site URL
is configured. The frontend connection settings are in git-ignored
`frontend/.env.local`. No Render deployment or billing-plan changes were made.

Open **http://127.0.0.1:4181/#picks** and use the email/password you created in
Supabase. The hosted Auth/session and database save/read/update/delete checks
passed; the temporary verification row was removed and its session signed out.
Your password was not changed. NBA results in this demo are still synthetic.

The instructions below are retained for a new project/checkout. **Do not rerun
the create-table migration on this already configured project.**

This is the current account setup. It replaces the earlier custom Flask/Neon
prototype. No Render deployment is needed to test it.

- **NBA data:** fixed synthetic fixtures in `npm run demo`.
- **Login and saving:** real Supabase Auth and database, once configured.
- **Access:** create only your user initially; each approved user has private rows.
- **Cost:** choose Supabase **Free**, with no paid upgrades or add-ons.
- **Not included:** placing bets, verified grading, public signup, live-data fixes.

## 1. Create your free project and user

1. Open [Supabase Dashboard](https://supabase.com/dashboard), create a **Free**
   organization/project (for example, `nba-picks`). Keep the database password
   private; the frontend does not need it.
2. In **Authentication → Sign In / Providers**, turn **Allow new users to sign up**
   OFF and **Allow anonymous sign-ins** OFF. Keep email/password authentication
   enabled. Hiding the signup form alone is not enough.
3. In **Authentication → Users → Add user / Create new user**, create your own
   email/password account and enable **Auto Confirm User**. Use a unique strong
   password. This is your app login, separate from the database password.
   No email invitations or custom email service are needed for this manual setup.
4. In Authentication URL Configuration, set the local Site URL to
   `http://127.0.0.1:4181`. The app uses direct password login, not magic links.
   There is no self-service email password-reset flow in this first version.

Reference: [Supabase Auth settings](https://supabase.com/docs/guides/auth/general-configuration).

## 2. Create private tables and approve yourself

Open **SQL Editor → New query**, paste the entire contents of
[supabase/migrations/202609070001_saved_picks.sql](../supabase/migrations/202609070001_saved_picks.sql),
and click **Run**. Run this migration once; it creates two new tables and policies.

Then run this separate query, replacing the example with the email you created:

```sql
insert into public.app_pick_members (user_id)
select id from auth.users
where lower(email) = lower('your-email@example.com')
on conflict do nothing;
```

Verify there is **one row** in `app_pick_members` in Table Editor.
If no row appears, the email does not match an existing Auth user.

Only an administrator can add members. Signed-in users cannot approve themselves.
Database row-level security restricts each approved user to their own saved picks.
This protects access even if someone accidentally enables signup later.
[Supabase RLS documentation](https://supabase.com/docs/guides/database/postgres/row-level-security).

## 3. Connect the local frontend

In the project's **Connect** dialog, copy the **Project URL** and
**publishable key** (`sb_publishable_...`; a legacy `anon` key also works).

Create `frontend/.env.local` using [frontend/.env.example](../frontend/.env.example):

```dotenv
VITE_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_YOUR_KEY
```

These two values are intended for browser use. Never put a secret key,
`service_role` key, database connection string, or password in a `VITE_` variable.
The app rejects privileged key types, but preventing secrets from entering a
frontend build is still your responsibility. `.env.local` is git-ignored.
[Supabase key types](https://supabase.com/docs/guides/api/api-keys).

Restart/rebuild after changing these values; Vite embeds them at build time.
Do not set `VITE_PERSONAL_DEMO=true` in this file—that selects the old fake login.

## 4. Run the local demo

From the project root:

```bash
cd frontend
npm install
npm run demo
```

Open **http://127.0.0.1:4181/#picks**.

1. Sign in with the email/password created in Supabase—not `jay / demo123`.
2. Open **Daily Edge**, expand the synthetic Nikola Jokic recommendation, and
   click **Save pick**. Or submit the prefilled Player Lookup example and save it.
3. Open **My Picks**. The record is labeled **Sample pick — synthetic data**.
4. Mark a manual result, refresh, then sign out/back in.
5. Clear the site's browser storage, reload, sign back in: the pick returns
   from Supabase. A different browser can load it with the same account.
6. Remove the pick with confirmation. Refresh to verify it stays removed.

The sample server binds only to 127.0.0.1 and makes no NBA/odds-provider calls.
It builds into ignored `frontend/dist-demo/`, leaving the regular build separate.
Internet is required for Supabase login/saving. With no project configuration,
the app displays setup instructions and does not pretend cloud saving succeeded.

The first local demo used browser storage. It is retained as
`npm run demo:offline`, also on port 4181 (stop the other demo first).
That command alone uses the public test credentials `jay / demo123`.
Its records are browser-only and are **not** imported into your Supabase account.

## 5. Add friends later, without public signup

Repeat the dashboard user-creation step and membership query for each friend's
email. No app rewrite is required. Each account sees its own picks—even when two
users save the same quote. Keep public signup and anonymous sign-ins disabled.

Removing someone's `app_pick_members` row blocks their future database access
without deleting their saved picks. Deleting the Auth user also deletes their
saved picks because the tables use cascading foreign keys. Do not delete a user
as a password-reset method if you want to retain their data.

## Behavior and boundaries

- Supabase handles email/password authentication and token refresh. The browser
  persists the Supabase session using its SDK; it does **not** save your plaintext
  password. Clearing browser data removes the session, not the cloud records.
  This is different from the retired HttpOnly-cookie Flask prototype.
- Logout signs out this browser session. Supabase access tokens already issued
  may remain usable until expiry; this is not an instant global token revocation.
- App data is protected by database policies, not merely hidden in the UI.
  Membership and ownership are checked on reads, inserts, updates, and deletes.
  Quotes cannot be edited after saving; only the manual result can be updated.
- Picks refresh on login, reload, browser-tab/window focus, or **Refresh picks**.
  There is no constant polling and no promise of instant push sync across devices.
- A saved snapshot is not independently verified or proof a bet was placed.
  Win/Loss/Push results are manual. Sample picks retain their label across sessions
  and cannot collide with real-model snapshots of the same quote.
- Saving a duplicate quote does not reset its manual result or original timestamp.
  Failed requests show errors; there is no silent browser-storage fallback.
  A timed-out write might have completed—refresh before retrying.
- Free Supabase projects can pause after a week of low activity and need manual
  resuming in the dashboard. Render waking up does not resume Supabase.
  See [pausing](https://supabase.com/docs/guides/platform/free-project-pausing)
  and [current Free limits](https://supabase.com/pricing).
- Keep backups of important data. Clearing browser data is safe for cloud picks;
  deleting the Supabase project/database is not.

## Render later—not needed now

Use the same project URL and publishable key as Render **build-time** environment
variables, then rebuild the regular frontend with `npm run build`.
Do not deploy the sample server or enable demo flags in production.
Add your deployed URL to the appropriate Supabase URL settings.

The Supabase calls go directly from the browser to Supabase; Flask is still used
for NBA projections only. This does not fix or verify the existing hosted
NBA-data-access problem. No Render configuration is changed by this setup.

## Tests

```bash
cd frontend
npm test
npm run build
```

Tests cover login/store transitions with an offline SDK double and actual
PostgreSQL row-level-security behavior in PGlite: separate owners, blocked
anonymous/unapproved users, forged ownership, immutable quotes, manual grading,
and deletion isolation. No Supabase project or real credentials are used by tests.
A real end-to-end Supabase login/save check remains necessary after steps 1–3.

The frontend dependency audit currently reports 10 advisories (including seven
high-severity) in existing tooling dependencies. The Supabase packages were not
flagged. Broader dependency upgrades were not included in this account change;
review these before the later deployment.
