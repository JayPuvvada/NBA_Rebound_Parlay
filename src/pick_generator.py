"""Bounded, read-only rebound assessments with explicitly separate profiles.

The established feature model and betting gates remain authoritative. Experimental
profiles use exact probabilities from a three-component minutes mixture; they
never authorize a primary-model play or a Kelly stake.
"""
from __future__ import annotations

import math
import multiprocessing
import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date as Date, datetime, timezone

from src.data_loader import NBADataLoader, DataUnavailableError, RequestBudgetExceeded
from src.features import FeatureEngineer
from src.markets import fetch_board, BOOKS, freshness
from src.model import ReboundSimulator
from src.preseason_analysis import summarize_history
from src.projection_safety import projection_eligibility
from src.recommendation import edge_from_odds, tier_from_signals, weighted_hit_rate, is_actionable_tier
from src.utils import current_season, eastern_today, normalize_name

EXPERIMENTAL_VERSION = 'rebounds-scenarios-1.0'
MAX_SECONDS = 75.0


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RequestBudgetExceeded('Generation deadline reached')
    return remaining


def _loader(season, deadline):
    result = NBADataLoader(season=season)
    result.set_request_budget(_remaining(deadline))
    result.reset_data_source_metadata()
    return result


def empty_assessment(name, reason='pending', **identity):
    return {
        'player': name, 'player_id': None, 'team': None,
        'result_kind': 'unavailable', 'profile': None, 'model_version': None,
        'projection': None, 'minutes': None, 'quote': None,
        'candidate_direction': None, 'actionable': False,
        'limitations': [], 'reason_code': reason, 'assumptions': {}, 'analysis': None,
        **identity,
    }


def minutes_scenarios(minutes, profile):
    if (isinstance(minutes, bool) or not isinstance(minutes, (int, float))
            or not math.isfinite(minutes) or not 0 <= minutes <= 48):
        raise ValueError('Minutes must be a finite number from 0 to 48')
    delta = 6 if profile == 'preseason' else 4
    return [{'name': label, 'minutes': max(0.0, min(48.0, minutes + shift)), 'weight': weight}
            for label, shift, weight in [('low', -delta, .25), ('base', 0, .5), ('high', delta, .25)]]


def scenario_probabilities(rate, scenarios, line):
    """Exact mixture, including a point mass at zero and integer-line pushes."""
    if not math.isfinite(rate) or rate < 0:
        raise ValueError('Rebound rate must be finite and nonnegative')
    simulator = ReboundSimulator(num_simulations=1, random_state=0)
    result = {key: 0.0 for key in ('over_probability', 'under_probability', 'push_probability')}
    for scenario in scenarios:
        model = simulator.simulate({'projection': rate * scenario['minutes'],
                                    'components': {'Proj Minutes': scenario['minutes']}}, player_variance=None)
        probabilities = simulator.get_probabilities(model, line)
        for key in result:
            result[key] += scenario['weight'] * probabilities[key]
    return result


def _summary(frame, date, season, scope):
    summary, minutes = summarize_history(frame, date, season)
    summary.update(scope=scope, total_minutes=sum(minutes), source=frame.attrs.get('source', 'unknown'))
    return summary, minutes


def choose_profile(current, prior, preseason=False):
    """A failed prior is never silently interpreted as zero prior appearances."""
    prior_ok = prior.get('games', 0) >= 10 and prior.get('total_minutes', 0) >= 150
    if preseason:
        if prior_ok:
            return 'preseason', prior['rebounds_per_minute'], 'prior_regular'
        if current.get('games', 0) >= 3 and current.get('total_minutes', 0) >= 45:
            return 'preseason', current['rebounds_per_minute'], 'current_preseason'
        return None, None, None
    n = current.get('games', 0)
    if n >= 15:
        return 'full_regular', current['rebounds_per_minute'], 'current_regular'
    if not prior_ok:
        return None, None, None
    weight = n / 15
    rate = (weight * (current.get('rebounds_per_minute') or 0)
            + (1 - weight) * prior['rebounds_per_minute'])
    return 'early_regular', rate, 'current_prior_regular_blend'


