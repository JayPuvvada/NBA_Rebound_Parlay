const key = 'nba-lookup-draft-v1';
const fields = ['player', 'opponent', 'date', 'spread', 'line', 'overOdds', 'underOdds', 'bookmaker', 'matchup', 'venue'] as const;
export type LookupDraft = Partial<Record<typeof fields[number], string>>;

export function readLookupDraft(): LookupDraft {
  try {
    const raw: unknown = JSON.parse(sessionStorage.getItem(key) || '{}');
    if (!raw || typeof raw !== 'object') return {};
    return Object.fromEntries(fields.flatMap(field => {
      const value = (raw as Record<string, unknown>)[field];
      return typeof value === 'string' && value.length <= 200 ? [[field, value]] : [];
    }));
  } catch { return {}; }
}

export function writeLookupDraft(draft: LookupDraft): void {
  try { sessionStorage.setItem(key, JSON.stringify(draft)); } catch { /* Storage may be disabled. */ }
}
