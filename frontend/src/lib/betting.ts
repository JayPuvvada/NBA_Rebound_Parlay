import type { Direction, ProjectionBase, ProjectionMetrics } from "@/types/api";

/** Return estimates are valid only for the side, line and price evaluated. */
export function sideExpectedReturn(metrics: ProjectionMetrics, side: Direction, line: number, price: number | null | undefined): number | null {
  if (!Number.isFinite(line) || line < 0 || typeof price !== 'number'
    || !Number.isInteger(price) || Math.abs(price) < 100) return null;
  const evaluation = metrics.side_evaluations?.[side === 'OVER' ? 'over' : 'under'];
  // Side evaluations are paired with their corresponding market quote by the
  // API, including when the Over and Under have different lines.
  if (evaluation?.direction === side && evaluation.american_odds === price
    && typeof evaluation.ev_roi === 'number' && Number.isFinite(evaluation.ev_roi)) {
    return evaluation.ev_roi;
  }
  const selectedSides = [metrics.evaluated_side, metrics.odds_side, metrics.direction].filter(value => value != null);
  if (selectedSides.length > 0 && selectedSides.every(value => value === side)
    && metrics.line === line && metrics.american_odds === price
    && typeof metrics.ev_roi === 'number' && Number.isFinite(metrics.ev_roi)) {
    return metrics.ev_roi;
  }
  return null;
}

/** Presentation guards only: never create a pick that the backend did not issue. */
export function bettingView(data: ProjectionBase, metrics: ProjectionMetrics = {}) {
  const freshness = typeof data.data_freshness === "object" ? data.data_freshness : null;
  const eligibility = [data.prediction_eligible, data.metadata?.prediction_eligible, freshness?.prediction_eligible];
  const sources = [data.metadata?.projection_inputs, freshness?.projection_inputs];
  const blocked = eligibility.includes(false) || sources.some(source => source?.status && source.status !== "primary");
  const eligible = !blocked && eligibility.includes(true);
  const validPrice = typeof metrics.american_odds === "number" && Number.isInteger(metrics.american_odds) && Math.abs(metrics.american_odds) >= 100;
  const validLine = typeof metrics.line === "number" && Number.isFinite(metrics.line) && metrics.line >= 0;
  const blockedTier = ["STALE_ODDS", "GAME_NOT_PREGAME", "HISTORICAL_CONTEXT_INCOMPLETE", "AVOID", "NO_PRICE", "LOW_VOLUME", "INSUFFICIENT_DATA"].includes(metrics.tier ?? "");
  const direction = eligible && metrics.actionable === true && validPrice && validLine && !blockedTier
    && (metrics.direction === "OVER" || metrics.direction === "UNDER") ? metrics.direction : null;
  const limitations = [...new Set([
    ...(data.limitations ?? []),
    ...(data.metadata?.limitations ?? []),
    ...(freshness?.limitations ?? []),
    ...sources.flatMap(source => source?.limitations ?? []),
  ].filter(Boolean))];
  return { eligible, direction, limitations, freshness };
}

export function noBetReason(metrics: ProjectionMetrics, eligible: boolean): string {
  if (!eligible) return "Data or game status is not verified for a live pick. Treat these numbers as analysis only.";
  if (metrics.line == null) return "Add a rebound line and its odds to compare a bet.";
  if (metrics.american_odds == null) return "No price supplied. Win probability alone does not establish value.";
  switch (metrics.tier) {
    case "LOW_VOLUME": return "Projected rebounds are too low for a supported pick.";
    case "INSUFFICIENT_DATA": return "There are too few recent games to support a pick.";
    case "STALE_ODDS": return "This quote is stale or its update time is unknown.";
    case "GAME_NOT_PREGAME": return "This game is not verified as pregame.";
    default: return "Neither offered side meets the model's price and evidence requirements.";
  }
}
