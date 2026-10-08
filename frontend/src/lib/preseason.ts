import { ApiRequestError, fetchJson } from '@/lib/api';

export interface PreseasonRosterTeam {
  team: string;
  players: { player_id: number; name: string }[];
  source?: string;
  limitations: string[];
  unmatched_count: number;
  error?: string;
}

export interface PreseasonRoster {
  date: string;
  season: string;
  game: { home: string; away: string };
  teams: PreseasonRosterTeam[];
  analysis_only: true;
}

export interface HistorySummary {
  season: string;
  status: 'available' | 'empty' | 'unavailable';
  games: number;
  minutes_per_game: number | null;
  rebounds_per_game: number | null;
  rebounds_per_minute: number | null;
  source?: string;
  recent_games?: { date: string; minutes: number; rebounds: number }[];
}

export interface PreseasonPlayer {
  player_id: number;
  player: string;
  team: string;
  opponent: string;
  date: string;
  season: string;
  analysis_only: true;
  prediction_eligible: false;
  prior_season: HistorySummary;
  preseason: HistorySummary;
  estimate: {
    rebounds: number;
    minutes: number;
    minutes_source: 'manual' | 'earlier_preseason';
    history_games: number;
  } | null;
  limitations: string[];
}

export interface PreseasonPlayerRequest {
  player_id: number;
  team: string;
  opponent: string;
  date: string;
  minutes?: number;
}

export interface PreseasonMarkets {
  date: string;
  game: { home: string; away: string };
  book: string;
  analysis_only: true;
  status: 'available' | 'empty' | 'unconfigured';
  message: string;
  game_spreads?: { home: number | null; away: number | null };
  markets: { player: string; quotes: { side: 'OVER' | 'UNDER'; line: number; odds: number; updated_at: string | null; fresh: boolean }[] }[];
}

export function validatePreseasonMarkets(value: unknown, expected: { date: string; home: string; away: string; book: string }): PreseasonMarkets {
  if (!record(value) || value.analysis_only !== true || value.date !== expected.date || value.book !== expected.book
    || !record(value.game) || value.game.home !== expected.home || value.game.away !== expected.away
    || !text(value.message) || typeof value.status !== 'string' || !['available', 'empty', 'unconfigured'].includes(value.status)
    || !Array.isArray(value.markets) || (value.status === 'available') !== (value.markets.length > 0)) invalid('markets');
  if (value.game_spreads !== undefined) {
    const spreads = value.game_spreads;
    if (!record(spreads) || ![spreads.home, spreads.away].every(item => item === null
      || (typeof item === 'number' && Number.isFinite(item)))) invalid('markets');
  }
  for (const market of value.markets) {
    if (!record(market) || !text(market.player) || !Array.isArray(market.quotes) || !market.quotes.length) invalid('markets');
    const sides = new Set<string>();
    for (const quote of market.quotes) {
      if (!record(quote) || (quote.side !== 'OVER' && quote.side !== 'UNDER') || sides.has(quote.side)
        || !nonnegative(quote.line) || typeof quote.odds !== 'number' || !Number.isFinite(quote.odds)
        || (quote.odds > -100 && quote.odds < 100) || typeof quote.fresh !== 'boolean'
        || (quote.updated_at !== null && typeof quote.updated_at !== 'string')
        || (quote.fresh && !quote.updated_at)) invalid('markets');
      sides.add(quote.side);
    }
  }
  return value as unknown as PreseasonMarkets;
}

export async function fetchPreseasonMarkets(expected: { date: string; home: string; away: string; book: string }, signal: AbortSignal): Promise<PreseasonMarkets> {
  const query = new URLSearchParams({ date: expected.date, team: expected.home, book: expected.book });
  return validatePreseasonMarkets(await fetchJson(`/preseason-markets?${query}`, { signal }, { timeoutMs: 45_000 }), expected);
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function text(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}
function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === 'string');
}
function count(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
function positiveId(value: unknown): value is number {
  return count(value) && value > 0;
}
function nonnegative(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}
function team(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Z]{2,3}$/.test(value);
}
function invalid(subject: string): never {
  throw new ApiRequestError(`The preseason ${subject} response contained invalid or mismatched data. Please retry.`, 'invalid-response');
}

