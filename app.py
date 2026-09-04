import os
import sys
import math
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import date as _date, datetime, timezone
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

from src.data_loader import NBADataLoader
from src.features import FeatureEngineer
from src.model import ReboundSimulator
from src.recommendation import (
    edge_from_odds,
    is_actionable_tier,
    select_best_bet,
    tier_from_signals,
    weighted_hit_rate,
)
from src.cheat_sheet import project_team
from src.utils import get_logger, eastern_today, current_season

load_dotenv()
log = get_logger('app')

PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
MODEL_VERSION = os.environ.get("MODEL_VERSION", "2.0.0")

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

cors_origins = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]
CORS(
    app,
    resources={
        r"/predict": {"origins": cors_origins},
        r"/games": {"origins": cors_origins},
        r"/cheat-sheet": {"origins": cors_origins},
    },
)


class APIValidationError(ValueError):
    """Client input failed validation."""


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_date(value, field="date", default=None):
    raw = default if value is None or value == "" else value
    if not isinstance(raw, str):
        raise APIValidationError(f"'{field}' must be a YYYY-MM-DD string")
    try:
        parsed = _date.fromisoformat(raw)
    except ValueError as exc:
        raise APIValidationError(f"'{field}' must use YYYY-MM-DD format") from exc
    if parsed.year < 1996 or parsed.year > _date.today().year + 2:
        raise APIValidationError(f"'{field}' is outside the supported NBA date range")
    return parsed.isoformat(), parsed


def _required_text(data, field, max_length=100):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise APIValidationError(f"Missing or invalid '{field}'")
    value = value.strip()
    if len(value) > max_length:
        raise APIValidationError(f"'{field}' is too long")
    return value


