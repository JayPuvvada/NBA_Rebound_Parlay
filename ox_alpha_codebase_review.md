# 🔍 Ox Alpha — Full Codebase Review: NBA Rebound Parlay Model

---

## 1. 🌟 Executive Summary & Architectural Overview

This is a genuinely well-conceived system: a **heuristic-multiplier projection core** (`src/features.py`) feeding a **Negative Binomial Monte Carlo simulator** (`src/model.py`), wrapped in a Flask API with a React/Vite frontend. The recent refactors — extracting `recommendation.py` and `cheat_sheet.py` so `/predict` and `/cheat-sheet` can't drift, adding the volume-floor Fano logic, the injury-scrape sanity threshold, and the LOW_VOLUME tier gate — show strong engineering judgment. The test suite covering the simulator and tiering math is a solid foundation most hobby projects never reach.

**Architecture at a glance:**

```
Flask (app.py)
 ├── NBADataLoader (data_loader.py)   ← NBA API + scrapers + odds, ad-hoc dict cache
 ├── FeatureEngineer (features.py)    ← skill × minutes × env multipliers, clamped
 ├── ReboundSimulator (model.py)      ← NegBin MC, empirical/heuristic Fano blend
 └── recommendation.py / cheat_sheet.py ← shared tiering + per-team fan-out
React SPA ← Vite proxy → Flask
```

**The three structural weaknesses:**

1. **No feedback loop.** You never store predictions, so you cannot measure calibration, tier ROI, or whether the raised thresholds (0.68/0.62/0.58) actually improved anything. For a betting tool, this is the single biggest gap — you're flying blind on accuracy.
2. **Staleness-prone, unbounded in-memory caching.** `NBADataLoader._cache` lives forever per process: gamelogs, rosters, and `CommonPlayerInfo` never expire, so trades and last-night's box scores are invisible until a restart.
3. **Monte Carlo where closed-form math exists.** Over/under probabilities from a fitted NegBin are analytically computable via `scipy.stats.nbinom.cdf`. Your 10k-sample simulation injects ~±0.5pp of pure noise into every edge calculation — noise that directly corrupts tier assignments near your 62%/68% thresholds.

Also notable: despite the product name, **there is no parlay engine** — no same-game correlation, no joint leg simulation, no parlay EV. That's your stated differentiator and it doesn't exist yet (roadmap item in §3).

---

## 2. 🛡️ Critical Issues, Potential Bugs & Reliability Risks

### 🔴 BUG — `generate_pick_summary` renders "0% simulation win rate"
`src/features.py`, in `generate_pick_summary`:

```python
win_perc = int(confidence * 100) if confidence > 1 else int(confidence)
```

`confidence` arrives as a fraction (e.g. `0.655`), so the `> 1` branch is dead code and `int(0.655) == 0`. Every narrative in production literally tells users *"Based on a 0% simulation win rate."* Fix:

```python
conf_frac = confidence / 100.0 if confidence > 1.0 else confidence
win_perc = round(conf_frac * 100)
ev_pct = round((edge * 100 if abs(edge) <= 1.0 else edge), 1)
p1 += f"... Based on a {win_perc}% simulation win rate ... +{ev_pct}% Expected Value edge."
```

### 🔴 Reliability — eager init failure leaves routes pointing at undefined globals
`app.py`: if `NBADataLoader()` raises at import time, you log the error but continue registering routes. Every request then dies with `NameError: loader is not defined` → opaque 500s. Fail fast instead:

```python
try:
    loader = NBADataLoader()
    engineer = FeatureEngineer(loader)
    simulator = ReboundSimulator()
except Exception:
    log.exception("Fatal: model components failed to initialize")
    raise SystemExit(1)   # let the platform restart/crash-loop visibly
```

