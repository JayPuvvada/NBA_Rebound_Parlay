import type { ApiErrorPayload, CheatRow, CheatSheetOddsStatus, CheatSheetResponse, GamesResponse, PredictResponse } from "@/types/api";

export type RequestFailureKind = "http" | "network" | "timeout" | "aborted" | "invalid-response";

export class ApiRequestError extends Error {
  readonly kind: RequestFailureKind;
  readonly status?: number;

  constructor(message: string, kind: RequestFailureKind, status?: number) {
    super(message);
    this.name = "ApiRequestError";
    this.kind = kind;
    this.status = status;
  }
}

interface FetchJsonOptions {
  timeoutMs?: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optionalText(value: unknown): boolean {
  return value == null || typeof value === 'string';
}

function optionalBoolean(value: unknown): boolean {
  return value == null || typeof value === 'boolean';
}

function optionalTextList(value: unknown): boolean {
  return value == null || (Array.isArray(value) && value.every(item => typeof item === 'string'));
}

function validRiskFields(value: Record<string, unknown>): boolean {
  return optionalBoolean(value.prediction_eligible) && optionalTextList(value.limitations);
}

function validProjectionSource(value: unknown): boolean {
  return value == null || (isRecord(value)
    && optionalText(value.status) && optionalText(value.source) && optionalTextList(value.limitations));
}

function validRiskContext(value: unknown): boolean {
  return value == null || (isRecord(value) && validRiskFields(value)
    && validProjectionSource(value.projection_inputs));
}

// TypeScript types do not validate JSON. Reject malformed risk fields rather
// than dropping warnings or allowing a malformed false flag to look eligible.
function validProjectionContext(value: Record<string, unknown>): boolean {
  if (!validRiskFields(value) || !validRiskContext(value.metadata)) return false;
  const freshness = value.data_freshness;
  if (freshness != null && typeof freshness !== 'string') {
    if (!isRecord(freshness) || !validRiskContext(freshness)
      || !optionalText(freshness.note) || !optionalText(freshness.injuries_updated_at)
      || !optionalBoolean(freshness.stale)) return false;
    const injuries = freshness.injuries;
    if (injuries != null && (!isRecord(injuries)
      || !optionalText(injuries.status) || !optionalText(injuries.fetched_at)
      || !optionalBoolean(injuries.stale))) return false;
  }
  const injuries = value.injuries;
  return injuries == null || (isRecord(injuries)
    && optionalText(injuries.matchup) && optionalText(injuries.team)
    && optionalTextList(injuries.team_list) && optionalTextList(injuries.opp_list));
}

function validProvenance(value: unknown): boolean {
  return isRecord(value)
    && ['bookmaker', 'odds_source', 'odds_updated_at', 'generated_at'].every(key => optionalText(value[key]));
}

function validOddsStatus(value: unknown): boolean {
  return value == null || (isRecord(value)
    && ['error', 'source', 'updated_at', 'fetched_at'].every(key => optionalText(value[key]))
    && optionalBoolean(value.available) && optionalBoolean(value.fresh));
}

export function validateGamesResponse(value: unknown): GamesResponse {
  const team = (candidate: unknown): candidate is string =>
    typeof candidate === 'string' && /^[A-Z]{2,3}$/.test(candidate);
  if (!isRecord(value) || !Array.isArray(value.games) || value.games.some(game =>
    !isRecord(game) || !team(game.home) || !team(game.away) || game.home === game.away
    || (game.is_preseason !== undefined && typeof game.is_preseason !== 'boolean')
    || ['id', 'game_id'].some(key => game[key] !== undefined && typeof game[key] !== 'string')
  ) || (value.message !== undefined && typeof value.message !== 'string')) {
    throw new ApiRequestError('The schedule response contained invalid game data. Please retry.', 'invalid-response');
  }
  return value as unknown as GamesResponse;
}

export function validatePredictResponse(value: unknown): PredictResponse {
  if (!isRecord(value) || typeof value.player !== 'string' || !value.player.trim()
    || typeof value.projection !== 'number' || !Number.isFinite(value.projection)
    || value.projection < 0 || typeof value.home_game !== 'boolean'
    || !validProjectionContext(value) || !validProvenance(value)) {
    throw new ApiRequestError('The projection response contained missing or invalid player data. Please retry.', 'invalid-response');
  }
  return value as unknown as PredictResponse;
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) return fallback;
  const candidate = payload as ApiErrorPayload;
  for (const value of [candidate.error, candidate.message]) {
    if (typeof value === 'string' && value.trim()) return value;
  }
  return fallback;
}

