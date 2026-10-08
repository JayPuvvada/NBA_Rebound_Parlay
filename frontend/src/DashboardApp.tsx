import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Bookmark, Check, UserRound, X } from "lucide-react";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { PersonalProvider } from "@/components/PersonalProvider";
import { AccountProvider } from "@/components/AccountProvider";
import { MyPicks } from "@/components/ui/MyPicks";
import { PicksAndLines } from "@/components/ui/PicksAndLines";
import { PlayerResearch } from "@/components/ui/PlayerResearch";
import { buildSelectionSnapshot, demoEnabled, type SavedPick } from "@/lib/personal-picks";
import { usePersonalPicks } from "@/lib/personal-context";
import { BOOKS, locationHash, quoteLabel, readLocation, type Assessment, type DashboardContext, type Page, type Quote } from "@/lib/dashboard";
import "./index.css";

const personalDemo = demoEnabled(import.meta.env.VITE_PERSONAL_DEMO, window.location.hostname);
const syntheticOdds = demoEnabled(import.meta.env.VITE_SYNTHETIC_ODDS, window.location.hostname);
const tabs: { id: Page; label: string }[] = [{ id: "edge", label: "Picks & Lines" }, { id: "lookup", label: "Player Research" }, { id: "picks", label: "My Picks" }];

