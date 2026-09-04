import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pandas as pd

from src.data_loader import (
    DataUnavailableError,
    NBADataLoader,
    _combine_period_per_game_frames,
    _date_to_parameter,
)


class FakeEndpointResponse:
    def __init__(self, frame):
        self.frame = frame

    def get_data_frames(self):
        return [self.frame.copy()]


class FakeHTTPResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class DataLoaderTest(unittest.TestCase):
    def make_loader(self, season='2025-26'):
        with patch.object(NBADataLoader, '_load_offline_cache'):
            return NBADataLoader(season=season)

    @staticmethod
    def complete_team_cache():
        """Small but league-complete fixtures for offline-cache validation."""
        team_ids = range(1, 31)
        return {
            'league_team_stats_base': [
                {'TEAM_ID': team_id, 'FG_PCT': .47} for team_id in team_ids
            ],
            'league_team_stats_advanced': [
                {'TEAM_ID': team_id, 'PACE': 99} for team_id in team_ids
            ],
            'league_opponent_stats': [
                {'TEAM_ID': team_id, 'OPP_OREB': 10, 'OPP_DREB': 33}
                for team_id in team_ids
            ],
        }

    def test_retry_injects_nba_proxy_headers_and_timeout(self):
        loader = self.make_loader()
        endpoint = Mock(return_value='ok')
        endpoint.__name__ = 'Endpoint'
        with patch.dict(os.environ, {'NBA_API_PROXY': 'http://proxy.invalid:8000'}):
            result = loader._retry_api_call(endpoint, timeout=9)

        self.assertEqual(result, 'ok')
        kwargs = endpoint.call_args.kwargs
        self.assertEqual(kwargs['proxy'], 'http://proxy.invalid:8000')
        self.assertEqual(kwargs['timeout'], 9)
        self.assertIn('User-Agent', kwargs['headers'])
        self.assertEqual(kwargs['headers']['Origin'], 'https://www.nba.com')

    def test_scoreboard_uses_retry_wrapper_and_returns_metadata(self):
        loader = self.make_loader()
        board = Mock()
        board.game_header.get_dict.return_value = {
            'headers': [
                'GAME_ID', 'GAME_DATE_EST', 'GAME_STATUS_ID', 'GAME_STATUS_TEXT',
                'HOME_TEAM_ID', 'VISITOR_TEAM_ID',
            ],
            'data': [
                ['001', '2026-01-02', 1, '7:30 pm ET', 10, 20],
                ['001', '2026-01-02', 1, 'duplicate', 10, 20],
            ],
        }
        loader._retry_api_call = Mock(return_value=board)

        games = loader.get_games_for_date('2026-01-02')

        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]['game_id'], '001')
        self.assertEqual(games[0]['home_id'], 10)
        self.assertEqual(games[0]['status_text'], '7:30 pm ET')
        call_kwargs = loader._retry_api_call.call_args.kwargs
        self.assertEqual(call_kwargs['game_date'], '2026-01-02')
        self.assertEqual(call_kwargs['timeout'], 15)

    def test_scoreboard_rejects_invalid_schema_and_bad_date(self):
        loader = self.make_loader()
        with self.assertRaises(ValueError):
            loader.get_games_for_date('01/02/2026')

        board = Mock()
        board.game_header.get_dict.return_value = {'headers': ['GAME_ID'], 'data': []}
        loader._retry_api_call = Mock(return_value=board)
        with self.assertRaises(DataUnavailableError):
            loader.get_games_for_date('2026-01-03')

    def test_fresh_scoreboard_method_bypasses_cached_slate(self):
        loader = self.make_loader()
        board = Mock()
        board.game_header.get_dict.return_value = {
            'headers': ['GAME_ID', 'HOME_TEAM_ID', 'VISITOR_TEAM_ID'],
            'data': [['fresh-1', 10, 20]],
        }
        loader._retry_api_call = Mock(return_value=board)

        first = loader.get_games_for_date('2026-02-02')
        cached = loader.get_games_for_date('2026-02-02')
        fresh = loader.get_games_for_date_fresh('2026-02-02')

        self.assertEqual(first, cached)
        self.assertEqual(fresh[0]['game_id'], 'fresh-1')
        self.assertEqual(loader._retry_api_call.call_count, 2)

    def test_player_gamelog_is_season_and_date_aware(self):
        loader = self.make_loader(season='2026-27')
        calls = []

        def endpoint(_api, **kwargs):
            calls.append(kwargs)
            if kwargs['season_type_all_star'] != 'Regular Season':
                return FakeEndpointResponse(pd.DataFrame())
            return FakeEndpointResponse(pd.DataFrame({
                'GAME_DATE': ['JAN 03, 2025', 'JAN 01, 2025'],
                'REB': [99, 8],
            }))

        loader._retry_api_call = endpoint
        result = loader.get_player_gamelog(7, as_of='2025-01-02')

        self.assertEqual(result['REB'].tolist(), [8])
        self.assertTrue(all(call['season'] == '2024-25' for call in calls))
        self.assertTrue(all(call['date_to_nullable'] == '01/01/2025' for call in calls))
        self.assertEqual(
            [call['season_type_all_star'] for call in calls],
            ['Regular Season', 'PlayIn', 'Playoffs'],
        )

    def test_period_dashboards_are_combined_by_games_played(self):
        regular = pd.DataFrame([{
            'TEAM_ID': 1, 'TEAM_NAME': 'Old Name', 'GP': 10, 'W': 6,
            'PACE': 100.0,
        }])
        play_in = pd.DataFrame([{
            'TEAM_ID': 1, 'TEAM_NAME': 'Current Name', 'GP': 2, 'W': 1,
            'PACE': 98.0,
        }])
        playoffs = pd.DataFrame([{
            'TEAM_ID': 1, 'TEAM_NAME': 'Current Name', 'GP': 3, 'W': 2,
            'PACE': 96.0,
        }])

        combined = _combine_period_per_game_frames(
            [regular, play_in, playoffs], 'TEAM_ID'
        )

        self.assertEqual(len(combined), 1)
        self.assertEqual(combined.iloc[0]['GP'], 15)
        self.assertEqual(combined.iloc[0]['W'], 9)
        self.assertEqual(combined.iloc[0]['TEAM_NAME'], 'Current Name')
        self.assertAlmostEqual(combined.iloc[0]['PACE'], 1484 / 15)

    def test_all_failed_gamelog_calls_are_not_valid_empty_data(self):
        loader = self.make_loader()
        loader._retry_api_call = Mock(side_effect=TimeoutError('blocked'))
        with self.assertRaises(DataUnavailableError):
            loader.get_team_gamelog(10)

    def test_partially_failed_gamelog_is_not_treated_as_complete(self):
        loader = self.make_loader()
        regular = FakeEndpointResponse(pd.DataFrame({
            'GAME_DATE': ['JAN 01, 2026'], 'REB': [8],
        }))
        loader._retry_api_call = Mock(side_effect=[regular, TimeoutError('blocked')])

        with self.assertRaises(DataUnavailableError):
            loader.get_player_gamelog(7)

    def test_mutable_roster_cache_has_a_bounded_lifetime(self):
        loader = self.make_loader()
        loader._retry_api_call = Mock(side_effect=[
            FakeEndpointResponse(pd.DataFrame([{'PLAYER_ID': 1}])),
            FakeEndpointResponse(pd.DataFrame([{'PLAYER_ID': 2}])),
        ])

        with patch('src.data_loader.time.monotonic', return_value=1000):
            first = loader.get_team_roster(10)
        with patch('src.data_loader.time.monotonic', return_value=1001):
            cached = loader.get_team_roster(10)
        with patch(
            'src.data_loader.time.monotonic',
            return_value=1000 + loader.ROSTER_CACHE_TTL_SEC + 1,
        ):
            refreshed = loader.get_team_roster(10)

        self.assertEqual(first.iloc[0]['PLAYER_ID'], 1)
        self.assertEqual(cached.iloc[0]['PLAYER_ID'], 1)
        self.assertEqual(refreshed.iloc[0]['PLAYER_ID'], 2)
        self.assertEqual(loader._retry_api_call.call_count, 2)

    def test_odds_match_eastern_date_and_preserve_both_sides(self):
        loader = self.make_loader()
        # 00:30 UTC on Jan 2 is still Jan 1 in New York.
        events = [{
            'id': 'event-1',
            'home_team': 'Boston Celtics',
            'away_team': 'Los Angeles Lakers',
            'commence_time': '2026-01-02T00:30:00Z',
        }]
        props = {
            'bookmakers': [{
                'key': 'fanduel',
                'title': 'FanDuel',
                'markets': [
                    {'key': 'spreads', 'outcomes': [
                        {'name': 'Boston Celtics', 'point': -4.5, 'price': -110},
                        {'name': 'Los Angeles Lakers', 'point': 4.5, 'price': -110},
                    ]},
                    {'key': 'player_rebounds', 'outcomes': [
                        {'name': 'Over', 'description': 'LeBron James', 'point': 7.5, 'price': -115},
                        {'name': 'Under', 'description': 'LeBron James', 'point': 8.0, 'price': 105},
                    ]},
                ],
            }],
        }
        loader._retry_http_get = Mock(side_effect=[
            FakeHTTPResponse(events), FakeHTTPResponse(props),
        ])

        result = loader.get_odds_for_game(
            'secret', 'BOS', 'LAL', '2026-01-01', bookmaker='fanduel'
        )

        quote = result['lebron james']
        self.assertEqual(quote['over'], {
            'line': 7.5, 'point': 7.5, 'odds': -115, 'price': -115,
            'book': 'FanDuel', 'bookmaker': 'fanduel',
            'source': 'the-odds-api',
            'fetched_at': quote['fetched_at'], 'updated_at': quote['updated_at'],
        })
        self.assertEqual(quote['under']['line'], 8.0)
        self.assertEqual(quote['under_odds'], 105)
        self.assertEqual(quote['odds'], -115)  # legacy field remains Over only
        self.assertEqual(result['_meta']['home_spread'], -4.5)
        self.assertEqual(result['_meta']['event_id'], 'event-1')
        self.assertNotIn('secret', json.dumps(result))

    def test_odds_cache_refreshes_after_five_minute_safety_window(self):
        loader = self.make_loader()
        events = [{
            'id': 'event-cache',
            'home_team': 'Boston Celtics',
            'away_team': 'Los Angeles Lakers',
            'commence_time': '2026-01-02T00:30:00Z',
        }]
        props = {'bookmakers': []}
        loader._retry_http_get = Mock(side_effect=[
            FakeHTTPResponse(events), FakeHTTPResponse(props),
            FakeHTTPResponse(events), FakeHTTPResponse(props),
        ])

        with patch('src.cache.time.monotonic', return_value=1000):
            first = loader.get_odds_for_game('secret', 'BOS', 'LAL', '2026-01-01')
            cached = loader.get_odds_for_game('secret', 'BOS', 'LAL', '2026-01-01')
        self.assertEqual(first, cached)
        self.assertEqual(loader._retry_http_get.call_count, 2)

        with patch('src.cache.time.monotonic', return_value=1301):
            loader.get_odds_for_game('secret', 'BOS', 'LAL', '2026-01-01')
        self.assertEqual(loader._retry_http_get.call_count, 4)

    def test_offline_cache_uses_embedded_timestamp_not_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = os.path.join(directory, 'nba_cache.json')
            old_timestamp = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
            payload = {
                'timestamp': old_timestamp,
                'season': '2025-26',
                'data': {
                    'league_team_stats_base': [{'TEAM_ID': 1}],
                    'league_team_stats_advanced': [{'TEAM_ID': 1}],
                    'league_opponent_stats': [{'TEAM_ID': 1}],
                },
            }
            with open(cache_path, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle)
            os.utime(cache_path, None)  # freshly copied old content

            with patch.object(NBADataLoader, 'OFFLINE_CACHE_FILE', cache_path):
                loader = NBADataLoader(season='2025-26')
            self.assertEqual(loader._cache, {})

    def test_offline_cache_maps_exact_as_of_dashboard_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = os.path.join(directory, 'nba_cache.json')
            as_of = '2026-09-04'
            payload = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'season': '2025-26',
                'as_of_date': as_of,
                'data_through': _date_to_parameter(as_of),
                'data': self.complete_team_cache(),
            }
            with open(cache_path, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle)

            with patch.object(NBADataLoader, 'OFFLINE_CACHE_FILE', cache_path):
                loader = NBADataLoader(season='2025-26')
            key = 'league_team_stats_base_2025-26_2026-09-04'
            self.assertIn(key, loader._cache)
            self.assertEqual(loader._cache[key].iloc[0]['TEAM_ID'], 1)

    def test_historical_offline_cache_does_not_populate_current_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = os.path.join(directory, 'nba_cache.json')
            as_of = '2026-01-15'
            payload = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'season': '2025-26',
                'as_of_date': as_of,
                'data_through': _date_to_parameter(as_of),
                'data': self.complete_team_cache(),
            }
            with open(cache_path, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle)

            with patch.object(NBADataLoader, 'OFFLINE_CACHE_FILE', cache_path):
                loader = NBADataLoader(season='2025-26')

            exact_key = f'league_team_stats_base_2025-26_{as_of}'
            self.assertIn(exact_key, loader._cache)
            self.assertNotIn('league_team_stats_base_2025-26', loader._cache)

    def test_bounded_stale_injury_cache_does_not_outlive_hard_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = os.path.join(directory, 'injuries.json')
            loader = self.make_loader()
            now = time.time()
            written_at = now - loader.INJURY_STALE_MAX_SEC + 30
            payload = {
                'timestamp': datetime.fromtimestamp(written_at, timezone.utc).isoformat(),
                'injuries': {f'player {index}': 'Out' for index in range(12)},
            }
            with open(cache_path, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle)
            loader._retry_http_get = Mock(side_effect=DataUnavailableError('offline'))

            with (
                patch.object(NBADataLoader, 'INJURY_DISK_CACHE', cache_path),
                patch('src.data_loader.time.time', return_value=now),
            ):
                first = loader.get_injury_report()
            self.assertEqual(len(first), 12)
            self.assertEqual(
                loader.get_injury_report_metadata()['source'],
                'bounded_stale_disk_cache',
            )

            # Once the remaining 30-second allowance expires, the in-memory
            # copy must not silently receive a fresh 20-minute lease.
            with (
                patch.object(NBADataLoader, 'INJURY_DISK_CACHE', cache_path),
                patch('src.data_loader.time.time', return_value=now + 31),
            ):
                second = loader.get_injury_report()
            self.assertEqual(second, {})
            self.assertEqual(loader.get_injury_report_metadata()['status'], 'unavailable')

    def test_timestamped_injury_cache_never_falls_back_to_fresh_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = os.path.join(directory, 'injuries.json')
            with open(cache_path, 'w', encoding='utf-8') as handle:
                json.dump({
                    'timestamp': 'not-a-date',
                    'injuries': {f'player {index}': 'Out' for index in range(12)},
                }, handle)
            os.utime(cache_path, None)
            loader = self.make_loader()
            loader._retry_http_get = Mock(side_effect=DataUnavailableError('offline'))

            with patch.object(NBADataLoader, 'INJURY_DISK_CACHE', cache_path):
                result = loader.get_injury_report()

            self.assertEqual(result, {})
            self.assertEqual(loader.get_injury_report_metadata()['status'], 'unavailable')

    def test_legacy_injury_cache_without_timestamp_is_not_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = os.path.join(directory, 'injuries.json')
            with open(cache_path, 'w', encoding='utf-8') as handle:
                json.dump({f'player {index}': 'Out' for index in range(12)}, handle)
            os.utime(cache_path, None)
            loader = self.make_loader()
            loader._retry_http_get = Mock(side_effect=DataUnavailableError('offline'))

            with patch.object(NBADataLoader, 'INJURY_DISK_CACHE', cache_path):
                result = loader.get_injury_report()

            self.assertEqual(result, {})
            self.assertEqual(loader.get_injury_report_metadata()['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
