import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.recommendation import (
    MIN_TIER_PROJECTION,
    edge_from_odds,
    is_actionable_tier,
    normalize_prop_odds,
    select_best_bet,
    tier_from_signals,
    weighted_hit_rate,
)


def _games(rebounds):
    return [
        {"rebounds": value, "date": f"g{i}", "opponent": "XXX"}
        for i, value in enumerate(rebounds)
    ]


def _tier(
    confidence=0.60,
    *,
    direction="OVER",
    line=9.5,
    hit_rate=0.5,
    games=10,
    projection=10,
    expected_roi=0.08,
    edge=0.04,
    high_variance=False,
    odds_available=True,
    push_probability=0.0,
):
    return tier_from_signals(
        confidence,
        direction,
        line,
        6.0,
        hit_rate,
        games,
        mean_proj=projection,
        ev_roi=expected_roi,
        edge=edge,
        high_variance=high_variance,
        odds_available=odds_available,
        push_probability=push_probability,
    )


class WeightedHitRateTest(unittest.TestCase):
    def test_all_hits(self):
        rate, games = weighted_hit_rate(_games([10, 11, 12, 13, 14, 15]), 9.5, "OVER")
        self.assertEqual(rate, 1.0)
        self.assertEqual(games, 6)

    def test_recent_games_have_more_weight(self):
        recent_hits, _ = weighted_hit_rate(_games([3, 3, 3, 15, 15, 15]), 9.5, "OVER")
        old_hits, _ = weighted_hit_rate(_games([15, 15, 15, 3, 3, 3]), 9.5, "OVER")
        self.assertGreater(recent_hits, 0.5)
        self.assertLess(old_hits, 0.5)

    def test_pushes_are_excluded_from_rate(self):
        rate, games = weighted_hit_rate(_games([8, 8, 9]), 8, "OVER")
        self.assertEqual(rate, 1.0)
        self.assertEqual(games, 3)

    def test_invalid_observations_are_ignored(self):
        rate, games = weighted_hit_rate([{"rebounds": None}, {}, {"rebounds": 10}], 9.5, "OVER")
        self.assertEqual(rate, 1.0)
        self.assertEqual(games, 1)

    def test_invalid_rebound_counts_do_not_affect_rates_or_recency_weights(self):
        invalid = [-1, "-2", True, False, 9.5, "8.25", float("nan"), float("inf"), "DNP"]
        valid = [3, 15, 10]
        mixed = _games([valid[0], *invalid, valid[1], valid[2]])
        for direction in ("OVER", "UNDER"):
            with self.subTest(direction=direction):
                self.assertEqual(
                    weighted_hit_rate(mixed, 9.5, direction),
                    weighted_hit_rate(_games(valid), 9.5, direction),
                )

    def test_invalid_counts_cannot_satisfy_minimum_sample_gate(self):
        rate, games = weighted_hit_rate(_games([10, 11, 12, 13, 14, -1, True, 12.5]), 9.5, "OVER")
        self.assertEqual(games, 5)
        self.assertEqual(_tier(games=games, hit_rate=rate), ("INSUFFICIENT_DATA", "gray"))

    def test_numeric_string_counts_and_zero_are_valid_and_pushes_still_count(self):
        # A zero is an observed count, not a DNP. Pushes count toward the sample
        # but do not affect the settled hit-rate denominator.
        rate, games = weighted_hit_rate(_games([0, "0", "8", "8.0", "9"]), 8, "OVER")
        self.assertEqual(games, 5)
        self.assertAlmostEqual(rate, 1.5 / (0.5 + 0.75 + 1.5))

    def test_missing_inputs_are_empty(self):
        self.assertEqual(weighted_hit_rate([], 9.5, "OVER"), (0.0, 0))
        self.assertEqual(weighted_hit_rate(_games([10]), None, "OVER"), (0.0, 0))
        self.assertEqual(weighted_hit_rate(_games([10]), 9.5, "SIDEWAYS"), (0.0, 0))