### 🔴 Modeling-correctness — `get_days_rest` is anchored to *now*, not the target game date
`data_loader.py::get_days_rest` computes `(datetime.now() - last_game).days`. When the frontend sends a future date (users absolutely will pick tomorrow's slate in the date picker), rest days are wrong by the offset. Thread the target date through:

```python
def get_days_rest(self, team_id, as_of: str | None = None):
    target = datetime.strptime(as_of, "%Y-%m-%d") if as_of else datetime.now()
    ...
    days_diff = (target - last_date).days
```

Update callers in `app.py::predict` and `cheat_sheet` to pass `date_str`.

### 🔴 Odds matching can grab the wrong game
`data_loader.py::get_odds_for_game` fetches **all** upcoming events with no date filter, then breaks on the first name-substring match. Teams that play twice in a week (very common) will sometimes bind to the wrong event's props. Compare the event date explicitly:

```python
for event in events:
    if event.get('commence_time', '')[:10] != date_str:
        continue
    ...
```

### 🟠 Timezone correctness (three places)
- `app.py::_date.today().isoformat()` — server-local date. A 10:30 PM ET finish or a UTC-hosted deploy flips the slate.
- `frontend/src/components/ui/CheatSheet.tsx`: `new Date().toISOString().split("T")[0]` is **UTC** — after 8 PM ET, the app opens on *tomorrow's* empty slate.
- `ScoreboardV2(game_date=...)` interprets dates in US/Eastern.

Standardize on America/New_York:

```python
from zoneinfo import ZoneInfo
def eastern_today() -> str:
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()
```
```ts
const todayStr = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit"
}).format(new Date());
```

### 🟠 Stale-cache family of bugs (`data_loader.py`)
- `get_player_gamelog` / `get_team_gamelog` / `get_common_player_info` / `get_team_roster` cache **forever** in-process. Last night's results and post-deadline rosters never appear until a restart. Give every entry a TTL (see §4's decorator) — gamelogs ~30–60 min, rosters/player-info ~12 h.
- `get_games_for_date` only caches on success (`if games:`) — an off-night slate re-hits the API on every poll. Cache empty results with a short TTL too.

### 🟠 Input validation gaps in `/predict` (`app.py`)
`float(data.get('spread', ...))` and `int(odds_val)` raise `ValueError` on junk input → 500 with a leaked traceback string. Wrap in a small validator returning 400:

```python
def _to_float(val, field, default=None):
    try:
        return float(val) if val not in (None, '') else default
    except (TypeError, ValueError):
        raise BadRequest(f"'{field}' must be numeric")
```

Also: `jsonify({'error': str(e)})` leaks internals. Log the traceback server-side, return a generic message + request ID.

### 🟠 Injury-status keyword drift
Three separate keyword lists decide who is "OUT": `data_loader.check_status` (`out/inactive/injured/nwt/ruled out`), `features.adjust_minutes_for_injuries` (`out/inactive/nwt`), and the cannibalization scan (`out/inactive`). These *will* drift apart. Centralize:

```python
# src/utils.py
OUT_KEYWORDS = ('out', 'inactive', 'injured', 'nwt', 'ruled out')
TTE_KEYWORDS = ('questionable', 'day-to-day', 'gtd', 'game time decision', 'doubtful')
def injury_bucket(status: str) -> str: ...
```

Related: **Questionable/Day-to-Day players are treated as fully active** in minutes and cannibalization adjustments. Even a modest 20–30% minutes haircut for TTE starters would materially improve Thursday/Friday accuracy.

### 🟡 Misc reliability
- `ox_alpha.py` / `review_codebase_ox.py`: the `ssl._create_unverified_context()` fallback silently disables cert verification — remove it and fix the root CA issue (`pip install --upgrade certifi`).
- `requirements.txt` is fully unpinned — one breaking `nba_api` release takes prod down. Pin everything.
- README references `main.py` and `check_team_fit.py`, neither of which is in the tree — doc drift.
- `frontend/src/declarations.d.ts` declares `@splinetool/react-spline`, which isn't even a dependency anymore (the Spline scene was replaced with the SVG ball in `demo.tsx`). Delete the declaration; `recharts` ships its own types.
- `frontend/src/App.css` is orphaned Vite-template CSS, imported by nothing. Remove.
- `index.html` title is still `"frontend"`.

---

## 3. 🧠 ML & Statistical Modeling Insights

