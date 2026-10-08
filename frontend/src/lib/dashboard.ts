import { ApiRequestError } from "./api";
import { easternToday } from "./format";
import type { Game } from "@/types/api";

export const BOOKS = { fanduel: "FanDuel", draftkings: "DraftKings", betmgm: "BetMGM" } as const;
export const MARKET_NAMES = { player_rebounds: "Rebounds", spreads: "Spreads", h2h: "Moneyline", totals: "Totals" } as const;
export type Book = keyof typeof BOOKS;
export type Market = keyof typeof MARKET_NAMES;
export type Page = "edge" | "lookup" | "picks";
export function defaultGame(games: Game[]): Game | undefined {
  const scheduled = games.filter(game => game.status === 1 || game.status === '1' || /scheduled/i.test(game.status_text || ''));
  const time = (game: Game) => {
    // Only compare absolute provider timestamps; display text and dates alone are not tipoff times.
    const value = game.start_time;
    if (!value || !/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return Infinity;
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : Infinity;
  };
  return [...scheduled].sort((a, b) => time(a) - time(b))[0] || games[0];
}
export interface DashboardContext { date: string; home: string; away: string; book: Book; market: Market; player: string; }
export interface Quote {
  market: Market; selection: string; player: string | null; team: string | null;
  line: number | null; odds: number; book: Book; book_title?: string;
  updated_at: string | null; freshness: "fresh" | "stale" | "unknown";
  event_id?: string | null; fetched_at?: string | null; source?: string;
  sport?: string;
}
export function quoteFreshness(quote: Quote, now = Date.now()): Quote['freshness'] {
  if (quote.freshness !== 'fresh') return quote.freshness;
  if (!quote.updated_at || !/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(quote.updated_at)) return 'unknown';
  const updated = Date.parse(quote.updated_at);
  if (!Number.isFinite(updated)) return 'unknown';
  return now >= updated && now - updated <= 300_000 ? 'fresh' : 'stale';
}
export function filterMarketQuotes(quotes: Quote[], market: Market, book: Book, compare: boolean, search: string, team: string) {
  const available = quotes.filter(q => q.market === market && (compare || q.book === book));
  const query = search.trim().toLowerCase();
  const visible = available.filter(q => (!query || [q.player, q.team, q.selection, q.market === 'totals' ? 'Game total' : ''].join(' ').toLowerCase().includes(query)) && (!team || q.team === team));
  return { available, visible };
}
export interface Board {
  status: string; date: string; game: { home: string; away: string }; sport: string;
  quotes: Quote[]; coverage: Record<string, Record<string, string>>;
  event_id?: string | null; fetched_at?: string; message?: string; refresh_error?: string; reason_code?: string;
  cached?: boolean; budget?: { daily_used: number; daily_limit: number; cycle_used: number; cycle_limit: number; provider_remaining: number | null };
}
export interface Assessment {
  player: string; player_id?: number | null; team?: string | null;
  result_kind: "model_pick" | "experimental_candidate" | "no_pick" | "needs_input" | "unavailable";
  profile?: string; model_version?: string; projection: number | null;
  minutes?: { value: number | null; source: string }; quote?: Quote | null;
  direction?: string | null; candidate_direction?: string | null; actionable: boolean;
  limitations: string[]; reason_code?: string; assumptions?: Record<string, unknown>;
  analysis?: Record<string, unknown>; generated_at?: string;
}
export interface Generation {
  status: string; date: string; game: { home: string; away: string };
  assessments: Assessment[]; coverage: { total: number; completed: number; incomplete: string[] };
  generated_at: string; message?: string; limitations?: string[];
}
export function mergeGeneration(prior: Generation, next: Generation): Generation {
  const replacements = new Set(next.assessments.map(row => row.player));
  const assessments = [...prior.assessments.filter(row => !replacements.has(row.player)), ...next.assessments];
  const incomplete = [...new Set([
    ...prior.coverage.incomplete.filter(name => !replacements.has(name)),
    ...next.coverage.incomplete,
    ...assessments.filter(row => row.result_kind === 'unavailable').map(row => row.player),
  ])];
  const total = Math.max(prior.coverage.total, new Set([...assessments.map(row => row.player), ...incomplete]).size);
  return { ...next, assessments, status: incomplete.length ? 'partial' : 'complete',
    coverage: { total, completed: total - incomplete.length, incomplete } };
}
export interface HistoryGame { date: string; minutes: number; rebounds: number; }
export interface History {
  kind: string; season: string; status: "available" | "empty" | "unavailable";
  games: number; source?: string; date_range?: { from?: string; to?: string; scope?: string };
  minutes_per_game: number | null; rebounds_per_game: number | null;
  last_5?: { rebounds: number; minutes: number }; last_10?: { rebounds: number; minutes: number };
  recent_games?: HistoryGame[];
  observed_above_line?: { line: number; above: number; below?: number; push?: number; games: number };
}
export interface HistoryResponse { player: string; date: string; histories: History[]; message: string; status?: 'complete' | 'partial' | 'unavailable'; reason_code?: string; }

const record = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const optionalText = (v: unknown) => v == null || typeof v === "string";
const count = (v: unknown): v is number => finite(v) && Number.isInteger(v) && v >= 0;
const invalid = (message: string): never => { throw new ApiRequestError(message, "invalid-response"); };
export function validCalendarDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000')) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0,10) === value;
}

