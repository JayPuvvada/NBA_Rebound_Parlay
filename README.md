# NBA Rebound Projection Engine

A Flask and React application for producing NBA player-rebound projections,
fitting a count distribution around each projection, and comparing side-specific
sportsbook prices with model probabilities. It supports a per-game Daily Edge
view, manual player lookup, and a local prediction ledger for evaluation.

This is a probabilistic decision-support tool, not a guarantee of betting
results. The feature coefficients are transparent heuristics and should be
validated on immutable out-of-sample predictions before risking money.

## Requirements

- Python 3.13 (see `.python-version`)
- Node.js 20.19 or newer
- Optional The Odds API key for live rebound lines
- Optional authenticated proxy for `stats.nba.com`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env

cd frontend
npm ci
cd ..
```

Add secrets to `.env`; never commit proxy or sportsbook credentials.

Important settings:

- `ODDS_API_KEY`: enables live lines in Daily Edge.
- `ODDS_MAX_AGE_SECONDS`: maximum provider quote age for actionable Daily Edge
  rows (defaults to five minutes).
- `NBA_API_PROXY`: one full proxy URL used for NBA Stats HTTP requests.
- `CORS_ORIGINS`: comma-separated development origins.
- `PREDICTIONS_DB_PATH`: SQLite ledger location.
- `LEDGER_WRITE_TOKEN`: required authorization secret for opt-in API ledger
  writes. If unset, browser/API writes are disabled.
- `LOG_LEVEL`: defaults to `INFO`.

See `.env.example` for all runtime and rate-limit settings.

## Local development

Run Flask:

```bash
python3 app.py
```

In a second terminal, run Vite:

```bash
cd frontend
npm run dev
```

Vite proxies `/games`, `/predict`, and `/cheat-sheet` to Flask on port 5001.

## API

### `GET /games?date=YYYY-MM-DD`

Returns the NBA slate with stable game IDs and home/away abbreviations.

### `POST /predict`

Example:

```json
{
  "player": "Nikola Jokic",
  "opponent": "BOS",
  "date": "2026-01-15",
  "spread": -4.5,
  "line": 12.5,
  "over_odds": -105,
  "under_odds": -115,
  "home_game": true
}
```

`home_game` may be `null` to verify the venue from that date's schedule. Over
and Under prices are separate because the model evaluates each side at its own
break-even probability. If no price is supplied, the response is informational
and does not pretend a market EV exists.

To save an actionable, scheduled pregame pick, also send
`"record_prediction": true` and the configured secret in the
`X-Ledger-Write-Token` header. Merely viewing or refreshing a projection never
writes to the ledger. Historical, live, final, schedule-unverified,
non-actionable, and unauthorized requests remain diagnostic-only.

### `GET /cheat-sheet?team=BOS&date=YYYY-MM-DD&book=fanduel`

Returns a response envelope containing game metadata, generation time, selected
bookmaker, and both teams' projections. Rows use raw probabilities/fractions in
the API; the frontend performs percentage formatting.

### `GET /health`

Lightweight process health, model version, season, and timestamp.

## Model pipeline

1. Regular-season, Play-In, and playoff data are combined by games played, and
   player logs are filtered to the requested as-of date.
2. Offensive and defensive rebound rates are estimated per minute, with
   recency and small-sample shrinkage.
3. Minutes are projected from season/recent workload, availability, role trend,
   rest, and spread context.
4. Pace, expected misses, pace-normalized opponent rebound environment, venue,
   and matchup heuristics adjust the base projection within guarded limits.
5. A negative-binomial predictive distribution supplies exact over/under/push
   probabilities and deterministic prediction intervals.
6. Each side is evaluated using its own price. EV and fractional Kelly are only
   actionable when the market price and evidence gates are satisfied.

The repository models individual rebound props. It does not currently model
multi-leg parlay correlation or joint outcomes.

Actionable rows require explicit fresh injury provenance, a verified pregame
schedule state, and a sportsbook quote no older than `ODDS_MAX_AGE_SECONDS`.
Anything incomplete or stale is still shown for diagnosis but is labeled
`NO BET` and cannot be written as an issued pick.

## Cache and grading operations

Refresh the daily league/roster cache:

```bash
python3 -m src.cache_manager
```

Grade pending ledger records:

```bash
python3 scripts/grade.py --date YYYY-MM-DD
python3 scripts/grade.py --summary-only
```

Production deployments should schedule cache refresh and grading externally.
Use persistent storage for `data/predictions.db`; many hosts use ephemeral local
filesystems by default.

## Verification

```bash
python3 -m unittest discover -s tests -v

cd frontend
npm run lint
npm run typecheck
npm run build
```

The manual `test_predict*.py` and `test_proxies.py` scripts are inert during
test discovery and only contact external services when executed directly.

## Production

`./build.sh` installs locked frontend dependencies and builds `frontend/dist`.
The `Procfile` starts Gunicorn with a threaded worker. Configure worker count,
threads, and timeout through the documented environment variables.
