"""Count-distribution model used by the rebound projection pipeline.

The feature model supplies an expected rebound count. This module turns that
expectation into a predictive distribution; it deliberately does not anchor to
the sportsbook line.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.stats import nbinom


class ReboundSimulator:
    """Negative-binomial predictive model for integer rebound totals.

    ``random_state`` may be an integer seed or a NumPy ``Generator``. The RNG
    only affects the diagnostic sample and sample summary. Market probabilities
    and prediction intervals are calculated exactly from the fitted
    distribution and are therefore deterministic.
    """

    FANO_MIN = 1.05
    FANO_MAX = 5.0
    HIGH_FANO_FLAG = 3.5
    EMPIRICAL_PRIOR_GAMES = 15.0
    MIN_EMPIRICAL_GAMES = 3

    def __init__(self, num_simulations: int = 10_000, random_state: Any = None):
        self.num_simulations = self._validate_sample_size(num_simulations)
        self._rng = self._make_rng(random_state)

    @staticmethod
    def _validate_sample_size(value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("num_simulations must be a positive integer")
        try:
            integer = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("num_simulations must be a positive integer") from exc
        if integer != value or integer <= 0:
            raise ValueError("num_simulations must be a positive integer")
        return integer

    @staticmethod
    def _make_rng(random_state: Any):
        if isinstance(random_state, (np.random.Generator, np.random.RandomState)):
            return random_state
        try:
            return np.random.default_rng(random_state)
        except (TypeError, ValueError) as exc:
            raise ValueError("random_state must be None, an integer seed, or a NumPy RNG") from exc

    @staticmethod
    def _finite_float(value: Any, name: str, *, minimum: float | None = None) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a finite number")
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{name} must be a finite number") from exc
        if not math.isfinite(result):
            raise ValueError(f"{name} must be a finite number")
        if minimum is not None and result < minimum:
            raise ValueError(f"{name} must be at least {minimum}")
        return result

    def fit_negative_binomial(self, mean: float, variance: float) -> tuple[float, float]:
        """Fit SciPy's ``nbinom(n, p)`` using method of moments."""
        mean = self._finite_float(mean, "mean", minimum=0.0)
        variance = self._finite_float(variance, "variance", minimum=0.0)
        if mean == 0:
            raise ValueError("a zero mean is degenerate and has no negative-binomial fit")

        variance = max(variance, mean * (1.0 + 1e-6))
        p = mean / variance
        n = (mean * mean) / (variance - mean)
        if not (math.isfinite(n) and n > 0 and 0 < p < 1):
            raise ValueError("mean and variance produced invalid negative-binomial parameters")
        return n, p

    @staticmethod
    def _volume_fano_floor(mean: float) -> float:
        if mean < 3.0:
            return 2.0
        if mean < 5.0:
            return 1.6
        if mean < 8.0:
            return 1.4
        return 1.2

    @staticmethod
    def _heuristic_fano(minutes: float) -> float:
        if minutes > 34:
            return 1.35
        if minutes > 28:
            return 1.28
        if minutes < 20:
            return 1.15
        return 1.20

    @staticmethod
    def _variance_sample_size(projection_data: dict, player_variance: dict) -> int | None:
        for key in ("sample_size", "games_played", "n_games"):
            value = player_variance.get(key)
            if value is not None:
                try:
                    value = int(value)
                except (TypeError, ValueError, OverflowError):
                    return None
                return value if value >= 0 else None
        trend = projection_data.get("trend_data")
        if isinstance(trend, (list, tuple)) and trend:
            return len(trend)
        return None

    def simulate(
        self,
        projection_data: dict,
        market_line: float | None = None,
        player_variance: dict | None = None,
        *,
        random_state: Any = None,
        num_simulations: int | None = None,
    ) -> dict:
        """Fit the predictive distribution and draw a diagnostic sample.

        ``market_line`` is accepted for API compatibility but never influences
        the projection or variance.
        """
        if not isinstance(projection_data, dict):
            raise ValueError("projection_data must be a mapping")
        model_mean = projection_data.get("projection", projection_data.get("mean_projection"))
        if model_mean is None:
            raise ValueError("Projection data missing 'projection' or 'mean_projection' key")
        final_mean = self._finite_float(model_mean, "projection", minimum=0.0)
        if market_line is not None:
            self._finite_float(market_line, "market_line", minimum=0.0)

        draws = self.num_simulations if num_simulations is None else self._validate_sample_size(num_simulations)
        rng = self._rng if random_state is None else self._make_rng(random_state)

        components = projection_data.get("components") or {}
        modifiers = projection_data.get("modifiers") or {}
        minutes_raw = components.get("Proj Minutes", modifiers.get("minutes", 30.0))
        try:
            minutes = self._finite_float(minutes_raw, "projected minutes", minimum=0.0)
        except ValueError:
            minutes = 30.0

        volume_floor = self._volume_fano_floor(final_mean)
        heuristic_fano = max(self._heuristic_fano(minutes), volume_floor)
        fano_factor = heuristic_fano
        fano_source = "heuristic"
        raw_empirical_fano = None
        empirical_weight = 0.0
        empirical_games = None
        high_variance_flag = False

        variance_data = player_variance if isinstance(player_variance, dict) else {}
        try:
            reb_var = self._finite_float(variance_data.get("reb_variance"), "reb_variance", minimum=0.0)
            reb_mean = self._finite_float(variance_data.get("reb_mean"), "reb_mean", minimum=0.0)
            empirical_valid = reb_mean > 0 and reb_var > 0
        except ValueError:
            empirical_valid = False

        if empirical_valid:
            raw_empirical_fano = reb_var / reb_mean
            empirical_games = self._variance_sample_size(projection_data, variance_data)
            if empirical_games is None:
                empirical_weight = 0.35
            elif empirical_games >= self.MIN_EMPIRICAL_GAMES:
                empirical_weight = empirical_games / (empirical_games + self.EMPIRICAL_PRIOR_GAMES)

            if empirical_weight > 0:
                high_variance_flag = raw_empirical_fano > self.HIGH_FANO_FLAG
                empirical_fano = min(self.FANO_MAX, max(self.FANO_MIN, raw_empirical_fano))
                empirical_fano = max(empirical_fano, volume_floor)
                fano_factor = (
                    empirical_weight * empirical_fano
                    + (1.0 - empirical_weight) * heuristic_fano
                )
                fano_factor = max(volume_floor, fano_factor)
                fano_source = "empirical"
            elif empirical_games is not None:
                fano_source = "heuristic_insufficient_sample"

        variance = final_mean * fano_factor
        if final_mean == 0:
            samples = np.zeros(draws, dtype=np.int64)
            n = None
            p = 1.0
            distribution = "degenerate"
            distribution_std = 0.0
        else:
            n, p = self.fit_negative_binomial(final_mean, variance)
            samples = rng.negative_binomial(n, p, draws)
            distribution = "negative_binomial"
            distribution_std = math.sqrt(variance)

        return {
            "mean_sim": float(np.mean(samples)),
            "std_sim": float(np.std(samples)),
            "samples": samples,
            "params": {
                "distribution": distribution,
                "n": n,
                "p": p,
                "final_mean": final_mean,
                "model_mean": final_mean,
                "variance": variance,
                "distribution_std": distribution_std,
                "fano": round(fano_factor, 6) if final_mean > 0 else None,
                "heuristic_fano": round(heuristic_fano, 6) if final_mean > 0 else None,
                "empirical_fano_raw": raw_empirical_fano,
                "empirical_weight": round(empirical_weight, 6),
                "empirical_games": empirical_games,
                "fano_source": fano_source,
                "high_variance_flag": high_variance_flag,
                "sample_size": draws,
                "market_anchored": False,
            },
        }

    @staticmethod
    def _interval_coverage(low: int, high: int, n: float, p: float) -> float:
        below = nbinom.cdf(low - 1, n, p) if low > 0 else 0.0
        return float(nbinom.cdf(high, n, p) - below)

    def get_probabilities(self, sim_result: dict, line: float) -> dict:
        """Return exact strict over/under/push probabilities and intervals."""
        line = self._finite_float(line, "line", minimum=0.0)
        if not isinstance(sim_result, dict) or not isinstance(sim_result.get("params"), dict):
            raise ValueError("sim_result is missing distribution parameters")
        params = sim_result["params"]

        if params.get("distribution") == "degenerate" or params.get("final_mean") == 0:
            over = 1.0 if 0 > line else 0.0
            under = 1.0 if 0 < line else 0.0
            ci_68 = [0, 0]
            ci_95 = [0, 0]
            coverage_68 = coverage_95 = 1.0
        else:
            try:
                n = self._finite_float(params.get("n"), "n", minimum=0.0)
                p = self._finite_float(params.get("p"), "p", minimum=0.0)
            except ValueError as exc:
                raise ValueError("sim_result contains invalid distribution parameters") from exc
            if n <= 0 or not 0 < p < 1:
                raise ValueError("sim_result contains invalid distribution parameters")

            floor_line = math.floor(line)
            ceil_line = math.ceil(line)
            over = float(nbinom.sf(floor_line, n, p))
            under = float(nbinom.cdf(ceil_line - 1, n, p))
            ci_68 = [int(x) for x in nbinom.ppf([0.16, 0.84], n, p)]
            ci_95 = [int(x) for x in nbinom.ppf([0.025, 0.975], n, p)]
            coverage_68 = self._interval_coverage(ci_68[0], ci_68[1], n, p)
            coverage_95 = self._interval_coverage(ci_95[0], ci_95[1], n, p)

        over = min(1.0, max(0.0, over))
        under = min(1.0, max(0.0, under))
        push = min(1.0, max(0.0, 1.0 - over - under))
        return {
            "over_probability": over,
            "under_probability": under,
            "push_probability": push,
            "ci_68": ci_68,
            "ci_95": ci_95,
            "ci_68_coverage": coverage_68,
            "ci_95_coverage": coverage_95,
            "interval_method": "exact_equal_tailed",
        }


if __name__ == "__main__":
    sim = ReboundSimulator(random_state=42)
    dummy_proj = {"mean_projection": 12.88}
    result = sim.simulate(dummy_proj)
    probabilities = sim.get_probabilities(result, 12.5)
    print(f"Mean Sim: {result['mean_sim']:.2f} (Input: {dummy_proj['mean_projection']})")
    print(f"Prob Over 12.5: {probabilities['over_probability']:.2%}")
    print(f"95% PI: {probabilities['ci_95']}")
