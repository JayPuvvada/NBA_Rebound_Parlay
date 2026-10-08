import os
import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from src.markets import fetch_board, normalize_board
from src.odds_budget import OddsStore, OddsBudgetError, OddsBusyError, metered_request


class OddsBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, 'quotes.db')
        self.env = patch.dict(os.environ, {'ODDS_CACHE_PATH': self.path, 'ODDS_BUDGET_ENABLED': '1',
                                           'ODDS_DAILY_CREDITS': '16', 'ODDS_CYCLE_CREDITS': '450',
                                           'ODDS_CREDIT_RESERVE': '50', 'VERCEL': '', 'RENDER': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = OddsStore(api_key='private-test-key')
        self.store.observe({'x-requests-used': '0', 'x-requests-remaining': '500'})

    def test_concurrent_reservations_cannot_exceed_daily_cap(self):
        def reserve(_):
            try:
                return OddsStore(api_key='private-test-key').reserve(1)
            except OddsBudgetError:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(reserve, range(30)))
        self.assertEqual(sum(value is not None for value in ids), 16)
        self.assertEqual(OddsStore(api_key='private-test-key').snapshot()['daily_used'], 16)

    def test_restart_preserves_ambiguous_reservations(self):
        self.store.reserve(3)
        restarted = OddsStore(api_key='private-test-key')
        self.assertEqual(restarted.snapshot()['cycle_used'], 3)
        with self.assertRaises(OddsBudgetError):
            restarted.reserve(14)

    def test_provider_reserve_prevents_spending_last_fifty(self):
        self.store.observe({'x-requests-used': '448', 'x-requests-remaining': '52'})
        with self.assertRaises(OddsBudgetError):
            self.store.reserve(3)
        self.assertIsInstance(self.store.reserve(2), str)

    def test_cycle_cap_is_independent_of_daily_cap(self):
        with patch.dict(os.environ, {'ODDS_CYCLE_CREDITS': '2'}):
            self.store.reserve(2)
            with self.assertRaises(OddsBudgetError):
                self.store.reserve(1)

    def test_empty_response_refunds_charge_and_reset_starts_new_cycle(self):
        charge = self.store.reserve(1)
        self.store.reconcile(charge, {'x-requests-last': '0'})
        self.assertEqual(self.store.snapshot()['cycle_used'], 0)
        self.store.observe({'x-requests-used': '150', 'x-requests-remaining': '350'})
        charge = self.store.reserve(2)
        self.store.reconcile(charge, {'x-requests-last': '2', 'x-requests-used': '152', 'x-requests-remaining': '348',
                                      'date': 'Wed, 30 Sep 2026 23:59:59 GMT'})
        self.store.observe({'x-requests-used': '0', 'x-requests-remaining': '500', 'date': 'Thu, 01 Oct 2026 00:00:01 GMT'})
        self.assertEqual(self.store.snapshot()['cycle_used'], 0)
        self.assertEqual(self.store.snapshot()['daily_used'], 2)

    def test_request_crossing_reset_counts_actual_in_new_cycle(self):
        self.store.observe({'x-requests-used': '100', 'x-requests-remaining': '400', 'date': 'Wed, 30 Sep 2026 23:59:59 GMT'})
        charge = self.store.reserve(3)
        self.store.reconcile(charge, {'x-requests-last': '3', 'x-requests-used': '3', 'x-requests-remaining': '497',
                                      'date': 'Thu, 01 Oct 2026 00:00:01 GMT'})
        self.assertEqual(self.store.snapshot()['cycle_used'], 3)
        self.assertEqual(self.store.snapshot()['provider_remaining'], 497)

    def test_ambiguous_reservation_survives_a_verified_reset(self):
        self.store.observe({'x-requests-used': '100', 'x-requests-remaining': '400', 'date': 'Wed, 30 Sep 2026 23:59:59 GMT'})
        self.store.reserve(3)
        self.store.observe({'x-requests-used': '0', 'x-requests-remaining': '500', 'date': 'Thu, 01 Oct 2026 00:00:01 GMT'})
        self.assertEqual(self.store.snapshot()['cycle_used'], 3)

    def test_stale_or_undated_usage_cannot_refill_budget(self):
        self.store.observe({'x-requests-used': '100', 'x-requests-remaining': '400', 'date': 'Thu, 01 Oct 2026 01:00:00 GMT'})
        for headers in ({'x-requests-used': '0', 'x-requests-remaining': '500'},
                        {'x-requests-used': '0', 'x-requests-remaining': '500', 'date': 'Thu, 01 Oct 2026 00:00:01 GMT'}):
            self.assertFalse(self.store.observe(headers))
            self.assertEqual(self.store.snapshot()['provider_remaining'], 400)

    def test_actual_cost_without_usage_decrements_remaining_once(self):
        self.store.observe({'x-requests-used': '448', 'x-requests-remaining': '52'})
        charge = self.store.reserve(2)
        self.store.reconcile(charge, {'x-requests-last': '2'})
        self.store.reconcile(charge, {'x-requests-last': '2'})
        self.assertEqual(self.store.snapshot()['provider_remaining'], 50)
        with self.assertRaises(OddsBudgetError):
            self.store.reserve(1)

    def test_repeated_usage_header_still_accounts_for_actual_cost(self):
        self.store.observe({'x-requests-used': '448', 'x-requests-remaining': '52'})
        charge = self.store.reserve(2)
        self.store.reconcile(charge, {'x-requests-last': '2', 'x-requests-used': '448', 'x-requests-remaining': '52'})
        self.assertEqual(self.store.snapshot()['provider_remaining'], 50)

    def test_invalid_cost_does_not_refund_and_unknown_headers_keep_reservation(self):
        for bad_cost in (True, -1, '1.5', 'NaN'):
            charge = self.store.reserve(1)
            self.store.reconcile(charge, {'x-requests-last': bad_cost})
        self.assertEqual(self.store.snapshot()['cycle_used'], 4)

    def test_bootstrap_honors_the_callers_remaining_deadline(self):
        with self.store.connection() as db:
            db.execute('update odds_meta set checked=0')
        bootstrap = Mock(status_code=200, headers={'x-requests-used': '0', 'x-requests-remaining': '500'})
        paid = Mock(headers={'x-requests-last': '1', 'x-requests-used': '1', 'x-requests-remaining': '499'})
        timeout_for = Mock(return_value=.25)
        with patch('requests.get', return_value=bootstrap) as get:
            metered_request(lambda: paid, 'private-test-key', 1, timeout_for=timeout_for)
        self.assertEqual(get.call_args.kwargs['timeout'], .25)
        timeout_for.assert_called_once_with(8)

    def test_unknown_usage_cannot_reserve(self):
        with self.assertRaises(OddsBudgetError):
            OddsStore(api_key='another-key').reserve(1)

    def test_lease_blocks_another_process_store_and_releases(self):
        other = OddsStore(api_key='private-test-key')
        with self.store.lease('board'):
            with self.assertRaises(OddsBudgetError):
                with other.lease('board'):
                    self.fail('duplicate lease')
        with other.lease('board'):
            pass

    def test_expired_lease_recovers_without_old_owner_deleting_new_owner(self):
        now = [1000]
        store = OddsStore(api_key='private-test-key', clock=lambda: now[0])
        old = store.lease('recover', seconds=1)
        old.__enter__()
        now[0] += 2
        new = store.lease('recover', seconds=90)
        new.__enter__()
        old.__exit__(None, None, None)
        with self.assertRaises(OddsBusyError):
            with store.lease('recover'):
                pass
        new.__exit__(None, None, None)

    def test_new_utc_day_resets_daily_limit_but_not_cycle_limit(self):
        now = [1791158399]  # A controlled clock, independent of real test time.
        store = OddsStore(api_key='clock-key', clock=lambda: now[0])
        store.observe({'x-requests-used': '0', 'x-requests-remaining': '500'})
        store.reserve(16)
        now[0] += 86400
        snapshot = store.snapshot()
        self.assertEqual(snapshot['daily_used'], 0)
        self.assertEqual(snapshot['cycle_used'], 16)

    def test_each_metered_attempt_reconciles_and_ambiguous_failure_is_kept(self):
        response = Mock(headers={'x-requests-last': '1', 'x-requests-used': '1', 'x-requests-remaining': '499'})
        self.assertIs(metered_request(lambda: response, 'private-test-key', 1), response)
        def failed():
            raise TimeoutError('ambiguous transport')
        with self.assertRaises(TimeoutError):
            metered_request(failed, 'private-test-key', 3)
        self.assertEqual(self.store.snapshot()['daily_used'], 4)

    def test_cached_payload_and_key_do_not_include_secret(self):
        self.store.cache('public-key', {'quotes': []}, 5)
        self.assertEqual(self.store.cached('public-key'), {'quotes': []})
        with open(self.path, 'rb') as stream:
            self.assertNotIn(b'private-test-key', stream.read())


class MarketBoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'ODDS_CACHE_PATH': os.path.join(self.temp.name, 'quotes.db'), 'ODDS_BUDGET_ENABLED': '0'})
        env.start(); self.addCleanup(env.stop)
        self.event = {'id': 'event-1', 'home_team': 'Denver Nuggets', 'away_team': 'Utah Jazz',
                      'commence_time': '2026-10-05T01:00:00Z'}
        self.updated = datetime.now(timezone.utc).isoformat()
        self.payload = {'id': 'event-1', 'bookmakers': [{'key': 'fanduel', 'markets': [
            {'key': 'player_rebounds', 'last_update': self.updated, 'outcomes': [
                {'description': 'Nikola Jokic', 'name': 'Over', 'point': 11.5, 'price': -110},
                {'description': 'Nikola Jokic', 'name': 'Under', 'point': 12.5, 'price': 120}]},
            {'key': 'h2h', 'last_update': self.updated, 'outcomes': [{'name': 'Denver Nuggets', 'price': -200}]},
            {'key': 'spreads', 'last_update': self.updated, 'outcomes': [{'name': 'Denver Nuggets', 'point': -5.5, 'price': -115}]}
        ]}]}
        self.loader = Mock()
        self.loader._get_odds_events.return_value = [self.event]
        self.loader._retry_http_get.return_value = Mock(json=lambda: self.payload)

    def board(self, **kwargs):
        return fetch_board(self.loader, 'key', 'DEN', 'UTA', '2026-10-04', 'basketball_nba_preseason', ('fanduel',), **kwargs)

    def test_side_prices_thresholds_and_moneyline_shape_are_preserved(self):
        quotes, coverage = normalize_board(self.payload, self.event, ('fanduel',), 'DEN', 'UTA')
        rebound = [q for q in quotes if q['market'] == 'player_rebounds']
        self.assertEqual([(q['selection'], q['line'], q['odds']) for q in rebound], [('OVER', 11.5, -110), ('UNDER', 12.5, 120)])
        self.assertIsNone(next(q for q in quotes if q['market'] == 'h2h')['line'])
        self.assertEqual(coverage['fanduel']['totals'], 'market_missing')

    def test_rebounds_only_fetch_shares_three_books_and_has_no_stats_dependency(self):
        first = self.board()
        second = self.board(refresh=True)
        self.assertEqual(first['status'], 'available')
        self.assertTrue(second['cached'])
        self.assertEqual(self.loader._retry_http_get.call_count, 1)
        params = self.loader._retry_http_get.call_args.kwargs['params']
        self.assertEqual(params['markets'], 'player_rebounds')
        self.assertEqual(set(params['bookmakers'].split(',')), {'fanduel', 'draftkings', 'betmgm'})
        self.loader.get_player_gamelog.assert_not_called()
        self.loader.get_team_roster.assert_not_called()
        self.assertEqual(first['quotes'][0]['sport'], 'basketball_nba_preseason')

    def test_game_markets_pack_is_shared_and_keeps_original_retrieval_time(self):
        self.loader._retry_http_get.return_value = Mock(json=lambda: [self.payload])
        result = self.board(group='game')
        self.assertEqual({q['market'] for q in result['quotes']}, {'spreads', 'h2h'})
        self.assertEqual(self.loader._retry_http_get.call_args.kwargs['params']['markets'], 'spreads,h2h,totals')
        self.assertEqual(self.board(group='game')['fetched_at'], result['fetched_at'])
        self.assertEqual(self.loader._retry_http_get.call_count, 1)

    def test_refresh_failure_keeps_original_quotes_and_marks_stale(self):
        first = self.board()
        store = OddsStore(api_key='key')
        with store.connection() as db:
            db.execute('update odds_cache set expires=0')
        self.loader._retry_http_get.side_effect = OSError('upstream private URL')
        result = self.board()
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['fetched_at'], first['fetched_at'])
        self.assertTrue(all(q['freshness'] == 'stale' for q in result['quotes']))
        self.assertNotIn('private', result['refresh_error'])

    def test_new_board_keeps_the_original_game_pack_expiry(self):
        self.loader._retry_http_get.return_value = Mock(json=lambda: [self.payload])
        original = self.board(group='game')
        store = OddsStore(api_key='key')
        key = 'game-pack:basketball_nba_preseason:2026-10-04'
        pack = store.cached(key)
        pack['cache_time'] -= 3600
        store.cache(key, pack, 82800)
        with store.connection() as db:
            db.execute("delete from odds_cache where cache_key like 'board:%'")
        result = self.board(group='game')
        self.assertEqual(result['fetched_at'], original['fetched_at'])
        with store.connection() as db:
            expiry = db.execute("select expires from odds_cache where cache_key like 'board:%'").fetchone()[0]
        self.assertAlmostEqual(expiry, pack['cache_time'] + 86400, delta=.1)
        self.assertEqual(self.loader._retry_http_get.call_count, 1)

    def test_different_games_cannot_duplicate_an_inflight_daily_pack(self):
        second_event = {**self.event, 'id': 'event-2', 'home_team': 'Boston Celtics', 'away_team': 'Dallas Mavericks'}
        second_payload = {'id': 'event-2', 'bookmakers': []}
        self.loader._get_odds_events.return_value = [self.event, second_event]
        entered, release = threading.Event(), threading.Event()
        def download(*args, **kwargs):
            entered.set()
            release.wait(2)
            return Mock(json=lambda: [self.payload, second_payload])
        self.loader._retry_http_get.side_effect = download
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.board, group='game')
            self.assertTrue(entered.wait(1))
            second = fetch_board(self.loader, 'key', 'BOS', 'DAL', '2026-10-04', 'basketball_nba_preseason', ('fanduel',), group='game')
            release.set()
            self.assertEqual(first.result()['status'], 'available')
        self.assertEqual(second['status'], 'request_in_progress')
        again = fetch_board(self.loader, 'key', 'BOS', 'DAL', '2026-10-04', 'basketball_nba_preseason', ('fanduel',), group='game')
        self.assertEqual(again['status'], 'empty')
        self.assertEqual(self.loader._retry_http_get.call_count, 1)

    def test_provider_empty_and_missing_book_are_distinct(self):
        self.payload['bookmakers'] = []
        result = self.board()
        self.assertEqual(result['status'], 'empty')
        self.assertEqual(result['coverage']['fanduel']['player_rebounds'], 'book_missing')

    def test_invalid_market_and_wrong_event_are_rejected(self):
        with self.assertRaises(ValueError):
            self.board(group='all')
        self.payload['id'] = 'another-event'
        self.assertEqual(self.board()['status'], 'provider_unavailable')


class LegacyMeteringTests(unittest.TestCase):
    def test_every_paid_retry_reserves_unique_markets_and_ceil_book_groups(self):
        from src.data_loader import NBADataLoader
        loader = NBADataLoader()
        response = Mock(status_code=200)
        with patch('src.odds_budget.metered_request', return_value=response) as meter:
            loader._retry_http_get('https://api.the-odds-api.com/v4/sports/basketball_nba/odds',
                                   params={'apiKey': 'key', 'markets': 'spreads,h2h,h2h',
                                           'bookmakers': ','.join(f'book-{index}' for index in range(11))})
        self.assertEqual(meter.call_args.args[2], 4)
        self.assertEqual(meter.call_args.kwargs['timeout_for'], loader._bounded_timeout)

    def test_budget_rejection_does_not_retry_or_fall_through_to_network(self):
        from src.data_loader import NBADataLoader
        loader = NBADataLoader()
        with patch('src.odds_budget.metered_request', side_effect=OddsBusyError('busy')) as meter, patch('requests.get') as get:
            with self.assertRaises(OddsBusyError):
                loader._retry_http_get('https://api.the-odds-api.com/v4/sports/basketball_nba/odds')
        meter.assert_called_once()
        get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
