import { BettingAnalysis } from "./BettingAnalysis";
import type { CheatRow } from "@/types/api";

export function PlayerDetailPanel({ player, id }: { player: CheatRow; id?: string }) {
  return (
    <div id={id} className="my-2 rounded-lg border border-zinc-700/50 bg-zinc-950 p-4 sm:p-5">
      <BettingAnalysis data={player} metrics={player} range={player.range} marketOdds={player.market_odds} />
    </div>
  );
}
