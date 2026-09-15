import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
from scripts.check_preseason import summarize, aggregate_reports, audit_player


class PreseasonAuditTests(unittest.TestCase):
    def test_aggregate_weights_games_not_players_and_reports_missing_samples(self):
        row = lambda error: {'error': error, 'naive_prior_projection': 8, 'actual': 5}
        reports = [{'player': 'A', 'evaluation': {'games': [row(1), row(1)]}},
                   {'player': 'B', 'evaluation': {'games': [row(4)]}},
                   {'player': 'C', 'evaluation': {'status': 'source_failed'}}]
        result = aggregate_reports(reports)
        self.assertEqual(result['mae'], 2)
        self.assertEqual(result['evaluated_games'], 3)
        self.assertEqual(result['players_without_evaluated_games'], ['C'])
        self.assertEqual(result['coverage_status'], 'partial')
        self.assertEqual(result['evaluated_players'], 2)
        self.assertEqual(result['unavailable_samples'], [{'player': 'C', 'reason': 'source_failed'}])
        self.assertIsNone(aggregate_reports([])['mae'])

    def test_empty_history_is_not_reported_as_outage_or_invalid_schema(self):
        loader = MagicMock()
        loader.get_player_id.return_value = 1
        loader.get_preseason_player_gamelog.return_value = pd.DataFrame()
        loader._prepare_gamelog.return_value = pd.DataFrame()
        loader.get_data_source_metadata.return_value = {}
        with patch('scripts.check_preseason.NBADataLoader', return_value=loader):
            result = audit_player('Example', '2025-10-18', True)
        self.assertEqual(result['evaluation']['status'], 'empty_history')
        self.assertEqual(result['evaluation']['empty_samples'], ['preseason', 'prior_season'])
        self.assertIsNone(loader.set_request_budget.call_args.args[0])

    def test_source_failure_is_redacted_and_other_history_is_still_checked(self):
        loader = MagicMock()
        loader.get_player_id.return_value = 1
        loader.get_preseason_player_gamelog.side_effect = RuntimeError('secret URL')
        loader._prepare_gamelog.return_value = pd.DataFrame()
        loader.get_data_source_metadata.return_value = {}
        with patch('scripts.check_preseason.NBADataLoader', return_value=loader):
            result = audit_player('Example', '2025-10-18', True)
        self.assertEqual(result['evaluation']['status'], 'source_failed')
        self.assertEqual(result['prior_season_history']['status'], 'empty')
        self.assertNotIn('secret URL', str(result))
        self.assertEqual(loader.set_request_budget.call_count, 4)
        self.assertIsNone(loader.set_request_budget.call_args.args[0])

    def test_batch_distinguishes_missing_player_and_unrequested_evaluation(self):
        result = aggregate_reports([{'player': 'A', 'status': 'player_not_found'}, {'player': 'B'}])
        self.assertEqual(result['coverage_status'], 'no_evaluated_games')
        self.assertEqual([s['reason'] for s in result['unavailable_samples']],
                         ['player_not_found', 'evaluation_not_requested'])
        self.assertIsNone(result['mae'])

    def test_summary_excludes_dnps_and_invalid_rows(self):
        result = summarize(pd.DataFrame([
            {'MIN': '20:30', 'REB': 5}, {'MIN': 10, 'REB': 2},
            {'MIN': 0, 'REB': 0}, {'MIN': 'bad', 'REB': 20},
            {'MIN': 20, 'REB': float('inf')},
        ]))
        self.assertEqual(result['games'], 2)
        self.assertEqual(result['minutes_per_game'], 15.25)
        self.assertEqual(result['rebounds_per_game'], 3.5)

    def test_empty_and_invalid_history_are_not_zero_rebound_forecasts(self):
        self.assertEqual(summarize(pd.DataFrame())['status'], 'empty')
        self.assertEqual(summarize(pd.DataFrame([{'MIN': 20}]))['status'], 'missing_columns')
        self.assertNotIn('rebounds_per_game', summarize(pd.DataFrame([{'MIN': 0, 'REB': 0}])))
