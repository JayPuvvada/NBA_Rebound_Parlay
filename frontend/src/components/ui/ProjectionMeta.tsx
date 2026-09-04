import { formatAmericanOdds, formatTimestamp } from "@/lib/format";
import type { Direction } from "@/types/api";

interface ProjectionMetaProps {
  americanOdds?: number | null;
  oddsSide?: Direction | null;
  bookmaker?: string | null;
  oddsSource?: string | null;
  oddsUpdatedAt?: string | null;
  generatedAt?: string | null;
}

export function ProjectionMeta({
  americanOdds,
  oddsSide,
  bookmaker,
  oddsSource,
  oddsUpdatedAt,
  generatedAt,
}: ProjectionMetaProps) {
  const updated = formatTimestamp(oddsUpdatedAt || generatedAt);
  const hasPrice = americanOdds !== null && americanOdds !== undefined;

  if (!hasPrice && !bookmaker && !oddsSource && !updated) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500" aria-label="Odds provenance">
      {hasPrice && (
        <span className="font-medium text-zinc-300">
          {oddsSide ? `${oddsSide} ` : ""}{formatAmericanOdds(americanOdds)}
        </span>
      )}
      {bookmaker && <span>{bookmaker}</span>}
      {oddsSource && <span>Source: {oddsSource}</span>}
      {updated && <span>Updated <time dateTime={oddsUpdatedAt || generatedAt || undefined}>{updated}</time></span>}
    </div>
  );
}
