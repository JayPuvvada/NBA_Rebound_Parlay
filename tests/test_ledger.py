import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ledger import LATEST_SCHEMA_VERSION, PredictionLedger
from src.recommendation import edge_from_odds


def _prediction(**overrides):
    values = {
        "game_date": "2026-01-15",
        "player": "Test Player",
        "team": "LAL",
        "opponent": "BOS",
        "is_home": True,
        "projection": 9.2,
        "line": 8.0,
        "american_odds": -110,
        "bookmaker": "FanDuel",
        "odds_side": "OVER",
        "direction": "OVER",
        "tier": "PLAY",
        "confidence": 0.55,
        "over_prob": 0.55,
        "under_prob": 0.35,
        "push_prob": 0.10,
        "input_snapshot": {"minutes": 32, "source": "test"},
    }
    values.update(overrides)
    metrics = edge_from_odds(
        values["confidence"], values["american_odds"], values["push_prob"]
    )
    values.update(
        {
            "implied_prob": metrics["implied_probability"],
            "edge": metrics["edge"],
            "ev_roi": metrics["ev_roi"],
            "kelly_fraction": metrics["kelly_fraction"],
        }
    )
    return values


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "predictions.db")
        self.ledger = PredictionLedger(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()


class AppendOnlyLedgerTest(LedgerTestCase):
    def test_record_contains_versioned_snapshot_and_side(self):
        pred_id = self.ledger.record_prediction(**_prediction())
        row = self.ledger.get_prediction(pred_id)
        self.assertEqual(row["schema_version"], LATEST_SCHEMA_VERSION)
        self.assertEqual(row["model_version"], "rebound-nb-v2")
        self.assertEqual(row["bookmaker"], "FanDuel")
        self.assertEqual(row["odds_side"], "OVER")
        self.assertEqual(row["input_snapshot"], {"minutes": 32, "source": "test"})
        self.assertEqual(row["result"], "PENDING")
        self.assertTrue(row["prediction_key"])
        self.assertTrue(row["created_at"].endswith("+00:00"))

    def test_identical_refresh_is_idempotent(self):
        first = self.ledger.record_prediction(**_prediction())
        second = self.ledger.record_prediction(**_prediction())
        self.assertEqual(first, second)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 1)

    def test_graded_prediction_is_never_reset_by_refresh(self):
        pred_id = self.ledger.record_prediction(**_prediction())
        self.assertEqual(self.ledger.grade_prediction(pred_id, 10), "WIN")
        refreshed_id = self.ledger.record_prediction(**_prediction())
        self.assertEqual(refreshed_id, pred_id)
        row = self.ledger.get_prediction(pred_id)
        self.assertEqual(row["result"], "WIN")
        self.assertEqual(row["actual_rebounds"], 10)

    def test_changed_immutable_input_creates_new_version(self):
        first = self.ledger.record_prediction(**_prediction())
        second = self.ledger.record_prediction(
            **_prediction(american_odds=-105)
        )
        third = self.ledger.record_prediction(
            **_prediction(input_snapshot={"minutes": 33, "source": "test"})
        )
        self.assertEqual(len({first, second, third}), 3)

    def test_non_actionable_rows_are_not_recorded(self):
        self.assertIsNone(self.ledger.record_prediction(**_prediction(tier="AVOID")))
        self.assertEqual(self.ledger.get_pending_predictions(), [])

    def test_invalid_probability_partition_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.record_prediction(**_prediction(over_prob=0.6))

    def test_side_and_direction_must_match(self):
        with self.assertRaises(ValueError):
            self.ledger.record_prediction(**_prediction(odds_side="UNDER"))

    def test_inconsistent_ev_is_rejected(self):
        prediction = _prediction()
        prediction["ev_roi"] = prediction["edge"]
        with self.assertRaises(ValueError):
            self.ledger.record_prediction(**prediction)


