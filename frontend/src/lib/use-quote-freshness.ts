import { useEffect, useState } from 'react';
import { quoteFreshness, type Quote } from './dashboard';

// One local expiry timer, never a provider refresh or background polling loop.
export function useQuoteFreshness(quote?: Quote) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const sync = window.setTimeout(() => setNow(Date.now()), 0);
    const remaining = quote && quoteFreshness(quote) === 'fresh'
      ? Date.parse(quote.updated_at!) + 300_001 - Date.now() : null;
    const timer = remaining === null ? null : window.setTimeout(() => setNow(Date.now()), Math.max(1, remaining));
    return () => { window.clearTimeout(sync); if (timer !== null) window.clearTimeout(timer); };
  }, [quote]);
  return quote ? quoteFreshness(quote, now) : 'unknown';
}
