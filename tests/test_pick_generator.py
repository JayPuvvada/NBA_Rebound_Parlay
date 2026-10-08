import multiprocessing
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pandas as pd

from src.data_loader import NBADataLoader, DataUnavailableError
from src.pick_generator import (assess_player, choose_profile, generate_picks, minutes_scenarios,
                                scenario_probabilities, _pipeline, empty_assessment, _history_entry, player_histories)


def history(count, minutes=20, rebounds=10, end='2026-10-03'):
    return pd.DataFrame([{'GAME_ID': f'{end}-{index}', 'GAME_DATE': str(day.date()),
                          'MIN': minutes, 'REB': rebounds}
                         for index, day in enumerate(pd.date_range(end=end, periods=count))],
                        columns=['GAME_ID', 'GAME_DATE', 'MIN', 'REB'])


def quote(side='OVER', line=1.5, odds=-110, **extra):
    return {'market': 'player_rebounds', 'selection': side, 'player': 'Test Player', 'team': None,
            'line': line, 'odds': odds, 'book': 'fanduel', 'source': 'the-odds-api',
            'event_id': 'event-1', 'updated_at': datetime.now(timezone.utc).isoformat(), **extra}


class FixtureLoader:
    season = '2026-27'

    def __init__(self, count=3, prior=False):
        self.frame = history(count, end='2026-04-01' if prior else '2026-10-03')
        self.status = None
        self.preseason = True

    def get_preseason_player_gamelog(self, *args, **kwargs):
        return self.frame

    def get_regular_player_gamelog(self, *args, **kwargs):
        return self.frame

    def get_team_id(self, name):
        return {'BOS': 1, 'DAL': 2}[name]

    def get_injury_report(self):
        return {'test player': self.status} if self.status else {}

    def get_injury_report_metadata(self):
        return {'status': 'available', 'stale': False, 'fetched_at': datetime.now(timezone.utc).isoformat()}

    def get_days_rest(self, *args, **kwargs):
        return 2

    def get_games_for_date_fresh(self, *args):
        return [{'home_id': 1, 'away_id': 2, 'status': 1, 'is_preseason': self.preseason}]


def hung_worker(request, key, deadline, output):
    output.put(('players', ['Done Player', 'Slow Player']))
    output.put(('assessment', {**empty_assessment('Done Player'), 'result_kind': 'no_pick', 'reason_code': 'no_edge'}))
    time.sleep(15)


def completed_worker(request, key, deadline, output):
    output.put(('players', ['Done Player']))
    output.put(('assessment', {**empty_assessment('Done Player'), 'result_kind': 'no_pick'}))
    output.put(('done', None))


