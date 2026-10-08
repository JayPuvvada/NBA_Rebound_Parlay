# Local release acceptance — October 4, 2026

This record separates functioning code, deterministic tests, and live provider coverage.
It must not be used as proof of predictive profitability.

## October 8 rebound-only usability revision

Owner feedback led to removing game-market tabs and Compare 3 books from the main
page. Old game-market links now load rebounds. Rebound analysis replaces Model picks;
generation requires offered lines for the selected book, with an explanation and
manual research shortcut when absent. The sportsbook selector remains, without a
comparison feature. Rebound stale/unknown price safeguards, account saving, existing
non-rebound records and internal/operator market functionality are preserved.
101 frontend tests, lint/types/build and 32 desktop/mobile checks pass. The browser
tests cover missing-line generation guidance, old links, book switching and retained
research/saving journeys. Owner follow-up usability results are not yet collected.

## October 5 follow-up: real local accounts verified

Docker's engine is now running. The persistent local Supabase stack started and
applied all three migrations locally. Hosted settings/database/accounts were untouched.

Real auto-confirm local signup and Auth/REST checks passed: save and new-client retrieval, duplicate prevention,
notes/Void, foreign-owner read/insert denial, immutable-price denial, anonymous-read
denial, and deletion. A real mobile browser also passed sign-in/save, sign-out,
browser-storage clearing/sign-in, notes/Void and reload persistence. Only market data
was a fixture in that browser test; authentication and database calls were real/local.
Temporary local users and their records were removed after verification.

Local Supabase security advisors reported no warning/error findings. Runtime-only
npm audit reported zero vulnerabilities; the five Tailwind development-chain findings
remain, pending a separately tested breaking tooling migration.

Live October 5 schedule returned five preseason matchups. One bounded MEM @ ATL
rebound request returned no offered quotes across the three books, reconciled at
zero credits. This is not verification of a live quoted model pick.

Separate local-account preview: `http://127.0.0.1:5174/#picks`. Local accounts are
different from hosted accounts; existing hosted credentials are not transferred.
The old 5173 preview does not automatically switch to the local database.

From `frontend`, with `LOCAL_SUPABASE_CLI` pointing to your installed CLI:
`npm run dev:local-account` starts the separate preview without overwriting `.env`.
`npm run test:local-account` runs real API acceptance. Set
`LOCAL_ACCOUNT_BROWSER_URL=http://127.0.0.1:5174` to include the real browser flow.

## Verified so far

- Backend: 364 tests pass, including 28 market/cache/quota tests. Legacy transport
  fixtures disable budget enforcement; quota-specific tests explicitly enable it.
- Frontend: 93 tests pass, including PostgreSQL/PGlite migration, cross-account
  ownership and immutable-column checks. Lint, typecheck and production build pass.
- Browser: 14 desktop/mobile fixture checks pass, including manual save, sign-out,
  browser-data clearing/sign-in, notes/Void, threshold changes, keyboard navigation,
  stale refresh and old-game response cancellation. These fixtures are not real Auth.
- Actual cached live-price layouts were visually inspected at 1440px and 390px with
  no page overflow. [Desktop](screenshots/local-lines-desktop.png) and
  [mobile](screenshots/local-lines-mobile.png); quote timestamps/staleness are visible.
- Real local schedule: GSW @ LAC and UTA @ DEN returned for October 4, marked preseason.
- Real local game markets: FanDuel and DraftKings returned spreads, moneylines and totals
  for GSW @ LAC. BetMGM did not return these markets in that response.
- Real rebound check: the provider returned an empty quote list for that event.
  This does not verify live rebound generation; it is an explicit coverage gap.
- These live checks reserved/reconciled three credits; no bets, ledger writes,
  hosted migrations, deployment or new subscriptions were performed.
