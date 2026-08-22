import os
import sys
import argparse
import pandas as pd
from datetime import datetime

# Add parent directory to path to allow importing src modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ledger import PredictionLedger
from src.data_loader import NBADataLoader
from src.utils import get_logger

log = get_logger('grade')

def grade_predictions(date_str=None):
    """Fetch pending predictions and grade them against actual box scores."""
    ledger = PredictionLedger()
    loader = NBADataLoader()
    
    pending = ledger.get_pending_predictions(date_str)
    if not pending:
        log.info(f"No pending predictions to grade{f' for {date_str}' if date_str else ''}.")
        return

    # Group pending predictions by date to minimize API calls
    dates = set(p['game_date'] for p in pending)
    
    for d in dates:
        log.info(f"Grading predictions for {d}...")
        games = loader.get_games_for_date(d)
        if not games:
            log.warning(f"No games found for {d}, skipping...")
            continue
            
        # We need actual player box scores for these games.
        # It's more efficient to just fetch the gamelogs for the players we need to grade.
        players_to_grade = [p for p in pending if p['game_date'] == d]
        
        for p in players_to_grade:
            player_name = p['player']
            pid = loader.get_player_id(player_name)
            if not pid:
                log.warning(f"Could not find ID for {player_name}")
                continue
                
            logs = loader.get_player_gamelog(pid)
            if logs.empty:
                continue
                
            # Find the game matching the date
            # Dates in gamelog are like 'MMM DD, YYYY'
            try:
                target_date = datetime.strptime(d, "%Y-%m-%d")
                target_date_str = target_date.strftime("%b %d, %Y").replace(" 0", " ")
                
                # Check for match (case insensitive, some APIs use 0 padding for days)
                game_row = None
                for _, row in logs.iterrows():
                    log_date = datetime.strptime(row['GAME_DATE'], "%b %d, %Y")
                    if log_date.date() == target_date.date():
                        game_row = row
                        break
                        
                if game_row is not None:
                    actual_rebounds = int(game_row['REB'])
                    ledger.grade_prediction(p['id'], actual_rebounds)
                    log.info(f"Graded {player_name} (Line: {p['line']}, Actual: {actual_rebounds}) -> {p['result']}")
                else:
                    log.debug(f"No gamelog entry found for {player_name} on {d}. Did they play?")
            except Exception as e:
                log.warning(f"Failed to grade {player_name} on {d}: {e}")

def print_summary():
    ledger = PredictionLedger()
    summary = ledger.get_performance_summary()
    
    if not summary:
        print("No graded predictions available yet.")
        return
        
    print("\n" + "="*60)
    print(" PREDICTION LEDGER PERFORMANCE SUMMARY")
    print("="*60)
    print(f"{'Tier':<15} | {'Bets':<5} | {'W-L-P':<10} | {'Win %':<7} | {'Units':<7} | {'Brier':<7}")
    print("-" * 60)
    
    total_bets = total_wins = total_losses = total_pushes = 0
    total_pnl = 0.0
    
    for row in summary:
        tier = row['tier']
        bets = row['total_bets']
        w = row['wins']
        l = row['losses']
        p = row['pushes']
        pnl = row['total_pnl']
        brier = row['avg_brier']
        
        win_pct = (w / (w + l)) * 100 if (w + l) > 0 else 0
        
        total_bets += bets
        total_wins += w
        total_losses += l
        total_pushes += p
        total_pnl += pnl
        
        print(f"{tier:<15} | {bets:<5} | {w}-{l}-{p:<6} | {win_pct:>5.1f}% | {pnl:>+6.2f}u | {brier:.3f}")
        
    print("-" * 60)
    overall_win_pct = (total_wins / (total_wins + total_losses)) * 100 if (total_wins + total_losses) > 0 else 0
    print(f"{'TOTAL':<15} | {total_bets:<5} | {total_wins}-{total_losses}-{total_pushes:<6} | {overall_win_pct:>5.1f}% | {total_pnl:>+6.2f}u")
    print("="*60 + "\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Grade predictions against actual box scores.")
    parser.add_argument('--date', type=str, help="Specific date to grade (YYYY-MM-DD)")
    parser.add_argument('--summary-only', action='store_true', help="Only print the summary, don't grade")
    args = parser.parse_args()
    
    if not args.summary_only:
        grade_predictions(args.date)
        
    print_summary()
