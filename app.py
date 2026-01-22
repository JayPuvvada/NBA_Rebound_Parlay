import sys
from flask import Flask, render_template, request, jsonify
from src.data_loader import NBADataLoader
from src.features import FeatureEngineer
from src.model import ReboundSimulator
import traceback

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

if __name__ == '__main__':
    app.run(debug=True, port=5001)
