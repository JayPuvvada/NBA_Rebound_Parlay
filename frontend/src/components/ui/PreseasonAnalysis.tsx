import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { PreseasonMarkets } from '@/components/ui/PreseasonMarkets';
import { ApiRequestError } from '@/lib/api';
import { fetchPreseasonPlayer, fetchPreseasonRoster } from '@/lib/preseason';
import type { HistorySummary, PreseasonPlayer, PreseasonRoster } from '@/lib/preseason';

const buttonClass = 'rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-200 hover:border-emerald-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400';

function WarningList({ warnings }: { warnings: string[] }) {
  return warnings.length > 0 ? <ul className="mt-3 list-disc space-y-1 pl-5 text-xs leading-relaxed text-amber-200">{warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}</ul> : null;
}

export function HistoryCard({ title, summary }: { title: string; summary: HistorySummary }) {
  return <section className="rounded-lg border border-zinc-800 p-4">
    <h4 className="font-semibold text-zinc-100">{title} · {summary.season}</h4>
    {summary.status === 'available' ? <>
      <p className="mt-1 text-xs text-zinc-400">Observed history, not a forecast · {summary.games} games</p>
      <dl className="mt-3 grid grid-cols-3 gap-3 text-sm">
        <div><dt className="text-xs text-zinc-500">Rebounds / game</dt><dd className="mt-1 font-mono text-zinc-100">{summary.rebounds_per_game?.toFixed(1)}</dd></div>
        <div><dt className="text-xs text-zinc-500">Minutes / game</dt><dd className="mt-1 font-mono text-zinc-100">{summary.minutes_per_game?.toFixed(1)}</dd></div>
        <div><dt className="text-xs text-zinc-500">Rebounds / minute</dt><dd className="mt-1 font-mono text-zinc-100">{summary.rebounds_per_minute?.toFixed(3)}</dd></div>
      </dl>
      {summary.recent_games && summary.recent_games.length > 0 && <div className="mt-4">
        <p className="text-xs text-zinc-500">Most recent earlier appearances</p>
        <table className="mt-2 w-full text-left text-xs text-zinc-300">
          <thead className="text-zinc-500"><tr><th>Date</th><th>Minutes</th><th>Rebounds</th></tr></thead>
          <tbody>{summary.recent_games.map(game => <tr key={game.date}><td className="py-1">{game.date}</td><td>{game.minutes.toFixed(1)}</td><td>{game.rebounds}</td></tr>)}</tbody>
        </table>
      </div>}
    </> : <p className="mt-2 text-sm text-zinc-400">{summary.status === 'empty' ? 'No eligible earlier games found. This is not a zero-rebound average.' : 'History could not be loaded. Retry player history below.'}</p>}
    {summary.source && <p className="mt-3 text-xs text-zinc-500">Source: {summary.source}</p>}
  </section>;
}

function PlayerHistory({ player, team, opponent, date }: { player: { player_id: number; name: string }; team: string; opponent: string; date: string }) {
  const [data, setData] = useState<PreseasonPlayer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [minutesText, setMinutesText] = useState('');
  const [minutesError, setMinutesError] = useState<string | null>(null);
  const [request, setRequest] = useState<{ minutes?: number; revision: number }>({ revision: 0 });

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      setError(null);
      setData(null);
      try {
        const response = await fetchPreseasonPlayer({ player_id: player.player_id, team, opponent, date, minutes: request.minutes }, controller.signal);
        if (!controller.signal.aborted) setData(response);
      } catch (failure: unknown) {
        if (controller.signal.aborted || (failure instanceof ApiRequestError && failure.kind === 'aborted')) return;
        setError(failure instanceof Error ? failure.message : 'Player history could not be loaded.');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, [player.player_id, team, opponent, date, request]);

  return <section className="mt-5 border-t border-zinc-800 pt-5" aria-label={`${player.name} preseason analysis`}>
    <h3 className="text-lg font-semibold text-white">{player.name} · {team}</h3>
    <p className="mt-1 text-xs text-zinc-400">Only games before {date} are used. No win probability, betting edge or saved pick is issued here.</p>
    {loading ? <p className="mt-4 flex items-center gap-2 text-sm text-zinc-400" role="status"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading this player’s real history…</p> : error ? <div className="mt-4 rounded border border-red-900 bg-red-950/20 p-4 text-red-300" role="alert"><p>{error}</p><button type="button" className={`${buttonClass} mt-3`} onClick={() => setRequest(current => ({ ...current, revision: current.revision + 1 }))}>Retry player history</button></div> : data ? <>
      <div className="mt-4 grid gap-3 md:grid-cols-2"><HistoryCard title="Prior season" summary={data.prior_season} /><HistoryCard title="Earlier preseason" summary={data.preseason} /></div>
      <div className="mt-4 rounded-lg border border-amber-800/60 bg-amber-950/10 p-4">
        <h4 className="font-semibold text-amber-200">Experimental minutes scenario · not a betting projection</h4>
        <p className="mt-2 text-sm text-zinc-400">Prior-season rebounds per minute × assumed playing time. This does not model preseason rotations, injuries, matchup or a changed role.</p>
        {data.estimate ? <div className="mt-3">
          <p className="text-lg text-zinc-100"><strong>{data.estimate.rebounds.toFixed(1)}</strong> rebounds at {data.estimate.minutes.toFixed(1)} minutes</p>
          <p className="mt-1 text-xs text-zinc-400">{data.estimate.minutes_source === 'manual' ? 'Minutes entered by you; hypothetical, not a forecast of playing time.' : 'Minutes based on earlier preseason appearances, not confirmed playing time.'} Rate sample: {data.estimate.history_games} prior-season games.</p>
        </div> : <p className="mt-3 text-sm text-amber-200">No automatic estimate is available. A first preseason appearance has no earlier preseason minutes; no minutes or rebounds are invented. A usable prior-season rate is also required.</p>}
        <form className="mt-4" onSubmit={event => {
          event.preventDefault();
          const minutes = minutesText.trim() === '' ? undefined : Number(minutesText);
          if (minutes !== undefined && (!Number.isFinite(minutes) || minutes < 0 || minutes > 48)) {
            setMinutesError('Enter minutes from 0 to 48, or leave blank to use earlier preseason minutes.');
            return;
          }
          setMinutesError(null);
          setRequest(current => ({ minutes, revision: current.revision + 1 }));
        }}>
          <label htmlFor="preseason-minutes" className="block text-xs text-zinc-300">Optional minutes assumption (0–48)</label>
          <div className="mt-2 flex flex-wrap items-center gap-2"><input id="preseason-minutes" type="number" min="0" max="48" step="0.1" value={minutesText} onChange={event => setMinutesText(event.target.value)} placeholder="No manual assumption" className="w-52 rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100" /><button type="submit" className={buttonClass}>Update scenario</button></div>
          <p className="mt-2 text-xs text-zinc-500">Leave blank to use earlier preseason minutes, if available.</p>
          {minutesError && <p className="mt-2 text-xs text-red-300" role="alert">{minutesError}</p>}
        </form>
      </div>
      <WarningList warnings={data.limitations} />
      <button type="button" className={`${buttonClass} mt-4`} onClick={() => setRequest(current => ({ ...current, revision: current.revision + 1 }))}>Retry player history</button>
    </> : null}
  </section>;
}

