import { formatAmericanOdds, formatPercent, formatSignedPercent } from "@/lib/format";
import type { Direction, ProjectionMetrics } from "@/types/api";

interface SideEvaluationsProps {
  evaluations?: ProjectionMetrics["side_evaluations"];
  selectedDirection?: Direction | null;
  selectedOdds?: number | null;
}

export function SideEvaluations({ evaluations, selectedDirection, selectedOdds }: SideEvaluationsProps) {
  if (!evaluations) return null;

  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">Side-by-side pricing</h3>
      <div className="grid gap-3 sm:grid-cols-2">
        {(["over", "under"] as const).map((side) => {
          const evaluation = evaluations[side];
          if (!evaluation) return null;
          const selected = evaluation.direction === selectedDirection && evaluation.american_odds === selectedOdds;
          return (
            <div key={side} className={`rounded-lg border p-3 ${selected ? "border-emerald-500/40 bg-emerald-500/5" : "border-zinc-800 bg-zinc-900/30"}`}>
              <div className="flex items-center justify-between">
                <strong className={evaluation.direction === "OVER" ? "text-emerald-400" : "text-red-400"}>{evaluation.direction}</strong>
                <span className="font-mono text-zinc-300">{formatAmericanOdds(evaluation.american_odds)}</span>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-zinc-500">
                <span>Win <b className="block text-zinc-300">{formatPercent(evaluation.confidence)}</b></span>
                <span>Edge <b className="block text-zinc-300">{formatSignedPercent(evaluation.edge)}</b></span>
                <span>EV <b className="block text-zinc-300">{formatSignedPercent(evaluation.ev_roi)}</b></span>
              </div>
              <p className="mt-2 text-xs text-zinc-500">{evaluation.tier || "Informational"}{selected ? " · actionable selection" : ""}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
