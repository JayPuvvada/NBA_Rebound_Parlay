# Local reliability work: verified and pending

This is a progress record, not a claim that all issues are fixed. Nothing in
this work authorizes or performs a Render/Vercel deployment.

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
- Backend: 239 tests passing. Frontend: 41 tests passing; production build,
  TypeScript and lint passed, including explanatory copy and cancellation guards.

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

## External limitations

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
