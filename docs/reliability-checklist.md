# Local reliability work: verified and pending

This is a progress record, not a claim that all issues are fixed. Nothing in
this work authorizes or performs a Render/Vercel deployment.

## Current dashboard acceptance — October 7, 2026

The connected Picks & Lines, Player Research and My Picks implementation supersedes
the older UI described below. Current evidence: 372 backend tests, 101 frontend tests,
30 desktop/mobile checks, lint, TypeScript and production build pass. Dependency
audit reports zero vulnerabilities. Real local account persistence was verified
separately; deterministic browser fixtures do not establish live provider coverage.

The generator accepts explicit preseason minutes as research-only scenario inputs,
with fresh provider prices and verified pregame required for an experimental
candidate. It never promotes experimental output to the legacy actionable model.
Research failures and partial samples expose targeted retry. Quote freshness labels
expire locally without provider polling or extra credits.

See [local release acceptance](local-release-acceptance.md) for commands and exact
live checks. Remaining gates: actual offered rebound props/full-input live approval,
broader predictive evaluation, consenting beta participants, and separately authorized
hosted schema/deployment with durable shared quota storage. No local test establishes
those external outcomes.

## Historical reliability work

The entries below are dated earlier evidence, including references to the previous
Daily Edge/Player Lookup UI and work that was pending at that time. They are not the
current dashboard acceptance checklist.

## Verified locally

- NBA client default headers restored; completed-season real data retrieved.
- Individual historical Flask predictions returned HTTP 200.
- Full historical Daily Edge returned 21 rows in 75.39 seconds, partial and
  diagnostic-only. Odds calls were disabled for that test.
- Cooperative 75-second upstream allowance, thread isolation, teardown cleanup,
  bounded retry sleeps, partial roster handling, and budget warnings.
- Shared 60-second odds event discovery across games/books. Quote caching and
  stale-price gates are unchanged; event caching is tested with synthetic data.
- Player Lookup draft inputs persist in session storage, without results or
  credentials. Invalid or disabled storage fails safely.
- Cancelled/replaced UI requests cannot apply late results at the component
  update points. Browser interaction testing remains pending.
- League dashboard memory cache expires after 45 minutes rather than lasting
  indefinitely. Accepted offline dashboard loads also receive a retention timestamp.
- UI quote timestamps use provider update time, never substitute download time.
- Loading a saved snapshot no longer extends its original hard expiry; roster
  timestamps preserve snapshot age. Cache waiters honor their request allowance
  without cancelling the worker that owns the shared fetch.
- Malformed slate rows now produce a recoverable response error instead of
  reaching rendering code. Rest calculations use Eastern dates and reject
  same-day/future history as an observed back-to-back (marking fallback instead).
- Cache invalidation during an in-flight fetch no longer repopulates the cache
  with the invalidated result. Already-aborted UI requests never start a fetch;
  structured server errors fall back to a readable message.
- Calculated primary player statistics are reused for 60 seconds by player,
  opponent, date, and season, with defensive copies and provenance replay.
  Empty/degraded results are not retained; injury eligibility and recommendations
  are still recomputed. Real Jokic statistics: 0.422s first call, <0.001s repeat.
- Two historical Daily Edge requests in one process: the second returned HTTP
  200 with 33 rows in 13.31 seconds. It remained partial/analysis-only, with odds
  disabled. This is not a controlled cold-vs-warm speed guarantee.
- Slate processing prioritizes players with quoted markets without dropping the
  rest of the roster. Results have a refresh button and visible loaded-row count.
- Backend no longer fabricates quote update times from download times, and
  the route's freshness gate also rejects missing provider timestamps even when
  the download is recent. Regression tests cover stale and absent timestamps.
- Odds parsing explicitly filters the requested sportsbook. Malformed quote
  entries (including infinite prices, boolean lines and non-string player names)
  are skipped without losing valid quotes; malformed market containers surface
  as provider errors rather than appearing to be legitimate empty markets.
- Provider HTTP 429 stops immediate retries. Alternate odds-market requests
  occur only after HTTP 400/422, not authentication failures, rate limits,
  exhausted request budgets, or server outages. Status-bearing exceptions omit
  credentials and response bodies. Regression coverage verifies retry counts.
- Recognized preseason schedules are labeled, and both routes force analysis-only
  output for them. Historical ESPN verification identified five preseason games.
  See [preseason readiness](preseason-readiness.md) for the remaining modeling gaps.
- Separate preseason history and a read-only prior-season input audit are
  implemented; both samples were retrieved successfully for historical Jokic.
  The live projection formula has not been switched to an unvalidated blend.
- Optional walk-forward preseason baseline evaluation reports errors using only
  earlier appearances, with leakage/duplicate/schema tests. Real Jokic historical
  run evaluated three games; too small to establish predictive quality.
- Batch preseason audit supports repeated player arguments, reports unavailable
  samples, and pools errors by game. Three-player historical run evaluated 10
  games with primary data: exploratory MAE 2.096 vs naive 2.863, but worse for
  Curry. This is not sufficient validation to enable preseason recommendations.