def _pregame(game):
    if not isinstance(game, dict):
        return False
    status = game.get('status')
    valid = status.strip() == '1' if isinstance(status, str) else (
        isinstance(status, (int, float)) and not isinstance(status, bool) and status == 1)
    text = game.get('status_text') or ''
    return valid and isinstance(text, str) and not any(
        word in text.lower() for word in ('postponed', 'ppd', 'canceled', 'cancelled', 'final', 'suspended', 'delayed'))


def _verify_game(loader, request, deadline):
    _remaining(deadline)
    home_id, away_id = loader.get_team_id(request['home']), loader.get_team_id(request['away'])
    game = next((game for game in loader.get_games_for_date_fresh(request['date'])
                 if game.get('home_id') == home_id and game.get('away_id') == away_id), None)
    phase_matches = game is not None and (
        bool(game.get('is_preseason')) == (request['sport'] == 'basketball_nba_preseason'))
    return game, bool(phase_matches and _pregame(game)
                      and request['date'] >= eastern_today())


def _quote_is_fresh(quote):
    return (quote.get('source') == 'the-odds-api' and bool(quote.get('event_id'))
            and quote.get('freshness') != 'stale'
            and freshness(quote.get('updated_at')) == 'fresh')


def _availability(loader, name):
    try:
        report = loader.get_injury_report()
        metadata = loader.get_injury_report_metadata()
        try:
            fetched = datetime.fromisoformat(str(metadata.get('fetched_at', '')).replace('Z', '+00:00'))
            if fetched.tzinfo is None:
                return 'unknown'
            age = (datetime.now(timezone.utc) - fetched).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 'unknown'
        if (metadata.get('status') != 'available' or metadata.get('stale') is not False
                or not -300 <= age < NBADataLoader.INJURY_CACHE_TTL_SEC):
            return 'unknown'
        status = report.get(normalize_name(name))
        if status and any(word in str(status).lower() for word in ('out', 'inactive', 'injured', 'nwt')):
            return 'out'
        # Questionable/probable/day-to-day entries do not confirm participation.
        return 'known' if str(status or '').strip().lower() in {'active', 'available'} else 'unknown'
    except RequestBudgetExceeded:
        raise
    except Exception:
        return 'unknown'


