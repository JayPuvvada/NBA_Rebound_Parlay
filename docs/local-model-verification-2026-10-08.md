# Local calculation verification — October 8, 2026

These are real-data diagnostic checks, not live sportsbook recommendations or predictive validation. No selections were saved and no deployment or hosted migration was performed.

## Established regular-season calculation

Called the running local `POST /predict` endpoint with Nikola Jokić versus SAS, target date April 12, 2026, away venue, manual spread 0, manual line 12.5, and manual Over/Under prices -110. The schedule matched a completed DEN–SAS game.

The full model returned estimated rebounds 12.81, estimated minutes 35.9, and 64 pre-cutoff observations. Input provenance was `stats.nba.com`, status `primary`, with no reduced-data input limitations. Pace, rebound environment, matchup and dispersion components were populated. Both sides were evaluated separately: Over probability 0.506636, Under probability 0.493364; neither cleared the supplied price. The result was NO BET, actionable false.

Historical injuries were deliberately disabled; current injuries must not leak into a historical calculation. Completed-game eligibility remained false. Prices and spread were test inputs, not historical sportsbook observations. Cold retrieval took tens of seconds; this is not a verified latency target.

## Early-season calculation

Called the shared `assess_player` service for Jokić with target October 20, 2026, a hypothetical DEN–SAS context, manual 34 minutes, line 12.5 and -110 prices. No sportsbook event or actual opening-night matchup was asserted.

Current regular-season history was empty. Prior 2025–26 history loaded 65 appearances and 2,265 minutes, with 0.369095 rebounds per minute. The `early_regular` profile used prior history with current weight zero and 30/34/38-minute scenarios. Estimated rebounds were 12.549. Manual assumptions and unmodeled factors were explicit. The unverified matchup and manual quote remained non-actionable; no candidate was fabricated.

## Regression checks and fixes

`python3 -m unittest tests.test_pick_generator tests.test_features tests.test_model tests.test_projection_safety -q`: 82 tests passed. These cover profile boundaries, prior requirements, minutes scenarios, zero-count and push handling, full-model veto preservation and eligibility. The repository uses unittest; pytest is not installed in the system interpreter.

No confirmed calculation regression was found in these checks, so model rules were not changed. This verifies one real full historical calculation and one real-history early-season scenario, not every player, live fresh-price generation, or hosted availability. Rebound quote coverage remains a separate provider dependency.

## Additional coverage and player checks

A fresh October 8 BOS–CLE preseason rebound request matched the provider event but returned no quotes for FanDuel, DraftKings or BetMGM. It was not a cached response. Live sportsbook-backed generation remains unverified.

Verified April 8 completed matchups before submitting additional manual-price diagnostics:

| Player | Verified matchup | Estimate | Earlier observations | Input status |
| --- | --- | --- | --- | --- |
| Jarrett Allen | ATL at CLE | 9.10 | 55 | Degraded / ESPN fallback |
| Rudy Gobert | MIN at ORL | 11.43 | 76 | Degraded / ESPN fallback |

Both calculations completed, but league matchup dashboards were unavailable and adjustments were neutralized. Both outputs explicitly remained diagnostic-only and non-actionable. These results narrow the earlier successful Jokić finding: primary NBA Stats inputs are not reliably available for every calculation. Positive manual-price calculations did not override the safety gate.

For today's actual BOS–CLE schedule context, Allen's real prior-season history loaded. No earlier preseason observations caused `minutes_required`; supplying manual 24 minutes produced 7.501 expected rebounds. The manual quote was rejected for provider-backed recommendation with `quote_not_provider_verified`, actionable false. This is a scenario calculation, not confirmation Allen will participate.

Additional regression command: `python3 -m unittest tests.test_pick_generator tests.test_markets tests.test_projection_safety -q` — 62 tests passed. No provider coverage, historical injury record, or missing primary matchup data was fabricated.

## Five-area follow-up

