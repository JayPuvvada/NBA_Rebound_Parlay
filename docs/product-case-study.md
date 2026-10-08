# NBA Picks: product evidence and beta plan

## Product brief

Audience: the owner and a small group of friends who want to investigate NBA rebound
selections without stitching together schedules, prices, history and saved notes.

Promise: choose a game, generate a conditional selection when data permits, understand
its assumptions, save it privately, and revisit the original snapshot later.

Constraints: local-first Flask/React, existing providers, free-oriented operation,
private accounts, provider outages and incomplete preseason coverage. No bets are placed.
Functional correctness does not establish predictive quality.

## Priorities and user stories

| Priority | User story | Acceptance evidence |
| --- | --- | --- |
| P0 | As a user, I can browse offered prices when NBA Stats fails. | Independent markets tests and browser fixtures |
| P0 | I can generate rebounds without silently invented history or minutes. | Generator threshold, cutoff, availability and minutes tests |
| P0 | I can understand why a calculation produced no selection. | Distinct no-pick, needs-input and unavailable states |
| P0 | I can save a complete quote without model approval. | Manual snapshot validation and account journey |
| P0 | My records are private and the captured price cannot be rewritten. | RLS, grants, ownership and immutable-column tests |
| P1 | I can inspect observed history and return without losing my game. | Browser research/context journey |
| P1 | I can annotate, grade, filter and export my journal. | Journal tests; CSV formula escaping |
| P1 | I can use the primary workflow on a phone or keyboard. | Narrow-viewport and keyboard acceptance |

Excluded: parlays, staking, automatic settlement, social features, notifications,
unsupported injury feeds, non-rebound predictions and profit claims.

## Decisions worth discussing in an interview

1. **Keep the core promise.** Lines and research support the generator rather than replace it.
2. **Separate dependencies.** A statistics outage must not erase sportsbook prices or private records.
3. **Be explicit about uncertainty.** Preseason and limited-history outputs use separate scenario profiles.
4. **Design for the actual budget.** Shared caching and conservative reservations prevent refresh clicks
   or simultaneous users from exhausting the free provider allowance.
5. **Preserve history.** Additive records retain old selections and never rewrite captured quotes.
6. **Prefer useful density.** Remove decorative hero content and place assumptions beside decisions.

These are design decisions, not evidence that users prefer the result. Validate them in beta.

## Six-person usability protocol

### October 8 owner walkthrough — qualitative feedback

One owner reported that the checked games generated no picks; the Model picks label
and sportsbook section were confusing, game markets felt unnecessary for a rebound
product, and Compare 3 books was not understood. Player Research was described as
useful. No task timing or unassisted-completion metric was collected; this is not
the planned six-participant study and does not verify the cause of every failed attempt.

Approved response: remove game-market tabs and comparison from the main page,
focus on rebound lines, rename Model picks to Rebound analysis, and explain missing
lines beside the disabled generation action with a research shortcut. Keep stale
rebound-price labels for honesty. Re-test with the owner; do not claim the redesign
resolved the confusion before receiving that feedback.

Recruit six consenting participants; do not collect passwords or private notes in recordings.
Use the same warm test environment, document provider coverage, and offer no coaching initially.

Tasks: find a game; explain a generated result or its blocker; inspect observed history;
save a manual selection; sign out/in and retrieve it; add a note and manual result;
repeat the main browsing task on mobile.

Record completion, time, assistance, misunderstood labels, failed requests and severity.
Targets: five of six complete the primary journey unassisted, median warm task under
two minutes. These are targets—not results. Findings are **not yet collected**.

## Model evaluation card

Scope: rebounds only. Primary regular-season model is distinct from experimental
preseason/early/reduced-data scenarios. Known-out exclusions and historical cutoffs
must remain enforced. Unknown availability is not a claim of health.

Future evaluation: chronological holdouts, rebound-average and minutes-rate baselines,
error metrics with sample counts, separate competition profiles, and probability calibration.
Do not infer historical profit without timestamped historical quotes. Scenario dispersion
and minutes weights are engineering assumptions, not calibrated confidence intervals.

Implemented exploratory tooling: `scripts.check_preseason --evaluate --scenario-profile`
uses regular-only prior inputs and generator preseason thresholds/scenario means.
The October 7 Jokić check evaluated three later appearances (one initial appearance
skipped), MAE 1.165 rebounds. This small, selected historical sample is not an
untouched holdout or predictive validation. Keep it separate from usability results.

## Honest portfolio narrative

Explain your ownership of the problem definition, priorities, budget, acceptance criteria,
and beta decisions. Disclose AI implementation/review assistance. Attach verified test
results and dated screenshots; distinguish deterministic fixtures from live-provider checks.
Add measured usability findings only after conducting the study.
