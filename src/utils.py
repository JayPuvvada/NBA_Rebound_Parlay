import logging
import math
import os
import sys
from datetime import datetime, date
from zoneinfo import ZoneInfo

try:
    from unidecode import unidecode
except ImportError:
    def unidecode(s):
        return s


def normalize_name(name):
    return unidecode(name).lower().replace('.', '').strip()


def get_logger(name):
    logger = logging.getLogger(name)
    if not logger.handlers:
        level_name = os.environ.get('LOG_LEVEL', 'INFO').upper()
        level = getattr(logging, level_name, logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)s %(name)s: %(message)s',
            datefmt='%H:%M:%S'
        ))
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    return logger


def implied_prob_from_american(odds):
    """Breakeven implied probability from American odds (float)."""
    o = _validate_american_odds(odds)
    if o < 0:
        return abs(o) / (abs(o) + 100.0)
    return 100.0 / (o + 100.0)


def decimal_odds_from_american(odds: float) -> float:
    """Convert valid American odds to decimal odds."""
    o = _validate_american_odds(odds)
    return 1.0 + (100.0 / abs(o) if o < 0 else o / 100.0)


def _validate_american_odds(odds) -> float:
    if isinstance(odds, bool):
        raise ValueError("American odds must be a finite, non-zero number")
    try:
        value = float(odds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("American odds must be a finite, non-zero number") from exc
    if not math.isfinite(value) or -100 < value < 100:
        raise ValueError("American odds must be <= -100 or >= +100")
    return value


def _validate_outcome_probabilities(p_win: float, p_push: float = 0.0) -> tuple[float, float, float]:
    try:
        win = float(p_win)
        push = float(p_push)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("win and push probabilities must be finite numbers") from exc
    if not math.isfinite(win) or not math.isfinite(push):
        raise ValueError("win and push probabilities must be finite numbers")
    if win < 0 or push < 0 or win > 1 or push > 1 or win + push > 1 + 1e-12:
        raise ValueError("win and push probabilities must be in [0, 1] and sum to at most 1")
    loss = max(0.0, 1.0 - win - push)
    return win, push, loss


OUT_KEYWORDS = ('out', 'inactive', 'injured', 'nwt', 'ruled out')
TTE_KEYWORDS = ('questionable', 'day-to-day', 'gtd', 'game time decision', 'doubtful')

def injury_bucket(status: str) -> str:
    """Categorize an injury status into OUT, QUESTIONABLE, or ACTIVE."""
    s = status.lower()
    if any(k in s for k in OUT_KEYWORDS):
        return 'OUT'
    if any(k in s for k in TTE_KEYWORDS):
        return 'QUESTIONABLE'
    return 'ACTIVE'

def ev_roi(p_win: float, american_odds: float, p_push: float = 0.0) -> float:
    """Expected profit per unit staked, with the stake returned on a push."""
    if american_odds is None:
        return 0.0
    win, _push, loss = _validate_outcome_probabilities(p_win, p_push)
    profit_multiple = decimal_odds_from_american(american_odds) - 1.0
    return win * profit_multiple - loss

def kelly_criterion(p_win: float, american_odds: float, p_push: float = 0.0, fractional: float = 0.25) -> float:
    """Return fractional-Kelly bankroll sizing for a win/loss/push market.

    Pushes leave wealth unchanged. The full-Kelly solution therefore conditions
    on the bet settling as a win or loss before applying ``fractional``.
    """
    if american_odds is None:
        return 0.0
    win, _push, loss = _validate_outcome_probabilities(p_win, p_push)
    try:
        fraction = float(fractional)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("fractional Kelly multiplier must be between 0 and 1") from exc
    if not math.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ValueError("fractional Kelly multiplier must be between 0 and 1")

    settled_probability = win + loss
    if settled_probability == 0:
        return 0.0
    b = decimal_odds_from_american(american_odds) - 1.0
    full_kelly = (win * b - loss) / (b * settled_probability)
    return min(1.0, max(0.0, full_kelly * fraction))

def eastern_today() -> str:
    """Get the current date in the America/New_York timezone as YYYY-MM-DD."""
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()

def current_season(d: date = None) -> str:
    """Automatically detect the NBA season string (e.g., '2025-26') from a given date."""
    d = d or datetime.now(ZoneInfo("America/New_York")).date()
    y = d.year if d.month >= 10 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"
