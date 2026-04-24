import logging
import os
import sys

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
