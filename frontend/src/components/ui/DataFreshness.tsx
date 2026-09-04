import { formatTimestamp } from "@/lib/format";
import type { DataFreshness as DataFreshnessValue } from "@/types/api";

interface DataFreshnessProps {
  freshness?: DataFreshnessValue | string | null;
  className?: string;
}

function readableSource(value: string): string {
  return value.replaceAll("_", " ");
}

export function DataFreshness({ freshness, className = "" }: DataFreshnessProps) {
  if (!freshness) return null;
  if (typeof freshness === "string") {
    return <p className={`text-xs text-zinc-500 ${className}`}>Data: {freshness}</p>;
  }

  const injuries = freshness.injuries;
  const injuryUpdated = formatTimestamp(injuries?.fetched_at ?? freshness.injuries_updated_at);
  const statsUpdated = formatTimestamp(freshness.stats_updated_at);
  const generated = formatTimestamp(freshness.generated_at);
  const injuryStatus = injuries?.status?.toLowerCase() ?? null;
  const warningStatuses = new Set(["degraded", "unavailable", "not_loaded", "unknown"]);
  const stale = freshness.stale === true || injuries?.stale === true;
  const warning = stale || freshness.prediction_eligible === false || (injuryStatus !== null && warningStatuses.has(injuryStatus));

  const details = [
    freshness.as_of_date ? `As of ${freshness.as_of_date}` : null,
    freshness.nba_stats_cutoff ? `NBA stats through ${freshness.nba_stats_cutoff}` : null,
    statsUpdated ? `Stats updated ${statsUpdated}` : null,
    freshness.season ? `Season ${freshness.season}` : null,
    injuries?.status ? `Injuries: ${readableSource(injuries.status)}` : null,
    injuries?.source ? `via ${readableSource(injuries.source)}` : null,
    injuryUpdated ? `injury feed updated ${injuryUpdated}` : null,
    injuries?.entry_count !== null && injuries?.entry_count !== undefined ? `${injuries.entry_count} injury entries` : null,
    freshness.source ? `Source: ${readableSource(freshness.source)}` : null,
    freshness.odds_updated_at ? `Odds updated ${formatTimestamp(freshness.odds_updated_at)}` : null,
    freshness.note ?? null,
  ].filter((detail): detail is string => Boolean(detail));

  if (details.length === 0 && !generated && !warning) return null;

  return (
    <div
      className={`rounded-md border px-3 py-2 text-xs ${warning ? "border-yellow-900/40 bg-yellow-950/20 text-yellow-300" : "border-zinc-800 bg-zinc-900/40 text-zinc-500"} ${className}`}
      role="status"
    >
      <strong className={warning ? "text-yellow-200" : "text-zinc-400"}>
        {stale ? "Potentially stale data" : "Data freshness"}
      </strong>
      {details.length > 0 && <p className="mt-1 leading-relaxed">{details.join(" · ")}</p>}
      {details.length === 0 && generated && <p className="mt-1">Generated {generated}</p>}
    </div>
  );
}
