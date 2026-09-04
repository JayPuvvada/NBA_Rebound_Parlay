import type { ComponentBreakdown, ComponentValue } from "@/types/api";

interface FactorBreakdownProps {
  components?: ComponentBreakdown;
  compact?: boolean;
}

const MULTIPLIER_KEYS = new Set([
  "Env Mult (Final)",
  "Raw Mult",
  "Pace",
  "Opp",
  "DvP",
  "Matchup",
  "Pace Factor",
  "Opp Defense",
  "DvP Mult",
  "Matchup Adj",
  "Home/Away",
  "Rest Factor",
]);

function multiplierLabel(value: number): { label: string; colorClass: string } {
  if (value >= 1.05) return { label: "Great boost", colorClass: "text-emerald-400" };
  if (value >= 1.01) return { label: "Favorable", colorClass: "text-green-400" };
  if (value <= 0.95) return { label: "Very tough", colorClass: "text-red-400" };
  if (value <= 0.99) return { label: "Difficult", colorClass: "text-yellow-400" };
  return { label: "Neutral", colorClass: "text-zinc-500" };
}

function formatComponent(key: string, value: ComponentValue): string {
  if (typeof value === "string") return value;
  if (key === "DNP Rate") return `${(value * 100).toFixed(0)}%`;
  if (key.includes("Minutes") || key.includes("Base Rebs") || key === "Base") return value.toFixed(1);
  if (MULTIPLIER_KEYS.has(key)) return `${value.toFixed(2)}x`;
  return Number.isInteger(value) ? `${value}` : value.toFixed(2);
}

export function FactorBreakdown({ components, compact = false }: FactorBreakdownProps) {
  if (!components || Object.keys(components).length === 0) return null;

  return (
    <div>
      <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">Factor breakdown</h4>
      <div className={compact ? "grid gap-1 sm:grid-cols-2" : "space-y-1.5"}>
        {Object.entries(components).map(([key, value]) => {
          const isMultiplier = typeof value === "number" && MULTIPLIER_KEYS.has(key);
          const signal = isMultiplier ? multiplierLabel(value) : null;
          const isBase = key.includes("Base") || key.includes("Proj");

          return (
            <div key={key} className="flex items-center justify-between gap-3 rounded px-3 py-1.5 hover:bg-zinc-800/30">
              <span className="text-sm text-zinc-300">{key}</span>
              <div className="flex shrink-0 items-center gap-2">
                {signal && <span className={`text-xs ${signal.colorClass}`}>{signal.label}</span>}
                <span className={`font-mono text-sm ${isBase ? "font-bold text-indigo-300" : "text-zinc-500"}`}>
                  {formatComponent(key, value)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
