import { useEffect, useRef, useState } from "react";
import { ArrowRight, RefreshCw, Search, SlidersHorizontal } from "lucide-react";
import { ApiRequestError, fetchJson, validateGamesResponse } from "@/lib/api";
import { BOOKS, contextKey, formatPrice, isBetterPrice, quoteLabel, reasonLabel,
  sportFor, validateBoard, validateGeneration, filterMarketQuotes, mergeGeneration, defaultGame,
  type Assessment, type Board, type DashboardContext, type Generation, type Quote } from "@/lib/dashboard";
import type { Game } from "@/types/api";
import { useQuoteFreshness } from "@/lib/use-quote-freshness";
import { AnalysisVisuals } from './AnalysisVisuals';

interface Props {
  active: boolean; context: DashboardContext;
  update: (change: Partial<DashboardContext>) => void;
  inspect: (player: string, quote?: Quote) => void;
  save: (quote: Quote, assessment?: Assessment) => void;
}

const cancelled = (error: unknown) => error instanceof ApiRequestError && error.kind === "aborted";
const errorText = (error: unknown) => error instanceof Error ? error.message : "This request could not be completed.";
const timeLabel = (value?: string | null) => {
  if (!value || !Number.isFinite(Date.parse(value))) return "Update time unknown";
  return `Updated ${new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`;
};
const kinds = { model_pick: "Model pick", experimental_candidate: "Experimental candidate", no_pick: "No qualifying pick", needs_input: "More information needed", unavailable: "Data unavailable" };

export function ModelPickCard({ row, onInspect, onSave, minutes, setMinutes, rerun, busy }: {
  row: Assessment; onInspect: () => void; onSave: () => void; minutes: string;
  setMinutes: (value: string) => void; rerun: () => void; busy: boolean;
}) {
  const candidate = row.result_kind === "model_pick" || row.result_kind === "experimental_candidate";
  const synthetic = row.quote?.source === 'synthetic-local-test';
  const freshness = useQuoteFreshness(row.quote || undefined);
  return <article className={`nba-card pick-card ${candidate ? "pick-candidate" : ""}`}>
    <div className="nba-card-top"><span className={`nba-badge ${row.result_kind === "experimental_candidate" || synthetic ? "amber" : ""}`}>{synthetic ? 'Sample analysis' : kinds[row.result_kind]}</span><span className="nba-meta">{row.team}</span></div>
    <h3>{row.player}</h3>
    {candidate && row.quote ? <p className="pick-selection">{row.quote.selection} {row.quote.line} <span>{formatPrice(row.quote.odds)}</span></p> : <p className="nba-muted">{synthetic ? 'Calculation completed with synthetic odds. Expand analysis to inspect the scenario; no live recommendation is issued.' : reasonLabel(row.reason_code)}</p>}
    <dl className="nba-metrics"><div><dt>{row.result_kind === "experimental_candidate" ? "Scenario rebounds" : "Estimated rebounds"}</dt><dd>{row.projection == null ? "—" : row.projection.toFixed(1)}</dd></div><div><dt>{row.minutes?.source === "primary_model" ? "Estimated minutes" : "Minutes assumption"}</dt><dd>{row.minutes?.value == null ? "—" : row.minutes.value.toFixed(1)}</dd></div></dl>
    {row.limitations[0] && <p className="nba-risk">{row.limitations[0]}</p>}
    {row.result_kind === "needs_input" && <div className="nba-inline-input"><label>Minutes for {row.player}<input type="number" min="0" max="48" step="0.5" value={minutes} onChange={e => setMinutes(e.target.value)} placeholder="e.g. 20" /></label><button className="nba-button secondary" disabled={busy || minutes.trim() === "" || !Number.isFinite(Number(minutes)) || Number(minutes) < 0 || Number(minutes) > 48} onClick={rerun}>Calculate</button></div>}
    <div className="nba-actions"><button className="nba-button secondary" onClick={onInspect}>Inspect player <ArrowRight size={15} /></button>{(candidate || synthetic) && row.quote && <button className="nba-button" onClick={onSave}>{synthetic ? 'Save sample analysis' : 'Save selection'}</button>}</div>
    <details className="nba-details"><summary>Advanced analysis</summary><p className="nba-meta">{row.profile?.replaceAll("_", " ")} · {row.model_version || "Version unavailable"}</p>
      {row.quote && <p className="nba-meta">{BOOKS[row.quote.book]} · {timeLabel(row.quote.updated_at)} · {freshness}</p>}
      <AnalysisVisuals row={row} />
      {row.result_kind === "experimental_candidate" && <p>Scenario probabilities use assumed minutes and heuristic dispersion; they have not been calibrated for this competition.</p>}
      {row.limitations.map((limitation, index) => <p key={index}>{limitation}</p>)}
    </details>
  </article>;
}