Added `python3 -m scripts.check_model_inputs --date 2026-04-08 --budget 35`, a bounded input diagnostic that prints exception types rather than provider URLs or secrets. All three team dashboards (base, advanced, opponent) returned 30 rows. Cold reads took 2.135, 2.320 and 1.839 seconds respectively; same-loader repeat reads were equal and rounded to 0.000 seconds. This confirms local cache reuse, not a whole-request latency target or cross-process cache. The earlier failures are intermittent; their exact network cause remains unproven.

Cache/data-loader regression suite: 79 tests passed. Frontend: 101 tests passed; lint, type checking and production build passed. Empty preseason quotes now explain limited coverage separately from NBA statistical-data errors.

Remaining acceptance: broader repeat live-input checks, warm end-to-end timing, and browser-level account journey. Fresh regular-season prop generation still depends on offered provider quotes. No paid service or hosted rollout was used.

### Subsequent verification

The real local mobile Chromium account journey passed: save a fixture rebound selection, sign out, clear local/session storage, reload and sign in, retrieve the selection, persist notes and Void grading. Auth and REST were real local Supabase; only schedule/quote inputs were fixtures. API checks also confirmed duplicate prevention, immutable prices, cross-account/anonymous denial and deletion. Temporary test users and records were cleaned up; existing/hosted accounts were untouched. Desktop/mobile regression suite: 32 passed.

Repeating the Allen April 8 historical calculation recovered primary NBA Stats inputs with no degraded-input limitations, producing 9.02 rebounds. First measured recovery request took 39.644 seconds; immediate same-input repeat took 0.010550 seconds with the same projection and primary provenance. This is one local warm-cache measurement, not a production latency percentile. The earlier 9.10 diagnostic estimate used neutral fallback context, so its difference is explained by different source inputs, not a frozen model-output regression. No current injury information was applied to historical analysis.

Next: broader input/cutoff recovery checks and diagnostic script tests; provider transport intermittency and live fresh-quote eligibility remain unproven. No Supabase cache architecture is needed to achieve the measured same-worker reuse.

### Recovery and diagnostic regression follow-up

Gobert's verified April 8 MIN–ORL calculation recovered primary NBA Stats provenance, no degraded-input limitations, and estimated rebounds 11.30. Historical eligibility correctly remained disabled. Allen and Gobert now both have observed degraded and recovered primary-input runs; this proves recovery is possible, not uninterrupted provider reliability.

Four diagnostic tests cover same-cutoff repeat requests, empty frames versus availability, safe exception-cause reporting with later checks continuing, and unequal repeat frames. Complete backend suite: `python3 -m unittest discover -s tests -q` — 379 tests. Use `-s tests` to avoid importing root-level ad-hoc network probes during test discovery.

| Requested area | Current evidence | Remaining boundary |
| --- | --- | --- |
| Investigate missing NBA inputs | Team dashboard diagnosis and Allen/Gobert recovery; endpoint-local cooldowns and fallback provenance already tested | Exact remote timeout cause cannot be proven from successful retries; future outages remain possible |
| Broader player/matchup cases | Real Jokić, Allen, Gobert historical checks; real Allen preseason scenario; fixture tests for out/missing-history/early-season gates | Not every NBA player or matchup has been live-tested |
| Repeat loading speed | Same-cutoff team reads reused; full Allen repeat 39.644s then 0.010550s | Single-worker sample, not a percentile or cross-process cache guarantee |
| Private saving journey | Real local mobile login/save/storage clearing/relogin/notes/Void plus ownership/immutability/deletion checks | Quotes were fixtures; live prop feed absent |
| Unavailable states | Dedicated preseason coverage wording, statistical errors separate; 32 desktop/mobile journey checks | No guarantee preseason props will appear |

No safe code change can guarantee external NBA endpoint availability or create sportsbook quotes. The verification scope remains explicitly local, with no deployment, paid dependencies or hosted account changes.

Dedicated desktop and mobile browser tests now verify that empty preseason quote coverage displays the limited-coverage explanation and disables generation, while a subsequent provider outage replaces it with the provider-unavailable message. Both checks passed. This adds two checks to the existing 32-check browser suite; no live quotes are claimed by these fixtures.
