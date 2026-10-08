import { bettingView } from "./betting";
import type { ProjectionBase, ProjectionMetrics } from "@/types/api";

export const PICKS_KEY = "nba.personal-demo.picks.v1";
export const SESSION_KEY = "nba.personal-demo.session.v1";
export type PickResult = "Pending" | "Win" | "Loss" | "Push" | "Void";
export interface SavedPick {
  id: string;
  player: string | null;
  opponent: string;
  date: string;
  projection: number | null;
  direction: "OVER" | "UNDER" | null;
  line: number | null;
  odds: number;
  bookmaker: string;
  savedAt: string;
  result: PickResult;
  demo: boolean;
  version?: 1 | 2;
  kind?: "manual_pick" | "model_pick" | "experimental_model_pick";
  fingerprint?: string;
  sport?: string;
  event_id?: string | null;
  home?: string;
  away?: string;
  market?: string;
  selection?: string;
  team?: string | null;
  quote_updated_at?: string | null;
  quote_fetched_at?: string | null;
  source?: string | null;
  model_version?: string | null;
  profile?: string | null;
  assumptions?: unknown;
  analysis?: unknown;
  model_generated_at?: string | null;
  notes?: string;
}

export interface SelectionQuote {
  market: string; selection: string; player?: string | null; team?: string | null;
  line: number | null; odds: number; book: string; updated_at?: string | null;
  fetched_at?: string | null; source?: string | null; event_id?: string | null;
}
export interface SelectionContext {
  date: string; home: string; away: string; sport: string; event_id?: string | null; demo?: boolean;
}
export interface SelectionAssessment {
  projection?: number | null; model_version?: string | null; profile?: string | null;
  assumptions?: unknown; analysis?: unknown; result_kind?: string; generated_at?: string | null;
}
function canonical(value: unknown): string {
  if (value === undefined || value === null) return "null";
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value === "object") return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical((value as Record<string, unknown>)[k])}`).join(",")}}`;
  return JSON.stringify(value);
}

/** Exact quote plus material model inputs; click time, annotations and results are excluded. */
export function buildSelectionSnapshot(quote: SelectionQuote, context: SelectionContext, assessment?: SelectionAssessment): SavedPick {
  const kind: NonNullable<SavedPick['kind']> = !assessment ? "manual_pick" : /experimental|preseason/i.test(`${assessment.result_kind} ${assessment.profile}`) ? "experimental_model_pick" : "model_pick";
  const immutable = {
    version: 2 as const, kind, player: quote.player || null, opponent: `${context.away} @ ${context.home}`,
    date: context.date, projection: assessment?.projection ?? null,
    direction: /^(over|under)$/i.test(quote.selection) ? quote.selection.toUpperCase() as "OVER" | "UNDER" : null,
    line: quote.line, odds: quote.odds, bookmaker: quote.book, demo: context.demo === true || quote.source === 'synthetic-local-test',
    sport: context.sport, event_id: quote.event_id || context.event_id || null, home: context.home, away: context.away,
    market: quote.market, selection: quote.selection, team: quote.team || null,
    quote_updated_at: quote.updated_at || null, quote_fetched_at: quote.fetched_at || null, source: quote.source || null,
    model_version: assessment?.model_version || null, profile: assessment?.profile || null,
    assumptions: assessment?.assumptions ?? null, analysis: assessment?.analysis ?? null,
    model_generated_at: assessment?.generated_at || null,
  };
  // Canonical content is collision-free and Postgres hashes it for its unique index.
  const fingerprint = canonical({ ...immutable, quote_updated_at: null, quote_fetched_at: null, model_generated_at: null });
  const pick: SavedPick = { ...structuredClone(immutable), id: crypto.randomUUID(), fingerprint, savedAt: new Date().toISOString(), result: "Pending", notes: "" };
  if (!isSavedPick(pick)) throw Error("A complete event, selection, sportsbook and valid price are required to save a pick.");
  return pick;
}

export function demoEnabled(flag: unknown, hostname: string) {
  return flag === "true" && ["localhost", "127.0.0.1", "[::1]"].includes(hostname);
}

// Public demo credentials, deliberately NOT authentication or server access.
export function demoCredentials(username: string, password: string) {
  return username.trim() === "jay" && password === "demo123";
}

export function snapshotPick(data: ProjectionBase, metrics: ProjectionMetrics, demo = true): SavedPick {
  const { direction } = bettingView(data, metrics);
  if (!direction || !data.date || !Number.isFinite(data.projection)) {
    throw new Error("Only a qualifying, dated model recommendation can be saved.");
  }
  const line = metrics.line!;
  const odds = metrics.american_odds!;
  return {
    id: JSON.stringify([data.player, data.opponent, data.date, direction, line, odds, metrics.bookmaker || "Entered price", demo ? "sample" : "model"]),
    player: data.player, opponent: data.opponent, date: data.date,
    projection: data.projection, direction, line, odds,
    bookmaker: metrics.bookmaker || "Entered price", savedAt: new Date().toISOString(),
    result: "Pending", demo,
  };
}

