import { lazy, Suspense } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { DataFreshness } from "@/components/ui/DataFreshness";
import { FactorBreakdown } from "@/components/ui/FactorBreakdown";
import { MarkdownText } from "@/components/ui/MarkdownText";
import { PredictionIntervals } from "@/components/ui/PredictionIntervals";
import { ProjectionMeta } from "@/components/ui/ProjectionMeta";
import { ProjectionContext } from "@/components/ui/ProjectionContext";
import { SideEvaluations } from "@/components/ui/SideEvaluations";
import { VarianceNotice } from "@/components/ui/VarianceNotice";
import { formatPercent, formatSignedPercent, formatTimestamp } from "@/lib/format";
import type { InjuryInfo, PredictResponse, SimulationRange, TierColor } from "@/types/api";

const TrendChart = lazy(() => import("@/components/ui/TrendChart").then((module) => ({ default: module.TrendChart })));

interface PredictResultsProps {
  data: PredictResponse;
}

function getRecBannerStyles(color: TierColor | string | null | undefined) {
  switch (color) {
    case "green": return { bg: "bg-emerald-500/10", border: "border-emerald-500/30", text: "text-emerald-400" };
    case "blue": return { bg: "bg-blue-500/10", border: "border-blue-500/30", text: "text-blue-400" };
    case "purple": return { bg: "bg-purple-500/10", border: "border-purple-500/30", text: "text-purple-400" };
    case "yellow": return { bg: "bg-yellow-500/10", border: "border-yellow-500/30", text: "text-yellow-400" };
    case "gray": return { bg: "bg-zinc-500/10", border: "border-zinc-500/30", text: "text-zinc-300" };
    case "red": return { bg: "bg-red-500/10", border: "border-red-500/30", text: "text-red-400" };
    default: return { bg: "bg-zinc-500/10", border: "border-zinc-500/30", text: "text-zinc-300" };
  }
}

function numericRange(range: PredictResponse["range"]): SimulationRange | null {
  return range && typeof range === "object" ? range : null;
}

