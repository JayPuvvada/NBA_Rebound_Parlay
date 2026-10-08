"""One bounded local market-coverage check; never generates or saves a pick."""
import argparse
import json
import os
from urllib.parse import urlencode


def coverage_report(response):
    payload = response.get_json(silent=True) or {}
    quotes = payload.get('quotes', [])
    if not isinstance(quotes, list):
        quotes = []
    # Allowlist output rather than dumping provider errors, quotes or configuration.
    counts = {}
    for quote in quotes:
        if isinstance(quote, dict) and quote.get('market') in ('player_rebounds', 'spreads', 'h2h', 'totals'):
            market = quote['market']
            counts[market] = counts.get(market, 0) + 1
    budget = payload.get('budget') or {}
    return {
        'http_status': response.status_code,
        'status': payload.get('status') if payload.get('status') in (
            'available', 'empty', 'stale', 'event_missing', 'unconfigured', 'unavailable', 'budget_limit') else 'unavailable',
        'event_matched': bool(payload.get('event_id')),
        'quote_counts': counts,
        'budget': {key: budget[key] for key in ('daily_used', 'daily_limit', 'cycle_used', 'cycle_limit', 'provider_remaining', 'reserve')
                   if isinstance(budget.get(key), (int, float)) and not isinstance(budget[key], bool)},
        'live_rebound_pick_verified': False,
        'note': 'Coverage only. An empty response is not a verified live pick; stale prices are not current offers.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True, help='NBA calendar date, YYYY-MM-DD')
    parser.add_argument('--home', required=True)
    parser.add_argument('--away', required=True)
    parser.add_argument('--sport', choices=['basketball_nba', 'basketball_nba_preseason'], required=True)
    parser.add_argument('--group', choices=['rebounds', 'game'], default='rebounds')
    parser.add_argument('--refresh', action='store_true', help='Request a metered refresh; otherwise reuse valid cache')
    args = parser.parse_args()
    from src.data_loader import _parse_iso_date
    try:
        _parse_iso_date(args.date)
    except ValueError:
        parser.error('date must be a valid YYYY-MM-DD calendar date')
    from dotenv import load_dotenv
    load_dotenv()
    if os.environ.get('ODDS_BUDGET_ENABLED') == '0':
        parser.error('Live coverage checks require quota enforcement; remove ODDS_BUDGET_ENABLED=0')
    from app import app
    query = urlencode({**vars(args), 'home': args.home.upper(), 'away': args.away.upper(),
                       'refresh': str(args.refresh).lower()})
    with app.test_client() as client:
        report = coverage_report(client.get('/markets?' + query))
    print(json.dumps(report, indent=2))
    return 0 if report['http_status'] == 200 else 1


if __name__ == '__main__':
    raise SystemExit(main())
