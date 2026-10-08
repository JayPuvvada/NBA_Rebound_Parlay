import unittest
import os
from unittest.mock import Mock, patch

import pandas as pd

import app as app_module
from src.data_loader import DataUnavailableError
from src.preseason_analysis import player_analysis, summarize_history


def history(rows):
    return pd.DataFrame(rows, columns=['GAME_ID', 'GAME_DATE', 'MIN', 'REB'])


def loader(season, frame):
    source = Mock(season=season)
    source.get_player_gamelog.return_value = frame
    source.get_preseason_player_gamelog.return_value = frame
    source.get_data_source_metadata.return_value = {'status': 'primary', 'source': 'stats.nba.com', 'limitations': []}
    return source


class PreseasonAnalysisTests(unittest.TestCase):
    def test_cutoff_excludes_target_and_future_and_preserves_input(self):
        frame = history([['1', '2026-10-01', 10, 4], ['2', '2026-10-04', 30, 20],
                         ['3', '2026-10-05', 40, 30], ['4', '2026-10-02', 0, 0]])
        original = frame.copy(deep=True)
        summary, minutes = summarize_history(frame, '2026-10-04', '2026-27')
        self.assertEqual(summary['games'], 1)
        self.assertEqual(summary['rebounds_per_minute'], .4)
        self.assertEqual(minutes, [10])
        self.assertEqual(summary['recent_games'], [{'date': '2026-10-01', 'minutes': 10.0, 'rebounds': 4}])
        pd.testing.assert_frame_equal(frame, original)

    def test_invalid_rebound_counts_do_not_enter_observed_averages(self):
        frame = history([[str(i), '2026-10-01', 10, rebound]
                         for i, rebound in enumerate([True, False, -1, 2.5, 'bad', float('inf'), 5])])
        summary, _ = summarize_history(frame, '2026-10-04', '2026-27')
        self.assertEqual(summary['games'], 1)
        self.assertEqual(summary['rebounds_per_game'], 5)

    def test_duplicate_or_schema_invalid_inputs_fail_visibly(self):
        for frame in [history([['1', '2026-10-01', 10, 4]] * 2), pd.DataFrame([{'REB': 2}])]:
            with self.assertRaises(ValueError):
                summarize_history(frame, '2026-10-04', '2026-27')

    def test_corruption_is_not_presented_as_legitimately_empty_history(self):
        for row in (['1', 'bad-date', 10, 4], ['1', '2026-10-01', '10:90', 4],
                    ['1', '2026-10-01', 'bad', 4]):
            with self.subTest(row=row), self.assertRaises(ValueError):
                summarize_history(history([row]), '2026-10-04', '2026-27')
        summary, _ = summarize_history(history([['1', '2026-10-01', 'DNP', None]]), '2026-10-04', '2026-27')
        self.assertEqual(summary['status'], 'empty')

    def test_partial_corruption_has_a_visible_warning(self):
        current = loader('2026-27', history([['2', '2026-10-01', '10:30', 5], ['3', 'bad-date', 10, 4]]))
        prior = loader('2025-26', history([['1', '2026-04-01', 30, 12]]))
        result = player_analysis(7, current, prior, '2026-10-04')
        self.assertEqual(result['preseason']['games'], 1)
        self.assertIn('malformed preseason rows', ' '.join(result['limitations']))

    def test_first_appearance_has_no_automatic_estimate(self):
        current = loader('2026-27', history([]))
        prior = loader('2025-26', history([['1', '2026-04-01', 30, 12]]))
        result = player_analysis(7, current, prior, '2026-10-04')
        self.assertIsNone(result['estimate'])
        self.assertEqual(result['preseason']['status'], 'empty')
        self.assertFalse(result['prediction_eligible'])
        prior.get_player_gamelog.assert_called_once_with(7)
        current.get_preseason_player_gamelog.assert_called_once_with(7, as_of='2026-10-04')

    def test_manual_and_observed_minutes_are_explicit_not_betting_signals(self):
        current = loader('2026-27', history([['2', '2026-10-01', 10, 5], ['3', '2026-10-02', 20, 8]]))
        prior = loader('2025-26', history([['1', '2026-04-01', 30, 12]]))
        for minutes, expected, source in [(None, 6, 'earlier_preseason'), (20, 8, 'manual'), (0, 0, 'manual')]:
            with self.subTest(minutes=minutes):
                result = player_analysis(7, current, prior, '2026-10-04', minutes)
                self.assertEqual(result['estimate']['rebounds'], expected)
                self.assertEqual(result['estimate']['minutes_source'], source)
                self.assertTrue(result['analysis_only'])
                self.assertFalse(result['prediction_eligible'])
                self.assertNotIn('confidence', result)
                self.assertNotIn('direction', result)

    def test_failure_preserves_other_history_and_clears_budgets(self):
        current = loader('2026-27', history([]))
        prior = loader('2025-26', history([['1', '2026-04-01', 30, 12]]))
        current.get_preseason_player_gamelog.side_effect = DataUnavailableError('private detail')
        result = player_analysis(7, current, prior, '2026-10-04', 20)
        self.assertEqual(result['preseason']['status'], 'unavailable')
        self.assertEqual(result['prior_season']['status'], 'available')
        self.assertEqual(result['estimate']['rebounds'], 8)
        self.assertNotIn('private detail', str(result))
        for item in (current, prior):
            item.set_request_budget.assert_any_call(15)
            item.set_request_budget.assert_called_with(None)

    def test_minutes_must_be_explicit_valid_numbers(self):
        for value in [True, '20', -1, 49, float('inf'), float('nan')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                player_analysis(1, None, None, '2026-10-04', value)


class PreseasonRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.current = loader('2026-27', history([]))
        self.prior = loader('2025-26', history([['1', '2026-04-01', 30, 12]]))
        self.current.get_games_for_date.return_value = [
            {'home_id': 1610612746, 'away_id': 1610612744, 'is_preseason': True}]
        self.current.get_analysis_roster.return_value = {
            'players': [{'player_id': 7, 'name': 'Test Player'}], 'source': 'espn',
            'limitations': ['Fallback roster; availability unverified.'], 'unmatched_count': 1}
        self.components = patch.object(app_module, '_components_for_date',
                                      side_effect=lambda date: (self.prior if date.year == 2025 else self.current, None))
        self.components.start()
        self.addCleanup(self.components.stop)
        self.body = {'player_id': 7, 'team': 'GSW', 'opponent': 'LAC', 'date': '2026-10-04'}

    def test_roster_preserves_partial_team_and_fallback_warnings(self):
        roster = self.current.get_analysis_roster.return_value
        self.current.get_analysis_roster.side_effect = [DataUnavailableError('secret'), roster]
        response = self.client.get('/preseason-roster?team=GSW&date=2026-10-04')
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result['teams'][0]['players'], [])
        self.assertTrue(result['teams'][0]['error'])
        self.assertEqual(len(result['teams'][1]['players']), 1)
        self.assertNotIn('secret', str(result))
        self.current.set_request_budget.assert_called_with(None)

    def test_player_analysis_has_no_betting_or_ledger_path(self):
        response = self.client.post('/preseason-player', json={**self.body, 'minutes': 20, 'record': True})
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result['estimate']['rebounds'], 8)
        self.assertFalse(result['prediction_eligible'])
        self.assertTrue(result['analysis_only'])
        self.assertIn('Fallback roster; availability unverified.', result['limitations'])
        self.current.get_odds_for_game.assert_not_called()

    def test_invalid_identity_minutes_and_opponent_fail_before_history_calls(self):
        for change in ({'player_id': True}, {'player_id': 1.5}, {'player_id': 999},
                       {'opponent': 'BOS'}, {'minutes': True}, {'minutes': -1}, {'minutes': 49}):
            with self.subTest(change=change):
                response = self.client.post('/preseason-player', json={**self.body, **change})
                self.assertEqual(response.status_code, 400)
        self.current.get_preseason_player_gamelog.assert_not_called()
        self.prior.get_player_gamelog.assert_not_called()

    def test_nonpreseason_games_rejected_before_rosters_or_histories(self):
        self.current.get_games_for_date.return_value[0]['is_preseason'] = False
        response = self.client.post('/preseason-player', json=self.body)
        self.assertEqual(response.status_code, 400)
        self.current.get_analysis_roster.assert_not_called()
        self.current.set_request_budget.assert_called_with(None)

    def test_market_feed_does_not_invent_missing_quotes_or_fresh_timestamps(self):
        self.current.get_odds_for_game.return_value = {
            'test player': {'over': {'line': 4.5, 'odds': -110}, 'under': {'line': 5.5, 'odds': 120},
                            'fetched_at': '2026-10-04T12:00:00Z'}}
        with patch.dict(os.environ, {'ODDS_API_KEY': 'test-key'}):
            response = self.client.get('/preseason-markets?team=GSW&date=2026-10-04&book=fanduel')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['status'], 'available')
        quotes = payload['markets'][0]['quotes']
        self.assertEqual([quote['line'] for quote in quotes], [4.5, 5.5])
        self.assertTrue(all(quote['updated_at'] is None and not quote['fresh'] for quote in quotes))
        self.current.get_preseason_player_gamelog.assert_not_called()
        self.assertNotIn('confidence', payload)
        self.current.set_request_budget.assert_called_with(None)

    def test_market_empty_unconfigured_and_failed_are_distinct(self):
        path = '/preseason-markets?team=GSW&date=2026-10-04'
        with patch.dict(os.environ, {'ODDS_API_KEY': ''}):
            self.assertEqual(self.client.get(path).get_json()['status'], 'unconfigured')
        self.current.get_odds_for_game.assert_not_called()
        self.current.get_odds_for_game.return_value = {}
        with patch.dict(os.environ, {'ODDS_API_KEY': 'test-key'}):
            self.assertEqual(self.client.get(path).get_json()['status'], 'empty')
            self.current.get_odds_for_game.side_effect = DataUnavailableError('secret')
            response = self.client.get(path)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', str(response.get_json()))
        self.assertIn('history can still be viewed', response.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