def assess_player(identity, quotes, request, deadline, *, loader=None, prior_loader=None, engineer=None):
    """One isolated assessment; injectable collaborators support offline fixtures."""
    row = empty_assessment(identity['name'], **{key: identity[key] for key in ('player_id', 'team')})
    row['limitations'] = list(identity.get('limitations') or [])
    season = current_season(Date.fromisoformat(request['date']))
    loader = loader or _loader(season, deadline)
    try:
        _remaining(deadline)
        availability = _availability(loader, identity['name'])
        if availability == 'out':
            return {**row, 'result_kind': 'no_pick', 'reason_code': 'player_out',
                    'limitations': row['limitations'] + ['Player is reported out or inactive.']}
        if availability == 'unknown':
            row['limitations'].append('Availability is unconfirmed; roster membership is not confirmation that this player will play.')
        preseason = request['sport'] == 'basketball_nba_preseason'
        frame = (loader.get_preseason_player_gamelog(identity['player_id'], as_of=request['date'])
                 if preseason else loader.get_regular_player_gamelog(identity['player_id'], as_of=request['date']))
        current, observed_minutes = _summary(frame, request['date'], season,
                                              'preseason' if preseason else 'regular_season')
        prior = {}
        if preseason or current['games'] < 15:
            prior_year = int(season[:4]) - 1
            prior_season = f'{prior_year}-{str(prior_year + 1)[2:]}'
            prior_loader = prior_loader or _loader(prior_season, deadline)
            try:
                prior_frame = prior_loader.get_regular_player_gamelog(identity['player_id'], as_of=request['date'])
                prior, _ = _summary(prior_frame, request['date'], prior_season, 'regular_season')
            except RequestBudgetExceeded:
                raise
            except Exception:
                prior = {'status': 'unavailable', 'games': 0, 'total_minutes': 0, 'season': prior_season}
                row['limitations'].append('Prior regular-season history was unavailable.')
        profile, rate, rate_source = choose_profile(current, prior, preseason)
        row['assumptions'] = {'current_history': current, 'prior_history': prior,
                              'history_cutoff': request['date'], 'same_day_excluded': True}
        if profile is None:
            return {**row, 'reason_code': 'insufficient_history'}
        row['profile'] = profile
        if profile == 'full_regular':
            # Full model remains unchanged: its own projection, dispersion,
            # recent-hit gates and every explicit safety veto are preserved.
            engineer = engineer or FeatureEngineer(loader)
            opponent = request['away'] if identity['team'] == request['home'] else request['home']
            try:
                projection = engineer.compute_composite_projection(
                    identity['player_id'], opponent, spread=request.get('spreads', {}).get(identity['team'], 0),
                    home_game=identity['team'] == request['home'],
                    days_rest=loader.get_days_rest(loader.get_team_id(identity['team']), as_of=request['date']),
                    opp_days_rest=loader.get_days_rest(loader.get_team_id(opponent), as_of=request['date']),
                    as_of_date=request['date'])
            except RequestBudgetExceeded:
                raise
            except DataUnavailableError:
                projection = None
            if projection and 'error' not in projection:
                return _full_assessment(row, projection, quotes, request, loader, deadline)
            error = str((projection or {}).get('error', '')).lower()
            if error and not any(word in error for word in ('unavailable', 'missing', 'not found', 'invalid')):
                return {**row, 'result_kind': 'no_pick', 'reason_code': 'primary_model_veto',
                        'limitations': row['limitations'] + [str(projection['error'])]}
            profile = row['profile'] = 'reduced_regular'
            row['limitations'].append('Full-model inputs are unavailable; this estimate uses only observed total rebounds and minutes.')
        raw_minutes = request.get('minutes', {})
        minutes = raw_minutes.get(str(identity['player_id']), raw_minutes.get(identity['name']))
        source = 'manual'
        if minutes is None and observed_minutes:
            minutes = min(48.0, sum(observed_minutes[-3:]) / len(observed_minutes[-3:]))
            source = 'last_three_current_phase'
        if minutes is None:
            return {**row, 'result_kind': 'needs_input', 'reason_code': 'minutes_required',
                    'limitations': row['limitations'] + ['Enter a minutes assumption; no earlier current-phase appearances are available.']}
        scenarios = minutes_scenarios(minutes, profile)
        row.update(minutes={'value': minutes, 'source': source}, model_version=EXPERIMENTAL_VERSION,
                   projection=round(rate * sum(s['minutes'] * s['weight'] for s in scenarios), 3))
        row['assumptions'].update(rate=rate, rate_source=rate_source, current_weight=(current['games'] / 15 if profile == 'early_regular' else None),
                                  scenarios=scenarios, minutes_source=source, variance='heuristic_only',
                                  unmodeled=['injuries', 'opponent', 'coach_rotation', 'trades'])
        row['limitations'].append('Experimental scenario probabilities, not a validated forecast; opponent, rotation and injury effects are not modeled.')
        if source == 'manual':
            row['limitations'].append('Minutes are a manual assumption; this result is research only.')
        evaluations = []
        for quote in quotes:
            probabilities = scenario_probabilities(rate, scenarios, quote['line'])
            confidence = probabilities['over_probability' if quote['selection'] == 'OVER' else 'under_probability']
            price = edge_from_odds(confidence, quote['odds'], probabilities['push_probability'])
            evaluations.append({'quote': quote, **probabilities, **price, 'confidence': confidence, 'kelly_fraction': 0.0})
        if not evaluations:
            return {**row, 'reason_code': 'no_quote'}
        _, live = _verify_game(loader, request, deadline)
        qualifying = [item for item in evaluations if item['ev_roi'] is not None and item['ev_roi'] >= .02
                      and item['edge'] is not None and item['edge'] > 0 and _quote_is_fresh(item['quote'])]
        chosen = max(qualifying or evaluations, key=lambda item: item['ev_roi'] if item.get('ev_roi') is not None else -math.inf)
        # Explicit minutes are permitted scenario inputs, not manually entered odds.
        # Fresh provider prices and verified pregame context are still mandatory.
        candidate = bool(qualifying and live)
        row.update(result_kind='experimental_candidate' if candidate else 'no_pick', quote=chosen['quote'],
                   candidate_direction=chosen['quote']['selection'] if candidate else None,
                   reason_code='experimental_edge' if candidate else (
                               'game_not_verified_pregame' if not live else
                               'quote_not_provider_verified' if chosen['quote'].get('source') != 'the-odds-api' or not chosen['quote'].get('event_id') else
                               'stale_quote' if not _quote_is_fresh(chosen['quote']) else 'no_qualifying_edge'),
                   analysis={**{key: value for key, value in chosen.items() if key != 'quote'},
                             'direction': None, 'actionable': False, 'kelly_fraction': 0.0,
                             'probability_label': 'scenario_probability', 'side_evaluations': evaluations})
        return row
    except RequestBudgetExceeded:
        return {**row, 'reason_code': 'deadline_exceeded'}
    except Exception:
        return {**row, 'reason_code': 'player_data_unavailable',
                'limitations': row['limitations'] + ['This player could not be fully assessed; retry this player.']}