def _optional_float(value, field, default=None, minimum=None, maximum=None):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise APIValidationError(f"'{field}' must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise APIValidationError(f"'{field}' must be numeric") from exc
    if not math.isfinite(parsed):
        raise APIValidationError(f"'{field}' must be finite")
    if minimum is not None and parsed < minimum:
        raise APIValidationError(f"'{field}' must be at least {minimum}")
    if maximum is not None and parsed > maximum:
        raise APIValidationError(f"'{field}' must be at most {maximum}")
    return parsed


def _optional_american_odds(value, field):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise APIValidationError(f"'{field}' must be valid American odds")
    try:
        parsed_float = float(value)
        parsed = int(parsed_float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise APIValidationError(f"'{field}' must be valid American odds") from exc
    if not math.isfinite(parsed_float) or parsed_float != parsed:
        raise APIValidationError(f"'{field}' must be a whole number")
    if -100 < parsed < 100:
        raise APIValidationError(f"'{field}' must be <= -100 or >= +100")
    return parsed


def _parse_home_game(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "home"}:
            return True
        if normalized in {"false", "0", "no", "away"}:
            return False
    raise APIValidationError("'home_game' must be true, false, or null")


def _optional_boolean(value, field, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise APIValidationError(f"'{field}' must be true or false")


def _env_nonnegative_int(name, default):
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        log.warning("Ignoring invalid %s value; using %s", name, default)
        return default


# Lightweight process-local protection for endpoints that can trigger paid or
# rate-limited upstream requests. Deployments can override these limits.
_request_windows = defaultdict(deque)
_request_windows_lock = threading.Lock()
_rate_limits = {
    "/predict": (_env_nonnegative_int("PREDICT_RATE_LIMIT", 20), 60),
    "/games": (_env_nonnegative_int("GAMES_RATE_LIMIT", 60), 60),
    "/cheat-sheet": (_env_nonnegative_int("CHEAT_SHEET_RATE_LIMIT", 8), 60),
}


@app.before_request
def _rate_limit_expensive_routes():
    if app.testing or request.path not in _rate_limits:
        return None
    limit, window_seconds = _rate_limits[request.path]
    if limit <= 0:
        return None
    client = request.remote_addr or "unknown"
    cache_key = (request.path, client)
    now = time.monotonic()
    with _request_windows_lock:
        hits = _request_windows[cache_key]
        while hits and now - hits[0] >= window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = max(1, math.ceil(window_seconds - (now - hits[0])))
            response = jsonify({
                "error": "Rate limit exceeded. Please try again shortly.",
                "code": "rate_limited",
            })
            response.status_code = 429
            response.headers["Retry-After"] = str(retry_after)
            return response
        hits.append(now)
    return None

# Eager init; avoids cold start on every request.
try:
    log.info("Initializing model components...")
    loader = NBADataLoader()
    engineer = FeatureEngineer(loader)
    simulator = ReboundSimulator()
    log.info("Model components initialized.")
except Exception as e:
    log.exception(f"Fatal: Error initializing components: {e}")
    sys.exit(1)

_component_cache = {loader.season: (loader, engineer)}
_component_cache_lock = threading.Lock()


def _components_for_date(parsed_date):
    """Return season-correct loader/engineer instances for an as-of date."""
    season = current_season(parsed_date)
    with _component_cache_lock:
        cached = _component_cache.get(season)
        if cached is None:
            date_loader = NBADataLoader(season=season)
            cached = (date_loader, FeatureEngineer(date_loader))
            _component_cache[season] = cached
        return cached


@app.errorhandler(413)
def _payload_too_large(_error):
    return jsonify({"error": "Request payload is too large.", "code": "payload_too_large"}), 413


def _find_scheduled_matchup(
    date_loader, team_id, opponent_id, date_str, *, require_fresh=False
):
    """Return the exact scheduled game and the player's venue, if present."""
    if not date_str:
        return None, None
    if require_fresh:
        schedule_method = getattr(date_loader, 'get_games_for_date_fresh', None)
        if not callable(schedule_method):
            raise RuntimeError('A fresh schedule lookup is unavailable')
    else:
        schedule_method = date_loader.get_games_for_date
    games = schedule_method(date_str) or []
    for game in games:
        if game.get('home_id') == team_id and game.get('away_id') == opponent_id:
            return game, True
        if game.get('away_id') == team_id and game.get('home_id') == opponent_id:
            return game, False
    return None, None


def _detect_home_game(date_loader, team_id, opponent_id, date_str):
    """Backward-compatible venue-only schedule helper."""
    try:
        _game, is_home = _find_scheduled_matchup(
            date_loader, team_id, opponent_id, date_str
        )
        return is_home
    except Exception as exc:
        log.warning(
            "home-game detection failed for team %s on %s: %s",
            team_id,
            date_str,
            exc,
        )
        return None


def _is_pregame(game):
    if not isinstance(game, dict):
        return False
    try:
        if int(game.get('status')) != 1:
            return False
    except (TypeError, ValueError):
        return False
    status_text = str(game.get('status_text') or '').strip().lower()
    return not any(
        marker in status_text
        for marker in (
            'postponed', 'ppd', 'canceled', 'cancelled', 'final',
            'suspended', 'delayed',
        )
    )


def _verify_fresh_pregame(date_loader, team_id, opponent_id, date_str, home_game):
    """Re-fetch and validate the exact game immediately before issuing a pick."""
    game, scheduled_home = _find_scheduled_matchup(
        date_loader,
        team_id,
        opponent_id,
        date_str,
        require_fresh=True,
    )
    if game is None:
        return None, 'The matchup could not be freshly verified before issuance.'
    if scheduled_home is not home_game:
        return game, 'The scheduled venue changed before issuance.'
    if not _is_pregame(game):
        return game, (
            'The game is live, final, postponed, or otherwise not pregame; '
            'the pick was not recorded.'
        )
    return game, None


def _odds_timestamp_age_seconds(value, now=None):
    """Return a non-negative UTC age, or ``None`` for unsafe timestamps."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    current = now or datetime.now(timezone.utc)
    age = (current - parsed.astimezone(timezone.utc)).total_seconds()
    # Tolerate small provider clock skew, but not a timestamp materially in the
    # future (which could otherwise remain "fresh" indefinitely).
    if age < -60:
        return None
    return max(0.0, age)


def _max_actionable_odds_age_seconds():
    configured = _env_nonnegative_int('ODDS_MAX_AGE_SECONDS', 300)
    return configured if configured > 0 else 300


def _downgrade_projection_response(response, reason, game=None):
    """Make a completed projection diagnostic-only after a fresh status check."""
    limitations = list(response.get('limitations') or [])
    limitations.append(reason)
    limitations = list(dict.fromkeys(limitations))
    response['prediction_eligible'] = False
    response['limitations'] = limitations

    metadata = dict(response.get('metadata') or {})
    metadata.update({
        'prediction_eligible': False,
        'limitations': limitations,
        'schedule_verified': game is not None,
        'game_status': game.get('status') if game else None,
    })
    response['metadata'] = metadata

    freshness = dict(response.get('data_freshness') or {})
    freshness.update({
        'prediction_eligible': False,
        'limitations': limitations,
    })
    response['data_freshness'] = freshness

    schedule = dict(response.get('schedule') or {})
    schedule.update({
        'verified': game is not None,
        'game_id': game.get('game_id') if game else None,
        'status': game.get('status') if game else None,
        'status_text': game.get('status_text') if game else None,
    })
    response['schedule'] = schedule

    analysis = response.get('analysis')
    if isinstance(analysis, dict):
        analysis.update({
            'direction': None,
            'actionable': False,
            'tier': 'GAME_NOT_PREGAME' if game is not None else 'SCHEDULE_UNVERIFIED',
            'tier_color': 'gray',
            'kelly_fraction': 0.0,
        })
        for side in (analysis.get('side_evaluations') or {}).values():
            if isinstance(side, dict):
                side.update({
                    'tier': analysis['tier'],
                    'tier_color': 'gray',
                    'kelly_fraction': 0.0,
                })
        response['summary'] = (
            '**Recommendation: NO BET**. The matchup was not in a freshly '
            'verified pregame state when issuance was requested.'
        )


def _downgrade_cheat_row(row, tier, warning, *, prediction_eligible=None):
    """Apply a coherent no-bet state to one cheat-sheet row."""
    row['direction'] = None
    row['actionable'] = False
    row['kelly_fraction'] = 0.0
    row['kelly_stake'] = 0.0
    row_limitations = list(row.get('limitations') or [])
    row_limitations.append(warning)
    row['limitations'] = list(dict.fromkeys(row_limitations))

    if prediction_eligible is not None:
        row['prediction_eligible'] = prediction_eligible
    metadata = dict(row.get('metadata') or {})
    if prediction_eligible is not None:
        metadata['prediction_eligible'] = prediction_eligible
    metadata['limitations'] = row['limitations']
    row['metadata'] = metadata
    freshness = dict(row.get('data_freshness') or {})
    if prediction_eligible is not None:
        freshness['prediction_eligible'] = prediction_eligible
    freshness['limitations'] = row['limitations']
    row['data_freshness'] = freshness

    if row.get('tier') != 'HISTORICAL_CONTEXT_INCOMPLETE':
        row['tier'] = tier
        row['tier_color'] = 'gray'
    for side in (row.get('side_evaluations') or {}).values():
        if isinstance(side, dict):
            side.update({
                'tier': row.get('tier'),
                'tier_color': 'gray',
                'kelly_fraction': 0.0,
            })
    row['summary'] = f'**Recommendation: NO BET**. {warning}'


def _projection_error_status(message):
    normalized = str(message or '').lower()
    client_markers = (
        'player is out',
        'player is injured',
        'matchup player',
        'opponent team not found',
        'player not found',
        'must be',
        'outside valid',
    )
    return 422 if any(marker in normalized for marker in client_markers) else 503


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path == "predict":
        response = jsonify({"error": "Method not allowed.", "code": "method_not_allowed"})
        response.status_code = 405
        response.headers["Allow"] = "POST"
        return response
    if path.startswith("api/"):
        return jsonify({"error": "API route not found.", "code": "not_found"}), 404
    if path:
        candidate = (FRONTEND_DIST / path).resolve()
        if candidate.is_relative_to(FRONTEND_DIST.resolve()) and candidate.is_file():
            return send_from_directory(FRONTEND_DIST, path)
    index_file = FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return send_from_directory(FRONTEND_DIST, "index.html")
    return jsonify({
        "error": "Frontend build not found. Run 'npm run build' in frontend/.",
        "code": "frontend_not_built",
    }), 503


@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "model_version": MODEL_VERSION,
        "season": loader.season,
        "timestamp": _utc_now(),
    })


@app.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise APIValidationError("Request body must be a JSON object")

        player_name = _required_text(data, 'player')
        opp_team = _required_text(data, 'opponent', max_length=3).upper()
        spread = _optional_float(data.get('spread'), 'spread', 0.0, -40.0, 40.0)
        line = _optional_float(data.get('line'), 'line', minimum=0.0, maximum=40.0)
        over_odds = _optional_american_odds(data.get('over_odds'), 'over_odds')
        under_odds = _optional_american_odds(data.get('under_odds'), 'under_odds')
        legacy_odds = _optional_american_odds(data.get('odds'), 'odds')

        legacy_side = str(data.get('odds_side', 'OVER')).strip().upper()
        if legacy_side not in {'OVER', 'UNDER'}:
            raise APIValidationError("'odds_side' must be OVER or UNDER")
        if legacy_odds is not None:
            if legacy_side == 'OVER' and over_odds is None:
                over_odds = legacy_odds
            elif legacy_side == 'UNDER' and under_odds is None:
                under_odds = legacy_odds
        if line is None and (over_odds is not None or under_odds is not None):
            raise APIValidationError("A betting line is required when odds are supplied")

        matchup_raw = data.get('matchup')
        matchup = None
        if matchup_raw not in (None, ''):
            if not isinstance(matchup_raw, str) or len(matchup_raw.strip()) > 100:
                raise APIValidationError("'matchup' must be a player name")
            matchup = matchup_raw.strip()

        bookmaker_raw = data.get('bookmaker')
        bookmaker = None
        if bookmaker_raw not in (None, ''):
            if not isinstance(bookmaker_raw, str) or len(bookmaker_raw.strip()) > 50:
                raise APIValidationError("'bookmaker' must be a short name")
            bookmaker = bookmaker_raw.strip()

        home_game = _parse_home_game(data.get('home_game'))
        record_requested = _optional_boolean(
            data.get('record_prediction'), 'record_prediction'
        )
        date_str, parsed_date = _parse_date(data.get('date'), default=eastern_today())
        date_loader, date_engineer = _components_for_date(parsed_date)

        opp_id = date_loader.get_team_id(opp_team)
        if not opp_id:
            return jsonify({
                'error': f"Unknown NBA team abbreviation '{opp_team}'.",
                'code': 'opponent_not_found',
            }), 404

        pid = date_loader.get_player_id(player_name)
        if not pid:
            return jsonify({
                'error': f"Player '{player_name}' was not found uniquely.",
                'code': 'player_not_found',
            }), 404

        p_info = date_loader.get_common_player_info(pid)
        if p_info.empty:
            return jsonify({'error': 'Player information is unavailable.', 'code': 'player_info_unavailable'}), 503

        team_id = p_info.iloc[0]['TEAM_ID']
        if parsed_date < _date.fromisoformat(eastern_today()):
            # CommonPlayerInfo reflects the player's current roster. Historical
            # forecasts must instead use the newest game strictly before the
            # requested date so trades do not assign the wrong venue/rest/team.
            historical_stats = date_engineer.get_player_stats(
                pid, opponent_abbrev=opp_team, as_of_date=date_str
            )
            if historical_stats and historical_stats.get('team_id'):
                team_id = historical_stats['team_id']
        if not team_id:
            return jsonify({'error': 'The player is not on an active NBA roster.', 'code': 'player_not_rostered'}), 422

        if int(team_id) == int(opp_id):
            raise APIValidationError("A player's team cannot also be the opponent")

        scheduled_game = None
        scheduled_home = None
        schedule_error = None
        try:
            needs_live_schedule = parsed_date >= _date.fromisoformat(eastern_today())
            scheduled_game, scheduled_home = _find_scheduled_matchup(
                date_loader,
                team_id,
                opp_id,
                date_str,
                require_fresh=needs_live_schedule,
            )
        except Exception as exc:
            schedule_error = exc
            log.warning(
                "Schedule verification failed for player %s on %s: %s",
                pid,
                date_str,
                exc,
            )

        if home_game is None:
            if schedule_error is not None:
                return jsonify({
                    'error': 'The schedule provider is unavailable; select a venue to run a diagnostic projection.',
                    'code': 'schedule_unavailable',
                }), 503
            home_game = scheduled_home
            if scheduled_game is None:
                return jsonify({
                    'error': 'Venue could not be verified for that matchup and date. Select Home or Away explicitly.',
                    'code': 'venue_unverified',
                }), 422
        elif scheduled_game is not None and scheduled_home != home_game:
            return jsonify({
                'error': 'The selected venue does not match the scheduled matchup.',
                'code': 'venue_mismatch',
            }), 422

        team_rest = date_loader.get_days_rest(team_id, as_of=date_str)
        opp_rest = date_loader.get_days_rest(opp_id, as_of=date_str)

        proj_data = date_engineer.compute_composite_projection(
            pid,
            opp_team,
            spread=spread,
            home_game=home_game,
            days_rest=team_rest,
            opp_days_rest=opp_rest,
            matchup_player=matchup,
            as_of_date=date_str,
        )

        if not proj_data or 'error' in proj_data:
            message = (proj_data or {}).get('error', 'Projection data is unavailable')
            status = _projection_error_status(message)
            return jsonify({'error': message, 'code': 'projection_unavailable'}), status

        mean_proj = float(proj_data['projection'])
        projection_metadata = dict(proj_data.get('metadata') or {})
        eligibility_signal = projection_metadata.get('prediction_eligible')
        prediction_eligible = eligibility_signal is True
        limitations = list(projection_metadata.get('limitations') or [])
        if eligibility_signal is not True and eligibility_signal is not False:
            limitations.append(
                'projection safety metadata did not explicitly authorize a live pick'
            )
        schedule_status = scheduled_game.get('status') if scheduled_game else None
        schedule_is_pregame = _is_pregame(scheduled_game)
        if scheduled_game is None:
            prediction_eligible = False
            limitations.append(
                'scheduled matchup could not be verified; projection is analysis-only'
            )
        elif not schedule_is_pregame:
            prediction_eligible = False
            limitations.append(
                'game is live, final, or has an unknown status; projection is analysis-only'
            )
        projection_metadata.update({
            'prediction_eligible': prediction_eligible,
            'limitations': list(dict.fromkeys(limitations)),
            'schedule_verified': scheduled_game is not None,
            'game_status': schedule_status,
        })
        limitations = projection_metadata['limitations']

        data_freshness = dict(proj_data.get('data_freshness') or {})
        data_freshness.update({
            'prediction_eligible': prediction_eligible,
            'limitations': list(limitations),
        })

        player_var_data = proj_data.get('player_variance')
        sim_res = simulator.simulate(proj_data, market_line=line, player_variance=player_var_data)

        response = {
            'player': proj_data.get('player', player_name),
            'team': proj_data.get('team_abbreviation', proj_data.get('team')),
            'team_id': int(proj_data.get('team_id', team_id)),
            'opponent': opp_team,
            'date': date_str,
            'season': date_loader.season,
            'projection': round(mean_proj, 2),
            'home_game': home_game,
            'context': proj_data.get('matchup_context', 'Neutral'),
            'injuries': {
                'matchup': proj_data.get('matchup_injury'),
                'team': proj_data.get('team_injury'),
                'team_list': proj_data.get('team_injury_list', []),
                'opp_list': proj_data.get('opp_injury_list', []),
            },
            'components': proj_data.get('components', {}),
            'trend': proj_data.get('trend_data', []),
            'generated_at': _utc_now(),
            'model_version': MODEL_VERSION,
            'data_freshness': data_freshness,
            'metadata': projection_metadata,
            'prediction_eligible': prediction_eligible,
            'limitations': limitations,
            'schedule': {
                'verified': scheduled_game is not None,
                'game_id': scheduled_game.get('game_id') if scheduled_game else None,
                'status': schedule_status,
                'status_text': (
                    scheduled_game.get('status_text') if scheduled_game else None
                ),
            },
        }

        if line is not None:
            probs = simulator.get_probabilities(sim_res, line)
            over_prob = probs['over_probability']
            under_prob = probs['under_probability']
            trend_data = proj_data.get('trend_data', [])
            high_variance = bool(sim_res['params'].get('high_variance_flag', False))
            side_prices = {'OVER': over_odds, 'UNDER': under_odds}
            offered_sides = [side for side, price in side_prices.items() if price is not None]
            sides_to_evaluate = offered_sides or ['OVER', 'UNDER']
            evaluations = []

            for direction in sides_to_evaluate:
                confidence = over_prob if direction == 'OVER' else under_prob
                hit_rate, n_games = weighted_hit_rate(trend_data, line, direction)
                price = side_prices[direction]
                edge_info = edge_from_odds(confidence, price, probs['push_probability'])
                tier, tier_color = tier_from_signals(
                    confidence,
                    direction,
                    line,
                    probs['ci_68'][0],
                    hit_rate,
                    n_games,
                    mean_proj=mean_proj,
                    ev_roi=edge_info['ev_roi'],
                    edge=edge_info['edge'],
                    high_variance=high_variance,
                    odds_available=price is not None,
                    push_probability=probs['push_probability'],
                )
                evaluations.append({
                    'direction': direction,
                    'confidence': confidence,
                    'hit_rate': hit_rate,
                    'hit_rate_games': n_games,
                    'tier': tier,
                    'tier_color': tier_color,
                    'american_odds': edge_info['american_odds'],
                    'implied_probability': edge_info['implied_probability'],
                    'break_even_probability': edge_info['break_even_probability'],
                    'edge': edge_info['edge'],
                    'ev_roi': edge_info['ev_roi'],
                    'kelly_fraction': edge_info['kelly_fraction'],
                })

            if not prediction_eligible:
                for evaluation in evaluations:
                    evaluation.update({
                        'tier': 'HISTORICAL_CONTEXT_INCOMPLETE',
                        'tier_color': 'gray',
                        'kelly_fraction': 0.0,
                    })

            selected = (
                select_best_bet(evaluations, actionable_only=True)
                if offered_sides and prediction_eligible
                else None
            )
            evaluated = selected or max(
                evaluations,
                key=lambda item: (
                    item['ev_roi'] if item['ev_roi'] is not None else float('-inf'),
                    item['confidence'],
                ),
            )
            direction = (
                selected['direction']
                if selected is not None and is_actionable_tier(selected['tier'])
                else None
            )
            actionable = direction is not None

            response['analysis'] = {
                'line': line,
                'over_probability': over_prob,
                'under_probability': under_prob,
                'push_probability': probs['push_probability'],
                'direction': direction,
                'evaluated_side': evaluated['direction'],
                'actionable': actionable,
                'confidence': evaluated['confidence'],
                'tier': evaluated['tier'],
                'tier_color': evaluated['tier_color'],
                'edge': evaluated['edge'],
                'ev_roi': evaluated['ev_roi'],
                'kelly_fraction': evaluated['kelly_fraction'],
                'american_odds': evaluated['american_odds'],
                'odds_side': evaluated['direction'] if evaluated['american_odds'] is not None else None,
                'bookmaker': bookmaker,
                'implied_probability': evaluated['implied_probability'],
                'break_even_probability': evaluated['break_even_probability'],
                'hit_rate': evaluated['hit_rate'],
                'hit_rate_games': evaluated['hit_rate_games'],
                'side_evaluations': {item['direction'].lower(): item for item in evaluations},
                'prediction_interval_68': probs['ci_68'],
                'prediction_interval_95': probs['ci_95'],
                'prediction_interval_68_coverage': probs['ci_68_coverage'],
                'prediction_interval_95_coverage': probs['ci_95_coverage'],
                'interval_method': probs['interval_method'],
                'probability_unit': 'fraction',
                'ev_roi_unit': 'fraction_per_unit_staked',
                'kelly_unit': 'bankroll_fraction',
                'variance': {
                    'fano': sim_res['params'].get('fano'),
                    'source': sim_res['params'].get('fano_source', 'heuristic'),
                    'high_variance': high_variance,
                    'sample_size': sim_res['params'].get('empirical_games'),
                },
            }

            proj_data_for_summary = dict(proj_data)
            proj_data_for_summary.update({
                'player': response['player'],
                'projection': mean_proj,
                'tier': evaluated['tier'],
                'direction': direction or 'NO BET',
                'confidence': evaluated['confidence'],
                'edge': evaluated['edge'],
                'ev_roi': evaluated['ev_roi'],
                'american_odds': evaluated['american_odds'],
            })
            response['summary'] = date_engineer.generate_pick_summary(proj_data_for_summary, line)

            if record_requested:
                recording = {
                    'requested': True,
                    'recorded': False,
                    'prediction_id': None,
                    'reason': None,
                }
                today = _date.fromisoformat(eastern_today())
                if not prediction_eligible or parsed_date < today:
                    recording['reason'] = (
                        limitations[0]
                        if limitations
                        else 'Historical projections cannot be issued as live picks.'
                    )
                elif not offered_sides:
                    recording['reason'] = 'A line and side-specific price are required to save a pick.'
                elif selected is None:
                    if evaluated.get('ev_roi') is not None and evaluated['ev_roi'] > 0:
                        recording['reason'] = (
                            f"The {evaluated['tier']} result is not an actionable pick."
                        )
                    else:
                        recording['reason'] = 'No positive-EV priced side was found.'
                elif not is_actionable_tier(evaluated['tier']):
                    recording['reason'] = f"The {evaluated['tier']} result is not an actionable pick."
                else:
                    configured_token = os.environ.get('LEDGER_WRITE_TOKEN')
                    supplied_token = request.headers.get('X-Ledger-Write-Token')
                    if not configured_token:
                        recording['reason'] = (
                            'Ledger writes are disabled until LEDGER_WRITE_TOKEN is configured.'
                        )
                    elif not supplied_token or not secrets.compare_digest(
                        supplied_token, configured_token
                    ):
                        recording['reason'] = 'Ledger write authorization failed.'
                    else:
                        try:
                            fresh_game, issuance_error = _verify_fresh_pregame(
                                date_loader,
                                team_id,
                                opp_id,
                                date_str,
                                home_game,
                            )
                        except Exception as exc:
                            log.warning(
                                'Fresh schedule verification failed before issuing %s: %s',
                                response['player'],
                                exc,
                            )
                            fresh_game = None
                            issuance_error = (
                                'The schedule provider could not freshly verify the '
                                'pregame state; the pick was not recorded.'
                            )

                        if issuance_error:
                            recording['reason'] = issuance_error
                            _downgrade_projection_response(
                                response, issuance_error, fresh_game
                            )
                        else:
                            response['schedule'].update({
                                'verified': True,
                                'game_id': fresh_game.get('game_id'),
                                'status': fresh_game.get('status'),
                                'status_text': fresh_game.get('status_text'),
                                'freshly_verified_at': _utc_now(),
                            })
                            response['metadata'].update({
                                'schedule_verified': True,
                                'game_status': fresh_game.get('status'),
                            })
                            try:
                                from src.ledger import PredictionLedger

                                team_abbr = response.get('team')
                                if not team_abbr:
                                    from nba_api.stats.static import teams as nba_teams_static

                                    team_abbr = next(
                                        (
                                            team['abbreviation']
                                            for team in nba_teams_static.get_teams()
                                            if team['id'] == team_id
                                        ),
                                        None,
                                    )
                                ledger = PredictionLedger(
                                    os.environ.get(
                                        'PREDICTIONS_DB_PATH', 'data/predictions.db'
                                    )
                                )
                                prediction_id = ledger.record_prediction(
                                    game_date=date_str,
                                    player=response['player'],
                                    team=team_abbr,
                                    opponent=opp_team,
                                    is_home=home_game,
                                    projection=mean_proj,
                                    line=line,
                                    american_odds=evaluated['american_odds'],
                                    direction=direction,
                                    tier=evaluated['tier'],
                                    confidence=evaluated['confidence'],
                                    over_prob=over_prob,
                                    under_prob=under_prob,
                                    push_prob=probs['push_probability'],
                                    ev_roi=evaluated['ev_roi'],
                                    bookmaker=bookmaker or 'manual',
                                    odds_side=evaluated['direction'],
                                    implied_prob=evaluated['implied_probability'],
                                    edge=evaluated['edge'],
                                    kelly_fraction=evaluated['kelly_fraction'],
                                    model_version=MODEL_VERSION,
                                    input_snapshot={
                                        'components': response['components'],
                                        'context': response['context'],
                                        'injuries': response['injuries'],
                                        'trend': response['trend'],
                                        'data_freshness': response['data_freshness'],
                                        'variance': response['analysis']['variance'],
                                        'spread': spread,
                                        'home_game': home_game,
                                        'matchup_player': matchup,
                                        'schedule': response['schedule'],
                                    },
                                )
                                recording.update({
                                    'recorded': prediction_id is not None,
                                    'prediction_id': prediction_id,
                                    'reason': (
                                        None
                                        if prediction_id is not None
                                        else 'The pick was not actionable.'
                                    ),
                                })
                            except Exception:
                                log.exception("Failed to save issued prediction")
                                recording['reason'] = (
                                    'The projection succeeded, but the ledger is unavailable.'
                                )
                response['recording'] = recording
        else:
            probs = simulator.get_probabilities(sim_res, mean_proj)
            response['range'] = {
                'low': probs['ci_68'][0],
                'high': probs['ci_68'][1],
                'level': 0.68,
                'actual_coverage': probs['ci_68_coverage'],
                'method': probs['interval_method'],
            }
            if record_requested:
                response['recording'] = {
                    'requested': True,
                    'recorded': False,
                    'prediction_id': None,
                    'reason': 'A line and side-specific price are required to save a pick.',
                }

        return jsonify(response)

    except APIValidationError as exc:
        return jsonify({'error': str(exc), 'code': 'invalid_request'}), 400
    except Exception as e:
        log.exception(f"Error in /predict: {e}")
        return jsonify({
            'error': 'The projection service is temporarily unavailable.',
            'code': 'projection_service_unavailable',
        }), 503


@app.route('/games')
def get_games():
    """Return the list of NBA games for a given date."""
    from nba_api.stats.static import teams as nba_teams_static
    try:
        date_str, parsed_date = _parse_date(request.args.get('date'), default=eastern_today())
        date_loader, _ = _components_for_date(parsed_date)
        if parsed_date >= _date.fromisoformat(eastern_today()):
            raw_games = date_loader.get_games_for_date_fresh(date_str)
        else:
            raw_games = date_loader.get_games_for_date(date_str)
        if not raw_games:
            return jsonify({
                'date': date_str,
                'games': [],
                'message': f'No games found for {date_str}.',
            })

        all_teams = {t['id']: t['abbreviation'] for t in nba_teams_static.get_teams()}
        games = [
            {
                'id': g.get('game_id'),
                'date': date_str,
                'home': all_teams.get(g['home_id'], '???'),
                'away': all_teams.get(g['away_id'], '???'),
                'status': g.get('status'),
                'status_text': g.get('status_text'),
                'game_time': g.get('game_time'),
            }
            for g in raw_games
        ]
        return jsonify({'date': date_str, 'games': games})

    except APIValidationError as exc:
        return jsonify({'error': str(exc), 'code': 'invalid_request'}), 400
    except Exception as e:
        log.exception("Failed to retrieve NBA schedule")
        return jsonify({
            'error': 'The NBA schedule provider is temporarily unavailable.',
            'code': 'schedule_unavailable',
        }), 503


@app.route('/cheat-sheet')
def cheat_sheet():
    """Projections for every rostered player in a given game."""
    try:
        team_abbr = str(request.args.get('team') or '').strip().upper()
        if len(team_abbr) != 3 or not team_abbr.isalpha():
            raise APIValidationError("'team' must be a three-letter NBA abbreviation")
        date_str, parsed_date = _parse_date(request.args.get('date'), default=eastern_today())
        book = str(request.args.get('book') or 'fanduel').strip().lower()
        if not book or len(book) > 40 or any(ch not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for ch in book):
            raise APIValidationError("'book' contains unsupported characters")

        date_loader, date_engineer = _components_for_date(parsed_date)
        if parsed_date >= _date.fromisoformat(eastern_today()):
            raw_games = date_loader.get_games_for_date_fresh(date_str)
        else:
            raw_games = date_loader.get_games_for_date(date_str)
        from nba_api.stats.static import teams as nba_teams_static
        all_teams = {t['id']: t['abbreviation'] for t in nba_teams_static.get_teams()}
        abbr_to_id = {v: k for k, v in all_teams.items()}

        requested_team_id = abbr_to_id.get(team_abbr)
        if not requested_team_id:
            return jsonify({'error': f'Unknown NBA team: {team_abbr}', 'code': 'team_not_found'}), 404

        selected_game = None
        for g in raw_games:
            if requested_team_id in (g.get('home_id'), g.get('away_id')):
                selected_game = g
                break

        if not selected_game:
            return jsonify({
                'error': f'No game found for {team_abbr} on {date_str}.',
                'code': 'game_not_found',
            }), 404

        home_id = selected_game['home_id']
        away_id = selected_game['away_id']
        home_abbr = all_teams.get(home_id)
        away_abbr = all_teams.get(away_id)
        if not home_abbr or not away_abbr:
            raise RuntimeError("Schedule contained an unknown NBA team identifier")

        odds_key = os.environ.get('ODDS_API_KEY', '')
        player_odds = {}
        odds_error = None
        if odds_key:
            try:
                player_odds = date_loader.get_odds_for_game(
                    odds_key,
                    home_abbr,
                    away_abbr,
                    date_str,
                    bookmaker=book,
                )
            except Exception as exc:
                odds_error = 'Live sportsbook prices are temporarily unavailable.'
                log.warning("Odds lookup failed for %s @ %s: %s", away_abbr, home_abbr, exc)

        odds_meta = player_odds.get('_meta', {}) if isinstance(player_odds, dict) else {}
        home_spread = odds_meta.get('home_spread')
        away_spread = odds_meta.get('away_spread')

        home_rest = date_loader.get_days_rest(home_id, as_of=date_str)
        away_rest = date_loader.get_days_rest(away_id, as_of=date_str)
        home_diagnostics = {}
        away_diagnostics = {}

        home_results = project_team(
            date_loader,
            date_engineer,
            simulator,
            home_id,
            home_abbr,
            away_abbr,
            True,
            home_rest,
            away_rest,
            player_odds,
            date_str,
            spread=home_spread,
            diagnostics=home_diagnostics,
        )
        away_results = project_team(
            date_loader,
            date_engineer,
            simulator,
            away_id,
            away_abbr,
            home_abbr,
            False,
            away_rest,
            home_rest,
            player_odds,
            date_str,
            spread=away_spread,
            diagnostics=away_diagnostics,
        )

        projections = home_results + away_results
        warnings = []
        team_diagnostics = [home_diagnostics, away_diagnostics]
        if not projections and any(
            diagnostic.get('all_failed') for diagnostic in team_diagnostics
        ):
            return jsonify({
                'error': 'Every roster projection failed; no cheat sheet was produced.',
                'code': 'projection_pipeline_failed',
            }), 503
        if any(
            diagnostic.get('status') in {'partial_failure', 'all_failed'}
            or (diagnostic.get('failed_count') or 0) > 0
            for diagnostic in team_diagnostics
        ):
            warnings.append(
                'Some player projections were unavailable; the slate is partial.'
            )

        max_odds_age = _max_actionable_odds_age_seconds()
        stale_quote_count = 0
        fresh_quote_count = 0
        snapshot_timestamp = odds_meta.get('fetched_at')
        provider_snapshot_timestamp = odds_meta.get('updated_at')
        for row in projections:
            if row.get('line') is None or row.get('american_odds') is None:
                row['odds_fresh'] = None
                row['odds_age_seconds'] = None
                continue
            # Prefer the sportsbook/provider update time. A newly fetched HTTP
            # response can still contain an old, suspended market snapshot.
            quote_timestamp = (
                row.get('odds_updated_at')
                or provider_snapshot_timestamp
                or snapshot_timestamp
            )
            quote_age = _odds_timestamp_age_seconds(quote_timestamp)
            quote_is_fresh = quote_age is not None and quote_age <= max_odds_age
            row['odds_fresh'] = quote_is_fresh
            row['odds_age_seconds'] = (
                round(quote_age, 1) if quote_age is not None else None
            )
            if quote_is_fresh:
                fresh_quote_count += 1
                continue
            stale_quote_count += 1
            warning = (
                'The selected sportsbook quote is stale or has no trustworthy '
                'timestamp, so it is diagnostic only.'
            )
            _downgrade_cheat_row(row, 'STALE_ODDS', warning)
        if stale_quote_count:
            warnings.append(
                'One or more sportsbook quotes were stale or lacked a trustworthy '
                'timestamp; affected rows are not actionable.'
            )

        if not _is_pregame(selected_game):
            warning = (
                'The game is not in a verified pregame state; all projections '
                'are diagnostic and no rows are actionable.'
            )
            warnings.append(warning)
            for row in projections:
                _downgrade_cheat_row(
                    row,
                    'GAME_NOT_PREGAME',
                    warning,
                    prediction_eligible=False,
                )

        projections.sort(key=lambda item: (
            not bool(item.get('actionable')),
            -(item.get('ev_roi') if item.get('ev_roi') is not None else float('-inf')),
            -(item.get('confidence') if item.get('confidence') is not None else float('-inf')),
            -float(item.get('projection', 0.0)),
        ))

        return jsonify({
            'game': {
                'id': selected_game.get('game_id'),
                'date': date_str,
                'home': home_abbr,
                'away': away_abbr,
                'status': selected_game.get('status'),
                'status_text': selected_game.get('status_text'),
            },
            'bookmaker': odds_meta.get('book') or book,
            'odds': {
                'available': any(
                    row.get('line') is not None
                    and row.get('american_odds') is not None
                    for row in projections
                ),
                'fresh': fresh_quote_count > 0 if fresh_quote_count + stale_quote_count else None,
                'stale_quote_count': stale_quote_count,
                'max_actionable_age_seconds': max_odds_age,
                'source': odds_meta.get('source'),
                'fetched_at': odds_meta.get('fetched_at'),
                'updated_at': odds_meta.get('updated_at'),
                'error': odds_error,
            },
            'warnings': warnings,
            'projection_status': {
                'home': {
                    key: home_diagnostics.get(key)
                    for key in (
                        'status',
                        'roster_count',
                        'attempted_count',
                        'projected_count',
                        'failed_count',
                    )
                },
                'away': {
                    key: away_diagnostics.get(key)
                    for key in (
                        'status',
                        'roster_count',
                        'attempted_count',
                        'projected_count',
                        'failed_count',
                    )
                },
            },
            'generated_at': _utc_now(),
            'model_version': MODEL_VERSION,
            'season': date_loader.season,
            'projections': projections,
        })

    except APIValidationError as exc:
        return jsonify({'error': str(exc), 'code': 'invalid_request'}), 400
    except Exception:
        log.exception("Failed to generate cheat sheet")
        return jsonify({
            'error': 'The Daily Edge service is temporarily unavailable.',
            'code': 'cheat_sheet_unavailable',
        }), 503


if __name__ == '__main__':
    app.run(debug=True, port=5001)
