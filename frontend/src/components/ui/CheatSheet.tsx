import { Fragment, useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PlayerDetailPanel } from "@/components/ui/PlayerDetailPanel";
import { Loader2 } from "lucide-react";
import { ApiRequestError, fetchJson, unwrapCheatSheet } from "@/lib/api";
import { easternToday, formatAmericanOdds, formatSignedPercent, formatTimestamp } from "@/lib/format";
import type { CheatRow, CheatSheetOddsStatus, CheatSheetResponse, Game, GamesResponse } from "@/types/api";

const BOOKMAKERS = [
  { key: "fanduel", label: "FanDuel" },
  { key: "draftkings", label: "DraftKings" },
  { key: "betmgm", label: "BetMGM" },
] as const;

function requestMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message;
  return fallback;
}

function tierClass(row: CheatRow): string {
  const color = row.tier_color;
  if (color === "green") return "text-emerald-400";
  if (color === "blue") return "text-blue-400";
  if (color === "purple") return "text-purple-400";
  if (color === "yellow") return "text-yellow-400";
  if (color === "red") return "text-red-400";
  if (color === "gray") return "text-zinc-400";

  const tier = row.tier || "";
  if (tier.includes("STRONG")) return "text-emerald-400";
  if (tier.includes("PLAY") && !tier.includes("SAFE")) return "text-green-400";
  if (tier.includes("SAFE")) return "text-blue-400";
  if (tier.includes("LEAN")) return "text-purple-400";
  if (tier.includes("AVOID")) return "text-red-400";
  return "text-zinc-500";
}

function detailId(row: CheatRow): string {
  return `detail-${row.team || "team"}-${row.player}`.replace(/[^A-Za-z0-9_-]/g, "-");
}

