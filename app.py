import sys
import pandas as pd
from flask import Flask, render_template, request, jsonify
from src.data_loader import NBADataLoader
from src.features import FeatureEngineer
from src.model import ReboundSimulator
import traceback
import os
from dotenv import load_dotenv
from flask_cors import CORS

load_dotenv() # Load .env file

# app configuration
app = Flask(__name__, static_folder="frontend/dist", static_url_path="/")
CORS(app)

# Initialize components globally to avoid reloading on every request (Simulate cold start)
try:
    print("Initializing Model Components...", file=sys.stdout)
    loader = NBADataLoader()
    engineer = FeatureEngineer(loader)
    simulator = ReboundSimulator()
    print("Model Components Initialized.", file=sys.stdout)
except Exception as e:
    print(f"Error initializing components: {e}", file=sys.stderr)
    traceback.print_exc()

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    import os
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return app.send_static_file(path)
    else:
        return app.send_static_file('index.html')

@app.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.get_json()
        
        player_name = data.get('player')
        opp_team = data.get('opponent').upper()
        spread = float(data.get('spread', 0.0))
        
        # Optional fields
        line_val = data.get('line')
        line = float(line_val) if line_val else None
        
        # Odds Input (American odds, e.g. -110)
        odds_val = data.get('odds')
        american_odds = int(odds_val) if odds_val else None
        
        matchup_val = data.get('matchup')
        matchup = matchup_val if matchup_val else None

        # Get Player ID
        pid = loader.get_player_id(player_name)
        if not pid:
            return jsonify({'error': f"Player '{player_name}' not found."}), 404

        # Get Team IDs for Rest Calculation
        p_info = loader.get_common_player_info(pid)
        if p_info.empty:
             return jsonify({'error': 'Player info not found'}), 404
        team_id = p_info.iloc[0]['TEAM_ID']
        opp_id = loader.get_team_id(opp_team)
        
        # Calculate Rest Days
        team_rest = loader.get_days_rest(team_id)
        opp_rest = loader.get_days_rest(opp_id) if opp_id else 1
        
        # Compute Features
        proj_data = engineer.compute_composite_projection(
            pid, 
            opp_team, 
            spread=spread,
            home_game=True,    # Default to home for simplicity, or add toggle later
            days_rest=team_rest,
            opp_days_rest=opp_rest,
            matchup_player=matchup
        )
        
        if not proj_data or 'error' in proj_data:
             return jsonify({'error': proj_data.get('error', 'Unknown error generating projection')}), 500

        mean_proj = proj_data['projection']
        
        # Simulation (with variance-aware data)
        player_var_data = proj_data.get('player_variance')
        sim_res = simulator.simulate(proj_data, market_line=line, player_variance=player_var_data)
        
        # Prepare Response
        response = {
            'player': player_name,
            'opponent': opp_team,
            'projection': round(mean_proj, 1),
            'context': proj_data.get('matchup_context', 'Neutral'),
            'injuries': {
                'matchup': proj_data.get('matchup_injury'),
                'team': proj_data.get('team_injury'),
                'team_list': proj_data.get('team_injury_list', []),
                'opp_list': proj_data.get('opp_injury_list', [])
            },
            'components': proj_data.get('components', {}),
            'trend': proj_data.get('trend_data', [])
        }
        
        # If line provided, add probability analysis
        if line is not None:
            probs = simulator.get_probabilities(sim_res, line)
            
            over_prob = probs['over_probability']
            under_prob = probs['under_probability']
            confidence = max(over_prob, under_prob)
            direction = "OVER" if over_prob > under_prob else "UNDER"
            
            # Trend Analysis (Hit Rate)
            trend_data = proj_data.get('trend_data', [])
            hit_count = 0
            valid_games = 0
            for game in trend_data:
                valid_games += 1
                if direction == "OVER" and game['rebounds'] > line: hit_count += 1
                elif direction == "UNDER" and game['rebounds'] < line: hit_count += 1
            
            hit_rate = (hit_count / valid_games) if valid_games > 0 else 0.0
            
            # Floor Check (Safe Play)
            # 16th percentile ~ -1 STD. 
            floor_val = probs['ci_68'][0] # Lower bound of 68% CI
            
            # Recommendation Logic (5-Tier)
            tier = "AVOID"
            rec_color = "red" # Default (Avoid/Lean)
            
            # 1. STRONG PLAY
            if confidence > 0.635:
                tier = "STRONG PLAY"
                rec_color = "green"
            
            # 2. PLAY
            elif confidence > 0.585:
                tier = "PLAY"
                rec_color = "green"
                
            # 3. SAFE PLAY (Floor Check)
            # If bet is OVER and Line < Floor -> Safe
            elif direction == "OVER" and line < floor_val:
                tier = "SAFE PLAY"
                rec_color = "blue"
            
            # 4. TREND LEAN (Math Neutral, Trend Hot)
            # If hit rate >= 70% in last 10
            elif hit_rate >= 0.70:
                tier = "TREND LEAN"
                rec_color = "purple"
                
            # 5. LEAN (Small Edge)
            elif confidence > 0.555:
                tier = "LEAN"
                rec_color = "yellow"
            
            # 6. AVOID (Explicit check logic, though 'else' covers it)
            # Default is AVOID.
            
            edge = confidence - 0.535 # Breakeven
            
            response['analysis'] = {
                'line': line,
                'over_prob': round(over_prob * 100, 1),
                'under_prob': round(under_prob * 100, 1),
                'confidence': round(confidence * 100, 1),
                'recommendation': f"{tier}",
                'rec_color': rec_color,
                'edge': round(edge * 100, 1),
                'hit_rate': round(hit_rate * 100, 0),
                'fano': sim_res['params'].get('fano'),
                'fano_source': sim_res['params'].get('fano_source', 'heuristic')
            }
            
            # True Edge from American Odds (if provided)
            if american_odds:
                if american_odds < 0:
                    implied_prob = abs(american_odds) / (abs(american_odds) + 100)
                else:
                    implied_prob = 100 / (american_odds + 100)
                true_edge = confidence - implied_prob
                response['analysis']['implied_prob'] = round(implied_prob * 100, 1)
                response['analysis']['true_edge'] = round(true_edge * 100, 1)
                response['analysis']['american_odds'] = american_odds
            
            # Generate summary
            summary = engineer.generate_pick_summary(proj_data, line)
            response['summary'] = summary
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
        date_str = request.args.get('date')
        if not date_str:
            from datetime import date
            date_str = date.today().isoformat()

        raw_games = loader.get_games_for_date(date_str)
        if not raw_games:
            return jsonify({'games': [], 'message': f'No games found for {date_str}.'})

        # Map team IDs to abbreviations
        all_teams = {t['id']: t['abbreviation'] for t in nba_teams_static.get_teams()}

        games = []
        for g in raw_games:
            home_abbr = all_teams.get(g['home_id'], '???')
            away_abbr = all_teams.get(g['away_id'], '???')
            games.append({'home': home_abbr, 'away': away_abbr})

        return jsonify({'games': games})

    except Exception as e:
        traceback.print_exc()
        return jsonify({'games': [], 'message': str(e)}), 500