- Preseason evaluation reports excluded rows and skipped-game reasons, rejects
  overlapping source samples, and normalizes IDs before duplicate checks.
- Batch audits distinguish empty histories from source failures and report
  partial player coverage alongside pooled error scores.
- Historical Player Lookup uses its as-of historical team before requesting
  current roster information, avoiding an unnecessary live dependency when
  historical team data exists. Current/future lookups retain the roster check.
- Daily Edge rejects malformed schedule rows and messages before rendering.
  Player Lookup rejects invalid core projection fields, and empty successful
  HTTP bodies produce recoverable API errors instead of null results.
- Isolated frontend tests disable unused dependency discovery to avoid background
  scan/shutdown errors; production dependency optimization is unchanged.
- Saved-pick mutations no longer return success after an account transition,
  including a sign-out/sign-in round trip during the post-write reload. Writes
  remain pinned to the initiating user; completed writes are not rolled back.
- My Picks distinguishes loading and failed retrieval from an empty account.
- Saved-pick rows are validated before cloud results reach the UI, sharing
  structural validation with offline demo storage. Invalid records cause a
  visible retrieval error; they are not silently dropped, deleted or rewritten.
- Matchup scouting skips the opponent profile request when no scouting inputs
  can use its position. Numeric-string contest percentages no longer crash the
  matchup narrative. Final composite safety refreshes preserve earlier
  restrictions and warnings instead of upgrading base eligibility.
- Preseason CLI deduplicates normalized names before retrieval and rejects blank
  names/invalid dates before loading configuration or making requests.
- NBA schedules reject missing identifiers, invalid/wrong dates, duplicate
  columns, and conflicting duplicate games instead of caching a corrupt slate
  as an empty day. Valid empty days and identical duplicate rows still work.
- Pregame verification rejects boolean/fractional/nonfinite status codes and
  malformed status text; invalid status keeps lookup results analysis-only.
- Cache keys preserve argument/container types, preventing a successful integer
  lookup from bypassing validation for a boolean input. First-use instance tokens
  are initialized under a shared lock to prevent duplicate concurrent cold loads.
- Frontend response guards validate nested safety flags, warnings, source/injury
  context and odds provenance, preventing malformed context from reaching the UI.
- Side-card probabilities and expected returns are tied to the evaluated side
  and rebound line; expected return additionally requires the same price.
  Explicit per-side lines support different Over/Under lines. Older responses
  without them can only reuse evaluations at the selected line, not another
  market line. Invalid side lines/probabilities are rejected at the API boundary.
- NBA HTTP 403/429 responses stop immediately rather than retrying in the same
  request. Endpoint cooldown survives budget exhaustion during retry backoff;
  a successful retry still clears it. This reduces unnecessary probes but does
  not guarantee access to NBA Stats.
- Historical hit-rate/sample gates exclude negative, boolean and fractional
  rebound observations. Valid zero counts and numeric-string whole counts remain
  supported, with the existing recency weighting and push handling unchanged.
- Quote normalization no longer promotes download time to quote-update time.
  A regression through the real Daily Edge projection pipeline verifies that
  download-only quotes reach the route as stale and non-actionable. Nested sides
  require their own price and cannot borrow a legacy Over price; invalid nested
  quotes do not fall back to resurrecting the flat quote. Shared lines and actual
  provider-update metadata remain supported, and boolean lines are rejected.
- Malformed explicit variance sample counts use the existing heuristic path
  (`heuristic_invalid_sample`) rather than receiving unknown-sample empirical
  weighting. Missing sample counts and valid integral counts retain their
  previous behavior; no variance parameters were recalibrated.
- Server eligibility reconciliation preserves explicit vetoes and warnings from
  metadata, freshness and top-level context. Degraded sources cannot be upgraded
  by an optimistic flag. Malformed metadata/freshness now retains diagnostic
  output instead of causing a route error or skipped player; no pick is issued.
- Recommendation validation rejects malformed numeric signals, fractional game
  counts and impossible win-plus-push probabilities without changing thresholds.
- Verified 2026-10-03: 280 backend tests pass. The last frontend verification
  passed 64 tests; lint,
  TypeScript, production build and diff checks pass. Tests use mocked providers;
  these tests do not establish live-provider or hosted readiness. The build
  still warns that its Browserslist compatibility dataset is out of date.

## Still pending

- Faster healthy and degraded full-slate loading; no hard wall-clock guarantee.
- End-to-end current-season slate with fresh real odds.
- Reuse complete statistical projections across book changes. Do not cache
  final recommendations blindly: spreads, injury freshness, live schedule,
  provenance and quote timestamps affect eligibility.
- Browser interaction checks for input restoration, cancellation, partial
  coverage, and account-switch saving. Database policy tests are not a live
  hosted-account verification.
- Early-season prior-year blending: requires explicit modeling, trade handling,
  data cutoff tests and historical validation; currently not implemented.
- Held-out calibration/performance evaluation with verified historical inputs.
- Persistent shared stats caching design within existing free storage limits.
- Finish reconciling older README change-audit sections with current behavior.
- Deploy only after explicit approval and local verification.

## Preseason research implementation (2026-10-04)