export function CheatSheet() {
  const [date, setDate] = useState(easternToday);
  const [book, setBook] = useState<(typeof BOOKMAKERS)[number]["key"]>("fanduel");
  const [games, setGames] = useState<Game[]>([]);
  const [selectedGame, setSelectedGame] = useState<Game | null>(null);
  const [data, setData] = useState<CheatRow[] | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [oddsStatus, setOddsStatus] = useState<CheatSheetOddsStatus | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingGames, setLoadingGames] = useState(false);
  const [gamesError, setGamesError] = useState<string | null>(null);
  const [sheetError, setSheetError] = useState<string | null>(null);
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [gamesRetry, setGamesRetry] = useState(0);
  const [sheetRetry, setSheetRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    const loadGames = async () => {
      setLoadingGames(true);
      setGames([]);
      setGamesError(null);
      try {
        const query = new URLSearchParams({ date });
        const response = await fetchJson<GamesResponse>(`/games?${query.toString()}`, { signal: controller.signal }, { timeoutMs: 30_000 });
        if (!Array.isArray(response.games)) throw new Error("The games response had an unexpected shape.");
        setGames(response.games);
        if (response.games.length === 0) setGamesError(response.message || `No NBA games found for ${date}.`);
      } catch (error: unknown) {
        if (error instanceof ApiRequestError && error.kind === "aborted") return;
        setGamesError(requestMessage(error, "Failed to fetch the NBA schedule."));
      } finally {
        if (!controller.signal.aborted) setLoadingGames(false);
      }
    };

    void loadGames();
    return () => controller.abort();
  }, [date, gamesRetry]);

  useEffect(() => {
    if (!selectedGame) return;
    const controller = new AbortController();

    const loadSheet = async () => {
      setLoading(true);
      setData(null);
      setGeneratedAt(null);
      setOddsStatus(null);
      setWarnings([]);
      setSheetError(null);
      setExpandedKey(null);
      try {
        const query = new URLSearchParams({ team: selectedGame.home, date, book });
        const response = await fetchJson<CheatSheetResponse>(`/cheat-sheet?${query.toString()}`, { signal: controller.signal }, { timeoutMs: 110_000 });
        const normalized = unwrapCheatSheet(response);
        setData(normalized.rows);
        setGeneratedAt(normalized.generatedAt || null);
        setOddsStatus(normalized.odds || null);
        setWarnings(normalized.warnings);
      } catch (error: unknown) {
        if (error instanceof ApiRequestError && error.kind === "aborted") return;
        setSheetError(requestMessage(error, "Failed to fetch projections."));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };

    void loadSheet();
    return () => controller.abort();
  }, [selectedGame, date, book, sheetRetry]);

  const changeDate = (nextDate: string) => {
    setSelectedGame(null);
    setData(null);
    setGeneratedAt(null);
    setOddsStatus(null);
    setWarnings([]);
    setExpandedKey(null);
    setSheetError(null);
    setLoading(false);
    setDate(nextDate);
  };

  const selectGame = (game: Game) => {
    setSelectedGame(game);
    setData(null);
    setWarnings([]);
    setSheetError(null);
    setExpandedKey(null);
  };

  const renderPlayerRow = (projection: CheatRow) => {
    const key = `${projection.team || ""}:${projection.player}`;
    const isExpanded = expandedKey === key;
    const line = typeof projection.line === "number" ? projection.line : null;
    const panelId = detailId(projection);

    return (
      <Fragment key={key}>
        <tr className={`border-b border-zinc-800/50 transition-colors ${isExpanded ? "bg-zinc-800/40" : "hover:bg-zinc-900/30"}`}>
          <td className="px-4 py-3">
            <button
              type="button"
              onClick={() => setExpandedKey(isExpanded ? null : key)}
              aria-expanded={isExpanded}
              aria-controls={panelId}
              className="flex w-full items-center gap-1 text-left font-medium text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
            >
              {projection.player}
              <span className="text-xs text-zinc-600" aria-hidden="true">{isExpanded ? "▲" : "▼"}</span>
            </button>
          </td>
          <td className="px-4 py-3 text-zinc-300">
            <span aria-hidden="true">{projection.team === selectedGame?.home ? "🏠" : "✈️"}</span>{" "}{projection.team || "—"}
          </td>
          <td className="px-4 py-3 text-sm text-zinc-400">
            vs {projection.opponent}
            {projection.rest_note && <span className="ml-1 text-xs text-zinc-600">({projection.rest_note})</span>}
          </td>
          <td className="px-4 py-3 text-right font-mono font-bold text-indigo-300">{projection.projection}</td>
          <td className="px-4 py-3 text-right">
            {line !== null ? (
              <div>
                <div>{line}</div>
                <div className="text-xs text-zinc-500">{formatAmericanOdds(projection.american_odds)}{projection.bookmaker ? ` · ${projection.bookmaker}` : ""}</div>
              </div>
            ) : <span className="text-zinc-600">—</span>}
          </td>
          <td className="px-4 py-3">
            {projection.direction ? (
              <span className={`rounded border px-2 py-0.5 text-xs font-bold ${projection.direction === "OVER" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400" : "border-red-500/20 bg-red-500/10 text-red-400"}`}>
                {projection.direction}
              </span>
            ) : <span className="whitespace-nowrap text-xs font-semibold text-zinc-500">NO BET</span>}
          </td>
          <td className="px-4 py-3 text-right font-mono text-sm text-yellow-400">{formatSignedPercent(projection.ev_roi)}</td>
          <td className={`px-4 py-3 text-sm font-semibold ${tierClass(projection)}`}>{projection.tier || "Info"}</td>
        </tr>
        {isExpanded && (
          <tr>
            <td colSpan={8} className="p-0"><PlayerDetailPanel player={projection} id={panelId} /></td>
          </tr>
        )}
      </Fragment>
    );
  };

  const renderRankedTable = (players: CheatRow[]) => {
    return (
      <div className="mb-6">
        <div className="mb-3 flex items-center gap-2 px-1">
          <span className="text-lg" aria-hidden="true">🏆</span>
          <h3 className="text-base font-bold text-white">Best edges</h3>
          <span className="text-xs text-zinc-500">actionable picks first, then EV and confidence</span>
        </div>
        <table className="w-full min-w-[920px] text-left text-sm">
          <thead className="bg-zinc-900/50 text-xs uppercase text-zinc-400">
            <tr>
              <th scope="col" className="rounded-tl-md px-4 py-2.5">Player</th>
              <th scope="col" className="px-4 py-2.5">Team</th>
              <th scope="col" className="px-4 py-2.5">Matchup</th>
              <th scope="col" className="px-4 py-2.5 text-right">Proj</th>
              <th scope="col" className="px-4 py-2.5 text-right">Line / price</th>
              <th scope="col" className="px-4 py-2.5">Dir</th>
              <th scope="col" className="px-4 py-2.5 text-right">EV ROI</th>
              <th scope="col" className="rounded-tr-md px-4 py-2.5">Tier</th>
            </tr>
          </thead>
          <tbody>{players.map(renderPlayerRow)}</tbody>
        </table>
      </div>
    );
  };

  const renderedGeneratedAt = formatTimestamp(generatedAt);

  return (
    <Card className="w-full border-zinc-800 bg-zinc-950 text-zinc-100 shadow-2xl">
      <CardHeader className="border-b border-zinc-800 pb-6">
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <div>
            <CardTitle className="flex items-center gap-2 text-2xl font-bold">🔥 Daily Edge Generator</CardTitle>
            <CardDescription className="mt-1 text-zinc-400">Choose a game, then expand a player for probabilities, price, factors, injuries, and trend.</CardDescription>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row">
            <div>
              <label htmlFor="edge-book" className="mb-1 block text-xs uppercase tracking-wider text-zinc-500">Sportsbook</label>
              <select id="edge-book" value={book} onChange={(event) => setBook(event.target.value as (typeof BOOKMAKERS)[number]["key"])} className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500">
                {BOOKMAKERS.map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="edge-date" className="mb-1 block text-xs uppercase tracking-wider text-zinc-500">Game date</label>
              <input id="edge-date" type="date" value={date} onChange={(event) => changeDate(event.target.value)} className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500" />
            </div>
          </div>
        </div>

        {loadingGames ? (
          <div className="mt-4 flex items-center gap-2 text-sm text-zinc-500" role="status"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading games…</div>
        ) : games.length > 0 ? (
          <div className="mt-4 flex flex-wrap gap-2" aria-label="Games">
            {games.map((game) => {
              const selected = selectedGame?.home === game.home && selectedGame?.away === game.away;
              return (
                <button key={game.id || game.game_id || `${game.away}-${game.home}`} type="button" onClick={() => selectGame(game)} aria-pressed={selected} className={`rounded-full border px-3 py-1.5 text-xs transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 ${selected ? "border-emerald-500 bg-emerald-600/20 text-emerald-400 shadow-lg shadow-emerald-900/20" : "border-zinc-700 bg-zinc-900 text-zinc-400 hover:border-zinc-500 hover:text-zinc-300"}`}>
                  {game.away} @ {game.home}
                </button>
              );
            })}
          </div>
        ) : null}
      </CardHeader>

      <CardContent className="min-h-[300px] pt-6">
        {gamesError && !selectedGame && (
          <div className="rounded-md border border-red-900/50 bg-red-950/20 p-4 text-red-400" role="alert">
            <p className="font-semibold">Schedule unavailable</p><p className="mt-1 text-sm">{gamesError}</p>
            <button type="button" onClick={() => setGamesRetry((value) => value + 1)} className="mt-3 rounded bg-red-900/30 px-3 py-2 text-xs font-semibold text-red-200 hover:bg-red-900/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400">Retry schedule</button>
          </div>
        )}

        {!selectedGame && !gamesError && !loadingGames && (
          <div className="flex h-64 w-full flex-col items-center justify-center text-zinc-500"><span className="mb-3 text-4xl" aria-hidden="true">📊</span><p>Select a game above to see projections.</p></div>
        )}

        {loading ? (
          <div className="flex h-64 w-full flex-col items-center justify-center text-center text-zinc-400" role="status"><Loader2 className="mb-4 h-8 w-8 animate-spin text-emerald-500" aria-hidden="true" /><p>Pulling market and player data, then simulating outcomes…</p><p className="mt-2 text-xs text-zinc-600">The first load can take up to 90 seconds.</p></div>
        ) : sheetError ? (
          <div className="rounded-md border border-red-900/50 bg-red-950/20 p-4 text-red-400" role="alert">
            <p className="font-semibold">Edge data unavailable</p><p className="mt-1 text-sm">{sheetError}</p>
            <button type="button" onClick={() => setSheetRetry((value) => value + 1)} className="mt-3 rounded bg-red-900/30 px-3 py-2 text-xs font-semibold text-red-200 hover:bg-red-900/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400">Retry projections</button>
          </div>
        ) : data && data.length > 0 && selectedGame ? (
          <div className="overflow-x-auto">
            {renderedGeneratedAt && <p className="mb-3 text-right text-xs text-zinc-600">Generated <time dateTime={generatedAt || undefined}>{renderedGeneratedAt}</time></p>}
            {oddsStatus?.error && (
              <div className="mb-4 rounded-md border border-yellow-900/40 bg-yellow-950/20 p-3 text-sm text-yellow-300" role="status">
                <strong>Live prices unavailable.</strong> {oddsStatus.error} Projections below are informational where no line is shown.
              </div>
            )}
            {warnings.map((warning) => (
              <div key={warning} className="mb-4 rounded-md border border-yellow-900/40 bg-yellow-950/20 p-3 text-sm text-yellow-300" role="status">
                <strong>Projection warning.</strong> {warning}
              </div>
            ))}
            {data.every((row) => typeof row.line !== "number") && (
              <div className="mb-4 rounded-md border border-yellow-900/40 bg-yellow-950/20 p-3 text-sm text-yellow-400/80">⏳ <strong>Sportsbook lines are not available.</strong> Projections remain informational until side-specific prices arrive.</div>
            )}
            {renderRankedTable(data)}
          </div>
        ) : selectedGame && data && data.length === 0 ? (
          <div className="flex h-64 w-full items-center justify-center text-zinc-500">No projection data is available for this game.</div>
        ) : null}
      </CardContent>
    </Card>
  );
}
