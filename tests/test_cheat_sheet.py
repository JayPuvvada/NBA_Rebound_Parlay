import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cheat_sheet import project_team, project_team_with_diagnostics
from src.model import ReboundSimulator


class FakeLoader:
    def __init__(self, players=None):
        self.players = [(1, "Value Player")] if players is None else players

    def get_team_roster(self, _team_id):
        return pd.DataFrame(
            [{"PLAYER_ID": player_id, "PLAYER": name} for player_id, name in self.players]
        )


class FakeEngineer:
    def __init__(self, projections=None):
        self.projections = projections or {1: 8.0}
        self.calls = []

    def compute_composite_projection(self, player_id, opponent, **kwargs):
        self.calls.append((player_id, opponent, kwargs))
        projection = self.projections[player_id]
        return {
            "projection": projection,
            "components": {"Proj Minutes": 31.0, "Base Rebs": projection},
            "modifiers": {"minutes": 31.0},
            "matchup_context": "Neutral",
            "matchup_injury": None,
            "team_injury": None,
            "team_injury_list": ["Teammate (OUT)"],
            "opp_injury_list": ["Opponent (Questionable)"],
            "metadata": {
                "prediction_eligible": True,
                "limitations": [],
            },
            "trend_data": [
                {"date": f"g{i}", "rebounds": value, "opponent": "BOS"}
                for i, value in enumerate([7, 8, 6, 8, 7, 8, 6, 7, 8, 7])
            ],
            "player_variance": {
                "reb_variance": projection * 1.4,
                "reb_mean": projection,
                "sample_size": 30,
            },
        }

    def generate_pick_summary(self, projection, line):
        return f"{projection['tier']} at {line}"


class FakeLedger:
    def __init__(self):
        self.records = []

    def record_prediction(self, **kwargs):
        self.records.append(kwargs)
        return len(self.records)


class HistoricalEngineer(FakeEngineer):
    def compute_composite_projection(self, player_id, opponent, **kwargs):
        result = super().compute_composite_projection(player_id, opponent, **kwargs)
        result["metadata"] = {
            "prediction_eligible": False,
            "historical_mode": True,
            "limitations": ["historical injury status is unavailable"],
        }
        return result


class MissingEligibilityEngineer(FakeEngineer):
    def compute_composite_projection(self, player_id, opponent, **kwargs):
        result = super().compute_composite_projection(player_id, opponent, **kwargs)
        result.pop("metadata", None)
        return result


class ProjectionErrorEngineer(FakeEngineer):
    def compute_composite_projection(self, player_id, opponent, **kwargs):
        self.calls.append((player_id, opponent, kwargs))
        return {"error": "player has insufficient history"}


class PartialFailureEngineer(FakeEngineer):
    def compute_composite_projection(self, player_id, opponent, **kwargs):
        if player_id == 2:
            raise RuntimeError("upstream failure details should stay in logs")
        return super().compute_composite_projection(player_id, opponent, **kwargs)


def _run(
    odds,
    *,
    loader=None,
    engineer=None,
    ledger=None,
    record=False,
    spread=None,
    diagnostics=None,
):
    return project_team(
        loader or FakeLoader(),
        engineer or FakeEngineer(),
        ReboundSimulator(250, random_state=4),
        10,
        "LAL",
        "BOS",
        True,
        1,
        2,
        odds,
        "2026-01-15",
        spread,
        record_predictions=record,
        ledger=ledger,
        diagnostics=diagnostics,
    )


