import { formatTimestamp } from "@/lib/format";
import type { DataFreshness as DataFreshnessValue } from "@/types/api";

export function DataFreshness({ freshness, className = "" }: {
  freshness?: DataFreshnessValue | string | null;
  className?: string;
}) {
  if (!freshness) return null;
  if (typeof freshness === "string") return <p className={"text-sm text-zinc-400 " + className}>{freshness}</p>;
  const injuries = freshness.injuries;
  const status = injuries?.status?.toLowerCase();
  const updated = formatTimestamp(injuries?.fetched_at ?? freshness.injuries_updated_at);
  const stale = freshness.stale === true || injuries?.stale === true;
  const warning = stale || (status !== undefined && status !== "available" && status !== "disabled");
  const description = stale
    ? "Injury information is stale. Verify player availability before betting."
    : status === "available"
      ? "Injury report available."
      : status === "disabled"
        ? "Live injuries are not applied to this date."
        : "Current injury information is not verified.";
  return (
    <div className={(warning ? "rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-amber-200 " : "text-zinc-400 ") + "text-xs " + className} role="status">
      <p>{description}{updated ? " Report timestamp: " + updated + "." : ""}</p>
      {freshness.note && <p className="mt-1">{freshness.note}</p>}
    </div>
  );
}
