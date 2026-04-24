import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.features import _parse_height_inches


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


if __name__ == '__main__':
    unittest.main()