class CheatSheetContractTest(unittest.TestCase):
    def test_uses_side_specific_price_and_raw_fraction_contract(self):
        rows = _run(
            {
                "value player": {
                    "over": {"line": 8.5, "odds": -300, "book": "FanDuel"},
                    "under": {
                        "line": 8.5,
                        "odds": 110,
                        "book": "FanDuel",
                        "source": "the-odds-api",
                    },
                }
            }
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["direction"], "UNDER")
        self.assertEqual(row["odds_side"], "UNDER")
        self.assertEqual(row["american_odds"], 110)
        self.assertEqual(row["bookmaker"], "FanDuel")
        self.assertEqual(row["odds_source"], "the-odds-api")
        self.assertEqual(row["evaluated_side"], "UNDER")
        self.assertGreater(row["ev_roi"], 0)
        self.assertTrue(row["actionable"])
        for key in (
            "over_probability",
            "under_probability",
            "push_probability",
            "confidence",
            "implied_probability",
            "edge",
            "kelly_fraction",
        ):
            self.assertGreaterEqual(row[key], 0)
            self.assertLessEqual(row[key], 1)
        self.assertAlmostEqual(
            row["over_probability"]
            + row["under_probability"]
            + row["push_probability"],
            1.0,
        )
        self.assertEqual(row["probability_unit"], "fraction")
        self.assertEqual(row["injuries"]["team_list"], ["Teammate (OUT)"])
        self.assertIn("source", row["variance"])
        self.assertIn("high_variance", row["variance"])
        self.assertIn("sample_size", row["variance"])
        self.assertEqual(set(row["side_evaluations"]), {"over", "under"})
        self.assertEqual(row["prediction_interval_68"], [row["range"]["low"], row["range"]["high"]])

    def test_legacy_over_price_is_never_used_for_under(self):
        row = _run({"value player": {"line": 20.5, "odds": -110, "book": "Legacy"}})[0]
        self.assertIsNone(row["direction"])
        self.assertEqual(row["odds_side"], "OVER")
        self.assertEqual(row["tier"], "AVOID")
        self.assertLess(row["ev_roi"], 0)
        self.assertIsNone(row["market_odds"]["under"])

    def test_marginal_positive_ev_side_is_diagnostic_not_a_direction(self):
        row = _run(
            {
                "value player": {
                    "under": {"line": 8.5, "odds": -145, "book": "FanDuel"}
                }
            }
        )[0]
        self.assertGreater(row["ev_roi"], 0)
        self.assertEqual(row["evaluated_side"], "UNDER")
        self.assertEqual(row["tier"], "AVOID")
        self.assertFalse(row["actionable"])
        self.assertIsNone(row["direction"])

    def test_lower_ev_actionable_side_beats_higher_ev_avoid_side(self):
        row = _run(
            {
                "value player": {
                    "over": {"line": 8.5, "odds": 500, "book": "FanDuel"},
                    "under": {"line": 8.5, "odds": 100, "book": "FanDuel"},
                }
            }
        )[0]
        self.assertGreater(
            row["side_evaluations"]["over"]["ev_roi"],
            row["side_evaluations"]["under"]["ev_roi"],
        )
        self.assertEqual(row["side_evaluations"]["over"]["tier"], "AVOID")
        self.assertTrue(isinstance(row["direction"], str))
        self.assertEqual(row["direction"], "UNDER")
        self.assertEqual(row["tier"], "PLAY")

    def test_no_market_uses_nulls_not_string_sentinels(self):
        row = _run({})[0]
        for key in (
            "line",
            "direction",
            "odds_side",
            "american_odds",
            "tier",
            "confidence",
            "ev_roi",
        ):
            self.assertIsNone(row[key])
        self.assertIsInstance(row["range"]["low"], int)
        self.assertIsInstance(row["range"]["high"], int)

    def test_spread_and_as_of_date_reach_feature_engineer(self):
        engineer = FakeEngineer()
        row = _run({}, engineer=engineer, spread=-7.5)[0]
        kwargs = engineer.calls[0][2]
        self.assertEqual(kwargs["spread"], -7.5)
        self.assertEqual(kwargs["as_of_date"], "2026-01-15")
        self.assertEqual(row["spread"], -7.5)
        self.assertTrue(row["spread_available"])

    def test_missing_spread_is_explicitly_marked(self):
        row = _run({})[0]
        self.assertEqual(row["spread"], 0)
        self.assertFalse(row["spread_available"])

    def test_incomplete_historical_context_is_diagnostic_only(self):
        odds = {
            "value player": {
                "under": {"line": 8.5, "odds": 110, "book": "FanDuel"}
            }
        }
        row = _run(odds, engineer=HistoricalEngineer())[0]
        self.assertFalse(row["prediction_eligible"])
        self.assertFalse(row["actionable"])
        self.assertIsNone(row["direction"])
        self.assertEqual(row["tier"], "HISTORICAL_CONTEXT_INCOMPLETE")
        self.assertEqual(row["tier_color"], "gray")
        self.assertEqual(row["kelly_fraction"], 0)
        self.assertIsNotNone(row["under_probability"])
        self.assertEqual(row["limitations"], ["historical injury status is unavailable"])

    def test_missing_safety_metadata_fails_closed(self):
        ledger = FakeLedger()
        row = _run(
            {
                "value player": {
                    "under": {"line": 8.5, "odds": 110, "book": "FanDuel"}
                }
            },
            engineer=MissingEligibilityEngineer(),
            ledger=ledger,
            record=True,
        )[0]
        self.assertFalse(row["prediction_eligible"])
        self.assertFalse(row["actionable"])
        self.assertIsNone(row["direction"])
        self.assertEqual(row["tier"], "HISTORICAL_CONTEXT_INCOMPLETE")
        self.assertTrue(any("safety metadata" in item for item in row["limitations"]))
        self.assertEqual(ledger.records, [])


class CheatSheetPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.odds = {
            "value player": {
                "over": {"line": 8.5, "odds": -300, "book": "FanDuel"},
                "under": {"line": 8.5, "odds": 110, "book": "FanDuel"},
            }
        }

    def test_read_path_does_not_record_by_default(self):
        ledger = FakeLedger()
        _run(self.odds, ledger=ledger)
        self.assertEqual(ledger.records, [])

    def test_explicit_record_stores_roi_not_probability_edge(self):
        ledger = FakeLedger()
        row = _run(self.odds, ledger=ledger, record=True)[0]
        self.assertEqual(len(ledger.records), 1)
        record = ledger.records[0]
        self.assertAlmostEqual(record["ev_roi"], row["ev_roi"])
        self.assertAlmostEqual(record["edge"], row["edge"])
        self.assertNotAlmostEqual(record["ev_roi"], record["edge"])
        self.assertEqual(record["bookmaker"], "FanDuel")
        self.assertEqual(record["odds_side"], "UNDER")


class CheatSheetDiagnosticsTest(unittest.TestCase):
    def test_empty_roster_is_distinct_from_all_failed(self):
        diagnostics = {}
        rows = _run({}, loader=FakeLoader([]), diagnostics=diagnostics)
        self.assertEqual(rows, [])
        self.assertEqual(diagnostics["status"], "empty_roster")
        self.assertTrue(diagnostics["empty_roster"])
        self.assertFalse(diagnostics["all_failed"])
        self.assertEqual(diagnostics["roster_count"], 0)
        self.assertEqual(diagnostics["attempted_count"], 0)

    def test_every_projection_returning_error_is_reported(self):
        diagnostics = {}
        rows = _run(
            {},
            loader=FakeLoader([(1, "One"), (2, "Two")]),
            engineer=ProjectionErrorEngineer(),
            diagnostics=diagnostics,
        )
        self.assertEqual(rows, [])
        self.assertEqual(diagnostics["status"], "all_failed")
        self.assertTrue(diagnostics["all_failed"])
        self.assertFalse(diagnostics["empty_roster"])
        self.assertEqual(diagnostics["roster_count"], 2)
        self.assertEqual(diagnostics["attempted_count"], 2)
        self.assertEqual(diagnostics["projection_error_count"], 2)
        self.assertEqual(diagnostics["exception_count"], 0)
        self.assertEqual(len(diagnostics["failure_samples"]), 2)

    def test_partial_failure_keeps_successful_rows_and_reports_health(self):
        diagnostics = {}
        rows = _run(
            {},
            loader=FakeLoader([(1, "Value Player"), (2, "Broken Player")]),
            engineer=PartialFailureEngineer({1: 8.0}),
            diagnostics=diagnostics,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(diagnostics["status"], "partial_failure")
        self.assertFalse(diagnostics["all_failed"])
        self.assertEqual(diagnostics["projected_count"], 1)
        self.assertEqual(diagnostics["exception_count"], 1)
        # Exception messages are logged server-side but not copied into diagnostics.
        self.assertNotIn("detail", diagnostics["failure_samples"][0])

    def test_helper_returns_rows_and_diagnostics_tuple(self):
        rows, diagnostics = project_team_with_diagnostics(
            FakeLoader(),
            FakeEngineer(),
            ReboundSimulator(50, random_state=1),
            10,
            "LAL",
            "BOS",
            True,
            1,
            2,
            {},
            "2026-01-15",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(diagnostics["status"], "ok")
        self.assertEqual(diagnostics["projected_count"], 1)
        self.assertEqual(diagnostics["failed_count"], 0)

    def test_invalid_diagnostics_sink_fails_before_roster_lookup(self):
        with self.assertRaises(TypeError):
            _run({}, diagnostics=[])


if __name__ == "__main__":
    unittest.main()
