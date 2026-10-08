"""Separate loopback-only server: real NBA data, synthetic sportsbook quotes."""
from datetime import datetime, timezone
from functools import lru_cache

from app import app
import app as app_module
import src.pick_generator as generator
from src.markets import BOOKS, MARKETS


@lru_cache(maxsize=16)
def subjects(home, away, date):
    from src.data_loader import NBADataLoader
    from src.utils import current_season
    from datetime import date as Date
    loader = NBADataLoader(season=current_season(Date.fromisoformat(date)))
    loader.set_request_budget(25)
    result = []
    preferred = {'Jarrett Allen', 'Evan Mobley', 'Jaylen Brown', 'Derrick White'}
    for team in (home, away):
        roster = loader.get_analysis_roster(loader.get_team_id(team))['players']
        roster = sorted(roster, key=lambda p: (p['name'] not in preferred, p['name']))
        result.extend((p['name'], team) for p in roster[:2])
    return result


def synthetic_board(loader, api_key, home, away, date, sport, books=BOOKS, **kwargs):
    games = loader.get_games_for_date(date)
    game = next((g for g in games if g['home_id'] == loader.get_team_id(home)
                 and g['away_id'] == loader.get_team_id(away)), None)
    if game is None:
        return {'status': 'event_missing', 'date': date, 'game': {'home': home, 'away': away},
                'quotes': [], 'coverage': {}, 'message': 'Choose a real scheduled matchup.'}
    fetched = datetime.now(timezone.utc).isoformat()
    quotes = [{'market': 'player_rebounds', 'player': name, 'team': team,
               'selection': side, 'line': 8.5 if index % 2 == 0 else 5.5,
               'odds': -110 if side == 'OVER' else -115, 'book': book,
               'sport': sport, 'source': 'synthetic-local-test', 'event_id': str(game['game_id']),
               'updated_at': None, 'fetched_at': fetched, 'freshness': 'unknown'}
              for index, (name, team) in enumerate(subjects(home, away, date))
              for book in books for side in ('OVER', 'UNDER')]
    return {'status': 'available', 'date': date, 'game': {'home': home, 'away': away},
            'sport': sport, 'event_id': str(game['game_id']), 'source': 'synthetic-local-test',
            'fetched_at': fetched, 'quotes': quotes,
            'coverage': {b: {m: 'available' if m == 'player_rebounds' else 'not_requested'
                             for m in MARKETS} for b in books},
            'message': 'Synthetic odds for interface testing; real NBA schedule and history.'}


# This module is also imported by spawned generator workers. Production app
# entrypoints never import it, so real-provider behavior remains untouched.
if __name__ in {'__main__', '__mp_main__'}:
    app_module.fetch_board = synthetic_board
    generator.fetch_board = synthetic_board

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5010, debug=False, use_reloader=False)