def _full_assessment(row, projection, quotes, request, loader, deadline):
    eligible, limitations = projection_eligibility(projection)
    if projection.get('team_id') != loader.get_team_id(row['team']):
        eligible = False
        limitations.append('Full-model team identity does not match the verified current roster.')
    row['limitations'].extend(limitations)
    simulator = ReboundSimulator(num_simulations=1, random_state=0)
    simulated = simulator.simulate(projection, player_variance=projection.get('player_variance'))
    evaluations = []
    for quote in quotes:
        probabilities = simulator.get_probabilities(simulated, quote['line'])
        side = quote['selection']
        confidence = probabilities['over_probability' if side == 'OVER' else 'under_probability']
        price = edge_from_odds(confidence, quote['odds'], probabilities['push_probability'])
        hit_rate, games = weighted_hit_rate(projection.get('trend_data', []), quote['line'], side)
        tier, color = tier_from_signals(confidence, side, quote['line'], probabilities['ci_68'][0],
                                       hit_rate, games, mean_proj=projection['projection'],
                                       ev_roi=price['ev_roi'], edge=price['edge'],
                                       high_variance=simulated['params'].get('high_variance_flag', False),
                                       odds_available=True, push_probability=probabilities['push_probability'])
        evaluations.append({'quote': quote, **probabilities, **price, 'confidence': confidence,
                            'tier': tier, 'tier_color': color, 'hit_rate': hit_rate, 'hit_rate_games': games})
    _, live = _verify_game(loader, request, deadline)
    qualified = [item for item in evaluations if eligible and live and _quote_is_fresh(item['quote'])
                 and is_actionable_tier(item['tier']) and item['ev_roi'] is not None and item['ev_roi'] > 0]
    selected = max(qualified or evaluations, key=lambda item: item.get('ev_roi') if item.get('ev_roi') is not None else -math.inf) if evaluations else None
    actionable = bool(qualified)
    if not actionable:
        for evaluation in evaluations:
            evaluation['kelly_fraction'] = 0.0
            if not eligible:
                evaluation.update(tier='HISTORICAL_CONTEXT_INCOMPLETE', tier_color='gray')
    row.update(result_kind='model_pick' if actionable else 'no_pick', model_version=os.environ.get('MODEL_VERSION', '2.0.0'),
               projection=round(float(projection['projection']), 3),
               minutes={'value': projection.get('components', {}).get('Proj Minutes'), 'source': 'primary_model'},
               actionable=actionable, quote=selected['quote'] if selected else None,
               reason_code='primary_model_pick' if actionable else ('primary_safety_veto' if not eligible else
                           'game_not_verified_pregame' if not live else 'no_qualifying_primary_pick'))
    if selected:
        row['analysis'] = {**{key: value for key, value in selected.items() if key != 'quote'},
                           'direction': selected['quote']['selection'] if actionable else None,
                           'actionable': actionable, 'kelly_fraction': selected['kelly_fraction'] if actionable else 0,
                           'side_evaluations': evaluations}
    return row