export function validQuote(v: unknown): v is Quote {
  if (!record(v) || typeof v.market !== "string" || !Object.hasOwn(MARKET_NAMES, v.market)
    || typeof v.book !== "string" || !Object.hasOwn(BOOKS, v.book) || typeof v.selection !== "string"
    || !finite(v.odds) || !Number.isInteger(v.odds) || Math.abs(v.odds) < 100 || Math.abs(v.odds) > 100000
    || !optionalText(v.player) || !optionalText(v.team) || !optionalText(v.updated_at)
    || !optionalText(v.event_id) || !optionalText(v.fetched_at) || !optionalText(v.source) || !optionalText(v.sport)
    || !["fresh", "stale", "unknown"].includes(String(v.freshness))) return false;
  if (v.market === "h2h") return v.line === null && /^[A-Z]{2,3}$/.test(v.selection);
  if (!finite(v.line) || Math.abs(v.line) > 1000) return false;
  if (v.market === "spreads") return /^[A-Z]{2,3}$/.test(v.selection);
  return ["OVER", "UNDER"].includes(v.selection) && v.line >= 0
    && (v.market !== "player_rebounds" || (typeof v.player === "string" && !!v.player.trim()));
}

export function validateBoard(value: unknown, context: DashboardContext): Board {
  if (!record(value) || !record(value.game) || value.date !== context.date
    || value.game.home !== context.home || value.game.away !== context.away
    || typeof value.status !== "string" || !Array.isArray(value.quotes) || !value.quotes.every(validQuote)
    || !record(value.coverage) || !optionalText(value.message) || !optionalText(value.refresh_error)
    || typeof value.sport !== "string"
    || !['basketball_nba', 'basketball_nba_preseason'].includes(value.sport)
    || !optionalText(value.event_id)
    || (value.budget != null && (!record(value.budget)
      || ![value.budget.daily_used, value.budget.daily_limit, value.budget.cycle_used, value.budget.cycle_limit].every(count)
      || (value.budget.provider_remaining != null && !count(value.budget.provider_remaining))))
    || !Object.values(value.coverage).every(book => record(book) && Object.values(book).every(v => typeof v === "string"))) {
    return invalid("The sportsbook response did not match this game. Retry this market.");
  }
  for (const quote of value.quotes as Quote[]) {
    if ((quote.event_id && value.event_id && quote.event_id !== value.event_id)
      || (quote.sport && quote.sport !== value.sport)
      || (['h2h', 'spreads'].includes(quote.market) && ![context.home, context.away].includes(quote.selection))
      || (quote.team && ![context.home, context.away].includes(quote.team))) {
      return invalid('A sportsbook selection did not match this event. Retry this market.');
    }
  }
  return value as unknown as Board;
}