@app.route('/cheat-sheet')
def cheat_sheet():
    """
    Generate projections for every rostered player in a game.
    Query params: team (home team abbrev), date, book (sportsbook key).
    """
    try:
        home_abbr = request.args.get('team', '').upper()
        date_str = request.args.get('date')
        book = request.args.get('book', 'fanduel')

        if not home_abbr:
            return jsonify({'error': 'Missing team parameter'}), 400

        # Find the game for the given date involving this team
        raw_games = loader.get_games_for_date(date_str) if date_str else []

        from nba_api.stats.static import teams as nba_teams_static
        all_teams = {t['id']: t['abbreviation'] for t in nba_teams_static.get_teams()}
        abbr_to_id = {v: k for k, v in all_teams.items()}

        home_id = abbr_to_id.get(home_abbr)
        if not home_id:
            return jsonify({'error': f'Unknown team: {home_abbr}'}), 404

        # Find away team from the schedule
        away_abbr = None
        for g in raw_games:
            if g['home_id'] == home_id:
                away_abbr = all_teams.get(g['away_id'], '???')
                break
            elif g['away_id'] == home_id:
                # The queried team is actually away; swap perspective
                away_abbr = all_teams.get(g['home_id'], '???')
                break

        if not away_abbr:
            return jsonify({'error': f'No game found for {home_abbr} on {date_str}'}), 404

        away_id = abbr_to_id.get(away_abbr)

        # Fetch odds (optional – won't fail if API key missing)
        odds_key = os.environ.get('ODDS_API_KEY', '')
        player_odds = {}
        if odds_key:
            try:
                player_odds = loader.get_odds_for_game(odds_key, home_abbr, away_abbr, date_str, bookmaker=book)
            except Exception:
                traceback.print_exc()

        # Rest days
        home_rest = loader.get_days_rest(home_id)
        away_rest = loader.get_days_rest(away_id) if away_id else 1

        # Helper to build projections for one team's roster
        def project_team(team_id, team_abbr, opp_abbr, is_home, team_rest, opp_rest):
            from src.data_loader import normalize_name
            roster = loader.get_team_roster(team_id)
            if roster.empty:
                return []

            results = []
            for _, row in roster.iterrows():
                pid = row['PLAYER_ID']
                pname = row['PLAYER']
                try:
                    proj_data = engineer.compute_composite_projection(
                        pid, opp_abbr, spread=0,
                        home_game=is_home,
                        days_rest=team_rest,
                        opp_days_rest=opp_rest
                    )
                    if not proj_data or 'error' in proj_data:
                        continue

                    mean_proj = proj_data['projection']

                    # Match odds by normalized name
                    norm_name = normalize_name(pname)
                    odds_entry = player_odds.get(norm_name, {})
                    line = odds_entry.get('line')
                    odds_val = odds_entry.get('odds')

                    # Compute direction/tier if line exists
                    direction = '-'
                    tier = '-'
                    over_prob = None
                    under_prob = None
                    confidence = None

                    if line is not None:
                        player_var = proj_data.get('player_variance')
                        sim_res = simulator.simulate(proj_data, market_line=line, player_variance=player_var)
                        probs = simulator.get_probabilities(sim_res, line)

                        over_prob = probs['over_probability']
                        under_prob = probs['under_probability']
                        confidence = max(over_prob, under_prob)
                        direction = 'OVER' if over_prob > under_prob else 'UNDER'

                        # Tier logic (mirrors /predict)
                        trend_data = proj_data.get('trend_data', [])
                        hit_count = sum(1 for g in trend_data if (direction == 'OVER' and g['rebounds'] > line) or (direction == 'UNDER' and g['rebounds'] < line))
                        hit_rate = hit_count / len(trend_data) if trend_data else 0

                        floor_val = probs['ci_68'][0]

                        if confidence > 0.635:
                            tier = 'STRONG PLAY'
                        elif confidence > 0.585:
                            tier = 'PLAY'
                        elif direction == 'OVER' and line < floor_val:
                            tier = 'SAFE PLAY'
                        elif hit_rate >= 0.70:
                            tier = 'TREND LEAN'
                        elif confidence > 0.555:
                            tier = 'LEAN'
                        else:
                            tier = 'AVOID'

                    rest_note = f"{'Home' if is_home else 'Away'}"
                    if team_rest == 0:
                        rest_note += " B2B"

                    entry = {
                        'player': pname,
                        'team': team_abbr,
                        'opponent': opp_abbr,
                        'projection': round(mean_proj, 1),
                        'line': line if line is not None else '-',
                        'direction': direction,
                        'tier': tier,
                        'rest_note': rest_note,
                        'context': proj_data.get('matchup_context', ''),
                        'components': proj_data.get('components', {}),
                        'trend': proj_data.get('trend_data', []),
                    }
                    if confidence is not None:
                        entry['confidence'] = round(confidence * 100, 1)
                    if over_prob is not None:
                        entry['over_prob'] = round(over_prob * 100, 1)
                        entry['under_prob'] = round(under_prob * 100, 1)

                    results.append(entry)

                except Exception as player_err:
                    print(f"DEBUG: Skipping {pname}: {player_err}", flush=True)
                    continue

            # Sort by projection descending
            results.sort(key=lambda x: x['projection'], reverse=True)
            return results

        # Project both teams
        home_results = project_team(home_id, home_abbr, away_abbr, True, home_rest, away_rest)
        away_results = project_team(away_id, away_abbr, home_abbr, False, away_rest, home_rest)

        return jsonify(home_results + away_results)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5001)
