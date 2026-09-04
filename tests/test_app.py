import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pandas as pd

import app as app_module


BOS_ID = 1610612738
DAL_ID = 1610612742


class FakeLoader:
    season = "2025-26"
    DEFAULT_DAYS_REST = 2

    def get_team_id(self, abbreviation):
        return {"BOS": BOS_ID, "DAL": DAL_ID}.get(abbreviation)

    def get_player_id(self, name):
        return 1 if name == "Test Player" else None

    def get_common_player_info(self, _player_id):
        return pd.DataFrame([{"TEAM_ID": DAL_ID}])

    def get_games_for_date(self, _date):
        return [{
            "game_id": "game-1",
            "home_id": BOS_ID,
            "away_id": DAL_ID,
            "status": 1,
            "status_text": "7:30 pm ET",
            "game_time": "7:30 pm ET",
        }]

    def get_games_for_date_fresh(self, date_str):
        return self.get_games_for_date(date_str)

    def get_days_rest(self, _team_id, as_of=None):
        del as_of
        return 1

    def get_odds_for_game(self, *_args, **_kwargs):
        return {}


class FakeEngineer:
    def get_player_stats(self, *_args, **_kwargs):
        return {"team_id": DAL_ID}

    def compute_composite_projection(self, *_args, **_kwargs):
        return {
            "player": "Test Player",
            "team": "DAL",
            "team_id": DAL_ID,
            "team_abbreviation": "DAL",
            "projection": 7.0,
            "components": {"Proj Minutes": 30.0, "Blowout": "None"},
            "matchup_context": "Neutral",
            "matchup_injury": None,
            "team_injury": None,
            "team_injury_list": [],
            "opp_injury_list": [],
            "metadata": {
                "prediction_eligible": True,
                "limitations": [],
            },
            "data_freshness": {
                "prediction_eligible": True,
                "limitations": [],
            },
            "trend_data": [
                {"date": f"2026-01-{day:02d}", "rebounds": 6 + day % 3, "opponent": "BOS"}
                for day in range(1, 11)
            ],
            "player_variance": {
                "reb_variance": 10.0,
                "reb_mean": 7.0,
                "sample_size": 10,
            },
        }

    def generate_pick_summary(self, *_args, **_kwargs):
        return "Model summary."


