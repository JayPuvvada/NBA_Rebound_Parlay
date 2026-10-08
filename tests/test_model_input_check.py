import json
import unittest
from unittest.mock import Mock

import pandas as pd

from scripts.check_model_inputs import check_inputs


class InputCheckTests(unittest.TestCase):
    def loader(self):
        loader = Mock()
        for name in ('get_team_stats', 'get_team_advanced_stats', 'get_opponent_stats_per_game'):
            getattr(loader, name).return_value = pd.DataFrame({'TEAM_ID': [1]})
        return loader

    def test_success_rechecks_same_cutoff(self):
        loader = self.loader()
        report = check_inputs(loader, '2026-04-08')
        self.assertTrue(all(row['repeat_equal'] for row in report['checks']))
        self.assertEqual(loader.get_team_stats.call_count, 2)
        loader.get_team_stats.assert_called_with(as_of='2026-04-08')

    def test_empty_is_not_available(self):
        loader = self.loader()
        loader.get_team_stats.return_value = pd.DataFrame()
        self.assertEqual(check_inputs(loader, '2026-04-08')['checks'][0]['status'], 'empty')

    def test_exception_chain_is_safe_and_other_inputs_continue(self):
        loader = self.loader()
        cause = TimeoutError('https://provider/?apiKey=secret')
        error = RuntimeError('secret')
        error.__cause__ = cause
        loader.get_team_stats.side_effect = error
        report = check_inputs(loader, '2026-04-08')
        self.assertNotIn('secret', json.dumps(report))
        self.assertEqual(report['checks'][0]['exception_types'], ['RuntimeError', 'TimeoutError'])
        self.assertEqual(report['checks'][1]['status'], 'available')

    def test_changed_repeat_does_not_claim_cache_equality(self):
        loader = self.loader()
        loader.get_team_stats.side_effect = [pd.DataFrame({'TEAM_ID': [1]}), pd.DataFrame({'TEAM_ID': [2]})]
        self.assertFalse(check_inputs(loader, '2026-04-08')['checks'][0]['repeat_equal'])
