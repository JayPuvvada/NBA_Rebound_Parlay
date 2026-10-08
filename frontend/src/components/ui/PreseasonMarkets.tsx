import { useEffect, useState } from 'react';
import { ApiRequestError } from '@/lib/api';
import { fetchPreseasonMarkets } from '@/lib/preseason';
import type { PreseasonMarkets as Markets } from '@/lib/preseason';
import { formatAmericanOdds, formatTimestamp } from '@/lib/format';

export function PreseasonMarkets({ date, home, away }: { date: string; home: string; away: string }) {
  const [book, setBook] = useState('fanduel');
  const [data, setData] = useState<Markets | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true); setData(null); setError(null);
      try {
        const response = await fetchPreseasonMarkets({ date, home, away, book }, controller.signal);
        if (!controller.signal.aborted) setData(response);
      } catch (failure: unknown) {
        if (controller.signal.aborted || (failure instanceof ApiRequestError && failure.kind === 'aborted')) return;
        setError(failure instanceof Error ? failure.message : 'Sportsbook prices could not be loaded.');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, [date, home, away, book, revision]);
  return <section className="mt-4 rounded-lg border border-zinc-800 p-4" aria-label="Available sportsbook prices">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h3 className="font-semibold text-zinc-100">Sportsbook rebound lines</h3>
      <label className="text-sm text-zinc-400">Sportsbook <select aria-label="Preseason sportsbook" value={book} onChange={event => setBook(event.target.value)} className="ml-2 rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100">
        <option value="fanduel">FanDuel</option><option value="draftkings">DraftKings</option><option value="betmgm">BetMGM</option>
      </select></label>
    </div>
    {loading ? <p className="mt-3 text-sm text-zinc-400" role="status">Checking sportsbook coverage…</p> : error ? <p className="mt-3 text-sm text-amber-200" role="alert">{error}</p> : data ? <>
      <p className="mt-3 text-sm text-zinc-400" role="status">{data.message}</p>
      {data.game_spreads?.home != null && <p className="mt-2 text-sm text-zinc-300">Game spread from the feed: {home} {data.game_spreads.home > 0 ? '+' : ''}{data.game_spreads.home}{data.game_spreads.away != null && <> · {away} {data.game_spreads.away > 0 ? '+' : ''}{data.game_spreads.away}</>}</p>}
      {data.markets.length > 0 && <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-sm">
        <thead className="text-zinc-500"><tr><th className="py-2">Player</th><th>Side / line</th><th>Price</th><th>Quote status</th></tr></thead>
        <tbody>{data.markets.flatMap(market => market.quotes.map(quote => <tr key={`${market.player}:${quote.side}`} className="border-t border-zinc-800">
          <td className="py-2 pr-3 text-zinc-100">{market.player}</td><td className="pr-3">{quote.side} {quote.line}</td><td className="pr-3">{formatAmericanOdds(quote.odds)}</td>
          <td className="text-xs text-zinc-400">{quote.fresh ? 'Recent provider quote' : 'Stale or unverified timestamp'}{quote.updated_at && <span className="block">{formatTimestamp(quote.updated_at)}</span>}</td>
        </tr>))}</tbody>
      </table></div>}
    </> : null}
    <button type="button" disabled={loading} onClick={() => setRevision(value => value + 1)} className="mt-3 rounded border border-zinc-700 px-3 py-2 text-xs text-zinc-300 hover:border-emerald-500 disabled:opacity-50">Refresh prices</button>
  </section>;
}
