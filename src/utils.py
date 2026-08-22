import logging
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
    o = float(odds)
    if o < 0:
        return abs(o) / (abs(o) + 100.0)
    return 100.0 / (o + 100.0)


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
    """Calculate the Expected Value ROI per unit staked."""
    if american_odds is None:
        return 0.0
    dec = 1 + (100 / abs(american_odds) if american_odds < 0 else american_odds / 100)
    p_loss = 1 - p_win - p_push
    return p_win * (dec - 1) - p_loss

def kelly_criterion(p_win: float, american_odds: float, p_push: float = 0.0, fractional: float = 0.25) -> float:
    """Calculate the Kelly Criterion recommended stake sizing (fraction of bankroll)."""
    if american_odds is None:
        return 0.0
    b = (100 / abs(american_odds) if american_odds < 0 else american_odds / 100)
    p_loss = 1 - p_win - p_push
    kelly = (p_win * b - p_loss) / b
    return max(0.0, kelly * fractional)

def eastern_today() -> str:
    """Get the current date in the America/New_York timezone as YYYY-MM-DD."""
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()

def current_season(d: date = None) -> str:
    """Automatically detect the NBA season string (e.g., '2025-26') from a given date."""
    d = d or datetime.now(ZoneInfo("America/New_York")).date()
    y = d.year if d.month >= 10 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"
