"""Read-only preseason input audit; does not generate a betting recommendation.

Run from the repository root: python3 -m scripts.check_preseason --player 'Nikola Jokic' --date 2025-10-18
"""
import argparse
import json

import pandas as pd
from dotenv import load_dotenv

from src.data_loader import NBADataLoader, _parse_iso_date
from src.features import _clean_minutes
from src.utils import current_season, normalize_name


def unique_players(players):
    seen = set()
    result = []
    for player in players:
        cleaned = ' '.join(player.split())
        key = normalize_name(cleaned)
        if not key:
            raise ValueError('Player names must not be blank')
        if key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def summarize(frame):
    if frame.empty:
        return {'status': 'empty', 'games': 0}
    if not {'MIN', 'REB'}.issubset(frame.columns):
        return {'status': 'missing_columns', 'games': len(frame)}
    minutes = frame['MIN'].apply(_clean_minutes)
    rebounds = pd.to_numeric(frame['REB'], errors='coerce')
    valid = minutes.gt(0) & rebounds.ge(0) & minutes.le(60) & rebounds.le(100)
    if not valid.any():
        return {'status': 'no_usable_appearances', 'games': 0}
    return {'status': 'available', 'games': int(valid.sum()),
            'minutes_per_game': round(float(minutes[valid].mean()), 2),
            'rebounds_per_game': round(float(rebounds[valid].mean()), 2),
            'rebounds_per_minute': round(float(rebounds[valid].sum() / minutes[valid].sum()), 4)}


def audit_player(player, date, evaluate=False):
    day = _parse_iso_date(date)
    season = current_season(day)
    year = int(season[:4])
    prior = f'{year - 1}-{str(year)[-2:]}'
    report = {'player': player, 'as_of': day.isoformat(), 'season': season,
              'prior_season': prior, 'analysis_only': True,
              'note': 'Separate observed samples, not a blend or preseason minutes forecast.'}
    loader = NBADataLoader(season=season)
    samples = {}
    pid = loader.get_player_id(player)
    if pid is None:
        return {**report, 'status': 'player_not_found'}
    for label, source in [('preseason', loader), ('prior_season', NBADataLoader(season=prior))]:
        source.set_request_budget(15)
        try:
            frame = (source.get_preseason_player_gamelog(pid, as_of=date) if label == 'preseason'
                     else source._prepare_gamelog(source.get_player_gamelog(pid), date))
            report[label + '_history'] = {**summarize(frame), 'source': source.get_data_source_metadata()}
            samples[label] = frame
        except Exception as exc:
            report[label + '_history'] = {'status': 'source_failed', 'error_type': type(exc).__name__}
        finally:
            source.set_request_budget(None)
    if evaluate:
        if len(samples) == 2:
            from src.preseason_evaluation import evaluate_preseason
            empty_samples = [name for name, frame in samples.items() if frame.empty]
            if empty_samples:
                report['evaluation'] = {'status': 'empty_history', 'empty_samples': empty_samples,
                                        'analysis_only': True}
            else:
                try:
                    report['evaluation'] = evaluate_preseason(samples['prior_season'], samples['preseason'])
                except ValueError as exc:
                    report['evaluation'] = {'status': 'invalid_inputs', 'reason': str(exc),
                                            'analysis_only': True}
        else:
            report['evaluation'] = {'status': 'source_failed', 'analysis_only': True}
    return report


def aggregate_reports(reports):
    rows = [row for report in reports for row in report.get('evaluation', {}).get('games', [])]
    n = len(rows)
    evaluated_players = sum(bool(r.get('evaluation', {}).get('games')) for r in reports)
    unavailable = []
    for report in reports:
        evaluation = report.get('evaluation', {})
        if not evaluation.get('games'):
            unavailable.append({'player': report['player'], 'reason':
                                evaluation.get('status') or report.get('status') or
                                ('no_evaluable_games' if evaluation else 'evaluation_not_requested')})
    return {'requested_players': len(reports), 'evaluated_games': n,
            'evaluated_players': evaluated_players,
            'coverage_status': ('no_evaluated_games' if not n else
                                'partial' if evaluated_players < len(reports) else 'all_players_evaluated'),
            'unavailable_samples': unavailable,
            'players_without_evaluated_games': [r['player'] for r in reports if not r.get('evaluation', {}).get('games')],
            'mae': sum(abs(row['error']) for row in rows) / n if n else None,
            'naive_prior_mae': sum(abs(row['naive_prior_projection'] - row['actual']) for row in rows) / n if n else None,
            'analysis_only': True, 'note': 'Exploratory selected-player sample, not production-model validation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--player', required=True, action='append', help='Repeat for multiple players')
    parser.add_argument('--date', required=True)
    parser.add_argument('--evaluate', action='store_true', help='Evaluate a diagnostic walk-forward baseline, not betting picks')
    args = parser.parse_args()
    try:
        date = _parse_iso_date(args.date).isoformat()
        players = unique_players(args.player)
    except ValueError as exc:
        parser.error(str(exc))
    load_dotenv('.env')
    reports = [audit_player(player, date, args.evaluate) for player in players]
    output = reports[0] if len(reports) == 1 else {'players': reports, 'aggregate': aggregate_reports(reports)}
    print(json.dumps(output, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