class TierTest(unittest.TestCase):
    def test_invalid_numeric_signals_cannot_create_actionable_tiers(self):
        invalid = {
            "line": [True, False, "bogus", -1, float("nan"), float("inf")],
            "games": [True, False, -1, 8.9, "8.9", float("nan"), float("inf")],
            "confidence": [True, False, -0.1, 1.1, float("nan")],
            "hit_rate": [True, False, -0.1, 1.1],
            "projection": [True, False, -1, float("nan"), float("inf")],
            "expected_roi": [True, False, float("nan"), float("inf")],
            "edge": [True, False, 1.1, float("nan"), float("inf")],
            "odds_available": [0, 1, "false", "true"],
            "high_variance": [0, 1, "false", None],
            "push_probability": [True, False, -0.1, 1.1, float("nan"), .8],
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertEqual(_tier(**{field: value}), ("AVOID", "red"))

    def test_valid_numeric_strings_and_pushes_keep_existing_tiers(self):
        self.assertEqual(
            _tier(confidence="0.60", line="9", games="10.0", projection="10",
                  hit_rate="0.5", expected_roi="0.08", edge="0.04", push_probability="0.1"),
            ("PLAY", "green"),
        )
        self.assertEqual(_tier(odds_available=False), ("NO_PRICE", "gray"))

    def test_strong_play_requires_strong_probability_price_and_sample(self):
        tier, color = _tier(confidence=0.63, expected_roi=0.12, edge=0.06, games=10)
        self.assertEqual((tier, color), ("STRONG PLAY", "green"))

    def test_play_is_reachable(self):
        tier, _ = _tier(confidence=0.57, expected_roi=0.06, edge=0.03, games=6)
        self.assertEqual(tier, "PLAY")

    def test_trend_lean_is_reachable(self):
        tier, color = _tier(
            confidence=0.54, expected_roi=0.03, edge=0.01, hit_rate=0.75, games=8
        )
        self.assertEqual((tier, color), ("TREND LEAN", "purple"))

    def test_lean_is_reachable(self):
        tier, _ = _tier(confidence=0.54, expected_roi=0.025, edge=0.01, games=6)
        self.assertEqual(tier, "LEAN")

    def test_confidence_without_price_is_not_a_bet(self):
        tier, color = tier_from_signals(
            0.99, "OVER", 9.5, 2, 1, 10, mean_proj=10, ev_roi=None, edge=None
        )
        self.assertEqual((tier, color), ("NO_PRICE", "gray"))

    def test_negative_ev_is_avoid_even_at_high_confidence(self):
        tier, _ = _tier(confidence=0.90, expected_roi=-0.01, edge=-0.01)
        self.assertEqual(tier, "AVOID")

    def test_tiny_apparent_ev_is_treated_as_noise(self):
        tier, _ = _tier(confidence=0.60, expected_roi=0.019, edge=0.02)
        self.assertEqual(tier, "AVOID")

    def test_low_volume_gate(self):
        tier, color = _tier(
            confidence=0.99,
            projection=MIN_TIER_PROJECTION - 0.01,
            expected_roi=0.50,
            edge=0.30,
        )
        self.assertEqual((tier, color), ("LOW_VOLUME", "gray"))

    def test_inadequate_history_gate(self):
        tier, color = _tier(games=5, expected_roi=0.50, edge=0.30)
        self.assertEqual((tier, color), ("INSUFFICIENT_DATA", "gray"))

    def test_high_variance_caps_strong_signal_at_lean(self):
        tier, color = _tier(
            confidence=0.70,
            expected_roi=0.20,
            edge=0.10,
            high_variance=True,
        )
        self.assertEqual((tier, color), ("HIGH-VARIANCE LEAN", "yellow"))

    def test_high_variance_weak_signal_is_avoid(self):
        tier, _ = _tier(
            confidence=0.55,
            expected_roi=0.04,
            edge=0.02,
            high_variance=True,
        )
        self.assertEqual(tier, "AVOID")

    def test_only_real_tiers_are_actionable(self):
        self.assertTrue(is_actionable_tier("PLAY"))
        self.assertTrue(is_actionable_tier("HIGH-VARIANCE LEAN"))
        self.assertFalse(is_actionable_tier("AVOID"))
        self.assertFalse(is_actionable_tier("NO_PRICE"))
        self.assertFalse(is_actionable_tier(["PLAY"]))
        self.assertFalse(is_actionable_tier({"tier": "PLAY"}))


class EdgeTest(unittest.TestCase):
    def test_missing_price_stays_missing(self):
        info = edge_from_odds(0.60, None)
        self.assertIsNone(info["american_odds"])
        self.assertIsNone(info["implied_probability"])
        self.assertIsNone(info["edge"])
        self.assertIsNone(info["ev_roi"])
        self.assertEqual(info["kelly_fraction"], 0)

    def test_positive_odds(self):
        info = edge_from_odds(0.55, 150)
        self.assertAlmostEqual(info["implied_probability"], 0.40)
        self.assertAlmostEqual(info["edge"], 0.15)
        self.assertAlmostEqual(info["ev_roi"], 0.375)

    def test_push_adjusts_break_even_and_kelly(self):
        info = edge_from_odds(0.50, -110, p_push=0.10)
        self.assertAlmostEqual(info["break_even_probability"], (110 / 210) * 0.9)
        self.assertAlmostEqual(info["edge"], 0.50 - (110 / 210) * 0.9)
        self.assertGreater(info["kelly_fraction"], 0)

    def test_invalid_probability_partition_raises(self):
        with self.assertRaises(ValueError):
            edge_from_odds(0.95, -110, p_push=0.10)

    def test_boolean_probabilities_are_not_numeric_model_signals(self):
        for confidence, push in [(True, 0), (False, 0), (.6, True), (.6, False)]:
            with self.subTest(confidence=confidence, push=push):
                with self.assertRaises(ValueError):
                    edge_from_odds(confidence, -110, p_push=push)


class OddsNormalizationTest(unittest.TestCase):
    def test_download_time_is_never_a_quote_update_time(self):
        fetched = '2026-09-26T12:00:00Z'
        for entry in [
            {'line': 8.5, 'odds': -110, 'fetched_at': fetched},
            {'fetched_at': fetched, 'over': {'line': 8.5, 'odds': -110}},
            {'over': {'line': 8.5, 'odds': -110, 'fetched_at': fetched}},
        ]:
            with self.subTest(entry=entry):
                self.assertIsNone(normalize_prop_odds(entry)['over']['updated_at'])

    def test_nested_price_cannot_borrow_flat_over_price_or_resurrect_invalid_sides(self):
        for entry in [
            {'line': 8.5, 'odds': -110, 'under': {'line': 8.5}},
            {'line': 8.5, 'odds': -110, 'over': {'odds': None}},
            {'line': 8.5, 'odds': -110, 'under': None},
            {'line': 8.5, 'odds': -110, 'Under': {'odds': 0}},
        ]:
            with self.subTest(entry=entry):
                self.assertEqual(normalize_prop_odds(entry), {'over': None, 'under': None})

    def test_provider_update_and_shared_line_can_be_inherited_without_inheriting_price(self):
        market = normalize_prop_odds({
            'line': 8.5, 'odds': -110, 'updated_at': '2026-09-25T12:00:00Z',
            'under': {'odds': 105, 'fetched_at': '2026-09-26T12:00:00Z'},
        })
        self.assertEqual(market['under']['updated_at'], '2026-09-25T12:00:00Z')
        self.assertEqual(market['under']['line'], 8.5)
        self.assertEqual(market['under']['odds'], 105)
        self.assertIsNone(market['over'])

    def test_nested_two_sided_market(self):
        market = normalize_prop_odds(
            {
                "over": {"line": 8.5, "odds": -105, "book": "FanDuel"},
                "under": {"point": 8.5, "price": -115, "bookmaker": "FanDuel"},
            }
        )
        self.assertEqual(market["over"]["odds"], -105)
        self.assertEqual(market["under"]["odds"], -115)
        self.assertEqual(market["under"]["line"], 8.5)

    def test_legacy_flat_quote_is_over_only(self):
        market = normalize_prop_odds({"line": 8.5, "odds": -110, "book": "Legacy"})
        self.assertIsNotNone(market["over"])
        self.assertIsNone(market["under"])

    def test_explicit_flat_under_quote(self):
        market = normalize_prop_odds(
            {"line": 8.5, "odds": 105, "book": "Book", "side": "UNDER"}
        )
        self.assertIsNone(market["over"])
        self.assertEqual(market["under"]["odds"], 105)

    def test_invalid_quote_is_ignored(self):
        market = normalize_prop_odds({"over": {"line": -1, "odds": -110}})
        self.assertEqual(market, {"over": None, "under": None})

    def test_boolean_lines_are_not_normalized_into_real_quotes(self):
        for line in (True, False):
            self.assertEqual(normalize_prop_odds({'over': {'line': line, 'odds': -110}}),
                             {'over': None, 'under': None})

    def test_best_bet_uses_roi_not_probability(self):
        # Better price makes the lower-probability Under more valuable.
        candidates = [
            {"side": "OVER", "confidence": 0.60, "ev_roi": 0.02},
            {"side": "UNDER", "confidence": 0.55, "ev_roi": 0.20},
        ]
        self.assertEqual(select_best_bet(candidates)["side"], "UNDER")

    def test_no_positive_ev_means_no_selection(self):
        self.assertIsNone(
            select_best_bet([{"side": "OVER", "confidence": 0.7, "ev_roi": -0.01}])
        )

    def test_invalid_candidate_signals_cannot_mask_a_valid_play(self):
        valid = {"side": "UNDER", "confidence": .58, "ev_roi": .08, "tier": "PLAY"}
        invalid = [
            {"confidence": confidence} for confidence in
            [-.1, 1.1, True, False, float("nan"), float("inf")]
        ] + [{"ev_roi": True}, {"ev_roi": False}]
        for values in invalid:
            candidate = {"side": "OVER", "confidence": .7, "ev_roi": .9, "tier": "PLAY", **values}
            for actionable_only in (True, False):
                with self.subTest(values=values, actionable_only=actionable_only):
                    self.assertIsNone(select_best_bet([candidate], actionable_only=actionable_only))
                    self.assertIs(select_best_bet([candidate, valid], actionable_only=actionable_only), valid)

    def test_malformed_tier_is_not_actionable_and_does_not_crash_selection(self):
        candidate = {"side": "OVER", "confidence": .7, "ev_roi": .9, "tier": ["PLAY"]}
        self.assertIsNone(select_best_bet([candidate], actionable_only=True))

    def test_actionable_selection_does_not_let_larger_bad_signal_mask_play(self):
        candidates = [
            {
                "side": "OVER",
                "confidence": 0.40,
                "ev_roi": 0.40,
                "tier": "AVOID",
            },
            {
                "side": "UNDER",
                "confidence": 0.58,
                "ev_roi": 0.08,
                "tier": "PLAY",
            },
        ]
        self.assertEqual(
            select_best_bet(candidates, actionable_only=True)["side"], "UNDER"
        )


if __name__ == "__main__":
    unittest.main()
