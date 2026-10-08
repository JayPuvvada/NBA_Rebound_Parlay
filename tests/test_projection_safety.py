import copy
import unittest

from src.projection_safety import projection_eligibility


class ProjectionSafetyTests(unittest.TestCase):
    def test_primary_authorized_inputs_preserve_warnings_without_mutation(self):
        projection = {
            'prediction_eligible': True, 'limitations': ['top-level warning'],
            'metadata': {'prediction_eligible': True, 'limitations': ['model warning'],
                         'projection_inputs': {'status': 'primary', 'limitations': ['source note']}},
            'data_freshness': {'prediction_eligible': True, 'limitations': ['model warning']},
        }
        original = copy.deepcopy(projection)
        eligible, limitations = projection_eligibility(projection)
        self.assertTrue(eligible)
        self.assertEqual(limitations, ['model warning', 'source note', 'top-level warning'])
        self.assertEqual(projection, original)

    def test_optional_legacy_context_can_be_absent_but_authorization_cannot(self):
        self.assertEqual(projection_eligibility({'metadata': {'prediction_eligible': True}}), (True, []))
        eligible, limitations = projection_eligibility({'prediction_eligible': True})
        self.assertFalse(eligible)
        self.assertIn('explicitly authorize', ' '.join(limitations))

    def test_malformed_or_negative_explicit_signals_fail_closed(self):
        for signal in (False, None, 0, 1, 'true', 'false', [], {}):
            with self.subTest(signal=signal):
                eligible, _ = projection_eligibility({
                    'metadata': {'prediction_eligible': True},
                    'data_freshness': {'prediction_eligible': signal},
                })
                self.assertFalse(eligible)

    def test_unverified_source_and_malformed_warnings_cannot_authorize(self):
        for context in (
            {'projection_inputs': {'status': 'degraded'}},
            {'projection_inputs': {'status': 'unknown'}},
            {'projection_inputs': {}},
            {'projection_inputs': 'primary'},
            {'limitations': 'not a list'},
            {'limitations': [{}]},
        ):
            with self.subTest(context=context):
                eligible, limitations = projection_eligibility({
                    'metadata': {'prediction_eligible': True}, 'data_freshness': context})
                self.assertFalse(eligible)
                self.assertTrue(limitations)
