"""Read-only sportsbook board. No rosters or statistical projections required."""
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import quote

from nba_api.stats.static import teams

from src.data_loader import DataUnavailableError, ProviderHTTPError
from src.odds_budget import OddsStore, OddsBudgetError, OddsBusyError

BOOKS = ('fanduel', 'draftkings', 'betmgm')
MARKETS = ('player_rebounds', 'spreads', 'h2h', 'totals')
SPORTS = ('basketball_nba', 'basketball_nba_preseason')


def freshness(timestamp, now=None):
    if not isinstance(timestamp, str):
        return 'unknown'
    try:
        updated = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if updated.tzinfo is None:
            return 'unknown'
        age = ((now or datetime.now(timezone.utc)) - updated).total_seconds()
        return 'fresh' if 0 <= age <= 300 else 'stale'
    except ValueError:
        return 'unknown'


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def normalize_board(payload, event, requested_books, home, away):
    if not isinstance(payload, dict) or not isinstance(payload.get('bookmakers'), list):
        raise DataUnavailableError('Invalid sportsbook response')
    if payload.get('id') != event['id']:
        raise DataUnavailableError('Sportsbook event identity changed')
    entries = []
    coverage = {key: {market: 'book_missing' for market in MARKETS} for key in requested_books}
    for book in payload['bookmakers']:
        if not isinstance(book, dict) or book.get('key') not in requested_books:
            continue
        key = book['key']
        coverage[key] = {market: 'market_missing' for market in MARKETS}
        if not isinstance(book.get('markets'), list):
            raise DataUnavailableError('Invalid sportsbook markets')
        for market in book['markets']:
            if not isinstance(market, dict) or market.get('key') not in MARKETS:
                continue
            kind = market['key']
            if not isinstance(market.get('outcomes'), list):
                raise DataUnavailableError('Invalid sportsbook outcomes')
            for outcome in market['outcomes']:
                if not isinstance(outcome, dict):
                    continue
                price, point = outcome.get('price'), outcome.get('point')
                if not finite(price) or int(price) != price or abs(price) < 100 or abs(price) > 100000:
                    continue
                if kind != 'h2h' and (not finite(point) or abs(point) > 1000):
                    continue
                name, player = outcome.get('name'), outcome.get('description')
                team = None
                if kind in ('spreads', 'h2h'):
                    if name not in (event['home_team'], event['away_team']):
                        continue
                    team = home if name == event['home_team'] else away
                    selection = team
                else:
                    if name not in ('Over', 'Under') or (kind == 'player_rebounds' and (not isinstance(player, str) or not player.strip())):
                        continue
                    if point < 0:
                        continue
                    selection = name.upper()
                updated = market.get('last_update') or book.get('last_update')
                updated = updated if isinstance(updated, str) else None
                entries.append({'market': kind, 'selection': selection, 'player': player.strip() if kind == 'player_rebounds' else None,
                                'team': team, 'line': point if kind != 'h2h' else None, 'odds': int(price),
                                'book': key, 'book_title': book.get('title') or key,
                                'updated_at': updated, 'freshness': freshness(updated)})
                coverage[key][kind] = 'available'
    # Identical records must not render twice or create duplicate saved selections.
    unique = {(item['market'], item['player'], item['selection'], item['line'], item['book']): item for item in entries}
    return list(unique.values()), coverage