def hung_history_worker(request, key, deadline, output):
    output.put(('history', {'kind': 'current_season', 'games': 8, 'status': 'available'}))
    time.sleep(15)


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.request = {'home': 'BOS', 'away': 'DAL', 'date': '2026-10-04',
                        'sport': 'basketball_nba_preseason', 'book': 'fanduel', 'minutes': {}}
        self.identity = {'name': 'Test Player', 'player_id': 1, 'team': 'BOS'}
        self.today = patch('src.pick_generator.eastern_today', return_value='2026-10-04')
        self.today.start()
        self.addCleanup(self.today.stop)

    def assess(self, current=3, prior=10, **kwargs):
        loader = kwargs.pop('loader', FixtureLoader(current))
        return assess_player(self.identity, kwargs.pop('quotes', [quote()]), self.request,
                             time.monotonic() + 10, loader=loader,
                             prior_loader=FixtureLoader(prior, prior=True), **kwargs)

    def test_profile_boundaries(self):
        prior = {'games': 10, 'total_minutes': 150, 'rebounds_per_minute': .5}
        current = {'games': 14, 'total_minutes': 200, 'rebounds_per_minute': .2}
        profile, rate, _ = choose_profile(current, prior)
        self.assertEqual(profile, 'early_regular')
        self.assertAlmostEqual(rate, .2 * 14 / 15 + .5 / 15)
        self.assertEqual(choose_profile({**current, 'games': 15}, {})[0], 'full_regular')
        for insufficient in ({**prior, 'games': 9}, {**prior, 'total_minutes': 149.9}):
            self.assertIsNone(choose_profile(current, insufficient)[0])
        self.assertEqual(choose_profile({'games': 3, 'total_minutes': 45, 'rebounds_per_minute': .3}, {}, True)[0], 'preseason')
        self.assertIsNone(choose_profile({'games': 2, 'total_minutes': 60}, {}, True)[0])
        self.assertIsNone(choose_profile({'games': 3, 'total_minutes': 44}, {}, True)[0])

    def test_minutes_clamped_scenarios_and_validation(self):
        self.assertEqual([s['minutes'] for s in minutes_scenarios(0, 'preseason')], [0, 0, 6])
        self.assertEqual([s['minutes'] for s in minutes_scenarios(48, 'early_regular')], [44, 48, 48])
        for invalid in (-1, 49, True, float('nan'), None):
            with self.assertRaises(ValueError):
                minutes_scenarios(invalid, 'preseason')

    def test_integer_line_push_and_zero_distribution(self):
        probabilities = scenario_probabilities(.3, minutes_scenarios(20, 'early_regular'), 6)
        self.assertGreater(probabilities['push_probability'], 0)
        self.assertAlmostEqual(sum(probabilities.values()), 1)
        self.assertEqual(scenario_probabilities(0, minutes_scenarios(0, 'preseason'), 0),
                         {'over_probability': 0, 'under_probability': 0, 'push_probability': 1})

    def test_same_day_and_dnp_are_excluded(self):
        loader = FixtureLoader(2)
        loader.frame = pd.concat([loader.frame, history(1, end='2026-10-04'), history(1, minutes=0, end='2026-10-01')])
        row = self.assess(loader=loader, prior=0)
        self.assertEqual(row['assumptions']['current_history']['games'], 2)
        self.assertEqual(row['reason_code'], 'insufficient_history')

    def test_experimental_candidate_never_actionable(self):
        row = self.assess()
        self.assertEqual(row['result_kind'], 'experimental_candidate')
        self.assertEqual(row['candidate_direction'], 'OVER')
        self.assertFalse(row['actionable'])
        self.assertIsNone(row['analysis']['direction'])
        self.assertEqual(row['analysis']['kelly_fraction'], 0)
        self.assertEqual(row['assumptions']['variance'], 'heuristic_only')

    def test_manual_minutes_allow_only_nonactionable_provider_backed_candidates(self):
        self.request['minutes'] = {'1': 20}
        row = self.assess()
        self.assertEqual(row['result_kind'], 'experimental_candidate')
        self.assertEqual(row['candidate_direction'], 'OVER')
        self.assertFalse(row['actionable'])
        self.assertEqual(row['minutes'], {'value': 20, 'source': 'manual'})
        self.assertTrue(any('manual assumption' in item for item in row['limitations']))
        manual_quote = self.assess(quotes=[quote(source='manual', event_id=None)])
        self.assertEqual(manual_quote['reason_code'], 'quote_not_provider_verified')
        self.assertIsNone(manual_quote['candidate_direction'])
        row = self.assess(quotes=[quote(updated_at='2020-01-01T00:00:00Z')])
        self.assertEqual(row['reason_code'], 'stale_quote')
        no_edge = self.assess(quotes=[quote(line=99.5)])
        self.assertEqual(no_edge['result_kind'], 'no_pick')
        self.assertIsNone(no_edge['candidate_direction'])
        loader = FixtureLoader()
        loader.get_games_for_date_fresh = lambda *args: [{'home_id':1, 'away_id':2, 'status':3, 'is_preseason':True}]
        postgame = self.assess(loader=loader)
        self.assertEqual(postgame['reason_code'], 'game_not_verified_pregame')
        self.assertIsNone(postgame['candidate_direction'])

    def test_first_preseason_requires_manual_minutes(self):
        row = self.assess(current=0)
        self.assertEqual(row['result_kind'], 'needs_input')
        self.assertIsNone(row['projection'])
        self.request['minutes'] = {'1': 20}
        row = self.assess(current=0)
        self.assertEqual(row['result_kind'], 'experimental_candidate')
        self.assertEqual(row['minutes']['source'], 'manual')
        self.assertFalse(row['actionable'])

    def test_available_preseason_fallback_without_prior(self):
        row = self.assess(prior=0)
        self.assertEqual(row['assumptions']['rate_source'], 'current_preseason')

    def test_one_sided_quote_is_evaluated_at_own_line_and_price(self):
        row = self.assess(quotes=[quote('UNDER', 40, 200)])
        self.assertEqual(row['candidate_direction'], 'UNDER')
        self.assertEqual(row['quote']['line'], 40)
        self.assertEqual(row['analysis']['american_odds'], 200)

    def test_no_quote_and_failure_are_unavailable(self):
        self.assertEqual(self.assess(quotes=[])['reason_code'], 'no_quote')
        loader = FixtureLoader()
        loader.get_preseason_player_gamelog = Mock(side_effect=DataUnavailableError('timeout'))
        self.assertEqual(self.assess(loader=loader)['reason_code'], 'player_data_unavailable')

    def test_known_out_is_excluded(self):
        loader = FixtureLoader()
        loader.status = 'Out'
        self.assertEqual(self.assess(loader=loader)['reason_code'], 'player_out')

    def test_unverifiable_injury_status_is_not_current_out(self):
        now = datetime.now(timezone.utc)
        for metadata in (
            {'status': 'available', 'stale': True, 'fetched_at': now.isoformat()},
            {'status': 'degraded', 'stale': False, 'fetched_at': now.isoformat()},
            {'status': 'available', 'stale': False, 'fetched_at': (now-timedelta(hours=1)).isoformat()},
            {'status': 'available', 'stale': False, 'fetched_at': (now+timedelta(hours=1)).isoformat()},
            {'status': 'available', 'stale': False, 'fetched_at': 'invalid'},
            {'status': 'available', 'stale': False, 'fetched_at': '2026-10-05T12:00:00'},
        ):
            with self.subTest(metadata=metadata):
                loader = FixtureLoader()
                loader.status = 'Out'
                loader.get_injury_report_metadata = Mock(return_value=metadata)
                row = self.assess(loader=loader)
                self.assertNotEqual(row['reason_code'], 'player_out')
                self.assertTrue(any('Availability is unconfirmed' in item for item in row['limitations']))

    def test_fresh_listed_status_does_not_claim_healthy_roster(self):
        loader = FixtureLoader()
        loader.status = 'Questionable'
        row = self.assess(loader=loader)
        self.assertNotEqual(row['reason_code'], 'player_out')
        self.assertTrue(any('Availability is unconfirmed' in item for item in row['limitations']))

    def test_full_model_safety_no_pick_never_falls_back(self):
        self.request['sport'] = 'basketball_nba'
        loader = FixtureLoader(15)
        loader.preseason = False
        engineer = Mock()
        engineer.compute_composite_projection.return_value = {
            'projection': 10, 'components': {'Proj Minutes': 30}, 'metadata': {'prediction_eligible': False}}
        row = self.assess(loader=loader, engineer=engineer)
        self.assertEqual(row['profile'], 'full_regular')
        self.assertEqual(row['reason_code'], 'primary_safety_veto')
        self.assertFalse(row['actionable'])

    def test_full_model_uses_existing_price_gates_and_exact_probabilities(self):
        from src.model import ReboundSimulator
        self.request['sport'] = 'basketball_nba'
        loader = FixtureLoader(15)
        loader.preseason = False
        projection = {'projection': 10, 'team_id': 1, 'components': {'Proj Minutes': 30},
                      'metadata': {'prediction_eligible': True},
                      'trend_data': [{'rebounds': 10, 'date': f'2026-09-{day:02d}'} for day in range(1, 16)]}
        engineer = Mock()
        engineer.compute_composite_projection.return_value = projection
        row = self.assess(loader=loader, engineer=engineer)
        self.assertEqual(row['result_kind'], 'model_pick')
        self.assertTrue(row['actionable'])
        simulator = ReboundSimulator(num_simulations=1)
        probabilities = simulator.get_probabilities(simulator.simulate(projection), 1.5)
        self.assertEqual(row['analysis']['over_probability'], probabilities['over_probability'])
        self.assertEqual(row['analysis']['direction'], 'OVER')

    def test_reduced_only_when_full_inputs_unavailable(self):
        self.request['sport'] = 'basketball_nba'
        loader = FixtureLoader(15)
        loader.preseason = False
        engineer = Mock()
        engineer.compute_composite_projection.return_value = {'error': 'Usable player statistics are unavailable'}
        row = self.assess(loader=loader, engineer=engineer)
        self.assertEqual(row['profile'], 'reduced_regular')
        self.assertFalse(row['actionable'])
        engineer.compute_composite_projection.return_value = {'error': 'Player is OUT or injured'}
        row = self.assess(loader=loader, engineer=engineer)
        self.assertEqual(row['reason_code'], 'primary_model_veto')

    def test_live_or_wrong_phase_prevents_candidate(self):
        loader = FixtureLoader()
        loader.preseason = False
        self.assertEqual(self.assess(loader=loader)['reason_code'], 'game_not_verified_pregame')

    def test_board_filters_book_market_and_retry_players_before_history(self):
        loader = Mock()
        loader.get_analysis_roster.return_value = {'players': []}
        board = {'quotes': [quote(), quote(player='Other Player'), quote(book='draftkings'),
                            quote(market='h2h')], 'event_id': 'event-1'}
        self.request['players'] = ['Other Player']
        emitted = []
        with patch('src.pick_generator._loader', return_value=loader), patch('src.pick_generator.fetch_board', return_value=board):
            _pipeline(self.request, '', time.monotonic() + 5, emitted.append)
        self.assertEqual(emitted[0], ('players', ['Other Player']))
        self.assertEqual(next(value for kind, value in emitted if kind == 'assessment')['reason_code'], 'roster_identity_unverified')

    def test_grouped_quotes_keep_canonical_subject_across_provider_spelling_variants(self):
        loader = Mock()
        loader.get_analysis_roster.side_effect = [
            {'players':[{'name':'Nikola Jokic','player_id':1}], 'limitations':[]},
            {'players':[], 'limitations':[]},
        ]
        board = {'quotes':[quote(player='Nikola Jokic'),quote(player='Nikola Jokić',side='UNDER')], 'event_id':'event-1'}
        with patch('src.pick_generator._loader',return_value=loader), patch('src.pick_generator.fetch_board',return_value=board), patch('src.pick_generator.assess_player',return_value=empty_assessment('Nikola Jokic')) as assess:
            _pipeline(self.request,'',time.monotonic()+5,lambda value:None)
        self.assertEqual([q['player'] for q in assess.call_args.args[1]],['Nikola Jokic','Nikola Jokic'])

    def test_supervisor_stops_expired_worker_and_returns_named_partial(self):
        before = {p.pid for p in multiprocessing.active_children()}
        started = time.monotonic()
        result = generate_picks(self.request, budget_seconds=2, worker=hung_worker)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(result['coverage'], {'total': 2, 'completed': 1, 'incomplete': ['Slow Player']})
        self.assertEqual(result['status'], 'partial')
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before)

    def test_supervisor_completed_response(self):
        result = generate_picks(self.request, budget_seconds=5, worker=completed_worker)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['coverage']['completed'], 1)

    def test_research_preserves_completed_source_at_deadline(self):
        result = player_histories('Test Player', '2026-10-04', budget_seconds=2, worker=hung_history_worker)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['reason_code'], 'deadline_exceeded')
        self.assertEqual(result['histories'][0]['games'], 8)

    def test_research_completion_distinguishes_source_failure_from_valid_empty(self):
        available = {'kind':'current_season', 'status':'available', 'games':8}
        failed = {'kind':'prior_season', 'status':'unavailable', 'games':0}
        empty = {'kind':'prior_season', 'status':'empty', 'games':0}
        for rows, expected in [([available,failed],'partial'), ([failed,failed],'unavailable'), ([available,empty],'complete')]:
            with self.subTest(expected=expected), patch('src.pick_generator._supervise', return_value=([('history',row) for row in rows],True)):
                result = player_histories('Test Player','2026-10-04')
                self.assertEqual(result['status'],expected)
                self.assertEqual(result['histories'],rows)
        with patch('src.pick_generator._supervise', return_value=([('error','player_identity_unverified')],True)):
            result = player_histories('Unknown','2026-10-04')
            self.assertEqual(result['status'],'unavailable')
            self.assertEqual(result['reason_code'],'player_identity_unverified')

    def test_research_offline_summaries_have_explicit_scope_and_push_counts(self):
        loader = FixtureLoader(10)
        loader.get_player_id = lambda name: 1
        loader.set_request_budget = lambda seconds: None
        sink = Mock()
        with patch('src.pick_generator._loader', return_value=loader):
            _history_entry({'player': 'Test Player', 'date': '2026-10-04', 'preseason': False, 'line': 10},
                           '', time.monotonic() + 5, sink)
        summaries = [call.args[0][1] for call in sink.put.call_args_list if call.args[0][0] == 'history']
        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]['scope'], 'regular_season')
        self.assertEqual(summaries[0]['last_10']['rebounds'], 10)
        self.assertEqual(summaries[0]['observed_pushes']['pushes'], 10)


