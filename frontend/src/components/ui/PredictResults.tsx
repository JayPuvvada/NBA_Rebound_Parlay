import { Card, CardContent } from "@/components/ui/card";
import { TrendChart } from "@/components/ui/TrendChart";

interface PredictResultsProps {
  data: any;
}

function getComponentLabel(key: string, val: number): { label: string; colorClass: string } {
  const multiplierKeys = ["Pace", "Opp", "DvP", "Matchup", "Env Mult (Final)", "Pace Factor", "Opp Defense", "DvP Mult", "Matchup Adj", "Home/Away", "Rest Factor"];

  if (key === "Base Rebs" || key === "Base") return { label: "", colorClass: "" };

  const isMultiplier = multiplierKeys.includes(key) || (typeof val === "number" && val > 0.5 && val < 1.5);
  if (!isMultiplier) return { label: "", colorClass: "" };

  if (val >= 1.05) return { label: "🔥 Great Boost", colorClass: "text-emerald-400" };
  if (val >= 1.01) return { label: "✅ Favorable", colorClass: "text-green-400" };
  if (val <= 0.95) return { label: "🛑 Very Tough", colorClass: "text-red-400" };
  if (val <= 0.99) return { label: "⚠️ Difficult", colorClass: "text-yellow-400" };
  return { label: "➖ Neutral", colorClass: "text-zinc-500" };
}

function getRecBannerStyles(color: string) {
  switch (color) {
    case "green": return { bg: "bg-emerald-500/10", border: "border-emerald-500/30", text: "text-emerald-400" };
    case "blue": return { bg: "bg-blue-500/10", border: "border-blue-500/30", text: "text-blue-400" };
    case "purple": return { bg: "bg-purple-500/10", border: "border-purple-500/30", text: "text-purple-400" };
    case "yellow": return { bg: "bg-yellow-500/10", border: "border-yellow-500/30", text: "text-yellow-400" };
    default: return { bg: "bg-red-500/10", border: "border-red-500/30", text: "text-red-400" };
  }
}

