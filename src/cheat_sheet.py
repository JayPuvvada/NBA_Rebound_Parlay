"""Side-effect-free cheat-sheet projection pipeline."""

from __future__ import annotations

import math
from collections.abc import MutableMapping
from datetime import datetime, timezone

from src.recommendation import (
    edge_from_odds,
    is_actionable_tier,
    normalize_prop_odds,
    select_best_bet,
    tier_from_signals,
    weighted_hit_rate,
)
from src.utils import get_logger, normalize_name


log = get_logger("cheat_sheet")
MAX_FAILURE_SAMPLES = 10


def _new_diagnostics(team_id, team_abbr):
    return {
        "team_id": team_id,
        "team": team_abbr,
        "status": "initializing",
        "roster_count": 0,
        "attempted_count": 0,
        "projected_count": 0,
        "projection_error_count": 0,
        "exception_count": 0,
        "failed_count": 0,
        "empty_roster": False,
        "all_failed": False,
        "failure_samples": [],
    }


def _publish_diagnostics(target, stats):
    if target is None:
        return
    if not isinstance(target, MutableMapping):
        raise TypeError("diagnostics must be a mutable mapping")
    target.clear()
    target.update(stats)


def _add_failure_sample(stats, player, category, detail=None):
    if len(stats["failure_samples"]) >= MAX_FAILURE_SAMPLES:
        return
    sample = {"player": str(player), "category": category}
    if detail:
        sample["detail"] = str(detail)[:300]
    stats["failure_samples"].append(sample)


def _finish_diagnostics(stats, results):
    stats["projected_count"] = len(results)
    stats["failed_count"] = stats["projection_error_count"] + stats["exception_count"]
    stats["all_failed"] = stats["attempted_count"] > 0 and not results
    if stats["empty_roster"]:
        stats["status"] = "empty_roster"
    elif stats["all_failed"]:
        stats["status"] = "all_failed"
    elif stats["failed_count"]:
        stats["status"] = "partial_failure"
    else:
        stats["status"] = "ok"


def _finite_spread(spread):
    if spread is None:
        return 0.0, False
    try:
        value = float(spread)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("spread must be a finite number") from exc
    if not math.isfinite(value):
        raise ValueError("spread must be a finite number")
    return value, True


def _variance_metadata(sim_result):
    params = sim_result["params"]
    metadata = {
        "distribution": params.get("distribution"),
        "fano": params.get("fano"),
        "fano_source": params.get("fano_source"),
        "high_variance_flag": bool(params.get("high_variance_flag", False)),
        "variance": params.get("variance"),
        "standard_deviation": params.get("distribution_std"),
        "empirical_fano_raw": params.get("empirical_fano_raw"),
        "empirical_weight": params.get("empirical_weight"),
        "empirical_games": params.get("empirical_games"),
        "simulation_sample_size": params.get("sample_size"),
        "market_anchored": bool(params.get("market_anchored", False)),
    }
    metadata.update(
        {
            "source": metadata["fano_source"],
            "high_variance": metadata["high_variance_flag"],
            "sample_size": metadata["empirical_games"],
        }
    )
    return metadata


def _candidate_for_side(simulator, sim_result, side, quote):
    probabilities = simulator.get_probabilities(sim_result, quote["line"])
    key = "over_probability" if side == "OVER" else "under_probability"
    confidence = probabilities[key]
    price = edge_from_odds(confidence, quote["odds"], probabilities["push_probability"])
    return {
        "side": side,
        "line": quote["line"],
        "odds": quote["odds"],
        "book": quote.get("book"),
        "source": quote.get("source"),
        "updated_at": quote.get("updated_at"),
        "confidence": confidence,
        "probabilities": probabilities,
        **price,
    }


def _candidate_sort_key(candidate):
    roi = candidate.get("ev_roi")
    confidence = candidate.get("confidence")
    return (
        float(roi) if roi is not None else float("-inf"),
        float(confidence) if confidence is not None else float("-inf"),
    )


