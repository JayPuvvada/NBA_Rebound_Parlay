import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.grade import grade_predictions, manually_settle
from src.utils import eastern_today


class FakeLedger:
    def __init__(self, pending=None):
        self.pending = pending or []
        self.graded = []
        self.voided = []

    def get_pending_predictions(self, date_str=None):
        if date_str:
            return [row for row in self.pending if row["game_date"] == date_str]
        return list(self.pending)

    def grade_prediction(self, pred_id, actual):
        self.graded.append((pred_id, actual))
        return "WIN"

    def void_prediction(self, pred_id, reason):
        self.voided.append((pred_id, reason))
        return "VOID"


def _pending(pred_id=1, game_date="2024-01-15", opponent="BOS"):
    return {
        "id": pred_id,
        "game_date": game_date,
        "player": "Test Player",
        "opponent": opponent,
        "line": 8.5,
    }


class FakeLoader:
    def __init__(self, rows):
        self.rows = rows

    def get_player_id(self, _name):
        return 42

    def get_player_gamelog(self, _player_id):
        return pd.DataFrame(self.rows)


class AutomaticGradingTest(unittest.TestCase):
    def test_historical_date_uses_appropriate_nba_season(self):
        ledger = FakeLedger([_pending()])
        seasons = []

        def factory(season=None):
            seasons.append(season)
            return FakeLoader(
                [{"GAME_DATE": "Jan 15, 2024", "REB": 10, "MATCHUP": "LAL vs. BOS"}]
            )

        stats = grade_predictions(ledger=ledger, loader_factory=factory)
        self.assertEqual(seasons, ["2023-24"])
        self.assertEqual(ledger.graded, [(1, 10)])
        self.assertEqual(stats["graded"], 1)

    def test_different_seasons_use_different_loaders(self):
        ledger = FakeLedger(
            [_pending(1, "2024-01-15"), _pending(2, "2025-11-01")]
        )
        seasons = []

        def factory(season=None):
            seasons.append(season)
            rows = (
                [{"GAME_DATE": "Jan 15, 2024", "REB": 10, "MATCHUP": "LAL vs. BOS"}]
                if season == "2023-24"
                else [{"GAME_DATE": "Nov 01, 2025", "REB": 11, "MATCHUP": "LAL vs. BOS"}]
            )
            return FakeLoader(rows)

        grade_predictions(ledger=ledger, loader_factory=factory)
        self.assertEqual(seasons, ["2023-24", "2025-26"])
        self.assertEqual(ledger.graded, [(1, 10), (2, 11)])

    def test_missing_log_is_left_pending_not_auto_voided(self):
        ledger = FakeLedger([_pending()])
        stats = grade_predictions(ledger=ledger, loader=FakeLoader([]))
        self.assertEqual(ledger.graded, [])
        self.assertEqual(ledger.voided, [])
        self.assertEqual(stats["skipped"], 1)

    def test_opponent_mismatch_is_not_graded(self):
        ledger = FakeLedger([_pending()])
        loader = FakeLoader(
            [{"GAME_DATE": "Jan 15, 2024", "REB": 10, "MATCHUP": "LAL vs. NYK"}]
        )
        stats = grade_predictions(ledger=ledger, loader=loader)
        self.assertEqual(ledger.graded, [])
        self.assertEqual(stats["errors"], 1)

    def test_future_predictions_are_not_queried(self):
        ledger = FakeLedger([_pending(game_date="2099-01-01")])

        def forbidden_factory(**_kwargs):
            raise AssertionError("future date should not construct a loader")

        stats = grade_predictions(ledger=ledger, loader_factory=forbidden_factory)
        self.assertEqual(stats["skipped"], 1)

    def test_same_day_is_skipped_unless_explicitly_allowed(self):
        today = eastern_today()
        ledger = FakeLedger([_pending(game_date=today)])
        loader = FakeLoader(
            [{"GAME_DATE": today, "REB": 10, "MATCHUP": "LAL vs. BOS"}]
        )
        self.assertEqual(grade_predictions(ledger=ledger, loader=loader)["skipped"], 1)
        self.assertEqual(ledger.graded, [])
        self.assertEqual(
            grade_predictions(ledger=ledger, loader=loader, allow_today=True)["graded"],
            1,
        )


class ManualSettlementTest(unittest.TestCase):
    def test_manual_actual(self):
        ledger = FakeLedger()
        self.assertEqual(manually_settle(ledger, 7, actual_rebounds=12), "WIN")
        self.assertEqual(ledger.graded, [(7, 12)])

    def test_manual_void(self):
        ledger = FakeLedger()
        self.assertEqual(manually_settle(ledger, 7, void_reason="Confirmed DNP"), "VOID")
        self.assertEqual(ledger.voided, [(7, "Confirmed DNP")])

    def test_manual_settlement_requires_exactly_one_outcome(self):
        ledger = FakeLedger()
        with self.assertRaises(ValueError):
            manually_settle(ledger, 7)
        with self.assertRaises(ValueError):
            manually_settle(ledger, 7, actual_rebounds=10, void_reason="No")


if __name__ == "__main__":
    unittest.main()
