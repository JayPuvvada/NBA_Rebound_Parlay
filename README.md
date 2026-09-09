# NBA Rebound Projection Engine

A guide to the web app, its model, and the recent changes.

This app estimates **individual NBA player rebounds**, calculates Over/Under
probabilities, and compares them with side-specific sportsbook prices. It has
three tabs: **Daily Edge**, **Player Lookup**, and **My Picks**.

Despite the repository name, it does **not** build parlays, calculate correlated
multi-leg probabilities, place bets, or connect to your sportsbook account.
Its projections and recommendation tiers are heuristic model outputs, not
guarantees of accuracy or profit.

**Updated:** September 7, 2026. The interface now focuses on the betting decision,
with a shared compact results panel. Model calculations and backend API contracts
are unchanged by this display update. The September 5 change audit below remains
anchored to `0f0b903`; newer display changes are listed separately.

## Contents

**Optional Vercel deployment:** see [Vercel setup](docs/vercel.md). The repository
supports preparing a Vercel deployment alongside Render; Render's build/start
files are retained. Hosting changes do not resolve missing NBA data by themselves.

**Current saving UI:** **My Picks** now uses Supabase Auth and private database
rows. Production builds include the public Supabase connection settings.
Public signup is enabled for the small beta; new accounts enroll automatically.
Email confirmation is disabled at the owner's request. Emails are unverified,
and anyone who discovers the site can register. Password reset is not available.
Anonymous login remains disabled. See the [Supabase Free setup](docs/private-account.md).
Your project, user and database policies must be configured before cloud saving
works. No hosted project, default real password, or Render deployment is created
automatically. The earlier custom Flask/Neon account prototype has been replaced.

Player Lookup still sends `record_prediction: false` and no ledger token. The
backend performance ledger and existing records remain intact for operator use.
The earlier token-saving workflow documented below describes that retained API,
not the new private-account bookmarks.