export function isSavedPick(value: unknown): value is SavedPick {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const p = value as Record<string, unknown>;
  if (p.version === 2) {
    const text = (v: unknown) => typeof v === 'string' && v.trim().length > 0;
    return [p.id,p.opponent,p.date,p.bookmaker,p.savedAt,p.fingerprint,p.sport,p.home,p.away,p.market,p.selection].every(text)
      && /^\d{4}-\d{2}-\d{2}$/.test(p.date as string) && Number.isFinite(Date.parse(p.date as string))
      && ['h2h','spreads','totals','player_rebounds'].includes(p.market as string)
      && ['manual_pick','model_pick','experimental_model_pick'].includes(p.kind as string)
      && (p.player === null || text(p.player)) && (p.projection === null || typeof p.projection === 'number' && Number.isFinite(p.projection) && p.projection >= 0)
      && (p.direction === null || p.direction === 'OVER' || p.direction === 'UNDER')
      && (p.market !== 'player_rebounds' || text(p.player) && p.direction !== null)
      && (p.kind !== 'manual_pick' || p.projection === null)
      && (['h2h','spreads'].includes(p.market as string) ? [p.home,p.away].includes(p.selection) && p.direction === null : ['OVER','UNDER'].includes(p.selection as string) && p.direction === p.selection)
      && (p.kind === 'manual_pick' || p.market === 'player_rebounds' && p.projection !== null && text(p.model_version) && text(p.profile))
      && (p.market === 'h2h' ? p.line === null : typeof p.line === 'number' && Number.isFinite(p.line) && (p.market === 'spreads' || p.line >= 0))
      && typeof p.odds === 'number' && Number.isInteger(p.odds) && Math.abs(p.odds) >= 100 && Math.abs(p.odds) <= 100000
      && ['Pending','Win','Loss','Push','Void'].includes(p.result as string) && typeof p.demo === 'boolean'
      && (p.notes === undefined || typeof p.notes === 'string' && p.notes.length <= 5000);
  }
  if (p.version !== undefined && p.version !== 1) return false;
  return [p.id, p.player, p.opponent, p.date, p.bookmaker, p.savedAt]
    .every(v => typeof v === 'string' && v.trim().length > 0)
    && [p.projection, p.line, p.odds].every(v => typeof v === 'number' && Number.isFinite(v))
    && (p.projection as number) >= 0 && (p.line as number) >= 0
    && Math.abs(p.odds as number) >= 100
    && (p.direction === 'OVER' || p.direction === 'UNDER')
    && ['Pending', 'Win', 'Loss', 'Push', 'Void'].includes(p.result as string)
    && typeof p.demo === 'boolean';
}

export function decodePicks(rows: unknown[]): { picks: SavedPick[]; skipped: number } {
  const picks = rows.filter(isSavedPick);
  return { picks, skipped: rows.length - picks.length };
}

export function picksCsv(picks: SavedPick[]): string {
  const cell = (value: unknown) => {
    let text = value == null ? "" : typeof value === 'object' ? canonical(value) : String(value);
    if (/^[\s]*[=+\-@]/.test(text)) text = "'" + text;
    return `"${text.replaceAll('"', '""')}"`;
  };
  const fields: (keyof SavedPick)[] = ['id','version','kind','date','sport','event_id','home','away','player','market','selection','direction','line','odds','bookmaker','projection','model_version','profile','assumptions','quote_updated_at','quote_fetched_at','savedAt','demo','result','notes'];
  return [fields.join(','), ...picks.map(p => fields.map(f => cell(p[f])).join(','))].join('\r\n');
}

export function readPicks(storage: Pick<Storage, "getItem">): SavedPick[] {
  const raw = storage.getItem(PICKS_KEY);
  if (raw === null) return [];
  const value: unknown = JSON.parse(raw);
  if (!Array.isArray(value) || !value.every(p => isSavedPick(p) && p.demo === true)) {
    throw new Error("Invalid saved-pick data");
  }
  return value;
}

export function writePicks(storage: Pick<Storage, "setItem">, picks: SavedPick[], signedIn: boolean) {
  if (!signedIn) throw new Error("Sign in to the test profile first.");
  storage.setItem(PICKS_KEY, JSON.stringify(picks));
}
export interface NoteDraft { base: string; value: string; conflict: boolean; }
export function reconcileNoteDraft(draft: NoteDraft, saved: string): NoteDraft {
  if (draft.base === saved) return draft;
  if (draft.value === draft.base || draft.value === saved) return { base: saved, value: saved, conflict: false };
  return { base: saved, value: draft.value, conflict: true };
}
