"""Versioned, append-only prediction ledger with explicit settlement updates."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any

from src.recommendation import is_actionable_tier
from src.utils import (
    ev_roi as calculate_ev_roi,
    get_logger,
    implied_prob_from_american,
    kelly_criterion,
)


log = get_logger("ledger")

LATEST_SCHEMA_VERSION = 2
DEFAULT_MODEL_VERSION = "rebound-nb-v2"
FINAL_RESULTS = {"WIN", "LOSS", "PUSH", "VOID"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value):
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, default=_json_default, sort_keys=True, separators=(",", ":"), allow_nan=False)


_VOLATILE_SNAPSHOT_KEYS = {
    "created_at",
    "fetched_at",
    "freshly_verified_at",
    "generated_at",
    "injuries_updated_at",
    "odds_updated_at",
    "stats_updated_at",
}


def _identity_snapshot(value: Any) -> Any:
    """Remove observation timestamps that do not change a prediction's inputs.

    The full snapshot is still persisted for auditability.  Ignoring only these
    volatile provenance fields in the idempotency hash prevents a browser retry
    from creating another wager when the model inputs, side, line, and price are
    otherwise identical.
    """
    if isinstance(value, dict):
        return {
            key: _identity_snapshot(item)
            for key, item in value.items()
            if key not in _VOLATILE_SNAPSHOT_KEYS
        }
    if isinstance(value, list):
        return [_identity_snapshot(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_identity_snapshot(item) for item in value)
    return value


class PredictionLedger:
    def __init__(self, db_path="data/predictions.db"):
        self.db_path = os.fspath(db_path)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _columns(conn):
        return {row[1] for row in conn.execute("PRAGMA table_info(predictions)")}

    @staticmethod
    def _create_latest_table(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_key TEXT NOT NULL UNIQUE,
                schema_version INTEGER NOT NULL DEFAULT 2,
                model_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                timestamp TEXT,
                game_date TEXT NOT NULL,
                player TEXT NOT NULL,
                team TEXT,
                opponent TEXT,
                is_home INTEGER,
                projection REAL NOT NULL,
                line REAL NOT NULL,
                american_odds REAL NOT NULL,
                bookmaker TEXT,
                odds_side TEXT NOT NULL,
                direction TEXT NOT NULL,
                tier TEXT NOT NULL,
                confidence REAL NOT NULL,
                over_prob REAL NOT NULL,
                under_prob REAL NOT NULL,
                push_prob REAL NOT NULL DEFAULT 0,
                implied_prob REAL,
                edge REAL,
                ev_roi REAL NOT NULL,
                kelly_fraction REAL,
                input_snapshot TEXT NOT NULL DEFAULT '{}',
                actual_rebounds INTEGER,
                result TEXT NOT NULL DEFAULT 'PENDING',
                brier_score REAL,
                pnl_units REAL,
                graded_at TEXT,
                void_reason TEXT
            )
            """
        )

    def _migrate_legacy_table(self, conn):
        columns = self._columns(conn)
        additions = {
            "prediction_key": "TEXT",
            "schema_version": "INTEGER DEFAULT 1",
            "model_version": "TEXT DEFAULT 'legacy-v1'",
            "created_at": "TEXT",
            "bookmaker": "TEXT",
            "odds_side": "TEXT",
            "push_prob": "REAL DEFAULT 0",
            "implied_prob": "REAL",
            "edge": "REAL",
            "kelly_fraction": "REAL",
            "input_snapshot": "TEXT DEFAULT '{}'",
            "graded_at": "TEXT",
            "void_reason": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f'ALTER TABLE predictions ADD COLUMN "{name}" {definition}')

        conn.execute("DROP INDEX IF EXISTS idx_player_date_line")
        conn.execute("UPDATE predictions SET prediction_key = 'legacy-' || id WHERE prediction_key IS NULL")
        conn.execute("UPDATE predictions SET schema_version = 1 WHERE schema_version IS NULL")
        conn.execute("UPDATE predictions SET model_version = 'legacy-v1' WHERE model_version IS NULL")
        conn.execute("UPDATE predictions SET created_at = COALESCE(timestamp, ?) WHERE created_at IS NULL", (_utc_now(),))
        conn.execute("UPDATE predictions SET timestamp = created_at WHERE timestamp IS NULL")
        conn.execute("UPDATE predictions SET odds_side = direction WHERE odds_side IS NULL")
        conn.execute("UPDATE predictions SET push_prob = 0 WHERE push_prob IS NULL")
        conn.execute("UPDATE predictions SET input_snapshot = '{}' WHERE input_snapshot IS NULL")
        conn.execute("UPDATE predictions SET result = 'PENDING' WHERE result IS NULL")

    def _init_db(self):
        directory = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(directory, exist_ok=True)
        with self._connection() as conn:
            # Serialize schema inspection/migration across threads and Gunicorn
            # workers so two first-time ledger writes cannot race ALTER TABLE.
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            self._create_latest_table(conn)
            self._migrate_legacy_table(conn)
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_predictions_key ON predictions (prediction_key)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_predictions_pending_date ON predictions (result, game_date)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (LATEST_SCHEMA_VERSION, _utc_now()),
            )
            conn.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION}")

    @staticmethod
    def _finite(value, name, *, minimum=None, maximum=None):
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a finite number")
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{name} must be a finite number") from exc
        if not math.isfinite(result):
            raise ValueError(f"{name} must be a finite number")
        if minimum is not None and result < minimum:
            raise ValueError(f"{name} must be at least {minimum}")
        if maximum is not None and result > maximum:
            raise ValueError(f"{name} must be at most {maximum}")
        return result

    @staticmethod
    def _validate_game_date(value):
        try:
            return date.fromisoformat(str(value)).isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError("game_date must be YYYY-MM-DD") from exc

    def record_prediction(
        self,
        game_date,
        player,
        team,
        opponent,
        is_home,
        projection,
        line,
        american_odds,
        direction,
        tier,
        confidence,
        over_prob,
        under_prob,
        ev_roi,
        *,
        push_prob=0.0,
        bookmaker=None,
        odds_side=None,
        implied_prob=None,
        edge=None,
        kelly_fraction=None,
        input_snapshot=None,
        model_version=DEFAULT_MODEL_VERSION,
        created_at=None,
    ):
        """Append an issued pick, or return the identical existing row's id.

        Prediction fields are never updated. A materially changed model output,
        price, book, side, version, or input snapshot creates a new record. An
        identical refresh is idempotent—even after the original has been graded.
        """
        if not is_actionable_tier(tier):
            return None
        game_date = self._validate_game_date(game_date)
        player = str(player or "").strip()
        if not player:
            raise ValueError("player is required")
        direction = str(direction or "").upper()
        if direction not in ("OVER", "UNDER"):
            raise ValueError("direction must be OVER or UNDER")
        odds_side = str(odds_side or direction).upper()
        if odds_side not in ("OVER", "UNDER"):
            raise ValueError("odds_side must be OVER or UNDER")
        if odds_side != direction:
            raise ValueError("odds_side must match the recommended direction")

        projection = self._finite(projection, "projection", minimum=0)
        line = self._finite(line, "line", minimum=0)
        odds = self._finite(american_odds, "american_odds")
        implied_prob_from_american(odds)
        confidence = self._finite(confidence, "confidence", minimum=0, maximum=1)
        over_prob = self._finite(over_prob, "over_prob", minimum=0, maximum=1)
        under_prob = self._finite(under_prob, "under_prob", minimum=0, maximum=1)
        push_prob = self._finite(push_prob, "push_prob", minimum=0, maximum=1)
        if abs((over_prob + under_prob + push_prob) - 1.0) > 1e-6:
            raise ValueError("over, under, and push probabilities must sum to 1")
        target_probability = over_prob if direction == "OVER" else under_prob
        if abs(confidence - target_probability) > 1e-6:
            raise ValueError("confidence must match the recommended side probability")

        calculated_implied = implied_prob_from_american(odds)
        calculated_edge = confidence - calculated_implied * (1.0 - push_prob)
        calculated_ev = calculate_ev_roi(confidence, odds, push_prob)
        calculated_kelly = kelly_criterion(confidence, odds, push_prob)

        # Refuse internally inconsistent records instead of silently persisting
        # the former bug where probability edge was written into the EV column.
        supplied_metrics = {
            "ev_roi": (ev_roi, calculated_ev),
            "implied_prob": (implied_prob, calculated_implied),
            "edge": (edge, calculated_edge),
            "kelly_fraction": (kelly_fraction, calculated_kelly),
        }
        for name, (supplied, calculated) in supplied_metrics.items():
            if supplied is None:
                continue
            supplied_value = self._finite(
                supplied,
                name,
                minimum=0 if name in ("implied_prob", "kelly_fraction") else None,
                maximum=1 if name in ("implied_prob", "kelly_fraction") else None,
            )
            if abs(supplied_value - calculated) > 1e-5:
                raise ValueError(f"{name} does not match probabilities and American odds")

        implied_value = calculated_implied
        edge_value = calculated_edge
        ev_value = calculated_ev
        kelly_value = calculated_kelly
        model_version = str(model_version or "").strip()
        if not model_version:
            raise ValueError("model_version is required")

        immutable_fields = {
            "schema_version": LATEST_SCHEMA_VERSION,
            "model_version": model_version,
            "game_date": game_date,
            "player": player,
            "team": team,
            "opponent": opponent,
            "is_home": None if is_home is None else bool(is_home),
            "projection": projection,
            "line": line,
            "american_odds": odds,
            "bookmaker": bookmaker,
            "odds_side": odds_side,
            "direction": direction,
            "tier": tier,
            "confidence": confidence,
            "over_prob": over_prob,
            "under_prob": under_prob,
            "push_prob": push_prob,
            "implied_prob": implied_value,
            "edge": edge_value,
            "ev_roi": ev_value,
            "kelly_fraction": kelly_value,
            "input_snapshot": input_snapshot or {},
        }
        snapshot_json = _canonical_json(input_snapshot or immutable_fields)
        key_material = dict(immutable_fields)
        key_material["input_snapshot"] = _identity_snapshot(json.loads(snapshot_json))
        prediction_key = hashlib.sha256(_canonical_json(key_material).encode("utf-8")).hexdigest()
        timestamp = created_at or _utc_now()

        values = (
            prediction_key,
            LATEST_SCHEMA_VERSION,
            model_version,
            timestamp,
            timestamp,
            game_date,
            player,
            team,
            opponent,
            None if is_home is None else int(bool(is_home)),
            projection,
            line,
            odds,
            bookmaker,
            odds_side,
            direction,
            tier,
            confidence,
            over_prob,
            under_prob,
            push_prob,
            implied_value,
            edge_value,
            ev_value,
            kelly_value,
            snapshot_json,
        )
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO predictions (
                    prediction_key, schema_version, model_version, created_at, timestamp,
                    game_date, player, team, opponent, is_home, projection, line,
                    american_odds, bookmaker, odds_side, direction, tier, confidence,
                    over_prob, under_prob, push_prob, implied_prob, edge, ev_roi,
                    kelly_fraction, input_snapshot, result
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, 'PENDING'
                )
                """,
                values,
            )
            if cursor.rowcount:
                return cursor.lastrowid
            row = conn.execute(
                "SELECT id FROM predictions WHERE prediction_key = ?", (prediction_key,)
            ).fetchone()
            return row[0] if row else None

    @staticmethod
    def _row_dict(row):
        result = dict(row)
        snapshot = result.get("input_snapshot")
        if isinstance(snapshot, str):
            try:
                result["input_snapshot"] = json.loads(snapshot)
            except json.JSONDecodeError:
                pass
        return result

    def get_prediction(self, pred_id):
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM predictions WHERE id = ?", (pred_id,)).fetchone()
            return self._row_dict(row) if row else None

    def get_pending_predictions(self, date_str=None):
        """Fetch PENDING predictions, optionally filtered by ISO game date."""
        query = "SELECT * FROM predictions WHERE result = 'PENDING'"
        params = []
        if date_str:
            query += " AND game_date = ?"
            params.append(self._validate_game_date(date_str))
        query += " ORDER BY game_date, created_at, id"
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            return [self._row_dict(row) for row in conn.execute(query, params)]

    def grade_prediction(self, pred_id, actual_rebounds, *, void_reason=None):
        """Settle a pending pick once; final records cannot be overwritten."""
        if actual_rebounds is None:
            if not void_reason:
                raise ValueError("void_reason is required when actual_rebounds is None")
            return self.void_prediction(pred_id, void_reason)
        if isinstance(actual_rebounds, bool):
            raise ValueError("actual_rebounds must be a non-negative integer")
        try:
            actual = int(actual_rebounds)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("actual_rebounds must be a non-negative integer") from exc
        if actual != actual_rebounds or actual < 0:
            raise ValueError("actual_rebounds must be a non-negative integer")

        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM predictions WHERE id = ?", (pred_id,)).fetchone()
            if not row:
                return None
            if row["result"] != "PENDING":
                return row["result"]

            line = float(row["line"])
            direction = row["direction"]
            odds = float(row["american_odds"])
            target_prob = row["over_prob"] if direction == "OVER" else row["under_prob"]
            if actual > line:
                outcome = "WIN" if direction == "OVER" else "LOSS"
            elif actual < line:
                outcome = "WIN" if direction == "UNDER" else "LOSS"
            else:
                outcome = "PUSH"

            brier_score = None
            if outcome in ("WIN", "LOSS") and target_prob is not None:
                # Pushes are excluded from the binary scoring sample, so score
                # the corresponding conditional win probability.  Using the
                # unconditional side probability here would systematically make
                # every pushed market look under-confident.
                settled_probability = 1.0 - float(row["push_prob"] or 0.0)
                if settled_probability > 0:
                    conditional_win_probability = min(
                        1.0,
                        max(0.0, float(target_prob) / settled_probability),
                    )
                    brier_score = (
                        conditional_win_probability
                        - (1.0 if outcome == "WIN" else 0.0)
                    ) ** 2
            pnl = 0.0
            if outcome == "WIN":
                pnl = 100.0 / abs(odds) if odds < 0 else odds / 100.0
            elif outcome == "LOSS":
                pnl = -1.0

            conn.execute(
                """
                UPDATE predictions
                SET actual_rebounds = ?, result = ?, brier_score = ?, pnl_units = ?,
                    graded_at = ?, void_reason = NULL
                WHERE id = ? AND result = 'PENDING'
                """,
                (actual, outcome, brier_score, pnl, _utc_now(), pred_id),
            )
            return outcome

    def void_prediction(self, pred_id, reason):
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("a void reason is required")
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE predictions
                SET result = 'VOID', actual_rebounds = NULL, brier_score = NULL,
                    pnl_units = 0.0, graded_at = ?, void_reason = ?
                WHERE id = ? AND result = 'PENDING'
                """,
                (_utc_now(), reason, pred_id),
            )
            if cursor.rowcount:
                return "VOID"
            row = conn.execute("SELECT result FROM predictions WHERE id = ?", (pred_id,)).fetchone()
            return row[0] if row else None

    def get_performance_summary(self):
        """Aggregate settled betting and calibration performance by tier."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    tier,
                    SUM(CASE WHEN result IN ('WIN', 'LOSS', 'PUSH') THEN 1 ELSE 0 END) AS total_bets,
                    SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN result = 'PUSH' THEN 1 ELSE 0 END) AS pushes,
                    SUM(CASE WHEN result = 'VOID' THEN 1 ELSE 0 END) AS voids,
                    COALESCE(SUM(CASE WHEN result IN ('WIN', 'LOSS', 'PUSH') THEN pnl_units ELSE 0 END), 0) AS total_pnl,
                    AVG(CASE WHEN result IN ('WIN', 'LOSS') THEN brier_score END) AS avg_brier,
                    CASE
                        WHEN SUM(CASE WHEN result IN ('WIN', 'LOSS', 'PUSH') THEN 1 ELSE 0 END) > 0
                        THEN COALESCE(SUM(CASE WHEN result IN ('WIN', 'LOSS', 'PUSH') THEN pnl_units ELSE 0 END), 0)
                             / SUM(CASE WHEN result IN ('WIN', 'LOSS', 'PUSH') THEN 1 ELSE 0 END)
                        ELSE NULL
                    END AS realized_roi
                FROM predictions
                WHERE result IN ('WIN', 'LOSS', 'PUSH', 'VOID')
                GROUP BY tier
                ORDER BY total_pnl DESC, total_bets DESC
                """
            )
            return [dict(row) for row in rows]
