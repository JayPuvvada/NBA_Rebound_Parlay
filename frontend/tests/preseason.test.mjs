import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

let server, validatePreseasonRoster, validatePreseasonPlayer, validatePreseasonMarkets, fetchPreseasonRoster, fetchPreseasonPlayer, PreseasonAnalysis, HistoryCard;
const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
before(async () => {
  server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null, ws: false }, appType: 'custom' });
  ({ validatePreseasonRoster, validatePreseasonPlayer, validatePreseasonMarkets, fetchPreseasonRoster, fetchPreseasonPlayer } = await server.ssrLoadModule('/src/lib/preseason.ts'));
  ({ PreseasonAnalysis, HistoryCard } = await server.ssrLoadModule('/src/components/ui/PreseasonAnalysis.tsx'));
  globalThis.window = { setTimeout, clearTimeout };
});
after(async () => {
  globalThis.fetch = originalFetch;
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
  await server?.close();
});

const game = { date: '2026-10-04', home: 'DEN', away: 'UTA' };
const request = { player_id: 203999, team: 'DEN', opponent: 'UTA', date: game.date };
const prior = { season: '2025-26', status: 'available', games: 60, minutes_per_game: 30, rebounds_per_game: 12, rebounds_per_minute: 0.4, source: 'NBA Stats' };
const empty = { season: '2026-27', status: 'empty', games: 0, minutes_per_game: null, rebounds_per_game: null, rebounds_per_minute: null };
const player = { ...request, player: 'Example Player', season: '2026-27', analysis_only: true, prediction_eligible: false, prior_season: prior, preseason: empty, estimate: null, limitations: ['Not validated for betting.'] };
const roster = { date: game.date, season: '2026-27', game: { home: game.home, away: game.away }, analysis_only: true,
  teams: [{ team: 'DEN', players: [{ player_id: request.player_id, name: player.player }], source: 'NBA Stats', limitations: [], unmatched_count: 0 },
    { team: 'UTA', players: [], source: 'unavailable', limitations: ['Roster unavailable'], unmatched_count: 0, error: 'Retry later' }],
};

test('preseason roster accepts partial coverage and preserves unavailable-team warnings', () => {
  assert.equal(validatePreseasonRoster(roster, game), roster);
  assert.equal(validatePreseasonRoster(roster, game).teams[1].error, 'Retry later');
});

test('preseason roster rejects wrong dates, teams, duplicate players and malformed warnings', () => {
  for (const value of [null, {}, { ...roster, analysis_only: false }, { ...roster, date: '2026-10-05' },
    { ...roster, game: { home: 'UTA', away: 'DEN' } }, { ...roster, teams: [roster.teams[0], roster.teams[0]] },
    ...[{ player_id: true, name: 'A' }, { player_id: 1.5, name: 'A' }, { player_id: 1, name: {} }].map(bad => ({ ...roster, teams: [{ ...roster.teams[0], players: [bad] }, roster.teams[1]] })),
    ...[{ players: [roster.teams[0].players[0], roster.teams[0].players[0]] }, { limitations: ['fine', {}] }, { unmatched_count: -1 }, { error: {} }].map(bad => ({ ...roster, teams: [{ ...roster.teams[0], ...bad }, roster.teams[1]] })),
  ]) assert.throws(() => validatePreseasonRoster(value, game), error => error.kind === 'invalid-response');
});

test('first appearance preserves real history without inventing an estimate', () => {
  assert.equal(validatePreseasonPlayer(player, request), player);
  assert.equal(validatePreseasonPlayer(player, request).estimate, null);
  assert.equal(validatePreseasonPlayer({ ...player, prior_season: { ...empty, status: 'unavailable' } }, request).prior_season.status, 'unavailable');
});

test('observed recent games cannot include target-day or future results', () => {
  const gameRow = { date: '2026-04-01', minutes: 30, rebounds: 12 };
  assert.equal(validatePreseasonPlayer({ ...player, prior_season: { ...prior, recent_games: [gameRow] } }, request).prior_season.recent_games.length, 1);
  for (const row of [{ ...gameRow, date: request.date }, { ...gameRow, date: '2026-10-05' },
    { ...gameRow, minutes: '30' }, { ...gameRow, rebounds: true }, { ...gameRow, rebounds: 2.5 }]) {
    assert.throws(() => validatePreseasonPlayer({ ...player, prior_season: { ...prior, recent_games: [row] } }, request));
  }
});

test('preseason player rejects optimistic safety flags and mismatched player identity', () => {
  for (const patch of [{ analysis_only: false }, { prediction_eligible: true }, { prediction_eligible: 'false' },
    { player_id: 9 }, { date: '2026-10-05' }, { team: 'BOS' }, { opponent: 'LAL' }, { limitations: 'Not safe' }, { player: {} }]) {
    assert.throws(() => validatePreseasonPlayer({ ...player, ...patch }, request), error => error.kind === 'invalid-response');
  }
});

test('history rejects nonfinite or fractional counts and fabricated empty-season averages', () => {
  for (const summary of [{ ...prior, games: 1.5 }, { ...prior, games: true }, { ...prior, games: 0 },
    { ...prior, rebounds_per_minute: Infinity }, { ...prior, minutes_per_game: -1 }, { ...prior, rebounds_per_game: '12' },
    { ...empty, rebounds_per_game: 0 }, { ...empty, games: 1 }, { ...empty, status: 'okay' },
    { ...empty, status: ['empty'] }]) {
    assert.throws(() => validatePreseasonPlayer({ ...player, prior_season: summary }, request), error => error.kind === 'invalid-response');
  }
});

