import os
import sys
import traceback
from datetime import date as _date

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from src.data_loader import NBADataLoader
from src.features import FeatureEngineer
from src.model import ReboundSimulator
from src.recommendation import weighted_hit_rate, tier_from_signals, edge_from_odds
from src.cheat_sheet import project_team
from src.utils import get_logger

load_dotenv()
log = get_logger('app')

app = Flask(__name__, static_folder="frontend/dist", static_url_path="/")
CORS(app)

# Eager init; avoids cold start on every request.
try:
    log.info("Initializing model components...")
    loader = NBADataLoader()
    engineer = FeatureEngineer(loader)
    simulator = ReboundSimulator()
    log.info("Model components initialized.")
except Exception as e:
    log.error(f"Error initializing components: {e}")
    traceback.print_exc()


def _detect_home_game(loader, team_id, date_str):
    """Return True if `team_id` is the home side of their game on `date_str`, else False."""
    if not date_str:
        return None
    try:
        games = loader.get_games_for_date(date_str) or []
        for g in games:
            if g.get('home_id') == team_id:
                return True
            if g.get('away_id') == team_id:
                return False
    except Exception as e:
        log.warning(f"home-game detection failed for team {team_id} on {date_str}: {e}")
    return None


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return app.send_static_file(path)
    return app.send_static_file('index.html')


@app.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.get_json() or {}

        player_name = data.get('player')
        opp_team = (data.get('opponent') or '').upper()
        spread = float(data.get('spread', 0.0) or 0.0)

        line_val = data.get('line')
        line = float(line_val) if line_val not in (None, '') else None

        odds_val = data.get('odds')
        american_odds = int(odds_val) if odds_val not in (None, '') else None

        matchup = data.get('matchup') or None
        date_str = data.get('date') or _date.today().isoformat()

        # Home/away: client-supplied takes precedence, else auto-detect from schedule,
        # else default True (old behavior).
        home_game_raw = data.get('home_game')
        if isinstance(home_game_raw, bool):
            home_game = home_game_raw
        elif isinstance(home_game_raw, str):
            home_game = home_game_raw.lower() in ('true', '1', 'yes', 'home')
        else:
            home_game = None

        pid = loader.get_player_id(player_name)
        if not pid:
            return jsonify({'error': f"Player '{player_name}' not found."}), 404

        p_info = loader.get_common_player_info(pid)
        if p_info.empty:
            return jsonify({'error': 'Player info not found'}), 404

        team_id = p_info.iloc[0]['TEAM_ID']
        opp_id = loader.get_team_id(opp_team)

        if home_game is None:
            detected = _detect_home_game(loader, team_id, date_str)
            home_game = True if detected is None else detected

        team_rest = loader.get_days_rest(team_id)
        opp_rest = loader.get_days_rest(opp_id) if opp_id else loader.DEFAULT_DAYS_REST

        proj_data = engineer.compute_composite_projection(
            pid,
            opp_team,
            spread=spread,
            home_game=home_game,
            days_rest=team_rest,
            opp_days_rest=opp_rest,
            matchup_player=matchup,
        )

        if not proj_data or 'error' in proj_data:
            return jsonify({'error': proj_data.get('error', 'Unknown error generating projection')}), 500

        mean_proj = proj_data['projection']

        player_var_data = proj_data.get('player_variance')
        sim_res = simulator.simulate(proj_data, market_line=line, player_variance=player_var_data)

        response = {
            'player': player_name,
            'opponent': opp_team,
            'projection': round(mean_proj, 1),
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
        }

        if line is not None:
            probs = simulator.get_probabilities(sim_res, line)
            over_prob = probs['over_probability']
            under_prob = probs['under_probability']
            confidence = max(over_prob, under_prob)
            direction = 'OVER' if over_prob > under_prob else 'UNDER'

            trend_data = proj_data.get('trend_data', [])
            hit_rate, n_games = weighted_hit_rate(trend_data, line, direction)
            floor_val = probs['ci_68'][0]

            tier, rec_color = tier_from_signals(confidence, direction, line, floor_val, hit_rate, n_games,
                                                mean_proj=mean_proj)
            edge_info = edge_from_odds(confidence, american_odds)

            response['analysis'] = {
                'line': line,
                'over_prob': round(over_prob * 100, 1),
                'under_prob': round(under_prob * 100, 1),
                'confidence': round(confidence * 100, 1),
                'recommendation': tier,
                'rec_color': rec_color,
                'edge': round(edge_info['edge'] * 100, 1),
                'hit_rate': round(hit_rate * 100, 0),
                'hit_rate_games': n_games,
                'fano': sim_res['params'].get('fano'),
                'fano_source': sim_res['params'].get('fano_source', 'heuristic'),
                'high_variance_flag': sim_res['params'].get('high_variance_flag', False),
                'american_odds': edge_info['american_odds'],
                'implied_prob': round(edge_info['implied_prob'] * 100, 1),
                'true_edge': round(edge_info['edge'] * 100, 1),
            }

            # Narrative summary
            proj_data_for_summary = dict(proj_data)
            proj_data_for_summary.update({
                'player': player_name,
                'projection': mean_proj,
                'tier': tier,
                'direction': direction,
                'confidence': confidence,
                'edge': edge_info['edge'],
            })
            response['summary'] = engineer.generate_pick_summary(proj_data_for_summary, line)
        else:
            probs = simulator.get_probabilities(sim_res, mean_proj)
            response['range'] = f"{probs['ci_68'][0]:.1f} - {probs['ci_68'][1]:.1f}"

        return jsonify(response)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/games')