export function PreseasonAnalysis({ date, home, away }: { date: string; home: string; away: string }) {
  const [roster, setRoster] = useState<PreseasonRoster | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<{ team: string; player: { player_id: number; name: string } } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      setError(null);
      setRoster(null);
      setSelected(null);
      try {
        const response = await fetchPreseasonRoster({ date, home, away }, controller.signal);
        if (!controller.signal.aborted) setRoster(response);
      } catch (failure: unknown) {
        if (controller.signal.aborted || (failure instanceof ApiRequestError && failure.kind === 'aborted')) return;
        setError(failure instanceof Error ? failure.message : 'The preseason roster could not be loaded.');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, [date, home, away, retry]);

  return <div>
    <div className="rounded border border-amber-800 bg-amber-950/10 p-4 text-sm text-amber-200"><strong>Preseason research · analysis only.</strong> Select a player to inspect real history and an optional minutes scenario. The regular-season betting model is not validated for preseason; no betting recommendations are generated. Rosters do not confirm that a player is healthy or will play.</div>
    <PreseasonMarkets date={date} home={home} away={away} />
    {loading ? <p className="mt-4 flex items-center gap-2 text-sm text-zinc-400" role="status"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading team rosters…</p> : error ? <div className="mt-4 rounded border border-red-900 bg-red-950/20 p-4 text-red-300" role="alert"><p>{error}</p><button type="button" className={`${buttonClass} mt-3`} onClick={() => setRetry(current => current + 1)}>Retry rosters</button></div> : roster ? <>
      <div className="mt-4 grid gap-4 md:grid-cols-2">{roster.teams.map(entry => <section key={entry.team} className="rounded-lg border border-zinc-800 p-4">
        <h3 className="font-semibold text-zinc-100">{entry.team} players</h3>
        {entry.source && <p className="mt-1 text-xs text-zinc-500">Roster source: {entry.source}</p>}
        {entry.error && <p className="mt-2 text-sm text-red-300" role="status">{entry.error}</p>}
        {entry.players.length > 0 ? <div className="mt-3 flex flex-wrap gap-2">{entry.players.map(player => <button type="button" key={player.player_id} aria-pressed={selected?.team === entry.team && selected.player.player_id === player.player_id} onClick={() => setSelected({ team: entry.team, player })} className={`${buttonClass} ${selected?.team === entry.team && selected.player.player_id === player.player_id ? 'border-emerald-500 bg-emerald-950/50 text-emerald-300' : ''}`}>{player.name}</button>)}</div> : <p className="mt-3 text-sm text-zinc-400">No identifiable players available for this team.</p>}
        {entry.unmatched_count > 0 && <p className="mt-3 text-xs text-amber-200">{entry.unmatched_count} roster players could not be matched to NBA history and are not shown.</p>}
        <WarningList warnings={entry.limitations} />
      </section>)}</div>
      <button type="button" className={`${buttonClass} mt-3`} onClick={() => setRetry(current => current + 1)}>Refresh rosters</button>
      {selected ? <PlayerHistory key={`${date}:${selected.team}:${selected.player.player_id}`} player={selected.player} team={selected.team} opponent={selected.team === home ? away : home} date={date} /> : <p className="mt-5 text-sm text-zinc-400">Select one player above. History is loaded on demand, so you don’t have to wait for every player.</p>}
    </> : null}
  </div>;
}
