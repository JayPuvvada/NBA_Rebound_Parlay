# NBA connection investigation

## Local header comparison (2026-09-08)

- Same Jokic regular-season request, explicitly using completed season 2024-25:
  stock `nba_api` returned 70 rows in 0.5 seconds; the app wrapper timed out
  after 15.3 seconds. Repeated comparison: app timed out at 8.1 seconds,
  stock succeeded at 0.2 seconds, then both succeeded at 0.2/0.1 seconds.
- This rules out missing season history for these probes, but does not establish
  an Akamai block or prove headers are the only cause of intermittent failures.
- Locally restored a copy of `NBAStatsHTTP.headers` instead of randomized
  browser headers for NBA endpoint requests. Explicit caller overrides, proxy
  configuration, TLS verification, and bounded timeouts remain supported.
- After the change, the full player-history loader returned 84 rows in 0.7
  seconds and Denver roster loading returned 18 rows in 0.5 seconds.
- Existing ESPN historical fallback separately returned 86 total-rebound rows;
  that is alternate-source data, not equivalent proof of NBA source completeness.
- All 188 backend unit tests passed. No deployment performed for this change.
- A complete local composite projection for Jokic vs LAL, as of 2025-03-14,
  succeeded in 35.2 seconds: 13.18 projected rebounds, 60 pre-cutoff games,
  primary `stats.nba.com` inputs with no source limitations. Historical injury
  information remains unavailable, so it correctly stays analysis-only. This
  verifies the projection engine, not the entire browser/HTTP workflow or Render.

## Follow-up local verification

- Real Flask `/predict` requests (no saved picks) succeeded for Jokic vs LAL
  on 2025-03-14 (HTTP 200, 21.0 seconds) and Curry vs NYK on 2025-03-15
  (HTTP 200, 43.9 seconds). Both remain historical analysis-only. Curry hit
  TeamGameLog timeouts and correctly included a neutral-rest limitation.
- A direct 2025-26 Jokic history probe still timed out at 8.1 seconds, while
  2026-27 returned valid empty history in 0.5 seconds. The header change does
  not eliminate intermittent source failures; empty history is a distinct case.
- Replaced misleading unknown-player errors for unusable history with an
  explicit selected-date/season statistics message. Connection failures now
  return Retry-After: 30 without implying a proxy is the confirmed solution.
- Empty, missing-date, and malformed-date team history now mark neutral rest
  as estimated. NBA rest failures no longer incorrectly label their source ESPN.
- Added regression coverage for these cases. No Render/Vercel deployment or
  provider switch. Full Daily Edge/browser and current-season success remain
  unverified; the successful HTTP tests above used completed historical dates.

## Earlier investigation

Local patch, not deployed to Render.

- An 8-second direct Toronto roster request timed out; the following request
  with a 30-second allowance returned 17 rows in 0.2 seconds. This demonstrates
  intermittent access, not proof that longer timeouts alone fix connectivity.
- Replaced the five-minute host-wide circuit with a 30-second endpoint-specific
  cooldown. Failed team logs no longer prevent independent roster calls.
- Roster calls now allow 30 seconds. Other requests retain their existing bounded
  timeouts so a full roster does not multiply 30-second waits for every input.
- Daily Edge distinguishes upstream data failures from missing model inputs and
  returns a 30-second Retry-After hint for upstream failures. Player-level source
  errors are counted even when the projection loop catches them.
- Stale-cache and betting-eligibility safeguards are unchanged. No unverified
  roster fallback or cross-season history substitution was introduced.

Real Toronto/Miami, 2026-10-03, testing got past roster loading on one run but
failed all player projections. A further diagnostic run identified empty player
history and PlayerGameLog failures, followed by another roster timeout. The
schedule alone does not establish that the selected season has usable player
history. Full real-data projection success remains unverified.

Backend tests should run with `TZ=America/New_York python3 -m unittest discover
-s tests -q`: existing live-game tests use system `date.today()` while production
uses the Eastern date, so those tests otherwise disagree near midnight.

Remaining: establish reliable player/team history access and verify a complete
real-data projection before deploying. Do not present this connection-handling
patch as a completed NBA data-access fix.
