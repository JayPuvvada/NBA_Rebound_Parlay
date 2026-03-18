import { useState, useEffect, Fragment } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { PlayerDetailPanel } from "@/components/ui/PlayerDetailPanel";
import { Loader2 } from "lucide-react";

interface GameInfo {
  home: string;
  away: string;
}

export function CheatSheet() {
  const todayStr = new Date().toISOString().split("T")[0];
  const [date, setDate] = useState<string>(todayStr);
  const [games, setGames] = useState<GameInfo[]>([]);
  const [selectedGame, setSelectedGame] = useState<GameInfo | null>(null);
  const [data, setData] = useState<any[] | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [loadingGames, setLoadingGames] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  // Fetch available games whenever the date changes
  useEffect(() => {
    const fetchGames = async () => {
      setLoadingGames(true);
      setGames([]);
      setSelectedGame(null);
      setData(null);
      setError(null);
      setExpandedIdx(null);
      try {
        const res = await fetch(`/games?date=${date}`);
        const json = await res.json();
        if (json.games && json.games.length > 0) {
          setGames(json.games);
        } else {
          setError(json.message || "No games found for this date.");
        }
      } catch {
        setError("Could not connect to backend. Is the Flask server running on port 5001?");
      } finally {
        setLoadingGames(false);
      }
    };
    fetchGames();
  }, [date]);

  // Fetch cheat-sheet data when a game is selected
  useEffect(() => {
    if (!selectedGame) return;

    const fetchData = async () => {
      setLoading(true);
      setError(null);
      setExpandedIdx(null);
      try {
        const res = await fetch(`/cheat-sheet?team=${selectedGame.home}&date=${date}&book=fanduel`);

        if (!res.ok) {
          try {
            const errorJson = await res.json();
            if (errorJson.error) throw new Error(errorJson.error);
          } catch (e) {
            if (e instanceof Error && e.message !== "Unexpected end of JSON input") throw e;
          }
          throw new Error(`Server returned ${res.status}`);
        }

        const json = await res.json();
        if (json.error) throw new Error(json.error);
        setData(Array.isArray(json) ? json : []);
      } catch (err: any) {
        setError(err.message || "Failed to fetch projections.");
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [selectedGame, date]);

  // Group data by team
  const homeTeamData = data?.filter(p => p.team === selectedGame?.home) || [];
  const awayTeamData = data?.filter(p => p.team === selectedGame?.away) || [];

  const toggleExpand = (globalIdx: number) => {
    setExpandedIdx(expandedIdx === globalIdx ? null : globalIdx);
  };

  const renderPlayerRow = (proj: any, idx: number) => {
    const isExpanded = expandedIdx === idx;
    let tierClass = "text-zinc-500";
    if (proj.tier?.includes("STRONG")) tierClass = "text-emerald-400";
    else if (proj.tier?.includes("PLAY") && !proj.tier?.includes("SAFE")) tierClass = "text-green-400";
    else if (proj.tier?.includes("SAFE")) tierClass = "text-blue-400";
    else if (proj.tier?.includes("LEAN")) tierClass = "text-purple-400";
    else if (proj.tier?.includes("AVOID")) tierClass = "text-red-400";

    return (
      <Fragment key={idx}>
        <tr
          onClick={() => toggleExpand(idx)}
          className={`border-b border-zinc-800/50 cursor-pointer transition-colors ${
            isExpanded ? "bg-zinc-800/40" : "hover:bg-zinc-900/30"
          }`}
        >
          <td className="px-4 py-3">
            <div className="font-medium text-white">
              {proj.player}
              <span className="text-zinc-600 text-xs ml-1">{isExpanded ? "▲" : "▼"}</span>
            </div>
          </td>
          <td className="px-4 py-3 text-zinc-400 text-sm">
            vs {proj.opponent}
            <span className="text-xs text-zinc-600 ml-1">({proj.rest_note})</span>
          </td>
          <td className="px-4 py-3 text-right font-mono text-indigo-300 font-bold">{proj.projection}</td>
          <td className="px-4 py-3 text-right">{proj.line}</td>
          <td className="px-4 py-3">
            {proj.direction !== "-" ? (
              <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                proj.direction === "OVER"
                  ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                  : "bg-red-500/10 text-red-400 border border-red-500/20"
              }`}>
                {proj.direction}
              </span>
            ) : <span className="text-zinc-600">—</span>}
          </td>
          <td className={`px-4 py-3 text-sm font-semibold ${tierClass}`}>{proj.tier || "—"}</td>
        </tr>
        {isExpanded && (
          <tr>
            <td colSpan={6} className="p-0">
              <PlayerDetailPanel player={proj} />
            </td>
          </tr>
        )}
      </Fragment>
    );
  };

  const renderTeamTable = (players: any[], teamCode: string, isHome: boolean, startIdx: number) => {
    if (players.length === 0) return null;
    return (
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-3 px-1">
          <span className="text-lg">{isHome ? "🏠" : "✈️"}</span>
          <h3 className="text-white font-bold text-base">{teamCode}</h3>
          <span className="text-zinc-500 text-xs">{isHome ? "(Home)" : "(Away)"}</span>
        </div>
        <table className="w-full text-sm text-left">
          <thead className="text-xs uppercase bg-zinc-900/50 text-zinc-400">
            <tr>
              <th className="px-4 py-2.5 rounded-tl-md">Player</th>
              <th className="px-4 py-2.5">Matchup</th>
              <th className="px-4 py-2.5 text-right">Proj</th>
              <th className="px-4 py-2.5 text-right">Line</th>
              <th className="px-4 py-2.5">Dir</th>
              <th className="px-4 py-2.5 rounded-tr-md">Tier</th>
            </tr>
          </thead>
          <tbody>
            {players.map((p, i) => renderPlayerRow(p, startIdx + i))}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <Card className="w-full bg-zinc-950 border-zinc-800 text-zinc-100 shadow-2xl">
      <CardHeader className="border-b border-zinc-800 pb-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <CardTitle className="text-2xl font-bold flex items-center gap-2">
              🔥 Daily Edge Generator
            </CardTitle>
            <CardDescription className="text-zinc-400 mt-1">
              Pick a date, click a game, then click any player to see the full breakdown.
            </CardDescription>
          </div>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="bg-zinc-900 border border-zinc-700 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 w-fit"
          />
        </div>

        {/* Game pills */}
        {loadingGames ? (
          <div className="mt-4 flex items-center gap-2 text-zinc-500 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading games...
          </div>
        ) : games.length > 0 ? (
          <div className="flex flex-wrap gap-2 mt-4">
            {games.map((g, i) => (
              <button
                key={i}
                onClick={() => setSelectedGame(g)}
                className={`text-xs px-3 py-1.5 rounded-full border transition-all duration-200
                  ${selectedGame?.home === g.home && selectedGame?.away === g.away
                    ? "bg-emerald-600/20 border-emerald-500 text-emerald-400 shadow-lg shadow-emerald-900/20"
                    : "bg-zinc-900 border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-300"
                  }`}
              >
                {g.away} @ {g.home}
              </button>
            ))}
          </div>
        ) : null}
      </CardHeader>

      <CardContent className="pt-6 min-h-[300px]">
        {!selectedGame && !error && (
          <div className="w-full h-64 flex flex-col items-center justify-center text-zinc-500">
            <span className="text-4xl mb-3">📊</span>
            <p>Select a game above to see projections.</p>
          </div>
        )}

        {loading ? (
          <div className="w-full h-64 flex flex-col items-center justify-center text-zinc-400">
            <Loader2 className="h-8 w-8 animate-spin mb-4 text-emerald-500" />
            <p>Crunching Scheme Matchups & Cannibalization Engines...</p>
            <p className="text-xs text-zinc-600 mt-2">This may take 30-60 seconds on first load.</p>
          </div>
        ) : error ? (
          <div className="w-full p-4 border border-red-900/50 bg-red-950/20 text-red-400 rounded-md">
            <p className="font-semibold">Error retrieving Edge Data</p>
            <p className="text-sm mt-1">{error}</p>
          </div>
        ) : data && data.length > 0 && selectedGame ? (
          <div className="overflow-x-auto">
            {/* Lines availability notice */}
            {data.every(p => p.line === '-') && (
              <div className="mb-4 p-3 border border-yellow-900/40 bg-yellow-950/20 text-yellow-400/80 rounded-md text-sm">
                ⏳ <strong>Sportsbook lines not yet available.</strong> FanDuel typically posts player prop lines in the afternoon. Projections are still calculated from the model — lines, directions, and tiers will populate once odds go live.
              </div>
            )}
            {renderTeamTable(homeTeamData, selectedGame.home, true, 0)}
            {renderTeamTable(awayTeamData, selectedGame.away, false, homeTeamData.length)}
          </div>
        ) : selectedGame && data && data.length === 0 ? (
          <div className="w-full h-64 flex items-center justify-center text-zinc-500">
            No projection data available for this game.
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
