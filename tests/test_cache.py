import threading
import unittest

from src.cache import ttl_cache


class TTLCacheTest(unittest.TestCase):
    def test_instances_and_seasons_do_not_share_entries(self):
        class Source:
            def __init__(self, season, marker):
                self.season = season
                self.marker = marker
                self.calls = 0

            @ttl_cache(60)
            def load(self, value):
                self.calls += 1
                return {'items': [self.marker, value]}

        first = Source('2024-25', 'old')
        second = Source('2025-26', 'new')
        self.assertEqual(first.load(1)['items'][0], 'old')
        self.assertEqual(second.load(1)['items'][0], 'new')
        self.assertEqual(first.calls, 1)
        self.assertEqual(second.calls, 1)

    def test_cached_mutable_values_are_defensive_copies(self):
        calls = []

        @ttl_cache(60)
        def load():
            calls.append(True)
            return {'values': [1]}

        first = load()
        first['values'].append(2)
        self.assertEqual(load(), {'values': [1]})
        self.assertEqual(len(calls), 1)

    def test_empty_values_are_not_cached_unless_explicit(self):
        calls = []

        @ttl_cache(60)
        def default():
            calls.append(True)
            return []

        default()
        default()
        self.assertEqual(len(calls), 2)

        cached_calls = []

        @ttl_cache(60, cache_empty=True)
        def opted_in():
            cached_calls.append(True)
            return []

        opted_in()
        opted_in()
        self.assertEqual(len(cached_calls), 1)

    def test_exception_is_not_cached(self):
        calls = []

        @ttl_cache(60)
        def unstable():
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError('temporary')
            return 7

        with self.assertRaises(RuntimeError):
            unstable()
        self.assertEqual(unstable(), 7)
        self.assertEqual(len(calls), 2)

    def test_simultaneous_calls_compute_once(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        results = []

        @ttl_cache(60)
        def slow():
            calls.append(True)
            entered.set()
            release.wait(timeout=2)
            return [3]

        first = threading.Thread(target=lambda: results.append(slow()))
        second = threading.Thread(target=lambda: results.append(slow()))
        first.start()
        entered.wait(timeout=2)
        second.start()
        release.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertEqual(calls, [True])
        self.assertEqual(results, [[3], [3]])


if __name__ == '__main__':
    unittest.main()