export function QuoteCard({ quote, comparable, compare, inspect, save }: { quote: Quote; comparable: Quote[]; compare: boolean; inspect: () => void; save: () => void }) {
  const better = compare && isBetterPrice(quote, comparable);
  const freshness = useQuoteFreshness(quote);
  return <article className="nba-card quote-card"><div className="nba-card-top"><span className="nba-meta">{BOOKS[quote.book]}</span><span className={`nba-badge ${freshness !== "fresh" ? "amber" : ""}`}>{freshness === "unknown" ? "Freshness unknown" : freshness === "stale" ? "Stale quote" : "Recent quote"}</span></div>
    <h3>{quote.player || quote.team || "Game total"}</h3><div className="quote-value"><span>{quote.selection}{quote.line == null ? "" : ` ${quote.market === "spreads" && quote.line > 0 ? "+" : ""}${quote.line}`}</span><strong>{formatPrice(quote.odds)}</strong></div>
    {better && <p className="nba-positive">Better price for this exact selection</p>}<p className="nba-meta">{timeLabel(quote.updated_at)}</p>
    <div className="nba-actions">{quote.player && <button className="nba-button secondary" onClick={inspect}>Research</button>}<button className="nba-button secondary" onClick={save} aria-label={`Save ${quoteLabel(quote)} at ${BOOKS[quote.book]}`}>Save selection</button></div>
  </article>;
}

