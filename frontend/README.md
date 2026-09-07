# NBA Rebound Engine Frontend

React 19, TypeScript, Vite, Tailwind CSS, and Recharts power three interface views:

- **Daily Edge** loads the NBA schedule, then displays the selected game's player props in backend-ranked edge order.
- **Player Lookup** runs one date-specific projection with optional Over and Under prices.
- **My Picks** uses Supabase email/password login and per-user private snapshots.
  Approve only your account initially; friends can be added later without a rewrite.
  See [Supabase Free setup](../docs/private-account.md). There is no signup form;
  disable signup and anonymous sign-ins in the dashboard too.

## Local development

### Local demo: synthetic data, real Supabase account

From `frontend/`, run `npm run demo`, then open
<http://127.0.0.1:4181/#picks>. Sign in with your Supabase email/password after
following [the setup guide](../docs/private-account.md). Put the project URL and
publishable key in git-ignored `.env.local` (template: `.env.example`).
No Flask server, NBA/odds keys, or working Render deployment is needed.

1. Open Daily Edge and expand Nikola Jokic's synthetic recommendation.
2. Click **Save pick**, then **View My Picks**. Player Lookup also offers saving
   after you submit the prefilled example.
3. Refresh: the snapshot remains. Try a manual Win/Loss/Push result, sign out
   and back in, or remove the pick with confirmation.

The demo uses fixed synthetic data; changing lookup inputs does not calculate
a new forecast. NO BET and fallback examples cannot be saved. Duplicate quotes
are not added twice. Prices/projections are snapshots, not live updates.

These are synthetic NBA picks, but the Supabase login and cloud saving are real.
Saved records retain a **Sample pick — synthetic data** label. Clearing site data
signs you out; sign back in to recover your cloud picks, including from another
browser. Missing configuration disables cloud saving with a setup message.
Only publishable/legacy anon keys belong in frontend settings, never secret or
service-role keys. Database row-level security enforces membership and ownership.

`npm run demo` builds separately into ignored `dist-demo/` and binds only to
127.0.0.1. It uses `.env.demo` for sample data, without the fake browser login.
Stop the server with Ctrl+C. The existing production `dist/` is unchanged.

The earlier browser-only prototype remains under `npm run demo:offline` on the
same port (stop the other demo first). Only that mode uses **jay / demo123** and
localStorage (`nba.personal-demo.picks.v1`). Its picks disappear when site data is
cleared and are not imported into Supabase. Fake login requires a loopback
hostname and `VITE_PERSONAL_DEMO=true`; it is disabled in regular production.

### Regular app development

Use Node 20.19 or newer (`nvm use` reads `.nvmrc`). Install dependencies and start Vite:

```bash
npm ci
npm run dev
```

Vite proxies `/games`, `/cheat-sheet`, and `/predict` to Flask at `http://127.0.0.1:5001`.
Account requests go directly from the browser to Supabase over HTTPS.

## Checks and build

```bash
npm test
npm run lint
npm run typecheck
npm run build
```

`npm run build` runs lint and the strict referenced TypeScript projects before emitting `dist/`. Flask serves that directory in production.

## API units

Probability-like values are raw fractions on the wire. For example, `confidence: 0.61`, `edge: 0.07`, `ev_roi: 0.12`, and `kelly_fraction: 0.03` render as 61%, +7%, +12%, and 3%. UI components perform all percent formatting.

Player Lookup sends side-specific `over_odds` and `under_odds`. If no odds are supplied, the UI treats the output as informational rather than presenting a priced edge. The public form sends `record_prediction: false`. The retained operator API requires `record_prediction: true` and the `X-Ledger-Write-Token` header for server ledger recording; the personal demo does not use that API.

## Backend contract

Public Player Lookup currently hides performance-ledger/token controls and
always sends `record_prediction: false`, without a ledger token header. The
backend recording contract described here remains available for operator use.
Supabase Auth and its Data API handle account requests. The earlier custom
`/api/private` account endpoints are removed. The Supabase SDK persists the
browser session; saved picks live in `app_saved_picks`, protected by RLS and
`app_pick_members`. Account saving never uses the operator ledger token.

- `GET /games?date=YYYY-MM-DD` returns `{ date, games: [{ id, home, away }] }`.
- `GET /cheat-sheet?team=TEAM&date=YYYY-MM-DD&book=BOOK` returns `{ game, bookmaker, generated_at, projections }`. A legacy bare projections array is also accepted during migration.
- `POST /predict` accepts `player`, `opponent`, `date`, nullable `line`, nullable `over_odds`/`under_odds`, nullable `bookmaker`/`matchup`/`home_game`, numeric `spread`, and Boolean `record_prediction`.

Both projection payloads use nullable `direction`: `OVER` or `UNDER` means an actionable positive-EV selection, while `null` means **NO BET**. `evaluated_side`/`odds_side` identifies pricing context and is never treated as a recommendation. Manual recording metadata is `{ requested, recorded, prediction_id, reason }`.

## Betting-focused display (September 7)

Both result views use `BettingAnalysis.tsx`: projection, recommendation or NO BET,
side-specific line/price/probability/expected return, integer-line push chance,
one 68% range, projected minutes, recent appearances, and material risk warnings.
Injury lists and optional form controls are expandable.

The active UI no longer renders duplicate confidence, Kelly, Fano values,
probability edge, implied probability, weighted hit rate, 95% ranges, raw factor
multipliers, internal model metadata, or the long rule-generated narrative.
Backend fields and calculations are unchanged.

Manual prices are explicitly unverified. Expected returns are hidden for
unverified/degraded eligibility or stale quotes. All reported limitations and
injury freshness warnings remain visible. A projection timestamp is not a
sportsbook-update timestamp.

`npm test` runs 29 offline display, storage, auth-transition and access-control
tests. PGlite executes the actual PostgreSQL migration to verify ownership and
membership rules. No real Supabase credentials or live NBA requests are used.
