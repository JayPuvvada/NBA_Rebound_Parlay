"""Price-aware recommendation and market-normalization helpers."""

from __future__ import annotations

import math
from typing import Any

from src.utils import ev_roi, implied_prob_from_american, kelly_criterion


MIN_TREND_GAMES = 6
MIN_STRONG_GAMES = 8
MIN_TIER_PROJECTION = 3.0
MIN_ACTIONABLE_EV = 0.02

ACTIONABLE_TIERS = {
    "STRONG PLAY",
    "PLAY",
    "TREND LEAN",
    "LEAN",
    "HIGH-VARIANCE LEAN",
}


def _probability(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a probability in [0, 1]") from exc
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError(f"{name} must be a probability in [0, 1]")
    return result


def weighted_hit_rate(trend_data, line, direction):
    """Return a recency-weighted, push-excluded historical hit rate.

    ``trend_data`` is expected oldest-to-newest. Invalid observations are
    ignored. The returned sample count includes all valid games, while integer
    pushes do not enter the hit-rate denominator.
    """
    if not trend_data or line is None or direction not in ("OVER", "UNDER"):
        return 0.0, 0
    try:
        line = float(line)
    except (TypeError, ValueError, OverflowError):
        return 0.0, 0
    if not math.isfinite(line):
        return 0.0, 0

    valid_values = []
    for game in trend_data:
        if not isinstance(game, dict):
            continue
        try:
            rebounds = float(game.get("rebounds"))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(rebounds):
            valid_values.append(rebounds)

    hit_weight = 0.0
    settled_weight = 0.0
    n = len(valid_values)
    for i, rebounds in enumerate(valid_values):
        weight = 0.5 + (i / max(1, n - 1)) if n > 1 else 1.0
        if math.isclose(rebounds, line, abs_tol=1e-9):
            continue
        settled_weight += weight
        if (direction == "OVER" and rebounds > line) or (
            direction == "UNDER" and rebounds < line
        ):
            hit_weight += weight

    return (hit_weight / settled_weight if settled_weight else 0.0), n


def tier_from_signals(
    confidence,
    direction,
    line,
    floor_val,
    hit_rate,
    n_games,
    mean_proj=None,
    *,
    ev_roi=None,
    edge=None,
    high_variance=False,
    odds_available=None,
    push_probability=0.0,
):
    """Return a coherent, EV-gated recommendation tier and UI color.

    Confidence alone can never create a bet. Every actionable tier requires an
    offered price, positive expected value above a noise floor, and at least six
    historical observations. High-variance distributions are capped at a lean.

    ``floor_val`` remains in the signature for older callers but is intentionally
    not used as a separate "safe" rule: falling outside a predictive interval is
    already represented in confidence, and no wager is intrinsically safe.
    """
    del floor_val, push_probability
    if direction not in ("OVER", "UNDER") or line is None:
        return "AVOID", "red"
    try:
        confidence = _probability(confidence, "confidence")
        hit_rate = _probability(hit_rate, "hit_rate")
        games = int(n_games)
        projection = float(mean_proj) if mean_proj is not None else None
    except (ValueError, TypeError, OverflowError):
        return "AVOID", "red"

    if projection is not None and (not math.isfinite(projection) or projection < MIN_TIER_PROJECTION):
        return "LOW_VOLUME", "gray"
    if games < MIN_TREND_GAMES:
        return "INSUFFICIENT_DATA", "gray"
    if odds_available is False or ev_roi is None:
        return "NO_PRICE", "gray"

    try:
        expected_roi = float(ev_roi)
        price_edge = float(edge) if edge is not None else expected_roi
    except (TypeError, ValueError, OverflowError):
        return "AVOID", "red"
    if not math.isfinite(expected_roi) or not math.isfinite(price_edge):
        return "AVOID", "red"
    if expected_roi < MIN_ACTIONABLE_EV or price_edge <= 0:
        return "AVOID", "red"

    if high_variance:
        if expected_roi >= 0.06 and confidence >= 0.56 and price_edge >= 0.025:
            return "HIGH-VARIANCE LEAN", "yellow"
        return "AVOID", "red"

    if (
        games >= MIN_STRONG_GAMES
        and expected_roi >= 0.10
        and confidence >= 0.60
        and price_edge >= 0.05
    ):
        return "STRONG PLAY", "green"
    if expected_roi >= 0.05 and confidence >= 0.56 and price_edge >= 0.025:
        return "PLAY", "green"
    if (
        games >= MIN_STRONG_GAMES
        and expected_roi >= 0.025
        and confidence >= 0.52
        and hit_rate >= 0.70
    ):
        return "TREND LEAN", "purple"
    if expected_roi >= MIN_ACTIONABLE_EV and confidence >= 0.53:
        return "LEAN", "yellow"
    return "AVOID", "red"


def edge_from_odds(confidence, american_odds, p_push=0.0):
    """Return push-aware price, edge, EV, and quarter-Kelly metrics.

    Missing odds stay missing; fabricating -110 would turn a probability opinion
    into a wager without knowing whether the wager is profitable.
    """
    win_probability = _probability(confidence, "confidence")
    push_probability = _probability(p_push, "p_push")
    if win_probability + push_probability > 1 + 1e-12:
        raise ValueError("win and push probabilities must sum to at most 1")
    if american_odds is None:
        return {
            "american_odds": None,
            "implied_probability": None,
            "implied_prob": None,
            "break_even_probability": None,
            "edge": None,
            "ev_roi": None,
            "kelly_fraction": 0.0,
            "kelly_stake": 0.0,
        }

    odds = float(american_odds)
    implied = implied_prob_from_american(odds)
    # If pushes are possible, a smaller unconditional win probability is needed
    # to break even because the stake is returned on that outcome.
    break_even = implied * (1.0 - push_probability)
    expected_roi = ev_roi(win_probability, odds, push_probability)
    kelly = kelly_criterion(win_probability, odds, push_probability)
    odds_out = int(odds) if odds.is_integer() else odds
    return {
        "american_odds": odds_out,
        "implied_probability": implied,
        "implied_prob": implied,
        "break_even_probability": break_even,
        "edge": win_probability - break_even,
        "ev_roi": expected_roi,
        "kelly_fraction": kelly,
        "kelly_stake": kelly,
    }


def _normalize_quote(value: Any, inherited: dict | None = None) -> dict | None:
    if not isinstance(value, dict):
        return None
    inherited = inherited or {}
    line = value.get("line", value.get("point", inherited.get("line", inherited.get("point"))))
    odds = value.get("odds", value.get("price", inherited.get("odds", inherited.get("price"))))
    try:
        line = float(line)
        odds_float = float(odds)
        implied_prob_from_american(odds_float)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(line) or line < 0:
        return None
    return {
        "line": line,
        "odds": int(odds_float) if odds_float.is_integer() else odds_float,
        "book": value.get("book", value.get("bookmaker", inherited.get("book", inherited.get("bookmaker")))),
        "source": value.get("source", inherited.get("source")),
        "updated_at": value.get(
            "updated_at",
            value.get(
                "fetched_at",
                inherited.get("updated_at", inherited.get("fetched_at")),
            ),
        ),
    }


def normalize_prop_odds(odds_entry: Any) -> dict[str, dict | None]:
    """Normalize current and legacy rebound-prop odds into side-specific quotes.

    Preferred input::

        {"over": {"line": 8.5, "odds": -105, "book": "FanDuel"},
         "under": {"line": 8.5, "odds": -115, "book": "FanDuel"}}

    A legacy flat quote is treated as OVER-only because the old loader stored
    only the Over outcome. This prevents accidentally pricing an Under bet with
    the Over price.
    """
    normalized = {"over": None, "under": None}
    if not isinstance(odds_entry, dict):
        return normalized

    for side in ("over", "under"):
        nested = odds_entry.get(side, odds_entry.get(side.upper(), odds_entry.get(side.title())))
        quote = _normalize_quote(nested, odds_entry)
        if quote:
            normalized[side] = quote

    if normalized["over"] is None and normalized["under"] is None:
        side = str(odds_entry.get("side", odds_entry.get("direction", "OVER"))).upper()
        target = "under" if side == "UNDER" else "over"
        normalized[target] = _normalize_quote(odds_entry)
    return normalized


def select_best_bet(candidates, *, actionable_only=False):
    """Select the highest-EV offered side.

    ``actionable_only=True`` is for recommendation callers after tier assignment;
    it prevents a larger but low-quality apparent edge from masking a smaller
    positive-EV side that passed every evidence gate.  The default preserves the
    legacy price-comparison helper behavior for tierless candidate dictionaries.
    """
    valid = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        if actionable_only and not is_actionable_tier(candidate.get("tier")):
            continue
        try:
            roi = float(candidate.get("ev_roi"))
            confidence = float(candidate.get("confidence"))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(roi) and math.isfinite(confidence) and roi > 0:
            valid.append(candidate)
    if not valid:
        return None
    return max(valid, key=lambda item: (float(item["ev_roi"]), float(item["confidence"])))


def is_actionable_tier(tier: str | None) -> bool:
    return tier in ACTIONABLE_TIERS