def _pipeline(request, api_key, deadline, emit):
    loader = _loader(current_season(Date.fromisoformat(request['date'])), deadline)
    board = fetch_board(loader, api_key, request['home'], request['away'], request['date'],
                        request['sport'], BOOKS, group='rebounds', refresh=True)
    grouped = {}
    canonical_names = {}
    selected_players = {normalize_name(name) for name in request.get('players', [])}
    for raw in board.get('quotes', []):
        if raw.get('market') != 'player_rebounds' or raw.get('book') != request['book']:
            continue
        name = raw.get('player')
        if not name or (selected_players and normalize_name(name) not in selected_players):
            continue
        name = canonical_names.setdefault(normalize_name(name), name)
        quote = {**raw, 'player': name, 'event_id': raw.get('event_id') or board.get('event_id'),
                 'source': raw.get('source') or board.get('source'), 'fetched_at': raw.get('fetched_at') or board.get('fetched_at')}
        grouped.setdefault(name, []).append(quote)
    names = list(grouped)
    emit(('players', names))
    emit(('board_metadata', {key: board[key] for key in ('status', 'reason_code', 'budget', 'message') if key in board}))
    if not names:
        emit(('status', 'no_quotes' if board.get('status') in {'available', 'empty', 'event_missing'} else board.get('status', 'unavailable')))
        return
    identities = {}
    for team in (request['home'], request['away']):
        _remaining(deadline)
        try:
            roster = loader.get_analysis_roster(loader.get_team_id(team))
            for player in roster['players']:
                identities.setdefault(normalize_name(player['name']), []).append(
                    {**player, 'team': team, 'limitations': roster.get('limitations', [])})
        except RequestBudgetExceeded:
            raise
        except Exception:
            continue
    jobs = []
    roster_id_counts = {}
    for matches in identities.values():
        for identity in matches:
            roster_id_counts[identity['player_id']] = roster_id_counts.get(identity['player_id'], 0) + 1
    for name in names:
        matches = identities.get(normalize_name(name), [])
        if len(matches) != 1 or roster_id_counts.get(matches[0]['player_id']) != 1:
            emit(('assessment', empty_assessment(name, 'roster_identity_unverified')))
        else:
            # Keep the sportsbook spelling as the stable retry/coverage key.
            jobs.append(({**matches[0], 'name': name}, grouped[name]))
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='rebound-assessment') as executor:
        futures = []
        for identity, quotes in jobs:
            _remaining(deadline)
            futures.append(executor.submit(assess_player, identity, quotes, request, deadline))
        for future in as_completed(futures):
            _remaining(deadline)
            emit(('assessment', future.result()))


def _process_entry(request, api_key, deadline, output):
    try:
        _pipeline(request, api_key, deadline, output.put)
    except RequestBudgetExceeded:
        output.put(('status', 'partial'))
    except Exception:
        output.put(('status', 'unavailable'))
    finally:
        output.put(('done', None))


def _supervise(request, api_key, budget_seconds, worker):
    """Collect bounded messages and reap the entire process before returning."""
    allowance = min(MAX_SECONDS, max(.01, budget_seconds))
    # Leave room to reap the worker within the advertised server allowance.
    deadline = time.monotonic() + allowance - min(.25, allowance / 4)
    context = multiprocessing.get_context('spawn')
    output = context.Queue()
    process = context.Process(target=worker, args=(request, api_key, deadline, output), daemon=True)
    messages, finished = [], False
    try:
        process.start()
        while time.monotonic() < deadline:
            try:
                kind, payload = output.get(timeout=min(.1, max(.001, deadline - time.monotonic())))
            except queue.Empty:
                if not process.is_alive():
                    break
                continue
            if kind == 'done':
                finished = True
                break
            messages.append((kind, payload))
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=.2)
            if process.is_alive():
                process.kill()
                process.join()
        output.close()
    return messages, finished