export function validateGeneration(value: unknown, context: DashboardContext): Generation {
  if (!record(value) || !record(value.game) || value.date !== context.date
    || value.game.home !== context.home || value.game.away !== context.away
    || !Array.isArray(value.assessments) || !record(value.coverage)
    || !count(value.coverage.total) || !count(value.coverage.completed) || value.coverage.completed > value.coverage.total
    || !Array.isArray(value.coverage.incomplete) || !value.coverage.incomplete.every(v => typeof v === "string")
    || typeof value.generated_at !== "string" || typeof value.status !== "string" || !optionalText(value.message)) return invalid("The calculation response did not match this game.");
  for (const row of value.assessments) {
    if (!record(row) || typeof row.player !== "string" || !row.player.trim()
      || !["model_pick", "experimental_candidate", "no_pick", "needs_input", "unavailable"].includes(String(row.result_kind))
      || (row.projection != null && (!finite(row.projection) || row.projection < 0))
      || typeof row.actionable !== "boolean" || !Array.isArray(row.limitations) || !row.limitations.every(v => typeof v === "string")
      || ![row.team, row.profile, row.model_version, row.reason_code].every(optionalText)
      || (row.analysis != null && !record(row.analysis)) || (row.assumptions != null && !record(row.assumptions))
      || (row.quote != null && (!validQuote(row.quote) || row.quote.book !== context.book
        || row.quote.market !== 'player_rebounds' || row.quote.player !== row.player))
      || (row.minutes != null && (!record(row.minutes) || typeof row.minutes.source !== "string" || (row.minutes.value != null && (!finite(row.minutes.value) || row.minutes.value < 0 || row.minutes.value > 48))))) {
      return invalid("The calculation contained invalid player data. Retry generation.");
    }
    if (row.result_kind !== "model_pick" && row.actionable !== false) return invalid("Experimental analysis cannot approve a primary-model pick.");
    if (row.result_kind === "model_pick" && (!row.actionable || !row.quote)) return invalid("A primary-model pick requires an eligible quoted selection.");
  }
  return value as unknown as Generation;
}

export function validateHistory(value: unknown, player: string, date: string): HistoryResponse {
  if (!record(value) || value.player !== player || value.date !== date || !Array.isArray(value.histories)
    || typeof value.message !== "string" || !optionalText(value.reason_code)
    || (value.status != null && !['complete', 'partial', 'unavailable'].includes(String(value.status)))) return invalid("The history response did not match this player.");
  for (const history of value.histories) {
    if (!record(history) || typeof history.kind !== "string" || typeof history.season !== "string"
      || !["available", "empty", "unavailable"].includes(String(history.status)) || !count(history.games)
      || !optionalText(history.source)
      || (history.date_range != null && (!record(history.date_range)
        || !optionalText(history.date_range.from) || !optionalText(history.date_range.to) || !optionalText(history.date_range.scope)))
      || [history.minutes_per_game, history.rebounds_per_game].some(v => v != null && (!finite(v) || v < 0))) return invalid("Player history contained invalid observations.");
    if (history.recent_games != null && !Array.isArray(history.recent_games)) return invalid("Player history contained invalid observations.");
    for (const sample of [history.last_5, history.last_10]) {
      if (sample != null && (!record(sample) || !finite(sample.rebounds) || sample.rebounds < 0 || !finite(sample.minutes) || sample.minutes < 0)) return invalid("Historical averages contained invalid observations.");
    }
    if (history.observed_above_line != null) {
      const frequency = history.observed_above_line;
      if (!record(frequency) || !finite(frequency.line) || !count(frequency.above) || !count(frequency.games)
        || frequency.above > frequency.games || (frequency.below != null && !count(frequency.below))
        || (frequency.push != null && !count(frequency.push))
        || frequency.line < 0 || frequency.line > 100
        || (typeof frequency.below === 'number' && frequency.below > frequency.games)
        || (typeof frequency.push === 'number' && frequency.push > frequency.games)
        || frequency.games > history.games
        || (typeof frequency.below === 'number' && typeof frequency.push === 'number'
          && frequency.above + frequency.below + frequency.push !== frequency.games)) return invalid("Historical counts contained invalid observations.");
    }
    for (const row of (history.recent_games as unknown[] | undefined) || []) {
      if (!record(row) || !validCalendarDate(row.date) || row.date >= date || !finite(row.minutes)
        || row.minutes <= 0 || row.minutes > 60 || !count(row.rebounds)) return invalid("Player history contained invalid or future appearances.");
    }
  }
  return value as unknown as HistoryResponse;
}