- Added a dedicated analysis-only roster/player flow. The UI does not send
  preseason games into the failing regular-season full-slate calculation.
- Current-season roster fallback uses ESPN with exact, unique NBA name-to-ID
  mapping and visible omission/provenance warnings; no current-roster fallback
  is allowed for older seasons. Cached fallback responses preserve provenance.
- Histories are fetched per selected player, independently bounded, with same-day
  cutoffs, no invented first-appearance minutes, and no picks/account writes.
- Real GSW–LAC rosters and Curry prior-season history loaded locally. This does
  not establish uninterrupted NBA availability, hosted readiness or model accuracy.
- ESPN preseason fallback requires an explicit matching season/preseason group,
  validates dates and statistics, and preserves source warnings on cached reads.
  Ambiguous provider responses remain unavailable rather than a verified empty
  season. A controlled NBA timeout plus live ESPN response retrieved Bam's
  October 3 appearance (13 minutes, 6 rebounds) successfully.
- The actual frontend fetch/validation code accepted both GSW–LAC and UTA–DEN
  local roster/player responses. Curry and Jokic had prior history but no earlier
  preseason appearances; manually entered 20-minute scenarios were labeled as
  assumptions. No automatic first-appearance minutes were supplied.
- Final local verification: 307 backend tests, 75 frontend tests, lint, TypeScript,
  production build and diff checks passed. Frontend tests run sequentially to
  avoid a stalled concurrent Vite module-loading test process. The compatibility
  dataset warning remains. Hosted deployment and interactive browser testing
  have not been performed.
- Subsequent feed integration adds independently fetched sportsbook rebound
  lines and five recent observed appearances. Fixed the odds league selection:
  preseason queries use `basketball_nba_preseason` for both event discovery and
  event odds, with caches separated from regular NBA queries. The corrected
  FanDuel GSW–LAC query found the game and LAC +2.5 but no rebound props.
  Available game spreads do not imply player props are offered. Timestamp-less
  quotes remain visibly unverified. Verification: 310 backend and 77 frontend
  tests passed, with production-build checks.

## External limitations

On 2026-10-04, tracing GSW–LAC with odds requests disabled found a roster
failure before any player was attempted: LAC timed out, and GSW encountered
the roster endpoint cooldown. The request failed in 45.83 seconds. The API now
distinguishes unavailable rosters and exhausted request budgets from a generic
source failure; this does not restore NBA access or implement preseason forecasts.
281 backend tests passed after this error-reporting change.

Local schedule check on 2026-10-03 returned Miami at Toronto directly from NBA
Stats, marked preseason and Final (game `0012600009`). A sandbox-only attempt
first failed DNS resolution; the network-enabled check succeeded. This verifies
schedule access, not a full live projection, fresh odds or hosted connectivity.

Local schedule recheck on 2026-09-21: the stricter parser accepted 10 games
for 2025-03-14 directly from NBA Stats in 0.37 seconds, including the provider's
midnight `GAME_DATE_EST` format. This verifies one historical schedule request,
not a live projection slate or Render/Vercel connectivity. No odds requests or
account writes were made.

Local recheck on 2026-09-17: the read-only Jokic audit for 2025-10-18
retrieved four preseason and 84 prior-season appearances from primary NBA
sources, with three evaluated games and no excluded input rows. This confirms
those historical endpoints worked for that request, not uninterrupted service
or hosted connectivity. No odds API calls or saved-pick writes were involved.

The same local session exercised `/predict` for Nikola Jokic versus LAL on
2025-03-14. An explicit away venue was rejected with `venue_mismatch`; automatic
venue selection returned HTTP 200 in 42.09 seconds, projection 13.47, and
`prediction_eligible: false`. Common-player-info and league-dashboard failures
caused ESPN/neutral-context fallbacks. Historical injury and completed-game
limitations also remained visible. This verifies a degraded historical route,
not fresh live recommendations or hosted readiness. Recording was disabled;
no market line or odds were supplied.

Follow-up historical lookup after the matchup-request optimization returned
HTTP 200 in 18.71 seconds, projection 13.27, still analysis-only. It reported
historical-injury/completed-game restrictions without the earlier source-failure
warnings. Different upstream availability means these two runs are not a
controlled speed benchmark, and their differing projections are not an accuracy
comparison. The later conservative safety-merge change is covered by local tests.

Current-day check on 2026-09-09: `/games` returned HTTP 200 with zero games
after ESPN fallback (8.23s; NBA scoreboard timed out). Existing Odds API key
successfully returned 41 upcoming events, starting October 20. This checks event
access only, not player props, quote freshness or end-to-end live recommendations.

Follow-up upcoming BOS/DET (2026-10-20), FanDuel lookup returned two player
rebound markets. The initial probe preceded the backend timestamp fix above;
its printed update time cannot be trusted as a provider timestamp. This verifies
market availability, not price freshness or a current-season recommendation.

NBA requests still time out intermittently. Akamai/IP blocking is not proven.
API-Basketball free access rejected recent-season history in the recorded probe.
No paid provider, proxy purchase, or fake-data substitution is used as a fix.
