# NBA Rebound Engine Frontend

React 19, TypeScript, Vite, Tailwind CSS, and Recharts power the two interface views:

- **Daily Edge** loads the NBA schedule, then displays the selected game's player props in backend-ranked edge order.
- **Player Lookup** runs one date-specific projection with optional Over and Under prices.

## Local development

Use Node 20.19 or newer (`nvm use` reads `.nvmrc`). Install dependencies and start Vite:

```bash
npm ci
npm run dev
```

Vite proxies `/games`, `/cheat-sheet`, and `/predict` to Flask at `http://127.0.0.1:5001`.

## Checks and build

```bash
npm run lint
npm run typecheck
npm run build
```

`npm run build` runs lint and the strict referenced TypeScript projects before emitting `dist/`. Flask serves that directory in production.

## API units

Probability-like values are raw fractions on the wire. For example, `confidence: 0.61`, `edge: 0.07`, `ev_roi: 0.12`, and `kelly_fraction: 0.03` render as 61%, +7%, +12%, and 3%. UI components perform all percent formatting.

Player Lookup sends side-specific `over_odds` and `under_odds`. If no odds are supplied, the UI treats the output as informational rather than presenting a priced edge. Ledger recording is opt-in through `record_prediction: true` and is unchecked by default. When saving is selected, the required password-style token is sent only in the `X-Ledger-Write-Token` request header; it is never added to the JSON body or browser storage.

## Backend contract

- `GET /games?date=YYYY-MM-DD` returns `{ date, games: [{ id, home, away }] }`.
- `GET /cheat-sheet?team=TEAM&date=YYYY-MM-DD&book=BOOK` returns `{ game, bookmaker, generated_at, projections }`. A legacy bare projections array is also accepted during migration.
- `POST /predict` accepts `player`, `opponent`, `date`, nullable `line`, nullable `over_odds`/`under_odds`, nullable `bookmaker`/`matchup`/`home_game`, numeric `spread`, and Boolean `record_prediction`.

Both projection payloads use nullable `direction`: `OVER` or `UNDER` means an actionable positive-EV selection, while `null` means **NO BET**. `evaluated_side`/`odds_side` identifies pricing context and is never treated as a recommendation. Manual recording metadata is `{ requested, recorded, prediction_id, reason }`.
