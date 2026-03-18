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
app = Flask(__name__)
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

@app.route('/parlay', methods=['POST'])
def parlay():
    """
    Parlay Builder: Accepts multiple picks and calculates combined probability.
    Each leg: {player, opponent, spread, line, direction}
    Supports: correlation penalty for same-game legs, EV calculation.
    """
    try:
        data = request.get_json()
        legs = data.get('legs', [])
        parlay_odds_input = data.get('parlay_odds')  # American odds offered
        
        if len(legs) < 2:
            return jsonify({'error': 'Parlay requires at least 2 legs'}), 400
        if len(legs) > 8:
            return jsonify({'error': 'Maximum 8 legs allowed'}), 400
        
        results = []
        combined_prob = 1.0
        game_teams = {}  # Track teams per game for correlation
        
        for i, leg in enumerate(legs):
            try:
                player_name = leg.get('player')
                opp_team = leg.get('opponent', '').upper()
                spread = float(leg.get('spread', 0.0))
                line = float(leg.get('line', 0))
                direction = leg.get('direction', 'OVER').upper()
                
                if not player_name or not opp_team or not line:
                    results.append({'leg': i+1, 'error': 'Missing player, opponent, or line'})
                    combined_prob = 0
                    continue
                
                # Get Player ID
                pid = loader.get_player_id(player_name)
                if not pid:
                    results.append({'leg': i+1, 'player': player_name, 'error': f"Player '{player_name}' not found"})
                    combined_prob = 0
                    continue
                
                # Get rest data
                p_info = loader.get_common_player_info(pid)
                team_id = p_info.iloc[0]['TEAM_ID'] if not p_info.empty else None
                team_abbrev = p_info.iloc[0].get('TEAM_ABBREVIATION', '') if not p_info.empty else ''
                opp_id = loader.get_team_id(opp_team)
                team_rest = loader.get_days_rest(team_id) if team_id else 1
                opp_rest = loader.get_days_rest(opp_id) if opp_id else 1
                
                # Track game for correlation detection
                game_key = tuple(sorted([team_abbrev.upper(), opp_team]))
                if game_key not in game_teams:
                    game_teams[game_key] = []
                game_teams[game_key].append(i)
                
                # Run projection
                proj_data = engineer.compute_composite_projection(
                    pid, opp_team, spread=spread,
                    home_game=True, days_rest=team_rest, opp_days_rest=opp_rest
                )
                
                if not proj_data or 'error' in proj_data:
                    results.append({'leg': i+1, 'player': player_name, 'error': proj_data.get('error', 'Projection failed')})
                    combined_prob = 0
                    continue
                
                # Simulate
                player_var_data = proj_data.get('player_variance')
                sim_res = simulator.simulate(proj_data, market_line=line, player_variance=player_var_data)
                probs = simulator.get_probabilities(sim_res, line)
                
                # Get directional probability
                if direction == 'OVER':
                    leg_prob = probs['over_probability']
                else:
                    leg_prob = probs['under_probability']
                
                combined_prob *= leg_prob
                
                results.append({
                    'leg': i+1,
                    'player': proj_data.get('player', player_name),
                    'opponent': opp_team,
                    'team': team_abbrev.upper(),
                    'projection': round(proj_data['projection'], 1),
                    'line': line,
                    'direction': direction,
                    'probability': round(leg_prob * 100, 1),
                    'over_prob': round(probs['over_probability'] * 100, 1),
                    'under_prob': round(probs['under_probability'] * 100, 1)
                })
                
            except Exception as leg_err:
                results.append({'leg': i+1, 'player': leg.get('player', '?'), 'error': str(leg_err)})
                combined_prob = 0
        
        # -------------------------------------------------------------------
        # Advanced Correlation Engine
        # -------------------------------------------------------------------
        # Rebounding is a zero-sum game. If Player A grabs a rebound, Player B cannot.
        # This causes strong negative correlation between overs, and positive correlation between over/under.
        
        correlation_penalty = 1.0
        correlated_games = []
        correlated_pairs = 0
        
        for game_key, leg_indices in game_teams.items():
            if len(leg_indices) > 1:
                correlated_games.append(f"{game_key[0]} vs {game_key[1]}")
                # Evaluate every pair in this game
                for idx1 in range(len(leg_indices)):
                    for idx2 in range(idx1 + 1, len(leg_indices)):
                        leg1 = results[leg_indices[idx1]]
                        leg2 = results[leg_indices[idx2]]
                        
                        # Guard against failed legs
                        if 'error' in leg1 or 'error' in leg2:
                            continue
                            
                        is_teammates = (leg1['team'] == leg2['team'])
                        dir1 = leg1['direction']
                        dir2 = leg2['direction']
                        
                        multiplier = 1.0
                        correlated_pairs += 1
                        if is_teammates:
                            # Teammate Rebounds
                            if dir1 == 'OVER' and dir2 == 'OVER':
                                multiplier = 0.85  # Strong Penalty (Zero-sum)
                            elif dir1 == 'UNDER' and dir2 == 'UNDER':
                                multiplier = 0.85  # Strong Penalty
                            elif (dir1 == 'OVER' and dir2 == 'UNDER') or (dir1 == 'UNDER' and dir2 == 'OVER'):
                                multiplier = 1.10  # Positive Correlation
                        else:
                            # Opponent Rebounds
                            if dir1 == 'OVER' and dir2 == 'OVER':
                                multiplier = 0.95  # Weak Penalty
                            elif dir1 == 'UNDER' and dir2 == 'UNDER':
                                multiplier = 0.95  # Weak Penalty
                            elif (dir1 == 'OVER' and dir2 == 'UNDER') or (dir1 == 'UNDER' and dir2 == 'OVER'):
                                multiplier = 1.02  # Weak Positive Correlation
                                
                        correlation_penalty *= multiplier
        
        adjusted_prob = min(combined_prob * correlation_penalty, 0.99)
        
        # Calculate parlay odds from adjusted probability
        if adjusted_prob > 0:
            if adjusted_prob >= 0.5:
                parlay_american = round(-100 * adjusted_prob / (1 - adjusted_prob))
            else:
                parlay_american = round(100 * (1 - adjusted_prob) / adjusted_prob)
            parlay_decimal = round(1 / adjusted_prob, 2)
        else:
            parlay_american = 0
            parlay_decimal = 0
        
        # EV Calculation (if user entered offered odds)
        ev_info = None
        if parlay_odds_input:
            offered_odds = int(parlay_odds_input)
            if offered_odds < 0:
                offered_implied = abs(offered_odds) / (abs(offered_odds) + 100)
                offered_decimal = 1 + (100 / abs(offered_odds))
            else:
                offered_implied = 100 / (offered_odds + 100)
                offered_decimal = 1 + (offered_odds / 100)
            
            ev_pct = (adjusted_prob - offered_implied) * 100
            ev_info = {
                'offered_odds': offered_odds,
                'offered_implied': round(offered_implied * 100, 1),
                'ev_pct': round(ev_pct, 1),
                'is_positive_ev': bool(ev_pct > 0),
                'offered_decimal': round(offered_decimal, 2)
            }
        
        return jsonify({
            'legs': results,
            'raw_probability': round(combined_prob * 100, 2),
            'combined_probability': round(adjusted_prob * 100, 2),
            'parlay_american_odds': parlay_american,
            'parlay_decimal_odds': parlay_decimal,
            'num_legs': len(legs),
            'correlation': {
                'correlated_pairs': correlated_pairs,
                'penalty_multiplier': round(correlation_penalty, 3),
                'correlated_games': list(set(correlated_games))
            },
            'ev': ev_info
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/games', methods=['GET'])
def games_for_date():
    """Return list of games for a given date so the UI can populate team dropdowns."""
    try:
        req_date = request.args.get('date')
        if not req_date:
            return jsonify({'error': 'Please provide a date parameter.'}), 400

        games = loader.get_games_for_date(req_date)
        if not games:
            return jsonify({'games': [], 'message': f'No games found for {req_date}.'}), 200

        id_to_code = {
            1610612737: 'ATL', 1610612738: 'BOS', 1610612751: 'BKN', 1610612766: 'CHA', 1610612741: 'CHI',
            1610612739: 'CLE', 1610612742: 'DAL', 1610612743: 'DEN', 1610612765: 'DET', 1610612744: 'GSW',
            1610612745: 'HOU', 1610612754: 'IND', 1610612746: 'LAC', 1610612747: 'LAL', 1610612763: 'MEM',
            1610612748: 'MIA', 1610612749: 'MIL', 1610612750: 'MIN', 1610612740: 'NOP', 1610612752: 'NYK',
            1610612760: 'OKC', 1610612753: 'ORL', 1610612755: 'PHI', 1610612756: 'PHX', 1610612757: 'POR',
            1610612758: 'SAC', 1610612759: 'SAS', 1610612761: 'TOR', 1610612762: 'UTA', 1610612764: 'WAS'
        }

        result = []
        for g in games:
            h_code = id_to_code.get(g['home_id'], 'UNK')
            a_code = id_to_code.get(g['away_id'], 'UNK')
            result.append({'home': h_code, 'away': a_code})

        return jsonify({'games': result, 'date': req_date})

    except Exception as e:
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

        # LAZY LOAD CACHE (For Render Free Tier)
        # Check if we need to rebuild the offline database before processing
        from src.cache_manager import is_cache_stale, fetch_and_cache_data
        if is_cache_stale():
            print("DEBUG: Offline JSON cache is missing or stale. Triggering rebuild...", flush=True)
            success = fetch_and_cache_data()
            if success:
                loader._load_offline_cache()
            else:
                print("DEBUG: Cache rebuild failed or timed out. Falling back to live API.", flush=True)

        # 1. Get Games for Date
        try:
            games = loader.get_games_for_date(req_date)
            if not games:
                return jsonify({'error': f"No games found for {req_date}. The NBA API might be blocking this IP or timing out."}), 404
        except Exception as e:
            if "timeout" in str(e).lower() or "read" in str(e).lower():
                return jsonify({'error': "NBA API Timeout: The server is likely blocking requests from this cloud IP address."}), 504
            return jsonify({'error': f"Failed to fetch games: {str(e)}"}), 500
            
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
            
            try:
                # Fetch Roster
                roster = loader.get_team_roster(tid)
                
                if roster.empty:
                    print(f"DEBUG: Skipping team {t_code}: roster unavailable", flush=True)
                    continue
                    
                # We need minutes played to filter rotation players. 
                # Fetching full league advanced stats is too heavy and often rate-limited.
                # Use the offline cache if available.
                league_base = loader._get_from_cache(f"league_player_stats_base_{loader.season}")
                if league_base is not None:
                    team_players_stats = league_base[league_base['TEAM_ID'] == tid]
                else:
                    team_players_stats = loader._retry_api_call(
                        loader.leaguedashplayerstats.LeagueDashPlayerStats,
                        season=loader.season,
                        team_id_nullable=tid
                    ).get_data_frames()[0]
                
                # Merge roster with basic stats to get MIN
                merged = pd.merge(roster, team_players_stats[['PLAYER_ID', 'MIN']], on='PLAYER_ID')
                
                # Filter out players who average less than 15 minutes to save API calls, then take top 5
                merged = merged[merged['MIN'] >= 15.0]
                merged = merged.sort_values('MIN', ascending=False).head(5) # Top 5 rotation
            except Exception as team_err:
                err_str = str(team_err).lower()
                if "timeout" in err_str or "read" in err_str:
                    return jsonify({'error': f"NBA API Timeout while fetching roster/stats for {t_code}. Cloud IPs are often blocked."}), 504
                print(f"DEBUG: Failed to fetch roster/stats for {t_code}: {team_err}", flush=True)
                continue

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
                        
                    # Get trend data from projection (already computed)
                    trend_data = proj.get('trend_data', [])
                        
                    # Check Odds
                    from unidecode import unidecode
                    norm_name = unidecode(pname).lower().replace('.', '').strip()
                    
                    line_info = odds_map.get(norm_name)
                    rec_tier = "Waiting for Line"
                    edge = 0
                    line_val = 0
                    over_prob = 0
                    under_prob = 0
                    confidence = 0
                    direction = "-"
                    
                    if line_info:
                        line_val = line_info['line']
                        odds_price = line_info.get('odds', -110)  # American odds
                        
                        # Run Simulation for EV
                        sim = simulator.simulate(proj, market_line=line_val)
                        probs = simulator.get_probabilities(sim, line_val)
                        
                        over_prob = round(probs['over_probability'] * 100, 1)
                        under_prob = round(probs['under_probability'] * 100, 1)
                        confidence = max(probs['over_probability'], probs['under_probability'])
                        direction = "OVER" if probs['over_probability'] > probs['under_probability'] else "UNDER"
                        
                        # Calculate edge using implied probability from actual odds
                        if odds_price < 0:
                            implied_prob = abs(odds_price) / (abs(odds_price) + 100)
                        else:
                            implied_prob = 100 / (odds_price + 100)
                        
                        edge = confidence - implied_prob
                        
                        # Tier logic
                        if edge <= 0:
                            rec_tier = "🛑 AVOID"
                        elif confidence > 0.635 and edge > 0.10: 
                            rec_tier = "🔥 STRONG PLAY"
                        elif confidence > 0.585 and edge > 0.05: 
                            rec_tier = "✅ PLAY"
                        elif direction == "OVER" and line_val < probs['ci_68'][0] and edge > 0: 
                            rec_tier = "🛡️ SAFE PLAY"
                        elif confidence > 0.555 and edge > 0: 
                            rec_tier = "👉 LEAN"
                        else: 
                            rec_tier = "🛑 AVOID"
                    else:
                        rec_tier = "-"
                    
                    # Build components for detail view
                    components = {
                        'Base Rebs': round(proj.get('base_rebounds', 0), 1),
                        'Pace Factor': round(proj.get('pace_factor', 1.0), 2),
                        'Opp Defense': round(proj.get('opp_factor', 1.0), 2),
                        'DvP Mult': round(proj.get('dvp_mult', 1.0), 2),
                        'Matchup Adj': round(proj.get('matchup_mult', 1.0), 2),
                        'Home/Away': round(proj.get('home_away_mult', 1.0), 2),
                        'Rest Factor': round(proj.get('rest_mult', 1.0), 2)
                    }
                        
                    results.append({
                        'player': pname,
                        'player_id': pid,
                        'team': t_code,
                        'opponent': opp_code,
                        'projection': round(proj['projection'], 1),
                        'line': line_val if line_info else '-',
                        'direction': direction,
                        'tier': rec_tier,
                        'edge_raw': edge,
                        'rest_note': f"{rest}d vs {opp_rest_val}d",
                        # Detail data
                        'components': components,
                        'trend': trend_data,
                        'over_prob': over_prob,
                        'under_prob': under_prob,
                        'confidence': round(confidence * 100, 1) if line_info else 0,
                        'injuries': proj.get('injuries', {}),
                        'summary': engineer.generate_pick_summary(proj, line_val) if line_info else f"{pname} projects for {round(proj['projection'], 1)} rebounds. No line available yet."
                    })
                    
                except Exception as e:
                    err_str = str(e).lower()
                    if "timeout" in err_str or "read" in err_str:
                         print(f"Skipping {pname} due to NBA API Timeout: {e}")
                    else:
                         print(f"Skipping {pname}: {e}")
                    continue

        # Sort by Edge (Descending) -> then Projection
        results.sort(key=lambda x: (x['tier'] == "🔥 STRONG PLAY", x['edge_raw'], x['projection']), reverse=True)
        
        if not results:
            return jsonify({'error': "No players processed successfully. The NBA API might be rate-limiting or blocking this server's IP address."}), 502
        
        return jsonify(results)

    except Exception as e:
        err_str = str(e).lower()
        if "timeout" in err_str or "read" in err_str or "max retries" in err_str:
            return jsonify({'error': "NBA API Connection Error: This cloud server IP (Render) is likely blocked by stats.nba.com."}), 504
        return jsonify({'error': str(e)}), 500



if __name__ == '__main__':
    app.run(debug=True, port=5001)
