import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import (
    decimal_odds_from_american,
    ev_roi,
    implied_prob_from_american,
    kelly_criterion,
    normalize_name,
)


class NormalizeNameTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(normalize_name("LeBron James"), "lebron james")

    def test_accents(self):
        self.assertEqual(normalize_name("Nikola Jokić"), "nikola jokic")

    def test_punctuation(self):
        self.assertEqual(normalize_name("P.J. Tucker"), "pj tucker")

    def test_whitespace(self):
        self.assertEqual(normalize_name("  Jalen  Brunson  "), "jalen  brunson")


class OddsConversionTest(unittest.TestCase):
    def test_common_prices(self):
        self.assertAlmostEqual(implied_prob_from_american(-110), 0.5238095238)
        self.assertAlmostEqual(implied_prob_from_american(200), 1 / 3)
        self.assertAlmostEqual(implied_prob_from_american(-200), 2 / 3)
        self.assertAlmostEqual(decimal_odds_from_american(-110), 1.909090909)
        self.assertAlmostEqual(decimal_odds_from_american(150), 2.5)

    def test_invalid_prices_raise(self):
        for odds in (0, 99, -99, None, True, float("nan"), float("inf"), "bad"):
            with self.subTest(odds=odds):
                with self.assertRaises(ValueError):
                    implied_prob_from_american(odds)


class BettingMathTest(unittest.TestCase):
    def test_ev_without_push(self):
        self.assertAlmostEqual(ev_roi(0.55, -110), 0.05)

    def test_ev_returns_stake_on_push(self):
        # Win .5 * .9091 profit, loss .4 * 1, push .1 * 0.
        self.assertAlmostEqual(ev_roi(0.50, -110, p_push=0.10), 0.0545454545)

    def test_kelly_conditions_on_settled_outcomes(self):
        # Full Kelly is 1/15; the application intentionally uses quarter Kelly.
        self.assertAlmostEqual(
            kelly_criterion(0.50, -110, p_push=0.10), (1 / 15) * 0.25
        )

    def test_kelly_never_recommends_negative_stake(self):
        self.assertEqual(kelly_criterion(0.40, -110), 0.0)

    def test_missing_odds_are_non_actionable(self):
        self.assertEqual(ev_roi(0.75, None), 0.0)
        self.assertEqual(kelly_criterion(0.75, None), 0.0)

    def test_invalid_probability_partition_raises(self):
        for p_win, p_push in ((-0.1, 0), (1.1, 0), (0.8, 0.3), (0.5, -0.1)):
            with self.subTest(p_win=p_win, p_push=p_push):
                with self.assertRaises(ValueError):
                    ev_roi(p_win, -110, p_push)

    def test_fractional_kelly_must_be_valid(self):
        # Validate public risk sizing input rather than silently leveraging up.
        with self.assertRaises(ValueError):
            kelly_criterion(0.6, -110, fractional=-0.1)


if __name__ == "__main__":
    unittest.main()
