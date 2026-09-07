import { lazy, Suspense } from "react";
import { DataFreshness } from "./DataFreshness";
import { SavePickControl } from "./SavePickControl";
import { formatAmericanOdds, formatPercent, formatSignedPercent, formatTimestamp } from "@/lib/format";
import { bettingView, noBetReason } from "@/lib/betting";
import type { CheatRange, MarketOdds, ProjectionBase, ProjectionMetrics, SimulationRange } from "@/types/api";

const TrendChart = lazy(() => import("./TrendChart").then(module => ({ default: module.TrendChart })));

interface Props {
  data: ProjectionBase;
  metrics?: ProjectionMetrics | null;
  range?: CheatRange | SimulationRange | string | null;
  marketOdds?: MarketOdds;
  manual?: boolean;
}

export function BettingAnalysis({ data, metrics: rawMetrics, range, marketOdds, manual = false }: Props) {
  const metrics = rawMetrics ?? {};
  const { eligible, direction, limitations } = bettingView(data, metrics);
  const line = metrics.line ?? null;
  const interval = metrics.prediction_interval_68 ?? (range && typeof range === "object" ? [range.low, range.high] : null);
  const minutes = data.components?.["Proj Minutes"];
  const blowout = data.components?.Blowout;
  const highVariance = metrics.variance?.high_variance || metrics.high_variance_flag;
  const quoteTime = formatTimestamp(metrics.odds_updated_at);
  const generated = formatTimestamp(data.generated_at);
  const injuries = data.injuries;
  const matchupAlert = injuries?.matchup && injuries.matchup.toLowerCase() !== "active" ? injuries.matchup : null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white">{data.player}</h2>
          <p className="mt-1 text-sm text-zinc-400">
            {data.team ? data.team + " · " : ""}vs {data.opponent}
            {data.date ? " · " + data.date : ""}
            {typeof data.home_game === "boolean" ? (data.home_game ? " · Home" : " · Away") : ""}
          </p>
          {generated && <p className="mt-1 text-xs text-zinc-500">Projection generated {generated}</p>}
        </div>
        <div className="rounded-lg bg-zinc-900 px-5 py-3">
          <p className="text-xs text-zinc-400">Projected rebounds</p>
          <p className="text-3xl font-bold text-indigo-300">{data.projection}</p>
        </div>
      </div>

      <div className={"rounded-lg border p-4 " + (direction ? "border-emerald-800 bg-emerald-950/20" : "border-zinc-700 bg-zinc-900/50")}>
        <p className="text-xs font-semibold uppercase tracking-wider text-zinc-400">Model recommendation</p>
        <p className={"mt-1 text-xl font-bold " + (direction ? "text-emerald-300" : "text-zinc-200")}>
          {direction ? direction + " " + line + " at " + formatAmericanOdds(metrics.american_odds) : "NO BET"}
        </p>
        <p className="mt-2 text-sm text-zinc-400">
          {direction ? "This side meets the model's rules at the shown price. Confirm the odds and player availability before deciding." : noBetReason(metrics, eligible)}
        </p>
      </div>

      <SavePickControl data={data} metrics={metrics} />
      {limitations.length > 0 && (
        <div className="rounded-lg border border-yellow-900/50 bg-yellow-950/20 p-3 text-sm text-yellow-200" role="status">
          <p className="font-semibold">Before you decide</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">{limitations.map(note => <li key={note}>{note}</li>)}</ul>
        </div>
      )}
      <DataFreshness freshness={data.data_freshness} />

      {line !== null && (
        <section aria-label="Compare Over and Under" className="space-y-3">
          <div className="flex flex-wrap justify-between gap-2 text-xs text-zinc-400">
            <span>{metrics.bookmaker || (manual ? "Your entered prices" : "Sportsbook prices")}</span>
            <span>{manual ? "Manually entered · not independently verified" : quoteTime ? "Quote updated " + quoteTime : "Quote update time unavailable"}</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {(["over", "under"] as const).map(side => {
              const evaluation = metrics.side_evaluations?.[side];
              const quote = marketOdds?.[side];
              const sideName = side === "over" ? "OVER" : "UNDER";
              const selectedSide = metrics.evaluated_side ?? metrics.odds_side ?? metrics.direction;
              const isEvaluated = selectedSide === sideName;
              const sideLine = quote?.line ?? line;
              const price = quote?.odds ?? evaluation?.american_odds ?? (isEvaluated ? metrics.american_odds : null);
              // Different lines must keep their own probability, never reuse the selected line's value.
              const probability = evaluation?.confidence ?? (sideLine === line ? (side === "over" ? metrics.over_probability : metrics.under_probability) : null);
              const ev = evaluation?.ev_roi ?? (isEvaluated ? metrics.ev_roi : null);
              const showReturn = eligible && metrics.tier !== "STALE_ODDS" && price != null && ev != null;
              return (
                <div key={side} className={"rounded-lg border p-4 " + (direction === sideName ? "border-emerald-600 bg-emerald-950/10" : "border-zinc-800 bg-zinc-900/30")}>
                  <div className="flex flex-wrap justify-between gap-2">
                    <h3 className="font-semibold text-zinc-200">{sideName} {sideLine}</h3>
                    <span className="font-mono text-zinc-300">{price != null ? formatAmericanOdds(price) : "No price"}</span>
                  </div>
                  <p className="mt-3 text-xs text-zinc-400">Model win probability</p>
                  <p className="text-2xl font-semibold text-indigo-300">{formatPercent(probability)}</p>
                  {showReturn && <p className="mt-2 text-sm text-zinc-300">Expected return <strong>{formatSignedPercent(ev)}</strong></p>}
                </div>
              );
            })}
          </div>
          {Number.isInteger(line) && <p className="text-xs text-zinc-400">Exactly {line} rebounds: {formatPercent(metrics.push_probability)} push probability at this line (stake returned).</p>}
          <p className="text-xs leading-relaxed text-zinc-500">Expected return is the model's estimated net return per amount staked, not a guaranteed profit. {!eligible && "Return estimates are hidden while the data or game status is unverified."}</p>
        </section>
      )}

      {(interval || typeof minutes === "number") && <div className="flex flex-wrap gap-x-8 gap-y-3 rounded-lg bg-zinc-900/40 p-4 text-sm">
        {interval && interval.length >= 2 && (
          <div><p className="text-zinc-400">Rebound range · central 68%</p><p className="mt-1 font-semibold text-zinc-200">{interval[0]}–{interval[1]} rebounds</p><p className="mt-1 text-xs text-zinc-500">Outcomes can fall outside this range.</p></div>
        )}
        {typeof minutes === "number" && <div><p className="text-zinc-400">Projected minutes</p><p className="mt-1 font-semibold text-zinc-200">{minutes.toFixed(1)}</p></div>}
      </div>}
      {(highVariance || (blowout && blowout !== "None")) && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">
          {highVariance && <p>Rebound totals have varied widely. Treat the probability estimate with extra caution.</p>}
          {blowout && blowout !== "None" && <p>Spread-related minutes risk: {String(blowout).toLowerCase()}. A lopsided game could reduce playing time.</p>}
        </div>
      )}

      {data.trend && data.trend.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-zinc-200">Last {data.trend.length} appearances</h3>
          <Suspense fallback={<div className="h-[180px] animate-pulse rounded bg-zinc-900/40" />}>
            <TrendChart data={data.trend} line={line} direction={direction} height={180} />
          </Suspense>
          <p className="mt-2 text-xs text-zinc-500">Past rebound totals, not a forecast. {direction ? "Colors compare each game with the recommended side at the shown line." : "No recommended side; bars are neutral."}</p>
        </section>
      )}

      {(matchupAlert || injuries?.team) && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">
          {matchupAlert && <p>Opponent matchup availability: {matchupAlert}</p>}
          {injuries?.team && <p>Teammate availability affecting the projection: {injuries.team}</p>}
        </div>
      )}
      {injuries && (
        <details className="rounded-lg border border-zinc-800 p-3">
          <summary className="cursor-pointer text-sm font-semibold text-zinc-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400">Team and opponent injury reports</summary>
          <div className="mt-3 grid gap-4 text-sm sm:grid-cols-2">
            {[{ label: "Team", list: injuries.team_list }, { label: "Opponent", list: injuries.opp_list }].map(group => (
              <div key={group.label}><h4 className="font-medium text-zinc-300">{group.label}</h4>
                {group.list?.length ? <ul className="mt-1 list-disc space-y-1 pl-4 text-zinc-400">{group.list.map(item => <li key={item}>{item}</li>)}</ul> : <p className="mt-1 text-zinc-500">No entries available. This does not confirm a healthy roster.</p>}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