class SettlementTest(LedgerTestCase):
    def test_win_loss_and_push_pnl(self):
        win_id = self.ledger.record_prediction(**_prediction(player="Winner"))
        loss_id = self.ledger.record_prediction(**_prediction(player="Loser"))
        push_id = self.ledger.record_prediction(**_prediction(player="Pusher"))

        self.assertEqual(self.ledger.grade_prediction(win_id, 9), "WIN")
        self.assertEqual(self.ledger.grade_prediction(loss_id, 7), "LOSS")
        self.assertEqual(self.ledger.grade_prediction(push_id, 8), "PUSH")

        self.assertAlmostEqual(self.ledger.get_prediction(win_id)["pnl_units"], 100 / 110)
        self.assertEqual(self.ledger.get_prediction(loss_id)["pnl_units"], -1)
        conditional_win_probability = 0.55 / 0.90
        self.assertAlmostEqual(
            self.ledger.get_prediction(win_id)["brier_score"],
            (conditional_win_probability - 1.0) ** 2,
        )
        self.assertAlmostEqual(
            self.ledger.get_prediction(loss_id)["brier_score"],
            conditional_win_probability ** 2,
        )
        push = self.ledger.get_prediction(push_id)
        self.assertEqual(push["pnl_units"], 0)
        self.assertIsNone(push["brier_score"])

    def test_under_direction_settles_correctly(self):
        pred_id = self.ledger.record_prediction(
            **_prediction(
                player="Under",
                direction="UNDER",
                odds_side="UNDER",
                confidence=0.35,
            )
        )
        self.assertEqual(self.ledger.grade_prediction(pred_id, 7), "WIN")

    def test_final_settlement_cannot_be_overwritten(self):
        pred_id = self.ledger.record_prediction(**_prediction())
        self.assertEqual(self.ledger.grade_prediction(pred_id, 10), "WIN")
        self.assertEqual(self.ledger.grade_prediction(pred_id, 2), "WIN")
        self.assertEqual(self.ledger.get_prediction(pred_id)["actual_rebounds"], 10)

    def test_void_requires_reason_and_is_final(self):
        pred_id = self.ledger.record_prediction(**_prediction())
        with self.assertRaises(ValueError):
            self.ledger.void_prediction(pred_id, "")
        self.assertEqual(self.ledger.void_prediction(pred_id, "Confirmed DNP void"), "VOID")
        self.assertEqual(self.ledger.grade_prediction(pred_id, 10), "VOID")
        row = self.ledger.get_prediction(pred_id)
        self.assertEqual(row["void_reason"], "Confirmed DNP void")
        self.assertEqual(row["pnl_units"], 0)

    def test_summary_excludes_void_from_bets_and_brier(self):
        win_id = self.ledger.record_prediction(**_prediction(player="Winner"))
        void_id = self.ledger.record_prediction(**_prediction(player="Void"))
        self.ledger.grade_prediction(win_id, 9)
        self.ledger.void_prediction(void_id, "Postponed")
        summary = self.ledger.get_performance_summary()[0]
        self.assertEqual(summary["total_bets"], 1)
        self.assertEqual(summary["voids"], 1)
        self.assertAlmostEqual(summary["realized_roi"], 100 / 110)


class MigrationTest(unittest.TestCase):
    def test_original_schema_migrates_without_losing_grade(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "legacy.db")
            with closing(sqlite3.connect(db_path)) as conn, conn:
                conn.execute(
                    """
                    CREATE TABLE predictions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT, game_date TEXT, player TEXT, team TEXT,
                        opponent TEXT, is_home BOOLEAN, projection REAL, line REAL,
                        american_odds INTEGER, direction TEXT, tier TEXT,
                        confidence REAL, over_prob REAL, under_prob REAL, ev_roi REAL,
                        actual_rebounds INTEGER, result TEXT, brier_score REAL,
                        pnl_units REAL
                    )
                    """
                )
                conn.execute(
                    "CREATE UNIQUE INDEX idx_player_date_line ON predictions (player, game_date, line)"
                )
                conn.execute(
                    """
                    INSERT INTO predictions (
                        timestamp, game_date, player, team, opponent, is_home,
                        projection, line, american_odds, direction, tier, confidence,
                        over_prob, under_prob, ev_roi, actual_rebounds, result,
                        brier_score, pnl_units
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "2026-01-15T12:00:00",
                        "2026-01-15",
                        "Legacy Player",
                        "LAL",
                        "BOS",
                        1,
                        9,
                        8.5,
                        -110,
                        "OVER",
                        "PLAY",
                        0.6,
                        0.6,
                        0.4,
                        0.145,
                        10,
                        "WIN",
                        0.16,
                        100 / 110,
                    ),
                )

            ledger = PredictionLedger(db_path)
            row = ledger.get_prediction(1)
            self.assertEqual(row["result"], "WIN")
            self.assertEqual(row["prediction_key"], "legacy-1")
            self.assertEqual(row["model_version"], "legacy-v1")
            self.assertEqual(row["odds_side"], "OVER")
            with closing(sqlite3.connect(db_path)) as conn, conn:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                index_names = {r[1] for r in conn.execute("PRAGMA index_list(predictions)")}
            self.assertEqual(version, LATEST_SCHEMA_VERSION)
            self.assertNotIn("idx_player_date_line", index_names)
            self.assertIn("idx_predictions_key", index_names)


if __name__ == "__main__":
    unittest.main()
