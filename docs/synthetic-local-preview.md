# Real-data / synthetic-odds local preview

Separate backend: `python3 -m scripts.synthetic_server` (127.0.0.1:5010).
Separate frontend, from `frontend`: set `NBA_BACKEND_URL=http://127.0.0.1:5010` and `VITE_SYNTHETIC_ODDS=true`, then run `npm run dev:local-account` with the existing local Supabase CLI configuration. Preview port is 5175; normal preview stays 5174.

Schedules, roster identity and player history are retrieved through the real loaders. A maximum of two players per team receive synthetic 5.5/8.5 rebound thresholds and -110/-115 prices. These are arbitrary interface-test values, not sportsbook observations. The test board only permits scheduled matchups. Synthetic quotes have explicit source provenance and no provider timestamp; generation cannot approve them as provider-backed picks. Preseason can require a manual minutes assumption.

The visible banner identifies synthetic odds. Saves are marked sample even with real local Supabase authentication. No hosted changes, real odds quota use, or production entrypoint changes are required. Generator subprocesses use the same test board. Importing the module for unit tests does not alter production endpoint functions.

Verified October 8: real BOS–CLE roster quotes loaded; Allen with manual 24 minutes completed using 56 prior regular-season appearances, estimating 7.501 rebounds. Output remained research-only with `quote_not_provider_verified`. Production build/lint/types passed; two synthetic-board tests passed. This is not verification of profitable or live sportsbook-backed picks.

Advanced analysis now includes accessible estimate-versus-line markers, probability bars, explicit minutes-scenario cards and expandable exact price calculations. Dedicated desktop/mobile checks passed and the mobile screenshot was inspected. Synthetic calculation cards explicitly say Sample analysis and permit saving a sample calculation snapshot without changing provider-backed recommendation eligibility.

Next acceptance task: connect this real-history synthetic calculation and player research to the real local-account browser persistence test; verify saved records keep their sample flag and model assumptions after re-login.

## Connected acceptance verified

The real local mobile browser test now supports `LOCAL_ACCOUNT_SYNTHETIC=1` with `LOCAL_ACCOUNT_BROWSER_URL=http://127.0.0.1:5175`. It requests a single Allen assessment with manual 24 minutes (no history or generation response mocks), opens the visual explanation, reads real prior-season research, saves the calculated sample, clears browser storage, signs in again and verifies source, sample flag, profile, projection, assumptions, analysis, notes and Void result. Temporary accounts are cleaned up. The first attempt failed on an incorrect test heading; correcting it to Prior regular season made the full test pass.

Usability improvements include explicit Sample analysis cards, a Save sample analysis action and accessible visual explanations with exact price calculations expandable. Synthetic provenance also forces sample status in the shared snapshot builder, not just the page UI. Normal provider-backed eligibility remains unchanged.

Speed: existing history/stat caches and bounded provider requests remain active. The connected real-history request completed in a few seconds on the documented warm local environment; earlier full historical model timing was 39.644 seconds cold/recovery versus 0.010550 seconds immediately warm. These are observations, not guaranteed latency. Repeated button requests, cancellation, partial history and targeted retry are exercised in browser regression tests.

Full verification: 381 backend tests; 36 desktop/mobile browser tests; production build, lint and types; frontend snapshot-provenance tests. Provider outage/empty coverage, no stale-response cross-game overwrite, minutes validation and sample/private-record persistence are covered. This local synthetic journey is complete; live sportsbook coverage and predictive validation are separate.
