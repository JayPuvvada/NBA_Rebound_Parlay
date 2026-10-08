import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

let server, lib, ModelPickCard, QuoteCard, ObservedHistoryCard;
before(async () => {
  server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, watch: null, ws: false }, appType: 'custom' });
  lib = await server.ssrLoadModule('/src/lib/dashboard.ts');
  ({ ModelPickCard, QuoteCard } = await server.ssrLoadModule('/src/components/ui/PicksAndLines.tsx'));
  ({ ObservedHistoryCard } = await server.ssrLoadModule('/src/components/ui/PlayerResearch.tsx'));
});
after(async () => { await server?.close(); });

const context = { date: '2026-10-04', home: 'DEN', away: 'UTA', book: 'fanduel', market: 'player_rebounds', player: 'Nikola Jokic' };
const quote = { market: 'player_rebounds', selection: 'OVER', player: 'Nikola Jokic', team: 'DEN', line: 11.5, odds: -110, book: 'fanduel', event_id: 'event-a', updated_at: '2026-10-04T18:00:00Z', freshness: 'fresh' };
const board = { date: context.date, game: { home: context.home, away: context.away }, sport: 'basketball_nba_preseason', status: 'available', quotes: [quote], coverage: { fanduel: { player_rebounds: 'available' } } };
const assessment = { player: quote.player, team: 'DEN', result_kind: 'experimental_candidate', projection: 7.2, actionable: false, candidate_direction: 'OVER', quote, minutes: { value: 20, source: 'manual' }, limitations: ['Minutes are an assumption.'], analysis: { over_probability: .62, ev_roi: .12 }, model_version: 'scenarios-1', profile: 'preseason' };
const generation = { status: 'complete', date: context.date, game: board.game, generated_at: '2026-10-04T18:00:00Z', assessments: [assessment], coverage: { total: 1, completed: 1, incomplete: [] } };
test('quote freshness expires without promoting stale or unknown provider status', () => {
  const updated = Date.parse(quote.updated_at);
  assert.equal(lib.quoteFreshness(quote,updated+300_000),'fresh');
  assert.equal(lib.quoteFreshness(quote,updated+300_001),'stale');
  assert.equal(lib.quoteFreshness(quote,updated-1),'stale');
  for (const timestamp of [null,'not-a-date','2026-10-04T18:00:00']) assert.equal(lib.quoteFreshness({...quote,updated_at:timestamp},updated),'unknown');
  for (const status of ['stale','unknown']) assert.equal(lib.quoteFreshness({...quote,freshness:status},updated),status);
});
test('default game chooses earliest scheduled absolute tipoff without guessing missing times', () => {
  const late = {home:'DEN',away:'UTA',status:1,start_time:'2026-10-05T03:00:00Z'};
  const early = {home:'LAC',away:'GSW',status:1,start_time:'2026-10-04T19:00:00-04:00'};
  const completed = {...early,status:3,start_time:'2026-10-04T18:00:00Z'};
  const unknown = {...late,home:'ATL',start_time:null};
  assert.equal(lib.defaultGame([completed,unknown,late,early]),early);
  assert.equal(lib.defaultGame([unknown,{...late,start_time:'2026-10-04'}]),unknown);
  assert.equal(lib.defaultGame([completed]),completed);
  assert.equal(lib.defaultGame([]),undefined);
});
test('retry without a replacement retains incomplete players and completed work', () => {
  const missing = {...assessment,player:'Missing',result_kind:'unavailable',quote:null};
  const prior = {...generation,status:'partial',assessments:[assessment,missing],coverage:{total:2,completed:1,incomplete:['Missing']}};
  const empty = {...generation,status:'no_quotes',assessments:[],coverage:{total:0,completed:0,incomplete:[]}};
  const stillPartial = lib.mergeGeneration(prior,empty);
  assert.deepEqual(stillPartial.assessments,prior.assessments);
  assert.deepEqual(stillPartial.coverage,prior.coverage);
  assert.equal(stillPartial.status,'partial');
  const recovered = lib.mergeGeneration(prior,{...generation,assessments:[{...missing,result_kind:'no_pick'}]});
  assert.deepEqual(recovered.coverage,{total:2,completed:2,incomplete:[]});
  assert.equal(recovered.assessments[0],assessment);
});
test('calendar dates reject normalized impossible dates and accept leap days', () => {
  for (const date of ['2026-02-29','2026-04-31','0000-01-01','2026-13-01','garbage']) {
    assert.equal(lib.validCalendarDate(date),false);
    assert.notEqual(lib.readLocation(`#edge?date=${date}`).context.date,date);
  }
  assert.equal(lib.validCalendarDate('2024-02-29'),true);
});
test('quotes cannot cross event, league, team or generated-player boundaries', () => {
  for (const patch of [{event_id:'wrong-event'}, {sport:'basketball_nba'}, {team:'BOS'}]) {
    assert.throws(() => lib.validateBoard({...board,event_id:'event-a',quotes:[{...quote,...patch}]},context));
  }
  assert.throws(() => lib.validateBoard({...board,quotes:[{...quote,market:'h2h',selection:'BOS',line:null,player:null}]},context));
  assert.throws(() => lib.validateGeneration({...generation,assessments:[{...assessment,quote:{...quote,player:'Another Player'}}]},context));
  assert.doesNotThrow(() => lib.validateBoard({...board,event_id:'event-a'},context));
});

