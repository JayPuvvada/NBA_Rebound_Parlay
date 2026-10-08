import type { Assessment } from '@/lib/dashboard';

function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function AnalysisVisuals({ row }: { row: Assessment }) {
  const analysis = row.analysis || {};
  const scenario = row.profile !== 'full_regular';
  const line = row.quote?.line;
  const estimate = number(row.projection);
  const maximum = Math.max(10, (estimate || 0) * 1.25, (line || 0) * 1.25);
  const sides = [ ['Over', number(analysis.over_probability)], ['Under', number(analysis.under_probability)], ['Push', number(analysis.push_probability)] ] as const;
  const scenarios = Array.isArray(row.assumptions?.scenarios) ? row.assumptions.scenarios : [];
  return <div className="analysis-visuals">
    {estimate !== null && line != null && <section aria-label="Estimate compared with rebound line">
      <h4>Where the estimate sits</h4>
      <svg viewBox="0 0 320 78" role="img" aria-label={`Estimated rebounds ${estimate.toFixed(1)} versus line ${line}. Not a prediction interval.`}>
        <line x1="16" y1="36" x2="304" y2="36" stroke="#2B3443" strokeWidth="8" strokeLinecap="round" />
        <line x1={16 + line / maximum * 288} x2={16 + line / maximum * 288} y1="22" y2="50" stroke="#F2C46D" strokeWidth="3" />
        <circle cx={16 + estimate / maximum * 288} cy="36" r="7" fill="#72DFC1" />
        <text x="16" y="70" fill="#A5AEBC" fontSize="12">0 rebounds</text>
        <text x="304" y="70" textAnchor="end" fill="#A5AEBC" fontSize="12">{maximum.toFixed(0)}</text>
      </svg>
      <p><span style={{color:'#72DFC1'}}>● Estimate {estimate.toFixed(1)}</span> · <span style={{color:'#F2C46D'}}>│ Line {line}</span></p>
      <p className="nba-meta">The estimate is {Math.abs(estimate-line).toFixed(1)} rebounds {estimate >= line ? 'above' : 'below'} the line. That alone does not establish a good price or an eligible pick.</p>
    </section>}
    {sides.some(([, value]) => value !== null) && <section aria-label="Estimated outcome probabilities">
      <h4>{scenario ? 'What the minutes scenario implies' : 'Estimated outcomes'}</h4>
      {sides.map(([label, probability]) => probability !== null && probability >= 0 && probability <= 1 && <div key={label} className="analysis-bar-row">
        <div><span>{label}{line != null ? ` ${line}` : ''}</span><strong>{(probability*100).toFixed(1)}%</strong></div>
        <div className="analysis-bar" aria-hidden="true"><span style={{width:`${probability*100}%`,background:label === 'Over' ? '#72DFC1' : label === 'Under' ? '#9CB7E8' : '#F2C46D'}} /></div>
      </div>)}
      <p className="nba-meta">{scenario ? 'Conditional scenario estimates—not calibrated forecast probabilities.' : 'Model estimates—not guarantees.'} Push means finishing exactly on an integer line; half-point lines cannot push.</p>
    </section>}
    {!!scenarios.length && <section aria-label="Minutes scenario assumptions"><h4>What changes if minutes change?</h4><div className="analysis-scenarios">{scenarios.map((raw, index) => {
      if (!raw || typeof raw !== 'object') return null;
      const item = raw as Record<string, unknown>;
      const minutes = number(item.minutes), weight = number(item.weight);
      if (minutes === null || weight === null) return null;
      return <div key={index}><span>{String(item.name || 'Scenario')}</span><strong>{minutes.toFixed(0)} min</strong><small>{(weight*100).toFixed(0)}% assumption weight</small></div>;
    })}</div><p className="nba-meta">These weights are engineering assumptions, not the chance of playing these minutes.</p></section>}
    <details><summary>Exact price calculations</summary>{['edge','ev_roi'].map(key => {
      const value = number(analysis[key]);
      return value !== null && <p key={key}>{key === 'edge' ? 'Estimated advantage over price break-even' : 'Hypothetical expected return'}: {(value*100).toFixed(1)}{key === 'edge' ? ' percentage points' : '% per unit'}</p>;
    })}<p className="nba-meta">Calculated from the selected side’s price and assumptions—not verified profit or a staking recommendation.</p></details>
  </div>;
}
