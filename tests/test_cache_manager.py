import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src import cache_manager
from src.data_loader import NBADataLoader, _atomic_json_write, _date_to_parameter
from src.utils import current_season, eastern_today


class DiskCacheTest(unittest.TestCase):
    def payload(self, timestamp):
        return {
            'timestamp': timestamp,
            'season': current_season(),
            'as_of_date': eastern_today(),
            'data_through': _date_to_parameter(eastern_today()),
            'data': {
                'league_team_stats_base': [{'TEAM_ID': 1, 'FG_PCT': .47}],
                'league_team_stats_advanced': [{'TEAM_ID': 1, 'PACE': 99}],
                'league_opponent_stats': [{
                    'TEAM_ID': 1, 'OPP_OREB': 10, 'OPP_DREB': 33,
                }],
            },
        }

    def test_staleness_uses_embedded_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'cache.json')
            old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(self.payload(old), handle)
            os.utime(path, None)
            with patch.object(cache_manager, 'CACHE_FILE', path):
                self.assertTrue(cache_manager.is_cache_stale())

    def test_complete_fresh_cache_is_not_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'cache.json')
            now = datetime.now(timezone.utc).isoformat()
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(self.payload(now), handle)
            with patch.object(cache_manager, 'CACHE_FILE', path):
                self.assertFalse(cache_manager.is_cache_stale())

    def test_missing_team_base_dataset_is_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'cache.json')
            payload = self.payload(datetime.now(timezone.utc).isoformat())
            del payload['data']['league_team_stats_base']
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle)
            with patch.object(cache_manager, 'CACHE_FILE', path):
                self.assertTrue(cache_manager.is_cache_stale())

    def test_failed_atomic_serialization_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'cache.json')
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('{"old": true}')
            with self.assertRaises(TypeError):
                _atomic_json_write(path, {'bad': object()})
            with open(path, 'r', encoding='utf-8') as handle:
                self.assertEqual(json.load(handle), {'old': True})


if __name__ == '__main__':
    unittest.main()
