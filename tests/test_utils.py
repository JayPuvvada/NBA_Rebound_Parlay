import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import normalize_name, implied_prob_from_american


class NormalizeNameTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(normalize_name("LeBron James"), "lebron james")

    def test_accents(self):
        self.assertEqual(normalize_name("Nikola Jokić"), "nikola jokic")

    def test_punctuation(self):
        self.assertEqual(normalize_name("P.J. Tucker"), "pj tucker")

    def test_whitespace(self):
        self.assertEqual(normalize_name("  Jalen  Brunson  "), "jalen  brunson")


class ImpliedProbTest(unittest.TestCase):
    def test_minus_110(self):
        self.assertAlmostEqual(implied_prob_from_american(-110), 0.5238, places=4)

    def test_plus_200(self):
        self.assertAlmostEqual(implied_prob_from_american(200), 0.3333, places=4)

    def test_minus_200(self):
        self.assertAlmostEqual(implied_prob_from_american(-200), 0.6667, places=4)


if __name__ == '__main__':
    unittest.main()
