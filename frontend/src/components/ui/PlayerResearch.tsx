import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowLeft, Search } from "lucide-react";
import { ApiRequestError, fetchJson } from "@/lib/api";
import { useQuoteFreshness } from "@/lib/use-quote-freshness";
import { validateHistory, quoteLabel, formatPrice, BOOKS, type DashboardContext, type History, type HistoryResponse, type Quote } from "@/lib/dashboard";
const PredictForm = lazy(() => import("./PredictForm").then(module => ({ default: module.PredictForm })));

const historyNames: Record<string, string> = { preseason: "Earlier preseason", prior_season: "Prior regular season", current_season: "Current regular season" };

export function ObservedHistoryCard({ history }: { history: History }) {
  const recent = history.recent_games || [];
  const maxRebounds = Math.max(1, ...recent.map(game => game.rebounds));
  const frequency = history.observed_above_line;
  return <article className="nba-card research-history"><div className="nba-card-top"><h2>{historyNames[history.kind] || history.kind.replaceAll("_", " ")}</h2><span className="nba-badge">{history.season}</span></div>
    <p className="nba-meta">{history.games} observed appearances · {history.source || "Source unavailable"}</p>
    {history.date_range?.from && history.date_range?.to && <p className="nba-meta">{history.date_range.scope === "displayed_recent_games" ? "Displayed sample" : "Observed sample"}: {history.date_range.from} to {history.date_range.to}</p>}
    {history.status === "available" ? <>
      <dl className="nba-metrics"><div><dt>Observed rebounds / game</dt><dd>{history.rebounds_per_game?.toFixed(1) ?? "—"}</dd></div><div><dt>Observed minutes / game</dt><dd>{history.minutes_per_game?.toFixed(1) ?? "—"}</dd></div></dl>
      <div className="nba-window-metrics">{([5, 10] as const).map(window => {
        const sample = window === 5 ? history.last_5 : history.last_10;
        return <div key={window}><span>Last {window}</span><strong>{sample ? `${sample.rebounds.toFixed(1)} REB · ${sample.minutes.toFixed(1)} MIN` : `Needs ${window} appearances`}</strong></div>;
      })}</div>
      {frequency && <p className="nba-notice">Observed frequency at {frequency.line}: {frequency.above}/{frequency.games} above{frequency.below == null ? "" : `, ${frequency.below} below`}{frequency.push == null ? "" : `, ${frequency.push} equal`}. This is a historical count of the displayed recent appearances.</p>}
      {recent.length > 0 && <><figure className="nba-history-chart" aria-label="Rebounds in the most recent observed appearances"><div className="nba-bars" aria-hidden="true">{[...recent].reverse().map(game => <div key={game.date}><span>{game.rebounds}</span><i style={{ height: `${Math.max(4, game.rebounds / maxRebounds * 82)}px` }} /><small>{game.date.slice(5)}</small></div>)}</div><figcaption>Recent rebounds · earliest to latest. Exact observations are listed below.</figcaption></figure>
        <table className="nba-history-table"><caption>Recent observed appearances, most recent first</caption><thead><tr><th>Date</th><th>Minutes</th><th>Rebounds</th></tr></thead><tbody>{recent.map((game, index) => <tr key={`${game.date}:${index}`}><td>{game.date}</td><td>{game.minutes.toFixed(1)}</td><td>{game.rebounds}</td></tr>)}</tbody></table><p className="nba-meta">Recent sample: {recent[recent.length - 1].date} to {recent[0].date}. All appearances precede the selected date.</p></>}
    </> : <div className="nba-state"><p>{history.status === "empty" ? "No earlier appearances were found in this competition." : "This history source could not be loaded."}</p><p className="nba-meta">Missing history is not a zero-rebound average.</p></div>}
  </article>;
}

