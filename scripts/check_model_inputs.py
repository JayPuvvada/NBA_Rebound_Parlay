"""Bounded, read-only diagnosis of model team inputs and warm cache reuse."""
import argparse
import json
import logging
import time


def check_inputs(loader, date):
    """Inspect only public status/shape; never serialize exception messages."""
    results = []
    for name in ('get_team_stats', 'get_team_advanced_stats', 'get_opponent_stats_per_game'):
        started = time.monotonic()
        try:
            frame = getattr(loader, name)(as_of=date)
            cold = time.monotonic() - started
            if frame.empty:
                results.append({'input': name, 'status': 'empty', 'rows': 0})
                continue
            warm_start = time.monotonic()
            repeated = getattr(loader, name)(as_of=date)
            results.append({'input': name, 'status': 'available', 'rows': len(frame),
                            'cold_seconds': round(cold, 3),
                            'warm_seconds': round(time.monotonic() - warm_start, 3),
                            'repeat_equal': frame.equals(repeated)})
        except Exception as exc:
            chain = []
            seen = set()
            while exc is not None and id(exc) not in seen and len(chain) < 4:
                seen.add(id(exc))
                chain.append(type(exc).__name__)
                exc = exc.__cause__
            results.append({'input': name, 'status': 'unavailable',
                            'elapsed_seconds': round(time.monotonic() - started, 3),
                            'exception_types': chain})
    return {'date': date, 'checks': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--budget', type=float, default=35)
    args = parser.parse_args()
    from src.data_loader import NBADataLoader, _parse_iso_date
    from src.utils import current_season
    try:
        date = _parse_iso_date(args.date)
    except ValueError:
        parser.error('date must be a valid YYYY-MM-DD calendar date')
    if not 1 <= args.budget <= 75:
        parser.error('budget must be between 1 and 75 seconds')
    logging.disable(logging.CRITICAL)
    loader = NBADataLoader(season=current_season(date))
    loader.set_request_budget(args.budget)
    report = check_inputs(loader, args.date)
    print(json.dumps(report, indent=2))
    return 0 if all(row['status'] == 'available' and row.get('repeat_equal') for row in report['checks']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
