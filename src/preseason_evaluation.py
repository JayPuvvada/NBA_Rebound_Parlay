"""Walk-forward diagnostic baseline, not a deployed forecasting model."""
import math
import pandas as pd
from src.features import _clean_minutes


def _appearances(frame):
    if 'GAME_ID' not in frame.columns and 'Game_ID' in frame.columns:
        frame = frame.rename(columns={'Game_ID': 'GAME_ID'})
    required = {'GAME_DATE', 'MIN', 'REB', 'GAME_ID'}
    if not required.issubset(frame.columns):
        raise ValueError('Evaluation requires GAME_DATE, GAME_ID, MIN and REB')
    data = frame.copy(deep=True)
    data['GAME_ID'] = data['GAME_ID'].astype('string').str.strip()
    data['day'] = pd.to_datetime(data['GAME_DATE'], format='mixed', errors='coerce').dt.normalize()
    data['minutes'] = data['MIN'].apply(_clean_minutes)
    data['rebounds'] = pd.to_numeric(data['REB'], errors='coerce')
    data = data[data['day'].notna() & data['GAME_ID'].notna() & data['GAME_ID'].ne('')
                & data['minutes'].gt(0) & data['minutes'].le(60)
                & data['rebounds'].ge(0) & data['rebounds'].le(100)]
    if data['GAME_ID'].duplicated().any():
        raise ValueError('Duplicate game IDs would bias evaluation')
    return data.sort_values('day')


def evaluate_preseason(prior_frame, preseason_frame):
    """Predict later appearances using earlier preseason minutes and prior rates.

    First preseason appearances are skipped, not assigned a guessed minute load.
    No target-game minutes, rebounds, injuries or odds enter the prediction.
    """
    prior, preseason = _appearances(prior_frame), _appearances(preseason_frame)
    if set(prior['GAME_ID']) & set(preseason['GAME_ID']):
        raise ValueError('Prior-season and preseason samples must not share game IDs')
    rows = []
    skipped = 0
    skip_reasons = {'no_earlier_preseason_appearance': 0, 'no_earlier_prior_history': 0}
    for _, target in preseason.iterrows():
        history = preseason[preseason['day'] < target['day']]
        baseline = prior[prior['day'] < target['day']]
        if history.empty or baseline.empty:
            skipped += 1
            if history.empty:
                skip_reasons['no_earlier_preseason_appearance'] += 1
            if baseline.empty:
                skip_reasons['no_earlier_prior_history'] += 1
            continue
        minutes = float(history.tail(3)['minutes'].mean())
        rate = float(baseline['rebounds'].sum() / baseline['minutes'].sum())
        estimate = minutes * rate
        actual = float(target['rebounds'])
        rows.append({'game_id': str(target['GAME_ID']), 'date': target['day'].date().isoformat(),
                     'preseason_history_games': len(history), 'prior_history_games': len(baseline),
                     'estimated_minutes': minutes, 'projection': estimate, 'actual': actual,
                     'error': estimate - actual,
                     'naive_prior_projection': float(baseline['rebounds'].mean())})
    n = len(rows)
    return {'analysis_only': True, 'baseline': 'prior rebound rate × last three preseason appearances mean minutes',
            'evaluated_games': n, 'skipped_games': skipped,
            'skip_reasons': skip_reasons,
            'sample_counts': {
                'prior': {'input_rows': len(prior_frame), 'usable_appearances': len(prior),
                          'excluded_rows': len(prior_frame) - len(prior)},
                'preseason': {'input_rows': len(preseason_frame), 'usable_appearances': len(preseason),
                              'excluded_rows': len(preseason_frame) - len(preseason)}},
            'mae': sum(abs(r['error']) for r in rows) / n if n else None,
            'rmse': math.sqrt(sum(r['error'] ** 2 for r in rows) / n) if n else None,
            'bias': sum(r['error'] for r in rows) / n if n else None,
            'naive_prior_mae': sum(abs(r['naive_prior_projection'] - r['actual']) for r in rows) / n if n else None,
            'limitations': ['Appearance-only sample; DNPs excluded.',
                            'No roster, injury or coach-minute information; no profitability or probability-calibration claim.',
                            'Exploratory baseline, not held-out validation of the production model.'],
            'games': rows}