function InjuryReport({ injuries }: { injuries?: InjuryInfo }) {
  if (!injuries) return null;
  const matchupAlert = injuries.matchup && injuries.matchup.toLowerCase() !== "active" ? injuries.matchup : null;

  return (
    <div>
      {(matchupAlert || injuries.team) && (
        <div className="mb-3 rounded-lg border border-red-900/30 bg-red-950/20 p-3 text-sm">
          {matchupAlert && <p className="text-red-300">🚑 <strong>Matchup alert:</strong> {matchupAlert}</p>}
          {injuries.team && <p className="mt-1 text-red-300">🏥 <strong>Impact alert:</strong> {injuries.team}</p>}
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase text-red-400">Team injuries</h4>
          {(injuries.team_list?.length ?? 0) > 0 ? (
            <ul className="space-y-1 text-sm text-zinc-400">
              {injuries.team_list?.map((injury) => <li key={injury}>• {injury}</li>)}
            </ul>
          ) : <p className="text-xs text-zinc-600">No injuries reported.</p>}
        </div>
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase text-red-400">Opponent injuries</h4>
          {(injuries.opp_list?.length ?? 0) > 0 ? (
            <ul className="space-y-1 text-sm text-zinc-400">
              {injuries.opp_list?.map((injury) => <li key={injury}>• {injury}</li>)}
            </ul>
          ) : <p className="text-xs text-zinc-600">No injuries reported.</p>}
        </div>
      </div>
    </div>
  );
}

export function PredictResults({ data }: PredictResultsProps) {
  const analysis = data.analysis ?? null;
  const line = typeof analysis?.line === "number" ? analysis.line : null;
  const direction = analysis?.direction ?? null;
  const evaluatedSide = analysis?.evaluated_side ?? analysis?.odds_side ?? null;
  const tier = analysis?.tier ?? analysis?.recommendation ?? null;
  const tierColor = analysis?.tier_color ?? analysis?.rec_color;
  const banner = getRecBannerStyles(tierColor);
  const range = numericRange(data.range);
  const generatedAt = formatTimestamp(data.generated_at);
  const structuredFreshness = data.data_freshness && typeof data.data_freshness === "object" ? data.data_freshness : null;
  const predictionEligible = data.prediction_eligible ?? data.metadata?.prediction_eligible ?? structuredFreshness?.prediction_eligible;
  const limitations = data.limitations ?? data.metadata?.limitations ?? structuredFreshness?.limitations;

  return (
    <Card className="w-full border-zinc-800 bg-zinc-950 text-zinc-100 shadow-2xl" aria-live="polite">
      <CardContent className="pt-6">
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-2xl font-bold text-white">{data.player}</h2>
            <p className="text-sm text-zinc-400">
              {data.team ? `${data.team} · ` : ""}vs {data.opponent}{data.context ? ` · ${data.context}` : ""} · {data.home_game ? "Home" : "Away"}
            </p>
            {(data.model_version || generatedAt) && (
              <p className="mt-1 text-xs text-zinc-600">
                {data.model_version && `Model ${data.model_version}`}{data.model_version && generatedAt ? " · " : ""}
                {generatedAt && <>Generated <time dateTime={data.generated_at || undefined}>{generatedAt}</time></>}
              </p>
            )}
            <DataFreshness freshness={data.data_freshness} className="mt-2" />
          </div>
          <div className="self-start rounded-lg bg-zinc-900 px-5 py-3 text-left sm:self-auto sm:text-right">
            <div className="text-xs uppercase text-zinc-500">Projected rebounds</div>
            <div className="text-3xl font-bold text-indigo-300">{data.projection}</div>
          </div>
        </div>

        {data.trend && data.trend.length > 0 && (
          <div className="mb-6 border-b border-zinc-800 pb-6">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">Last {data.trend.length} games</h3>
            <Suspense fallback={<div className="h-[200px] animate-pulse rounded bg-zinc-900/50" />}>
              <TrendChart data={data.trend} line={line} direction={direction} height={200} />
            </Suspense>
          </div>
        )}

        {analysis && line !== null ? (
          <div className="mb-6 space-y-4">
            <div className={`${banner.bg} ${banner.text} ${banner.border} rounded-lg border px-4 py-3 text-center text-lg font-bold`}>
              {direction ? `${direction} ${line}` : `NO BET · Line ${line}`} · {tier || (analysis.american_odds ? "Priced analysis" : "Informational only")}
            </div>

            <ProjectionMeta
              americanOdds={analysis.american_odds}
              oddsSide={evaluatedSide ?? direction}
              bookmaker={analysis.bookmaker}
              oddsSource={analysis.odds_source}
              oddsUpdatedAt={analysis.odds_updated_at}
              generatedAt={analysis.generated_at ?? data.generated_at}
            />

            {analysis.american_odds === null || analysis.american_odds === undefined ? (
              <div className="rounded-lg border border-blue-900/40 bg-blue-950/20 px-3 py-2 text-sm text-blue-300">
                No market price was supplied. Probabilities are informational; EV, Kelly, and betting tiers require side-specific odds.
              </div>
            ) : null}

            {!direction && analysis.american_odds !== null && analysis.american_odds !== undefined ? (
              <div className="rounded-lg border border-zinc-700 bg-zinc-900/60 px-3 py-2 text-sm text-zinc-300">
                {evaluatedSide ? `${evaluatedSide} was evaluated at this price, but ` : "The priced market was evaluated, but "}no side cleared the model's actionable betting threshold.
              </div>
            ) : null}

            <div className="grid grid-cols-2 gap-3 rounded-lg bg-zinc-900/50 p-4 sm:grid-cols-3 lg:grid-cols-6">
              <div className="text-center"><div className="text-xs uppercase text-zinc-500">Over</div><div className="text-xl font-bold text-emerald-400">{formatPercent(analysis.over_probability)}</div></div>
              <div className="text-center"><div className="text-xs uppercase text-zinc-500">Under</div><div className="text-xl font-bold text-red-400">{formatPercent(analysis.under_probability)}</div></div>
              <div className="text-center"><div className="text-xs uppercase text-zinc-500">Push</div><div className="text-xl font-bold text-zinc-300">{formatPercent(analysis.push_probability)}</div></div>
              <div className="text-center"><div className="text-xs uppercase text-zinc-500">Confidence</div><div className="text-xl font-bold text-indigo-300">{formatPercent(analysis.confidence)}</div></div>
              <div className="text-center"><div className="text-xs uppercase text-zinc-500" title="Expected return per unit staked">EV ROI</div><div className="text-xl font-bold text-yellow-400">{formatSignedPercent(analysis.ev_roi)}</div></div>
              <div className="text-center"><div className="text-xs uppercase text-zinc-500" title="Fractional Kelly bankroll recommendation">Kelly</div><div className="text-xl font-bold text-blue-400">{formatPercent(analysis.kelly_fraction, 2)}</div></div>
            </div>

            <div className="grid gap-3 text-sm sm:grid-cols-3">
              <div className="rounded bg-zinc-900/40 p-3"><span className="text-zinc-500">Probability edge</span><strong className="float-right text-zinc-200">{formatSignedPercent(analysis.edge)}</strong></div>
              <div className="rounded bg-zinc-900/40 p-3"><span className="text-zinc-500">Implied probability</span><strong className="float-right text-zinc-200">{formatPercent(analysis.implied_probability)}</strong></div>
              <div className="rounded bg-zinc-900/40 p-3"><span className="text-zinc-500">Recent hit rate</span><strong className="float-right text-zinc-200">{formatPercent(analysis.hit_rate)}{analysis.hit_rate_games ? ` (${analysis.hit_rate_games})` : ""}</strong></div>
            </div>

            <SideEvaluations evaluations={analysis.side_evaluations} selectedDirection={direction} selectedOdds={analysis.american_odds} />

            <PredictionIntervals metrics={analysis} />

            <VarianceNotice metrics={analysis} />
          </div>
        ) : data.range ? (
          <div className="mb-6 rounded-lg border border-indigo-500/20 bg-indigo-500/10 p-4 text-indigo-200">
            <p className="text-xs font-semibold uppercase tracking-wider text-indigo-300/70">Simulated range</p>
            <p className="mt-1 text-2xl font-bold">
              {range ? `${range.low.toFixed(1)} – ${range.high.toFixed(1)} rebounds` : String(data.range)}
            </p>
            {range && (
              <p className="mt-1 text-xs text-indigo-300/70">
                Central {formatPercent(range.level, 0)} interval
                {range.actual_coverage !== null && range.actual_coverage !== undefined ? ` · ${formatPercent(range.actual_coverage)} simulated coverage` : ""}
                {range.method ? ` · ${range.method.replaceAll("_", " ")}` : ""}
              </p>
            )}
          </div>
        ) : null}

        {data.summary && (
          <div className="mb-5 rounded-lg border border-zinc-800/50 bg-zinc-900/30 p-4">
            <h3 className="mb-2 text-sm font-bold text-white">Model insights</h3>
            <MarkdownText text={data.summary} className="text-sm leading-relaxed text-zinc-300" />
          </div>
        )}

        <ProjectionContext
          metadata={data.metadata}
          predictionEligible={predictionEligible}
          limitations={limitations}
          teamId={data.team_id}
          schedule={data.schedule}
          className="mb-5"
        />

        {data.recording?.requested && (
          <div
            className={`mb-5 rounded-lg border p-3 text-sm ${data.recording.recorded ? "border-emerald-900/50 bg-emerald-950/20 text-emerald-300" : "border-zinc-700 bg-zinc-900/50 text-zinc-300"}`}
            role="status"
          >
            <strong>{data.recording.recorded ? "Saved to evaluation ledger." : "Not saved to evaluation ledger."}</strong>
            {data.recording.reason && <span> {data.recording.reason}</span>}
          </div>
        )}

        <div className="mb-5"><FactorBreakdown components={data.components} /></div>
        <InjuryReport injuries={data.injuries} />
      </CardContent>
    </Card>
  );
}
