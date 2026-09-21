import threading
import unittest

from src.cache import ttl_cache


class TTLCacheTest(unittest.TestCase):
    def test_warm_cache_does_not_bypass_argument_type_validation(self):
        @ttl_cache(60)
        def load(player_id):
            if isinstance(player_id, bool):
                raise ValueError('boolean player ID is invalid')
            return {'player_id': player_id}

        self.assertEqual(load(1), {'player_id': 1})
        with self.assertRaisesRegex(ValueError, 'boolean player ID'):
            load(True)

    def test_container_types_remain_distinct_in_cache_keys(self):
        @ttl_cache(60)
        def load(options):
            return type(options).__name__

        self.assertEqual(load([1]), 'list')
        self.assertEqual(load((1,)), 'tuple')
        self.assertEqual(load({1}), 'set')

    def test_concurrent_first_calls_share_one_instance_token(self):
        # Synchronize missing-token reads to reproduce the race deterministically.
        # With serialized initialization, the first read times out harmlessly;
        # the second read sees the token that was already installed.
        token_reads = threading.Barrier(2)
        start = threading.Barrier(3)
        results = []

        class Source:
            def __init__(self):
                self.calls = 0

            def __getattr__(self, name):
                if name == '_ttl_cache_token':
                    try:
                        token_reads.wait(timeout=0.2)
                    except threading.BrokenBarrierError:
                        pass
                raise AttributeError(name)

            @ttl_cache(60)
            def load(self):
                self.calls += 1
                return [7]

        source = Source()

        def call():
            start.wait(timeout=2)
            results.append(source.load())

        workers = [threading.Thread(target=call) for _ in range(2)]
        for worker in workers:
            worker.start()
        start.wait(timeout=2)
        for worker in workers:
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(results, [[7], [7]])
        self.assertEqual(source.calls, 1)

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

    def test_expired_waiter_does_not_cancel_cache_owner(self):
        entered = threading.Event()
        release = threading.Event()
        results = []

        class Loader:
            def _bounded_timeout(self, timeout):
                raise TimeoutError('waiting request expired')

            @ttl_cache(60)
            def fetch(self):
                entered.set()
                release.wait(timeout=2)
                return [7]

        loader = Loader()
        owner = threading.Thread(target=lambda: results.append(loader.fetch()))
        owner.start()
        try:
            self.assertTrue(entered.wait(timeout=2))
            with self.assertRaises(TimeoutError):
                loader.fetch()
        finally:
            release.set()
            owner.join(timeout=2)
        self.assertEqual(results, [[7]])
        self.assertEqual(loader.fetch(), [7])

    def test_invalidation_during_fetch_does_not_repopulate_old_result(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        results = []

        @ttl_cache(60)
        def fetch():
            calls.append(True)
            if len(calls) == 1:
                entered.set()
                release.wait(timeout=2)
                return 'old'
            return 'new'

        owner = threading.Thread(target=lambda: results.append(fetch()))
        owner.start()
        try:
            self.assertTrue(entered.wait(timeout=2))
            fetch.invalidate()
        finally:
            release.set()
            owner.join(timeout=2)
        self.assertEqual(results, ['old'])
        self.assertEqual(fetch(), 'new')
        self.assertEqual(fetch(), 'new')
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