def generate_picks(request, api_key='', *, budget_seconds=MAX_SECONDS, worker=_process_entry):
    """Absolute budget; no expired provider/model work survives this call.

    The spawned process owns at most two threads with isolated player loaders.
    No web-app globals, loader instances, or Flask contexts cross the boundary.
    """
    result = {'status': 'complete', 'game': {'home': request['home'], 'away': request['away']},
              'date': request['date'], 'assessments': [], 'coverage': {'total': 0, 'completed': 0, 'incomplete': []},
              'generated_at': utc_now()}
    names, rows = list(request.get('players', [])), {}
    messages, finished = _supervise(request, api_key, budget_seconds, worker)
    for kind, payload in messages:
        if kind == 'players':
            names = payload
        elif kind == 'assessment':
            rows[payload['player']] = payload
        elif kind == 'status':
            result['status'] = payload
        elif kind == 'board_metadata':
            result['market_status'] = payload.get('status')
            for key in ('reason_code', 'budget', 'message'):
                if key in payload:
                    result[key] = payload[key]
    for name in names:
        if name not in rows:
            rows[name] = empty_assessment(name, 'deadline_exceeded' if not finished else 'player_data_unavailable')
    incomplete = [name for name, row in rows.items() if row['result_kind'] == 'unavailable']
    result['assessments'] = list(rows.values())
    result['coverage'] = {'total': len(rows), 'completed': len(rows) - len(incomplete), 'incomplete': incomplete}
    if not finished or incomplete:
        result['status'] = 'partial' if rows else 'unavailable'
    return result


def _history_entry(request, api_key, deadline, output):
    """Independent sources within one absolute research allowance."""
    try:
        season = current_season(Date.fromisoformat(request['date']))
        loader = _loader(season, deadline)
        player_id = loader.get_player_id(request['player'])
        if not player_id:
            output.put(('error', 'player_identity_unverified'))
            return
        prior_year = int(season[:4]) - 1
        prior_season = f'{prior_year}-{str(prior_year + 1)[2:]}'
        phases = [(season, 'preseason' if request['preseason'] else 'current_season'),
                  (prior_season, 'prior_season')]
        for season, kind in phases:
            try:
                source = _loader(season, deadline)
                source.set_request_budget(min(15, _remaining(deadline)))
                frame = (source.get_preseason_player_gamelog(player_id, as_of=request['date']) if kind == 'preseason'
                         else source.get_regular_player_gamelog(player_id, as_of=request['date']))
                summary, _ = _summary(frame, request['date'], season,
                                      'preseason' if kind == 'preseason' else 'regular_season')
                summary['kind'] = kind
                recent = summary.get('recent_games', [])
                for window in (5, 10):
                    if len(recent) >= window:
                        summary[f'last_{window}'] = {key: round(sum(row[key] for row in recent[:window]) / window, 2)
                                                     for key in ('rebounds', 'minutes')}
                line = request.get('line')
                if line is not None and recent:
                    summary['observed_above_line'] = {'line': line, 'above': sum(row['rebounds'] > line for row in recent),
                                                     'below': sum(row['rebounds'] < line for row in recent),
                                                     'push': sum(row['rebounds'] == line for row in recent), 'games': len(recent)}
                    summary['observed_below_line'] = {'line': line, 'below': sum(row['rebounds'] < line for row in recent), 'games': len(recent)}
                    summary['observed_pushes'] = {'line': line, 'pushes': sum(row['rebounds'] == line for row in recent), 'games': len(recent)}
                output.put(('history', summary))
            except Exception:
                output.put(('history', {'kind': kind, 'season': season, 'status': 'unavailable', 'games': 0,
                                        'minutes_per_game': None, 'rebounds_per_game': None, 'rebounds_per_minute': None}))
    except Exception:
        output.put(('error', 'history_unavailable'))
    finally:
        output.put(('done', None))


def player_histories(player, date, preseason=False, line=None, *, budget_seconds=30, worker=_history_entry):
    request = {'player': player, 'date': date, 'preseason': preseason, 'line': line}
    messages, finished = _supervise(request, '', min(30, budget_seconds), worker)
    histories = [value for kind, value in messages if kind == 'history']
    error = next((value for kind, value in messages if kind == 'error'), None)
    usable = [history for history in histories if history.get('status') in ('available', 'empty')]
    status = ('complete' if finished and not error and len(usable) == 2 else
              'partial' if usable else 'unavailable')
    result = {'player': player, 'date': date, 'analysis_only': True, 'histories': histories,
              'status': status,
              'message': 'Observed appearances before this date; not a forecast or availability confirmation.'}
    if error:
        result['reason_code'] = error
    elif not finished:
        result['reason_code'] = 'deadline_exceeded'
    elif status != 'complete':
        result['reason_code'] = 'history_source_unavailable'
    return result
