import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.recommendation import (
    weighted_hit_rate, tier_from_signals, edge_from_odds,
    MIN_TREND_GAMES, MIN_TIER_PROJECTION,
)


def _games(rebs):
    return [{'rebounds': r, 'date': f'g{i}', 'opponent': 'XXX'} for i, r in enumerate(rebs)]


class WeightedHitRateTest(unittest.TestCase):
    def test_all_hits_over(self):
        rate, n = weighted_hit_rate(_games([10, 11, 12, 13, 14, 15]), line=9.5, direction='OVER')
        self.assertAlmostEqual(rate, 1.0)
        self.assertEqual(n, 6)

    def test_all_miss(self):
        rate, _ = weighted_hit_rate(_games([5, 6, 4, 7, 3, 5]), line=9.5, direction='OVER')
        self.assertAlmostEqual(rate, 0.0)

    def test_recent_weighted_higher(self):
        rate, _ = weighted_hit_rate(_games([3, 3, 3, 15, 15, 15]), line=9.5, direction='OVER')
        self.assertGreater(rate, 0.5)

    def test_recent_weighted_lower(self):
        rate, _ = weighted_hit_rate(_games([15, 15, 15, 3, 3, 3]), line=9.5, direction='OVER')
        self.assertLess(rate, 0.5)

    def test_empty(self):
        rate, n = weighted_hit_rate([], line=9.5, direction='OVER')
        self.assertEqual(rate, 0.0)
        self.assertEqual(n, 0)

    def test_none_line(self):
        rate, n = weighted_hit_rate(_games([10, 11, 12]), line=None, direction='OVER')
        self.assertEqual(rate, 0.0)


class TierTest(unittest.TestCase):
    # ── thresholds raised to 68 / 62 / 58 ─────────────────────────────────────

    def test_strong_play(self):
        tier, color = tier_from_signals(0.70, 'OVER', 9.5, 6.0, 0.5, 10, mean_proj=10.0)
        self.assertEqual(tier, 'STRONG PLAY')
        self.assertEqual(color, 'green')

    def test_old_threshold_no_longer_strong_play(self):
        # 0.64 was STRONG PLAY under old threshold (0.635), should now be PLAY
        tier, _ = tier_from_signals(0.64, 'OVER', 9.5, 6.0, 0.5, 10, mean_proj=10.0)
        self.assertNotEqual(tier, 'STRONG PLAY')

    def test_play(self):
        tier, _ = tier_from_signals(0.64, 'OVER', 9.5, 6.0, 0.5, 10, mean_proj=10.0)
        self.assertEqual(tier, 'PLAY')

    def test_old_play_threshold_now_lean_or_avoid(self):
        # 0.57 was PLAY under old threshold (0.585), should now be LEAN or AVOID
        tier, _ = tier_from_signals(0.57, 'OVER', 9.5, 6.0, 0.5, 10, mean_proj=10.0)
        self.assertIn(tier, ('LEAN', 'AVOID'))

    def test_safe_play_when_line_below_floor(self):
        tier, color = tier_from_signals(0.56, 'OVER', line=7.0, floor_val=8.0,
                                        hit_rate=0.3, n_games=10, mean_proj=8.0)
        self.assertEqual(tier, 'SAFE PLAY')
        self.assertEqual(color, 'blue')

    def test_trend_lean_requires_min_games(self):
        tier, _ = tier_from_signals(0.52, 'OVER', 9.5, 6.0, hit_rate=0.80,
                                    n_games=MIN_TREND_GAMES - 1, mean_proj=10.0)
        self.assertNotEqual(tier, 'TREND LEAN')

    def test_trend_lean_hit_rate_raised_to_72pct(self):
        # 0.71 was enough under old threshold (0.70), now needs 0.72
        tier, _ = tier_from_signals(0.52, 'OVER', 9.5, 6.0, hit_rate=0.71,
                                    n_games=MIN_TREND_GAMES, mean_proj=10.0)
        self.assertNotEqual(tier, 'TREND LEAN')

    def test_trend_lean_with_new_threshold(self):
        tier, color = tier_from_signals(0.52, 'OVER', 9.5, 6.0, hit_rate=0.72,
                                        n_games=MIN_TREND_GAMES, mean_proj=10.0)
        self.assertEqual(tier, 'TREND LEAN')
        self.assertEqual(color, 'purple')

    def test_lean(self):
        tier, _ = tier_from_signals(0.59, 'UNDER', 9.5, 6.0, 0.4, 10, mean_proj=10.0)
        self.assertEqual(tier, 'LEAN')

    def test_avoid(self):
        tier, _ = tier_from_signals(0.51, 'OVER', 9.5, 6.0, 0.4, 10, mean_proj=10.0)
        self.assertEqual(tier, 'AVOID')

    # ── LOW_VOLUME gate ────────────────────────────────────────────────────────

    def test_low_volume_gate_blocks_tier(self):
        # Even with 99% confidence, sub-3.0 projection should return LOW_VOLUME.
        tier, color = tier_from_signals(0.99, 'UNDER', 2.5, 1.0, 0.9, 10, mean_proj=1.9)
        self.assertEqual(tier, 'LOW_VOLUME')
        self.assertEqual(color, 'gray')

    def test_low_volume_at_exact_boundary(self):
        tier, _ = tier_from_signals(0.99, 'UNDER', 2.5, 1.0, 0.9, 10,
                                    mean_proj=MIN_TIER_PROJECTION - 0.01)
        self.assertEqual(tier, 'LOW_VOLUME')

    def test_above_boundary_not_gated(self):
        tier, _ = tier_from_signals(0.99, 'OVER', 3.5, 2.0, 0.5, 10,
                                    mean_proj=MIN_TIER_PROJECTION)
        self.assertNotEqual(tier, 'LOW_VOLUME')

    def test_no_mean_proj_skips_gate(self):
        # Backward-compat: if mean_proj not provided, gate does not apply.
        tier, _ = tier_from_signals(0.99, 'OVER', 9.5, 6.0, 0.5, 10, mean_proj=None)
        self.assertNotEqual(tier, 'LOW_VOLUME')


class EdgeTest(unittest.TestCase):
    def test_default_minus_110(self):
        info = edge_from_odds(0.60, None)
        self.assertAlmostEqual(info['implied_prob'], 0.5238, places=4)
        self.assertAlmostEqual(info['edge'], 0.60 - 0.5238, places=4)
        self.assertEqual(info['american_odds'], -110)

    def test_positive_odds(self):
        info = edge_from_odds(0.55, 150)
        self.assertAlmostEqual(info['implied_prob'], 0.40, places=4)
        self.assertAlmostEqual(info['edge'], 0.15, places=4)


if __name__ == '__main__':
    unittest.main()
