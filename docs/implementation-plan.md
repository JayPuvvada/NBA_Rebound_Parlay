# NBA Picks implementation contract

Approved 2026-10-04. Local acceptance precedes any hosted migration or deployment.

October 8 approved usability revision supersedes the main-page market/comparison
requirements below: show rebounds only, remove book comparison, call the results
Rebound analysis, and explain/disable generation when the selected book has no lines.
Keep rebound quote freshness safeguards, existing records, operator endpoints,
and any internal spread features. Signup/account settings are unchanged.

## Product

Choose a game → generate rebound picks → inspect research → save privately → review.
Three connected pages: Picks & Lines (`#edge`), Player Research (`#lookup`), My Picks (`#picks`).
Keep Flask, React/Vite, existing providers and Supabase. Preserve existing changes,
regular-season model, historical picks, and operator ledger. No required paid dependencies.

## User experience

- Compact dark header with account control; remove decorative basketball/large hero.
- Shared public date/game/book/market/player context survives navigation and can be linked.
- Selected-game quotes load independently; generation runs only on request.
- Rebounds, spreads, moneyline and totals retain each selection's own price and line.
- Compare only identical event/market/subject/side/line selections across three books.
- Distinguish no games, missing market/book, provider failure, budget limit and stale cache.
- Model cards show selection, rebounds, minutes and material limitation; technical metrics expand.
- Research defaults to observed history, sources, sample scope, last-five/ten and recent games.
- Advanced inputs retain manual prices/context. User-entered prices have no provider timestamp.
- Save manual, primary model and experimental snapshots separately; no bet placement.
- Private journal includes filters, notes, Pending/Win/Loss/Push/Void, safe CSV and deletion confirmation.
- Keep signup settings; recovery is unavailable unless delivery is configured.
- Mobile cards, 44px controls, visible focus, accessible labels, reduced motion.

## Calculation profiles

- Established regular: at least 15 earlier current-regular appearances, full existing pipeline/gates.
- Early regular: qualifying prior regular baseline (10 appearances/150 minutes); blend current rate by n/15.
- Preseason: qualifying prior regular baseline, otherwise at least three earlier preseason appearances/45 minutes.
- Reduced regular: valid current total REB/MIN at >=15 appearances when full inputs are missing.
- Never switch methods solely to turn a valid primary no-pick into a pick.
- Strict season scope and exclusive target-date cutoff; no DNPs, invalid or duplicate appearances.
- Minutes use last three earlier appearances of the relevant competition or explicit 0–48 manual assumption.
- Explicit manual minutes may support an experimental candidate with fresh provider
  odds and a verified pregame; manual odds cannot. All experimental outputs remain non-actionable.
- Experimental three NB scenarios: ±6 preseason, ±4 early/reduced, weights .25/.5/.25, bounded 0–48.
- Use heuristic conditional dispersion, exact probabilities and zero-count distribution at zero minutes.
- Candidate needs its offered side's line/price, positive price edge, hypothetical ROI >=2%.
- Experimental candidate_direction remains separate and actionable=false; no operator-ledger promotion.
- Verified identity/game, known-out exclusion, honest unknown availability/freshness.

## Services and cost

- Independent `/games`, `/markets`, `/player-history`, `/generate-picks`; legacy adapters remain.
- Generation absolute deadline 75s, research 30s, at most two statistical workers.
- Completed rows survive partial failure; retry remaining reuses work; cancel/late-response protection.
- Shared persistent SQLite response cache, leases and conservative quota reservations locally.
- Default max16 credits/UTC day, max450/provider cycle, preserve50 provider credits.
- Three books share requests. Selected-game rebounds cost up to one credit; game markets up to three.
- Every paid attempt is reserved; actual headers reconcile; ambiguous timeout remains reserved.
- Provider reset detected from authoritative headers. No continuous polling or free-host reset loophole.
- Old game snapshots are displayable, not represented as current; stale quotes cannot approve live picks.
- Hosted multi-instance durable quota store is a separate rollout dependency.

## Account contract

- Additive versioned migration preserves legacy IDs/results and reads.
- Nullable moneyline line, signed spreads, optional non-model projection/player, generic selection.
- Immutable quote/model provenance and assumptions; only notes/result mutable.
- Ownership AND membership RLS, explicit grants, cross-user/anonymous tests.
- Stable material-content duplicate identity excludes click time.
- Local persistent Supabase accepts full workflow; cloud migration remains separately authorized.

## Milestones and evidence

| Milestone | State | Evidence |
| --- | --- | --- |
| 1 Baseline/data recovery | Implemented; live degraded path verified | Real NBA history and historical model calculation completed; missing full inputs remain explicit |
| 2 Markets/cache/budget | Implemented and tested | 28 quota/market tests; real game markets fetched; persistent SQLite cache |
| 3 Unified generator | Implemented and tested | Profiles, thresholds, scenarios, regression fixtures and killable deadlines |
| 4 Connected private journey | Verified locally October 5 | Real local Auth/REST and mobile save/storage-clear/relogin/notes/Void; local migration applied, hosted untouched |
| 5 Dashboard redesign | Verified locally | 22 desktop/mobile checks; actual-price screenshots; keyboard, reduced-motion and touch-target checks |
| 6 Journal completion | Implemented and tested | Filters/notes/Void/CSV, duplicates, legacy reads and immutable-column/RLS tests |
| 7 Local release acceptance | Partially verified | Tests/build and real private persistence pass; dependency audit clean; live quoted rebound approval remains a gap |

Do not declare success from mocks alone. Verify real completed-season history, current schedule,
available markets, a calculation with real inputs and persistence in the configured database.
Missing current rebound coverage remains an explicit coverage gap.

### Remaining gates and authority

| Gate | Current evidence | What is needed next |
| --- | --- | --- |
| Local correctness | 375 backend tests, 101 frontend tests, 32 browser checks; build/lint/types pass | Continue regression checks after any new change; this is not proof of every possible bug |
| Current provider-backed rebound pick | Repeated correctly matched preseason events return empty rebound quotes; latest MIN–IND check also empty | Actual offered rebound coverage, then verify the full-input calculation; never fabricate prices |
| Development dependency remediation | Approved local Tailwind 4.3.3 migration; full npm audit reports zero vulnerabilities | Keep regression checks and dependency audits current |
| Accuracy | Generator-aligned chronological exploratory tool works; one-player, three-game real check | Predeclared broader/untouched evaluation data; no profit claim without historical prices |
| Beta findings | Six-participant protocol and targets documented | Consenting human participants; do not invent results |
| Hosted readiness | Compatibility retained; new schema verified locally, not applied remotely | Separate authorization for hosted migration/deployment and shared durable quota storage |

No tests above establish provider uptime, profitable forecasts, official injury
coverage or confirmed lineups. New features, paid sources and hosted changes are
not authorized by the local bug-fixing goal.

## PM evidence

Product brief, prioritized stories/backlog, source/cost decisions, before/after screenshots,
six-user usability protocol, evaluation card and truthful case study. Targets are hypotheses:
5/6 unassisted, median task <2min warm, warm history/quotes p95<3s, privacy tests all pass.
Predictive evaluation is chronological, preseason separate, with baselines/sample counts.
Do not invent usability results, historical ROI, or predictive validation.