def get_games():
    """Return the list of NBA games for a given date."""
    from nba_api.stats.static import teams as nba_teams_static
    try:
        date_str = request.args.get('date') or _date.today().isoformat()
        raw_games = loader.get_games_for_date(date_str)
        if not raw_games:
            return jsonify({'games': [], 'message': f'No games found for {date_str}.'})

        all_teams = {t['id']: t['abbreviation'] for t in nba_teams_static.get_teams()}
        games = [
            {
                'home': all_teams.get(g['home_id'], '???'),
                'away': all_teams.get(g['away_id'], '???'),
            }
            for g in raw_games
        ]
        return jsonify({'games': games})

    except Exception as e:
        traceback.print_exc()
        return jsonify({'games': [], 'message': str(e)}), 500


@app.route('/cheat-sheet')
def cheat_sheet():
    """Projections for every rostered player in a given game."""
    try:
        home_abbr = (request.args.get('team', '') or '').upper()
        date_str = request.args.get('date')
        book = request.args.get('book', 'fanduel')

        if not home_abbr:
            return jsonify({'error': 'Missing team parameter'}), 400

        raw_games = loader.get_games_for_date(date_str) if date_str else []

        from nba_api.stats.static import teams as nba_teams_static
        all_teams = {t['id']: t['abbreviation'] for t in nba_teams_static.get_teams()}
        abbr_to_id = {v: k for k, v in all_teams.items()}

        home_id = abbr_to_id.get(home_abbr)
        if not home_id:
            return jsonify({'error': f'Unknown team: {home_abbr}'}), 404

        # Find the opponent abbreviation from the schedule.
        away_abbr = None
        for g in raw_games:
            if g['home_id'] == home_id:
                away_abbr = all_teams.get(g['away_id'], '???')
                break
            if g['away_id'] == home_id:
                # Queried team is actually the away side; swap perspective.
                away_abbr = all_teams.get(g['home_id'], '???')
                break

        if not away_abbr:
            return jsonify({'error': f'No game found for {home_abbr} on {date_str}'}), 404

        away_id = abbr_to_id.get(away_abbr)

        # Odds (optional – missing key just means no lines attached).
        odds_key = os.environ.get('ODDS_API_KEY', '')
        player_odds = {}
        if odds_key:
            try:
                player_odds = loader.get_odds_for_game(odds_key, home_abbr, away_abbr, date_str, bookmaker=book)
            except Exception:
                traceback.print_exc()

        home_rest = loader.get_days_rest(home_id)
        away_rest = loader.get_days_rest(away_id) if away_id else loader.DEFAULT_DAYS_REST

        home_results = project_team(
            loader, engineer, simulator,
            home_id, home_abbr, away_abbr, True, home_rest, away_rest, player_odds
        )
        away_results = project_team(
            loader, engineer, simulator,
            away_id, away_abbr, home_abbr, False, away_rest, home_rest, player_odds
        )

        return jsonify(home_results + away_results)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5001)
