import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const offline = process.argv.includes('--offline');
const root = fileURLToPath(new URL(offline ? '../dist-offline' : '../dist-demo', import.meta.url));
const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date());
const now = new Date().toISOString();
const profit = odds => odds < 0 ? 100 / Math.abs(odds) : odds / 100;
function sample(player, team, projection, line, win, direction, eligible = true) {
  const overOdds = -110, underOdds = -115;
  const side = direction ?? 'UNDER';
  const underWin = 1 - win;
  const overEV = win * profit(overOdds) - underWin;
  const underEV = underWin * profit(underOdds) - win;
  const sources = eligible ? { status: 'primary', source: 'demo' } : { status: 'degraded', source: 'demo-fallback' };
  const limitations = eligible ? [] : ['Sample fallback result: player data and game status are not verified for a live pick.'];
  return {
    player, team, opponent: team === 'DEN' ? 'LAL' : 'DEN', projection, date: today,
    home_game: team === 'DEN', generated_at: now, prediction_eligible: eligible,
    metadata: { prediction_eligible: eligible, projection_inputs: sources },
    limitations, components: { 'Proj Minutes': 34.5, Blowout: 'None' },
    injuries: { team_list: ['Sample teammate — Questionable (test data)'], opp_list: [] },
    data_freshness: { prediction_eligible: eligible, injuries: { status: eligible ? 'available' : 'degraded', stale: !eligible, fetched_at: now } },
    trend: Array.from({ length: 10 }, (_, i) => ({ date: '2026-04-' + (10 + i), opponent: ['LAL','BOS','SAS'][i % 3], rebounds: Math.max(0, Math.round(projection) + [-2,1,-1,-4,3,0,2,-2,1,-1][i]) })),
    line, direction: eligible ? direction : null, actionable: eligible && direction !== null,
    evaluated_side: side, american_odds: side === 'OVER' ? overOdds : underOdds,
    confidence: side === 'OVER' ? win : underWin,
    over_probability: win, under_probability: underWin, push_probability: 0,
    ev_roi: side === 'OVER' ? overEV : underEV,
    tier: eligible ? direction ? 'PLAY' : 'AVOID' : 'HISTORICAL_CONTEXT_INCOMPLETE',
    bookmaker: 'Sample sportsbook', odds_updated_at: now,
    prediction_interval_68: [Math.max(0, Math.round(projection) - 5), Math.round(projection) + 5],
    variance: { high_variance: !eligible },
    side_evaluations: {
      over: { direction: 'OVER', confidence: win, american_odds: overOdds, ev_roi: overEV },
      under: { direction: 'UNDER', confidence: underWin, american_odds: underOdds, ev_roi: underEV },
    },
  };
}
const rows = [
  sample('Nikola Jokic', 'DEN', 13.3, 12.5, 0.60, 'OVER'),
  sample('Austin Reaves', 'LAL', 4.1, 4.5, 0.47, null),
  sample('Sample Player (fallback)', 'DEN', 7.2, 7.5, 0.45, null, false),
];
const banner = '<div style="padding:14px 20px;background:#422006;color:#fef3c7;font:14px/1.5 system-ui;border-bottom:1px solid #a16207" role="status"><strong>DEMO — synthetic NBA data, not real picks.</strong> No NBA/odds calls. ' + (offline ? 'Offline test login: jay / demo123. Saves stay in this browser only.' : 'Sign in with your Supabase email/password. Saved sample picks go to your real private account.') + ' Player Lookup is prefilled and returns a fixed example, not a new calculation.</div>';
const setup = `
const filled = new WeakSet();
let selectedGame=false, openedPlayer=false;
const timer=setInterval(()=>{
  const input=document.querySelector('#lookup-player');
  if(input && !filled.has(input)){
    filled.add(input);
    const set=(id,value)=>{const el=document.querySelector(id);Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));};
    set('#lookup-player','Nikola Jokic');set('#lookup-opponent','LAL');set('#lookup-line','12.5');set('#lookup-over-odds','-110');set('#lookup-under-odds','-115');set('#lookup-spread','-5.5');
  }
  if(!selectedGame){const game=[...document.querySelectorAll('button')].find(b=>b.textContent==='LAL @ DEN');if(game){game.click();selectedGame=true;}}
  if(selectedGame&&!openedPlayer){const player=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Nikola Jokic'));if(player){player.click();openedPlayer=true;}}
},200);
window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
`;
const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://127.0.0.1');
    if (['/games','/cheat-sheet','/predict'].includes(url.pathname)) {
      res.setHeader('Content-Type','application/json');
      res.setHeader('Cache-Control','no-store');
      if(url.pathname === '/games') return res.end(JSON.stringify({date: today, games:[{id:'demo-den-lal',home:'DEN',away:'LAL',date:today,status:1}]}));
      if(url.pathname === '/cheat-sheet') return res.end(JSON.stringify({projections: rows, generated_at: now, bookmaker:'Sample sportsbook', warnings:['All players, game context, odds and results in this preview are synthetic fixtures.']})); 
      let body = '';
      for await (const chunk of req) {body += chunk;if(body.length > 65536){res.writeHead(413);return res.end(JSON.stringify({error:'Request too large'}));}}
      const input = JSON.parse(body || '{}');
      const sampleRow = rows[0];
      return res.end(JSON.stringify({
        ...sampleRow, analysis:sampleRow,
        limitations:['Fixed demo example — changing form inputs does not run the real model.'],
        recording: input.record_prediction ? {requested:true,recorded:false,prediction_id:null,reason:'Performance-ledger recording is disabled in the demo; account snapshots are separate.'} : undefined,
      }));
    }
    if(url.pathname === '/health'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({status:'ok',mode:'synthetic-demo'}));}
    const target = path.resolve(root, '.' + (url.pathname === '/' ? '/index.html' : url.pathname));
    if(!target.startsWith(root + path.sep) || !fs.existsSync(target) || !fs.statSync(target).isFile()){res.writeHead(404);return res.end('Not found');}
    res.setHeader('Content-Type', {'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'}[path.extname(target)] || 'application/octet-stream');
    const content = fs.readFileSync(target);
    res.end(path.extname(target)==='.html' ? content.toString().replace('<body>','<body>'+banner).replace('</body>','<script type="module">'+setup+'</script></body>') : content);
  } catch {res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({error:'Invalid demo request'}));}
});
server.listen(4181, '127.0.0.1', () => console.log('Demo ready: http://127.0.0.1:4181/#picks — synthetic data only'));
