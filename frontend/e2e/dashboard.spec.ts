import { test, expect, type Page } from '@playwright/test';

const date = '2026-10-04';
const quote = { market: 'player_rebounds', selection: 'OVER', player: 'Stephen Curry', team: 'GSW', line: 4.5, odds: -110, book: 'fanduel', updated_at: '2026-10-04T18:00:00Z', fetched_at: '2026-10-04T18:01:00Z', freshness: 'fresh', event_id: 'event-1', source: 'The Odds API', sport: 'basketball_nba_preseason' };

async function fixtures(page: Page) {
  await page.route('**/games?*', route => route.fulfill({ json: { date, games: [{ id: '1', date, home: 'LAC', away: 'GSW', status: 1, status_text: 'Scheduled', game_time: '7:00 PM', is_preseason: true }] } }));
  await page.route('**/markets?*', route => route.fulfill({ json: { status: 'available', date, game: { home: 'LAC', away: 'GSW' }, sport: quote.sport, quotes: [quote, { ...quote, selection: 'UNDER', odds: -115 }], coverage: { fanduel: { player_rebounds: 'available' } } } }));
  await page.route('**/player-history?*', route => route.fulfill({ json: { player: quote.player, date, message: 'Observed history, not a forecast.', histories: [{ kind: 'prior_season', season: '2025-26', status: 'available', games: 10, source: 'Fixture NBA Stats', minutes_per_game: 30, rebounds_per_game: 5, date_range: { start: '2026-01-01', end: '2026-01-10' }, last_5: { rebounds: 5, minutes: 30 }, last_10: { rebounds: 5, minutes: 30 }, recent_games: [{ date: '2026-01-10', minutes: 30, rebounds: 5 }], observed_above_line: { line: 4.5, above: 7, below: 3, push: 0, games: 10 } }] } }));
  await page.route('**/generate-picks', async route => {
    const minutes = route.request().postDataJSON().minutes;
    const ready = minutes && Object.keys(minutes).length > 0;
    await route.fulfill({ json: { status: 'complete', date, game: { home: 'LAC', away: 'GSW' }, generated_at: '2026-10-04T18:02:00Z', coverage: { total: 1, completed: 1, incomplete: [] }, assessments: [{ player: quote.player, player_id: 201939, team: 'GSW', result_kind: ready ? 'experimental_candidate' : 'needs_input', profile: 'preseason', model_version: 'scenario-v1', projection: ready ? 5.2 : null, minutes: { value: ready ? 25 : null, source: 'manual' }, quote: ready ? quote : null, actionable: false, candidate_direction: ready ? 'OVER' : null, reason_code: 'minutes_required', limitations: ['Availability unknown; minutes are an assumption.'] }] } });
  });
}

test('advanced analysis explains estimates visually without treating scenarios as forecasts', async ({ page }) => {
  await fixtures(page);
  await page.route('**/generate-picks', route => route.fulfill({json:{status:'complete',date,game:{home:'LAC',away:'GSW'},generated_at:'2026-10-04T18:02:00Z',coverage:{total:1,completed:1,incomplete:[]},assessments:[{
    player:quote.player,team:'GSW',result_kind:'no_pick',profile:'preseason',projection:5.2,
    minutes:{value:24,source:'manual'},quote,actionable:false,reason_code:'quote_not_provider_verified',limitations:[],
    assumptions:{scenarios:[{name:'low',minutes:18,weight:.25},{name:'base',minutes:24,weight:.5},{name:'high',minutes:30,weight:.25}]},
    analysis:{over_probability:.6,under_probability:.4,push_probability:0,edge:.076,ev_roi:.145}
  }]}}));
  await page.goto(`/#edge?date=${date}`);
  await page.getByRole('button',{name:/Generate rebound picks/}).click();
  await page.getByText('Advanced analysis',{exact:true}).click();
  await expect(page.getByRole('img',{name:/Estimated rebounds 5.2 versus line 4.5/})).toBeVisible();
  await expect(page.getByText('60.0%',{exact:true})).toBeVisible();
  await expect(page.getByText('24 min',{exact:true})).toBeVisible();
  await expect(page.getByText(/not calibrated forecast probabilities/)).toBeVisible();
  await page.getByText('Exact price calculations',{exact:true}).click();
  await expect(page.getByText(/7.6 percentage points/)).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath('analysis-visuals.png'),fullPage:true});
});