export async function fetchJson<T>(
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: FetchJsonOptions = {},
): Promise<T> {
  const timeoutMs = options.timeoutMs ?? 30_000;
  const controller = new AbortController();
  let timedOut = false;

  const abortFromCaller = () => controller.abort();
  if (init.signal?.aborted) controller.abort();
  else init.signal?.addEventListener("abort", abortFromCaller, { once: true });

  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    if (controller.signal.aborted) throw new Error('Request cancelled');
    const response = await fetch(input, { ...init, signal: controller.signal });
    const raw = await response.text();
    // Some mocked/custom fetch implementations resolve despite cancellation.
    // Do not hand a late response back to a newer UI request.
    if (controller.signal.aborted) throw new Error('Request cancelled');
    let payload: unknown = null;

    if (raw) {
      try {
        payload = JSON.parse(raw) as unknown;
      } catch {
        if (!response.ok) {
          throw new ApiRequestError(
            `Server returned ${response.status} ${response.statusText || "request error"}.`,
            "http",
            response.status,
          );
        }
        throw new ApiRequestError("Server returned an invalid JSON response.", "invalid-response", response.status);
      }
    }

    if (!response.ok) {
      throw new ApiRequestError(
        errorMessage(payload, `Server returned ${response.status} ${response.statusText || "request error"}.`),
        "http",
        response.status,
      );
    }

    if (!raw.trim()) {
      throw new ApiRequestError('Server returned an empty JSON response.', 'invalid-response', response.status);
    }

    return payload as T;
  } catch (error: unknown) {
    if (error instanceof ApiRequestError) throw error;
    if (controller.signal.aborted) {
      if (timedOut) {
        throw new ApiRequestError(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds.`, "timeout");
      }
      throw new ApiRequestError("Request cancelled.", "aborted");
    }
    const message = error instanceof Error ? error.message : "Unknown network error";
    throw new ApiRequestError(`Could not reach the server. ${message}`, "network");
  } finally {
    window.clearTimeout(timer);
    init.signal?.removeEventListener("abort", abortFromCaller);
  }
}

export function unwrapCheatSheet(response: CheatSheetResponse): {
  rows: CheatRow[];
  generatedAt?: string | null;
  oddsSource?: string | null;
  odds?: CheatSheetOddsStatus;
  warnings: string[];
} {
  const rows: unknown = Array.isArray(response) ? response : isRecord(response) ? response.projections : null;
  if (!Array.isArray(rows) || rows.some(row =>
    !isRecord(row) || typeof row.player !== 'string' || !row.player.trim()
    || typeof row.projection !== 'number' || !Number.isFinite(row.projection) || row.projection < 0
    || !validProjectionContext(row) || !validProvenance(row)
  )) {
    throw new ApiRequestError('The projection response contained missing or invalid player data. Please retry.', 'invalid-response');
  }
  if (Array.isArray(response)) {
    return {
      rows: response,
      generatedAt: response.find((row) => row.generated_at)?.generated_at,
      oddsSource: response.find((row) => row.odds_source)?.odds_source,
      warnings: [],
    };
  }

  if (!Array.isArray(response.projections) || !validProvenance(response)
    || !validOddsStatus(response.odds)) {
    throw new ApiRequestError("The projection response had an unexpected shape.", "invalid-response");
  }

  return {
    rows: response.projections.map((row) => ({
      ...row,
      bookmaker: row.bookmaker ?? response.bookmaker,
      odds_source: row.odds_source ?? response.odds_source ?? response.odds?.source,
      // Download time is not the sportsbook's quote update time.
      odds_updated_at: row.odds_updated_at ?? response.odds?.updated_at,
      generated_at: row.generated_at ?? response.generated_at,
    })),
    generatedAt: response.generated_at,
    oddsSource: response.odds_source ?? response.odds?.source,
    odds: response.odds,
    warnings: Array.isArray(response.warnings)
      ? response.warnings.filter((warning): warning is string => typeof warning === "string" && warning.trim().length > 0)
      : [],
  };
}
