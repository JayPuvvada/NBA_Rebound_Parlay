# NBA connection investigation

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