test('preseason empty coverage is distinct from a provider outage', async ({ page }) => {
  await fixtures(page);
  let unavailable = false;
  await page.route('**/markets?*', route => route.fulfill({ json: {
    status: unavailable ? 'provider_unavailable' : 'empty', date,
    game: {home:'LAC',away:'GSW'}, sport:quote.sport, quotes:[],
    coverage:{fanduel:{player_rebounds:'book_missing'}}
  } }));
  await page.goto(`/#edge?date=${date}`);
  await expect(page.getByText(/No preseason rebound lines were returned/)).toBeVisible();
  await expect(page.getByRole('button',{name:/Generate rebound picks/})).toBeDisabled();
  unavailable = true;
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await expect(page.getByText('The sportsbook provider is unavailable.',{exact:true})).toBeVisible();
  await expect(page.getByText(/No preseason rebound lines were returned/)).toHaveCount(0);
});

test('fresh quote labels expire locally without another market request', async ({ page }) => {
  await fixtures(page);
  let requests = 0;
  const start = Date.parse(quote.updated_at);
  await page.clock.install({time:start+240_000});
  await page.route('**/markets?*',route => {
    requests++;
    return route.fulfill({json:{status:'available',date,game:{home:'LAC',away:'GSW'},sport:quote.sport,quotes:[quote],coverage:{fanduel:{player_rebounds:'available'}}}});
  });
  await page.goto(`/#edge?date=${date}`);
  await expect(page.getByText('Recent quote',{exact:true})).toBeVisible();
  await page.clock.fastForward(61_000);
  await expect(page.getByText('Stale quote',{exact:true})).toBeVisible();
  expect(requests).toBe(1);
});

test('initial schedule selects earliest scheduled tipoff and preserves an explicit matchup', async ({ page }) => {
  await fixtures(page);
  const late = {id:'late',date,home:'DEN',away:'UTA',status:1,status_text:'Scheduled',start_time:'2026-10-05T03:00:00Z'};
  const early = {id:'early',date,home:'LAC',away:'GSW',status:1,status_text:'Scheduled',start_time:'2026-10-04T19:00:00-04:00'};
  await page.route('**/games?*',route => route.fulfill({json:{date,games:[late,early]}}));
  await page.goto(`/#edge?date=${date}`);
  await expect(page.getByRole('button',{name:/GSW at LAC/})).toHaveAttribute('aria-pressed','true');
  await page.goto(`/#edge?date=${date}&home=DEN&away=UTA`);
  await expect(page.getByRole('button',{name:/UTA at DEN/})).toHaveAttribute('aria-pressed','true');
});

test('primary controls have touch-sized targets and honor reduced motion', async ({ page }) => {
  await fixtures(page);
  await page.emulateMedia({ reducedMotion:'reduce' });
  await page.goto(`/#edge?date=${date}`);
  await expect(page.getByText('OVER 4.5',{exact:true})).toBeVisible();
  const dashboardStyle = await page.locator('.nba-app').evaluate(element => ({ background: getComputedStyle(element).backgroundColor, color: getComputedStyle(element).color }));
  expect(dashboardStyle.background).toBe('rgb(14, 17, 23)');
  expect(dashboardStyle.color).toBe('rgb(243, 244, 246)');
  await page.screenshot({ path: test.info().outputPath('dashboard-tailwind4.png'), fullPage: true });
  const smallControls = await page.locator('button:visible,input:visible,select:visible').evaluateAll(elements => elements.filter(element => {
    const bounds = element.getBoundingClientRect();
    return bounds.height < 44 || bounds.width < 44;
  }).map(element => element.getAttribute('aria-label') || element.textContent));
  expect(smallControls).toEqual([]);
  const animation = await page.getByRole('button',{name:'Refresh',exact:true}).evaluate(element => {
    element.classList.add('animate-spin');
    return getComputedStyle(element).animationName;
  });
  expect(animation).toBe('none');
  await page.getByRole('link',{name:'Skip to content',exact:true}).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();
});

