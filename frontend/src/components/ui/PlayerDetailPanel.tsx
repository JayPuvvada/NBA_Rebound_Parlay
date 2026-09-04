import { lazy, Suspense } from "react";
import { DataFreshness } from "./DataFreshness";
import { FactorBreakdown } from "./FactorBreakdown";
import { MarkdownText } from "./MarkdownText";
import { PredictionIntervals } from "./PredictionIntervals";
import { ProjectionMeta } from "./ProjectionMeta";
import { ProjectionContext } from "./ProjectionContext";
import { SideEvaluations } from "./SideEvaluations";
import { VarianceNotice } from "./VarianceNotice";
import { formatPercent, formatSignedPercent } from "@/lib/format";
import type { CheatRow } from "@/types/api";

const TrendChart = lazy(() => import("./TrendChart").then((module) => ({ default: module.TrendChart })));

interface PlayerDetailProps {
  player: CheatRow;
  id?: string;
}

export function PlayerDetailPanel({ player, id }: PlayerDetailProps) {
  const line = typeof player.line === "number" ? player.line : null;
  const rangeLevel = player.range?.level ?? player.range?.nominal_coverage;
  const evaluatedSide = player.evaluated_side ?? player.odds_side ?? null;
  const hasPrice = player.american_odds !== null && player.american_odds !== undefined;
  const structuredFreshness = player.data_freshness && typeof player.data_freshness === "object" ? player.data_freshness : null;
  const predictionEligible = player.prediction_eligible ?? player.metadata?.prediction_eligible ?? structuredFreshness?.prediction_eligible;
  const limitations = player.limitations ?? player.metadata?.limitations ?? structuredFreshness?.limitations;
  const matchupAlert = player.injuries?.matchup && player.injuries.matchup.toLowerCase() !== "active"
    ? player.injuries.matchup
    : null;

  return (
    <div id={id} className="my-2 rounded-lg border border-zinc-700/50 bg-zinc-900/80 p-4 sm:p-5">
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <span className="text-lg font-bold text-white">{player.player}</span>
          <p className="text-sm text-zinc-400">
            {player.team} vs {player.opponent} · Proj {player.projection}{line !== null ? ` · Line ${line}` : ""}
          </p>
          {player.context && <p className="mt-1 text-xs text-zinc-500">Matchup: {player.context}</p>}
        </div>
        {player.rest_note && <span className="text-xs text-zinc-500">{player.rest_note}</span>}
      </div>

      <ProjectionMeta
        americanOdds={player.american_odds}
        oddsSide={evaluatedSide ?? player.direction}
        bookmaker={player.bookmaker}
        oddsSource={player.odds_source}
        oddsUpdatedAt={player.odds_updated_at}
        generatedAt={player.generated_at}
      />
      <DataFreshness freshness={player.data_freshness} className="mt-2" />

      {player.range && (
        <p className="mt-2 text-xs text-zinc-500">
          {rangeLevel !== undefined ? `Central ${formatPercent(rangeLevel, 0)} range: ` : "Simulated range: "}<strong className="text-zinc-300">{player.range.low.toFixed(1)}–{player.range.high.toFixed(1)} rebounds</strong>
          {player.range.method ? ` · ${player.range.method}` : ""}
          {player.range.actual_coverage !== null && player.range.actual_coverage !== undefined ? ` · ${formatPercent(player.range.actual_coverage)} simulated coverage` : ""}
        </p>
      )}

      {line !== null ? (
        <>
          <div className="my-5 grid grid-cols-2 gap-3 rounded-lg bg-zinc-800/50 p-3 sm:grid-cols-4 lg:grid-cols-8">
            <div className="text-center"><div className="text-xs uppercase tracking-wider text-zinc-500">Pick</div><div className={`text-lg font-bold ${player.direction === "OVER" ? "text-emerald-400" : player.direction === "UNDER" ? "text-red-400" : "text-zinc-400"}`}>{player.direction || "NO BET"}</div></div>
            <div className="text-center"><div className="text-xs uppercase tracking-wider text-zinc-500">Over</div><div className="text-lg font-bold text-emerald-400">{formatPercent(player.over_probability)}</div></div>
            <div className="text-center"><div className="text-xs uppercase tracking-wider text-zinc-500">Under</div><div className="text-lg font-bold text-red-400">{formatPercent(player.under_probability)}</div></div>
            <div className="text-center"><div className="text-xs uppercase tracking-wider text-zinc-500">Push</div><div className="text-lg font-bold text-zinc-300">{formatPercent(player.push_probability)}</div></div>
            <div className="text-center"><div className="text-xs uppercase tracking-wider text-zinc-500">Confidence</div><div className="text-lg font-bold text-indigo-300">{formatPercent(player.confidence)}</div></div>
            <div className="text-center"><div className="text-xs uppercase tracking-wider text-zinc-500">Edge</div><div className="text-lg font-bold text-yellow-400">{formatSignedPercent(player.edge)}</div></div>
            <div className="text-center"><div className="text-xs uppercase tracking-wider text-zinc-500">EV ROI</div><div className="text-lg font-bold text-yellow-400">{formatSignedPercent(player.ev_roi)}</div></div>
            <div className="text-center"><div className="text-xs uppercase tracking-wider text-zinc-500">Kelly</div><div className="text-lg font-bold text-blue-400">{formatPercent(player.kelly_fraction, 2)}</div></div>
          </div>
          {!player.direction && (
            <p className="mb-4 rounded border border-zinc-700 bg-zinc-900/50 p-3 text-sm text-zinc-300">
              {hasPrice
                ? `NO BET: ${evaluatedSide ? `${evaluatedSide} was priced, but ` : "the priced market was evaluated, but "}no side cleared the model's actionable threshold.`
                : "NO BET: no side-specific market price is available, so the projection is informational."}
            </p>
          )}
          {(player.implied_probability !== null && player.implied_probability !== undefined) || (player.hit_rate !== null && player.hit_rate !== undefined) ? (
            <div className="mb-4 grid gap-3 text-sm sm:grid-cols-2">
              <div className="rounded bg-zinc-800/40 p-3"><span className="text-zinc-500">Implied probability</span><strong className="float-right text-zinc-200">{formatPercent(player.implied_probability)}</strong></div>
              <div className="rounded bg-zinc-800/40 p-3"><span className="text-zinc-500">Recent hit rate</span><strong className="float-right text-zinc-200">{formatPercent(player.hit_rate)}{player.hit_rate_games ? ` (${player.hit_rate_games})` : ""}</strong></div>
            </div>
          ) : null}
          <div className="mb-4"><SideEvaluations evaluations={player.side_evaluations} selectedDirection={player.direction} selectedOdds={player.american_odds} /></div>
          <div className="mb-4"><PredictionIntervals metrics={player} /></div>
          <VarianceNotice metrics={player} />
        </>
      ) : (
        <div className="my-4 rounded border border-yellow-900/40 bg-yellow-950/20 p-3 text-sm text-yellow-300">
          No sportsbook line is available. This projection is informational only.
        </div>
      )}

      {player.summary && (
        <div className="my-5 rounded-lg border border-zinc-700/30 bg-zinc-800/30 p-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">Why this prediction</h4>
          <MarkdownText text={player.summary} className="text-sm leading-relaxed text-zinc-300" />
        </div>
      )}

      <ProjectionContext
        metadata={player.metadata}
        predictionEligible={predictionEligible}
        limitations={limitations}
        teamId={player.team_id}
        className="mb-5"
      />

      {player.injuries && (
        <div className="mb-5">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">Injury report</h4>
          {(matchupAlert || player.injuries.team) && (
            <div className="mb-2 rounded border border-red-900/30 bg-red-950/20 p-2 text-sm">
              {matchupAlert && <p className="text-red-300">🚑 <strong>Matchup:</strong> {matchupAlert}</p>}
              {player.injuries.team && <p className="mt-1 text-red-300">🏥 <strong>Impact:</strong> {player.injuries.team}</p>}
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <div className="mb-1 text-xs font-semibold text-red-400">Team injuries</div>
              {(player.injuries.team_list?.length ?? 0) > 0 ? (
                <ul className="space-y-0.5 text-xs text-zinc-400">{player.injuries.team_list?.map((injury) => <li key={injury}>• {injury}</li>)}</ul>
              ) : <p className="text-xs text-zinc-600">None reported</p>}
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-red-400">Opponent injuries</div>
              {(player.injuries.opp_list?.length ?? 0) > 0 ? (
                <ul className="space-y-0.5 text-xs text-zinc-400">{player.injuries.opp_list?.map((injury) => <li key={injury}>• {injury}</li>)}</ul>
              ) : <p className="text-xs text-zinc-600">None reported</p>}
            </div>
          </div>
        </div>
      )}

      <div className="mb-5"><FactorBreakdown components={player.components} compact /></div>

      {player.trend && player.trend.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">Last {player.trend.length} games</h4>
          <Suspense fallback={<div className="h-[160px] animate-pulse rounded bg-zinc-800/40" />}>
            <TrendChart data={player.trend} line={line} direction={player.direction} height={160} />
          </Suspense>
        </div>
      )}
    </div>
  );
}
