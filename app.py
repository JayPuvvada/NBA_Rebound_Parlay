import sys
import pandas as pd
from flask import Flask, render_template, request, jsonify
from src.data_loader import NBADataLoader
from src.features import FeatureEngineer
from src.model import ReboundSimulator
import traceback
import os
from dotenv import load_dotenv

load_dotenv() # Load .env file

# app configuration
app = Flask(__name__)

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

@app.route('/')
def index():
    return render_template('index.html')

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
        
        # Simulation
        sim_res = simulator.simulate(proj_data, market_line=line)
        
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
                'hit_rate': round(hit_rate * 100, 0)
            }
            
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

@app.route('/cheat-sheet', methods=['GET'])
def cheat_sheet():
    """
    Automated 'Best Bets' Dashboard V2 (User Driven).
    Params:
    - team: Team Code (e.g. LAL)
    - date: YYYY-MM-DD
    """
    try:
        req_sub_team = request.args.get('team')
        req_date = request.args.get('date')
        req_book = request.args.get('book', 'fanduel')  # Default to fanduel
        
        if not req_sub_team or not req_date:
            return jsonify({'error': 'Please select a Team and Date.'}), 400
            
        req_sub_team = req_sub_team.upper()

        # 1. Get Games for Date
        games = loader.get_games_for_date(req_date)
        if not games:
            return jsonify({'error': f"No games found for {req_date}."}), 404
            
        # 2. Find Specific Game
        target_game = None
        
        # We need to resolve IDs to Codes to match user input
        # Dictionary of Team ID -> Code (Static for speed/reliability)
        id_to_code = {
            1610612737: 'ATL', 1610612738: 'BOS', 1610612751: 'BKN', 1610612766: 'CHA', 1610612741: 'CHI',
            1610612739: 'CLE', 1610612742: 'DAL', 1610612743: 'DEN', 1610612765: 'DET', 1610612744: 'GSW',
            1610612745: 'HOU', 1610612754: 'IND', 1610612746: 'LAC', 1610612747: 'LAL', 1610612763: 'MEM',
            1610612748: 'MIA', 1610612749: 'MIL', 1610612750: 'MIN', 1610612740: 'NOP', 1610612752: 'NYK',
            1610612760: 'OKC', 1610612753: 'ORL', 1610612755: 'PHI', 1610612756: 'PHX', 1610612757: 'POR',
            1610612758: 'SAC', 1610612759: 'SAS', 1610612761: 'TOR', 1610612762: 'UTA', 1610612764: 'WAS'
        }
        
        for g in games:
            h_code = id_to_code.get(g['home_id'], 'UNK')
            a_code = id_to_code.get(g['away_id'], 'UNK')
            
            if h_code == req_sub_team or a_code == req_sub_team:
                target_game = g
                target_game['home_team'] = h_code # Update with resolved code
                target_game['away_team'] = a_code
                break
        
        if not target_game:
             return jsonify({'error': f"Game with {req_sub_team} not found on {req_date}."}), 404

        # 3. Get Odds (Targeted)
        api_key = os.getenv('ODDS_API_KEY')
        odds_map = {}
        if api_key:
            odds_map = loader.get_odds_for_game(
                api_key, 
                target_game['home_team'], 
                target_game['away_team'], 
                req_date,
                req_book
            )
            
        results = []
        home_id = target_game['home_id']
        away_id = target_game['away_id']
        home_team = target_game['home_team']
        away_team = target_game['away_team']

        # Process BOTH teams in that game
        for team_data in [(home_id, home_team, away_team), (away_id, away_team, home_team)]:
            tid, t_code, opp_code = team_data
            
            # Fetch Roster
            roster = loader.get_team_roster(tid)
            
            # We need adv stats to get minutes
            # Use loader cache
            loader.get_player_advanced_stats(0) # Prime cache
            adv_stats = loader._get_from_cache(f"league_player_stats_advanced_{loader.season}")
            
            if not roster.empty and adv_stats is not None:
                 # Merge
                 merged = pd.merge(roster, adv_stats[['PLAYER_ID', 'MIN']], on='PLAYER_ID')
                 merged = merged.sort_values('MIN', ascending=False).head(5) # Top 5 rotation
                 
                 for _, player in merged.iterrows():
                     pid = player['PLAYER_ID']
                     pname = player['PLAYER']
                     
                     # Check Rest
                     rest = loader.get_days_rest(tid)
                     opp_rest_val = loader.get_days_rest(away_id if tid == home_id else home_id)
                     
                     try:
                         proj = engineer.compute_composite_projection(
                             pid, 
                             opp_code, 
                             days_rest=rest, 
                             opp_days_rest=opp_rest_val,
                             home_game=(tid == home_id)
                         )
                         
                         if 'error' in proj or proj['projection'] < 4.0: 
                             continue 
                             
                         # Check Odds
                         from unidecode import unidecode
                         norm_name = unidecode(pname).lower().replace('.', '').strip()
                         
                         line_info = odds_map.get(norm_name)
                         rec_tier = "Waiting for Line"
                         edge = 0
                         line_val = 0
                         
                         if line_info:
                             line_val = line_info['line']
                             # Run Simulation for EV
                             sim = simulator.simulate(proj, market_line=line_val)
                             probs = simulator.get_probabilities(sim, line_val)
                             
                             confidence = max(probs['over_probability'], probs['under_probability'])
                             direction = "OVER" if probs['over_probability'] > probs['under_probability'] else "UNDER"
                             
                             if confidence > 0.635: rec_tier = "🔥 STRONG PLAY"
                             elif confidence > 0.585: rec_tier = "✅ PLAY"
                             elif direction == "OVER" and line_val < probs['ci_68'][0]: rec_tier = "🛡️ SAFE PLAY"
                             elif confidence > 0.555: rec_tier = "👉 LEAN"
                             else: rec_tier = "🛑 AVOID"
                             
                             edge = confidence - 0.50
                         else:
                             rec_tier = "-"
                             
                         results.append({
                             'player': pname,
                             'team': t_code,
                             'opponent': opp_code,
                             'projection': round(proj['projection'], 1),
                             'line': line_val if line_info else '-',
                             'direction': direction if line_info else '-',
                             'tier': rec_tier,
                             'edge_raw': edge,
                             'rest_note': f"{rest}d vs {opp_rest_val}d"
                         })
                         
                     except Exception as e:
                         print(f"Skipping {pname}: {e}")
                         continue

        # Sort by Edge (Descending) -> then Projection
        results.sort(key=lambda x: (x['tier'] == "🔥 STRONG PLAY", x['edge_raw'], x['projection']), reverse=True)
        
        return jsonify(results)

    except Exception as e:
        return jsonify({'error': str(e)}), 500



if __name__ == '__main__':
    app.run(debug=True, port=5001)
