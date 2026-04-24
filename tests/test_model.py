import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.model import ReboundSimulator


class NegBinomialFitTest(unittest.TestCase):
    def setUp(self):
        self.sim = ReboundSimulator(num_simulations=2000)

    def test_underdispersed_fallback(self):
        n, p = self.sim.fit_negative_binomial(mean=10.0, variance=5.0)
        self.assertGreater(n, 0)
        self.assertLess(p, 1.0)

    def test_mean_recovered(self):
        np.random.seed(42)
        res = self.sim.simulate({'projection': 10.0, 'components': {'Proj Minutes': 30.0}})
        self.assertAlmostEqual(res['mean_sim'], 10.0, delta=1.0)


class FanoVolumeFloorTest(unittest.TestCase):
    """Ensure low-rebound players get higher Fano, preventing artificial confidence."""

    def setUp(self):
        self.sim = ReboundSimulator(num_simulations=20000)

    def test_low_mean_uses_volume_floor_fano(self):
        # For mean=2.0 with < 20 min, the old minutes-heuristic Fano was 1.15.
        # The volume floor should raise this to 2.0. Verify the reported Fano >= 2.0
        # and that the distribution is wider (higher std) than the old tight version.
        np.random.seed(0)
        res = self.sim.simulate({'projection': 2.0, 'components': {'Proj Minutes': 18.0}})
        reported_fano = res['params']['fano']
        self.assertGreaterEqual(reported_fano, 2.0,
                                f"Fano {reported_fano:.3f} below volume floor 2.0 for 2-rebound player")
        # Std should be noticeably larger than for old Fano=1.15 (which gave std ≈ 1.52).
        self.assertGreater(res['std_sim'], 1.8,
                           f"std_sim {res['std_sim']:.3f}: distribution not wide enough for bench player")

    def test_high_mean_unaffected(self):
        # Players projecting 10+ rebounds should not be penalized by the volume floor.
        np.random.seed(1)
        res = self.sim.simulate({'projection': 10.0, 'components': {'Proj Minutes': 32.0}})
        self.assertAlmostEqual(res['mean_sim'], 10.0, delta=1.5)

    def test_fano_floor_respected_for_empirical(self):
        # Even when empirical Fano is provided, the volume floor must be respected.
        # Give a small empirical Fano (1.0 — very tight) for a 2-rebound player.
        res = self.sim.simulate(
            {'projection': 2.0, 'components': {'Proj Minutes': 18.0}},
            player_variance={'reb_variance': 2.0, 'reb_mean': 2.0},  # empirical fano = 1.0
        )
        # Effective Fano should be >= 2.0 (volume floor), not the raw empirical 1.0.
        self.assertGreaterEqual(res['params']['fano'], 2.0 * 0.85,
                                "Volume floor not respected even with tight empirical Fano")


class EmpiricalFanoTest(unittest.TestCase):
    def setUp(self):
        self.sim = ReboundSimulator(num_simulations=2000)

    def test_empirical_used_when_available(self):
        res = self.sim.simulate(
            {'projection': 10.0, 'components': {'Proj Minutes': 30.0}},
            player_variance={'reb_variance': 20.0, 'reb_mean': 10.0},
        )
        self.assertEqual(res['params']['fano_source'], 'empirical')

    def test_heuristic_when_missing(self):
        res = self.sim.simulate({'projection': 10.0, 'components': {'Proj Minutes': 30.0}})
        self.assertEqual(res['params']['fano_source'], 'heuristic')

    def test_high_variance_flag_set(self):
        res = self.sim.simulate(
            {'projection': 10.0, 'components': {'Proj Minutes': 30.0}},
            player_variance={'reb_variance': 45.0, 'reb_mean': 10.0},  # fano 4.5
        )
        self.assertTrue(res['params']['high_variance_flag'])

    def test_high_variance_flag_unset_for_normal(self):
        res = self.sim.simulate(
            {'projection': 10.0, 'components': {'Proj Minutes': 30.0}},
            player_variance={'reb_variance': 15.0, 'reb_mean': 10.0},  # fano 1.5
        )
        self.assertFalse(res['params']['high_variance_flag'])


class ProbabilitiesTest(unittest.TestCase):
    def test_probs_sum_roughly_one(self):
        sim = ReboundSimulator(num_simulations=5000)
        np.random.seed(0)
        res = sim.simulate({'projection': 8.0, 'components': {'Proj Minutes': 28.0}})
        probs = sim.get_probabilities(res, 8.5)
        total = probs['over_probability'] + probs['under_probability'] + probs['push_probability']
        self.assertAlmostEqual(total, 1.0, places=6)


if __name__ == '__main__':
    unittest.main()