function AppContent() {
  const [initial] = useState(() => readLocation(window.location.hash));
  const [page, setPage] = useState<Page>(initial.page);
  const [context, setContext] = useState<DashboardContext>(initial.context);
  const [selectedQuote, setSelectedQuote] = useState<Quote>();
  const [pending, setPending] = useState<{ snapshot: SavedPick; label: string } | null>(null);
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const personal = usePersonalPicks();
  const scroll = useRef<Partial<Record<Page, number>>>({});
  const pageRef = useRef(page); pageRef.current = page;
  const contextRef = useRef(context); contextRef.current = context;

  const navigate = useCallback((next: Page) => {
    scroll.current[pageRef.current] = window.scrollY;
    setPage(next);
    window.history.pushState(null, "", locationHash(next, contextRef.current));
    window.requestAnimationFrame(() => window.scrollTo({ top: scroll.current[next] || 0, behavior: "instant" }));
  }, []);
  const update = useCallback((change: Partial<DashboardContext>) => {
    setContext(previous => {
      const next = { ...previous, ...change };
      window.history.replaceState(null, "", locationHash(pageRef.current, next));
      return next;
    });
    if (change.player !== undefined || change.date !== undefined || change.home !== undefined || change.away !== undefined) setSelectedQuote(undefined);
  }, []);
  useEffect(() => {
    const sync = () => {
      const next = readLocation(window.location.hash);
      setPage(next.page); setContext(next.context); setSelectedQuote(undefined);
    };
    window.addEventListener("hashchange", sync); window.addEventListener("popstate", sync);
    return () => { window.removeEventListener("hashchange", sync); window.removeEventListener("popstate", sync); };
  }, []);

  const inspect = (player: string, quote?: Quote) => {
    const next = { ...context, player };
    setContext(next); setSelectedQuote(quote);
    contextRef.current = next;
    navigate("lookup");
  };
  const save = async (quote: Quote, assessment?: Assessment) => {
    try {
      const snapshot = buildSelectionSnapshot(quote, { date: context.date, home: context.home, away: context.away, sport: quote.sport || "basketball_nba", event_id: quote.event_id || undefined, demo: personal?.mode === "demo" || syntheticOdds || quote.source === 'synthetic-local-test' }, assessment);
      if (!personal?.signedIn) {
        setPending({ snapshot, label: `${quoteLabel(quote)} · ${BOOKS[quote.book]}` });
        setNotice("Sign in, then review and save this selection."); navigate("picks"); return;
      }
      if (saving || personal.busy) return;
      setSaving(true); setNotice("");
      if (await personal.save(snapshot)) setNotice("Selection saved to My Picks.");
      else setNotice(personal.error || "The selection could not be saved. Review the account message in My Picks.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "This selection could not be saved."); }
    finally { setSaving(false); }
  };
  const savePending = async () => {
    if (!pending || !personal?.signedIn || saving || personal.busy) return;
    setSaving(true);
    try {
      if (await personal.save(pending.snapshot)) { setPending(null); setNotice("Selection saved to My Picks."); }
      else setNotice("Save did not complete. Review the account message and retry.");
    } finally { setSaving(false); }
  };
  const navigateTabs = (event: KeyboardEvent<HTMLElement>) => {
    const index = tabs.findIndex(tab => tab.id === page);
    const next = event.key === "ArrowRight" ? (index + 1) % 3 : event.key === "ArrowLeft" ? (index + 2) % 3 : event.key === "Home" ? 0 : event.key === "End" ? 2 : null;
    if (next === null) return;
    event.preventDefault(); navigate(tabs[next].id);
    window.requestAnimationFrame(() => document.getElementById(`${tabs[next].id}-tab`)?.focus());
  };

  return <div className="nba-app dark">
    {syntheticOdds && <div className="nba-warning" role="status">Local test mode: synthetic odds—not real sportsbook offers. Schedules and player history are real. Saved selections are samples; calculations remain research-only.</div>}
    <a href="#main-content" className="nba-skip-link" onClick={event => { event.preventDefault(); document.getElementById("main-content")?.focus(); }}>Skip to content</a>
    <header className="nba-header"><div className="nba-header-inner"><a className="nba-brand" href={locationHash("edge", context)} onClick={event => { event.preventDefault(); navigate("edge"); }}><span className="nba-brand-mark">N</span><span>NBA Picks</span></a><button className="nba-account-button" onClick={() => navigate("picks")}><UserRound size={17} /><span>{personal?.signedIn ? "Account" : "Sign in"}</span></button></div></header>
    <div className="nba-container"><nav className="nba-nav" role="tablist" aria-label="NBA workspace" onKeyDown={navigateTabs}>{tabs.map(tab => <button key={tab.id} id={`${tab.id}-tab`} role="tab" aria-controls={`${tab.id}-panel`} aria-selected={page === tab.id} tabIndex={page === tab.id ? 0 : -1} className={page === tab.id ? "selected" : ""} onClick={() => navigate(tab.id)}>{tab.label}{tab.id === "picks" && personal?.signedIn && personal.picks.length > 0 && <span className="nav-count">{personal.picks.length}</span>}</button>)}</nav>
      {notice && <div className="nba-toast" role="status"><Check size={16} /><span>{notice}</span><button className="nba-icon-button" aria-label="Dismiss message" onClick={() => setNotice("")}><X size={16} /></button></div>}
      <main id="main-content" tabIndex={-1}>
        <div id="edge-panel" role="tabpanel" aria-labelledby="edge-tab" hidden={page !== "edge"}><ErrorBoundary resetKey={page}><PicksAndLines active={page === "edge"} context={context} update={update} inspect={inspect} save={(quote, assessment) => void save(quote, assessment)} /></ErrorBoundary></div>
        <div id="lookup-panel" role="tabpanel" aria-labelledby="lookup-tab" hidden={page !== "lookup"}><ErrorBoundary resetKey={page}><PlayerResearch active={page === "lookup"} context={context} update={update} quote={selectedQuote} back={() => navigate("edge")} save={quote => void save(quote)} /></ErrorBoundary></div>
        <div id="picks-panel" role="tabpanel" aria-labelledby="picks-tab" hidden={page !== "picks"}><ErrorBoundary resetKey={page}>
          {pending && <section className="nba-card pending-selection"><Bookmark size={20} /><div><h2>Selection ready to save</h2><p>{pending.label}</p><p className="nba-meta">Review this captured selection after signing in.</p></div><button className="nba-button" disabled={!personal?.signedIn || personal.busy || saving} onClick={() => void savePending()}>{saving ? "Saving…" : "Save reviewed selection"}</button><button className="nba-icon-button" aria-label="Discard pending selection" onClick={() => setPending(null)}><X size={18} /></button></section>}
          <MyPicks key={personal?.signedIn ? personal.username : "signed-out"} />
        </ErrorBoundary></div>
      </main>
      <footer className="nba-footer">Research only. No bets are placed.</footer>
    </div>
  </div>;
}

export default function DashboardApp() {
  return personalDemo ? <PersonalProvider><AppContent /></PersonalProvider> : <AccountProvider><AppContent /></AccountProvider>;
}