class ScopedHistoryTests(unittest.TestCase):
    def test_regular_history_explicit_prior_season_and_cutoff(self):
        loader = NBADataLoader(season='2025-26')
        response = Mock()
        response.get_data_frames.return_value = [history(2, end='2026-10-04')]
        with patch.object(loader, '_retry_api_call', return_value=response) as called:
            frame = loader.get_regular_player_gamelog(987654321, as_of='2026-10-04')
        self.assertEqual(called.call_args.kwargs['season'], '2025-26')
        self.assertEqual(called.call_args.kwargs['season_type_all_star'], 'Regular Season')
        self.assertEqual(len(frame), 1)

    def test_espn_fallback_is_regular_scoped(self):
        loader = NBADataLoader(season='2025-26')
        with patch.object(loader, '_retry_api_call', side_effect=DataUnavailableError('offline')), \
                patch.object(loader, '_espn_preseason_player_gamelog', return_value=history(3)) as fallback:
            frame = loader.get_regular_player_gamelog(987654322, as_of='2026-10-04')
        self.assertTrue(fallback.call_args.kwargs['regular_only'])
        self.assertEqual(frame.attrs['season_type'], 'Regular Season')

    def test_espn_regular_scope_excludes_postseason_and_preseason(self):
        loader = NBADataLoader(season='2025-26')
        groups, events = [], {}
        for index, phase in enumerate(('regular season', 'postseason', 'preseason')):
            event_id = f'event-{index}'
            groups.append({'displayName': f'2025-26 {phase}',
                           'categories': [{'events': [{'eventId': event_id, 'stats': [20, index + 5]}]}]})
            events[event_id] = {'gameDate': '2026-04-01T23:00:00Z', 'team': {'abbreviation': 'BOS'},
                                'opponent': {'abbreviation': 'DAL'}, 'atVs': 'vs'}
        payload = {'names': ['minutes', 'totalRebounds'], 'seasonTypes': groups, 'events': events}
        with patch.object(loader, '_espn_player_resource', return_value=({}, payload)):
            frame = loader._espn_preseason_player_gamelog(1, '2025-26', regular_only=True)
        self.assertEqual(list(frame['REB']), [5])


