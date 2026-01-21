import numpy as np
import pandas as pd
from src.data_loader import NBADataLoader
from src.features import FeatureEngineer
from src.model import ReboundSimulator
import time

class ModelEvaluator:
    def __init__(self, player_name="Nikola Jokic", limit_games=10):
        self.player_name = player_name
        self.limit = limit_games
        self.loader = NBADataLoader()
        self.engineer = FeatureEngineer(self.loader)
    
    def get_opponent_starter_center(self, game_id, opponent_team_id):
        """
        Heuristic to find the 'Matchup' for the backtest.
        We look for the 'C' in the starting lineup for the opponent.
        """
        try:
            from nba_api.stats.endpoints import boxscoretraditionalv3
            # Use V3
            box = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id)
            players = box.get_data_frames()[0]
            
            # Map V3 columns to V2 expected names
            if 'personId' in players.columns:
                players['PLAYER_ID'] = players['personId']
                players['TEAM_ID'] = players['teamId']
                players['START_POSITION'] = players['startPosition']
                players['PLAYER_NAME'] = players['firstName'] + " " + players['familyName'] # V3 doesn't have full name? 
                # Actually V3 has 'firstName', 'familyName'. 
                # Or maybe just use personId to get name later? 
                # Let's hope 'playerSlug' or something exists.
                # Actually, standard V3 sometimes has 'firstName' 'familyName'.
                pass
            
            # Filter for opponent starters
            # STARTER is usually indicated by 'START_POSITION' != '' (F, C, G)
            opp_starters = players[
                (players['TEAM_ID'] == opponent_team_id) & 
                (players['START_POSITION'].isin(['C', 'F'])) 
            ]
            
            # Prioritize 'C'
            centers = opp_starters[opp_starters['START_POSITION'] == 'C']
            if not centers.empty:
                # Name construction might be flaky, let's just use first row safely
                row = centers.iloc[0]
                if 'firstName' in row and 'familyName' in row:
                     return f"{row['firstName']} {row['familyName']}"
                return "Opponent Center"
            
            if not opp_starters.empty:
                row = opp_starters.iloc[0]
                if 'firstName' in row and 'familyName' in row:
                     return f"{row['firstName']} {row['familyName']}"
                return "Opponent Forward"
                
            return None
        except Exception as e:
            # print(f"Error fetching boxscore for {game_id}: {e}")
            return None

    def run_backtest(self):
        pid = self.loader.get_player_id(self.player_name)
        if not pid:
            print("Player not found")
            return []

        # Get logs
        logs = self.loader.get_player_gamelog(pid)
        # Sort by date descending is default, take last N
        games = logs.head(self.limit)
        
        results = []
        simulator = ReboundSimulator()
        
        print(f"Running bias audit on last {self.limit} games for {self.player_name}...")
        
        for idx, row in games.iterrows():
            game_id = row['Game_ID']
            matchup_str = row['MATCHUP'] 
            
            if 'vs.' in matchup_str:
                is_home = True
                opp_abbr = matchup_str.split(' vs. ')[1]
            else:
                is_home = False
                opp_abbr = matchup_str.split(' @ ')[1]
                
            actual_rebs = row['REB']
            days_rest = 1 
            
            # --- Generate Projection (New Logic) ---
            # Try to find matchup, else None
            opp_id = self.loader.get_team_id(opp_abbr)
            matchup_player = self.get_opponent_starter_center(game_id, opp_id)
            
            proj_data = self.engineer.compute_composite_projection(
                pid, 
                opp_abbr, 
                home_game=is_home, 
                days_rest=days_rest,
                matchup_player=matchup_player
            )
            
            if 'error' in proj_data: continue

            # --- Evaluate vs Actual ---
            mean_proj = proj_data['mean_projection']
            
            # Measure Bias: P(Sim > Actual)
            # If unbiased, this chance should be ~50% on average
            sim_res = simulator.simulate(proj_data)
            probs = simulator.get_probabilities(sim_res, actual_rebs - 0.5) # Over Actual-0.5 = At least Actual
            
            # Using samples to get percentile
            samples = sim_res['samples']
            # Percentile of Actual in distribution
            # = (Num samples <= Actual) / Total
            cdf_val = np.mean(samples <= actual_rebs)
            
            results.append({
                'date': row['GAME_DATE'],
                'opp': opp_abbr,
                'actual': actual_rebs,
                'proj': mean_proj,
                'error': mean_proj - actual_rebs,
                'cdf_of_actual': cdf_val,
                'matchup': matchup_player
            })
            
            print(f"  {row['GAME_DATE']} vs {opp_abbr}: Act {actual_rebs} | Proj {mean_proj:.1f} | Bias Check (CDF): {cdf_val:.2f}")
            time.sleep(0.5)

        return pd.DataFrame(results)

    def calculate_metrics(self, df):
        if df.empty: return {}
        
        mean_error = df['error'].mean()
        mae = df['error'].abs().mean()
        
        # Bias Metric: Average CDF
        # 0.50 = Perfect Balance
        # < 0.50 = Actuals are consistently LOW vs distribution (We are OVER predicting)
        # > 0.50 = Actuals are consistently HIGH vs distribution (We are UNDER predicting)
        avg_cdf = df['cdf_of_actual'].mean()
        
        bias_status = "Balanced"
        if avg_cdf > 0.60: bias_status = "UNDER BIASED (Actuals > Proj)"
        elif avg_cdf < 0.40: bias_status = "OVER BIASED (Actuals < Proj)"
        
        return {
            'mean_error': mean_error,
            'mae': mae,
            'avg_cdf': avg_cdf,
            'bias_status': bias_status
        }

if __name__ == "__main__":
    # Test on a single reliable star for speed
    players = ["Nikola Jokic"] # Just one needed for verify
    
    print("\n=== BIAS AUDIT (NEW MODEL) ===")
    
    for p in players:
        evaluator = ModelEvaluator(player_name=p, limit_games=6) # 6 games
        df = evaluator.run_backtest()
        if not df.empty:
            m = evaluator.calculate_metrics(df)
            print(f"\n--- {p} Results ---")
            print(f"Mean Error: {m['mean_error']:.2f}")
            print(f"Bias Metric (CDF): {m['avg_cdf']:.2f} (Target: 0.50)")
            print(f"Status: {m['bias_status']}")
            print("-" * 30)