**Try the personal demo:** run `cd frontend` then `npm run demo`, open
<http://127.0.0.1:4181/#picks>, and sign in with your **Supabase email/password**.
The NBA results are synthetic; login and saving use your real Supabase account.
Sample picks remain labeled and survive clearing browser data after you sign
back in. No NBA/odds keys or working Render deployment are required.
The old fake login (**jay / demo123**) is only available via
`npm run demo:offline`, with browser-only storage. See
[frontend demo instructions](frontend/README.md#local-demo-synthetic-data-real-supabase-account).

- [1. App map and navigation](#1-app-map-and-navigation)
- [2. Daily Edge](#2-daily-edge)
- [3. Player Lookup](#3-player-lookup)
- [4. Results and shared feature panels](#4-results-and-shared-feature-panels)
- [5. How the projection works](#5-how-the-projection-works)
- [6. Recommendation tiers and eligibility](#6-recommendation-tiers-and-eligibility)
- [7. Data sources, caching, and outages](#7-data-sources-caching-and-outages)
- [8. Evaluation ledger and grading](#8-evaluation-ledger-and-grading)
- [9. What changed](#9-what-changed)
- [10. Complete changed-file map](#10-complete-changed-file-map)
- [11. Setup and configuration](#11-setup-and-configuration)
- [12. API reference](#12-api-reference)
- [13. Verification and known limitations](#13-verification-and-known-limitations)
- [14. Troubleshooting](#14-troubleshooting)

## 1. App map and navigation

There is one React application with three tabs, not a collection of separate
server-rendered pages:

```text
Home / landing section
├── Daily Edge (#edge)
│   ├── Date + sportsbook selection
│   ├── Game selection
│   ├── Ranked player table for both teams
│   └── Expandable player analysis
├── Player Lookup (#lookup)
│   ├── Manual projection form
│   ├── Projection result and analysis panels
│   └── Save snapshot to My Picks when signed in
└── My Picks (#picks)
    ├── Supabase sign-in / beta signup
    └── Private saved picks and manual outcome review
```

### Landing section

The headline is “NBA rebounds. A clearer bet check.” The basketball is an
animated SVG with lighting/shadow effects; it is not a live visualization of
model data. The component still has the historical name `SplineSceneBasic`,
but the displayed basketball is code-rendered SVG.

“Compare today\'s games” selects Daily Edge and scrolls to the tools. The copy
describes individual rebound props, probabilities, expected return, and warnings.
It explicitly states there is no parlay builder or bet placement.

### Navigation and accessibility

- Daily Edge is the default tab; `#lookup` opens Player Lookup directly.
- Tab changes update the URL hash and support browser Back/Forward navigation.
- Left/Right arrows switch tabs; Home selects Daily Edge and End selects My Picks.
- Labels, focus rings, selected/expanded states, and status/error announcements
  support keyboard and assistive-technology use.
- Layouts adapt to smaller screens; the wide Daily Edge table scrolls sideways.
- Tabs and trend charts load lazily. A rendering error boundary provides a
  recovery screen rather than leaving the entire app blank.
- Tab contents are unmounted when switching away. Player Lookup inputs are
  restored from session storage within the same browser tab, including refresh.
  Projection results and Daily Edge selections are not restored. Drafts are
  browser-tab-local, not account-specific saved picks, and contain no credentials.

Account controls and private saved picks are in My Picks. There is no separate
settings page, operator-ledger dashboard, or parlay builder. Server settings
live in environment variables.

## 2. Daily Edge

**Purpose:** inspect the players in one scheduled game and compare available
rebound markets from a selected sportsbook.

### Controls and request flow

1. **Game date:** defaults to today's date in US Eastern time. Choosing another
   date clears the previous game and results, then requests that date's schedule.
2. **Sportsbook:** FanDuel, DraftKings, or BetMGM. FanDuel is the default.
   Changing this reloads projections/prices for the selected game.
3. **Game buttons:** each button shows `AWAY @ HOME`. Selecting one requests
   both teams' player projections.
4. **Player name:** expands that player's detailed analysis. Selecting the
   name again closes it; only one row is expanded at a time.

The app calls `GET /games`, then `GET /cheat-sheet` for the selected home
team, date, and book. The backend identifies the actual scheduled opponent.
This is a **single-game** view, not an all-games-at-once daily optimizer.

The backend attempts projections for rostered players. Players with unusable
stats or projection errors can be omitted; a partial-slate warning indicates
that some projections failed. A complete pipeline failure is reported as an
error rather than being disguised as an ordinary empty table.

### Rebound props table

| Column | Meaning |
| --- | --- |
| Player | Player name and expand/collapse control. |
| Team | Team abbreviation; house/plane icon indicates home/away. |
| Projection | Expected rebound total, not a guaranteed outcome or ceiling. |
| Line / price | Evaluated rebound line, American odds, and available book label. |
| Model pick | An actionable `OVER` or `UNDER`; otherwise `NO BET`. |
| EV ROI | Model-expected net return per unit staked at that side's price. |
| Tier | Recommendation strength or the reason the row is informational. |

Sorting happens on the backend: actionable rows first, then descending EV,
confidence, and projection. A row near the top is not necessarily a bet—an
entire game can contain no actionable rows.

Expanding a row uses the analysis already returned with that sheet. It does
not fetch a new live quote or save a pick.

### Market-price behavior

- Live prices require a server-side `ODDS_API_KEY`.
- The odds loader finds the event by both teams and the **Eastern game date**,
  then requests rebound props and spreads for that event and selected book.
- Over and Under retain separate prices and, where supplied, separate lines.
  The model evaluates each quote on its own terms.
- A legacy single Over quote is never silently reused as the Under price.
- If the combined props/spreads request fails in the supported fallback path,
  the loader retries props only. Missing spread context is disclosed and
  modeled neutrally.
- Without a matching market, the projection can still appear with missing
  price/line fields and `NO BET`.
- Quote freshness is checked against `ODDS_MAX_AGE_SECONDS` (300 seconds by
  default). Stale or unusable timestamps downgrade the affected rows.
- Provider update times are preferred; the current loader can substitute its
  fetch timestamp when the provider omits an update time. Therefore “fresh”
  is a code-level timestamp check, not proof the sportsbook market is open.
- Daily Edge is a read path: opening it, expanding rows, or retrying does not
  write issued picks to the ledger.

### Loading, errors, and refresh

Schedule requests time out in the browser after 30 seconds; sheet requests
after 110 seconds. Loading copy warns that first loads may be slow and depend on data providers;
it no longer promises a specific completion time.

There are separate “Retry schedule” and “Retry projections” controls.
Changing date/game/book aborts obsolete browser requests to avoid displaying
the wrong response. There is no periodic live refresh or background polling.

Warnings distinguish unavailable prices, partial projections, stale quotes,
and non-pregame games. A successful empty schedule now gets a neutral “No games”
message and a suggestion to choose another date, rather than an outage alert.

## 3. Player Lookup

**Purpose:** run one date-specific projection with optional manually entered
market information. It does not automatically retrieve a sportsbook quote.

### Every form field

| Field | Required? | What it does |
| --- | --- | --- |
| Player name | Yes | Resolves a player through the player directory; ambiguous/unrecognized names fail. Maximum 100 characters. |
| Opponent | Yes | Three-letter NBA abbreviation, such as `LAL`, `BOS`, or `GSW`. The backend verifies the team. |
| Game date | Yes in the UI | Defaults to Eastern today; controls the season, statistical cutoff, schedule, and historical-mode handling. |
| Player team spread | No | Defaults to 0. Enter the spread from the player's team perspective: negative means favored, positive means underdog. UI/API range: -40 to +40. |
| Rebound line | No | Threshold used for Over/Under evaluation; range 0–40. Without it, the result is projection/range only. |
| Over odds | No | American price for Over, entered separately from Under. |
| Under odds | No | American price for Under. A single priced side is allowed. |
| Sportsbook / price source | No | A descriptive label, maximum 50 characters. Typing “FanDuel” does not query FanDuel or verify the quote. |
| Matchup override | No | Opposing player to use for individual-matchup scouting, maximum 100 characters. Must resolve and belong to the opponent roster. |
| Venue | Auto by default | Auto verifies the exact teams/date; Home or Away explicitly supplies the venue. |
| Save actionable pick | No | Opt-in ledger recording, disabled until there is a line and at least one side-specific price. |
| Ledger write token | Only when saving | Password-style input checked against the server's configured token. |

American prices must be whole numbers at most `-100` or at least `+100`.
`-110`, `-115`, and `+120` are valid; `0`, `-90`, and decimals are not.
Prices require a line. Blank price inputs stay missing; the app does not
invent a default `-110`.

### Venue and matchup rules

Auto venue requires a verifiable exact matchup. If the schedule is unavailable
or the game is absent, Auto can fail with an explanation to choose Home/Away.

An explicit venue can allow a **diagnostic** projection when the schedule is
unverifiable. It does not authorize a live pick. If the schedule is available
and contradicts the selected venue, the request is rejected.

The matchup override is an individual scouting assumption, not a confirmed
defensive assignment. Without it, the model tries to infer a likely opponent
using position and playing-time context. Missing optional scouting data can
leave this adjustment neutral. During an outage, a manual override may fail
because the opponent roster cannot be verified.

### Run, cancel, retry, and save

Sportsbook labeling and matchup override are inside “Optional sportsbook label
and matchup.” Saving/token controls are inside “Optional performance tracking.”
Opening these sections does not enable saving; the checkbox remains opt-in.

“Check rebound prop” validates the form, clears the previous result, and sends
`POST /predict`. A spinner and Cancel button appear during the request.

Cancel stops the browser waiting; it does not guarantee Flask has stopped
work or reversed a ledger write already in progress. Errors have a retry
button that rebuilds the request from the current form values.

When saving is selected, the token is sent only in the
`X-Ledger-Write-Token` header. It is not placed in the JSON body or browser
storage, and is cleared after a successful save-request response or when
saving is turned off. Use HTTPS in deployment.

Checking the box is a **request**, not a promise to save. The result explicitly
reports “Saved” or “Not saved” and a reason. A projection can succeed even if
authorization, eligibility, or ledger persistence fails.

### Three useful modes

- **Projection only:** player, opponent, date, and venue; no line or odds.
  Returns expected rebounds and a central range, plus context.
- **Probability analysis:** add a line without prices. Shows Over/Under/Push
  probabilities but does not claim a priced edge.
- **Priced analysis:** add one or both side-specific prices. Evaluates those
  prices, then applies recommendation and data-quality gates.

Historical dates are for diagnostic analysis. Current injuries are not
retrospectively applied, and the system does not have a complete archived
historical injury/roster/market dataset.

## 4. Results and shared feature panels

Player Lookup and expanded Daily Edge rows use the same
[BettingAnalysis component](frontend/src/components/ui/BettingAnalysis.tsx).

### What stays on screen

- **Projected rebounds:** the expected total, with player, opponent, game date,
  venue, and projection-generation time.
- **Model recommendation:** the backend's qualifying side, line, and price,
  or NO BET with a short explanation. A frontend guard cannot invent a pick
  from a high probability or positive return.
- **Both sides:** Over and Under each show their own line, price, model win
  probability, and expected return when usable. Missing prices stay missing.
- **Push probability:** shown for integer lines only, where exact equality can
  return the stake. Half-point lines omit this otherwise zero-value metric.
- **Central 68% rebound range:** one compact outcome range, with an explicit
  warning that results can fall outside it.
- **Projected minutes:** a useful indication of the workload assumed by the model.
- **Risk notes:** high variability, spread-related minutes risk, and injury/data
  limitations remain visible.
- **Recent appearances:** up to ten game totals, oldest to newest, compared
  with the recommended side at the shown line.
- **Injury reports:** roster lists are expandable; important injury impact and
  freshness warnings remain outside the collapsed section.

The selected game already supplies matchup context in Daily Edge, so the table
does not repeat an opponent column for every player.

### Metrics removed from the betting interface

Duplicate Confidence, probability edge, implied probability, Kelly sizing,
weighted hit rate, raw Fano values, the 95% interval, interval coverage/method
labels, model IDs, recency weights, raw factor multipliers, and duplicate DvP
aliases are no longer shown in the active result views.

The long rule-generated narrative is also no longer rendered. This avoids
repeating the displayed numbers and old wording implying “safe” outcomes.
These fields and the underlying backend calculations remain available in the
API for debugging/evaluation; this change does not retune the model.

### Reading the remaining numbers

**Model win probability** is the chance of strictly beating that side's line
under the fitted rebound distribution. It is not confidence in the software
or a verified historical success rate.

**Expected return** is model-estimated net profit per amount staked at that
specific price. For example, an API fraction of 0.08 displays as +8%. It is not
a guaranteed profit, and a positive number alone does not constitute a pick.
NO BET can still appear when a priced signal fails the evidence thresholds.

Return estimates are hidden when eligibility is unverified, explicitly
negative, or projection sources are degraded, and for stale-quote results.
Probabilities remain visible for diagnostic analysis, alongside the warnings.
Conflicting safety flags are resolved conservatively for display.

**The 68% range** describes an outcome interval from the fitted distribution,
not a guaranteed floor/ceiling and not historical calibration coverage.
The backend still computes its exact 68% and 95% intervals.

### Quote provenance and missing data

Manual Lookup prices are labeled “Manually entered · not independently
verified.” A projection-generation time is never labeled as a sportsbook
update by the new panel.

Daily Edge shows a quote-update timestamp if supplied, otherwise says it is
unavailable. Provider/fetch-time limitations described in section 7 still apply.
Distinct Over/Under lines retain their own side-specific evaluations; the UI
does not substitute the selected line's probability for a different line.

The player header is labeled “Projection generated,” separate from quote time.
Injury information shows a compact report-status/timestamp note. Stale injury
warnings remain explicit even when the backend's bounded stale policy permits
the result. An empty injury list says that it does not confirm a healthy roster.

### Recent games and tracking feedback

Chart colors represent wins/losses against the recommended side, not necessarily
the Over. Without a recommended side, bars stay neutral. Previous totals are
not portrayed as a forecast or an independent measure of edge.

When saving was requested, Player Lookup preserves the success/failure reason
and clarifies that recording a model pick does not place a bet.

## 5. How the projection works

Implementation: [features.py](src/features.py),
[model.py](src/model.py), and [recommendation.py](src/recommendation.py).

```text
Inputs + date
  → player/team identification and schedule context
  → pre-cutoff game logs, team data, and allowed injury information
  → per-minute rates × projected minutes
  → bounded environment and individual-matchup adjustments
  → negative-binomial rebound distribution
  → exact Over / Under / Push probabilities
  → side-specific price evaluation + eligibility gates
  → display; optionally record an eligible pick
```

### Statistical data and cutoffs

- Season selection follows the requested date rather than always using the
  current season.
- Player/team log retrieval combines regular-season, Play-In, and playoff
  periods; combined per-game dashboards use games-played weighting.
- Dated projections exclude games on or after the target date.
- Historical team identity preferentially comes from the newest pre-cutoff
  gamelog rather than today's roster, reducing trade-related leakage.
- Played appearances determine rebound variance. Genuine zero-minute rows
  are separate availability metadata, not artificial zero-rebound losses.
- Very short appearances are normally excluded from per-minute skill rates
  but can remain in appearance-based variance/trend data.

These safeguards reduce look-ahead leakage; they do not turn the app into a
fully point-in-time historical backtesting platform.

### Skill and minutes

Offensive/defensive rebounds are aggregated per minute. Recent rates use five
games and shrink toward the season rate; opponent-history rates use an
eight-game prior to reduce small-sample effects.

The ordinary minutes baseline is 60% season average plus 40% last-ten average.
A sufficiently large recent minutes trend can shift this by at most 1.5 minutes.
Near-term injury rules can reduce a questionable player's minutes, exclude an
OUT player, or redistribute a bounded amount of missing teammates' minutes.

The base rate blend changes with the number of appearances:

| Sample size | Season | Recent | Opponent history |
| --- | --- | --- | --- |
| Fewer than 15 games | 75% | 15% | 10% |
| 15–40 games | 65% | 25% | 10% |
| More than 40 games | 55% | 35% | 10% |

Missing opponent history sends that weight to the season rate. A large
recent-rate deviation can shift up to another ten percentage points toward
recent form, subject to a season-weight floor.

Large absolute spreads reduce minutes modestly for high-minute players:
9.5+ can produce Slight risk; 13.5+ can produce High risk. These are fixed
heuristics, not a trained probability of a blowout.

### Environment and scouting

Pace is measured against the player's team baseline to avoid rewarding the
same fast team twice. Miss opportunities similarly use the player's embedded
team shooting context. Opponent rebound totals are pace-normalized and are
honestly labeled as team-level information.

Optional individual scouting considers rebound percentage, tracking/chance
statistics, contested rebounds, and box-outs where available. Per-game
box-outs are not divided by games played again. The combined scouting effect
is modest and bounded.

Venue and back-to-back rules, three-point/long-rebound context, and available
teammate rebound competition also contribute. Correlated effects are shrunk
toward neutral. The environment is initially limited to 0.90–1.10; after the
lineup adjustment the combined bounds are 0.88–1.12.

These coefficients are transparent hand-set assumptions. The repository does
not establish that they are empirically optimal or profitable.

### Count distribution

The simulator fits a negative-binomial distribution to the projected mean
and estimated variance. It uses a heuristic variance prior, sample-size
shrinkage, and volume-specific uncertainty floors rather than treating tiny
samples as highly certain.

The default diagnostic sample has 10,000 draws. Random seeds are supported
internally for repeatable tests, but are not a browser control.

The sportsbook line does **not** pull the model mean toward the market.
It is applied after fitting. Exact distribution calculations—not the random
sample—produce market probabilities and prediction intervals, so changing
the random seed alone does not change those results.

ESPN fallback totals do not contain offensive/defensive splits. In that path,
the internal rate calculation carries the total through one channel solely
to preserve the sum; it is not a claim that all rebounds were defensive.
Split-dependent miss/opponent-environment adjustments are disabled.

## 6. Recommendation tiers and eligibility

There are two separate questions:

1. **Data eligibility:** is the context acceptable for a live pick?
2. **Priced recommendation:** does an offered side meet the model's thresholds?

Passing either one alone is insufficient.

### Tier rules

The following describes the current implementation, not independently
validated betting advice. Ordinary actionable tiers require a projection of
at least 3 rebounds, at least 6 valid trend games, a supplied price, positive
probability edge, and EV ROI of at least 2%.

| Tier | Additional/current thresholds |
| --- | --- |
| STRONG PLAY | At least 8 games; EV ≥10%; win probability ≥60%; edge ≥5 percentage points. |
| PLAY | EV ≥5%; win probability ≥56%; edge ≥2.5 percentage points. |
| TREND LEAN | At least 8 games; EV ≥2.5%; win probability ≥52%; weighted hit rate ≥70%. |
| LEAN | EV ≥2%; win probability ≥53%. |
| HIGH-VARIANCE LEAN | High-variance branch only: EV ≥6%; win probability ≥56%; edge ≥2.5 percentage points. |
| AVOID | The priced signal fails the required rules. |
| LOW_VOLUME | Mean projection is below the tiering minimum. |
| INSUFFICIENT_DATA | Too few trend games. |
| NO_PRICE | No usable price for recommendation math. |

Rules are checked in code order, and the high-variance branch prevents
promotion to an ordinary stronger tier. The older “SAFE PLAY” concept is not
a currently issued tier, even though compatibility styling/narrative text
can still contain the name.

Additional response labels include `STALE_ODDS`, `GAME_NOT_PREGAME`, and
`HISTORICAL_CONTEXT_INCOMPLETE`. The last label is also reused for some
nonhistorical data-quality failures; the accompanying limitations explain the
actual issue.

The winning side is selected by highest EV **among actionable candidates**.
A larger apparent EV on an AVOID side must not mask a smaller qualifying side.

### Data and schedule gates

- The date must be current/near-term, not historical. The live-injury window
  covers Eastern today through two days ahead.
- Projection-source tracking must remain acceptable. Marked alternate/
  estimated projection inputs make the result diagnostic-only.
- Injury status must be accepted by the current policy.
- The exact matchup and venue must be verified and the game must be pregame.
  Live, final, postponed, canceled, and unknown states do not qualify.
- Daily Edge additionally checks the selected quote's age.
- Manual ledger issuance freshly rechecks the schedule immediately before
  recording, and requires token authorization.

**Important injury-policy exception:** the code accepts a bounded stale disk
injury report during a poor/failed scrape, up to six hours from its embedded
timestamp. It is disclosed as stale/degraded but can still pass the injury
gate. Thus “every actionable pick always uses a freshly scraped injury report”
would be inaccurate. Unknown, missing, or unbounded/legacy injury data is not
accepted.

Manual prices have no independently verified provider timestamp. A successful
manual priced analysis means the server evaluated what you entered, not that
it confirmed the quote still exists.

## 7. Data sources, caching, and outages

Implementation: [data_loader.py](src/data_loader.py),
[cache.py](src/cache.py), and [cache_manager.py](src/cache_manager.py).

### Sources

| Source | Used for | Main limitation |
| --- | --- | --- |
| NBA Stats via `nba_api` | Player/team logs, dashboards, roster, scouting, schedule. | Can time out or be blocked from a particular machine/host even without a global outage. |
| Static NBA directory | Player/team ID resolution. | Tied to the installed package's directory; not proof of a current roster. |
| ESPN public feeds | Fallback player identity, actual game totals/minutes, and schedule. | Partial substitute; roster identity can be season-based and rebound splits are unavailable. |
| CBS Sports + ESPN injury pages | Scraped current injury information. | Page layouts, completeness, and update timing can change. |
| The Odds API | Selected game's book-specific rebound quotes and spreads. | Requires a key, available markets, and provider quota/access. |
| Local cache files / memory | Reuse previously fetched data. | Subject to freshness/schema rules; not an independent live source. |

### NBA Stats recovery

A normal NBA Stats attempt defaults to an eight-second timeout and one
attempt. On a connection/timeout failure or a recognized blocking/server HTTP
error, that loader temporarily suspends further primary calls for five minutes.
HTTP 403, 429, and server errors qualify when exposed as HTTP exceptions.

The next **uncached request after that window** tries NBA Stats again.
This is request-driven recovery:

```text
Primary request fails
  → primary calls paused for 5 minutes
  → supported requests try fallback
  → fallback retains diagnostic provenance while cached
  → after cooldown/cache expiry, next request probes primary again
```

There is no background health ping. A browser Retry during the cooldown does
not force an immediate primary probe. A successful primary response also does
not prove every other NBA endpoint is healthy.

Parsing/argument errors do not open the transport-failure circuit. They may
still cause that operation to fail or take its supported fallback path.

The circuit and in-memory caches are process-local (with loader state per
season). They are not a distributed outage detector shared across deployments.

### What fallback can and cannot do

Player Lookup can use ESPN identity and logs, try an ESPN schedule, and
neutralize unavailable league matchup/rest inputs. This can produce an
informational projection during a primary outage.

It cannot guarantee success if ESPN also fails, the player cannot be mapped,
usable season history is missing, or a required roster/manual matchup cannot
be verified. Daily Edge does not have a complete alternate roster and advanced
statistics pipeline and can still fail when the primary source is unavailable.

ESPN dates/team abbreviations are normalized and schedule payloads validated.
Missing event data is not treated as a successfully verified empty slate.
Postponed/unknown pregame-like statuses are not automatically “scheduled.”

### Cache lifetimes

| Cache/state | Current policy |
| --- | --- |
| Primary common player info | Up to 6 hours. |
| Player/team gamelog decorator caches | Up to 45 minutes. |
| Ordinary cached schedule | Up to 15 minutes; current/future route checks use the fresh method. |
| Provenance-aware degraded info/log/schedule results | At most 5 minutes. |
| Raw ESPN stats/gamelog resource cache | Reused for at most 5 minutes; athlete-ID mapping is separately cached. |
| Odds calls | Up to 5 minutes; quote-age gating is a separate check. |
| Mutable roster cache | Up to 6 hours. |
| Offline league snapshot | Validated at load with a 12-hour embedded-timestamp limit and correct season/schema. |
| Normal injury cache | 20-minute reuse window. |
| Failed/partial injury scrape | Short two-minute retry cache, unless bounded stale disk data is used. |
| Bounded stale injury fallback | No later than 6 hours from the embedded source timestamp. |

These are specific cache policies, not a blanket promise that every piece of
data in a long-lived process is refreshed at the same interval. Some league
dashboard data is also held in season/date-keyed memory caches.

The TTL cache protects concurrent callers from duplicate same-key fetches,
clones mutable results, uses season-aware keys, and normally avoids caching
empty failures. Verified empty schedules may be cached.

The source-aware wrapper caches data **together with its provenance** and
replays that provenance on cache hits. A cached ESPN result must not turn into
“primary NBA data” merely because a later request resets source tracking.

Disk snapshots are validated and written atomically. File modification time
alone does not make an old/copied snapshot fresh. Legacy injury JSON without
an embedded timestamp is rejected as current evidence.

### Proxy and process health

`NBA_API_PROXY` routes NBA Stats requests through a configured proxy; it
does not automatically proxy ESPN, injury scraping, or The Odds API.

`NBA_API_PROXY_VERIFY_SSL` defaults to true. Setting it false relaxes TLS
verification on the NBA API session when a proxy is configured, reducing
certificate protection. It is an explicit compatibility option for a trusted
interception setup, not a general outage fix.

`GET /health` reports Flask process status, model version, season, and time.
It does **not** contact NBA Stats, verify odds/injuries, test the ledger, or
prove a model request will complete.

## 8. Evaluation ledger and grading

The ledger is an SQLite evaluation record, not a sportsbook transaction log.
There is no ledger browser page in the current app.

### Recording

Browser writes are opt-in through Player Lookup. They require a qualifying
priced pick, valid schedule/eligibility context, and the write token.

Stored information includes player, game, team/opponent, venue, mean, line,
side/price/book, model version, probabilities, EV, Kelly, and an input snapshot
containing relevant factors, injury/trend information, and schedule evidence.

Prediction inputs are append-only. Repeating an identical issued pick returns
its existing record; changed material inputs create a new version. Refreshing
does not reset a graded result. Side/probability/price/EV consistency is checked
before insertion. Existing schema migration is designed to preserve grades.

### Grading and performance

The grader matches completed historical player logs to the prediction date
and opponent. It selects the appropriate season. Missing or ambiguous rows
stay pending instead of being assigned zero rebounds or automatically voided.

Default automatic grading skips today and future dates. Same-day grading
requires an explicit option and independent confirmation that games are final.

Settlements are WIN, LOSS, PUSH, or an explicitly reasoned VOID. Final
settlements cannot be overwritten by another grading call. A win earns the
offered price's net profit on one unit; a loss is -1 unit; pushes/voids are zero.

The CLI reports per-tier win/loss/push counts, voids, units, realized ROI, and
Brier score. Win rate excludes pushes/voids; ROI counts settled nonvoid bets,
including pushes. Binary Brier scoring excludes pushes and conditions win
probability on a non-push outcome.

### Operator commands

These commands perform work; they were **not run for this documentation update**.

```bash
# Refresh the league/roster disk snapshot (contacts NBA data services).
python3 -m src.cache_manager

# Grade a particular completed date; replace the placeholder.
python3 scripts/grade.py --date YYYY-MM-DD

# Print existing evaluation results without fetching game logs.
python3 scripts/grade.py --summary-only

# Use a nondefault database explicitly.
python3 scripts/grade.py --db /path/to/predictions.db --summary-only

# Explicitly settle one pending record after independently verifying the result.
python3 scripts/grade.py --prediction-id 123 --actual 12
python3 scripts/grade.py --prediction-id 123 --void "Confirmed sportsbook void"
```

Use `--allow-today` only after checking finality. The standalone grader accepts
`--db`; do not assume changing the web app's `PREDICTIONS_DB_PATH` silently
changes the CLI's default database.

Cache refresh/grading schedules must be configured externally. Gunicorn does
not automatically run them. Persist and back up the ledger on production hosts.

## 9. What changed

### Scope and attribution

Git records the recent work as large commits, including an amended commit.
It does not preserve a separate commit for each conversational request.

This section maps the **recent assistant-assisted work visible in the
repository**, using `03638e2` as the pre-overhaul baseline. It does not claim
that every existing feature was invented in the latest session or that every
line in a user-created/amended commit was individually authored by the assistant.
Earlier commits already contained the negative-binomial/ledger/cache
architecture, as well as prior frontend and summary features.

| Commit | Role in the recent history |
| --- | --- |
| `03638e2` — fix push | Baseline immediately before the broad recent overhaul. |
| `522e430` — gpt sol 5.6 ultra fixes | Broad model/API/frontend/persistence/test/deployment overhaul: 65 changed paths against the baseline. |
| `a192b03` — more fixes | Amended replacement containing that work plus later outage/recovery fixes and a diagnostic script. Compared with `522e430`: 11 changed paths. |
| `0f0b903` — Merge origin/main, preserving amended fixes | GitHub history repair. Preserves both branches; application file contents are identical to `a192b03`. |
| This README update | Documents the code and history; no application behavior changes. |

The original and amended commits were siblings, not consecutive changes.
A normal push failed because local `main` was one commit ahead and one behind.
The repair merged the histories, resolved conflicts in favor of the newer
amended files, and pushed normally without force-pushing.

### E. September 7 interface simplification

- Added one shared betting-analysis panel for Lookup and Daily Edge.
- Kept projection, price/line, side probabilities, modeled return, one range,
  minutes, recent games, and material risk warnings.
- Removed repeated/technical metrics and the long generated narrative from
  active views; backend formulas and responses are unchanged.
- Replaced tier-code clutter with a plain recommendation/NO BET explanation.
- Preserved side-specific prices/lines and conservative display eligibility.
- Collapsed optional form controls and injury lists, while retaining warnings.
- Rewrote the hero, browser title, form action, loading copy, and empty schedule
  state to match an individual rebound-prop comparison tool.
- Added 12 automated frontend display/contract tests (`npm test`).

### A. Model and recommendation corrections

- Kept the model mean independent of the sportsbook line.
- Reworked negative-binomial validation, reproducible diagnostic sampling,
  empirical variance shrinkage, low-volume floors, and high-variance warnings.
- Used exact strict Over/Under/Push probabilities and deterministic integer
  prediction intervals.
- Corrected per-minute rate estimation, appearance/DNP treatment, trend
  chronology, and sample-size reporting.
- Added season/date-aware lookups and pre-target-date filtering; improved
  historical team assignment across trades.
- Reduced hot-streak, minutes, injury, and scouting effects to bounded changes.
- Corrected pace/miss baselines and reduced duplicated environment effects.
- Renamed misleading position-DvP interpretation to team-level rebound
  environment while retaining compatibility aliases.
- Corrected per-game box-out handling.
- Replaced confidence-only/“safe” selection rules with price-aware, sample-aware
  tiers and a minimum EV threshold.
- Separated implied probability, push-adjusted probability edge, EV ROI, and
  quarter-Kelly; retained missing odds instead of fabricating prices.
- Compared offered sides independently and selected the best qualifying side.
- Updated narrative/trend logic to use actual EV and the newest chronological
  observations rather than conflating probability edge with expected return.

### B. API and web interface overhaul

- Added input validation, bounded numeric fields, structured error codes,
  request-body size safeguards, and configurable per-client route rate limits.
- Added season-correct component reuse and exact schedule/venue checks.
- Marked historical, incomplete, live/final, and unverified context diagnostic.
- Added fresh pre-issuance schedule verification for manual ledger writes.
- Gave Daily Edge a response envelope with game/book/time/odds metadata,
  per-team pipeline diagnostics, and partial-result warnings.
- Passed team-perspective spreads/rest/date into both teams' projections.
- Added quote-age checks and explicit NO BET downgrades.
- Reworked the two-tab interface, hash/history/keyboard behavior, responsive
  layouts, loading/error recovery, request cancellation, and retry controls.
- Expanded Player Lookup with separate Over/Under prices, venue selection,
  optional source/matchup labels, and token-protected opt-in ledger saving.
- Standardized typed fractional API values and null handling.
- Added shared freshness, pricing, probability interval, variance, factor,
  narrative, and model-context panels.
- Corrected Under-side chart coloring and oldest-to-newest trend handling.
- Used text-safe narrative rendering, lazy-loaded views/charts, and clearer
  accessibility labels/focus states.

### C. Data, persistence, and operational changes

- Routed primary calls through consistent timeout/header/proxy handling.
- Validated payloads and distinguished upstream failures from valid empty data.
- Combined seasonal periods with appropriate games-played weighting.
- Retained separate price/book/date provenance for both market sides.
- Made TTL caching season-aware, mutation-safe, and concurrency-aware.
- Added complete/schema-checked offline snapshots with embedded timestamps and
  atomic writes instead of relying on file modification times.
- Bounded roster/injury reuse and protected good injury snapshots from
  suspiciously small scrapes.
- Reworked the ledger into immutable, versioned prediction snapshots with
  duplicate protection, consistent pricing metrics, and preserved settlements.
- Removed automatic ledger writes from normal browser read paths.
- Corrected grading dates/seasons, missing-log handling, push/void settlement,
  realized unit returns, and conditional Brier calculations.
- Updated dependency/runtime declarations, strict frontend checks, build
  scripts, threaded Gunicorn configuration, and GitHub Actions CI.
- Added/expanded focused backend tests and guarded several standalone live
  diagnostic scripts from running merely on import.

### D. Later NBA outage and recovery fixes

These are the additional application changes between `522e430` and
`a192b03`, beyond the broad overhaul:

1. **Actionable upstream error response:** Player Lookup returns a structured
   NBA-data-unavailable error instead of exposing a generic internal failure.
2. **Bounded primary probe:** an eight-second/one-attempt default and a
   five-minute transport-failure circuit reduce repeated waits.
3. **Selective circuit opening:** parsing/programming errors do not suspend
   unrelated healthy NBA endpoints.
4. **ESPN fallback:** player mapping, season identity, actual rebound/minute
   logs, and schedules support some diagnostic manual projections.
5. **Neutral missing context:** unavailable league matchup/rest data can be
   disclosed and neutralized rather than always preventing a lookup.
6. **Rest bounds:** long/offseason breaks are capped at the model's 14-day
   input limit.
7. **Truthful source state:** request-local source tracking and cached
   provenance keep degraded results diagnostic on repeat requests.
8. **Recovery-friendly retention:** fallback data and raw ESPN resources
   refresh after five minutes rather than retaining an outage indefinitely.
9. **No invented historical splits:** actual ESPN total rebounds replace
   reconstructing offensive/defensive splits using later season averages.
   Split-dependent adjustments are disabled.
10. **Schedule validation:** malformed/absent events, Eastern date mismatches,
    and postponed/unknown pregame states are handled explicitly.
11. **Proxy TLS option:** added the explicit verification setting, defaulting
    to verification on.
12. **Regression coverage and docs:** added tests for repeated cached requests,
    recovery after cooldown, source labels, actual totals, schedule edge
    cases, and bounded rest.

The amended commit also includes `test_proxy_scraper.py`. It is a local
diagnostic, not part of the web request path or a general production fix.

## 10. Complete changed-file map

The following groups account for all **66 changed paths** between
`03638e2` and `a192b03`. A changed path can be an addition, modification,
or removal. This is a file-level audit map, not a claim that all 66 files
were newly created.

| Area | Changed paths | Responsibility/change |
| --- | --- | --- |
| Main documentation | `README.md` | Setup, behavior, limitations, and this expanded guide. |
| Frontend documentation | `frontend/README.md` | Frontend setup, units, API and ledger contract. |
| Server/API | `app.py` | Validation, routing, date/schedule gates, responses, rate limits, opt-in writes, static serving, upstream errors. |
| Data retrieval | `src/data_loader.py` | NBA/ESPN/odds/injury sources, cutoffs, validation, provenance, proxy/circuit and source caches. |
| Projection features | `src/features.py` | Rates/minutes, bounded adjustments, scouting, eligibility metadata, summaries, total-only fallback. |
| Distribution | `src/model.py` | Validated negative-binomial fitting, uncertainty and exact probabilities/intervals. |
| Recommendations | `src/recommendation.py` | Side-specific quotes, EV-gated tiers, historical hit rate and candidate selection. |
| Shared backend utilities | `src/utils.py` | Names, dates/seasons, logging, validated push-aware odds/EV/Kelly math. |
| Batch projections | `src/cheat_sheet.py` | Per-roster player analysis, quote selection, diagnostics and optional internal persistence. |
| Memory cache | `src/cache.py` | TTL keys, cloning, concurrent-call protection and value-dependent retention. |
| Disk refresh | `src/cache_manager.py` | Dated complete league/roster snapshots, validation, atomic writes. |
| Ledger | `src/ledger.py` | Schema migration, immutable identities/snapshots, consistency checks, grading and summaries. |
| Grading CLI | `scripts/grade.py` | Season-aware automatic grading, explicit manual settlement, pending/void handling and reports. |
| Injury data artifact | `data/injury_report.json` | Refreshed cache content; amended version uses timestamp + injuries format. It is data, not a model rule. |
| Tab shell | `frontend/src/App.tsx` | Tab navigation/history, keyboard support, lazy loading/error boundary. |
| Daily Edge | `frontend/src/components/ui/CheatSheet.tsx` | Date/book/game controls, requests, ranked table, warnings and row expansion. |
| Lookup form | `frontend/src/components/ui/PredictForm.tsx` | Fields, validation, cancellation, retry and write token. |
| Result containers | `frontend/src/components/ui/PredictResults.tsx`, `frontend/src/components/ui/PlayerDetailPanel.tsx` | Full and expanded player analysis. |
| Source/context panels | `frontend/src/components/ui/DataFreshness.tsx`, `frontend/src/components/ui/ProjectionContext.tsx`, `frontend/src/components/ui/ProjectionMeta.tsx` | Source age, limitations, technical context and quote provenance. |
| Analysis panels | `frontend/src/components/ui/FactorBreakdown.tsx`, `frontend/src/components/ui/PredictionIntervals.tsx`, `frontend/src/components/ui/SideEvaluations.tsx`, `frontend/src/components/ui/VarianceNotice.tsx` | Factors, ranges, side comparisons and uncertainty. |
| Narrative/chart | `frontend/src/components/ui/MarkdownText.tsx`, `frontend/src/components/ui/TrendChart.tsx` | Safe text formatting and side-aware chronological chart. |
| Shared visual shell | `frontend/src/components/ui/ErrorBoundary.tsx`, `frontend/src/components/ui/card.tsx`, `frontend/src/components/ui/demo.tsx`, `frontend/src/components/ui/spotlight.tsx`, `frontend/src/index.css` | Recovery UI, styling, hero interaction and accessibility/layout adjustments. |
| Browser utilities/types | `frontend/src/lib/api.ts`, `frontend/src/lib/format.ts`, `frontend/src/lib/trend.ts`, `frontend/src/lib/utils.ts`, `frontend/src/types/api.ts` | Typed request/error contracts, cancellation, formatting, units, response normalization and chart-result logic. |
| TypeScript cleanup | `frontend/tsconfig.app.json`, `frontend/tsconfig.json`, `frontend/src/declarations.d.ts` (removed) | Strict project configuration and removal of obsolete declarations. |
| Frontend runtime/dependencies | `frontend/.nvmrc`, `frontend/package.json`, `frontend/package-lock.json` | Node declaration, scripts and locked dependency metadata. |
| Backend runtime/dependencies | `.python-version`, `requirements.txt` | Python declaration and pinned requirements. |
| Configuration/deployment | `.env.example`, `.gitignore`, `Procfile`, `build.sh`, `.github/workflows/ci.yml` | Configurable settings, ignore rules, reproducible build, threaded serving and automated checks. |
| Live diagnostic scripts | `test_predict.py`, `test_predict_local.py`, `test_proxies.py`, `test_proxy_scraper.py` | Manual request/proxy troubleshooting; not normal unit tests or browser features. |
| API/data tests | `tests/test_app.py`, `tests/test_data_loader.py`, `tests/test_cheat_sheet.py` | Validation, schedule/eligibility, recovery, pricing, partial failure and persistence contracts. |
| Model/math tests | `tests/test_features.py`, `tests/test_model.py`, `tests/test_recommendation.py`, `tests/test_utils.py` | Statistical boundaries, cutoff/variance logic, probability/pricing math and tier behavior. |
| Cache/ledger tests | `tests/test_cache.py`, `tests/test_cache_manager.py`, `tests/test_ledger.py`, `tests/test_grade.py` | Concurrency/mutation, freshness, atomic persistence, identity, migration and settlement. |

For exact line-by-line history, these read-only commands reproduce the scope:

```bash
# Broad recent overhaul.
git diff 03638e2 522e430

# Additional amended/outage changes.
git diff 522e430 a192b03

# Entire recent application change set.
git diff --stat 03638e2 a192b03

# Git repair changed history, not application file contents: expected empty diff.
git diff a192b03 0f0b903
```

## 11. Setup and configuration

### Runtime and install

The repository declares Python 3.13.1 in `.python-version` and Node 20.19.0
in `frontend/.nvmrc`; `frontend/package.json` declares Node >=20.19.0.
These describe this checkout, not a claim about every dependency's future
runtime compatibility.

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt

# First setup only: do not overwrite an existing configured .env.
cp -n .env.example .env

cd frontend
npm ci
cd ..
```

Add secrets to `.env` locally. Do not commit tokens, proxy credentials, or
generated databases. Verify ignored/untracked files before committing;
the current ignore file explicitly lists `venv/` and `env/`, but does not
explicitly list `.venv/`.

### Development

Terminal one, from the root with the Python environment active:

```bash
python3 app.py
```

Terminal two:

```bash
cd frontend
npm run dev
```

Open the URL printed by Vite (normally port 5173). Flask uses port 5001.
Vite proxies `/games`, `/predict`, and `/cheat-sheet` to Flask.
For process health in development, use Flask directly:
`http://127.0.0.1:5001/health`.

The built-in Flask command enables development debugging. Use the production
server configuration for public hosting.

### Environment variables

| Variable | Default/example | Purpose |
| --- | --- | --- |
| `ODDS_API_KEY` | Unset | Live book quotes in Daily Edge; not needed merely to supply a manual price. |
| `ODDS_MAX_AGE_SECONDS` | `300` | Maximum age allowed by the Daily Edge quote gate. |
| `NBA_API_PROXY` | Unset | Full authenticated proxy URL for NBA Stats requests only. |
| `NBA_API_PROXY_VERIFY_SSL` | `true` | Keep certificate verification enabled unless intentionally configuring a trusted interception proxy. |
| `CORS_ORIGINS` | Localhost/127.0.0.1 on 5173 | Allowed browser origins for the three development API routes. |
| `LOG_LEVEL` | `INFO` | Logging verbosity. |
| `MODEL_VERSION` | `2.0.0` | Labels API responses and issued model snapshots; not an accuracy score. |
| `PREDICTIONS_DB_PATH` | `data/predictions.db` | Web API ledger location. |
| `LEDGER_WRITE_TOKEN` | Unset | Required for API ledger writes; unset disables those writes. |
| `PREDICT_RATE_LIMIT` | `20` | Per-client requests/minute to `/predict`. |
| `GAMES_RATE_LIMIT` | `60` | Per-client requests/minute to `/games`. |
| `CHEAT_SHEET_RATE_LIMIT` | `8` | Per-client requests/minute to `/cheat-sheet`. |
| `WEB_CONCURRENCY` | `1` | Gunicorn workers. |
| `WEB_THREADS` | `4` | Threads per Gunicorn worker. |
| `WEB_TIMEOUT` | `180` | Gunicorn worker timeout setting in seconds. |

Rate limits are process-local and keyed to the address Flask sees; they are
not a shared production-grade abuse-control service. Setting a route limit
to zero disables it. Request bodies are capped at 64 KiB.

Restart Flask/Gunicorn after changing loaded settings or application code.

### Production

`build.sh` installs backend requirements, runs `npm ci`, and builds
`frontend/dist`. Flask serves that build and confines asset-file lookups to
the build directory.

The `Procfile` runs Gunicorn with threaded workers, a 30-second graceful
timeout, and five-second keep-alive. Set the host's environment and persistent
database storage explicitly. A working local push does not establish that the
host has rebuilt/restarted successfully.

GitHub Actions defines separate backend and frontend jobs on pushes and pull
requests. Backend checks include dependency consistency and unit tests;
frontend checks include lint, TypeScript, and the production build.
There is no scheduled cache/grading job in that workflow.

## 12. API reference

The API paths do not have an `/api` prefix.

| Route | Used by | Response/purpose |
| --- | --- | --- |
| `GET /games?date=YYYY-MM-DD` | Daily Edge | Date and game objects with IDs, home/away teams, status and available timing. |
| `POST /predict` | Player Lookup | One projection; optional line/price analysis, context, and recording outcome. |
| `GET /cheat-sheet?team=BOS&date=YYYY-MM-DD&book=fanduel` | Daily Edge | Game, book, odds status, warnings, per-team diagnostics, generation/version data and projections. |
| `GET /health` | Operators | Lightweight process metadata only. |
| `GET /` and frontend assets | Production browser | Built React app. |

A valid empty schedule returns `games: []` with a message. Unknown teams,
players, or absent requested matchups have distinct errors. `GET /predict`
returns 405 because prediction requires POST.

### Example manual request

This demonstrates the schema; the date/matchup is illustrative and is not
claimed to be a verified scheduled game or an actionable recommendation.

```json
{
  "player": "Nikola Jokic",
  "opponent": "LAL",
  "date": "2026-09-04",
  "spread": -5.5,
  "line": 12.5,
  "over_odds": null,
  "under_odds": -115,
  "bookmaker": "manual",
  "matchup": null,
  "home_game": true,
  "record_prediction": false
}
```

`home_game: null` requests automatic schedule verification. Legacy
`odds` with `odds_side` remains accepted; it is not interpreted as both
sides' price. The default legacy side is Over.

With a line, `analysis` includes probabilities, evaluated side, nullable
recommended direction, prices/metrics, side evaluations, intervals, and
variance metadata. Without a line, `range` supplies numeric bounds.

`record_prediction: true` additionally requests recording and requires the
`X-Ledger-Write-Token` header to succeed. Viewing a successful response is
not proof a record was saved; inspect `recording.recorded` and its reason.

### Errors and compatibility

Responses use `error` and a machine-readable `code`. Typical categories
include 400 invalid input, 404 unresolved entity/game, 422 incompatible
venue/matchup/player context, 429 rate limiting, and 503 unavailable data/service.
Rate-limit responses include `Retry-After`.

The frontend distinguishes HTTP, network, timeout, canceled, and malformed
JSON failures. It accepts the current Daily Edge envelope and a legacy bare
array during compatibility handling. TypeScript types are not a complete
runtime schema validator for every upstream field.

## 13. Verification and known limitations

### What was previously checked

Before the September 7 interface simplification, the recorded local verification reported:

- **184 backend tests passed.**
- Frontend lint, TypeScript checking, and production build passed during the
  earlier work. Later recovery edits did not change the frontend.
- Two consecutive live manual Jokic requests completed with HTTP 200 using
  fallback data: approximately 11.2 seconds initially and 0.1 seconds cached.
  They remained diagnostic/ineligible, rather than being presented as verified
  live picks.
- NBA Stats still timed out from the development machine. Controlled tests
  exercised cooldown recovery; a healthy live-primary recovery was not thereby
  demonstrated.
- The GitHub push repair succeeded, with local and remote main synchronized
  at `0f0b903` before this README edit.

Those backend/live results are historical, not a live status monitor or proof
that every feature works. The September 7 display change passed its 12 new
frontend tests, lint, TypeScript checks, and production build. Browser smoke
checks use a separate mock-data preview, without NBA/odds calls. No backend
model code, real ledger data, or deployment was changed.

### Reproducing automated checks

```bash
python3 -m unittest discover -s tests -v

cd frontend
npm test
npm run lint
npm run typecheck
npm run build
```

The frontend build script itself includes lint and TypeScript checking.
The September 7 update adds 12 frontend tests using Node\'s test runner and
React server rendering via Vite. Run `npm test` in `frontend/`. These check
price/line pairing, reduced metrics, missing data, source/eligibility guards,
pushes, warnings, and both result entry points. They are not a full browser
end-to-end suite or a live-provider check.

Use the scoped `tests/` command. Standalone `test_predict.py`,
`test_predict_local.py`, and `test_proxies.py` have direct-execution guards.
`test_proxy_scraper.py` is a separate ad-hoc diagnostic that runs at top
level and can print proxy configuration; do not indiscriminately import/run
all root `test_*.py` files or share their raw output.

### What remains limited or unproven

- No guarantee of healthy NBA Stats connectivity on your machine or production
  host, and no evidence that a local timeout necessarily means a global outage.
- No complete offline/outage replacement for Daily Edge.
- No demonstrated profitable out-of-sample calibration or validated parlay
  correlation model.
- No complete historical injury/roster/quote archive; old-date projections
  are diagnostic, not fully replayable historical trading decisions.
- Injury scrapes can be stale/incomplete; the six-hour bounded stale exception
  and freshness-display caveats still apply.
- Manual quotes are trusted user inputs; provider-less timestamps can also
  limit Daily Edge freshness assurance.
- Individual matchup assignment is inferred, and some unavailable optional
  scouting data is silently neutralized rather than independently verified.
- “NO BET” can accompany a diagnostic expected return for a usable quote;
  positive numbers alone are not the actionability contract. Kelly remains
  in the API but is no longer displayed.
- Canceling a browser request does not cancel every backend side effect.
- A green process-health response or successful Git push does not prove
  deployment, upstream connectivity, browser behavior, or prediction accuracy.

## 14. Troubleshooting

| Symptom | Meaning / next check |
| --- | --- |
| “NBA Stats could not be reached” | Primary data and the required supported fallback path could not supply the request. Check host connectivity/proxy and logs; do not assume a worldwide outage. |
| Retry still uses ESPN | The primary circuit/fallback caches may still be inside their five-minute window. Recovery happens on a subsequent uncached request, not a background ping. |
| No games shown | It may be a genuine off-day/offseason date. A valid empty schedule has a neutral message; provider failures have an error/retry panel. |
| Auto venue fails | The exact opponent/date was not verified. An explicit venue can permit analysis only, not bypass live-pick eligibility. |
| Selected venue rejected | Available schedule evidence contradicts the chosen Home/Away value. |
| Daily Edge unavailable while Lookup works | Batch roster/advanced-data requirements are broader than the supported manual fallback. |
| No lines or EV | Check key/market availability in Daily Edge; in Lookup enter a line and side-specific prices. An absent quote is intentionally not replaced with -110. |
| Projection shown but NO BET | Read tier and limitations: price/sample/EV/variance, injury/source quality, quote age, or game state can block a recommendation. |
| Pick not saved | Read the recording reason; check token configuration, eligibility, priced tier, fresh pregame status and persistent database access. |
| Pending record never grades | Missing/ambiguous logs stay pending. Verify result/sportsbook settlement before explicit manual settlement. |
| Frontend build not found | Build `frontend/dist` with `npm run build` from `frontend/`, or use Vite during development. |
| Request timed out | The browser's wait limit was reached; this alone does not prove the backend stopped or the provider is globally down. |
| Git push rejected after amend | Published/local history may have diverged. Inspect history and reconcile it; do not blindly force-push. The documented incident was fixed with a preserving merge. |

This README is an explanation of the current implementation and recent work,
not a declaration that all defects or external-service failures are resolved.
