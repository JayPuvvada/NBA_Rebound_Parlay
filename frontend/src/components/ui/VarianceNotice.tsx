import type { ProjectionMetrics, VarianceInfo } from "@/types/api";

interface VarianceNoticeProps {
  metrics: ProjectionMetrics;
}

function varianceFromMetrics(metrics: ProjectionMetrics): VarianceInfo | null {
  if (metrics.variance) return metrics.variance;
  if (metrics.fano === null || metrics.fano === undefined) return null;
  return {
    fano: metrics.fano,
    source: metrics.fano_source,
    high_variance: metrics.high_variance_flag,
  };
}

export function VarianceNotice({ metrics }: VarianceNoticeProps) {
  const variance = varianceFromMetrics(metrics);
  if (!variance) return null;

  const empirical = variance.source === "empirical";
  const highVariance = variance.high_variance === true;

  return (
    <div
      className={`rounded-lg border px-3 py-2 text-sm ${
        highVariance
          ? "border-red-800/40 bg-red-950/30 text-red-300"
          : empirical
            ? "border-emerald-800/30 bg-emerald-900/20 text-emerald-300"
            : "border-yellow-800/30 bg-yellow-900/20 text-yellow-300"
      }`}
      role={highVariance ? "alert" : "status"}
    >
      <span aria-hidden="true">{highVariance ? "🔴" : empirical ? "🟢" : "🟡"}</span>{" "}
      {highVariance ? "High game-to-game variance" : `Variance based on ${empirical ? "player data" : "an estimate"}`}
      {variance.fano !== null && variance.fano !== undefined && ` (Fano ${variance.fano.toFixed(2)})`}
      {variance.sample_size !== null && variance.sample_size !== undefined && ` · ${variance.sample_size} games`}
      {highVariance && ". Treat the probability estimate with extra caution."}
    </div>
  );
}
