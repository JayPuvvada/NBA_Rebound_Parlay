import os
import sys
import unittest
from unittest.mock import Mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.features import (
    FeatureEngineer,
    _normalize_position,
    _parse_height_inches,
    _projection_safety_context,
)


class HeightParsingTest(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(_parse_height_inches("6-10"), 82)
        self.assertEqual(_parse_height_inches("7-0"), 84)
        self.assertEqual(_parse_height_inches("5-11"), 71)

    def test_malformed_returns_default(self):
        self.assertEqual(_parse_height_inches("6ft10in", default=72), 72)
        self.assertEqual(_parse_height_inches("", default=72), 72)
        self.assertEqual(_parse_height_inches(None, default=72), 72)
        self.assertEqual(_parse_height_inches(6.10, default=72), 72)

    def test_custom_default(self):
        self.assertEqual(_parse_height_inches("bad", default=80), 80)


class PositionNormalizationTest(unittest.TestCase):
    def test_primary_position_is_respected(self):
        self.assertEqual(_normalize_position('Center-Forward'), 'C')
        self.assertEqual(_normalize_position('Forward-Center'), 'F')
        self.assertEqual(_normalize_position('G-F'), 'G')
        self.assertEqual(_normalize_position('Guard'), 'G')


class PlayerStatsTest(unittest.TestCase):
    def test_dnp_variance_rate_sampling_and_trend_order(self):
        class Loader:
            def __init__(self):
                self.requested_as_of = None

            def get_player_gamelog(self, _player_id, as_of=None):
                self.requested_as_of = as_of
                return pd.DataFrame({
                    'GAME_DATE': ['JAN 01, 2025', 'JAN 04, 2025', 'JAN 03, 2025', 'JAN 02, 2025'],
                    'MIN': ['30:00', '6:00', '4:00', '0:00'],
                    'OREB': [2, 1, 0, 0],
                    'DREB': [8, 1, 1, 0],
                    'REB': [10, 2, 1, 0],
                    'MATCHUP': ['BOS vs. LAL', 'BOS vs. PHI', 'BOS @ NYK', 'BOS vs. MIA'],
                    'TEAM_ID': [1, 1, 1, 1],
                })

            def get_common_player_info(self, _player_id):
                return pd.DataFrame([{
                    'DISPLAY_FIRST_LAST': 'Example Center',
                    'POSITION': 'Center-Forward',
                    'TEAM_ID': 1,
                }])

        loader = Loader()
        stats = FeatureEngineer(loader).get_player_stats(
            9, opponent_abbrev='LAL', as_of_date='2025-01-05'
        )

        self.assertEqual(loader.requested_as_of, '2025-01-05')
        self.assertEqual(stats['position'], 'C')
        self.assertAlmostEqual(stats['dnp_rate'], 1 / 4)
        self.assertAlmostEqual(stats['reb_variance'], pd.Series([10.0, 2.0, 1.0]).var())
        self.assertEqual(stats['variance_sample_size'], 3)
        self.assertEqual(stats['rate_sample_size'], 2)  # four-minute game excluded from rate
        self.assertAlmostEqual(stats['season_oreb_rate'], 3 / 36)
        self.assertEqual([g['date'] for g in stats['last_10_games']], [
            'JAN 01, 2025', 'JAN 03, 2025', 'JAN 04, 2025'
        ])
        self.assertEqual(stats['trend_order'], 'oldest_to_newest')

    def test_historical_team_comes_from_latest_matchup_not_current_info(self):
        class Loader:
            def get_player_gamelog(self, _player_id, as_of=None):
                return pd.DataFrame({
                    'GAME_DATE': ['JAN 10, 2025'], 'MIN': [30],
                    'OREB': [2], 'DREB': [6], 'REB': [8],
                    'MATCHUP': ['BOS @ NYK'],
                })

            def get_common_player_info(self, _player_id):
                # Simulates a player traded after the forecast date.
                return pd.DataFrame([{
                    'DISPLAY_FIRST_LAST': 'Traded Player',
                    'POSITION': 'Forward', 'TEAM_ID': 999,
                }])

            def get_team_id(self, abbreviation):
                return {'BOS': 1}.get(abbreviation)

        stats = FeatureEngineer(Loader()).get_player_stats(
            8, as_of_date='2025-01-11'
        )
        self.assertEqual(stats['team_id'], 1)
        self.assertEqual(stats['team_abbreviation'], 'BOS')
        self.assertEqual(stats['team_source'], 'newest pre-cutoff gamelog MATCHUP')


class MatchupContextTest(unittest.TestCase):
    def test_dashboard_inputs_receive_as_of_and_source_is_truthful(self):
        class Loader:
            def __init__(self):
                self.calls = []

            def get_team_stats(self, as_of=None):
                self.calls.append(('base', as_of))
                return pd.DataFrame([
                    {'TEAM_ID': 1, 'FG_PCT': .46, 'FGA': 88, 'FG3A': 35},
                    {'TEAM_ID': 2, 'FG_PCT': .48, 'FGA': 90, 'FG3A': 42},
                ])

            def get_team_advanced_stats(self, as_of=None):
                self.calls.append(('advanced', as_of))
                return pd.DataFrame([
                    {'TEAM_ID': 1, 'PACE': 99}, {'TEAM_ID': 2, 'PACE': 101},
                ])

            def get_opponent_stats_per_game(self, as_of=None):
                self.calls.append(('opponent', as_of))
                return pd.DataFrame([
                    {'TEAM_ID': 1, 'OPP_OREB': 10, 'OPP_DREB': 33, 'OPP_FGA': 88, 'OPP_FG3A': 35},
                    {'TEAM_ID': 2, 'OPP_OREB': 12, 'OPP_DREB': 35, 'OPP_FGA': 90, 'OPP_FG3A': 39},
                ])

        loader = Loader()
        context = FeatureEngineer(loader).get_matchup_context(
            1, 2, as_of_date='2025-01-15'
        )
        self.assertEqual(set(loader.calls), {
            ('base', '2025-01-15'),
            ('advanced', '2025-01-15'),
            ('opponent', '2025-01-15'),
        })
        self.assertAlmostEqual(context['opp_oreb_allowed'], 12 * 100 / 101)
        self.assertEqual(context['opp_oreb_allowed_raw'], 12)
        self.assertFalse(context['is_position_level_dvp'])
        self.assertIn('pace-normalized', context['opponent_rebound_source'])

    def test_rebound_environment_removes_per_game_pace_double_count(self):
        class Loader:
            def get_team_stats(self, as_of=None):
                return pd.DataFrame([
                    {'TEAM_ID': 1, 'FG_PCT': .47},
                    {'TEAM_ID': 2, 'FG_PCT': .47},
                ])

            def get_team_advanced_stats(self, as_of=None):
                return pd.DataFrame([
                    {'TEAM_ID': 1, 'PACE': 90},
                    {'TEAM_ID': 2, 'PACE': 110},
                ])

            def get_opponent_stats_per_game(self, as_of=None):
                # Both teams allow exactly 0.10 OREB and 0.33 DREB per pace unit.
                return pd.DataFrame([
                    {'TEAM_ID': 1, 'OPP_OREB': 9, 'OPP_DREB': 29.7},
                    {'TEAM_ID': 2, 'OPP_OREB': 11, 'OPP_DREB': 36.3},
                ])

        context = FeatureEngineer(Loader()).get_matchup_context(1, 2)
        self.assertAlmostEqual(context['opp_oreb_allowed'], 10.0)
        self.assertAlmostEqual(context['opp_dreb_allowed'], 33.0)
        self.assertAlmostEqual(context['league_avg_oreb_allowed'], 10.0)
        self.assertAlmostEqual(context['league_avg_dreb_allowed'], 33.0)

    def test_team_signal_is_shrunk_by_positional_exposure(self):
        engineer = FeatureEngineer(Mock())
        center = engineer.get_opponent_rebound_environment_multiplier('C', 12, 10)
        guard = engineer.get_opponent_rebound_environment_multiplier('G', 12, 10)
        self.assertGreater(center, guard)
        self.assertLessEqual(center, 1.08)
        self.assertGreater(guard, 1.0)


class ProjectionSafetyTest(unittest.TestCase):
    @staticmethod
    def _configured_engineer(loader):
        loader.get_team_id.return_value = 2
        loader.get_common_player_info.return_value = pd.DataFrame()
        engineer = FeatureEngineer(loader)
        engineer.get_player_stats = Mock(return_value={
            'player_name': 'A Player', 'position': 'C', 'team_id': 1,
            'season_oreb_rate': .08, 'season_dreb_rate': .22,
            'recent_oreb_rate': .10, 'recent_dreb_rate': .25,
            'opp_oreb_rate': .12, 'opp_dreb_rate': .27,
            'season_min_avg': 30, 'last_10_min': 32,
            'minutes_trend_slope': 2, 'games_played': 50, 'dnp_rate': 0,
            'data_cutoff': 'latest available', 'trend_order': 'oldest_to_newest',
            'rate_sample_size': 45, 'variance_sample_size': 50,
        })
        engineer.get_matchup_context = Mock(return_value={
            'team_pace': 90, 'opp_pace': 110, 'league_avg_pace': 100,
            'team_fg_pct': .40, 'opp_fg_pct': .40, 'league_avg_fg_pct': .48,
            'team_fg_pct_allowed': .40, 'opp_fg_pct_allowed': .40,
            'opp_3par': .50, 'opp_oreb_allowed': 14, 'opp_dreb_allowed': 38,
            'league_avg_oreb_allowed': 10.5, 'league_avg_dreb_allowed': 33.5,
            'opp_def_3par': .50, 'league_avg_def_3par': .40,
            'opponent_rebound_source': 'team-level opponent rebounds allowed per game',
        })
        engineer.adjust_minutes_for_injuries = Mock(return_value=(31.0, {
            'player_status': 'Active', 'out_teammates': [], 'minutes_added': 0.0,
        }))
        engineer.get_cannibalization_factor = Mock(return_value=1.0)
        return engineer

    def test_historical_injury_list_never_uses_current_scrape(self):
        loader = Mock()
        result = FeatureEngineer(loader).get_team_injury_list(1, as_of_date='2020-01-01')
        self.assertEqual(result, [])
        loader.get_injury_report.assert_not_called()
        loader.get_team_roster.assert_not_called()

    def test_projection_has_bounded_context_and_explicit_metadata(self):
        loader = Mock()
        engineer = self._configured_engineer(loader)

        result = engineer.compute_projection(
            1, 'LAL', home_game=True, as_of_date='2020-01-10'
        )

        self.assertNotIn('error', result)
        self.assertLessEqual(result['components']['Env Mult (Final)'], 1.10)
        self.assertEqual(result['components']['Pace'], 1.06)
        self.assertEqual(result['components']['Miss Matchup'], 1.0)
        self.assertIn('Opp Rebound Environment', result['components'])
        self.assertFalse(result['metadata']['is_position_level_dvp'])
        self.assertTrue(result['metadata']['historical_mode'])
        self.assertFalse(result['metadata']['live_injuries_applied'])
        self.assertEqual(result['metadata']['pace_baseline'], 'player team season pace')
        self.assertFalse(result['data_freshness']['prediction_eligible'])
        self.assertEqual(result['data_freshness']['injuries']['status'], 'disabled')
        self.assertEqual(result['data_freshness']['season'], '2019-20')

    def test_near_term_eligibility_requires_acceptable_injury_status(self):
        for status in ('available', 'degraded'):
            with self.subTest(status=status):
                loader = Mock()
                loader.get_injury_report_metadata.return_value = {
                    'status': status,
                    'source': (
                        'live_scrape' if status == 'available'
                        else 'bounded_stale_disk_cache'
                    ),
                    'fetched_at': '2026-09-04T12:00:00+00:00',
                    'entry_count': 25,
                    'stale': status == 'degraded',
                }
                result = self._configured_engineer(loader).compute_projection(1, 'LAL')

                self.assertTrue(result['metadata']['prediction_eligible'])
                self.assertTrue(result['metadata']['injury_status_acceptable'])
                self.assertTrue(result['data_freshness']['prediction_eligible'])
                self.assertEqual(result['data_freshness']['limitations'], [])

        loader = Mock()
        loader.get_injury_report_metadata.return_value = {
            'status': 'unavailable', 'source': None, 'fetched_at': None,
            'entry_count': 0, 'stale': None,
        }
        result = self._configured_engineer(loader).compute_projection(1, 'LAL')

        self.assertFalse(result['metadata']['prediction_eligible'])
        self.assertFalse(result['metadata']['injury_status_acceptable'])
        self.assertFalse(result['data_freshness']['prediction_eligible'])
        self.assertIn('diagnostic-only', result['metadata']['limitations'][0])

        # "Degraded" alone is not enough: a suspiciously incomplete live scrape
        # is distinct from the loader's explicitly bounded stale-cache fallback.
        loader.get_injury_report_metadata.return_value = {
            'status': 'degraded', 'source': 'cbs',
            'fetched_at': '2026-09-04T12:00:00+00:00',
            'entry_count': 2, 'stale': False,
        }
        result = self._configured_engineer(loader).compute_projection(1, 'LAL')
        self.assertFalse(result['metadata']['prediction_eligible'])
        self.assertIn('diagnostic-only', result['metadata']['limitations'][0])

    def test_missing_or_malformed_injury_metadata_is_diagnostic_only(self):
        class LoaderWithoutMetadata:
            pass

        missing = _projection_safety_context(LoaderWithoutMetadata(), None)
        self.assertFalse(missing['prediction_eligible'])
        self.assertEqual(missing['injury_freshness']['status'], 'unknown')
        self.assertIn('diagnostic-only', missing['limitations'][0])

        malformed_loader = Mock()
        malformed_loader.get_injury_report_metadata.return_value = Mock()
        malformed = _projection_safety_context(malformed_loader, None)
        self.assertFalse(malformed['prediction_eligible'])
        self.assertEqual(malformed['injury_freshness']['status'], 'unknown')

    def test_projection_rejects_non_finite_inputs(self):
        engineer = FeatureEngineer(Mock())
        self.assertIn('error', engineer.compute_projection(1, 'LAL', spread=float('nan')))
        self.assertIn('error', engineer.compute_projection(1, 'LAL', manual_minutes=0))
        self.assertIn('error', engineer.compute_projection(1, 'LAKERS'))

    def test_summary_uses_newest_end_of_chronological_trend(self):
        engineer = FeatureEngineer(Mock())
        trend = [
            {'rebounds': 20} for _ in range(5)
        ] + [
            {'rebounds': 2} for _ in range(5)
        ]
        summary = engineer.generate_pick_summary({
            'player': 'A Player', 'projection': 8, 'components': {},
            'tier': 'PLAY', 'direction': 'UNDER', 'confidence': .60,
            'edge': .05, 'ev_roi': .04, 'trend_data': trend,
        }, line=8.5)
        self.assertIn('recent cold stretch', summary)
        self.assertNotIn('recent hot stretch', summary)

    def test_summary_does_not_call_probability_edge_expected_value(self):
        summary = FeatureEngineer(Mock()).generate_pick_summary({
            'player': 'A Player', 'projection': 8, 'components': {},
            'tier': 'NO_PRICE', 'direction': 'NO BET', 'confidence': .70,
            'edge': .20, 'ev_roi': None, 'trend_data': [],
        }, line=7.5)
        self.assertIn('Recommendation: NO BET', summary)
        self.assertNotIn('Expected Value', summary)


if __name__ == '__main__':
    unittest.main()
