import { formatPercent } from "@/lib/format";
import type { ProjectionMetrics } from "@/types/api";

interface PredictionIntervalsProps {
  metrics: ProjectionMetrics;
}

function intervalBounds(values?: number[]): string | null {
  if (!values || values.length < 2 || !Number.isFinite(values[0]) || !Number.isFinite(values[1])) return null;
  const display = (value: number) => Number.isInteger(value) ? String(value) : value.toFixed(1);
  return `${display(values[0])}–${display(values[1])} rebounds`;
}

function readable(value: string): string {
  return value.replaceAll("_", " ");
}

export function PredictionIntervals({ metrics }: PredictionIntervalsProps) {
  const interval68 = intervalBounds(metrics.prediction_interval_68);
  const interval95 = intervalBounds(metrics.prediction_interval_95);
  const unitDetails = [
    metrics.probability_unit ? `Probability unit: ${readable(metrics.probability_unit)}` : null,
    metrics.ev_roi_unit ? `EV unit: ${readable(metrics.ev_roi_unit)}` : null,
    metrics.kelly_unit ? `Kelly unit: ${readable(metrics.kelly_unit)}` : null,
  ].filter((detail): detail is string => detail !== null);

  if (!interval68 && !interval95 && unitDetails.length === 0) return null;

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-3 text-xs text-zinc-500">
      {(interval68 || interval95) && (
        <div className="grid gap-2 sm:grid-cols-2">
          {interval68 && (
            <p><strong className="text-zinc-300">68% prediction interval</strong><span className="block">{interval68}{metrics.prediction_interval_68_coverage !== null && metrics.prediction_interval_68_coverage !== undefined ? ` · ${formatPercent(metrics.prediction_interval_68_coverage)} simulated coverage` : ""}</span></p>
          )}
          {interval95 && (
            <p><strong className="text-zinc-300">95% prediction interval</strong><span className="block">{interval95}{metrics.prediction_interval_95_coverage !== null && metrics.prediction_interval_95_coverage !== undefined ? ` · ${formatPercent(metrics.prediction_interval_95_coverage)} simulated coverage` : ""}</span></p>
          )}
        </div>
      )}
      {(metrics.interval_method || unitDetails.length > 0) && (
        <p className={`${interval68 || interval95 ? "mt-2 border-t border-zinc-800 pt-2" : ""} leading-relaxed`}>
          {metrics.interval_method && `Method: ${readable(metrics.interval_method)}`}
          {metrics.interval_method && unitDetails.length > 0 ? " · " : ""}
          {unitDetails.join(" · ")}
        </p>
      )}
    </div>
  );
}
