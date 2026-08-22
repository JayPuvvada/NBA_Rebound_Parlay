"""
Tiering + edge logic shared between /predict and /cheat-sheet.
Extracted so the two endpoints can't drift.
"""
from src.utils import implied_prob_from_american, ev_roi, kelly_criterion

MIN_TREND_GAMES = 6       # weighted hit rate requires at least this many games
MIN_TIER_PROJECTION = 3.0 # projections below this are too noisy for tier calls


def weighted_hit_rate(trend_data, line, direction):
    """
    Recency-weighted hit rate. `trend_data` is oldest -> newest.
    Returns (rate, n_games).
    """
    if not trend_data or line is None:
        return 0.0, 0

    hit_weight = 0.0
    total_weight = 0.0
    n = len(trend_data)
    for i, game in enumerate(trend_data):
        # Linear ramp from 0.5 (oldest) to 1.5 (newest). Average weight = 1.0.
        w = 0.5 + (i / max(1, n - 1)) * 1.0 if n > 1 else 1.0
        total_weight += w
        hit = (direction == 'OVER' and game['rebounds'] > line) or \
              (direction == 'UNDER' and game['rebounds'] < line)
        if hit:
            hit_weight += w

    rate = hit_weight / total_weight if total_weight > 0 else 0.0
    return rate, n


def tier_from_signals(confidence, direction, line, floor_val, hit_rate, n_games,
                      mean_proj=None):
    """
    5-tier recommendation. Central so /predict and /cheat-sheet agree.
    Returns (tier, color).

    Thresholds raised from (0.635/0.585/0.555) to (0.68/0.62/0.58) because the
    old values were trivially breached by low-mean discrete NB distributions — any
    player projecting 1-2 rebounds below a .5 line looked like STRONG PLAY purely
    from CDF math, not real edge.

    A LOW_VOLUME gate prevents tiering for projections under MIN_TIER_PROJECTION
    (3.0 rebounds). Below that threshold the model's base projection is unreliable
    and market lines are highly efficient.
    """
    # Gate: too small a projection to make a reliable call.
    if mean_proj is not None and mean_proj < MIN_TIER_PROJECTION:
        return 'LOW_VOLUME', 'gray'

    if confidence > 0.68:
        return 'STRONG PLAY', 'green'
    if confidence > 0.62:
        return 'PLAY', 'green'
    if direction == 'OVER' and line is not None and line < floor_val:
        return 'SAFE PLAY', 'blue'
    if hit_rate >= 0.72 and n_games >= MIN_TREND_GAMES:
        return 'TREND LEAN', 'purple'
    if confidence > 0.58:
        return 'LEAN', 'yellow'
    return 'AVOID', 'red'


def edge_from_odds(confidence, american_odds):
    """
    Single source of truth for implied prob + edge.
    Defaults to -110 when no odds are supplied.
    """
    odds = american_odds if american_odds is not None else -110
    implied = implied_prob_from_american(odds)
    return {
        'american_odds': int(odds),
        'implied_prob': implied,
        'edge': confidence - implied,
        'ev_roi': ev_roi(confidence, odds),
        'kelly_stake': kelly_criterion(confidence, odds)
    }
