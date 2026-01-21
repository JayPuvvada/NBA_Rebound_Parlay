import argparse
import sys
from src.data_loader import NBADataLoader
from src.features import FeatureEngineer
from src.model import ReboundSimulator

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="NBA Player Rebound Projection Model")
    parser.add_argument('player', type=str, help="Full player name (e.g. 'Nikola Jokic')")
    parser.add_argument('opponent', type=str, help="Opponent Team Abbreviation (e.g. 'BOS')")
    parser.add_argument('--spread', type=float, default=0.0, help="Point Spread (e.g. -14.5). Used for blowout adjustment.")
    parser.add_argument('--line', type=float, default=None, help="Sportsbook Over/Under line")
    parser.add_argument('--minutes', type=float, default=None, help="Manual minutes projection override")
    parser.add_argument('--matchup', type=str, default=None, help="Manual matchup player override (e.g. 'Anthony Davis')")
    parser.add_argument('--verbose', action='store_true', help="Show detailed feature contributions and simulation stats")
    
    args = parser.parse_args()
    
    player_name = args.player
    opp_team = args.opponent.upper()
    
    if args.verbose:
        sys.stdout.reconfigure(encoding='utf-8')
        print(f"\n--- NBA Rebound Projection (Verbose) ---")
        print(f"Player: {player_name}")
        print(f"Opponent: {opp_team}")
        print(f"Spread: {args.spread}")
    
    # 1. Initialize
    loader = NBADataLoader()
    engineer = FeatureEngineer(loader)
    simulator = ReboundSimulator()
    
    # 2. Get Player ID
    pid = loader.get_player_id(player_name)
    if not pid:
        print(f"Player '{player_name}' not found.")
        sys.exit(1)
        
    if args.verbose: print(f"Found Player ID: {pid}")
    
    # 3. Compute Features
    if args.verbose: print("Fetching data and computing features...")
    try:
        # Using COMPLEX projection with Home/Away, Fatigue, and Matchup Player logic
        proj_data = engineer.compute_composite_projection(
            pid, 
            opp_team, 
            spread=args.spread,
            manual_minutes=args.minutes,
            home_game=True,    # Default to Home for now
            days_rest=1,      # Default to rested
            matchup_player=args.matchup
        )
    except Exception as e:
        print(f"Error computing projection: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    if not proj_data or 'error' in proj_data:
        print(f"Failed to generate projection: {proj_data.get('error') if proj_data else 'Unknown error'}")
        sys.exit(1)
        
    mean_proj = proj_data['projection']
    
    # 4. Simulation
    if args.verbose: print(f"Running {simulator.num_simulations} Simulations...")
    
    # Pass market line for anchoring if provided
    sim_res = simulator.simulate(proj_data, market_line=args.line)
    
    # --- OUTPUT SECTION ---
    
    # Header
    print(f"\n🏀 {player_name} vs {opp_team} 🏀")
    print(f"🎯 PROJECTION: {mean_proj:.1f} Rebs (Model Base)")
    if args.line:
        print(f"⚖️  ANCHORED MEAN: {sim_res['params']['final_mean']:.2f} (Blended with Line {args.line})")
        
    print(f"🏟️ Context: {proj_data.get('matchup_context', 'Neutral')}")
    
    # INJURY REPORT
    if proj_data.get('matchup_injury'):
         print(f"🏥 MATCHUP INJURY: {proj_data.get('matchup_injury')} (Check active status!)")
    if proj_data.get('team_injury'):
         print(f"🚑 TEAM INJURY: {proj_data.get('team_injury')} (Adjusted projection!)")
    
    # Display New Modifiers
    if args.verbose:
        print("\n--- Model Factors ---")
        mods = proj_data.get('modifiers', {})
        comps = proj_data.get('components', {})
        
        # New Feature Keys
        if 'Env Mult (Final)' in comps:
             print(f"Base Rebs: {comps.get('Base Rebs')}")
             print(f"Minutes: {comps.get('Proj Minutes')} (Base: {comps.get('Base Minutes')})")
             print(f"Env Multiplier: {comps.get('Env Mult (Final)')} (Raw: {comps.get('Raw Mult')})")
             print(f"  - Pace: {comps.get('Pace')}")
             print(f"  - Miss Opp: {comps.get('Opp')}")
             print(f"  - DvP: {comps.get('DvP')}")
             print(f"  - Matchup: {comps.get('Matchup')}")
        else:
             # Fallback for old keys if any
             print(f"Components: {comps}")

    # Line Analysis
    if args.line is not None:
        probs = simulator.get_probabilities(sim_res, args.line)
        
        over_prob = probs['over_probability']
        under_prob = probs['under_probability']
        
        # BREAK EVEN LOGIC
        # Standard -115 line implies ~53.5%. We use 54% as safe threshold.
        break_even_prob = 0.535 
        
        print(f"\n📊 Line: {args.line}")
        print(f"   Over:  {over_prob:.1%} ")
        print(f"   Under: {under_prob:.1%} ")
        
        confidence = max(over_prob, under_prob)
        direction = "OVER" if over_prob > under_prob else "UNDER"
        edge = confidence - break_even_prob
        
        # New Tiered Logic
        # > 53.5%: Positive EV (Technically a bet)
        # > 57.0%: Clear Edge (>3.5%)
        # > 62.0%: Strong Edge (>8.5%)
        
        if confidence < break_even_prob:
             # Losing bet (vig eats edge) - rare if we picked max, but possible if push prob is high
             print(f"\n🛑 RECOMMENDATION: AVOID (Negative EV)")
        elif confidence < 0.555:
             # Very small edge (< 2%)
             print(f"\n🛑 RECOMMENDATION: AVOID (Edge {edge*100:.1f}% is too thin, lean {direction})")
        elif confidence < 0.585:
             # Solid lean (2% - 5% edge)
             print(f"\n👉 RECOMMENDATION: LEAN {direction} {args.line} (Confidence: {confidence:.1%}, Edge: {edge*100:.1f}%)")
        elif confidence < 0.64:
             # Playable (5% - 10% edge)
             print(f"\n✅ RECOMMENDATION: PLAY {direction} {args.line} (Confidence: {confidence:.1%}, Edge: {edge*100:.1f}%)")
        else:
             # Strong (> 10% edge)
             print(f"\n🔥 RECOMMENDATION: STRONG PLAY {direction} {args.line} (Confidence: {confidence:.1%}, Edge: {edge*100:.1f}%)")



    else:
        # No line, just distribution
        probs = simulator.get_probabilities(sim_res, mean_proj)
        print(f"\nLikely Range (68%): {probs['ci_68'][0]:.1f} - {probs['ci_68'][1]:.1f}")
        
    # Verbose details
    # Verbose details
    if args.verbose:
        print(f"\n--- Detailed Stats ---")
        print(f"Mean Projection: {mean_proj:.2f}")
        print(f"Simulated Mean: {sim_res['mean_sim']:.2f} +/- {sim_res['std_sim']:.2f}")
        # Variance factor no longer returned explicitly in new API, default to 1.0 if missing
        if 'variance_factor' in proj_data:
             print(f"Variance Adjustment: {proj_data['variance_factor']:.2f}")
        
        print("\n--- Feature Contributions (Weighted Units) ---")
        # Support both old 'explanation' and new 'components' keys
        explanations = proj_data.get('explanation', proj_data.get('components', {}))
        
        # Sort so Base comes first, then Modifiers
        sorted_comps = sorted(explanations.items(), key=lambda x: x[0]) 
        
        for k, v in sorted_comps:
            if isinstance(v, (int, float)):
                print(f"  {k}: {v:.2f}")
            else:
                print(f"  {k}: {v}")
        
        print(f"\nConfidence Intervals:")
        print(f"  68%: {probs['ci_68']}")
        print(f"  95%: {probs['ci_95']}")
    
    # 5. Final Summary
    summary = engineer.generate_pick_summary(proj_data, args.line)
    print(f"💡 PICK SUMMARY")
    print(f"   {summary}")
    print("\n")

if __name__ == "__main__":
    main()