- Real historical research: Nikola Jokic before April 1, 2026 returned 60 earlier
  2025–26 regular-season appearances and 70 prior-regular-season appearances from
  `stats.nba.com`, with observed minutes/rebounds and recent samples. This run worked
  locally; it does not establish Render connectivity or future availability.
- Experimental probability helpers completed a conditional calculation using that
  observed rate and explicitly manual 25-minute/8.5-line assumptions. This is not a
  provider-backed candidate, a current-season baseline, or predictive validation.
- Existing regular-season `/predict` completed with real historical inputs for
  Jokić versus Utah before April 1, 2026: estimated rebounds 13.78. Manual odds,
  historical injury gaps and degraded ESPN/neutral adjustment inputs correctly kept
  it analysis-only (`prediction_eligible=false`, `actionable=false`). The initial
  incorrect manual venue was rejected; automatic venue resolution succeeded.

## Dependency checks

Latest local follow-up: 372 backend tests, 101 frontend tests and 30 desktop/mobile
checks pass; lint, types and production build pass. The final browser command was
`npm run test:e2e -- --workers=1` (30 passed in 25.6s).
Earlier browser runs had intermittent action timeouts; the isolated mobile journal
passed three repetitions, and the final complete sequential run passed. A fixture
race was corrected by awaiting grading completion before simulating a remote edit;
freshness clock tests now allow a realistic initial-load margin.
Research now distinguishes valid empty samples from unavailable/partial history,
including HTTP 200 failure payloads. Available samples remain visible alongside a
specific explanation and retry; unverified player identity is not presented as
normal empty history. Tests cover partial, all-failed, valid-empty and recovery states.
Generator contract correction: explicitly entered minutes can now support a
qualifying experimental candidate with fresh provider quotes and verified pregame
context, including the first preseason appearance. Previously the backend vetoed
all manual-minute candidates, contradicting the approved first-game workflow.
Regression checks retain visible manual assumptions, `actionable=false`, no legacy
direction/Kelly promotion, and rejection of manual/stale prices. This is deterministic
functional evidence, not verification of currently offered rebound props or accuracy.
Quote freshness labels expire after five minutes via a local timer, including
research and generated-result quote details. Unknown timestamps stay unknown,
and stale/unknown provider statuses are never promoted. Browser clock tests verify
expiry without any extra market fetch; no polling or provider credits are used.
Targeted history retries now use the edited line/competition instead of restoring
the original selected quote; desktop and mobile regression journeys cover this.
Schedule responses retain ESPN's absolute start time. Initial selection chooses
the earliest scheduled game with a known absolute tipoff, preserves an explicitly
selected matchup, and does not guess times from date-only/display strings.
Unknown times retain source ordering when no scheduled tipoff is known.

