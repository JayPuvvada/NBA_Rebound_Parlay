import { TrendChart } from "./TrendChart";

interface PlayerDetailProps {
  player: any;
}

export function PlayerDetailPanel({ player }: PlayerDetailProps) {
  const lineVal = typeof player.line === "number" ? player.line : null;
  const edgePct = player.edge_raw ? (player.edge_raw * 100).toFixed(1) : "0";

  return (
    <div className="bg-zinc-900/80 border border-zinc-700/50 rounded-lg p-5 mt-1 mb-2 animate-in slide-in-from-top-2">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <span className="text-white font-bold text-lg">{player.player}</span>
          <span className="text-zinc-400 ml-2 text-sm">
            {player.team} vs {player.opponent} • Proj: {player.projection} | Line: {player.line}
          </span>
        </div>
        <span className="text-xs text-zinc-500">{player.rest_note}</span>
      </div>

      {/* Probabilities Row */}
      {lineVal !== null && (
        <div className="grid grid-cols-3 gap-4 mb-5 p-3 bg-zinc-800/50 rounded-lg">
          <div className="text-center">
            <div className="text-xs text-zinc-500 uppercase tracking-wider">Over Prob</div>
            <div className="text-xl font-bold text-emerald-400">{player.over_prob}%</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-zinc-500 uppercase tracking-wider">Under Prob</div>
            <div className="text-xl font-bold text-red-400">{player.under_prob}%</div>
          </div>
          <div className="text-center">
            <div className="text-xs text-zinc-500 uppercase tracking-wider">Edge</div>
            <div className={`text-xl font-bold ${parseFloat(edgePct) > 0 ? 'text-yellow-400' : 'text-zinc-400'}`}>
              {edgePct}%
            </div>
          </div>
        </div>
      )}

      {/* Prediction Summary */}
      {player.summary && (
        <div className="mb-5 p-3 bg-zinc-800/30 rounded-lg border border-zinc-700/30">
          <h4 className="text-xs uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Why This Prediction</h4>
          <p className="text-sm text-zinc-300 leading-relaxed" 
            dangerouslySetInnerHTML={{ __html: player.summary.replace(/\*\*(.*?)\*\*/g, "<b>$1</b>") }} 
          />
        </div>
      )}

      {/* Injury Report */}
      {player.injuries && (
        <div className="mb-5">
          <h4 className="text-xs uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Injury Report</h4>
          {(player.injuries.matchup || player.injuries.team) && (
            <div className="mb-2 p-2 bg-red-950/20 border border-red-900/30 rounded text-sm">
              {player.injuries.matchup && <p className="text-red-300">🚑 <strong>Matchup:</strong> {player.injuries.matchup}</p>}
              {player.injuries.team && <p className="text-red-300 mt-1">🏥 <strong>Impact:</strong> {player.injuries.team}</p>}
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-red-400 font-semibold mb-1">Team Injuries</div>
              {player.injuries.team_list?.length > 0 ? (
                <ul className="text-xs text-zinc-400 space-y-0.5">
                  {player.injuries.team_list.map((inj: string, i: number) => <li key={i}>• {inj}</li>)}
                </ul>
              ) : <p className="text-xs text-zinc-600">None reported</p>}
            </div>
            <div>
              <div className="text-xs text-red-400 font-semibold mb-1">Opponent Injuries</div>
              {player.injuries.opp_list?.length > 0 ? (
                <ul className="text-xs text-zinc-400 space-y-0.5">
                  {player.injuries.opp_list.map((inj: string, i: number) => <li key={i}>• {inj}</li>)}
                </ul>
              ) : <p className="text-xs text-zinc-600">None reported</p>}
            </div>
          </div>
        </div>
      )}

      {/* Trend Chart */}
      {player.trend && player.trend.length > 0 && (
        <div>
          <h4 className="text-xs uppercase tracking-wider text-zinc-500 mb-2 font-semibold">
            Last {player.trend.length} Games
          </h4>
          <TrendChart data={player.trend} line={lineVal} height={140} />
        </div>
      )}
    </div>
  );
}
