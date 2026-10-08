# Preseason readiness

## Current local-first release work — October 4, 2026

The replacement dashboard connects Picks & Lines, Player Research and My Picks.
Its unified generator has explicit preseason/early/reduced-data scenario profiles;
these remain experimental and never set the legacy actionable flag. A preseason
calculation requires a qualifying prior regular-only sample (or a qualifying earlier
preseason sample) and observed earlier-preseason minutes or a manual 0–48 assumption.
The first appearance does not silently receive 30 minutes. Scenario probabilities
are assumptions, not calibrated predictive intervals.

Current live local checks loaded schedules and game-market prices successfully.
No rebound props were returned for the checked GSW @ LAC event. Historical NBA Stats
research succeeded; a historical regular-model calculation completed but was correctly
analysis-only because of source/context limitations. See the exact
[local acceptance record](local-release-acceptance.md).

The sections below retain earlier investigation/evaluation evidence and describe the
older interface; they are not a statement that the replacement has completed acceptance.
Earlier combined-season exploratory samples are not used as regular-only baselines in
the new generator. Hosted account migration and deployment are separate rollout steps.

The app is not yet a validated preseason betting model. It can be used to
inspect available data and diagnostic projections; a working UI does not prove
projection accuracy or profitable odds comparisons.

## Implemented

- Selecting a preseason game in Daily Edge opens **Preseason Player Research**
  rather than running the regular-season full-slate model. The separate sportsbook
  section fetches actual rebound lines when offered; it cannot issue or save a pick.
- Sportsbook prices load independently of rosters and histories. Unconfigured
  feeds, absent markets and provider failures are distinct states. Each side keeps
  its own line and price, with quote freshness based on the provider timestamp.
  Player research remains available when a game has no supported props.
- Observed history includes the five latest eligible appearances with dates,
  minutes and rebounds, excluding the selected game date and later games.
- Rosters load before individual histories. NBA roster requests have a shorter
  analysis timeout and a current-season ESPN fallback. ESPN names are matched
  uniquely to NBA IDs; unmapped entries are omitted with a visible count.
  Historical seasons cannot borrow the current ESPN roster.
- Selecting a player loads prior-season and earlier-preseason observations
  separately. Empty history and failed retrieval have different states. Same-day
  and future games are excluded, including when inspecting a completed game.
- If NBA preseason history fails, ESPN can supply an explicitly identified
  preseason sample for that same season. Source warnings stay visible. Missing
  preseason schema cannot be interpreted as proof of an empty history.
- Optional minutes scenarios multiply the prior-season observed rebound rate by
  an explicitly entered minutes assumption (0–48). Without a manual assumption,
  an estimate requires earlier preseason appearances and uses their last-three
  average minutes. First appearances do not receive invented minutes. No win
  probabilities, odds edges, or validated prediction intervals are claimed.
- Both paths are experimental: roster presence is not injury/availability
  confirmation; changed roles, trades, coaching decisions and matchups are not
  modeled. Regular-season Player Lookup and Daily Edge retain their existing model.

- Separate `get_preseason_player_gamelog` loader, isolated from regular-season
  history caches, with exclusive as-of cutoffs and analysis-only metadata.
- Read-only audit: `python3 -m scripts.check_preseason --player "Nikola Jokic" --date 2025-10-18`.
  It prints preseason and prior-season summaries separately; no files, picks,
  deployments or odds calls are written/performed. Prior history includes regular
  season, play-in and playoffs, matching the existing baseline definition.
- Real historical audit succeeded: four preseason appearances (21.5 minutes,
  7 rebounds/game) versus 84 prior-season appearances (37.36 minutes,
  12.74 rebounds/game). These are sample summaries, not predictive validation.

- Recognized NBA/ESPN preseason schedules carry a preseason flag.
- Daily Edge labels preseason games before loading projections.
- Both prediction routes disable actionable recommendations for recognized
  preseason games, even when the underlying model reports eligible inputs.
- Historical ESPN verification for 2025-10-10 identified five preseason games.
- Existing time budgets, partial-result warnings, price freshness and source
  safeguards remain enabled. No previous-season substitution is hidden.

## Required before preseason recommendations

### Generator-aligned exploratory evaluation (October 7)

Use `python3 -m scripts.check_preseason --player "Nikola Jokic" --date 2025-10-18 --evaluate --scenario-profile`.
This explicit mode retrieves regular-season-only prior history and uses the
generator's prior-sample thresholds, eligible preseason fallback, and bounded
three-scenario minutes expectation. The older command without this flag remains
a legacy diagnostic, not an evaluation of the replacement generator.

The real October 7 check retrieved four preseason and 70 prior regular-season
appearances from NBA Stats. Three later games were evaluated; the first was
skipped. MAE was 1.165 rebounds, RMSE 1.334, and bias -0.777; the prior per-game
baseline MAE on those same three games was 5.076. This selected single-player
sample is exploratory, not a chronological untouched holdout or probability
calibration result. No parameters, recommendation gates or odds were changed.
No profitability conclusion follows from these errors. Broader evaluation,
date-correct historical availability/rosters, and real beta feedback remain gaps.

### Exploratory evaluation command

`python3 -m scripts.check_preseason --player "Nikola Jokic" --date 2025-10-18 --evaluate`

