import unittest
import pandas as pd
from src.preseason_evaluation import evaluate_preseason


class PreseasonEvaluationTests(unittest.TestCase):
    def frames(self):
        return (pd.DataFrame([{'GAME_ID': 'prior', 'GAME_DATE': '2024-12-01', 'MIN': 30, 'REB': 12}]),
                pd.DataFrame([{'GAME_ID': 'a', 'GAME_DATE': '2025-10-01', 'MIN': 10, 'REB': 3},
                              {'GAME_ID': 'b', 'GAME_DATE': '2025-10-03', 'MIN': 20, 'REB': 5}]))

    def test_first_game_skipped_and_later_prediction_uses_only_earlier_minutes(self):
        prior, preseason = self.frames()
        result = evaluate_preseason(prior, preseason)
        self.assertEqual(result['skipped_games'], 1)
        self.assertEqual(result['evaluated_games'], 1)
        self.assertEqual(result['games'][0]['projection'], 4)
        self.assertEqual(result['mae'], 1)
        self.assertEqual(result['naive_prior_mae'], 7)

    def test_target_and_future_data_cannot_change_target_prediction(self):
        prior, preseason = self.frames()
        preseason.loc[1, ['MIN', 'REB']] = [48, 40]
        prior.loc[1] = {'GAME_ID': 'future', 'GAME_DATE': '2025-10-10', 'MIN': 48, 'REB': 40}
        self.assertEqual(evaluate_preseason(prior, preseason)['games'][0]['projection'], 4)

    def test_duplicates_rejected_and_no_sample_has_no_error_score(self):
        prior, preseason = self.frames()
        with self.assertRaises(ValueError):
            evaluate_preseason(prior, pd.concat([preseason, preseason]))
        result = evaluate_preseason(prior, preseason.iloc[:1])
        self.assertIsNone(result['mae'])
        self.assertEqual(result['evaluated_games'], 0)

    def test_nba_game_id_column_alias_is_supported(self):
        prior, preseason = self.frames()
        result = evaluate_preseason(prior.rename(columns={'GAME_ID': 'Game_ID'}), preseason)
        self.assertEqual(result['evaluated_games'], 1)

    def test_excluded_rows_and_skipped_appearances_are_reported_separately(self):
        prior, preseason = self.frames()
        extra = pd.DataFrame([
            {'GAME_ID': 'dnp', 'GAME_DATE': '2025-10-04', 'MIN': 0, 'REB': 0},
            {'GAME_ID': '   ', 'GAME_DATE': '2025-10-05', 'MIN': 20, 'REB': 6},
            {'GAME_ID': 'bad', 'GAME_DATE': 'invalid', 'MIN': 20, 'REB': 6}])
        result = evaluate_preseason(prior, pd.concat([preseason, extra]))
        self.assertEqual(result['sample_counts']['preseason'],
                         {'input_rows': 5, 'usable_appearances': 2, 'excluded_rows': 3})
        self.assertEqual(result['evaluated_games'], 1)
        self.assertEqual(result['skipped_games'], 1)
        self.assertEqual(result['skip_reasons'],
                         {'no_earlier_preseason_appearance': 1, 'no_earlier_prior_history': 0})

    def test_overlapping_samples_rejected_after_id_normalization(self):
        prior, preseason = self.frames()
        prior.loc[0, 'GAME_ID'] = ' a '
        with self.assertRaisesRegex(ValueError, 'must not share game IDs'):
            evaluate_preseason(prior, preseason)

    def test_missing_prior_history_is_reported_without_error_score(self):
        prior, preseason = self.frames()
        result = evaluate_preseason(prior.iloc[:0], preseason)
        self.assertEqual(result['skipped_games'], 2)
        self.assertEqual(result['skip_reasons']['no_earlier_prior_history'], 2)
        self.assertIsNone(result['mae'])

    def test_whitespace_duplicate_ids_are_rejected(self):
        prior, preseason = self.frames()
        preseason.loc[1, 'GAME_ID'] = ' a '
        with self.assertRaisesRegex(ValueError, 'Duplicate game IDs'):
            evaluate_preseason(prior, preseason)
