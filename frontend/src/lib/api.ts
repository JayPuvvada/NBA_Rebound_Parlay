import type { ApiErrorPayload, CheatRow, CheatSheetOddsStatus, CheatSheetResponse } from "@/types/api";

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
  return typeof value === "object" && value !== null;
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) return fallback;
  const candidate = payload as ApiErrorPayload;
  return candidate.error || candidate.message || fallback;
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
    const response = await fetch(input, { ...init, signal: controller.signal });
    const raw = await response.text();
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
  if (Array.isArray(response)) {
    return {
      rows: response,
      generatedAt: response.find((row) => row.generated_at)?.generated_at,
      oddsSource: response.find((row) => row.odds_source)?.odds_source,
      warnings: [],
    };
  }

  if (!Array.isArray(response.projections)) {
    throw new ApiRequestError("The projection response had an unexpected shape.", "invalid-response");
  }

  return {
    rows: response.projections.map((row) => ({
      ...row,
      bookmaker: row.bookmaker ?? response.bookmaker,
      odds_source: row.odds_source ?? response.odds_source ?? response.odds?.source,
      odds_updated_at: row.odds_updated_at ?? response.odds?.fetched_at,
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
