"""Observed preseason inputs and explicit what-if estimates, never betting picks."""
import math
import re

import pandas as pd

from src.features import _clean_minutes


def _observed_minutes(value):
    if isinstance(value, bool):
        return float('nan')
    if isinstance(value, str) and ':' in value and not re.fullmatch(r'\d{1,2}:[0-5]\d', value.strip()):
        return float('nan')
    return _clean_minutes(value)


def summarize_history(frame, as_of, season):
    """Validate and exclude the target date before summarizing appearances.

    No current-game box score may become an input. Missing/invalid schemas fail
    visibly instead of being interpreted as an empty season.
    """
    empty = {'season': season, 'status': 'empty', 'games': 0,
             'minutes_per_game': None, 'rebounds_per_game': None,
             'rebounds_per_minute': None}
    if frame.empty:
        return empty, []
    if not {'GAME_DATE', 'MIN', 'REB'}.issubset(frame.columns):
        raise ValueError('History requires game date, minutes and rebounds')
    game_id = 'GAME_ID' if 'GAME_ID' in frame.columns else 'Game_ID'
    if game_id not in frame.columns:
        raise ValueError('History requires game identifiers')
    data = frame.copy(deep=True)
    data['day'] = pd.to_datetime(data['GAME_DATE'], format='mixed', errors='coerce').dt.normalize()
    data['game_id'] = data[game_id].astype('string').str.strip()
    data['minutes'] = data['MIN'].map(_observed_minutes)
    data['rebounds'] = pd.to_numeric(data['REB'].map(lambda v: None if isinstance(v, bool) else v), errors='coerce')
    identity_valid = data['day'].notna() & data['game_id'].notna() & data['game_id'].ne('')
    stats_valid = (data['minutes'].gt(0) & data['minutes'].le(60)
                   & data['rebounds'].ge(0) & data['rebounds'].le(100)
                   & data['rebounds'].mod(1).eq(0))
    dnp = data['minutes'].eq(0) | data['MIN'].astype(str).str.strip().str.upper().isin(
        ['DNP', 'DND', 'NWT', 'DID NOT PLAY', 'DID NOT DRESS'])
    invalid_rows = int((~identity_valid | (~stats_valid & ~dnp)).sum())
    data = data[identity_valid & stats_valid & (data['day'] < pd.Timestamp(as_of))]
    if data['game_id'].duplicated().any():
        raise ValueError('Duplicate appearances cannot be summarized')
    if data.empty:
        if invalid_rows:
            raise ValueError('History contains invalid rows and no usable earlier appearances')
        return empty, []
    data = data.sort_values('day')
    return {**empty, 'status': 'available', 'games': len(data), 'invalid_rows': invalid_rows,
            'date_range': {'from': data['day'].min().date().isoformat(),
                           'to': data['day'].max().date().isoformat(), 'scope': 'all_observed_appearances'},
            'minutes_per_game': round(float(data['minutes'].mean()), 2),
            'rebounds_per_game': round(float(data['rebounds'].mean()), 2),
            'rebounds_per_minute': float(data['rebounds'].sum() / data['minutes'].sum()),
            'recent_games': [{'date': row['day'].date().isoformat(),
                              'minutes': round(float(row['minutes']), 2),
                              'rebounds': int(row['rebounds'])}
                             for _, row in data.tail(10).iloc[::-1].iterrows()]}, list(data['minutes'])


def player_analysis(player_id, current_loader, prior_loader, date, minutes=None):
    """Retrieve separate real histories with independent, bounded allowances."""
    if minutes is not None and (isinstance(minutes, bool) or not isinstance(minutes, (int, float))
                                or not math.isfinite(minutes) or not 0 <= minutes <= 48):
        raise ValueError('Minutes must be a finite number from 0 to 48')
    result = {'analysis_only': True, 'prediction_eligible': False, 'estimate': None}
    limitations = [
        'Experimental analysis, not a validated preseason forecast or betting recommendation.',
        'Roster inclusion does not confirm availability. Injuries, trades, coach decisions and opponent effects are not modeled.',
        'Only appearances before the selected date are included; same-day results and DNPs are excluded.',
        'Prior-season history includes regular season, play-in and playoffs; it is not blended into preseason observations.',
    ]
    observed_minutes = []
    for key, source in [('prior_season', prior_loader), ('preseason', current_loader)]:
        source.reset_data_source_metadata()
        source.set_request_budget(15)
        try:
            # Passing this season's date to get_player_gamelog would override
            # the prior loader's season. Fetch that explicit season, then cut.
            frame = (source.get_player_gamelog(player_id) if key == 'prior_season'
                     else source.get_preseason_player_gamelog(player_id, as_of=date))
            summary, history_minutes = summarize_history(frame, date, source.season)
            provenance = source.get_data_source_metadata()
            summary['source'] = provenance.get('source') or 'unknown'
            limitations.extend(provenance.get('limitations') or [])
            if summary.get('invalid_rows'):
                limitations.append(f'{summary["invalid_rows"]} malformed {key.replace("_", " ")} rows were excluded; observed coverage is incomplete.')
            result[key] = summary
            if key == 'preseason':
                observed_minutes = history_minutes
        except Exception:
            result[key] = {'season': source.season, 'status': 'unavailable', 'games': 0,
                           'minutes_per_game': None, 'rebounds_per_game': None,
                           'rebounds_per_minute': None, 'source': 'unavailable'}
            limitations.append(f'{key.replace("_", " ").capitalize()} history could not be loaded; no missing values were invented.')
        finally:
            source.set_request_budget(None)
    used_minutes = minutes
    minutes_source = 'manual'
    if used_minutes is None and observed_minutes:
        used_minutes = sum(observed_minutes[-3:]) / len(observed_minutes[-3:])
        minutes_source = 'earlier_preseason'
        limitations.append('Minutes assumption uses the last three available earlier preseason appearances, not a confirmed rotation.')
    elif used_minutes is None:
        limitations.append('No earlier preseason minutes are available. Enter your own minutes assumption for a what-if estimate.')
    else:
        limitations.append('Minutes are your assumption, not a model forecast or confirmed playing time.')
    prior = result['prior_season']
    if used_minutes is not None and prior['status'] == 'available':
        result['estimate'] = {'rebounds': round(prior['rebounds_per_minute'] * used_minutes, 2),
                              'minutes': round(used_minutes, 2), 'minutes_source': minutes_source,
                              'history_games': prior['games']}
    result['limitations'] = list(dict.fromkeys(limitations))
    return result