test('book switching reuses rebound quotes and filtered emptiness has a reset', async ({ page }) => {
  await fixtures(page);
  await page.route('**/markets?*', route => route.fulfill({ json: { status: 'available', date, game: { home: 'LAC', away: 'GSW' }, sport: quote.sport, quotes: [{ ...quote, book: 'draftkings' }], coverage: { fanduel: { player_rebounds: 'book_missing' }, draftkings: { player_rebounds: 'available' } } } }));
  await page.goto(`/#edge?date=${date}`);
  await expect(page.getByText('This book has not returned quotes for this game.')).toBeVisible();
  await expect(page.getByText('No selections match your filters.')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Compare 3 books', exact: true })).toHaveCount(0);
  await page.getByRole('combobox', { name: /Sportsbook/ }).selectOption('draftkings');
  await expect(page.getByText('OVER 4.5', { exact: true })).toBeVisible();
  await expect(page.getByText('This book has not returned quotes for this game.')).toHaveCount(0);
  await page.getByLabel('Search players or teams').fill('nobody');
  await expect(page.getByText('No selections match your filters.')).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
  await expect(page.getByText('OVER 4.5', { exact: true })).toBeVisible();
});

test('rebound-only page ignores old game-market links and explains unavailable generation', async ({ page }) => {
  await fixtures(page);
  const groups: string[] = [];
  await page.route('**/markets?*',route => {
    groups.push(new URL(route.request().url()).searchParams.get('group') || '');
    return route.fulfill({json:{status:'empty',date,game:{home:'LAC',away:'GSW'},sport:quote.sport,quotes:[],coverage:{fanduel:{player_rebounds:'book_missing'}}}});
  });
  await page.goto(`/#edge?date=${date}&market=spreads`);
  await expect(page.getByRole('heading',{name:'Rebound lines',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Generate rebound picks',exact:true})).toBeDisabled();
  await expect(page.getByText(/Generation needs offered rebound lines/)).toBeVisible();
  await expect(page.getByRole('button',{name:'Open player research',exact:true})).toBeVisible();
  for (const name of ['Spreads','Moneyline','Totals','Compare 3 books']) await expect(page.getByRole('button',{name,exact:true})).toHaveCount(0);
  expect(groups).toEqual(['rebounds']);
  await page.getByRole('button',{name:'Open player research',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Player Research',exact:true})).toBeVisible();
});

test('lines remain useful without projections; research preserves context', async ({ page }) => {
  await fixtures(page);
  await page.goto(`/#edge?date=${date}`);
  await expect(page.getByRole('heading', { name: 'Picks & Lines', exact: true })).toBeVisible();
  await expect(page.getByText('OVER 4.5', { exact: true })).toBeVisible();
  await expect(page.getByText('UNDER 4.5', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Research', exact: true }).first().click();
  await expect(page.getByText('Observed rebounds / game', { exact: true })).toBeVisible();
  await expect(page.getByText(/Observed frequency at 4.5/)).toBeVisible();
  await page.getByRole('button', { name: 'Back to picks', exact: true }).click();
  await expect(page.getByText('OVER 4.5', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test('successful HTTP history failures expose targeted retry without hiding partial samples', async ({ page }) => {
  await fixtures(page);
  let requests = 0;
  await page.route('**/player-history?*',route => {
    requests++;
    const available = {kind:'current_season',season:'2025-26',status:'available',games:8,rebounds_per_game:5,minutes_per_game:30};
    return route.fulfill({json:{player:quote.player,date,message:'Observed history',status:requests===1?'partial':requests===2?'unavailable':'complete',reason_code:requests===2?'player_identity_unverified':undefined,histories:requests===2?[]:[available]}});
  });
  await page.goto(`/#edge?date=${date}`);
  await page.getByRole('button',{name:'Research',exact:true}).first().click();
  await expect(page.getByText(/Some history sources could not be loaded/)).toBeVisible();
  await expect(page.getByText('Observed rebounds / game',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Retry history',exact:true}).click();
  await expect(page.getByText(/Player history could not be loaded/)).toBeVisible();
  await expect(page.getByText(/player identity could not be verified/)).toBeVisible();
  await page.getByRole('button',{name:'Retry history',exact:true}).click();
  await expect(page.getByText('Observed rebounds / game',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Retry history',exact:true})).toHaveCount(0);
});

test('history retry retains the edited line and competition', async ({ page }) => {
  await fixtures(page);
  const requests: URL[] = [];
  await page.route('**/player-history?*', async route => {
    requests.push(new URL(route.request().url()));
    if (requests.length === 2) { await route.fulfill({status:503,json:{error:'Temporary history failure'}}); return; }
    await route.fulfill({json:{player:quote.player,date,message:'History loaded',histories:[]}});
  });
  await page.goto(`/#edge?date=${date}`);
  await page.getByRole('button',{name:'Research',exact:true}).first().click();
  await expect(page.getByText('History loaded',{exact:true})).toBeVisible();
  await page.getByLabel('Compare line').fill('7.5');
  await page.getByRole('combobox',{name:/Competition/}).selectOption('regular');
  await page.getByRole('button',{name:'Load history',exact:true}).click();
  await expect(page.getByRole('button',{name:'Retry history',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Retry history',exact:true}).click();
  await expect(page.getByText('History loaded',{exact:true})).toBeVisible();
  expect(requests.at(-1)?.searchParams.get('line')).toBe('7.5');
  expect(requests.at(-1)?.searchParams.get('preseason')).toBe('false');
});

test('leaving research mid-request allows it to load again on return', async ({ page }) => {
  await fixtures(page);
  let attempts = 0;
  await page.route('**/player-history?*', async route => {
    attempts++;
    if (attempts === 1) { await new Promise(resolve => setTimeout(resolve, 1000)); await route.abort().catch(() => {}); return; }
    await route.fulfill({ json: { player: quote.player, date, message: 'Recovered history', histories: [] } });
  });
  await page.goto(`/#edge?date=${date}`);
  await page.getByRole('button', { name: 'Research', exact: true }).first().click();
  await expect(page.getByText('Loading observed player history…')).toBeVisible();
  await expect.poll(() => attempts).toBe(1);
  await page.getByRole('button', { name: 'Back to picks', exact: true }).click();
  await page.getByRole('tab', { name: 'Player Research', exact: true }).click();
  await expect(page.getByText('Recovered history', { exact: true })).toBeVisible();
  expect(attempts).toBe(2);
});

test('preseason asks for minutes and clearly labels the result', async ({ page }) => {
  await fixtures(page);
  await page.goto(`/#edge?date=${date}`);
  await page.getByRole('button', { name: 'Generate rebound picks', exact: true }).click();
  await expect(page.getByText('More information needed', { exact: true })).toBeVisible();
  await page.getByLabel('Minutes for Stephen Curry').fill('25');
  await page.getByRole('button', { name: 'Calculate', exact: true }).click();
  await expect(page.getByText('Experimental candidate', { exact: true })).toBeVisible();
  await expect(page.getByText('Scenario rebounds', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Save selection', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: 'Selection ready to save' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save reviewed selection' })).toBeDisabled();
});

test('retry remaining keeps unresolved players when the provider returns no replacements', async ({ page }) => {
  await fixtures(page);
  let attempts = 0;
  await page.route('**/generate-picks', route => {
    attempts++;
    return route.fulfill({json:{status:attempts === 1 ? 'partial' : 'no_quotes',date,game:{home:'LAC',away:'GSW'},generated_at:'2026-10-04T18:02:00Z',
      coverage: attempts === 1 ? {total:1,completed:0,incomplete:[quote.player]} : {total:0,completed:0,incomplete:[]},
      assessments:attempts === 1 ? [{player:quote.player,result_kind:'unavailable',projection:null,quote:null,actionable:false,limitations:[],reason_code:'deadline_exceeded'}] : []}});
  });
  await page.goto(`/#edge?date=${date}`);
  await page.getByRole('button',{name:'Generate rebound picks',exact:true}).click();
  const retry = page.getByRole('button',{name:'Retry remaining',exact:true});
  await expect(retry).toBeVisible();
  await retry.click();
  await expect.poll(() => attempts).toBe(2);
  await expect(retry).toBeVisible();
  await expect(page.getByText('Incomplete: Stephen Curry.',{exact:false})).toBeVisible();
});

test('failed refresh retains stale prices and keyboard navigation works', async ({ page }) => {
  await fixtures(page);
  await page.goto(`/#edge?date=${date}`);
  await expect(page.getByText('OVER 4.5', { exact: true })).toBeVisible();
  await page.route('**/markets?*', route => route.fulfill({ status: 503, json: { error: 'Provider temporarily unavailable.' } }));
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByText('Stale quote', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('OVER 4.5', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Picks & Lines' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Player Research' })).toBeFocused();
  await expect(page.getByRole('heading', { name: 'Player Research', exact: true })).toBeVisible();
});

test('regular-model result can be inspected without dropping the quoted selection', async ({ page }) => {
  await fixtures(page);
  await page.route('**/games?*', route => route.fulfill({ json: { date, games: [{ id: 'regular-1', date, home: 'LAC', away: 'GSW', status: 1, is_preseason: false }] } }));
  await page.route('**/generate-picks', route => route.fulfill({ json: { status: 'complete', date, game: { home: 'LAC', away: 'GSW' }, generated_at: '2026-10-04T18:02:00Z', coverage: { total: 1, completed: 1, incomplete: [] }, assessments: [{ player: quote.player, team: 'GSW', result_kind: 'model_pick', profile: 'full_regular', model_version: '2.0.0', projection: 5.2, minutes: { value: 32, source: 'primary_model' }, quote: { ...quote, sport: 'basketball_nba' }, actionable: true, limitations: ['Model estimates are not guarantees.'] }] } }));
  await page.goto(`/#edge?date=${date}`);
  await page.getByRole('button', { name: 'Generate rebound picks', exact: true }).click();
  await expect(page.getByText('Model pick', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Inspect player' }).click();
  await expect(page.getByText(/Selected quote/)).toBeVisible();
  await expect(page.getByText('Observed rebounds / game', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Back to picks' }).click();
  await expect(page.getByText('Model pick', { exact: true })).toBeVisible();
});

test('private-journal UI saves, signs back in, annotates and grades a snapshot', async ({ page }) => {
  // HTTP fixtures test the browser journey, not database privacy or real Auth.
  // SQL ownership/immutability and real local Auth acceptance are separate checks.
  await fixtures(page);
  const user = { id: '11111111-1111-4111-8111-111111111111', email: 'beta@example.test', aud: 'authenticated', role: 'authenticated', app_metadata: { provider: 'email' }, user_metadata: {}, created_at: new Date().toISOString() };
  const token = [Buffer.from('{}').toString('base64url'), Buffer.from(JSON.stringify({ sub: user.id, role: 'authenticated', exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url'), 'fixture'].join('.');
  const headers = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': 'GET,POST,PATCH,DELETE,OPTIONS' };
  let records: Record<string, unknown>[] = [];
  await page.route('**/auth/v1/**', route => {
    if (route.request().method() === 'OPTIONS' || route.request().url().includes('/logout')) return route.fulfill({ status: 204, headers });
    return route.fulfill({ headers, json: route.request().url().includes('/user') ? user : { access_token: token, refresh_token: 'fixture-refresh', expires_in: 3600, token_type: 'bearer', user } });
  });
  await page.route('**/rest/v1/app_pick_members*', route => route.fulfill({ headers, json: { user_id: user.id } }));
  await page.route('**/rest/v1/app_saved_picks*', route => {
    const method = route.request().method();
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers });
    if (method === 'POST') {
      const record = route.request().postDataJSON();
      records.push({ ...record, savedAt: new Date().toISOString(), result: 'Pending' });
    }
    if (method === 'PATCH') records = records.map(record => ({ ...record, ...route.request().postDataJSON() }));
    if (method === 'DELETE') records = [];
    return method === 'GET' ? route.fulfill({ headers, json: records }) : route.fulfill({ headers, status: 201, json: null });
  });
  const signIn = async () => {
    await page.getByLabel('Email', { exact: true }).fill(user.email);
    await page.getByLabel('Password', { exact: true }).fill('fixture-only-password');
    await page.locator('form').getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
  };
  await page.goto(`/#edge?date=${date}`);
  await page.getByRole('button', { name: 'Save Stephen Curry OVER 4.5 at FanDuel' }).click();
  await signIn();
  await page.getByRole('button', { name: 'Save reviewed selection' }).click();
  await expect(page.getByText(/1 saved pick/)).toBeVisible();
  expect(records).toHaveLength(1);
  expect(records[0].odds).toBe(-110);
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await page.reload();
  await signIn();
  await expect(page.getByText(/1 saved pick/)).toBeVisible();
  await page.getByLabel('Notes for Stephen Curry', { exact: true }).fill('Review the minutes assumption.');
  await page.getByRole('button', { name: 'Save notes' }).click();
  await page.getByLabel('Result for Stephen Curry', { exact: true }).selectOption('Void');
  await expect(page.getByLabel('Result for Stephen Curry', { exact: true })).toHaveValue('Void');
  // Wait for grading's reload before simulating a separate session's write.
  await expect(page.getByRole('button', { name: 'Refresh picks', exact: true })).toBeEnabled();
  expect(records[0].odds).toBe(-110);
  expect(records[0].notes).toBe('Review the minutes assumption.');
  records[0].notes = 'Updated in another session.';
  await page.getByRole('button', { name: 'Refresh picks', exact: true }).click();
  await expect(page.getByLabel('Notes for Stephen Curry', { exact: true })).toHaveValue('Updated in another session.');
  await page.getByLabel('Notes for Stephen Curry', { exact: true }).fill('Unsaved local draft');
  records[0].notes = 'Another remote change.';
  await page.getByRole('button', { name: 'Refresh picks', exact: true }).click();
  await expect(page.getByText(/Saved notes changed while you were editing/)).toBeVisible();
  await expect(page.getByLabel('Notes for Stephen Curry', { exact: true })).toHaveValue('Unsaved local draft');
  await page.getByRole('button', { name: 'Use saved notes', exact: true }).click();
  await expect(page.getByLabel('Notes for Stephen Curry', { exact: true })).toHaveValue('Another remote change.');
});

test('a late response from the previous game cannot replace the selected game', async ({ page }) => {
  await fixtures(page);
  await page.route('**/games?*', route => route.fulfill({ json: { date, games: [
    { id: 'one', date, home: 'LAC', away: 'GSW', status: 1, is_preseason: true },
    { id: 'two', date, home: 'DEN', away: 'UTA', status: 1, is_preseason: true },
  ] } }));
  let releaseFirst!: () => void;
  const first = new Promise<void>(resolve => { releaseFirst = resolve; });
  await page.route('**/markets?*', async route => {
    const oldGame = new URL(route.request().url()).searchParams.get('home') === 'LAC';
    if (oldGame) await first;
    try { await route.fulfill({ json: { status: 'available', date, game: oldGame ? { home: 'LAC', away: 'GSW' } : { home: 'DEN', away: 'UTA' }, sport: quote.sport, quotes: [{ ...quote, player: oldGame ? 'Stephen Curry' : 'Nikola Jokic', team: oldGame ? 'GSW' : 'DEN', event_id: oldGame ? 'one' : 'two' }], coverage: { fanduel: { player_rebounds: 'available' } } } }); } catch { /* cancelled old request */ }
  });
  const pendingOldRequest = page.waitForRequest(request => request.url().includes('/markets?') && request.url().includes('home=LAC'));
  await page.goto(`/#edge?date=${date}`);
  await pendingOldRequest;
  await page.getByRole('button', { name: /UTA at DEN/ }).click();
  await expect(page.getByRole('heading', { name: 'Nikola Jokic', exact: true })).toBeVisible();
  releaseFirst();
  await expect(page.getByRole('heading', { name: 'Stephen Curry', exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Nikola Jokic', exact: true })).toBeVisible();
});

test('research updates when the same player has a different quoted threshold', async ({ page }) => {
  await fixtures(page);
  await page.route('**/markets?*', route => route.fulfill({ json: { status: 'available', date, game: { home: 'LAC', away: 'GSW' }, sport: quote.sport, quotes: [quote, { ...quote, selection: 'UNDER', line: 5.5, odds: -115 }], coverage: { fanduel: { player_rebounds: 'available' } } } }));
  await page.goto(`/#edge?date=${date}`);
  await page.getByRole('button', { name: 'Research', exact: true }).first().click();
  await expect(page.getByLabel('Compare line')).toHaveValue('4.5');
  await page.getByRole('button', { name: 'Back to picks' }).click();
  await page.getByRole('button', { name: 'Research', exact: true }).nth(1).click();
  await expect(page.getByLabel('Compare line')).toHaveValue('5.5');
});