export function PicksAndLines({ active, context, update, inspect, save }: Props) {
  const [games, setGames] = useState<Game[]>([]);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [scheduleError, setScheduleError] = useState("");
  const [scheduleMessage, setScheduleMessage] = useState("");
  const [scheduleRetry, setScheduleRetry] = useState(0);
  const [boards, setBoards] = useState<Record<string, Board>>({});
  const [boardLoading, setBoardLoading] = useState(false);
  const [boardError, setBoardError] = useState("");
  const [generations, setGenerations] = useState<Record<string, Generation>>({});
  const [generationLoading, setGenerationLoading] = useState(false);
  const [generationError, setGenerationError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [minutes, setMinutes] = useState<Record<string, string>>({});
  const [search, setSearch] = useState("");
  const [teamFilter, setTeamFilter] = useState("");
  const boardRequest = useRef<AbortController | null>(null);
  const generationRequest = useRef<AbortController | null>(null);
  const contextRef = useRef(context);
  contextRef.current = context;
  const game = games.find(g => g.home === context.home && g.away === context.away);
  const sport = sportFor(game);
  const key = contextKey(context, sport);
  const boardKey = `${context.date}:${sport}:${context.home}:${context.away}:rebounds`;
  const board = boards[boardKey];
  const generation = generations[key];
  useEffect(() => {
    if (context.market !== 'player_rebounds') update({ market: 'player_rebounds' });
  }, [context.market, update]);

  useEffect(() => {
    const controller = new AbortController();
    setScheduleLoading(true); setScheduleError(""); setGames([]);
    void fetchJson<unknown>(`/games?date=${encodeURIComponent(context.date)}`, { signal: controller.signal }).then(raw => {
      const result = validateGamesResponse(raw);
      if (controller.signal.aborted) return;
      setGames(result.games); setScheduleMessage(result.message || "");
      const selection = contextRef.current;
      if (!result.games.some(g => g.home === selection.home && g.away === selection.away)) {
        const next = defaultGame(result.games);
        update({ home: next?.home || "", away: next?.away || "" });
      }
    }).catch(error => { if (!controller.signal.aborted) setScheduleError(errorText(error)); }).finally(() => { if (!controller.signal.aborted) setScheduleLoading(false); });
    return () => controller.abort();
  }, [context.date, scheduleRetry, update]);

  useEffect(() => {
    generationRequest.current?.abort(); generationRequest.current = null;
    setGenerationLoading(false); setGenerationError("");
    return () => { generationRequest.current?.abort(); };
  }, [key]);

  useEffect(() => {
    if (!generationLoading) return;
    setElapsed(0);
    const timer = window.setInterval(() => setElapsed(n => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [generationLoading]);

  const loadBoard = async (refresh: boolean) => {
    boardRequest.current?.abort();
    if (!context.home || !game) { setBoardLoading(false); return; }
    const controller = new AbortController(); boardRequest.current = controller;
    setBoardLoading(true); setBoardError("");
    const params = new URLSearchParams({ date: context.date, home: context.home, away: context.away, sport, books: Object.keys(BOOKS).join(","), group: 'rebounds', refresh: String(refresh) });
    try {
      const result = validateBoard(await fetchJson<unknown>(`/markets?${params}`, { signal: controller.signal }), context);
      if (controller.signal.aborted || boardRequest.current !== controller) return;
      setBoards(previous => ({ ...previous, [boardKey]: result }));
    } catch (error) {
      if (cancelled(error) || controller.signal.aborted || boardRequest.current !== controller) return;
      setBoardError(errorText(error));
      setBoards(previous => previous[boardKey] ? { ...previous, [boardKey]: { ...previous[boardKey], status: "stale", quotes: previous[boardKey].quotes.map(q => ({ ...q, freshness: "stale" })) } } : previous);
    } finally { if (boardRequest.current === controller) { setBoardLoading(false); boardRequest.current = null; } }
  };
  useEffect(() => {
    if (active && game) void loadBoard(false);
    return () => { boardRequest.current?.abort(); boardRequest.current = null; };
    // Context is represented by boardKey; book filtering reuses the shared board.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, boardKey, !!game]);

  const generate = async (players?: string[]) => {
    if (!game || generationRequest.current) return;
    const controller = new AbortController(); generationRequest.current = controller;
    setGenerationLoading(true); setGenerationError("");
    const inputs = Object.fromEntries(Object.entries(minutes).filter(([, value]) => value.trim() !== "").map(([id, value]) => [id, Number(value)]));
    try {
      const payload = { date: context.date, home: context.home, away: context.away, sport, book: context.book, minutes: inputs, ...(players ? { players } : {}) };
      const result = validateGeneration(await fetchJson<unknown>("/generate-picks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: controller.signal }, { timeoutMs: 85_000 }), context);
      if (controller.signal.aborted || generationRequest.current !== controller) return;
      setGenerations(previous => {
        const prior = previous[key];
        if (!players || !prior) return { ...previous, [key]: result };
        return { ...previous, [key]: mergeGeneration(prior, result) };
      });
    } catch (error) { if (!cancelled(error) && !controller.signal.aborted && generationRequest.current === controller) setGenerationError(errorText(error)); }
    finally { if (generationRequest.current === controller) { generationRequest.current = null; setGenerationLoading(false); } }
  };

  const marketQuotes = (board?.quotes || []).filter(q => q.market === 'player_rebounds');
  const { available, visible: quotes } = filterMarketQuotes(board?.quotes || [], 'player_rebounds', context.book, false, search, teamFilter);
  const teamOptions = [...new Set(marketQuotes.map(q => q.team).filter((t): t is string => !!t))];
  const assessments = [...(generation?.assessments || [])].sort((a, b) => Number(["model_pick", "experimental_candidate"].includes(b.result_kind)) - Number(["model_pick", "experimental_candidate"].includes(a.result_kind)));
  const noQuotes = board && available.length === 0;
  const coverage = board?.coverage[context.book]?.player_rebounds;
  const emptyMessage = board?.message || (board?.status === "unconfigured" ? "The sportsbook connection has not been configured." : board?.status === "event_missing" ? "No sportsbook event matched this scheduled game." : board?.status === "budget_limit" ? "The shared refresh budget has been reached." : board?.status === "provider_unavailable" ? "The sportsbook provider is unavailable." : board?.status === "empty" && game?.is_preseason ? "No preseason rebound lines were returned for this sportsbook. Preseason player-prop coverage can be limited; this is not an NBA statistics error. Player Research remains available." : coverage === "book_missing" ? "This book has not returned quotes for this game." : "No rebound props were returned for this game and sportsbook.");

  return <div className="nba-page">
    <div className="nba-page-heading"><div><p className="nba-eyebrow">Your NBA workspace</p><h1>Picks & Lines</h1><p className="nba-muted">Find a game, generate rebound picks, and keep the selections you want to follow.</p></div></div>
    <section className="nba-card game-controls" aria-label="Game selection"><div className="nba-control-row"><label>Game date<input type="date" value={context.date} onChange={e => update({ date: e.target.value, home: "", away: "" })} /></label><label>Sportsbook<select value={context.book} onChange={e => update({ book: e.target.value as DashboardContext["book"] })}>{Object.entries(BOOKS).map(([book, title]) => <option value={book} key={book}>{title}</option>)}</select></label><button className="nba-button generate-button" onClick={() => void generate()} disabled={!game || generationLoading || boardLoading || !available.length} aria-describedby="generation-help">Generate rebound picks <ArrowRight size={16} /></button></div>
      <p id="generation-help" className="nba-meta">{boardLoading ? 'Checking rebound lines…' : game && !available.length ? 'Generation needs offered rebound lines for this sportsbook. Player Research still works without lines.' : 'Uses the rebound lines below. Results explain their assumptions; a qualifying selection is not guaranteed.'}</p>
      {scheduleLoading ? <p role="status" className="nba-muted">Loading games…</p> : scheduleError ? <div className="nba-error" role="alert"><p>{scheduleError}</p><button className="nba-button secondary" onClick={() => setScheduleRetry(n => n + 1)}>Retry schedule</button></div> : !games.length ? <p className="nba-muted">{scheduleMessage || "No games were found for this date."}</p> : <div className="game-rail" aria-label="Matchups">{games.map(g => <button key={`${g.home}:${g.away}:${g.id || ""}`} className={`game-chip ${g.home === context.home && g.away === context.away ? "selected" : ""}`} aria-pressed={g.home === context.home && g.away === context.away} onClick={() => update({ home: g.home, away: g.away })}><strong>{g.away} <span>at</span> {g.home}</strong><small>{g.is_preseason ? "Preseason" : "Regular season"}{g.game_time ? ` · ${g.game_time}` : ""}</small></button>)}</div>}
    </section>

    <section aria-labelledby="model-picks-title"><div className="nba-section-heading"><h2 id="model-picks-title">Rebound analysis</h2>{generation && <span className="nba-meta">{generation.coverage.completed} / {generation.coverage.total} players evaluated</span>}</div>
      {generationLoading && <div className="nba-state" role="status"><p>Loading player inputs and calculating picks · {elapsed}s</p><p className="nba-meta">Completed results are kept if some players cannot be loaded.</p><button className="nba-button secondary" onClick={() => { generationRequest.current?.abort(); generationRequest.current = null; setGenerationLoading(false); }}>Cancel</button></div>}
      {generationError && <div className="nba-error" role="alert">{generationError}<button className="nba-button secondary" onClick={() => void generate()}>Retry generation</button></div>}
      {!generation && !generationLoading && <div className="nba-state"><SlidersHorizontal size={22} /><p>{game && noQuotes ? 'No rebound lines to evaluate at this sportsbook.' : 'Choose a game, then generate analysis from its offered rebound lines.'}</p><p className="nba-meta">{game && noQuotes ? 'The model needs a sportsbook rebound line to compare against. Check the line-source status below, try another sportsbook, or research a player without odds.' : 'Preseason and early-season calculations are experimental and show their minutes assumptions.'}</p>{game && noQuotes && <button className="nba-button secondary" onClick={() => inspect('')}>Open player research</button>}</div>}
      {generation?.message && <p className="nba-notice">{generation.message}</p>}
      {generation?.status === "no_quotes" && <div className="nba-state"><p>No rebound quotes are available to evaluate.</p><button className="nba-button secondary" onClick={() => inspect("")}>Open manual player research</button></div>}
      {generation && generation.status !== "no_quotes" && !assessments.length && <div className="nba-state"><p>{generation.message || reasonLabel(generation.status)}</p><button className="nba-button secondary" disabled={generationLoading} onClick={() => void generate()}>Retry generation</button></div>}
      {!!generation?.coverage.incomplete.length && <div className="nba-notice">Incomplete: {generation.coverage.incomplete.join(", ")}. <button className="nba-text-button" disabled={generationLoading} onClick={() => void generate(generation.coverage.incomplete)}>Retry remaining</button></div>}
      <div className="nba-card-grid">{assessments.map(row => <ModelPickCard key={row.player} row={row} onInspect={() => inspect(row.player, row.quote || undefined)} onSave={() => row.quote && save(row.quote, row)} minutes={minutes[String(row.player_id || row.player)] || ""} setMinutes={value => setMinutes(previous => ({ ...previous, [String(row.player_id || row.player)]: value }))} rerun={() => void generate([row.player])} busy={generationLoading} />)}</div>
    </section>

    <section aria-labelledby="sportsbook-lines-title"><div className="nba-section-heading"><div><h2 id="sportsbook-lines-title">Rebound lines</h2><p className="nba-meta">Over and Under prices from your selected sportsbook. Save a selection or research its player.</p></div><button className="nba-button secondary" disabled={!game || boardLoading} onClick={() => void loadBoard(true)}><RefreshCw size={15} className={boardLoading ? "animate-spin" : ""} />Refresh</button></div>
      {!!available.length && <div className="nba-filter-row"><label className="nba-search"><Search size={16} /><input aria-label="Search players or teams" placeholder="Search players or teams" value={search} onChange={e => setSearch(e.target.value)} /></label>{teamOptions.length > 0 && <select aria-label="Filter team" value={teamFilter} onChange={e => setTeamFilter(e.target.value)}><option value="">All teams</option>{teamOptions.map(team => <option key={team}>{team}</option>)}</select>}</div>}
      {boardLoading && <p className="nba-muted" role="status">Loading this market…</p>}
      {(boardError || board?.refresh_error) && <p className="nba-error" role="alert">{boardError || board?.refresh_error} {board?.quotes.length ? "Previously fetched quotes are shown as stale." : ""}</p>}
      {!boardLoading && (!game || noQuotes) && <div className="nba-state"><p>{game ? emptyMessage : "Choose a scheduled game to see available lines."}</p>{game && <button className="nba-button secondary" onClick={() => void loadBoard(true)}>Retry this market</button>}</div>}
      {!!available.length && !quotes.length && <div className="nba-state"><p>No selections match your filters.</p><button className="nba-button secondary" onClick={() => { setSearch(""); setTeamFilter(""); }}>Clear filters</button></div>}
      <div className="nba-card-grid quote-grid">{quotes.map(q => <QuoteCard key={`${q.book}:${q.player}:${q.team}:${q.selection}:${q.line}`} quote={q} comparable={[]} compare={false} inspect={() => q.player && inspect(q.player, q)} save={() => save(q)} />)}</div>
      {board && <details className="nba-details source-details"><summary>Source and refresh details</summary><p>Source: The Odds API · {board.cached ? "Shared cached response" : "Retrieved response"} · {timeLabel(board.fetched_at)}</p><p>Provider update time is shown separately on each selection; retrieval time does not establish freshness.</p>{board.budget && <p>Shared refresh use: {board.budget.daily_used}/{board.budget.daily_limit} credits today; {board.budget.cycle_used}/{board.budget.cycle_limit} this quota cycle.</p>}</details>}
    </section>
  </div>;
}