### ✅ What's genuinely good
- **Per-minute skill decomposition** (OREB_PM/DREB_PM) decoupled from minutes, with a DNP-rate penalty — correct instinct.
- **Volume-floor Fano** in `model.py` with the documented rationale (bench players' 0-0-0-5 burstiness) is exactly the kind of discrete-outcome correction most models miss. The tests locking it in are excellent.
- **Clamped environment multiplier [0.85, 1.18]** prevents multiplier-stack explosions.
- **Dynamic recency weights** keyed to games_played, and the trend-break override, are sensible.

### ⚠️ Issue — Monte Carlo noise is corrupting your tier thresholds
At 10k draws, the standard error of a ~60% probability estimate is ≈ **0.49pp**. Your PLAY↔STRONG boundary sits at 68%; LEAN↔PLAY at 62%. Two identical inputs can land on opposite sides of a tier boundary purely from RNG. Since the distribution is a fitted NegBin, compute probabilities **analytically**:

```python
from scipy.stats import nbinom

def get_probabilities(self, sim_result, line):
    n, p = sim_result['params']['n'], sim_result['params']['p']
    k_floor, k_ceil = int(np.floor(line)), int(np.ceil(line))
    cdf_floor = nbinom.cdf(k_floor, n, p)        # P(X <= line)
    cdf_below = nbinom.cdf(k_ceil - 1, n, p)     # P(X < line)
    return {
        'over_probability':  float(1.0 - cdf_floor),
        'under_probability': float(cdf_below),
        'push_probability':  float(cdf_floor - cdf_below),
        'ci_68': np.percentile(sim_result['samples'], [16, 84]).tolist(),  # keep tiny MC for chart only
        'ci_95': np.percentile(sim_result['samples'], [2.5, 97.5]).tolist(),
    }
```

Deterministic, instantaneous, and reproducible. Keep a small (1–2k draw) simulation purely for the histogram/CI visuals if desired. This is probably the highest-ROI *pure-modeling* change available.

### ⚠️ Issue — empirical variance excludes DNPs → overconfidence
In `features.get_player_stats`, you filter `logs[MIN_FLOAT > 0]` **before** computing `reb_variance`/`reb_std`. A bench player's zero-rebound DNP nights — precisely the outcomes that blow up unders — are erased from the empirical Fano. Compute variance on the *unfiltered* series (DNPs as 0) while keeping the per-minute rates on the filtered set:

```python
reb_all = pd.concat([logs['REB'], pd.Series([0]*dnp_count)])  # or compute before filtering
'reb_variance': float(reb_all.var()) if len(reb_all) > 2 else None,
```

### ⚠️ Issue — opponent-history sample size
`opp_oreb_rate`/`opp_dreb_rate` are means over possibly 2–3 games yet carry 15–20% weight. Apply shrinkage toward the season rate:

```python
k = len(opp_logs)
shrink = k / (k + 3)                      # 3-game prior strength
opp_oreb_rate = shrink * opp_raw + (1 - shrink) * season_oreb
```

### ⚠️ Issue — "edge" is probability edge, not EV
`edge_from_odds` returns `confidence − implied_prob`. That's a *probability* edge, but the UI labels it "Expected Value" (`generate_pick_summary`: "+X% Expected Value edge") and the field is named `true_edge`. Actual EV per unit staked:

```python
def ev_per_unit(p_win, american_odds, p_push=0.0):
    dec = 1 + (100/abs(american_odds) if american_odds < 0 else american_odds/100)
    p_loss = 1 - p_win - p_push
    return p_win * (dec - 1) - p_loss      # e.g. 0.57 @ -110 → +0.067 ROI
```

Rename the current field `prob_edge`, add `ev_roi`, and (once you have both sides' prices) de-vig with the multiplicative method for a fair-line comparison. While you're in there: **Kelly fraction** is a natural, cheap addition for stake sizing.

### ⚠️ Structural — the parlay engine doesn't exist
Same-game parlays need **correlated** leg outcomes: legs share pace, missed-shot volume, and teammate minutes. Independent NegBin draws per leg will systematically misprice SGPs. The right architecture: simulate the *game* once (possessions → FGA/misses per team → rebound pool allocation across the rotation), then derive every player's rebound count from that shared world-state. Legs become conditionally dependent through the common environment. This is a significant build, but it's the moat implied by your product name.

### 💡 Modeling upgrades worth queueing
- **Hierarchical simulation**: draw minutes (~Normal around projected minutes, σ≈4–6 scaled by blowout risk) × per-minute rate (~Gamma) rather than folding all variance into one Fano scalar. Captures the "got 34 instead of 28 minutes" pathway that Fano smoothing hides.
- **Calibration layer**: once §7's prediction ledger has a few hundred graded picks, fit isotonic regression mapping raw model probability → empirical frequency, per tier bucket. Your thresholds then become empirically justified rather than hand-tuned.
- **Smooth the long-rebound trigger**: `opp_3par > 0.42` is a cliff; interpolate the matrix continuously between 0.38–0.46.
- **Leakage note for the future**: opponent-split rates currently use only completed games (safe live). The moment you build a backtester against stored logs, you must filter gamelogs to `GAME_DATE < sim_date` — design the ledger schema with that column now.

---

## 4. ⚡ Backend & API Improvements

### TTL cache decorator (replaces the ad-hoc `_cache` protocol)
```python
# src/cache.py
import time, functools, threading

def ttl_cache(seconds: float):
    def deco(fn):
        store, lock = {}, threading.Lock()
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__name__, args, tuple(sorted(kwargs.items())))
            now = time.time()
            with lock:
                hit = store.get(key)
                if hit and now - hit[0] < seconds:
                    return hit[1]
            val = fn(*args, **kwargs)
            with lock:
                store[key] = (now, val)
            return val
        wrapper.invalidate = lambda: store.clear()
        return wrapper
    return deco
```
Apply: gamelogs 1800s, rosters/player-info 43200s, injury report 1200s (you already have disk TTL parity), odds 900s. This fixes the staleness family *and* bounds memory.

### Background warm job instead of cold 30–60s requests
`cache_manager.py` exists but nothing schedules it. Add APScheduler (or a cron + `flask cli` command) that at ~11 AM ET builds: scoreboard for today/tomorrow, all rosters, league stat frames, and — the big one — **precomputes the full cheat sheet for the night's slate** into a JSON blob. Endpoints then serve warm data in milliseconds and fall back to live computation only on miss. This converts your worst UX liability ("may take 30–60 seconds") into a non-issue.

### Parallelize the live fallback path
`cheat_sheet.project_team` loops rosters serially; each player triggers several I/O-bound API calls. Fan out with a bounded pool:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def project_team(...):
    roster = loader.get_team_roster(team_id)
    def one(row):
        try:
            return _project_single_player(...)   # current body of the loop
        except Exception as err:
            log.warning(f"Skipping {row['PLAYER']}: {err}")
            return None
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = [f for f in as_completed([ex.submit(one, r) for _, r in roster.iterrows()])]
    ...
```
Six workers with your existing jittered retry keeps you under stats.nba.com's practical rate ceiling while cutting wall-clock ~5×.

### Cheap API-call reduction
`compute_composite_projection` → `get_player_stats` → `get_common_player_info` runs **per player**, but `CommonTeamRoster` already returns POSITION and HEIGHT for everyone. Pass roster-supplied position into the per-player path and skip ~30 `CommonPlayerInfo` calls per cheat sheet.

### Other backend items
- **Rate limiting**: add `flask-limiter` (e.g. `30/hour` on `/predict`, `10/hour` on `/cheat-sheet`) — both endpoints proxy expensive upstream quota (Odds API costs money per event-odds call).
- **CORS**: `CORS(app)` is wildcard. With the Vite proxy serving same-origin in prod, you can likely drop `flask-cors` entirely; otherwise restrict to your deployed origin.
- **Blueprints**: split `app.py` into `api/predict.py`, `api/slate.py` with a thin `create_app()` factory — makes the Flask test-client suite (§6) trivial and kills the module-global singleton pattern.
- **Season autodetect** — `NBADataLoader(season='2025-26')` hardcodes obsolescence:
```python
def current_season(d: date | None = None) -> str:
    d = d or date.today()
    y = d.year if d.month >= 10 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"
```
- **Static asset caching**: add `send_from_directory(..., max_age=31536000 if hashed else 0)` semantics — Vite hashes filenames, so immutable caching for `/assets/*` is free wins.
- **Structured logging**: swap print-style f-string logs for `structlog` or JSON formatter with a request-ID middleware; you'll want this the moment you debug a bad tier at 2 AM.

---

## 5. 🎨 Frontend UI/UX & React/TypeScript Optimization

### Race conditions on rapid interaction
Both effects in `CheatSheet.tsx` fire fetches without cancellation. Change the date twice quickly and a slow stale response can overwrite the fresh one. Minimal fix:

```ts
useEffect(() => {
  const ac = new AbortController();
  (async () => {
    try {
      const res = await fetch(`/games?date=${date}`, { signal: ac.signal });
      ...
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError(...);
    }
  })();
  return () => ac.abort();
}, [date]);
```

Better: adopt **TanStack Query** — it gives you deduplication, caching, retries, and abort-on-unmount declaratively, and deletes both hand-rolled effects and their loading/error state plumbing. At this app's scale it's a one-hour migration with permanent payoff.

### Fragile error parsing
`CheatSheet.tsx::fetchData` has a nested try/catch guarding `"Unexpected end of JSON input"` — a string-matching anti-pattern. Simplify:

```ts
const res = await fetch(url);
const body = await res.json().catch(() => null);
if (!res.ok || !body) throw new Error(body?.error ?? `Server returned ${res.status}`);
```

### XSS surface via `dangerouslySetInnerHTML`
`PlayerDetailPanel.tsx` and `PredictResults.tsx` inject `summary` HTML built server-side from scraped injury names and matchup strings. Low-probability but real injection vector. Either render a tiny safe-subset (split on `**bold**` markers into `<strong>` elements programmatically — no HTML string at all), or run through DOMPurify:

```tsx
import DOMPurify from "dompurify";
dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(player.summary) }}
```

### Typing: kill the `any` boundary
`data: any[] | null`, `result: any`, `player: any` — the API contract is stable; encode it once:

```ts
// src/types/api.ts
export interface TrendGame { date: string; rebounds: number; opponent: string; minutes?: number }
export interface CheatRow {
  player: string; team: string; opponent: string;
  projection: number; line: number | "-"; direction: "OVER" | "UNDER" | "-";
  tier: string; rest_note: string; context: string;
  components: Record<string, number>;
  trend: TrendGame[];
  edge_raw: number; over_prob?: number; under_prob?: number;
  summary?: string; injuries?: InjuryInfo;
}
export interface PredictResponse { /* mirror of app.py response */ }
```

This immediately pays off in `PredictResults.getComponentLabel`, whose `val > 0.5 && val < 1.5` heuristic exists *because* the components shape is untyped. Better: change the backend to send `{ base: {...}, multipliers: {...} }` and delete the inference hack.

### Component & perf notes
- `ErrorBoundary.tsx` is written but **never mounted** — wrap the tab content in `App.tsx`; a bad recharts payload currently white-screens the whole app.
- Lazy-load the chart bundle: `const TrendChart = lazy(() => import("./TrendChart"))` — recharts is the dominant chunk and isn't needed for the form view.
- Game-pill buttons: `key={i}` → `key={`${g.away}@${g.home}`}` (stable identity).
- Tabs: add `aria-pressed` / `role="tablist"` semantics; expanded rows would benefit from `aria-expanded` on the `<tr>` (make it a button or add keyboard handler — click-only rows are inaccessible).
- Date input on dark theme: add `color-scheme: dark;` to `:root` in `index.css` so the native picker icon/calendar render legibly.
- `framer-motion` is in `package.json` but imported nowhere — remove (~30kB gz saved).
- The "30–60 seconds" loading copy becomes obsolete the moment §4's warm cache lands — replace with skeleton rows for perceived-speed polish.

---

## 6. 🧪 Testing & Code Quality Recommendations

**Current state:** good unit coverage of the *math* (`test_model.py`, `test_recommendation.py` are genuinely well-designed — the threshold-regression tests and volume-floor tests are exemplary). Zero coverage of the *plumbing*: loaders, endpoints, scraping, odds parsing.

**Highest-value additions, in order:**

1. **Endpoint tests with mocked collaborators** (Flask test client + stub loader/engineer/simulator):
```python
class PredictRouteTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(testing=True)   # needs the create_app factory from §4
        self.app.config["LOADER"] = FakeLoader()

    def test_predict_returns_analysis_with_line(self): ...
    def test_predict_400_on_non_numeric_spread(self): ...
    def test_predict_404_on_unknown_player(self): ...
    def test_home_detection_falls_back_gracefully(self): ...
```
2. **`get_odds_for_game` parsing tests** with recorded fixture JSON — especially the wrong-event/date-match bug and the Over-outcome extraction.
3. **Injury sanity-threshold test**: feed a 3-entry scrape with a populated disk cache, assert stale-fallback is returned and disk file untouched.
4. **`get_days_rest(as_of=...)` tests** once the date-anchoring fix lands.
5. **Golden-path `compute_projection` test** with fixture DataFrames asserting monotonicity properties (slower pace ⇒ lower projection; starter OUT ⇒ minutes boost ≤ clamp) rather than exact numbers — property assertions survive heuristic retuning.

**Tooling & structure:**
- Replace the `sys.path.insert` hack in every test file with a `pyproject.toml` + `pip install -e .` — enables `pytest`, `mypy`, and clean imports simultaneously.
- Adopt **ruff** (lint+format) and **mypy** in gradual mode; `src/` currently has almost no annotations, and the dict-shaped payloads (`proj_data`, `sim_res`) are exactly where bugs hide. Introduce dataclasses:
```python
@dataclass
class ProjectionResult:
    projection: float
    components: dict[str, float]
    modifiers: dict[str, Any]
    matchup_context: str = "Neutral"
    player_variance: PlayerVariance | None = None
    ...
```
- Add a GitHub Actions workflow: `ruff check && mypy src && pytest` + `npm ci && tsc -b && eslint .` on PR.
- Pin `requirements.txt` (`pip freeze`), split `-dev.txt`.
- Delete or commit the referenced-but-missing `main.py` / `check_team_fit.py`; align README.
- `data_loader.py` carries dead weight: `get_player_shot_chart` is never called; `get_cannibalization_factor`'s `base_projection_func`/`current_proj_minutes` params are unused. Prune.

---

## 7. 🚀 Concrete Priority Action Plan (Top 5, Highest ROI First)

| # | Action | Files | Why first |
|---|--------|-------|-----------|
| **1** | **Fix the 0%-confidence summary bug + input validation + fail-fast init** | `features.py::generate_pick_summary`, `app.py` | User-visible wrong math in every narrative today; hours of work, eliminates active credibility damage. |
| **2** | **Replace MC probabilities with analytic NegBin CDF** (`scipy.stats.nbinom`) | `model.py::get_probabilities` | Removes ±0.5pp RNG noise sitting directly on top of your 62%/68% tier boundaries. Deterministic, faster, free accuracy. |
| **3** | **Prediction ledger + grading harness** (SQLite: timestamp, inputs, probs, tier, odds → nightly grade vs box scores; Brier score, calibration curve, ROI-by-tier report) | new `src/ledger.py`, `scripts/grade.py` | Closes the accuracy feedback loop. Every future threshold tweak becomes evidence-based instead of vibes. Prerequisite for calibration layer. |
| **4** | **TTL cache layer + season autodetect + `as_of`-anchored rest + odds date-match fix** | `data_loader.py`, new `src/cache.py` | Fixes the entire staleness/wrong-data family (trades, last-night games, future slates, duplicate matchups) in one coherent refactor. |
| **5** | **Warm-slate background job + parallelized live fallback + frontend TanStack Query/AbortController** | `cache_manager.py`, `cheat_sheet.py`, `CheatSheet.tsx` | Kills the 30–60s wait (your worst UX trait), eliminates fetch races, cuts NBA API pressure ~80%. |

**Strategic follow-ups (post-top-5):** the correlated same-game parlay simulator (§3) — it's the product's namesake and its biggest untapped differentiator — then Kelly stake sizing, then the hierarchical minutes×rate simulation to replace the single-Fano abstraction.

The bones here are strong: the math is thoughtful, the shared-module discipline is real, and the test culture has started. Execute items 1–3 and this goes from "clever heuristic tool" to "measurable, improving prediction system" — which is the only kind that wins long-term against the market.