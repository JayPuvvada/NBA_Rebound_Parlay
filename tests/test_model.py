import os
import sys
import unittest

import numpy as np
from scipy.stats import nbinom

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.model import ReboundSimulator


class NegBinomialFitTest(unittest.TestCase):
    def setUp(self):
        self.sim = ReboundSimulator(num_simulations=2_000, random_state=1)

    def test_underdispersed_input_gets_valid_fallback(self):
        n, p = self.sim.fit_negative_binomial(mean=10.0, variance=5.0)
        self.assertGreater(n, 0)
        self.assertGreater(p, 0)
        self.assertLess(p, 1)

    def test_fit_recovers_requested_moments(self):
        n, p = self.sim.fit_negative_binomial(mean=10.0, variance=18.0)
        self.assertAlmostEqual(n * (1 - p) / p, 10.0)
        self.assertAlmostEqual(n * (1 - p) / (p * p), 18.0)

    def test_invalid_fit_inputs_raise(self):
        for mean, variance in ((-1, 2), (1, -1), (float("nan"), 2), (2, float("inf")), (0, 0)):
            with self.subTest(mean=mean, variance=variance):
                with self.assertRaises(ValueError):
                    self.sim.fit_negative_binomial(mean, variance)


class SimulationValidationTest(unittest.TestCase):
    def test_invalid_sample_sizes_raise(self):
        for value in (0, -1, 1.5, True, "100"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ReboundSimulator(value)

    def test_invalid_projection_raises(self):
        sim = ReboundSimulator(random_state=1)
        for value in (-1, float("nan"), float("inf"), "bad"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    sim.simulate({"projection": value})

    def test_seed_is_reproducible(self):
        data = {"projection": 8.2, "components": {"Proj Minutes": 31.0}}
        first = ReboundSimulator(500, random_state=2026).simulate(data)
        second = ReboundSimulator(500, random_state=2026).simulate(data)
        np.testing.assert_array_equal(first["samples"], second["samples"])

    def test_per_call_seed_is_reproducible(self):
        sim = ReboundSimulator(500)
        first = sim.simulate({"projection": 8.2}, random_state=9)
        second = sim.simulate({"projection": 8.2}, random_state=9)
        np.testing.assert_array_equal(first["samples"], second["samples"])

    def test_market_line_does_not_anchor_model(self):
        data = {"projection": 8.2}
        low = ReboundSimulator(500, random_state=7).simulate(data, market_line=4.5)
        high = ReboundSimulator(500, random_state=7).simulate(data, market_line=12.5)
        self.assertEqual(low["params"], high["params"])
        np.testing.assert_array_equal(low["samples"], high["samples"])
        self.assertFalse(low["params"]["market_anchored"])

    def test_distribution_mean_is_recovered_by_sample(self):
        result = ReboundSimulator(20_000, random_state=42).simulate(
            {"projection": 10.0, "components": {"Proj Minutes": 30.0}}
        )
        self.assertAlmostEqual(result["mean_sim"], 10.0, delta=0.2)


class VarianceModelTest(unittest.TestCase):
    def setUp(self):
        self.sim = ReboundSimulator(2_000, random_state=3)

    def test_low_volume_floor_is_hard_floor(self):
        result = self.sim.simulate(
            {"projection": 2.0, "components": {"Proj Minutes": 18.0}},
            player_variance={"reb_variance": 2.0, "reb_mean": 2.0, "sample_size": 30},
        )
        self.assertGreaterEqual(result["params"]["fano"], 2.0)

    def test_empirical_variance_is_shrunk_by_sample_size(self):
        data = {"projection": 10.0, "components": {"Proj Minutes": 30.0}}
        small = self.sim.simulate(
            data,
            player_variance={"reb_variance": 40.0, "reb_mean": 10.0, "sample_size": 5},
            random_state=1,
        )
        large = self.sim.simulate(
            data,
            player_variance={"reb_variance": 40.0, "reb_mean": 10.0, "sample_size": 80},
            random_state=1,
        )
        self.assertLess(small["params"]["fano"], large["params"]["fano"])
        self.assertLess(small["params"]["empirical_weight"], large["params"]["empirical_weight"])

    def test_explicit_tiny_empirical_sample_is_ignored(self):
        result = self.sim.simulate(
            {"projection": 10.0},
            player_variance={"reb_variance": 100.0, "reb_mean": 10.0, "sample_size": 2},
        )
        self.assertEqual(result["params"]["fano_source"], "heuristic_insufficient_sample")
        self.assertFalse(result["params"]["high_variance_flag"])

    def test_high_variance_is_flagged_after_adequate_evidence(self):
        result = self.sim.simulate(
            {"projection": 10.0},
            player_variance={"reb_variance": 45.0, "reb_mean": 10.0, "sample_size": 20},
        )
        self.assertEqual(result["params"]["fano_source"], "empirical")
        self.assertTrue(result["params"]["high_variance_flag"])

    def test_nan_empirical_data_falls_back_safely(self):
        result = self.sim.simulate(
            {"projection": 10.0},
            player_variance={"reb_variance": float("nan"), "reb_mean": 10.0},
        )
        self.assertEqual(result["params"]["fano_source"], "heuristic")


class ExactProbabilityTest(unittest.TestCase):
    def setUp(self):
        self.sim = ReboundSimulator(100, random_state=1)
        self.result = self.sim.simulate({"projection": 8.0})

    def test_half_line_partitions_without_push(self):
        probabilities = self.sim.get_probabilities(self.result, 8.5)
        self.assertEqual(probabilities["push_probability"], 0.0)
        self.assertAlmostEqual(
            probabilities["over_probability"] + probabilities["under_probability"], 1.0
        )

    def test_integer_line_has_exact_push_mass(self):
        probabilities = self.sim.get_probabilities(self.result, 8.0)
        n = self.result["params"]["n"]
        p = self.result["params"]["p"]
        self.assertAlmostEqual(probabilities["push_probability"], nbinom.pmf(8, n, p), places=12)
        self.assertAlmostEqual(sum(probabilities[key] for key in (
            "over_probability", "under_probability", "push_probability"
        )), 1.0, places=12)

    def test_probabilities_and_intervals_do_not_depend_on_random_draws(self):
        data = {"projection": 8.0}
        tiny = ReboundSimulator(1, random_state=1)
        large = ReboundSimulator(50_000, random_state=99)
        p1 = tiny.get_probabilities(tiny.simulate(data), 8.5)
        p2 = large.get_probabilities(large.simulate(data), 8.5)
        self.assertEqual(p1, p2)
        self.assertEqual(p1["interval_method"], "exact_equal_tailed")

    def test_zero_mean_is_degenerate(self):
        result = self.sim.simulate({"projection": 0})
        at_zero = self.sim.get_probabilities(result, 0)
        at_half = self.sim.get_probabilities(result, 0.5)
        self.assertEqual(at_zero["push_probability"], 1.0)
        self.assertEqual(at_half["under_probability"], 1.0)
        self.assertEqual(at_half["ci_95"], [0, 0])

    def test_invalid_lines_raise(self):
        for line in (-0.5, float("nan"), "x"):
            with self.subTest(line=line):
                with self.assertRaises(ValueError):
                    self.sim.get_probabilities(self.result, line)


if __name__ == "__main__":
    unittest.main()
