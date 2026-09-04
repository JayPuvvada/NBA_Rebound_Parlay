"""Settle issued predictions against player game logs."""

from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import date, datetime

# Allow direct execution with ``python scripts/grade.py``.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_loader import NBADataLoader
from src.ledger import PredictionLedger
from src.utils import current_season, eastern_today, get_logger


log = get_logger("grade")


def _parse_log_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _loader_for_season(loader_factory, season):
    try:
        return loader_factory(season=season)
    except TypeError:
        # Small fake loaders and older implementations may not accept a season.
        return loader_factory()


def grade_predictions(
    date_str=None,
    *,
    ledger=None,
    loader=None,
    loader_factory=NBADataLoader,
    allow_today=False,
):
    """Grade pending predictions, selecting the correct loader season per date.

    Missing game-log rows remain pending because they are ambiguous (DNP, delay,
    postponed game, or API failure). Use ``void_prediction`` or the CLI's
    ``--void`` option only after confirming the sportsbook settlement.
    """
    ledger = ledger or PredictionLedger()
    pending = ledger.get_pending_predictions(date_str)
    stats = {"graded": 0, "voided": 0, "skipped": 0, "errors": 0}
    if not pending:
        log.info(f"No pending predictions to grade{f' for {date_str}' if date_str else ''}.")
        return stats

    today = date.fromisoformat(eastern_today())
    season_loaders = {}
    for game_date in sorted({prediction["game_date"] for prediction in pending}):
        try:
            target_date = date.fromisoformat(game_date)
        except ValueError:
            log.warning(f"Skipping ledger rows with invalid date {game_date!r}")
            stats["errors"] += sum(p["game_date"] == game_date for p in pending)
            continue
        if target_date > today:
            count = sum(p["game_date"] == game_date for p in pending)
            log.info(f"Skipping {count} future prediction(s) for {game_date}.")
            stats["skipped"] += count
            continue
        if target_date == today and not allow_today:
            count = sum(p["game_date"] == game_date for p in pending)
            log.info(
                f"Skipping {count} same-day prediction(s) for {game_date}; "
                "grade after the slate is final or pass allow_today=True"
            )
            stats["skipped"] += count
            continue

        season = current_season(target_date)
        if loader is not None:
            date_loader = loader
        else:
            if season not in season_loaders:
                season_loaders[season] = _loader_for_season(loader_factory, season)
            date_loader = season_loaders[season]

        log.info(f"Grading predictions for {game_date} using NBA season {season}...")
        for prediction in (p for p in pending if p["game_date"] == game_date):
            player_name = prediction["player"]
            try:
                player_id = date_loader.get_player_id(player_name)
                if player_id is None:
                    log.warning(f"Could not find ID for {player_name}")
                    stats["errors"] += 1
                    continue
                logs = date_loader.get_player_gamelog(player_id)
                if logs is None or logs.empty or "GAME_DATE" not in logs.columns or "REB" not in logs.columns:
                    log.warning(f"No usable game log for {player_name}; leaving prediction pending")
                    stats["skipped"] += 1
                    continue

                game_row = None
                for _, row in logs.iterrows():
                    if _parse_log_date(row["GAME_DATE"]) == target_date:
                        game_row = row
                        break
                if game_row is None:
                    log.info(
                        f"No game-log entry for {player_name} on {game_date}; "
                        "leaving prediction pending"
                    )
                    stats["skipped"] += 1
                    continue

                # Guard against a bad date/player match in unusual data feeds.
                matchup = str(game_row.get("MATCHUP", ""))
                opponent = str(prediction.get("opponent") or "")
                if opponent and matchup and opponent not in matchup:
                    log.warning(
                        f"Opponent mismatch for {player_name} on {game_date}: "
                        f"ledger={opponent}, log={matchup}; leaving pending"
                    )
                    stats["errors"] += 1
                    continue

                rebounds_value = float(game_row["REB"])
                if not math.isfinite(rebounds_value) or not rebounds_value.is_integer() or rebounds_value < 0:
                    raise ValueError(f"invalid rebound total {game_row['REB']!r}")
                actual_rebounds = int(rebounds_value)
                outcome = ledger.grade_prediction(prediction["id"], actual_rebounds)
                if outcome in ("WIN", "LOSS", "PUSH"):
                    stats["graded"] += 1
                    log.info(
                        f"Graded {player_name} (line {prediction['line']}, actual "
                        f"{actual_rebounds}) -> {outcome}"
                    )
                else:
                    stats["skipped"] += 1
            except Exception as exc:
                log.warning(f"Failed to grade {player_name} on {game_date}: {exc}")
                stats["errors"] += 1
    return stats


