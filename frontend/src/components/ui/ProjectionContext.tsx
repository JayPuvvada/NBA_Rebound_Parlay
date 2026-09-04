import { formatPercent } from "@/lib/format";
import type { ProjectionMetadata, ScheduleVerification } from "@/types/api";

interface ProjectionContextProps {
  metadata?: ProjectionMetadata | null;
  predictionEligible?: boolean;
  limitations?: string[];
  teamId?: number | null;
  schedule?: ScheduleVerification | null;
  className?: string;
}

export function ProjectionContext({ metadata, predictionEligible, limitations, teamId, schedule, className = "" }: ProjectionContextProps) {
  const effectiveEligibility = predictionEligible ?? metadata?.prediction_eligible;
  const uniqueLimitations = [...new Set([...(limitations ?? []), ...(metadata?.limitations ?? [])].filter(Boolean))];
  const weights = metadata?.recency_weights;
  const hasBaselines = Boolean(metadata?.pace_baseline || metadata?.miss_baseline);
  const technicalDetails = [
    teamId !== null && teamId !== undefined ? `Team ID ${teamId}` : null,
    schedule?.verified === true || metadata?.schedule_verified === true ? "Schedule verified" : null,
    schedule?.verified === false || metadata?.schedule_verified === false ? "Schedule unverified" : null,
    schedule?.status_text ? `Game status: ${schedule.status_text}` : schedule?.status !== null && schedule?.status !== undefined ? `Game status code ${schedule.status}` : metadata?.game_status !== null && metadata?.game_status !== undefined ? `Game status code ${metadata.game_status}` : null,
    schedule?.game_id ? `Game ID ${schedule.game_id}` : null,
    metadata?.historical_mode === true ? "Historical mode" : metadata?.historical_mode === false ? "Current/future mode" : null,
    metadata?.live_injuries_applied === true ? "Live injuries applied" : metadata?.live_injuries_applied === false ? "Live injuries not applied" : null,
    metadata?.data_cutoff ? `Stats cutoff ${metadata.data_cutoff}` : null,
    metadata?.team_source ? `Team source: ${metadata.team_source.replaceAll("_", " ")}` : null,
    metadata?.opponent_rebound_source ? `Opponent environment: ${metadata.opponent_rebound_source.replaceAll("_", " ")}` : null,
    metadata?.is_position_level_dvp === false ? "Opponent environment is team-level, not position-level DvP" : null,
    metadata?.rate_sample_size !== null && metadata?.rate_sample_size !== undefined ? `Rate sample ${metadata.rate_sample_size} games` : null,
    metadata?.variance_sample_size !== null && metadata?.variance_sample_size !== undefined ? `Variance sample ${metadata.variance_sample_size} games` : null,
    metadata?.trend_order ? `Trend order: ${metadata.trend_order.replaceAll("_", " ")}` : null,
    weights ? `Recency weights: season ${formatPercent(weights.season, 0)}, recent ${formatPercent(weights.recent, 0)}, opponent ${formatPercent(weights.opponent_history, 0)}` : null,
  ].filter((detail): detail is string => detail !== null);

  if (effectiveEligibility !== false && uniqueLimitations.length === 0 && technicalDetails.length === 0 && !hasBaselines) return null;

  return (
    <div className={`space-y-3 ${className}`}>
      {(effectiveEligibility === false || uniqueLimitations.length > 0) && (
        <div className="rounded-lg border border-yellow-900/40 bg-yellow-950/20 p-3 text-sm text-yellow-300" role="status">
          <strong>{effectiveEligibility === false ? "Analysis only — not eligible for a live pick" : "Data limitations"}</strong>
          {uniqueLimitations.length > 0 && (
            <ul className="mt-1 list-disc space-y-1 pl-5">
              {uniqueLimitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
            </ul>
          )}
        </div>
      )}

      {(technicalDetails.length > 0 || hasBaselines) && (
        <details className="rounded-lg border border-zinc-800 bg-zinc-900/30 px-3 py-2 text-xs text-zinc-500">
          <summary className="cursor-pointer font-semibold text-zinc-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400">Model data context</summary>
          <p className="mt-2 leading-relaxed">{technicalDetails.join(" · ")}</p>
          {hasBaselines && (
            <p className="mt-1 leading-relaxed">
              {metadata?.pace_baseline && `Pace baseline: ${metadata.pace_baseline}`}
              {metadata?.pace_baseline && metadata?.miss_baseline ? " · " : ""}
              {metadata?.miss_baseline && `Miss baseline: ${metadata.miss_baseline}`}
            </p>
          )}
        </details>
      )}
    </div>
  );
}