export function PlayerResearch({ active, context, update, quote, back, save }: {
  active: boolean; context: DashboardContext; update: (change: Partial<DashboardContext>) => void;
  quote?: Quote; back: () => void; save: (quote: Quote) => void;
}) {
  const [player, setPlayer] = useState(context.player);
  const freshness = useQuoteFreshness(quote);
  const [line, setLine] = useState(quote?.line == null ? "" : String(quote.line));
  const [preseason, setPreseason] = useState(quote?.sport === "basketball_nba_preseason");
  const [result, setResult] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [projectionOpened, setProjectionOpened] = useState(false);
  const request = useRef<AbortController | null>(null);
  const lastRequested = useRef("");
  const submitted = useRef("");
  const inputs = useRef({ player, line, preseason });
  inputs.current = { player, line, preseason };
  const quoteIdentity = quote ? JSON.stringify([quote.event_id, quote.book, quote.line, quote.selection, quote.sport]) : "";
  const initialKey = `${context.player}:${context.date}:${quoteIdentity}`;

  useEffect(() => {
    if (submitted.current === initialKey) { submitted.current = ""; return; }
    setPlayer(context.player);
    setLine(quote?.line == null ? "" : String(quote.line));
    if (quote?.sport) setPreseason(quote.sport === "basketball_nba_preseason");
    lastRequested.current = "";
    setResult(null); setError("");
    // The incoming game/player identity controls these initial inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialKey]);

  const load = async (name: string, requestedLine: string, isPreseason: boolean) => {
    request.current?.abort();
    if (!name.trim()) return;
    const value = requestedLine.trim() === "" ? null : Number(requestedLine);
    if (value !== null && (!Number.isFinite(value) || value < 0 || value > 100)) { setError("Enter a rebound line between 0 and 100."); return; }
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setError("");
    setResult(null);
    const params = new URLSearchParams({ player: name.trim(), date: context.date, preseason: String(isPreseason) });
    if (value !== null) params.set("line", String(value));
    try {
      const response = validateHistory(await fetchJson<unknown>(`/player-history?${params}`, { signal: controller.signal }, { timeoutMs: 40_000 }), name.trim(), context.date);
      if (!controller.signal.aborted && request.current === controller) setResult(response);
    } catch (error) {
      if (controller.signal.aborted || request.current !== controller || error instanceof ApiRequestError && error.kind === "aborted") return;
      setError(error instanceof Error ? error.message : "Could not load this player's history.");
    } finally { if (request.current === controller) { request.current = null; setLoading(false); } }
  };

  useEffect(() => {
    if (!active || !context.player) return;
    const key = initialKey;
    if (lastRequested.current === key) return;
    lastRequested.current = key;
    void load(context.player, quote?.line == null ? inputs.current.line : String(quote.line), quote?.sport ? quote.sport === "basketball_nba_preseason" : inputs.current.preseason);
    const controller = request.current;
    return () => { if (request.current === controller && controller) { controller.abort(); request.current = null; lastRequested.current = ""; setLoading(false); } };
    // Requests are triggered by explicit incoming selection or retry, not every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, initialKey]);

  useEffect(() => {
    if (!active) { request.current?.abort(); request.current = null; setLoading(false); }
  }, [active]);

  useEffect(() => () => { request.current?.abort(); }, []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (player.trim() !== context.player) {
      const nextKey = `${player.trim()}:${context.date}:${quote?.player === player.trim() ? quoteIdentity : ""}`;
      submitted.current = nextKey;
      lastRequested.current = nextKey;
      update({ player: player.trim() });
    }
    void load(player, line, preseason);
  };

  return <div className="nba-page">
    <div className="nba-page-heading"><div><p className="nba-eyebrow">Understand the selection</p><h1>Player Research</h1><p className="nba-muted">Rebounds, minutes, and recent appearances—with the source and sample visible.</p></div><button className="nba-button secondary" onClick={back}><ArrowLeft size={15} />Back to picks</button></div>
    <form className="nba-card research-controls" onSubmit={submit}><label>Player<input value={player} onChange={e => setPlayer(e.target.value)} maxLength={100} placeholder="e.g. Nikola Jokic" required autoComplete="off" /></label><label>Before date<input type="date" value={context.date} onChange={e => update({ date: e.target.value, home: "", away: "" })} required /></label><label>Compare line<input type="number" min="0" max="100" step="0.5" value={line} onChange={e => setLine(e.target.value)} placeholder="Optional" /></label><label>Competition<select value={preseason ? "preseason" : "regular"} onChange={e => setPreseason(e.target.value === "preseason")}><option value="regular">Regular season</option><option value="preseason">Preseason</option></select></label><button className="nba-button" disabled={loading}><Search size={16} />Load history</button></form>
    {quote && context.player === quote.player && <section className="nba-card research-quote"><div><span className="nba-meta">Selected quote · {BOOKS[quote.book]}</span><h2>{quoteLabel(quote)}</h2><p>{formatPrice(quote.odds)} · {freshness === "unknown" ? "Freshness unknown" : `${freshness} quote`}</p></div><button className="nba-button secondary" onClick={() => save(quote)}>Save selection</button></section>}
    {loading && <div className="nba-state" role="status"><p>Loading observed player history…</p><button className="nba-button secondary" onClick={() => { request.current?.abort(); request.current = null; lastRequested.current = ""; setLoading(false); }}>Cancel</button></div>}
    {error && <div className="nba-error" role="alert"><p>{error}</p><button className="nba-button secondary" onClick={() => void load(player, line, preseason)}>Retry history</button></div>}
    {result && (result.status === 'partial' || result.status === 'unavailable' || result.histories.some(history => history.status === 'unavailable')) && <div className="nba-notice" role="status"><p>{result.status === 'unavailable' ? 'Player history could not be loaded.' : 'Some history sources could not be loaded. Available observations are shown below.'} {result.reason_code === 'deadline_exceeded' ? 'The research time limit was reached.' : result.reason_code === 'player_identity_unverified' ? 'The player identity could not be verified; check the name.' : 'Retry history without refreshing sportsbook lines.'}</p><button className="nba-button secondary" disabled={loading} onClick={() => void load(player, line, preseason)}>Retry history</button></div>}
    {result && <><p className="nba-meta">{result.message}</p><div className="nba-card-grid research-grid">{result.histories.map(history => <ObservedHistoryCard key={`${history.kind}:${history.season}`} history={history} />)}</div></>}
    {!result && !loading && !error && <div className="nba-state"><p>Search a player, or open research from a rebound selection.</p><p className="nba-meta">History loads without requiring a projection.</p></div>}
    <details className="nba-card nba-details manual-model" onToggle={event => { if (event.currentTarget.open) setProjectionOpened(true); }}><summary>Optional projection and advanced inputs</summary><p className="nba-meta">Run the regular-season model explicitly with manual inputs. Entered prices are unverified; historical checks are analysis only.</p>{projectionOpened && <Suspense fallback={<p role="status">Loading model inputs…</p>}><PredictForm initialPlayer={context.player} initialDate={context.date} initialQuote={quote} initialOpponent={quote?.team ? quote.team === context.home ? context.away : context.home : undefined} /></Suspense>}</details>
  </div>;
}