def manually_settle(ledger, pred_id, *, actual_rebounds=None, void_reason=None):
    """Explicitly settle one prediction for audited manual corrections."""
    if (actual_rebounds is None) == (void_reason is None):
        raise ValueError("provide exactly one of actual_rebounds or void_reason")
    if void_reason is not None:
        return ledger.void_prediction(pred_id, void_reason)
    return ledger.grade_prediction(pred_id, actual_rebounds)


def print_summary(ledger=None):
    ledger = ledger or PredictionLedger()
    summary = ledger.get_performance_summary()
    if not summary:
        print("No graded predictions available yet.")
        return

    print("\n" + "=" * 75)
    print(" PREDICTION LEDGER PERFORMANCE SUMMARY")
    print("=" * 75)
    print(f"{'Tier':<20} | {'Bets':<5} | {'W-L-P':<10} | {'Void':<4} | {'Win %':<7} | {'Units':<8} | {'ROI':<7} | {'Brier':<7}")
    print("-" * 75)

    total_bets = total_wins = total_losses = total_pushes = total_voids = 0
    total_pnl = 0.0
    for row in summary:
        tier = row["tier"]
        bets = int(row["total_bets"] or 0)
        wins = int(row["wins"] or 0)
        losses = int(row["losses"] or 0)
        pushes = int(row["pushes"] or 0)
        voids = int(row["voids"] or 0)
        pnl = float(row["total_pnl"] or 0.0)
        brier = row["avg_brier"]
        roi = row["realized_roi"]
        win_pct = wins / (wins + losses) * 100 if wins + losses else 0.0

        total_bets += bets
        total_wins += wins
        total_losses += losses
        total_pushes += pushes
        total_voids += voids
        total_pnl += pnl
        brier_text = f"{brier:.3f}" if brier is not None else "—"
        roi_text = f"{roi:+.1%}" if roi is not None else "—"
        print(
            f"{tier:<20} | {bets:<5} | {wins}-{losses}-{pushes:<6} | {voids:<4} | "
            f"{win_pct:>5.1f}% | {pnl:>+7.2f}u | {roi_text:>7} | {brier_text:>7}"
        )

    print("-" * 75)
    overall_win_pct = (
        total_wins / (total_wins + total_losses) * 100
        if total_wins + total_losses
        else 0.0
    )
    total_roi = total_pnl / total_bets if total_bets else 0.0
    print(
        f"{'TOTAL':<20} | {total_bets:<5} | {total_wins}-{total_losses}-{total_pushes:<6} | "
        f"{total_voids:<4} | {overall_win_pct:>5.1f}% | {total_pnl:>+7.2f}u | "
        f"{total_roi:>+6.1%} |"
    )
    print("=" * 75 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grade predictions against actual box scores.")
    parser.add_argument("--date", type=str, help="Specific date to grade (YYYY-MM-DD)")
    parser.add_argument("--summary-only", action="store_true", help="Only print performance")
    parser.add_argument("--db", default="data/predictions.db", help="Ledger SQLite path")
    parser.add_argument("--prediction-id", type=int, help="Manually settle this prediction ID")
    parser.add_argument(
        "--allow-today",
        action="store_true",
        help="Allow automatic same-day grading after independently confirming games are final",
    )
    manual = parser.add_mutually_exclusive_group()
    manual.add_argument("--actual", type=int, help="Manual actual rebound total")
    manual.add_argument("--void", dest="void_reason", help="Void reason confirmed by sportsbook")
    args = parser.parse_args()

    active_ledger = PredictionLedger(args.db)
    if args.prediction_id is not None:
        if args.actual is None and args.void_reason is None:
            parser.error("--prediction-id requires --actual or --void")
        result = manually_settle(
            active_ledger,
            args.prediction_id,
            actual_rebounds=args.actual,
            void_reason=args.void_reason,
        )
        log.info(f"Prediction {args.prediction_id} settlement: {result}")
    elif not args.summary_only:
        grade_predictions(args.date, ledger=active_ledger, allow_today=args.allow_today)

    print_summary(active_ledger)