Approved local migration: Tailwind and `@tailwindcss/vite` are pinned to 4.3.3.
The legacy theme config is explicitly loaded; the class-based dark variant is retained.
Obsolete direct Autoprefixer was removed because the new plugin handles prefixing.
Full network-enabled `npm audit --json` now reports **zero vulnerabilities**, including
development dependencies. Lint, TypeScript, production build and all 99 frontend tests
pass. The earlier seven-finding audit below is historical, not the current state.
All 22 desktop/mobile browser checks and 371 backend tests also pass after migration.
Desktop/mobile fixture screenshots were visually inspected: the dark/emerald theme,
legible cards, control spacing and single-column mobile layout are preserved.
Screenshots are generated under ignored `frontend/test-results`, not substituted
for the earlier real-provider evidence. The initial PostCSS integration emitted a
development `from`-option warning. Switching to Tailwind's native Vite integration
removed that warning; the production build and all exercised browser styles pass.
No hosted changes or deployment occurred. Browser minimums follow the
[Tailwind upgrade guide](https://tailwindcss.com/docs/upgrade-guide).

Earlier refresh: `source-map-js` was updated compatibly to patched 1.2.2 for
[GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q).
That full npm audit had seven development-only findings (five high and
two moderate), including the newly reported selector-parser issue
[GHSA-rj75-hqrm-r3gf](https://github.com/advisories/GHSA-rj75-hqrm-r3gf).
Runtime-only audit remains clean. Full remediation still requires a separately
tested Tailwind/toolchain migration; no forced major upgrade was applied.
The five-finding count below records the earlier check, not the latest audit.

Compatible security updates reduced the npm audit findings from 16 to five high
findings in the existing Tailwind 3 development dependency chain. The suggested
automatic fix requires a breaking Tailwind 4 migration; it was not applied blindly.
The development server is bound to loopback. These remaining advisories still need
review before exposing development tooling to untrusted input.

## Acceptance gates

Fresh October 7 follow-up: one metered MIN–IND preseason rebound refresh returned
HTTP 200, matched the event, and returned zero quotes across all three books.
Cycle usage stayed at 6, provider remaining 492; the empty check added zero credits.
`scripts.check_markets` now provides a reproducible, credential-safe single-board
coverage command with explicit refresh and enforced quota accounting. It never
generates or saves a pick and never treats an available spread as live rebound approval.
The command was verified against the cached real response; all 375 backend tests pass,
including coverage reporting, honest empty/stale output and credential omission.

- Resolved: actual local Supabase Auth/REST, verified October 5, as above.
- Live provider-backed rebound pick: no rebound props returned for the checked event.
- Full-input eligible regular pick: the historical calculation completed with
  degraded inputs, not a live primary-model approval.
- Resolved: development-chain advisories, by the approved local migration above.

No hosted database upgrade or deployment was performed. An older hosted schema
permits legacy reads; new selection saves show a specific upgrade-required message.

## Running the current source locally

Backend: `FLASK_APP=app python3 -m flask run --port 5002 --no-debugger --no-reload`.
Frontend, from `frontend`: `NBA_BACKEND_URL=http://127.0.0.1:5002 npm run dev -- --host 127.0.0.1`.
Open `http://127.0.0.1:5173`. The alternative port avoids replacing an older server
that may already occupy 5001. Restart Flask after backend edits when reload is disabled.

Keep keys in ignored environment files. Do not copy secrets into links or screenshots.
Account settings and local Supabase instructions are in `docs/private-account.md`.

## Remaining distinctions

### Latest local audit (October 7)

- Schedule retrieval returned five October 7 preseason matchups. A bounded
  MIN–IND rebound check matched the game but returned zero quotes for all three
  books, reconciled at zero credits; live rebound approval remains unverified.
- Patched source-map-js to 1.2.2; 99 frontend tests, lint, types and build passed
  afterward. Runtime npm audit has zero findings. Seven development findings
  remain, awaiting the requested decision on a breaking tooling migration.

- Partial retries preserve unresolved players when a retry returns no replacement,
  along with completed assessments; a desktop/mobile regression covers this case.
- Shared links and history rows reject impossible calendar dates rather than
  allowing JavaScript date normalization to accept them.
- All 99 frontend tests, 20 desktop/mobile workflow checks, lint, TypeScript and
  production build passed for these changes. Two additional desktop/mobile
  checks passed for 44px primary controls, reduced motion, and keyboard skip
  navigation (22 browser checks total, run in these two groups).

- Added opt-in `--scenario-profile` evaluation using regular-only prior inputs
  and the generator's preseason thresholds/scenario expectation; legacy mode
  remains unchanged. Chronological cutoffs, qualifying-history fallback and
  skipped-game coverage have regression tests.
- Real Jokić 2025–26 preseason audit retrieved four appearances and 70 prior
  regular appearances, evaluated three and skipped one; MAE 1.164833, RMSE
  1.333928. This selected exploratory sample is not predictive validation.
- All 371 backend tests passed after this addition. No odds or account writes
  were performed by the historical audit.

- Quote decoding rejects mismatched event IDs, league keys, unrelated teams,
  and a generated assessment carrying another player's or non-rebound quote.
- Generator quote grouping uses one canonical subject spelling for equivalent
  provider names, preserving each side's actual line and price.
- Exploratory evaluation now excludes boolean minutes/rebounds, fractional
  rebound counts and malformed minute clocks, consistent with observed research.
- 97 frontend tests and all 18 desktop/mobile fixture browser checks passed;
  lint, TypeScript and production build passed. All 368 backend tests passed
  after the canonical-name regression addition.
- No new provider calls, hosted migration, deployment or paid dependency was
  used in this audit. Live quoted rebound approval, predictive validation and
  six-person usability findings remain unproven.

### October 5: real-market local journey follow-up

Saved-note editors now follow refreshed saved values after successful saves,
while preserving and visibly flagging unsaved drafts when another session changes
the note. Desktop/mobile journal tests cover accepting the refreshed saved note.
The research response decoder also rejects contradictory above/below/push counts
and frequencies larger than the observed history instead of displaying them.

Injury safeguard review corrected the generator's loader-status mismatch:
current reports use `available`, not `fresh`. It now requires an explicit
non-stale, timezone-aware report timestamp within the 20-minute cache lifetime
(at most five minutes of future clock skew). Old, malformed, degraded or
unverifiable reports yield unknown availability rather than a current Out claim.
Questionable/probable entries also remain unconfirmed participation. Regression
cases cover these boundaries. This does not add an official injury or lineup feed.
An additional bounded Denver–Utah preseason rebound check returned zero quotes;
provider-backed live rebound generation remains unverified.

Subsequent bug review fixed comparison-scope empty states, whitespace/selection
search, and provided a filter reset. It also fixed cancelled research not
restarting after leaving the page and returning. All 18 desktop/mobile fixture
browser checks passed, including late-game responses, failed refresh retaining
stale quotes, keyboard navigation, threshold changes, and research cancellation.
Fixture browser results are separate from the real-market/account check below.

- `/games` returned tomorrow's four preseason matchups.
- Memphis at Atlanta game markets returned 12 cached real-provider quotes across
  FanDuel and DraftKings (moneyline, spreads, totals); stale timestamps remained
  visibly stale. BetMGM was absent from this response.
- Brooklyn at Charlotte rebound markets returned no quotes; generation returned
  `no_quotes`, zero evaluated players, and no fabricated assessments.
- Jokić research retrieved NBA Stats observations: one earlier 2026–27 preseason
  appearance and 65 prior 2025–26 regular-season appearances, separately labelled.
- `LOCAL_ACCOUNT_LIVE_MARKETS=1` extends the local account acceptance script:
  a narrow mobile browser used actual backend markets, saved an Atlanta moneyline,
  signed out, cleared browser storage, signed in again, and retained the snapshot,
  notes and Void result. Auth/REST were real local Supabase; no market fixtures
  were used in this mode. Temporary test accounts and records were removed.
- Backend: 364 tests passed. Frontend: 93 tests passed; lint, type checking and
  production build passed. No hosted migration or deployment was performed.

Run the additional real-market check from `frontend` with
`LOCAL_ACCOUNT_LIVE_MARKETS=1 LOCAL_ACCOUNT_BROWSER_URL=http://127.0.0.1:5174 npm run test:local-account`
and `LOCAL_SUPABASE_CLI` pointing to the installed CLI when it is not on PATH.
This dated live acceptance requires available FanDuel Atlanta moneyline quotes;
it is not a deterministic CI test or a claim that these prices remain current.

- Browser fixtures demonstrate interaction behavior, not external-feed reliability.
- A spread response does not establish rebound-prop coverage.
- Manual quotes are user-entered research inputs, not fresh provider quotes.
- Experimental scenarios are not primary-model approvals.
- Conservative quota reservations survive ambiguous timeouts; they are not free retries.
- Hosted free processes cannot use ephemeral SQLite as durable multi-user quota storage.
- Predictive validation and six-person usability findings remain separate work.