test('market availability follows comparison scope, independently of filters', () => {
  const otherBook = { ...quote, book: 'draftkings' };
  assert.equal(lib.filterMarketQuotes([otherBook], 'player_rebounds', 'fanduel', false, '', '').available.length, 0);
  const compared = lib.filterMarketQuotes([otherBook], 'player_rebounds', 'fanduel', true, 'missing player', '');
  assert.equal(compared.available.length, 1);
  assert.equal(compared.visible.length, 0);
  assert.equal(lib.filterMarketQuotes([otherBook], 'player_rebounds', 'fanduel', true, '  JOKIC  ', '').visible.length, 1);
  assert.equal(lib.filterMarketQuotes([otherBook], 'player_rebounds', 'fanduel', true, '', 'UTA').visible.length, 0);
  const total = { ...quote, market: 'totals', player: null, team: null };
  assert.equal(lib.filterMarketQuotes([total], 'totals', 'fanduel', false, 'under', '').visible.length, 0);
  assert.equal(lib.filterMarketQuotes([total], 'totals', 'fanduel', false, 'over', '').visible.length, 1);
});

test('legacy navigation hashes and shareable public selections round-trip', () => {
  assert.equal(lib.readLocation('#lookup').page, 'lookup');
  assert.equal(lib.readLocation('#picks').page, 'picks');
  assert.deepEqual(lib.readLocation(lib.locationHash('edge', context)), { page: 'edge', context });
  const bad = lib.readLocation('#picks?book=constructor&market=toString&password=secret&email=private');
  assert.equal(bad.context.book, 'fanduel');
  assert.equal(bad.context.market, 'player_rebounds');
  assert.doesNotMatch(lib.locationHash(bad.page, bad.context), /secret|private|password|email/);
});

test('book comparison never combines different thresholds, sides or events', () => {
  const better = { ...quote, book: 'draftkings', odds: 120 };
  assert.equal(lib.isBetterPrice(better, [quote, better]), true);
  assert.equal(lib.isBetterPrice(quote, [quote, better]), false);
  for (const other of [{ ...better, line: 12.5 }, { ...better, selection: 'UNDER' }, { ...better, event_id: 'event-b' }]) {
    assert.equal(lib.isBetterPrice(other, [quote, other]), false);
  }
  assert.equal(lib.isBetterPrice(quote, [quote, { ...quote, book: 'draftkings' }]), false);
});

test('board boundary preserves independent side lines and market-specific shapes', () => {
  const under = { ...quote, selection: 'UNDER', line: 12.5, odds: 120 };
  assert.equal(lib.validateBoard({ ...board, quotes: [quote, under] }, context).quotes[1].line, 12.5);
  assert.equal(lib.validQuote({ ...quote, market: 'h2h', player: null, selection: 'DEN', line: null }), true);
  assert.equal(lib.validQuote({ ...quote, market: 'spreads', player: null, selection: 'DEN', line: -5.5 }), true);
  for (const patch of [{ odds: -90 }, { odds: NaN }, { market: 'constructor' }, { book: 'toString' }, { freshness: 'sure' }, { updated_at: {} }, { line: true }]) assert.equal(lib.validQuote({ ...quote, ...patch }), false);
  assert.throws(() => lib.validateBoard({ ...board, date: '2026-10-05' }, context));
  assert.throws(() => lib.validateBoard({ ...board, coverage: { fanduel: {} }, quotes: [{ ...quote, player: {} }] }, context));
});

test('generation validates safety and rejects another game or optimistic experimental flags', () => {
  assert.equal(lib.validateGeneration(generation, context), generation);
  for (const row of [{ ...assessment, actionable: true }, { ...assessment, minutes: { value: 49, source: 'manual' } }, { ...assessment, limitations: [{}] }, { ...assessment, profile: {} }, { ...assessment, quote: { ...quote, book: 'draftkings' } }]) assert.throws(() => lib.validateGeneration({ ...generation, assessments: [row] }, context));
  assert.throws(() => lib.validateGeneration({ ...generation, game: { home: 'UTA', away: 'DEN' } }, context));
  assert.throws(() => lib.validateGeneration({ ...generation, coverage: { total: 1, completed: 2, incomplete: [] } }, context));
});

