import sqlite3
import os
from datetime import datetime
from src.utils import get_logger

log = get_logger('ledger')

class PredictionLedger:
    def __init__(self, db_path='data/predictions.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    game_date TEXT,
                    player TEXT,
                    team TEXT,
                    opponent TEXT,
                    is_home BOOLEAN,
                    projection REAL,
                    line REAL,
                    american_odds INTEGER,
                    direction TEXT,
                    tier TEXT,
                    confidence REAL,
                    over_prob REAL,
                    under_prob REAL,
                    ev_roi REAL,
                    actual_rebounds INTEGER,
                    result TEXT,
                    brier_score REAL,
                    pnl_units REAL
                )
            ''')
            # Create a unique index to prevent duplicate records for the same player, date, and line
            conn.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_player_date_line 
                ON predictions (player, game_date, line)
            ''')

    def record_prediction(self, game_date, player, team, opponent, is_home, 
                          projection, line, american_odds, direction, tier, 
                          confidence, over_prob, under_prob, ev_roi):
        """
        Record a new prediction. Updates existing prediction if the line is the same.
        """
        if tier in ('AVOID', 'LOW_VOLUME', '-'):
            return # Don't record non-actionable predictions

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO predictions (
                        timestamp, game_date, player, team, opponent, is_home,
                        projection, line, american_odds, direction, tier, 
                        confidence, over_prob, under_prob, ev_roi, result
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
                    ON CONFLICT(player, game_date, line) DO UPDATE SET
                        timestamp=excluded.timestamp,
                        projection=excluded.projection,
                        american_odds=excluded.american_odds,
                        direction=excluded.direction,
                        tier=excluded.tier,
                        confidence=excluded.confidence,
                        over_prob=excluded.over_prob,
                        under_prob=excluded.under_prob,
                        ev_roi=excluded.ev_roi,
                        result='PENDING'
                ''', (
                    datetime.now().isoformat(), game_date, player, team, opponent, 
                    is_home, projection, line, american_odds, direction, tier, 
                    confidence, over_prob, under_prob, ev_roi
                ))
        except Exception as e:
            log.error(f"Failed to record prediction for {player}: {e}")

    def get_pending_predictions(self, date_str=None):
        """Fetch all PENDING predictions, optionally filtered by date."""
        query = "SELECT * FROM predictions WHERE result = 'PENDING'"
        params = []
        if date_str:
            query += " AND game_date = ?"
            params.append(date_str)
            
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, params)]

    def grade_prediction(self, pred_id, actual_rebounds):
        """Grade a prediction based on actual rebounds and update the ledger."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM predictions WHERE id = ?", (pred_id,)).fetchone()
            if not row:
                return

            line = row['line']
            direction = row['direction']
            american_odds = row['american_odds'] or -110
            prob_target = row['over_prob'] if direction == 'OVER' else row['under_prob']

            if actual_rebounds > line:
                outcome = 'WIN' if direction == 'OVER' else 'LOSS'
            elif actual_rebounds < line:
                outcome = 'WIN' if direction == 'UNDER' else 'LOSS'
            else:
                outcome = 'PUSH'

            # Brier Score = (predicted_prob - actual_outcome)^2
            actual_binary = 1.0 if outcome == 'WIN' else 0.0
            if outcome == 'PUSH':
                actual_binary = 0.5 # or skip Brier scoring for pushes
            brier_score = (prob_target - actual_binary) ** 2

            # PnL (units)
            pnl = 0.0
            if outcome == 'WIN':
                if american_odds < 0:
                    pnl = 100.0 / abs(american_odds)
                else:
                    pnl = american_odds / 100.0
            elif outcome == 'LOSS':
                pnl = -1.0

            conn.execute('''
                UPDATE predictions 
                SET actual_rebounds = ?, result = ?, brier_score = ?, pnl_units = ?
                WHERE id = ?
            ''', (actual_rebounds, outcome, brier_score, pnl, pred_id))

    def get_performance_summary(self):
        """Aggregate ROI, hit rate, and Brier score by tier."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('''
                SELECT 
                    tier,
                    COUNT(*) as total_bets,
                    SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    SUM(CASE WHEN result = 'PUSH' THEN 1 ELSE 0 END) as pushes,
                    SUM(pnl_units) as total_pnl,
                    AVG(brier_score) as avg_brier
                FROM predictions
                WHERE result IN ('WIN', 'LOSS', 'PUSH')
                GROUP BY tier
                ORDER BY total_pnl DESC
            ''')
            return [dict(row) for row in rows]