class GeneratorRouteTests(unittest.TestCase):
    def setUp(self):
        import app
        self.app_module = app
        app.app.testing = True
        self.client = app.app.test_client()
        self.body = {'home': 'BOS', 'away': 'DAL', 'date': '2026-10-04', 'book': 'fanduel'}

    def test_generation_validation_precedes_any_provider_work(self):
        for invalid in ({'minutes': {'1': True}}, {'minutes': {'1': 49}}, {'players': [1]},
                        {'book': 'unknown'}, {'sport': 'football_nfl'}, {'away': 'BOS'}):
            with self.subTest(invalid=invalid), patch.object(self.app_module, 'generate_picks') as generate:
                response = self.client.post('/generate-picks', json={**self.body, **invalid})
                self.assertEqual(response.status_code, 400)
                generate.assert_not_called()

    def test_valid_request_passes_scoped_retry_and_minutes(self):
        with patch.object(self.app_module, 'generate_picks', return_value={'status': 'complete'}) as generate:
            response = self.client.post('/generate-picks', json={**self.body, 'minutes': {'1': 0}, 'players': ['Test Player']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(generate.call_args.args[0]['minutes'], {'1': 0})
        self.assertEqual(generate.call_args.args[0]['players'], ['Test Player'])

    def test_history_uses_bounded_service(self):
        with patch.object(self.app_module, 'player_histories', return_value={'histories': [], 'status': 'partial'}) as histories:
            response = self.client.get('/player-history?player=Test+Player&date=2026-10-04&preseason=true&line=6')
        self.assertEqual(response.status_code, 200)
        histories.assert_called_once_with('Test Player', '2026-10-04', True, 6)


if __name__ == '__main__':
    unittest.main()