def project_team(
    loader,
    engineer,
    simulator,
    team_id,
    team_abbr,
    opp_abbr,
    is_home,
    team_rest,
    opp_rest,
    player_odds,
    date_str=None,
    spread=None,
    *,
    record_predictions=False,
    ledger=None,
    diagnostics=None,
):
    """Build price-aware rebound projections for every rostered player.

    The function performs no ledger writes unless ``record_predictions=True``.
    ``spread`` is from the projected player's team perspective; callers should
    invert a home-side spread for the away team.
    """
    stats = _new_diagnostics(team_id, team_abbr)
    # Validate the opt-in sink before doing expensive upstream work.
    _publish_diagnostics(diagnostics, stats)
    spread_value, spread_available = _finite_spread(spread)
    generated_at = datetime.now(timezone.utc).isoformat()
    roster = loader.get_team_roster(team_id)
    if roster is None or roster.empty:
        stats["empty_roster"] = True
        _finish_diagnostics(stats, [])
        _publish_diagnostics(diagnostics, stats)
        return []
    stats["roster_count"] = len(roster)
    player_odds = player_odds if isinstance(player_odds, dict) else {}

    active_ledger = ledger
    if record_predictions and active_ledger is None:
        from src.ledger import PredictionLedger

        active_ledger = PredictionLedger()

    results = []
    for _, row in roster.iterrows():
        pid = row["PLAYER_ID"]
        pname = row["PLAYER"]
        stats["attempted_count"] += 1
        try:
            proj_data = engineer.compute_composite_projection(
                pid,
                opp_abbr,
                spread=spread_value,
                home_game=is_home,
                days_rest=team_rest,
                opp_days_rest=opp_rest,
                as_of_date=date_str,
            )
            if not proj_data or "error" in proj_data:
                stats["projection_error_count"] += 1
                detail = (
                    proj_data.get("error", "projection returned no data")
                    if isinstance(proj_data, dict)
                    else "projection returned no data"
                )
                _add_failure_sample(stats, pname, "projection_unavailable", detail)
                continue

            mean_proj = float(proj_data["projection"])
            projection_metadata = dict(proj_data.get("metadata") or {})
            eligibility_signal = projection_metadata.get("prediction_eligible")
            prediction_eligible = eligibility_signal is True
            limitations = list(projection_metadata.get("limitations") or [])
            if eligibility_signal is not True and eligibility_signal is not False:
                limitations.append(
                    "projection safety metadata did not explicitly authorize a live pick"
                )
            projection_metadata["prediction_eligible"] = prediction_eligible
            projection_metadata["limitations"] = list(dict.fromkeys(limitations))
            limitations = projection_metadata["limitations"]
            sim_result = simulator.simulate(
                proj_data,
                player_variance=proj_data.get("player_variance"),
            )
            variance = _variance_metadata(sim_result)
            # Predictive intervals do not depend on the requested line.
            interval_info = simulator.get_probabilities(sim_result, max(0.0, mean_proj))

            odds_entry = player_odds.get(normalize_name(pname), {})
            market_odds = normalize_prop_odds(odds_entry)
            candidates = []
            if market_odds["over"] is not None:
                candidates.append(_candidate_for_side(simulator, sim_result, "OVER", market_odds["over"]))
            if market_odds["under"] is not None:
                candidates.append(_candidate_for_side(simulator, sim_result, "UNDER", market_odds["under"]))

            trend = proj_data.get("trend_data", [])
            for candidate in candidates:
                candidate_hit_rate, candidate_games = weighted_hit_rate(
                    trend, candidate["line"], candidate["side"]
                )
                candidate_tier, candidate_color = tier_from_signals(
                    candidate["confidence"],
                    candidate["side"],
                    candidate["line"],
                    candidate["probabilities"]["ci_68"][0],
                    candidate_hit_rate,
                    candidate_games,
                    mean_proj=mean_proj,
                    ev_roi=candidate["ev_roi"],
                    edge=candidate["edge"],
                    high_variance=variance["high_variance_flag"],
                    odds_available=True,
                    push_probability=candidate["probabilities"]["push_probability"],
                )
                candidate.update(
                    {
                        "hit_rate": candidate_hit_rate,
                        "hit_rate_games": candidate_games,
                        "tier": candidate_tier,
                        "tier_color": candidate_color,
                    }
                )
                if not prediction_eligible:
                    candidate["tier"] = "HISTORICAL_CONTEXT_INCOMPLETE"
                    candidate["tier_color"] = "gray"
                    candidate["kelly_fraction"] = 0.0
                    candidate["kelly_stake"] = 0.0

            selected = select_best_bet(candidates, actionable_only=True)
            evaluated = selected or (max(candidates, key=_candidate_sort_key) if candidates else None)

            tier = evaluated.get("tier") if evaluated else None
            tier_color = evaluated.get("tier_color") if evaluated else None
            hit_rate = evaluated.get("hit_rate") if evaluated else None
            hit_rate_games = evaluated.get("hit_rate_games", 0) if evaluated else 0
            if not prediction_eligible:
                tier, tier_color = "HISTORICAL_CONTEXT_INCOMPLETE", "gray"
            direction = (
                selected["side"]
                if selected and prediction_eligible and is_actionable_tier(tier)
                else None
            )

            probabilities = evaluated["probabilities"] if evaluated else None
            line = evaluated["line"] if evaluated else None
            american_odds = evaluated["american_odds"] if evaluated else None
            bookmaker = evaluated.get("book") if evaluated else None
            odds_side = evaluated["side"] if evaluated else None
            confidence = evaluated["confidence"] if evaluated else None
            implied_probability = evaluated["implied_probability"] if evaluated else None
            break_even_probability = evaluated["break_even_probability"] if evaluated else None
            edge = evaluated["edge"] if evaluated else None
            expected_roi = evaluated["ev_roi"] if evaluated else None
            kelly_fraction = evaluated["kelly_fraction"] if evaluated else 0.0
            actionable = direction is not None
            side_evaluations = {
                candidate["side"].lower(): {
                    "direction": candidate["side"],
                    "confidence": candidate["confidence"],
                    "hit_rate": candidate["hit_rate"],
                    "hit_rate_games": candidate["hit_rate_games"],
                    "tier": candidate["tier"],
                    "tier_color": candidate["tier_color"],
                    "american_odds": candidate["american_odds"],
                    "implied_probability": candidate["implied_probability"],
                    "break_even_probability": candidate["break_even_probability"],
                    "edge": candidate["edge"],
                    "ev_roi": candidate["ev_roi"],
                    "kelly_fraction": candidate["kelly_fraction"],
                }
                for candidate in candidates
            }

            rest_note = "Home" if is_home else "Away"
            if team_rest == 0:
                rest_note += " B2B"

            injuries = {
                "matchup": proj_data.get("matchup_injury"),
                "team": proj_data.get("team_injury"),
                "team_list": proj_data.get("team_injury_list", []),
                "opp_list": proj_data.get("opp_injury_list", []),
            }
            prediction_range = {
                "low": interval_info["ci_68"][0],
                "high": interval_info["ci_68"][1],
                "nominal_coverage": 0.68,
                "actual_coverage": interval_info["ci_68_coverage"],
                "method": interval_info["interval_method"],
            }

            summary = None
            if evaluated is not None:
                summary_data = dict(proj_data)
                summary_data.update(
                    {
                        "player": pname,
                        "projection": mean_proj,
                        "tier": tier,
                        "direction": direction or "NO BET",
                        "confidence": confidence,
                        "edge": edge,
                        "ev_roi": expected_roi,
                    }
                )
                summary = engineer.generate_pick_summary(summary_data, line)

            entry = {
                "player_id": int(pid),
                "player": pname,
                "team": team_abbr,
                "opponent": opp_abbr,
                "is_home": bool(is_home),
                "home_game": bool(is_home),
                "game_date": date_str,
                "date": date_str,
                "season": getattr(loader, "season", None),
                "generated_at": generated_at,
                "projection": round(mean_proj, 2),
                "projection_unit": "rebounds",
                "line": line,
                "direction": direction,
                "evaluated_side": odds_side,
                "odds_side": odds_side,
                "american_odds": american_odds,
                "bookmaker": bookmaker,
                "book": bookmaker,
                "odds_source": evaluated.get("source") if evaluated else None,
                "odds_updated_at": evaluated.get("updated_at") if evaluated else None,
                "market_odds": market_odds,
                "side_evaluations": side_evaluations,
                "tier": tier,
                "tier_color": tier_color,
                "actionable": actionable,
                "prediction_eligible": prediction_eligible,
                "limitations": limitations,
                "over_probability": probabilities["over_probability"] if probabilities else None,
                "under_probability": probabilities["under_probability"] if probabilities else None,
                "push_probability": probabilities["push_probability"] if probabilities else None,
                "confidence": confidence,
                "implied_probability": implied_probability,
                "break_even_probability": break_even_probability,
                "edge": edge,
                "ev_roi": expected_roi,
                "kelly_fraction": kelly_fraction,
                "hit_rate": hit_rate,
                "hit_rate_games": hit_rate_games,
                "probability_unit": "fraction",
                "ev_roi_unit": "fraction_per_unit_staked",
                "kelly_unit": "bankroll_fraction",
                "range": prediction_range,
                "prediction_interval_68": interval_info["ci_68"],
                "prediction_interval_95": interval_info["ci_95"],
                "variance": variance,
                "rest_note": rest_note,
                "rest_days": team_rest,
                "opponent_rest_days": opp_rest,
                "spread": spread_value,
                "spread_available": spread_available,
                "context": proj_data.get("matchup_context", ""),
                "injuries": injuries,
                "components": proj_data.get("components", {}),
                "trend": proj_data.get("trend_data", []),
                "data_freshness": proj_data.get("data_freshness"),
                "metadata": projection_metadata,
                "summary": summary,
                # Compatibility aliases; all remain raw fractions.
                "over_prob": probabilities["over_probability"] if probabilities else None,
                "under_prob": probabilities["under_probability"] if probabilities else None,
                "push_prob": probabilities["push_probability"] if probabilities else None,
                "implied_prob": implied_probability,
                "kelly_stake": kelly_fraction,
                "edge_raw": edge,
            }

            if record_predictions and active_ledger is not None and actionable:
                active_ledger.record_prediction(
                    game_date=date_str or generated_at[:10],
                    player=pname,
                    team=team_abbr,
                    opponent=opp_abbr,
                    is_home=is_home,
                    projection=mean_proj,
                    line=line,
                    american_odds=american_odds,
                    direction=direction,
                    tier=tier,
                    confidence=confidence,
                    over_prob=probabilities["over_probability"],
                    under_prob=probabilities["under_probability"],
                    push_prob=probabilities["push_probability"],
                    ev_roi=expected_roi,
                    bookmaker=bookmaker,
                    odds_side=odds_side,
                    implied_prob=implied_probability,
                    edge=edge,
                    kelly_fraction=kelly_fraction,
                    input_snapshot={
                        "components": entry["components"],
                        "injuries": injuries,
                        "rest_days": team_rest,
                        "opponent_rest_days": opp_rest,
                        "spread": spread_value,
                        "spread_available": spread_available,
                        "market_odds": market_odds,
                        "variance": variance,
                    },
                )

            results.append(entry)
        except Exception as err:
            stats["exception_count"] += 1
            _add_failure_sample(stats, pname, type(err).__name__)
            log.warning(f"Skipping {pname}: {err}")

    results.sort(
        key=lambda item: (
            not item["actionable"],
            -(item["ev_roi"] if item["ev_roi"] is not None else float("-inf")),
            -(item["confidence"] if item["confidence"] is not None else float("-inf")),
            -item["projection"],
        )
    )
    _finish_diagnostics(stats, results)
    _publish_diagnostics(diagnostics, stats)
    return results


def project_team_with_diagnostics(*args, **kwargs):
    """Return ``(rows, diagnostics)`` without changing ``project_team`` callers."""
    if "diagnostics" in kwargs:
        raise TypeError("project_team_with_diagnostics manages the diagnostics argument")
    diagnostics = {}
    rows = project_team(*args, diagnostics=diagnostics, **kwargs)
    return rows, diagnostics