export function PredictResults({ data }: PredictResultsProps) {
  const analysis = data.analysis;
  const lineVal = analysis ? analysis.line : null;

  return (
    <Card className="w-full bg-zinc-950 border-zinc-800 text-zinc-100 shadow-2xl">
      <CardContent className="pt-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-2xl font-bold text-white">{data.player}</h2>
            <p className="text-zinc-400 text-sm">vs {data.opponent} ({data.context})</p>
          </div>
          <div className="text-right bg-zinc-900 px-5 py-3 rounded-lg">
            <div className="text-xs text-zinc-500 uppercase">Projected Rebounds</div>
            <div className="text-3xl font-bold text-indigo-300">{data.projection}</div>
          </div>
        </div>

        {/* Trend Chart */}
        {data.trend && data.trend.length > 0 && (
          <div className="mb-6 pb-6 border-b border-zinc-800">
            <h4 className="text-xs uppercase tracking-wider text-zinc-500 mb-2 font-semibold">
              Last {data.trend.length} Games
            </h4>
            <TrendChart data={data.trend} line={lineVal} height={200} />
          </div>
        )}

        {/* Recommendation Banner + Stats */}
        {analysis && (
          <div className="mb-6">
            {/* Recommendation */}
            {(() => {
              const styles = getRecBannerStyles(analysis.rec_color);
              return (
                <div className={`${styles.bg} ${styles.text} border ${styles.border} rounded-lg px-4 py-3 text-center font-bold text-lg mb-4`}>
                  {analysis.recommendation}
                </div>
              );
            })()}

            {/* Stats Grid */}
            <div className="grid grid-cols-3 gap-4 mb-4 p-4 bg-zinc-900/50 rounded-lg">
              <div className="text-center">
                <div className="text-xs text-zinc-500 uppercase">Over Probability</div>
                <div className="text-xl font-bold text-emerald-400">{analysis.over_prob}%</div>
              </div>
              <div className="text-center">
                <div className="text-xs text-zinc-500 uppercase">Under Probability</div>
                <div className="text-xl font-bold text-red-400">{analysis.under_prob}%</div>
              </div>
              <div className="text-center">
                <div className="text-xs text-zinc-500 uppercase">Edge</div>
                <div className="text-xl font-bold text-yellow-400">
                  {analysis.true_edge !== undefined ? `${analysis.true_edge}%` : `${analysis.edge}%`}
                </div>
              </div>
            </div>

            {/* Confidence Badge */}
            {analysis.fano_source && (
              <div className={`text-sm px-3 py-2 rounded-lg mb-4 ${
                analysis.fano_source === "empirical"
                  ? "bg-emerald-900/20 border border-emerald-800/30 text-emerald-300"
                  : "bg-yellow-900/20 border border-yellow-800/30 text-yellow-300"
              }`}>
                {analysis.fano_source === "empirical" ? "🟢" : "🟡"}{" "}
                Variance: {analysis.fano_source === "empirical" ? "Real Data" : "Estimated"}{" "}
                (Fano {analysis.fano?.toFixed(2) ?? "?"})
              </div>
            )}
          </div>
        )}

        {/* Model Summary */}
        {data.summary && (
          <div className="mb-5 p-4 bg-zinc-900/30 rounded-lg border border-zinc-800/50">
            <h3 className="text-sm font-bold text-white mb-2">Model Insights</h3>
            <p className="text-sm text-zinc-300 leading-relaxed"
              dangerouslySetInnerHTML={{ __html: data.summary.replace(/\*\*(.*?)\*\*/g, "<b>$1</b>") }}
            />
          </div>
        )}

        {/* Components */}
        {data.components && (
          <div className="mb-5">
            <h4 className="text-xs uppercase tracking-wider text-zinc-500 mb-3 font-semibold">Factor Breakdown</h4>
            <div className="space-y-1.5">
              {Object.entries(data.components).map(([key, val]) => {
                const numVal = val as number;
                const { label, colorClass } = getComponentLabel(key, numVal);
                const isBase = key === "Base Rebs" || key === "Base";

                return (
                  <div key={key} className="flex items-center justify-between py-1.5 px-3 rounded hover:bg-zinc-800/30">
                    <span className="text-sm text-zinc-300">{key}</span>
                    <div className="flex items-center gap-2">
                      {label && <span className={`text-xs ${colorClass}`}>{label}</span>}
                      <span className={`text-sm font-mono ${isBase ? "text-indigo-300 font-bold" : "text-zinc-500"}`}>
                        {isBase ? numVal.toFixed(1) : `${numVal.toFixed(2)}x`}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Injuries */}
        {data.injuries && (
          <div>
            {(data.injuries.matchup || data.injuries.team) && (
              <div className="mb-3 p-3 bg-red-950/20 border border-red-900/30 rounded-lg text-sm">
                {data.injuries.matchup && <p className="text-red-300">🚑 <strong>Matchup Alert:</strong> {data.injuries.matchup}</p>}
                {data.injuries.team && <p className="text-red-300 mt-1">🏥 <strong>Impact Alert:</strong> {data.injuries.team}</p>}
              </div>
            )}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <h4 className="text-xs uppercase text-red-400 font-semibold mb-2">Team Injuries</h4>
                {data.injuries.team_list?.length > 0 ? (
                  <ul className="space-y-1 text-sm text-zinc-400">
                    {data.injuries.team_list.map((inj: string, i: number) => <li key={i}>• {inj}</li>)}
                  </ul>
                ) : <p className="text-xs text-zinc-600">No injuries reported.</p>}
              </div>
              <div>
                <h4 className="text-xs uppercase text-red-400 font-semibold mb-2">Opponent Injuries</h4>
                {data.injuries.opp_list?.length > 0 ? (
                  <ul className="space-y-1 text-sm text-zinc-400">
                    {data.injuries.opp_list.map((inj: string, i: number) => <li key={i}>• {inj}</li>)}
                  </ul>
                ) : <p className="text-xs text-zinc-600">No injuries reported.</p>}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