class AppTestCase(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()
        self.loader = FakeLoader()
        self.engineer = FakeEngineer()
        self.components_patch = patch.object(
            app_module,
            "_components_for_date",
            return_value=(self.loader, self.engineer),
        )
        self.components_patch.start()

    def tearDown(self):
        self.components_patch.stop()


class ValidationTests(AppTestCase):
    def test_predict_requires_json_object_and_required_fields(self):
        response = self.client.post("/predict", json=[])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_request")

        response = self.client.post("/predict", json={"opponent": "BOS"})
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/predict",
            json={
                "player": "Test Player",
                "opponent": "BOS",
                "date": False,
                "home_game": False,
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_predict_rejects_invalid_odds_and_nonfinite_numbers(self):
        base = {
            "player": "Test Player",
            "opponent": "BOS",
            "home_game": False,
            "line": 6.5,
        }
        response = self.client.post("/predict", json={**base, "over_odds": 0})
        self.assertEqual(response.status_code, 400)

        response = self.client.post("/predict", json={**base, "spread": "NaN"})
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/predict", json={**base, "record_prediction": "yes"}
        )
        self.assertEqual(response.status_code, 400)

    def test_predict_rejects_unknown_opponent_before_projection(self):
        response = self.client.post(
            "/predict",
            json={"player": "Test Player", "opponent": "XYZ", "home_game": True},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["code"], "opponent_not_found")

    def test_predict_rejects_self_opponent_and_wrong_venue(self):
        today = date.today().isoformat()
        self_opponent = self.client.post(
            "/predict",
            json={
                "player": "Test Player",
                "opponent": "DAL",
                "date": today,
                "home_game": True,
            },
        )
        self.assertEqual(self_opponent.status_code, 400)

        wrong_venue = self.client.post(
            "/predict",
            json={
                "player": "Test Player",
                "opponent": "BOS",
                "date": today,
                "home_game": True,
            },
        )
        self.assertEqual(wrong_venue.status_code, 422)
        self.assertEqual(wrong_venue.get_json()["code"], "venue_mismatch")


class PredictContractTests(AppTestCase):
    def test_missing_safety_metadata_fails_closed(self):
        projection = self.engineer.compute_composite_projection()
        projection.pop("metadata")
        projection.pop("data_freshness")
        with patch.object(
            self.engineer, "compute_composite_projection", return_value=projection
        ):
            response = self.client.post(
                "/predict",
                json={
                    "player": "Test Player",
                    "opponent": "BOS",
                    "date": app_module.eastern_today(),
                    "line": 3.5,
                    "over_odds": 100,
                    "home_game": False,
                },
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertFalse(payload["prediction_eligible"])
        self.assertIsNone(payload["analysis"]["direction"])
        self.assertIn("explicitly authorize", " ".join(payload["limitations"]))

    def test_corrupt_upstream_projection_is_sanitized_server_error(self):
        projection = self.engineer.compute_composite_projection()
        projection["projection"] = "upstream-corrupt-value"
        with patch.object(
            self.engineer, "compute_composite_projection", return_value=projection
        ):
            response = self.client.post(
                "/predict",
                json={
                    "player": "Test Player",
                    "opponent": "BOS",
                    "date": "2026-01-15",
                    "home_game": False,
                },
            )

        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertEqual(payload["code"], "projection_service_unavailable")
        self.assertNotIn("could not convert", payload["error"].lower())

    def test_postponed_abbreviation_is_not_pregame(self):
        postponed = dict(
            self.loader.get_games_for_date(None)[0], status=1, status_text="PPD"
        )
        with patch.object(
            self.loader, "get_games_for_date_fresh", return_value=[postponed]
        ):
            response = self.client.post(
                "/predict",
                json={
                    "player": "Test Player",
                    "opponent": "BOS",
                    "date": app_module.eastern_today(),
                    "line": 3.5,
                    "over_odds": 100,
                    "home_game": False,
                },
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertFalse(payload["prediction_eligible"])
        self.assertFalse(payload["analysis"]["actionable"])

    def test_status_is_rechecked_immediately_before_ledger_write(self):
        pregame = self.loader.get_games_for_date(None)
        live = [dict(pregame[0], status=2, status_text="Q1 11:59")]
        request_json = {
            "player": "Test Player",
            "opponent": "BOS",
            "date": app_module.eastern_today(),
            "line": 3.5,
            "over_odds": 100,
            "home_game": False,
            "record_prediction": True,
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(
            self.loader,
            "get_games_for_date_fresh",
            side_effect=[pregame, live],
        ), patch.dict(
            os.environ,
            {
                "PREDICTIONS_DB_PATH": os.path.join(directory, "predictions.db"),
                "LEDGER_WRITE_TOKEN": "test-secret",
            },
        ):
            response = self.client.post(
                "/predict",
                json=request_json,
                headers={"X-Ledger-Write-Token": "test-secret"},
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertFalse(payload["recording"]["recorded"])
        self.assertFalse(payload["prediction_eligible"])
        self.assertIsNone(payload["analysis"]["direction"])
        self.assertIn("not pregame", payload["recording"]["reason"].lower())

    def test_auto_venue_matches_both_teams(self):
        response = self.client.post(
            "/predict",
            json={
                "player": "Test Player",
                "opponent": "BOS",
                "date": "2026-01-15",
                "line": 6.5,
                "over_odds": -105,
                "under_odds": -115,
                "home_game": None,
            },
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertFalse(payload["home_game"])
        analysis = payload["analysis"]
        self.assertIn(analysis["evaluated_side"], {"OVER", "UNDER"})
        if analysis["direction"] is not None:
            self.assertIn(analysis["direction"], {"OVER", "UNDER"})
        self.assertGreaterEqual(analysis["over_probability"], 0.0)
        self.assertLessEqual(analysis["over_probability"], 1.0)
        self.assertIn("side_evaluations", analysis)
        self.assertIn("variance", analysis)
        self.assertIn("actionable", analysis)
        self.assertEqual(analysis["probability_unit"], "fraction")
        self.assertEqual(analysis["ev_roi_unit"], "fraction_per_unit_staked")
        self.assertEqual(analysis["interval_method"], "exact_equal_tailed")
        self.assertGreaterEqual(analysis["prediction_interval_68_coverage"], 0.68)

    def test_missing_prices_are_explicitly_non_actionable(self):
        response = self.client.post(
            "/predict",
            json={
                "player": "Test Player",
                "opponent": "BOS",
                "line": 6.5,
                "home_game": False,
            },
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        analysis = response.get_json()["analysis"]
        self.assertEqual(analysis["tier"], "NO_PRICE")
        self.assertIsNone(analysis["american_odds"])
        self.assertIsNone(analysis["ev_roi"])

    def test_negative_ev_quote_is_not_presented_as_a_pick(self):
        response = self.client.post(
            "/predict",
            json={
                "player": "Test Player",
                "opponent": "BOS",
                "line": 6.5,
                "over_odds": -1000,
                "home_game": False,
            },
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        analysis = response.get_json()["analysis"]
        self.assertIsNone(analysis["direction"])
        self.assertEqual(analysis["evaluated_side"], "OVER")
        self.assertEqual(analysis["tier"], "AVOID")

    def test_actionable_side_is_not_masked_by_larger_avoid_ev(self):
        response = self.client.post(
            "/predict",
            json={
                "player": "Test Player",
                "opponent": "BOS",
                "date": date.today().isoformat(),
                "line": 7.5,
                "over_odds": 500,
                "under_odds": 100,
                "home_game": False,
            },
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        analysis = response.get_json()["analysis"]
        self.assertGreater(
            analysis["side_evaluations"]["over"]["ev_roi"],
            analysis["side_evaluations"]["under"]["ev_roi"],
        )
        self.assertEqual(analysis["side_evaluations"]["over"]["tier"], "AVOID")
        self.assertEqual(analysis["direction"], "UNDER")
        self.assertTrue(analysis["actionable"])

    def test_positive_ev_with_insufficient_history_is_not_presented_as_a_pick(self):
        original_projection = self.engineer.compute_composite_projection()
        original_projection["trend_data"] = original_projection["trend_data"][:2]
        with patch.object(
            self.engineer,
            "compute_composite_projection",
            return_value=original_projection,
        ):
            response = self.client.post(
                "/predict",
                json={
                    "player": "Test Player",
                    "opponent": "BOS",
                    "line": 3.5,
                    "over_odds": 100,
                    "home_game": False,
                },
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        analysis = response.get_json()["analysis"]
        self.assertGreater(analysis["ev_roi"], 0)
        self.assertEqual(analysis["tier"], "INSUFFICIENT_DATA")
        self.assertIsNone(analysis["direction"])

    def test_explicit_actionable_pick_is_recorded_idempotently(self):
        future_date = (date.today() + timedelta(days=7)).isoformat()
        request_json = {
            "player": "Test Player",
            "opponent": "BOS",
            "date": future_date,
            "line": 3.5,
            "over_odds": 100,
            "bookmaker": "test-book",
            "home_game": False,
            "record_prediction": True,
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "PREDICTIONS_DB_PATH": os.path.join(directory, "predictions.db"),
                "LEDGER_WRITE_TOKEN": "test-secret",
            },
        ):
            headers = {"X-Ledger-Write-Token": "test-secret"}
            first = self.client.post("/predict", json=request_json, headers=headers)
            second = self.client.post("/predict", json=request_json, headers=headers)

        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        first_recording = first.get_json()["recording"]
        second_recording = second.get_json()["recording"]
        self.assertTrue(first_recording["recorded"])
        self.assertIsInstance(first_recording["prediction_id"], int)
        self.assertEqual(
            first_recording["prediction_id"], second_recording["prediction_id"]
        )

    def test_ledger_write_requires_authorization(self):
        future_date = (date.today() + timedelta(days=1)).isoformat()
        request_json = {
            "player": "Test Player",
            "opponent": "BOS",
            "date": future_date,
            "line": 3.5,
            "over_odds": 100,
            "home_game": False,
            "record_prediction": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "predictions.db")
            with patch.dict(
                os.environ,
                {
                    "PREDICTIONS_DB_PATH": db_path,
                    "LEDGER_WRITE_TOKEN": "server-secret",
                },
            ):
                response = self.client.post("/predict", json=request_json)
                self.assertFalse(os.path.exists(db_path))

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        recording = response.get_json()["recording"]
        self.assertFalse(recording["recorded"])
        self.assertIn("authorization", recording["reason"].lower())

    def test_live_game_is_diagnostic_and_cannot_be_recorded(self):
        live_game = dict(self.loader.get_games_for_date(None)[0], status=2, status_text="Q2 4:31")
        request_json = {
            "player": "Test Player",
            "opponent": "BOS",
            "date": date.today().isoformat(),
            "line": 3.5,
            "over_odds": 100,
            "home_game": False,
            "record_prediction": True,
        }
        with patch.object(
            self.loader, "get_games_for_date_fresh", return_value=[live_game]
        ), patch.dict(os.environ, {"LEDGER_WRITE_TOKEN": "test-secret"}):
            response = self.client.post(
                "/predict",
                json=request_json,
                headers={"X-Ledger-Write-Token": "test-secret"},
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertFalse(payload["prediction_eligible"])
        self.assertIsNone(payload["analysis"]["direction"])
        self.assertFalse(payload["recording"]["recorded"])
        self.assertIn("live", payload["recording"]["reason"].lower())

    def test_ledger_failure_does_not_discard_projection(self):
        request_json = {
            "player": "Test Player",
            "opponent": "BOS",
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "line": 3.5,
            "over_odds": 100,
            "home_game": False,
            "record_prediction": True,
        }
        with patch.dict(
            os.environ, {"LEDGER_WRITE_TOKEN": "test-secret"}
        ), patch(
            "src.ledger.PredictionLedger", side_effect=OSError("read-only filesystem")
        ):
            response = self.client.post(
                "/predict",
                json=request_json,
                headers={"X-Ledger-Write-Token": "test-secret"},
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIn("analysis", response.get_json())
        recording = response.get_json()["recording"]
        self.assertFalse(recording["recorded"])
        self.assertIn("ledger", recording["reason"].lower())

    def test_no_line_returns_numeric_interval(self):
        response = self.client.post(
            "/predict",
            json={"player": "Test Player", "opponent": "BOS", "home_game": False},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        interval = response.get_json()["range"]
        self.assertEqual(interval["level"], 0.68)
        self.assertLessEqual(interval["low"], interval["high"])
        self.assertGreaterEqual(interval["actual_coverage"], 0.68)
        self.assertEqual(interval["method"], "exact_equal_tailed")

    def test_manual_matchup_validation_error_is_client_error(self):
        with patch.object(
            self.engineer,
            "compute_composite_projection",
            return_value={"error": "Matchup player is not on the opponent roster"},
        ):
            response = self.client.post(
                "/predict",
                json={
                    "player": "Test Player",
                    "opponent": "BOS",
                    "date": date.today().isoformat(),
                    "home_game": False,
                    "matchup": "Wrong Player",
                },
            )
        self.assertEqual(response.status_code, 422)


class RouteContractTests(AppTestCase):
    @staticmethod
    def _projection_diagnostics(target, status, projected, failed):
        target.update({
            "status": status,
            "all_failed": status == "all_failed",
            "roster_count": projected + failed,
            "attempted_count": projected + failed,
            "projected_count": projected,
            "failed_count": failed,
        })

    def test_one_team_total_failure_returns_partial_slate_warning(self):
        row = {
            "player": "Available Player",
            "projection": 8.0,
            "actionable": False,
            "ev_roi": None,
            "confidence": None,
        }
        call_count = 0

        def asymmetric_project(*_args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                self._projection_diagnostics(
                    kwargs["diagnostics"], "all_failed", 0, 15
                )
                return []
            self._projection_diagnostics(kwargs["diagnostics"], "ok", 1, 0)
            return [row]

        with patch.object(
            app_module, "project_team", side_effect=asymmetric_project
        ), patch.dict(os.environ, {"ODDS_API_KEY": ""}):
            response = self.client.get(
                f"/cheat-sheet?team=DAL&date={app_module.eastern_today()}"
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(len(payload["projections"]), 1)
        self.assertTrue(any("partial" in warning for warning in payload["warnings"]))

    def test_stale_sportsbook_quote_is_diagnostic_only(self):
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        fresh_fetch_time = datetime.now(timezone.utc).isoformat()
        odds = {
            "_meta": {
                "book": "Test Book",
                "source": "the-odds-api",
                "fetched_at": fresh_fetch_time,
                "updated_at": stale_time,
            }
        }
        row = {
            "player": "Priced Player",
            "projection": 8.0,
            "line": 7.5,
            "american_odds": -110,
            "direction": "OVER",
            "actionable": True,
            "prediction_eligible": True,
            "tier": "PLAY",
            "tier_color": "green",
            "ev_roi": 0.08,
            "confidence": 0.60,
            "kelly_fraction": 0.02,
            "side_evaluations": {"over": {"tier": "PLAY"}},
        }

        def fake_project(*_args, **kwargs):
            self._projection_diagnostics(kwargs["diagnostics"], "ok", 1, 0)
            return [dict(row)]

        with patch.dict(os.environ, {"ODDS_API_KEY": "key"}), patch.object(
            self.loader, "get_odds_for_game", return_value=odds
        ), patch.object(app_module, "project_team", side_effect=fake_project):
            response = self.client.get(
                f"/cheat-sheet?team=DAL&date={app_module.eastern_today()}"
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(payload["odds"]["stale_quote_count"], 2)
        for projection in payload["projections"]:
            self.assertFalse(projection["actionable"])
            self.assertIsNone(projection["direction"])
            self.assertEqual(projection["tier"], "STALE_ODDS")

    def test_games_returns_metadata(self):
        response = self.client.get("/games?date=2026-01-15")
        self.assertEqual(response.status_code, 200)
        game = response.get_json()["games"][0]
        self.assertEqual(game["id"], "game-1")
        self.assertEqual(game["away"], "DAL")
        self.assertIn("status_text", game)

    def test_cheat_sheet_uses_schedule_home_and_away_perspective(self):
        fake_rows = [
            {
                "player": "A",
                "projection": 8.0,
                "actionable": False,
                "ev_roi": None,
                "confidence": None,
            }
        ]
        calls = []

        def fake_project(*args, **kwargs):
            calls.append((args, kwargs))
            return [dict(fake_rows[0], team=args[4])]

        with patch.object(app_module, "project_team", side_effect=fake_project), patch.dict(
            os.environ, {"ODDS_API_KEY": ""}
        ):
            response = self.client.get("/cheat-sheet?team=DAL&date=2026-01-15")

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(payload["game"]["home"], "BOS")
        self.assertEqual(payload["game"]["away"], "DAL")
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0][0][6])
        self.assertFalse(calls[1][0][6])
        self.assertIsNone(payload["odds"]["source"])

    def test_cheat_sheet_reports_systemic_projection_failure(self):
        def fail_team(*_args, **kwargs):
            kwargs["diagnostics"].update({
                "status": "all_failed",
                "all_failed": True,
                "roster_count": 15,
                "attempted_count": 15,
                "projected_count": 0,
                "failed_count": 15,
            })
            return []

        with patch.object(app_module, "project_team", side_effect=fail_team):
            response = self.client.get(
                f"/cheat-sheet?team=DAL&date={date.today().isoformat()}"
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "projection_pipeline_failed")

    def test_cheat_sheet_live_game_forces_every_row_to_no_bet(self):
        live_game = dict(self.loader.get_games_for_date(None)[0], status=3, status_text="Final")
        row = {
            "player": "A",
            "projection": 8.0,
            "line": 7.5,
            "direction": "OVER",
            "actionable": True,
            "prediction_eligible": True,
            "tier": "PLAY",
            "tier_color": "green",
            "ev_roi": 0.1,
            "confidence": 0.6,
            "kelly_fraction": 0.02,
            "side_evaluations": {
                "over": {
                    "tier": "PLAY",
                    "tier_color": "green",
                    "kelly_fraction": 0.02,
                }
            },
        }

        def fake_project(*_args, **kwargs):
            kwargs["diagnostics"].update({
                "status": "ok",
                "all_failed": False,
                "roster_count": 1,
                "attempted_count": 1,
                "projected_count": 1,
                "failed_count": 0,
            })
            return [dict(row)]

        with patch.object(
            self.loader, "get_games_for_date_fresh", return_value=[live_game]
        ), patch.object(app_module, "project_team", side_effect=fake_project):
            response = self.client.get(
                f"/cheat-sheet?team=DAL&date={date.today().isoformat()}"
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertTrue(payload["warnings"])
        for projection in payload["projections"]:
            self.assertFalse(projection["actionable"])
            self.assertFalse(projection["prediction_eligible"])
            self.assertIsNone(projection["direction"])
            self.assertEqual(projection["kelly_fraction"], 0.0)

    def test_api_method_and_health_contracts(self):
        response = self.client.get("/predict")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers["Allow"], "POST")

        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