def fetch_board(loader, api_key, home, away, date, sport, books, *, group='rebounds', refresh=False):
    if sport not in SPORTS or not books or any(book not in BOOKS for book in books) or group not in ('rebounds', 'game'):
        raise ValueError('Unsupported sportsbook or NBA league')
    team_names = {team['abbreviation']: team['full_name'] for team in teams.get_teams()}
    if home not in team_names or away not in team_names or home == away:
        raise ValueError('Choose two different NBA teams')
    result = {'date': date, 'game': {'home': home, 'away': away}, 'sport': sport,
              'source': 'the-odds-api', 'quotes': [], 'coverage': {}, 'status': 'unconfigured',
              'fetched_at': datetime.now(timezone.utc).isoformat(), 'event_id': None,
              'group': group}
    if not api_key:
        return result
    store = OddsStore(api_key=api_key)
    cache_key = f'board:{sport}:{date}:{home}:{away}:{group}'
    old = store.cached(cache_key, stale=True)

    def present(board, cached=False):
        value = {**board, 'cached': cached, 'budget': store.snapshot()}
        value.pop('cache_time', None)
        value['quotes'] = [{**item, 'freshness': freshness(item.get('updated_at'))}
                           for item in board.get('quotes', [])]
        return value

    cached = store.cached(cache_key)
    # Refresh clicks within a minute coalesce, including empty provider results.
    if cached and (not refresh or store.clock() - cached.get('cache_time', 0) < 60):
        return present(cached, True)

    def matches(event):
        if not isinstance(event, dict) or event.get('home_team') != team_names[home] or event.get('away_team') != team_names[away]:
            return False
        try:
            start = datetime.fromisoformat(event['commence_time'].replace('Z', '+00:00'))
            return start.tzinfo is not None and start.astimezone(ZoneInfo('America/New_York')).date().isoformat() == date
        except (KeyError, TypeError, ValueError, AttributeError):
            return False
    try:
        with store.lease(cache_key):
            # A prior request may have finished after our first read.
            latest = store.cached(cache_key)
            if latest and latest != cached:
                return present(latest, True)
            event = next((item for item in loader._get_odds_events(api_key, sport) if matches(item)), None)
            if not event or not isinstance(event.get('id'), str) or not event['id']:
                board = {**result, 'status': 'event_missing', 'cache_time': store.clock()}
                store.cache(cache_key, board, 300)
                return present(board)
            # Three books share one bookmaker group and one response cache.
            params = {'apiKey': api_key, 'bookmakers': ','.join(BOOKS), 'oddsFormat': 'american'}
            if group == 'rebounds':
                params['markets'] = 'player_rebounds'
                url = f"https://api.the-odds-api.com/v4/sports/{sport}/events/{quote(event['id'], safe='')}/odds"
                response = loader._retry_http_get(url, params=params, timeout=15, max_retries=1)
                payload = response.json()
            else:
                pack_key = f'game-pack:{sport}:{date}'
                # Different matchups share the same paid daily game pack. Its
                # own lease covers the recheck and write, not just each board.
                with store.lease(pack_key):
                    pack = store.cached(pack_key)
                    if pack is None or (refresh and store.clock() - pack['cache_time'] >= 60):
                        params['markets'] = 'spreads,h2h,totals'
                        start = datetime.fromisoformat(date).replace(tzinfo=ZoneInfo('America/New_York'))
                        from datetime import timedelta
                        params['commenceTimeFrom'] = start.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
                        params['commenceTimeTo'] = (start + timedelta(days=1)).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
                        response = loader._retry_http_get(f'https://api.the-odds-api.com/v4/sports/{sport}/odds',
                                                         params=params, timeout=15, max_retries=1)
                        payloads = response.json()
                        if not isinstance(payloads, list):
                            raise DataUnavailableError('Invalid game market response')
                        pack = {'events': payloads, 'cache_time': store.clock(),
                                'fetched_at': datetime.now(timezone.utc).isoformat()}
                        store.cache(pack_key, pack, 86400)
                payloads = pack['events']
                payload = next((item for item in payloads if isinstance(item, dict) and item.get('id') == event['id']),
                               {'id': event['id'], 'bookmakers': []})
            entries, coverage = normalize_board(payload, event, BOOKS, home, away)
            wanted = ('player_rebounds',) if group == 'rebounds' else ('spreads', 'h2h', 'totals')
            downloaded = (datetime.now(timezone.utc).isoformat() if group == 'rebounds'
                          else pack['fetched_at'])
            entries = [{**item, 'event_id': event['id'], 'sport': sport, 'source': 'the-odds-api', 'fetched_at': downloaded}
                       for item in entries if item['market'] in wanted]
            for coverage_book in coverage.values():
                for market in MARKETS:
                    if market not in wanted:
                        coverage_book[market] = 'not_requested'
            cache_time = store.clock() if group == 'rebounds' else pack['cache_time']
            board = {**result, 'status': 'available' if entries else 'empty', 'event_id': event['id'],
                     'commence_time': event.get('commence_time'), 'quotes': entries, 'coverage': coverage,
                     'cache_time': cache_time, 'fetched_at': downloaded}
            ttl = 300 if group == 'rebounds' else max(0, 86400 - (store.clock() - cache_time))
            store.cache(cache_key, board, ttl)
            return present(board)
    except Exception as exc:
        code = exc.code if isinstance(exc, OddsBudgetError) else 'provider_unavailable'
        message = str(exc) if isinstance(exc, OddsBudgetError) else 'The sportsbook provider could not be reached. Retry this market later.'
        if old:
            return {**present(old, True), 'status': 'stale', 'refresh_error': message, 'reason_code': code,
                    'quotes': [{**item, 'freshness': 'stale'} for item in old.get('quotes', [])]}
        if isinstance(exc, ProviderHTTPError) and exc.status_code in (400, 422):
            return {**result, 'status': 'unsupported', 'reason_code': 'market_unsupported', 'budget': store.snapshot()}
        if isinstance(exc, OddsBusyError):
            return {**result, 'status': 'request_in_progress', 'message': message, 'budget': store.snapshot()}
        return {**result, 'status': 'budget_limit' if isinstance(exc, OddsBudgetError) else 'provider_unavailable',
                'message': message, 'reason_code': code, 'budget': store.snapshot()}