test('history excludes target-day data and rejects malformed averages', () => {
  const history = { player: context.player, date: context.date, message: 'Observed history', histories: [{ kind: 'prior_season', season: '2025-26', status: 'available', games: 20, source: 'stats.nba.com', rebounds_per_game: 10, minutes_per_game: 30, recent_games: [{ date: '2026-04-01', minutes: 30, rebounds: 12 }] }] };
  assert.equal(lib.validateHistory(history, context.player, context.date), history);
  for (const patch of [{ recent_games: {} }, { recent_games: [{ date: context.date, minutes: 30, rebounds: 12 }] }, { last_5: { rebounds: '12', minutes: 30 } }, { observed_above_line: { line: 10, above: 12, games: 10 } }]) assert.throws(() => lib.validateHistory({ ...history, histories: [{ ...history.histories[0], ...patch }] }, context.player, context.date));
});

test('observed frequency rejects contradictory counts instead of displaying them', () => {
  const history = { player: context.player, date: context.date, message: 'Observed history', histories: [{ kind: 'prior_season', season: '2025-26', status: 'available', games: 20, recent_games: [] }] };
  const frequency = {line: 10, above: 6, below: 3, push: 1, games: 10};
  for (const patch of [{below:11}, {push:11}, {below:4}, {games:21}, {line:-1}, {line:101}]) {
    assert.throws(() => lib.validateHistory({...history,histories:[{...history.histories[0],observed_above_line:{...frequency,...patch}}]},context.player,context.date));
  }
  assert.doesNotThrow(() => lib.validateHistory({...history,histories:[{...history.histories[0],observed_above_line:frequency}]},context.player,context.date));
});

test('experimental cards expose assumptions, own quote and inspect/save controls', () => {
  const html = renderToStaticMarkup(createElement(ModelPickCard, { row: assessment, onInspect() {}, onSave() {}, minutes: '', setMinutes() {}, rerun() {}, busy: false }));
  for (const label of ['Experimental candidate', 'OVER', '11.5', '-110', 'Scenario rebounds', 'Minutes assumption', 'Inspect player', 'Save selection', 'Advanced analysis', 'not been calibrated']) assert.ok(html.includes(label), label);
  assert.doesNotMatch(html, /Confidence score|Kelly stake|Best bet/);
});

test('missing minutes have a direct, bounded input and never render a candidate save', () => {
  const html = renderToStaticMarkup(createElement(ModelPickCard, { row: { ...assessment, result_kind: 'needs_input', quote: null, projection: null, minutes: null, reason_code: 'minutes_required' }, onInspect() {}, onSave() {}, minutes: '', setMinutes() {}, rerun() {}, busy: false }));
  assert.ok(html.includes('More information needed'));
  assert.ok(html.includes('max="48"'));
  assert.ok(html.includes('Calculate'));
  assert.ok(!html.includes('Save selection'));
});

test('stale sportsbook cards retain captured quote and unknown update time visibly', () => {
  const html = renderToStaticMarkup(createElement(QuoteCard, { quote: { ...quote, freshness: 'stale', updated_at: null }, comparable: [], compare: false, inspect() {}, save() {} }));
  for (const label of ['Stale quote', 'Update time unknown', '-110', 'Save selection']) assert.ok(html.includes(label), label);
});

test('research cards label observations and keep unavailable samples distinct', () => {
  const summary = { kind: 'prior_season', season: '2025-26', status: 'available', games: 20, rebounds_per_game: 10, minutes_per_game: 30, source: 'NBA Stats', recent_games: [{ date: '2026-04-01', minutes: 30, rebounds: 12 }], observed_above_line: { line: 11.5, above: 1, below: 0, push: 0, games: 1 } };
  const html = renderToStaticMarkup(createElement(ObservedHistoryCard, { history: summary }));
  for (const label of ['Prior regular season', 'Observed frequency', 'historical count', '2026-04-01', 'Needs 5 appearances']) assert.ok(html.includes(label), label);
  const missing = renderToStaticMarkup(createElement(ObservedHistoryCard, { history: { ...summary, status: 'empty', games: 0, rebounds_per_game: null, minutes_per_game: null, recent_games: [], observed_above_line: undefined } }));
  assert.ok(missing.includes('not a zero-rebound average'));
});
