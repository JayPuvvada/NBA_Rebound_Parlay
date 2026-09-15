# Preseason readiness

The app is not yet a validated preseason betting model. It can be used to
inspect available data and diagnostic projections; a working UI does not prove
projection accuracy or profitable odds comparisons.

## Implemented

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

1. Connect the separate preseason diagnostic loader to a validated forecasting
   workflow. Existing projection routes still use regular season, play-in and playoffs.
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

Use historical Player Lookup to inspect model behavior. During preseason,
expect analysis-only results or a missing-history message. Saved picks are
bookmarks/manual records, not placed bets. Do not interpret unavailable or
unverified data as a confident OVER/UNDER recommendation.