export function readLocation(hash: string): { page: Page; context: DashboardContext } {
  const [page, query] = hash.replace(/^#/, "").split("?");
  const params = new URLSearchParams(query);
  const date = params.get("date") || "";
  const team = (name: string) => /^[A-Z]{2,3}$/.test(params.get(name) || "") ? params.get(name)! : "";
  const book = params.get("book");
  const market = params.get("market");
  return { page: page === "lookup" || page === "picks" ? page : "edge", context: {
    date: validCalendarDate(date) ? date : easternToday(), home: team("home"), away: team("away"),
    book: book && Object.hasOwn(BOOKS, book) ? book as Book : "fanduel",
    market: market && Object.hasOwn(MARKET_NAMES, market) ? market as Market : "player_rebounds",
    player: (params.get("player") || "").slice(0, 100),
  } };
}

export function locationHash(page: Page, context: DashboardContext): string {
  const params = new URLSearchParams({ date: context.date, book: context.book, market: context.market });
  if (context.home && context.away) { params.set("home", context.home); params.set("away", context.away); }
  if (context.player) params.set("player", context.player);
  return `#${page}?${params}`;
}

export const sportFor = (game: Game | undefined) => game?.is_preseason ? "basketball_nba_preseason" : "basketball_nba";
export const groupFor = (market: Market) => market === "player_rebounds" ? "rebounds" : "game";
export const contextKey = (c: DashboardContext, sport: string) => `${c.date}:${sport}:${c.home}:${c.away}:${c.book}`;
export const formatPrice = (price: number) => price > 0 ? `+${price}` : String(price);
export const quoteLabel = (quote: Quote) => `${quote.player || quote.team || "Game total"} ${quote.selection}${quote.line == null ? "" : ` ${quote.line > 0 && quote.market === "spreads" ? "+" : ""}${quote.line}`}`;
export const reasonLabel = (reason?: string) => reason ? reason.replaceAll("_", " ").replace(/^./, c => c.toUpperCase()) : "Inputs could not be verified.";

export function selectionKey(quote: Quote): string {
  return JSON.stringify([quote.event_id, quote.market, quote.player, quote.team, quote.selection, quote.line]);
}
export function bestPrices(quotes: Quote[]): Map<string, number> {
  const result = new Map<string, number>();
  for (const q of quotes) {
    const key = selectionKey(q);
    const decimal = q.odds > 0 ? 1 + q.odds / 100 : 1 + 100 / Math.abs(q.odds);
    result.set(key, Math.max(result.get(key) || 0, decimal));
  }
  return result;
}
export function isBetterPrice(quote: Quote, quotes: Quote[]): boolean {
  const comparable = quotes.filter(q => selectionKey(q) === selectionKey(quote));
  if (new Set(comparable.map(q => q.book)).size < 2 || new Set(comparable.map(q => q.odds)).size < 2) return false;
  const decimal = quote.odds > 0 ? 1 + quote.odds / 100 : 1 + 100 / Math.abs(quote.odds);
  return decimal === bestPrices(comparable).get(selectionKey(quote));
}
