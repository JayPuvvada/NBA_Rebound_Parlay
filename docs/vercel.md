# Deploy alongside Render

Vercel runs both Flask and the React frontend. No local server is required.
Render's `build.sh` and `Procfile` are unchanged; keep that deployment running.
This configuration has not yet been verified in an actual Vercel deployment.

## Import settings

1. Push the prepared files to GitHub, then import `NBA_Rebound_Parlay` in Vercel.
2. Use the repository root (not `frontend`) as Root Directory.
3. Select **Services** as Framework Preset. `vercel.json` declares one Flask
   service with a catch-all rewrite and supplies its build command
   and function duration. Do not override Output Directory to `frontend/dist`:
   the build copies static assets into `public/` for Vercel's CDN, while Flask
   handles `/health`, `/games`, `/cheat-sheet`, and `/predict` at the same origin.
4. Choose Hobby only if your use meets its personal/non-commercial conditions.
   Do not enable paid add-ons just to make the build pass.
5. Deploy and inspect the build logs. Python scientific dependencies must fit
   Vercel's function bundle limit; a local frontend build does not verify that.

The Python pin is `3.13` rather than `3.13.1`, allowing the host to select an
available patch version. Render's build/start commands remain unchanged.

## Environment variables

- `ODDS_API_KEY`: backend-only, needed for automatic sportsbook prices.
- `OPENROUTER_API_KEY`: optional, only if using the existing narrative feature.
- `NBA_API_PROXY`: optional; only a working proxy you actually have. Never put
  proxy credentials into frontend variables. Keep TLS verification enabled.
- `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`: the checked-in
  `frontend/.env.production` already supplies public browser configuration.
  Override these only if using a different Supabase project.
- `VITE_PUBLIC_SIGNUP=true` is already in that file. The current beta intentionally
  has email confirmation disabled; accounts/picks remain in the same Supabase DB.

Do not copy the entire `.env`, set demo flags, or expose privileged Supabase keys.
Do not configure `LEDGER_WRITE_TOKEN` on Vercel: the optional SQLite operator
ledger is not durable serverless storage. My Picks uses Supabase, not that ledger.
Injury disk caching uses temporary storage on Vercel and can disappear at any
time. In-memory caches and rate limits are per-instance, not globally shared.

## Verify before sharing

1. Open `/health` and confirm JSON, then open the homepage and all three tabs.
2. Sign in with your existing Supabase account and check saved picks.
3. Test a real schedule and player projection; missing NBA data is still an
   unresolved problem. Deploying to another host does not guarantee a fix.
4. Keep the existing Supabase Site URL unless intentionally changing the primary
   site. When adding confirmation/OAuth/reset flows, add the exact Vercel callback
   URLs alongside Render/local URLs. Current password-only login has no redirect.

No Vercel account, project, or deployment is created by these files. Render is
not disabled or reconfigured. See [Flask on Vercel](https://vercel.com/docs/frameworks/backend/flask).