test('manual estimate must match an explicitly requested minutes assumption, including zero', () => {
  for (const minutes of [0, 20, 48]) {
    const estimate = { rebounds: minutes * 0.4, minutes, minutes_source: 'manual', history_games: 60 };
    assert.equal(validatePreseasonPlayer({ ...player, estimate }, { ...request, minutes }).estimate, estimate);
    assert.throws(() => validatePreseasonPlayer({ ...player, estimate }, request), error => error.kind === 'invalid-response');
    assert.throws(() => validatePreseasonPlayer({ ...player, estimate }, { ...request, minutes: minutes + 1 }), error => error.kind === 'invalid-response');
  }
  const rounded = { rebounds: 8.05, minutes: 20.12, minutes_source: 'manual', history_games: 60 };
  assert.equal(validatePreseasonPlayer({ ...player, estimate: rounded }, { ...request, minutes: 20.123 }).estimate, rounded);
  assert.throws(() => validatePreseasonPlayer({ ...player, estimate: rounded }, { ...request, minutes: 20.13 }), error => error.kind === 'invalid-response');
});

test('automatic estimates require earlier preseason games and a real prior-season rate', () => {
  const estimate = { rebounds: 8, minutes: 20, minutes_source: 'earlier_preseason', history_games: 60 };
  const valid = { ...player, estimate, preseason: { ...prior, season: '2026-27', games: 1 } };
  assert.equal(validatePreseasonPlayer(valid, request), valid);
  for (const payload of [{ ...player, estimate }, { ...valid, prior_season: empty },
    { ...valid, estimate: { ...estimate, rebounds: NaN } }, { ...valid, estimate: { ...estimate, history_games: 0 } },
    { ...valid, estimate: { ...estimate, minutes_source: 'invented' } }]) {
    assert.throws(() => validatePreseasonPlayer(payload, request), error => error.kind === 'invalid-response');
  }
  assert.throws(() => validatePreseasonPlayer(valid, { ...request, minutes: 20 }), error => error.kind === 'invalid-response');
  for (const minutes_source of [['manual'], ['earlier_preseason']]) {
    assert.throws(() => validatePreseasonPlayer({ ...player, estimate: { ...estimate, minutes_source } }, request), error => error.kind === 'invalid-response');
  }
});

test('preseason requests use separate read-only analysis endpoints, never odds or pick endpoints', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return { ok: true, status: 200, text: async () => JSON.stringify(String(url).startsWith('/preseason-roster') ? roster : player) };
  };
  await fetchPreseasonRoster(game, new AbortController().signal);
  await fetchPreseasonPlayer(request, new AbortController().signal);
  assert.match(calls[0].url, /^\/preseason-roster\?date=2026-10-04&team=DEN$/);
  assert.equal(calls[1].url, '/preseason-player');
  assert.equal(calls[1].init.method, 'POST');
  assert.deepEqual(JSON.parse(calls[1].init.body), request);
});

test('canceled preseason requests do not start fetch or accept late responses', async () => {
  const canceled = new AbortController();
  canceled.abort();
  let calls = 0;
  globalThis.fetch = async () => { calls++; throw new Error('Must not fetch'); };
  await assert.rejects(fetchPreseasonPlayer(request, canceled.signal), error => error.kind === 'aborted');
  assert.equal(calls, 0);
  const late = new AbortController();
  globalThis.fetch = async () => ({ ok: true, status: 200, text: async () => { late.abort(); return JSON.stringify(roster); } });
  await assert.rejects(fetchPreseasonRoster(game, late.signal), error => error.kind === 'aborted');
});

test('preseason research explains limitations without betting or save controls', () => {
  const html = renderToStaticMarkup(createElement(PreseasonAnalysis, game));
  for (const text of ['Preseason research', 'analysis only', 'no betting recommendations', 'healthy or will play']) assert.ok(html.includes(text), text);
  for (const text of ['Expected return', 'Save pick', 'Model win probability']) assert.ok(!html.includes(text), text);
  assert.ok(html.includes('Sportsbook rebound lines'));
});

test('market quotes retain side lines, reject unsafe freshness and preserve empty coverage', () => {
  const expected = { ...game, book: 'fanduel' };
  const emptyMarkets = { ...expected, game: { home: game.home, away: game.away }, analysis_only: true,
    status: 'empty', message: 'No props', markets: [] };
  assert.equal(validatePreseasonMarkets(emptyMarkets, expected), emptyMarkets);
  const quote = { side: 'UNDER', line: 5.5, odds: 120, updated_at: null, fresh: false };
  const valid = { ...emptyMarkets, status: 'available', markets: [{ player: 'Example', quotes: [quote] }] };
  assert.equal(validatePreseasonMarkets(valid, expected), valid);
  for (const patch of [{ line: true }, { odds: -90 }, { odds: Infinity }, { fresh: 'true' },
    { fresh: true }, { side: ['UNDER'] }, { updated_at: {} }]) {
    assert.throws(() => validatePreseasonMarkets({ ...valid, markets: [{ player: 'Example', quotes: [{ ...quote, ...patch }] }] }, expected));
  }
  for (const patch of [{ book: 'draftkings' }, { analysis_only: false }, { status: 'available' }]) {
    assert.throws(() => validatePreseasonMarkets({ ...emptyMarkets, ...patch }, expected));
  }
});

test('observed averages and empty history have explicit non-projection labels', () => {
  const available = renderToStaticMarkup(createElement(HistoryCard, { title: 'Prior season', summary: prior }));
  for (const text of ['Observed history, not a forecast', '60 games', '12.0', '30.0', '0.400']) assert.ok(available.includes(text), text);
  const missing = renderToStaticMarkup(createElement(HistoryCard, { title: 'Earlier preseason', summary: empty }));
  assert.ok(missing.includes('not a zero-rebound average'));
  assert.ok(!missing.includes('0.0'));
});
