import json
import unittest

from scripts.check_markets import coverage_report


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def get_json(self, **kwargs):
        return self.payload


class MarketCheckTests(unittest.TestCase):
    def test_coverage_does_not_claim_model_verification(self):
        report = coverage_report(Response({'status':'available', 'event_id':'event',
            'quotes':[{'market':'spreads'}, {'market':'player_rebounds'}, {'market':'player_rebounds'}]}))
        self.assertEqual(report['quote_counts'], {'spreads':1, 'player_rebounds':2})
        self.assertTrue(report['event_matched'])
        self.assertFalse(report['live_rebound_pick_verified'])

    def test_empty_and_stale_coverage_stay_explicit(self):
        for status in ('empty', 'stale', 'event_missing'):
            report = coverage_report(Response({'status':status, 'quotes':[]}))
            self.assertEqual(report['status'],status)
            self.assertEqual(report['quote_counts'],{})

    def test_report_omits_credentials_and_untrusted_error_text(self):
        report = coverage_report(Response({'status':'secret-value', 'error':'secret-value',
            'apiKey':'secret-value', 'quotes':[{'market':'secret-value'}],
            'budget':{'daily_used':2, 'apiKey':'secret-value', 'provider_remaining':'secret-value'}}))
        self.assertNotIn('secret-value',json.dumps(report))
        self.assertEqual(report['budget'], {'daily_used':2})


if __name__ == '__main__':
    unittest.main()