The optional evaluation compares prior-season rebound rate multiplied by the
last three earlier preseason appearances' mean minutes against a naive
prior-season per-game average. It reports MAE, RMSE, bias and game-level errors.
It skips the first preseason appearance and excludes DNPs. Target-game minutes
and rebounds are never used to construct that game's prediction. NBA `Game_ID`
and `GAME_ID` spellings are both supported; duplicate game IDs are rejected.
IDs are whitespace-normalized, blank IDs are excluded, and overlap between the
prior-season and preseason samples is rejected. Reports include input, usable
and excluded row counts for each sample. Skipped usable appearances have reason
counts (no earlier preseason appearance and/or no earlier prior history); reasons
can overlap, so their sum need not equal the number of skipped games. Excluded
rows include DNPs and malformed inputs, not only unavailable games.

The historical Jokic run successfully evaluated three games from four available
appearances. This tiny exploratory sample is not held-out validation, does not
include historical injuries/rosters, and is not grounds to enable recommendations.

### Expanded exploratory run (2026-09-15)

Repeat `--player` to evaluate a batch, for example:

```sh
python3 -m scripts.check_preseason --player "Nikola Jokic" --player "Stephen Curry" --player "Bam Adebayo" --date 2025-10-18 --evaluate
```

Batch reports identify evaluated player counts, partial coverage, and reasons
for unavailable samples. A valid empty history is distinct from a source outage
or malformed inputs. Pooled error scores cover evaluated games only; even
`all_players_evaluated` means each player contributed at least one game, not that
every scheduled game or appearance was evaluated.
Repeated names differing only in case, spacing, accents or periods are audited
once to avoid duplicate weighting and redundant requests. Blank player names and
invalid dates fail before source requests. Different aliases for the same player
are not guaranteed to deduplicate; use full player names.

All six source histories returned primary NBA data. No player failed retrieval.
The first appearance for each player was skipped; 10 subsequent games were
evaluated. The baseline and parameters were not changed after inspecting results.

| Player | Evaluated games | Minutes-adjusted MAE | Prior per-game MAE |
| --- | ---: | ---: | ---: |
| Nikola Jokic | 3 | 1.204 | 5.071 |
| Stephen Curry | 3 | 2.339 | 0.852 |
| Bam Adebayo | 4 | 2.583 | 2.714 |
| Pooled games | 10 | 2.096 | 2.863 |

MAE is mean absolute rebound error, not a win rate. Pooling weights games,
not players. Curry's result was worse with the minutes-adjusted baseline.
These three selected stars in one preseason are not representative validation;
no recommendation gates were relaxed. Broader roles, multiple years and a
separate untouched holdout are still required.

### Remaining gates

1. Validate a preseason forecasting workflow. The separate research screen is now
   connected to diagnostic histories, but is not a validated betting model.
   Existing regular-model routes still use regular season, play-in and playoffs.
2. A declared prior-season baseline and date-correct roster/trade handling.
   Opening-season empty history must not be treated as a source outage.
3. A preseason minutes assumption users can inspect, with uncertainty for
   coach decisions and limited appearances; ordinary season averages alone
   are not validated for this use.
4. Historical preseason evaluation with inputs available before each game.
   Report sample size and prediction error. Do not infer betting profitability
   from rebound prediction error or invented historical prices.
5. Live checks once a slate exists: schedule, rosters, player histories,
   injury/availability information, actual quote timestamps, and account saving.
6. Hosted verification separately from local verification, after approval.

## Practical use until those gates pass

### Local research-mode check (2026-10-04)

The new roster route retrieved 21 players on each GSW–LAC roster in 0.44 seconds
from NBA Stats. Curry's player route retrieved 45 prior-season appearances and
zero earlier preseason appearances in 0.92 seconds. An explicitly supplied
20-minute what-if assumption produced 2.27 rebounds from that observed prior
rate. This was not an automatic forecast or recommended bet. No odds or account
writes were involved. These local timings are one successful check, not an
availability or speed guarantee for other requests or hosted deployments.

After connecting the sportsbook section, a live FanDuel GSW–LAC query returned
no matching player markets in 0.22 seconds because it used the regular NBA
sport key. The Odds API publishes preseason separately as
`basketball_nba_preseason`; both preseason odds routes now select that key.
The corrected live check found the game in 0.29 seconds and returned LAC +2.5,
but no player rebound props at FanDuel. The screen distinguishes available game
spreads from unavailable player props. This does not verify other books/dates.

### Opening-day local check (2026-10-03)

NBA Stats returned Miami–Toronto as a completed preseason game. A read-only
Bam Adebayo audit with exclusive cutoff `2026-10-04` retrieved one preseason
appearance (13 minutes, 6 rebounds) and 74 prior-season appearances, both from
primary NBA data. The next-day cutoff includes the completed opening game for
inspection; it is not a pregame prediction. The exploratory evaluator correctly
skipped that first appearance because no earlier preseason minutes existed.
Zero games were evaluated, so this check provides no accuracy estimate.
No odds requests, saved-pick writes or deployment were performed.

Use the preseason research screen for separate observed histories and explicit
minutes scenarios; use historical Player Lookup to inspect the regular model.
Unavailable sources or missing histories remain visible rather than fabricated.
Saved picks are
bookmarks/manual records, not placed bets. Do not interpret unavailable or
unverified data as a confident OVER/UNDER recommendation.