export function validatePreseasonRoster(value: unknown, expected: { date: string; home: string; away: string }): PreseasonRoster {
  if (!record(value) || value.analysis_only !== true || value.date !== expected.date || !text(value.season)
    || !record(value.game) || value.game.home !== expected.home || value.game.away !== expected.away
    || !team(value.game.home) || !team(value.game.away) || value.game.home === value.game.away
    || !Array.isArray(value.teams) || value.teams.length !== 2) invalid('roster');
  const seenTeams = new Set<string>();
  for (const candidate of value.teams) {
    if (!record(candidate) || !team(candidate.team)
      || ![expected.home, expected.away].includes(candidate.team) || seenTeams.has(candidate.team)
      || (candidate.source !== undefined && typeof candidate.source !== 'string') || !strings(candidate.limitations)
      || !count(candidate.unmatched_count) || (candidate.error !== undefined && !text(candidate.error))
      || !Array.isArray(candidate.players)) invalid('roster');
    const seenPlayers = new Set<number>();
    for (const player of candidate.players) {
      if (!record(player) || !positiveId(player.player_id) || !text(player.name) || seenPlayers.has(player.player_id)) invalid('roster');
      seenPlayers.add(player.player_id);
    }
    seenTeams.add(candidate.team);
  }
  return value as unknown as PreseasonRoster;
}

function history(value: unknown): boolean {
  if (!record(value) || !text(value.season) || !count(value.games)
    || typeof value.status !== 'string' || !['available', 'empty', 'unavailable'].includes(value.status)
    || (value.source !== undefined && typeof value.source !== 'string')) return false;
  if (value.recent_games !== undefined && (!Array.isArray(value.recent_games)
    || !value.recent_games.every(item => record(item) && typeof item.date === 'string'
      && /^\d{4}-\d{2}-\d{2}$/.test(item.date) && nonnegative(item.minutes) && count(item.rebounds)))) return false;
  const stats = [value.minutes_per_game, value.rebounds_per_game, value.rebounds_per_minute];
  if (value.status === 'available') return value.games > 0 && stats.every(nonnegative);
  return value.games === 0 && stats.every(stat => stat === null);
}

export function validatePreseasonPlayer(value: unknown, expected: PreseasonPlayerRequest): PreseasonPlayer {
  if (!record(value) || !text(value.player) || value.player_id !== expected.player_id
    || value.team !== expected.team || value.opponent !== expected.opponent
    || value.date !== expected.date || !text(value.season) || value.analysis_only !== true || value.prediction_eligible !== false
    || !history(value.prior_season) || !history(value.preseason) || !strings(value.limitations)) invalid('player');
  for (const summary of [value.prior_season, value.preseason] as HistorySummary[]) {
    if (summary.recent_games?.some(item => item.date >= expected.date)) invalid('player');
  }
  if (value.estimate !== null) {
    const estimate = value.estimate;
    const prior = value.prior_season as unknown as HistorySummary;
    const earlier = value.preseason as unknown as HistorySummary;
    if (!record(estimate) || !nonnegative(estimate.rebounds) || !nonnegative(estimate.minutes)
      || !positiveId(estimate.history_games) || estimate.history_games !== prior.games || prior.status !== 'available'
      || typeof estimate.minutes_source !== 'string'
      || !['manual', 'earlier_preseason'].includes(estimate.minutes_source)) invalid('player');
    // The server rounds reported minutes to two decimals; allow that rounding,
    // but never accept an unsolicited or materially different assumption.
    if (estimate.minutes_source === 'manual' && (expected.minutes === undefined
      || !nonnegative(expected.minutes) || expected.minutes > 48
      || Math.abs(estimate.minutes - expected.minutes) > 0.005 + 1e-9)) invalid('player');
    if (estimate.minutes_source === 'earlier_preseason' && (expected.minutes !== undefined || earlier.status !== 'available')) invalid('player');
  }
  return value as unknown as PreseasonPlayer;
}

export async function fetchPreseasonRoster(expected: { date: string; home: string; away: string }, signal: AbortSignal): Promise<PreseasonRoster> {
  const query = new URLSearchParams({ date: expected.date, team: expected.home });
  return validatePreseasonRoster(await fetchJson(`/preseason-roster?${query}`, { signal }, { timeoutMs: 80_000 }), expected);
}

export async function fetchPreseasonPlayer(request: PreseasonPlayerRequest, signal: AbortSignal): Promise<PreseasonPlayer> {
  return validatePreseasonPlayer(await fetchJson('/preseason-player', {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
  }, { timeoutMs: 80_000 }), request);
}
