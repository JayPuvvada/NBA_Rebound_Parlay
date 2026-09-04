import pandas as pd
import numpy as np
import math
import re
from collections.abc import Mapping
from numbers import Real
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from src.data_loader import NBADataLoader
from src.utils import normalize_name, get_logger, current_season

log = get_logger('features')


def _parse_as_of_date(as_of_date):
    if not isinstance(as_of_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', as_of_date):
        raise ValueError('as_of_date must use YYYY-MM-DD format')
    return datetime.strptime(as_of_date, '%Y-%m-%d').date()


def _parse_height_inches(height_str, default=72):
    """Parse 'FT-IN' (e.g. '6-10') into inches. Returns `default` on malformed input."""
    if not isinstance(height_str, str) or '-' not in height_str:
        return default
    try:
        ft, inch = height_str.split('-')
        return int(ft) * 12 + int(inch)
    except (ValueError, AttributeError):
        return default


def _normalize_position(position, default='F'):
    """Map NBA position labels to their listed primary G/F/C role."""
    if not isinstance(position, str) or not position.strip():
        return default
    value = position.upper().strip()
    word_map = {'GUARD': 'G', 'FORWARD': 'F', 'CENTER': 'C'}
    # CommonPlayerInfo returns both forms across seasons: "Forward-Center" and "F-C".
    primary = value.replace('/', '-').split('-')[0].strip()
    if primary in word_map:
        return word_map[primary]
    if primary in {'G', 'F', 'C'}:
        return primary
    for word, code in word_map.items():
        if value.startswith(word):
            return code
    for code in ('G', 'F', 'C'):
        if code in value:
            return code
    return default


def _clean_minutes(value):
    """Parse NBA minute fields; malformed/DNP strings become NaN."""
    if isinstance(value, str):
        value = value.strip()
        if ':' in value:
            try:
                minutes, seconds = value.split(':', 1)
                return float(minutes) + float(seconds) / 60.0
            except (TypeError, ValueError):
                return np.nan
        if not value:
            return np.nan
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else np.nan
    except (TypeError, ValueError):
        return np.nan


def _is_historical(as_of_date):
    if not as_of_date:
        return False
    try:
        parsed = _parse_as_of_date(as_of_date)
    except (TypeError, ValueError):
        return False
    return parsed < datetime.now(ZoneInfo('America/New_York')).date()


def _uses_live_injuries(as_of_date, max_future_days=2):
    if not as_of_date:
        return True
    try:
        parsed = _parse_as_of_date(as_of_date)
    except (TypeError, ValueError):
        return False
    today = datetime.now(ZoneInfo('America/New_York')).date()
    return today <= parsed <= today + timedelta(days=max_future_days)


def _with_as_of(method, *args, as_of_date=None, **kwargs):
    """Keep compatibility with loaders while only adding a cutoff when requested."""
    if as_of_date is not None:
        kwargs['as_of'] = as_of_date
    return method(*args, **kwargs)


def _finite_float(value, default=None, *, minimum=None, maximum=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    if minimum is not None and result < minimum:
        return default
    if maximum is not None and result > maximum:
        return default
    return result


def _projection_safety_context(loader, as_of_date):
    """Build the actionability gate from date scope and injury provenance."""
    historical_mode = _is_historical(as_of_date)
    live_injury_window = _uses_live_injuries(as_of_date)
    limitations = []

    if historical_mode:
        limitations.append(
            'historical injury status is unavailable; projection is analysis-only'
        )
    elif not live_injury_window:
        limitations.append(
            'live injury status is unreliable beyond the near-term slate'
        )

    if not live_injury_window:
        injury_freshness = {
            'status': 'disabled', 'source': None, 'fetched_at': None,
            'entry_count': None, 'stale': None,
        }
    else:
        metadata_method = getattr(loader, 'get_injury_report_metadata', None)
        if not callable(metadata_method):
            injury_freshness = {
                'status': 'unknown', 'source': None, 'fetched_at': None,
                'entry_count': None, 'stale': None,
            }
        else:
            try:
                raw_metadata = metadata_method()
            except Exception as exc:
                log.warning(f"Injury report metadata unavailable: {exc}")
                raw_metadata = None
            if isinstance(raw_metadata, Mapping):
                injury_freshness = dict(raw_metadata)
                status = str(injury_freshness.get('status') or 'unknown').lower()
                injury_freshness['status'] = status
                for key in ('source', 'fetched_at', 'entry_count', 'stale'):
                    injury_freshness.setdefault(key, None)
            else:
                injury_freshness = {
                    'status': 'unknown', 'source': None, 'fetched_at': None,
                    'entry_count': None, 'stale': None,
                }

    # A degraded report is actionable only for the loader's explicitly bounded
    # stale-cache fallback. A partial/broken live scrape also reports degraded,
    # but must remain diagnostic-only because it can silently omit key players.
    injury_status_acceptable = live_injury_window and (
        injury_freshness['status'] == 'available'
        or (
            injury_freshness['status'] == 'degraded'
            and injury_freshness.get('source') == 'bounded_stale_disk_cache'
            and injury_freshness.get('stale') is True
        )
    )
    if live_injury_window and not injury_status_acceptable:
        limitations.append(
            f"injury data status is {injury_freshness['status']}; "
            'projection is diagnostic-only'
        )

    source_metadata = {
        'status': 'primary', 'source': 'stats.nba.com', 'limitations': [],
    }
    source_method = getattr(loader, 'get_data_source_metadata', None)
    if callable(source_method):
        try:
            raw_source_metadata = source_method()
        except Exception as exc:
            log.warning(f"Projection source metadata unavailable: {exc}")
            raw_source_metadata = None
        if isinstance(raw_source_metadata, Mapping):
            source_metadata = dict(raw_source_metadata)
            source_metadata['status'] = str(
                source_metadata.get('status') or 'unknown'
            ).lower()
            source_metadata['limitations'] = list(
                source_metadata.get('limitations') or []
            )
    source_acceptable = source_metadata['status'] == 'primary'
    if not source_acceptable:
        limitations.extend(source_metadata['limitations'])
        limitations.append(
            'alternate or estimated data was used; projection is diagnostic-only'
        )
    limitations = list(dict.fromkeys(limitations))

    return {
        'historical_mode': historical_mode,
        'live_injury_window': live_injury_window,
        'injury_freshness': injury_freshness,
        'injury_status_acceptable': injury_status_acceptable,
        'data_sources': source_metadata,
        'prediction_eligible': (
            not historical_mode
            and live_injury_window
            and injury_status_acceptable
            and source_acceptable
        ),
        'limitations': limitations,
    }

class FeatureEngineer:
    def __init__(self, data_loader):
        self.loader = data_loader
        # Heuristic constants for Long Rebounds
        # If Opponent 3PA Rate > 40%, adjust expectations:
        self.LONG_REB_MATRIX = {
            'G': 1.03,
            'F': 1.00,
            'C': 0.98,
        }

    def get_team_injury_list(self, team_id, as_of_date=None):
        """
        Returns a list of injured players for a given team.
        Format: ["Player Name (Status)", ...]
        """
        # Current scrapers cannot reconstruct historical availability. Returning
        # no list is safer than leaking today's injuries into an old forecast.
        if not _uses_live_injuries(as_of_date):
            return []
        try:
            roster = self.loader.get_team_roster(team_id)
        except Exception as exc:
            log.warning(f"Roster unavailable while building injury list for {team_id}: {exc}")
            return []
        if roster.empty:
            log.debug(f"Roster empty for team {team_id}")
            return []

        try:
            injury_report = self.loader.get_injury_report()
        except Exception as exc:
            log.warning(f"Injury report unavailable: {exc}")
            return []
        log.debug(f"Injury report size: {len(injury_report)}")

        notes = []
        for _, row in roster.iterrows():
            name = row['PLAYER']
            status = injury_report.get(normalize_name(name), 'Active')
            if status != 'Active':
                notes.append(f"{name} ({status})")
        return notes

    def get_player_stats(self, player_id, opponent_abbrev=None, as_of_date=None):
        """
        Fetches player logs and splits rebounding into OREB/DREB rates.
        Also calculates historical rates against the specific opponent.
        """
        logs = _with_as_of(
            self.loader.get_player_gamelog, player_id, as_of_date=as_of_date
        )
        if logs.empty:
             return None
        total_only = logs.attrs.get('total_rebounds_only') is True
        required = {'MIN', 'REB'} if total_only else {'MIN', 'OREB', 'DREB', 'REB'}
        if not required.issubset(logs.columns):
            log.warning(f"Player gamelog missing columns: {sorted(required.difference(logs.columns))}")
            return None

        logs = logs.copy()
        if total_only:
            # The rate blend adds its two channels. Route observed totals
            # through one channel for that calculation only; these are not
            # observed defensive rebounds. Disable split-based adjustments below.
            logs['OREB'] = 0.0
            logs['DREB'] = logs['REB']
            self.loader.mark_data_degraded(
                'ESPN provides total rebounds only; split-dependent matchup adjustments are disabled'
            )
        if 'GAME_DATE' in logs.columns:
            logs['_DATE'] = pd.to_datetime(logs['GAME_DATE'], errors='coerce', format='mixed')
            logs = logs.sort_values('_DATE', ascending=False).drop(columns=['_DATE'])
        logs['MIN_FLOAT'] = logs['MIN'].apply(_clean_minutes)
        for column in ('OREB', 'DREB', 'REB'):
            logs[column] = pd.to_numeric(logs[column], errors='coerce')

        # PlayerGameLog usually omits DNPs. If a provider does include one, count
        # only a true zero-minute row; a four-minute appearance is not a DNP.
        known_minutes = logs['MIN_FLOAT'].notna()
        dnp_count = int((logs.loc[known_minutes, 'MIN_FLOAT'] == 0).sum())
        total_game_entries = int(known_minutes.sum())
        dnp_rate = dnp_count / total_game_entries if total_game_entries else 0.0

        played_logs = logs[(logs['MIN_FLOAT'] > 0) & logs['REB'].notna()].copy()
        if played_logs.empty:
            return None
        # Sportsbook player props are normally void if a player never enters.
        # Estimate the settlement distribution from appearances only; DNP rate
        # remains separate availability metadata. Each appearance contributes once.
        reb_all = played_logs['REB'].astype(float)
        reb_variance = float(reb_all.var(ddof=1)) if len(reb_all) >= 3 else None
        # Avoid unstable per-minute skill rates from tiny garbage-time samples.
        rate_logs = played_logs[played_logs['MIN_FLOAT'] >= 5].copy()
        if rate_logs.empty:
            rate_logs = played_logs.copy()

        # 2. Calculate Per-Minute Rates (The "Skill" Metric)
        # We use Per-Minute instead of Per-Game to decouple skill from playing time
        rate_logs['OREB_PM'] = rate_logs['OREB'] / rate_logs['MIN_FLOAT']
        rate_logs['DREB_PM'] = rate_logs['DREB'] / rate_logs['MIN_FLOAT']
        
        # 3. Get Context (Position, Name, TeamID)
        try:
            info = self.loader.get_common_player_info(player_id)
        except Exception as exc:
            log.warning(f"Common player info unavailable for {player_id}: {exc}")
            info = pd.DataFrame()
        
        # Robust Team ID Fetch
        team_id = None
        team_abbrev = None
        team_source = None
        if 'TEAM_ID' in played_logs.columns:
            team_id = played_logs.iloc[0]['TEAM_ID']
            team_source = 'newest pre-cutoff gamelog TEAM_ID'
        elif 'Team_ID' in played_logs.columns:
            team_id = played_logs.iloc[0]['Team_ID']
            team_source = 'newest pre-cutoff gamelog Team_ID'

        # PlayerGameLog often omits TEAM_ID. MATCHUP still identifies the team
        # represented by that historical row and avoids a post-trade current-team leak.
        if 'MATCHUP' in played_logs.columns:
            matchup = str(played_logs.iloc[0].get('MATCHUP', '') or '').upper()
            match = re.match(r'^\s*([A-Z]{3})\s+(?:VS\.?|@)', matchup)
            if match:
                team_abbrev = match.group(1)
                team_id_missing = team_id is None or pd.isna(team_id) or not bool(team_id)
                if team_id_missing and hasattr(self.loader, 'get_team_id'):
                    team_id = self.loader.get_team_id(team_abbrev)
                    if team_id:
                        team_source = 'newest pre-cutoff gamelog MATCHUP'

        if (team_id is None or pd.isna(team_id) or not team_id) and not info.empty:
            team_id = info.iloc[0].get('TEAM_ID')
            team_source = 'current player info fallback'
        if isinstance(team_id, Real) and math.isfinite(float(team_id)):
            team_id = int(team_id)
            
        if not info.empty:
            pos_str = info.iloc[0].get('POSITION', 'Unknown')
            position = _normalize_position(pos_str)
        else:
            position = 'F'

        # 4. Opponent History (Filtered by Opponent Abbrev)
        opp_oreb_rate = None
        opp_dreb_rate = None
        total_rate_minutes = rate_logs['MIN_FLOAT'].sum()
        season_oreb = float(rate_logs['OREB'].sum() / total_rate_minutes)
        season_dreb = float(rate_logs['DREB'].sum() / total_rate_minutes)

        recent_logs = rate_logs.head(5)
        recent_minutes = recent_logs['MIN_FLOAT'].sum()
        recent_raw_oreb = float(recent_logs['OREB'].sum() / recent_minutes)
        recent_raw_dreb = float(recent_logs['DREB'].sum() / recent_minutes)
        recent_reliability = len(recent_logs) / (len(recent_logs) + 5.0)
        recent_oreb = recent_reliability * recent_raw_oreb + (1 - recent_reliability) * season_oreb
        recent_dreb = recent_reliability * recent_raw_dreb + (1 - recent_reliability) * season_dreb

        if opponent_abbrev and 'MATCHUP' in rate_logs.columns:
            # Matchup string usually contains abbreviations like "OKC vs. GSW"
            opponent = str(opponent_abbrev).strip().upper()
            pattern = rf"(?:vs\.?|@)\s*{re.escape(opponent)}\s*$"
            opp_logs = rate_logs[
                rate_logs['MATCHUP'].astype(str).str.contains(pattern, case=False, regex=True, na=False)
            ]
            if not opp_logs.empty:
                opp_minutes = opp_logs['MIN_FLOAT'].sum()
                opp_raw_oreb = opp_logs['OREB'].sum() / opp_minutes
                opp_raw_dreb = opp_logs['DREB'].sum() / opp_minutes
                # Head-to-head samples are especially noisy; use an eight-game prior.
                k = len(opp_logs)
                shrink = k / (k + 8)
                opp_oreb_rate = shrink * opp_raw_oreb + (1 - shrink) * season_oreb
                opp_dreb_rate = shrink * opp_raw_dreb + (1 - shrink) * season_dreb

        # 5. Trend Data for Chart
        last_10_trend = []
        if not played_logs.empty:
            trend_slice = played_logs.head(10).iloc[::-1]
            for _, row in trend_slice.iterrows():
                try: 
                    # Extract Opponent from MATCHUP
                    # Matchup ex: "DEN vs. BOS" or "DEN @ BOS"
                    m = str(row.get('MATCHUP', ''))
                    opp_code = m.split(' ')[-1] if m else ''
                    
                    last_10_trend.append({
                        'date': row['GAME_DATE'],
                        'rebounds': int(row['REB']),
                        'opponent': opp_code,
                        'minutes': float(row['MIN_FLOAT'])
                    })
                except (TypeError, ValueError, KeyError):
                    pass

        # 6. Variance-Aware Stats (actual game-to-game variance)
        reb_mean = float(reb_all.mean()) if len(reb_all) > 0 else None

        # 7. Minutes Trend Detection (linear regression on last 5 games)
        minutes_trend_slope = 0.0
        recent_mins = played_logs.head(5)['MIN_FLOAT'].values
        if len(recent_mins) >= 3:
            # logs are newest-first, so reverse for proper time order
            ordered_mins = recent_mins[::-1]
            x = np.arange(len(ordered_mins))
            coeffs = np.polyfit(x, ordered_mins, 1)
            minutes_trend_slope = float(coeffs[0])  # min/game slope

        return {
            'player_name': info.iloc[0].get('DISPLAY_FIRST_LAST', 'Unknown') if not info.empty else 'Unknown',
            'position': position,
            'season_oreb_rate': season_oreb,
            'rebound_split_available': not total_only,
            'season_dreb_rate': season_dreb,
            'recent_oreb_rate': recent_oreb,
            'recent_dreb_rate': recent_dreb,
            'opp_oreb_rate': opp_oreb_rate,
            'opp_dreb_rate': opp_dreb_rate,
            'last_5_min': float(played_logs.head(5)['MIN_FLOAT'].mean()),
            'last_10_min': float(played_logs.head(10)['MIN_FLOAT'].mean()),
            'season_min_avg': float(played_logs['MIN_FLOAT'].mean()),
            'team_id': team_id,
            'team_abbreviation': team_abbrev,
            'team_source': team_source,
            'last_10_games': last_10_trend,
            # New: Variance-Aware Simulation data
            'reb_variance': reb_variance,
            'reb_std': float(reb_all.std(ddof=1)) if len(reb_all) >= 3 else None,
            'reb_mean': reb_mean,
            'games_played': len(played_logs),
            'dnp_rate': dnp_rate,
            'minutes_trend_slope': minutes_trend_slope,
            'variance_sample_size': len(reb_all),
            'rate_sample_size': len(rate_logs),
            'trend_order': 'oldest_to_newest',
            'as_of_date': as_of_date,
            'data_cutoff': f"before {as_of_date}" if as_of_date else 'latest available',
        }

    def get_matchup_context(self, team_id, opponent_team_id, as_of_date=None):
        """
        Fetches environment stats: Pace, Shooting %, and Opponent tendencies.
        """
        # Load Team & Opponent Stats
        if not team_id or not opponent_team_id:
            return None
        try:
            league_adv = _with_as_of(
                self.loader.get_team_advanced_stats, as_of_date=as_of_date
            )
            league_base = _with_as_of(
                self.loader.get_team_stats, as_of_date=as_of_date
            )
            league_opp = _with_as_of(
                self.loader.get_opponent_stats_per_game, as_of_date=as_of_date
            )
        except Exception as exc:
            log.warning(
                "League matchup dashboards unavailable; using neutral context: %s",
                exc,
            )
            marker = getattr(self.loader, 'mark_data_degraded', None)
            if callable(marker):
                marker(
                    'league matchup dashboards were unavailable; matchup adjustments were neutralized'
                )
            return {
                'team_pace': 99.0,
                'opp_pace': 99.0,
                'team_fg_pct': 0.47,
                'opp_fg_pct': 0.47,
                'team_fg_pct_allowed': None,
                'opp_fg_pct_allowed': None,
                'opp_3par': 0.40,
                'opp_oreb_allowed': 10.5,
                'opp_dreb_allowed': 33.5,
                'opp_oreb_allowed_raw': 10.5,
                'opp_dreb_allowed_raw': 33.5,
                'league_avg_pace': 99.0,
                'league_avg_oreb_allowed': 10.5,
                'league_avg_dreb_allowed': 33.5,
                'league_avg_fg_pct': 0.47,
                'opp_def_3par': 0.40,
                'league_avg_def_3par': 0.40,
                'opponent_rebound_source': 'neutral fallback after upstream outage',
                'is_position_level_dvp': False,
                'as_of_date': as_of_date,
            }
        required_base = {'TEAM_ID', 'FG_PCT'}
        if (
            not required_base.issubset(league_base.columns)
            or 'TEAM_ID' not in league_adv.columns
            or 'TEAM_ID' not in league_opp.columns
        ):
            log.warning("League dashboard data is missing required matchup columns")
            return None
        
        team_stats = league_base[league_base['TEAM_ID'] == team_id]
        team_adv = league_adv[league_adv['TEAM_ID'] == team_id]
        
        opp_stats_off = league_base[league_base['TEAM_ID'] == opponent_team_id]
        opp_adv = league_adv[league_adv['TEAM_ID'] == opponent_team_id]
        opp_stats_def = league_opp[league_opp['TEAM_ID'] == opponent_team_id]
        team_stats_def = league_opp[league_opp['TEAM_ID'] == team_id]

        if team_stats.empty or opp_stats_off.empty:
            return None

        # 3-Point Attempt Rate (3PA / FGA) - From Opponent's OFFENSE
        opp_3par = 0.0
        if 'FG3A' in opp_stats_off.columns and 'FGA' in opp_stats_off.columns:
            fga = _finite_float(opp_stats_off['FGA'].values[0], 0, minimum=0)
            if fga > 0:
                opp_3par = _finite_float(opp_stats_off['FG3A'].values[0], 0, minimum=0) / fga

        # Opponent Rebounds Allowed (Split)
        opp_oreb_allowed = 10.5
        opp_dreb_allowed = 33.5
        if not opp_stats_def.empty:
            if 'OPP_OREB' in opp_stats_def.columns:
                opp_oreb_allowed = _finite_float(opp_stats_def['OPP_OREB'].values[0], opp_oreb_allowed, minimum=0)
            if 'OPP_DREB' in opp_stats_def.columns:
                opp_dreb_allowed = _finite_float(opp_stats_def['OPP_DREB'].values[0], opp_dreb_allowed, minimum=0)
        
        # League Averages
        league_avg_oreb_allowed = 10.5
        league_avg_dreb_allowed = 33.5
        if 'OPP_OREB' in league_opp.columns:
            league_avg_oreb_allowed = _finite_float(league_opp['OPP_OREB'].mean(), 10.5, minimum=0.1)
        if 'OPP_DREB' in league_opp.columns:
            league_avg_dreb_allowed = _finite_float(league_opp['OPP_DREB'].mean(), 33.5, minimum=0.1)
            
        # Defensive 3-Point Attempt Rate (Scheme proxy for Drop vs Switch)
        opp_def_3par = 0.40
        if not opp_stats_def.empty and 'OPP_FG3A' in opp_stats_def.columns and 'OPP_FGA' in opp_stats_def.columns:
            def_fga = _finite_float(opp_stats_def['OPP_FGA'].values[0], 0, minimum=0)
            if def_fga > 0:
                opp_def_3par = _finite_float(opp_stats_def['OPP_FG3A'].values[0], 0, minimum=0) / def_fga
                
        league_avg_def_3par = 0.40
        if 'OPP_FG3A' in league_opp.columns and 'OPP_FGA' in league_opp.columns:
            league_total_3pa = _finite_float(league_opp['OPP_FG3A'].sum(), 0, minimum=0)
            league_total_fga = _finite_float(league_opp['OPP_FGA'].sum(), 0, minimum=0)
            if league_total_fga > 0:
                league_avg_def_3par = league_total_3pa / league_total_fga
            
        league_avg_fg_pct = 0.47
        if 'FG_PCT' in league_base.columns:
            league_avg_fg_pct = _finite_float(league_base['FG_PCT'].mean(), 0.47, minimum=0.2, maximum=0.8)

        team_fg_allowed = None
        opp_fg_allowed = None
        if 'OPP_FG_PCT' in league_opp.columns:
            if not team_stats_def.empty:
                team_fg_allowed = _finite_float(
                    team_stats_def['OPP_FG_PCT'].values[0], None,
                    minimum=0.2, maximum=0.8,
                )
            if not opp_stats_def.empty:
                opp_fg_allowed = _finite_float(
                    opp_stats_def['OPP_FG_PCT'].values[0], None,
                    minimum=0.2, maximum=0.8,
                )

        team_pace = _finite_float(team_adv['PACE'].values[0], 99.0, minimum=70, maximum=130) if not team_adv.empty and 'PACE' in team_adv else 99.0
        opp_pace = _finite_float(opp_adv['PACE'].values[0], 99.0, minimum=70, maximum=130) if not opp_adv.empty and 'PACE' in opp_adv else 99.0
        league_avg_pace = _finite_float(league_adv['PACE'].mean(), 99.0, minimum=70, maximum=130) if 'PACE' in league_adv else 99.0
        # OPP_REB dashboard values are PerGame, so normalize the opponent to a
        # league-average pace before applying the separate matchup pace factor.
        # Otherwise a fast team is rewarded twice for the same extra possessions.
        opp_oreb_allowed_raw = opp_oreb_allowed
        opp_dreb_allowed_raw = opp_dreb_allowed
        pace_normalizer = league_avg_pace / opp_pace
        opp_oreb_allowed *= pace_normalizer
        opp_dreb_allowed *= pace_normalizer
        team_fg_pct = _finite_float(team_stats['FG_PCT'].values[0], league_avg_fg_pct, minimum=0.2, maximum=0.8)
        opp_fg_pct = _finite_float(opp_stats_off['FG_PCT'].values[0], league_avg_fg_pct, minimum=0.2, maximum=0.8)

        return {
            'team_pace': team_pace,
            'opp_pace': opp_pace,
            'team_fg_pct': team_fg_pct,
            'opp_fg_pct': opp_fg_pct,
            'team_fg_pct_allowed': team_fg_allowed,
            'opp_fg_pct_allowed': opp_fg_allowed,
            'opp_3par': opp_3par,
            'opp_oreb_allowed': opp_oreb_allowed,
            'opp_dreb_allowed': opp_dreb_allowed,
            'opp_oreb_allowed_raw': opp_oreb_allowed_raw,
            'opp_dreb_allowed_raw': opp_dreb_allowed_raw,
            'league_avg_pace': league_avg_pace,
            'league_avg_oreb_allowed': league_avg_oreb_allowed,
            'league_avg_dreb_allowed': league_avg_dreb_allowed,
            'league_avg_fg_pct': league_avg_fg_pct,
            'opp_def_3par': opp_def_3par,
            'league_avg_def_3par': league_avg_def_3par,
            'opponent_rebound_source': (
                'pace-normalized team-level opponent rebounds allowed per game'
            ),
            'is_position_level_dvp': False,
            'as_of_date': as_of_date,
        }

    def get_opponent_rebound_environment_multiplier(self, position, opp_allowed, league_avg, opp_def_3par=None, league_avg_def_3par=None):
        """
        Conservative team-level rebound environment adjustment.

        This is deliberately not labelled true defense-vs-position: the NBA
        Opponent dashboard is team-level. Position only controls how much of the
        team signal and three-point scheme proxy is applied.
        """
        position = _normalize_position(position)
        allowed = _finite_float(opp_allowed, None, minimum=0)
        average = _finite_float(league_avg, None, minimum=0.1)
        if allowed is None or average is None:
            return 1.0
        ratio = max(0.75, min(1.25, allowed / average))
        exposure = {'C': 0.45, 'F': 0.32, 'G': 0.20}.get(position, 0.30)
        base_factor = 1.0 + (ratio - 1.0) * exposure
        
        # Defensive Scheme Adjustment
        opp_scheme = _finite_float(opp_def_3par, None, minimum=0.1, maximum=0.8)
        league_scheme = _finite_float(league_avg_def_3par, None, minimum=0.1, maximum=0.8)
        if opp_scheme is not None and league_scheme is not None:
            scheme_ratio = max(0.8, min(1.2, opp_scheme / league_scheme))
            # If scheme ratio is > 1.0 (High 3PAR allowed), they likely pack the paint (Drop).
            # This means Centers get MORE rebounds (cleaning up the paint), Guards get FEWER (contesting 3s).
            if position in {'C', 'F'}:
                base_factor *= 1.0 + (scheme_ratio - 1.0) * 0.06
            elif position == 'G':
                base_factor *= 1.0 - (scheme_ratio - 1.0) * 0.06

        return max(0.92, min(1.08, base_factor))

    def get_dvp_multiplier(self, position, opp_allowed, league_avg, opp_def_3par=None, league_avg_def_3par=None):
        """Backward-compatible alias for the team-level environment method."""
        return self.get_opponent_rebound_environment_multiplier(
            position, opp_allowed, league_avg, opp_def_3par, league_avg_def_3par
        )

    def adjust_minutes_for_injuries(self, base_minutes, player_id, team_id, as_of_date=None, return_details=False):
        """
        Adjust minutes up if a starter is out, or down if the player themself is questionable.
        Uses cached roster/depth charts internally.
        """
        from src.utils import injury_bucket
        
        base_minutes = _finite_float(base_minutes, 0.0, minimum=0, maximum=48)
        details = {'player_status': 'Active', 'out_teammates': [], 'minutes_added': 0.0}
        if not _uses_live_injuries(as_of_date):
            # Current HTML reports are not valid historical/far-future sources.
            return (base_minutes, details) if return_details else base_minutes

        try:
            injury_report = self.loader.get_injury_report()
            info = self.loader.get_common_player_info(player_id)
        except Exception as exc:
            log.warning(f"Skipping injury minutes adjustment: {exc}")
            return (base_minutes, details) if return_details else base_minutes
        if info.empty:
            return (base_minutes, details) if return_details else base_minutes

        player_name = info.iloc[0]['DISPLAY_FIRST_LAST']
        norm_player_name = normalize_name(player_name)
        
        player_status = injury_report.get(norm_player_name, 'Active')
        details['player_status'] = player_status
        bucket = injury_bucket(player_status)
        if bucket == 'OUT':
            return (0.0, details) if return_details else 0.0
        
        # Haircut for GTD/Questionable starters playing hurt
        if bucket == 'QUESTIONABLE':
            base_minutes *= 0.92

        try:
            roster = self.loader.get_team_roster(team_id)
        except Exception as exc:
            log.warning(f"Skipping teammate injury adjustment: {exc}")
            return (base_minutes, details) if return_details else base_minutes
        if roster.empty:
            return (base_minutes, details) if return_details else base_minutes

        # Check for Teammate Injuries (Same position, Starter minutes)
        try:
            league_adv = _with_as_of(
                self.loader.get_player_advanced_stats, 0, as_of_date=as_of_date
            )
        except Exception as exc:
            log.warning(f"Skipping teammate injury adjustment without minute data: {exc}")
            return (base_minutes, details) if return_details else base_minutes
        # Passing player 0 returns an empty selection; retrieve its populated league cache.
        if hasattr(self.loader, '_as_of_context'):
            season, _, cutoff_key = self.loader._as_of_context(as_of_date)
            cached_league_adv = self.loader._get_from_cache(
                f"league_player_stats_advanced_{season}_{cutoff_key}"
            )
            if cached_league_adv is not None:
                league_adv = cached_league_adv
            if as_of_date is None and (league_adv is None or league_adv.empty):
                league_adv = self.loader._get_from_cache(f"league_player_stats_advanced_{season}")

        if league_adv is None or league_adv.empty or not {'PLAYER_ID', 'MIN'}.issubset(league_adv.columns):
            return (base_minutes, details) if return_details else base_minutes

        roster_stats = pd.merge(roster, league_adv[['PLAYER_ID', 'MIN']], on='PLAYER_ID', how='inner')
        
        teammate_minutes_out = 0.0
        p_pos = _normalize_position(info.iloc[0].get('POSITION', 'F'))
        is_big = p_pos in {'F', 'C'}
        is_guard = p_pos == 'G'

        for _, row in roster_stats.iterrows():
            if row['PLAYER_ID'] == player_id: continue
            
            t_pos = _normalize_position(str(row.get('POSITION', '')), default='')
            t_is_big = t_pos in {'F', 'C'}
            t_is_guard = t_pos == 'G'
            
            # Match if both are Bigs or both are Guards
            match = (is_big and t_is_big) or (is_guard and t_is_guard)
            
            if match:
                # Is this a high-minute player?
                teammate_minutes = _finite_float(row['MIN'], 0.0, minimum=0, maximum=48)
                if teammate_minutes > 20.0:
                    t_name = row['PLAYER']
                    t_status = injury_report.get(normalize_name(t_name), 'Active')
                    if injury_bucket(t_status) == 'OUT':
                        teammate_minutes_out += teammate_minutes
                        details['out_teammates'].append(t_name)

        # Redistribute only a modest fraction of vacated same-role minutes. The
        # previous fixed +8 per injury could stack into an unrealistic role jump.
        if teammate_minutes_out:
            role_share = 0.16 if base_minutes < 22 else 0.09
            teammate_boost = min(6.0, teammate_minutes_out * role_share)
            details['minutes_added'] = round(teammate_boost, 2)
            base_minutes += teammate_boost
        adjusted = min(40.0, base_minutes)
        return (adjusted, details) if return_details else adjusted

    def get_cannibalization_factor(self, team_id, opponent_abbrev, current_player_id, base_projection_func=None, current_proj_minutes=None, as_of_date=None):
        """
        Modest lineup-availability adjustment for rebound competition.

        Pace and miss opportunities are already handled in ``compute_projection``;
        applying another game-opportunity cap here used to double-count them.
        """
        if not _uses_live_injuries(as_of_date):
            return 1.0
        lineup_cannibal_mult = 1.0
        try:
            p_info = self.loader.get_common_player_info(current_player_id)
        except Exception as exc:
            log.warning(f"Skipping lineup rebound adjustment: {exc}")
            return 1.0
        if not p_info.empty:
            pos = _normalize_position(p_info.iloc[0].get('POSITION', ''), default='')
            is_big = pos in {'F', 'C'}
            
            if is_big:
                try:
                    roster = self.loader.get_team_roster(team_id)
                    injury_report = self.loader.get_injury_report()
                except Exception as exc:
                    log.warning(f"Skipping lineup rebound adjustment: {exc}")
                    return 1.0

                injured_bigs = 0
                for _, row in roster.iterrows():
                    t_id = row['PLAYER_ID']
                    if t_id == current_player_id:
                        continue

                    # Primary signal: position. A player listed F/C is a big.
                    # Height is a *tiebreaker* for players with ambiguous positions (e.g. 'G-F').
                    team_pos = _normalize_position(str(row.get('POSITION', '') or ''), default='')
                    is_teammate_big = team_pos in {'C', 'F'}

                    if not is_teammate_big:
                        # Only fall back to height for players with a listed position that
                        # doesn't already mark them as a big. Default missing height to
                        # something *short* so we don't falsely count guards.
                        h_inches = _parse_height_inches(row.get('HEIGHT'), default=72)
                        is_teammate_big = h_inches >= 80

                    if is_teammate_big:
                        t_name = row['PLAYER']
                        from src.utils import injury_bucket
                        status = injury_report.get(normalize_name(t_name), 'Active')
                        if injury_bucket(status) == 'OUT':
                            injured_bigs += 1

                if injured_bigs > 0:
                    lineup_cannibal_mult = 1.0 + (0.02 * min(2, injured_bigs))

        return lineup_cannibal_mult

    def compute_projection(self, player_id, opponent_abbrev, spread=0, manual_minutes=None, home_game=True, days_rest=1, opp_days_rest=1, matchup_factor=1.0, as_of_date=None):
        """
        Refactored 2-Layer Projection Model.
        Layer 1: Base (Skill * Minutes)
        Layer 2: Environment (Pace * Misses * team rebound environment * Matchup)
        """
        if isinstance(player_id, bool) or not isinstance(player_id, Real) or not math.isfinite(float(player_id)) or player_id <= 0:
            return {'error': 'player_id must be a positive number'}
        if not isinstance(opponent_abbrev, str) or not re.fullmatch(r'[A-Za-z]{3}', opponent_abbrev.strip()):
            return {'error': 'opponent must be a three-letter NBA abbreviation'}
        opponent_abbrev = opponent_abbrev.strip().upper()
        spread = _finite_float(spread, None)
        if spread is None or abs(spread) > 50:
            return {'error': 'spread must be a finite number between -50 and 50'}
        if not isinstance(home_game, bool):
            return {'error': 'home_game must be boolean'}
        days_rest = _finite_float(days_rest, None, minimum=0, maximum=14)
        opp_days_rest = _finite_float(opp_days_rest, None, minimum=0, maximum=14)
        matchup_factor = _finite_float(matchup_factor, None, minimum=0.8, maximum=1.2)
        if days_rest is None or opp_days_rest is None or matchup_factor is None:
            return {'error': 'rest and matchup inputs are outside valid ranges'}
        if manual_minutes is not None:
            manual_minutes = _finite_float(manual_minutes, None, minimum=1, maximum=48)
            if manual_minutes is None:
                return {'error': 'manual_minutes must be between 1 and 48'}
        if as_of_date is not None:
            try:
                _parse_as_of_date(as_of_date)
            except (TypeError, ValueError):
                return {'error': 'as_of_date must use YYYY-MM-DD format'}

        # 1. Load Data
        p_stats = self.get_player_stats(player_id, opponent_abbrev, as_of_date=as_of_date)
        if not p_stats: 
            return {'error': 'Player stats not found'}
        p_stats = dict(p_stats)
        rate_keys = (
            'season_oreb_rate', 'season_dreb_rate',
            'recent_oreb_rate', 'recent_dreb_rate',
        )
        for key in rate_keys:
            value = _finite_float(p_stats.get(key), None, minimum=0, maximum=2)
            if value is None:
                return {'error': f'Player stats contain invalid {key}'}
            p_stats[key] = value
        for key in ('opp_oreb_rate', 'opp_dreb_rate'):
            if p_stats.get(key) is not None:
                value = _finite_float(p_stats[key], None, minimum=0, maximum=2)
                if value is None:
                    return {'error': f'Player stats contain invalid {key}'}
                p_stats[key] = value
        for key in ('season_min_avg', 'last_10_min'):
            value = _finite_float(p_stats.get(key), None, minimum=0, maximum=48)
            if value is None:
                return {'error': f'Player stats contain invalid {key}'}
            p_stats[key] = value
        if not p_stats.get('team_id'):
            return {'error': 'Player team is unavailable'}
            
        opp_id = self.loader.get_team_id(opponent_abbrev)
        if not opp_id:
            return {'error': 'Opponent team not found'}
        env = self.get_matchup_context(p_stats['team_id'], opp_id, as_of_date=as_of_date)
        if not env: 
            return {'error': 'Matchup stats not found'}

        # --- Layer 1: Base Projection ---
        
        # Minutes
        season_min = p_stats.get('season_min_avg', p_stats['last_10_min'])
        base_minutes = manual_minutes if manual_minutes is not None else (season_min * 0.6 + p_stats['last_10_min'] * 0.4)
        
        # Minutes Trend Adjustment (NEW)
        # If minutes are trending significantly up/down, project forward
        min_trend_slope = _finite_float(p_stats.get('minutes_trend_slope'), 0.0)
        trend_adjustment = 0.0
        if manual_minutes is None and abs(min_trend_slope) > 0.5:
            # A single five-game slope is noisy; permit only a modest role adjustment.
            trend_adjustment = max(-1.5, min(1.5, min_trend_slope))
            base_minutes += trend_adjustment

        # Injury Adjustment for Minutes
        injury_details = {'player_status': 'Active', 'out_teammates': [], 'minutes_added': 0.0}
        if manual_minutes is None:
            base_minutes, injury_details = self.adjust_minutes_for_injuries(
                base_minutes, player_id, p_stats['team_id'],
                as_of_date=as_of_date, return_details=True,
            )

        if base_minutes <= 0:
            return {'error': 'Player is OUT or injured'}

        # Blowout Logic (Minutes Damping Only)
        abs_spread = abs(spread)
        blowout_risk_label = "None"
        blowout_modifier = 1.0
        
        # Only reduce minutes for extreme spreads
        if abs_spread >= 13.5:
            blowout_risk_label = "High"
            if base_minutes >= 28: blowout_modifier = 0.93
        elif abs_spread >= 9.5:
             blowout_risk_label = "Slight"
             if base_minutes >= 30: blowout_modifier = 0.97

        proj_minutes = base_minutes * blowout_modifier
        
        # Dynamic Recency Weights (NEW)
        # Adjust season/recent/opponent blend based on games played
        try:
            games_played = max(0, int(p_stats.get('games_played', 30)))
        except (TypeError, ValueError, OverflowError):
            games_played = 30
        if games_played < 15:
            w_season, w_recent, w_opp = 0.75, 0.15, 0.10
        elif games_played <= 40:
            w_season, w_recent, w_opp = 0.65, 0.25, 0.10
        else:
            w_season, w_recent, w_opp = 0.55, 0.35, 0.10
            
        # Core Improvement: Dynamic Weight Shifting for Trend Breaks
        season_reb = p_stats['season_oreb_rate'] + p_stats['season_dreb_rate']
        recent_reb = p_stats['recent_oreb_rate'] + p_stats['recent_dreb_rate']
        
        if season_reb > 0:
            deviation = abs(recent_reb - season_reb) / season_reb
            # A possible role change gets a bounded nudge, not a 70% hot-streak weight.
            if deviation > 0.30:
                shift = min(0.10, w_season - 0.50)
                w_recent += shift
                w_season -= shift
        
        # Skill (Rebounds Per Minute) - Dynamic Weighted Blend
        if p_stats.get('opp_oreb_rate') is not None and p_stats.get('opp_dreb_rate') is not None:
            skill_oreb = (p_stats['season_oreb_rate'] * w_season + 
                          p_stats['recent_oreb_rate'] * w_recent + 
                          p_stats['opp_oreb_rate'] * w_opp)
            skill_dreb = (p_stats['season_dreb_rate'] * w_season + 
                          p_stats['recent_dreb_rate'] * w_recent + 
                          p_stats['opp_dreb_rate'] * w_opp)
        else:
            # No opponent data: redistribute opp weight to season
            w_s_no_opp = w_season + w_opp
            skill_oreb = (p_stats['season_oreb_rate'] * w_s_no_opp + 
                          p_stats['recent_oreb_rate'] * w_recent)
            skill_dreb = (p_stats['season_dreb_rate'] * w_s_no_opp + 
                          p_stats['recent_dreb_rate'] * w_recent)

        # Base Calc
        base_rebs = proj_minutes * (skill_oreb + skill_dreb)

        # --- Layer 2: Environment Multiplier ---
        
        # 1. Pace
        game_pace = (env['team_pace'] + env['opp_pace']) / 2.0
        # Per-minute player rates already reflect his own team's normal pace.
        # Adjust only for the change from that baseline in this matchup.
        pace_factor = max(0.94, min(1.06, game_pace / env['team_pace']))
        
        # 2. Miss Opportunities (Weighted for OREB vs DREB)
        # OREB needs My Team Misses, DREB needs Opp Team Misses
        # We blend them based on the player's OREB/DREB ratio
        total_rate = skill_oreb + skill_dreb
        if total_rate > 0:
            oreb_ratio = skill_oreb / total_rate
            dreb_ratio = skill_dreb / total_rate
        else:
            oreb_ratio, dreb_ratio = 0.25, 0.75

        # Compare expected matchup shooting to the player's own embedded team
        # baseline. This avoids rewarding a poor-shooting team twice merely for
        # remaining the same poor-shooting team.
        team_fg_allowed = env.get('team_fg_pct_allowed')
        opp_fg_allowed = env.get('opp_fg_pct_allowed')
        dreb_miss_factor = 1.0
        oreb_miss_factor = 1.0
        if team_fg_allowed is not None:
            expected_opp_fg = (env['opp_fg_pct'] + team_fg_allowed) / 2.0
            dreb_miss_factor = (1.0 - expected_opp_fg) / (1.0 - team_fg_allowed)
        if opp_fg_allowed is not None:
            expected_team_fg = (env['team_fg_pct'] + opp_fg_allowed) / 2.0
            oreb_miss_factor = (1.0 - expected_team_fg) / (1.0 - env['team_fg_pct'])
        dreb_miss_factor = max(0.94, min(1.06, dreb_miss_factor))
        oreb_miss_factor = max(0.94, min(1.06, oreb_miss_factor))
        
        opportunity_factor = (dreb_miss_factor * dreb_ratio) + (oreb_miss_factor * oreb_ratio)
        if p_stats.get('rebound_split_available') is False:
            opportunity_factor = 1.0
        
        # 3. Team-level opponent rebound environment (not true position DvP)
        opp_def_3par = env.get('opp_def_3par')
        league_avg_def_3par = env.get('league_avg_def_3par')
        
        rebound_env_dreb = self.get_opponent_rebound_environment_multiplier(p_stats['position'], env['opp_dreb_allowed'], env['league_avg_dreb_allowed'], opp_def_3par, league_avg_def_3par)
        rebound_env_oreb = self.get_opponent_rebound_environment_multiplier(p_stats['position'], env['opp_oreb_allowed'], env['league_avg_oreb_allowed'], opp_def_3par, league_avg_def_3par)
        rebound_env_factor = (rebound_env_dreb * dreb_ratio) + (rebound_env_oreb * oreb_ratio)
        if p_stats.get('rebound_split_available') is False:
            rebound_env_factor = 1.0
        
        # 4. Long Rebound (Opp 3PA)
        long_reb_factor = 1.0
        if env['opp_3par'] > 0.42:
             long_reb_factor = self.LONG_REB_MATRIX.get(p_stats['position'], 1.0)
        
        # --- COMBINE & CLAMP ---
        
        # Multipliers
        # Matchup factor comes from outside (composite), defaulting to 1.0
        
        raw_env_mult = pace_factor * opportunity_factor * rebound_env_factor * long_reb_factor * matchup_factor
        
        # Rest/Venue (Applied to Base or Env? Let's apply to Env so it gets clamped)
        # Modified Rest Logic:
        # Player B2B (rest=0) -> -3%; opponent B2B -> +1%.
        venue_mult = 1.01 if home_game else 0.99
        
        rest_mult = 1.0
        if days_rest == 0: rest_mult *= 0.97
        if opp_days_rest == 0: rest_mult *= 1.01
        
        raw_global_mult = raw_env_mult * venue_mult * rest_mult
        
        # Correlated pace/miss/allowed inputs otherwise compound the same game
        # environment more than once. Shrink the combined deviation toward neutral.
        final_env_mult = max(0.90, min(1.10, 1.0 + (raw_global_mult - 1.0) * 0.65))
        
        # --- Layer 3: Soft Team Cap (Cannibalization) ---
        cannibalize_mult = self.get_cannibalization_factor(
            p_stats['team_id'], opponent_abbrev, player_id,
            current_proj_minutes=proj_minutes, as_of_date=as_of_date,
        )
        final_env_mult = max(0.88, min(1.12, final_env_mult * cannibalize_mult))
        
        final_projection = base_rebs * final_env_mult

        safety = _projection_safety_context(self.loader, as_of_date)
        historical_mode = safety['historical_mode']
        limitations = safety['limitations']
        injury_freshness = safety['injury_freshness']
        prediction_eligible = safety['prediction_eligible']
        live_injuries_applied = safety['injury_status_acceptable']
        data_freshness = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'as_of_date': as_of_date,
            'nba_stats_cutoff': p_stats.get('data_cutoff'),
            'season': (
                current_season(_parse_as_of_date(as_of_date))
                if as_of_date else getattr(self.loader, 'season', None)
            ),
            'injuries': injury_freshness,
            'projection_inputs': safety['data_sources'],
            'injury_status_acceptable': safety['injury_status_acceptable'],
            'prediction_eligible': prediction_eligible,
            'limitations': list(limitations),
        }

        return {
            'player': p_stats['player_name'],
            'team_id': p_stats['team_id'],
            'team_abbreviation': p_stats.get('team_abbreviation'),
            'team': p_stats.get('team_abbreviation'),
            'projection': round(final_projection, 2),
            'components': {
                'Base Rebs': round(base_rebs, 2),
                'Base Minutes': round(base_minutes, 1),
                'Proj Minutes': round(proj_minutes, 1),
                'Env Mult (Final)': round(final_env_mult, 2),
                'Raw Mult': round(raw_global_mult, 2),
                'Pace': round(pace_factor, 2),
                'Opp': round(opportunity_factor, 2),
                'Miss Matchup': round(opportunity_factor, 2),
                # DvP remains as a deprecated UI alias; this is team-level data.
                'DvP': round(rebound_env_factor, 2),
                'Opp Rebound Environment': round(rebound_env_factor, 2),
                'Matchup': round(matchup_factor, 2),
                'Blowout': blowout_risk_label,
                'DNP Rate': round(p_stats.get('dnp_rate', 0.0), 2),
            },
            'modifiers': {
                'blowout_risk': blowout_risk_label,
                'minutes': round(proj_minutes, 1),
                'injury_note': ', '.join(injury_details['out_teammates']) or None,
                'player_status': injury_details['player_status'],
                'injury_minutes_added': injury_details['minutes_added'],
            },
            'metadata': {
                'as_of_date': as_of_date,
                'data_cutoff': p_stats.get('data_cutoff'),
                'historical_mode': historical_mode,
                'live_injuries_applied': live_injuries_applied,
                'injury_status_acceptable': safety['injury_status_acceptable'],
                'projection_inputs': safety['data_sources'],
                'prediction_eligible': prediction_eligible,
                'limitations': list(limitations),
                'opponent_rebound_source': env.get('opponent_rebound_source'),
                'rebound_environment_baseline': (
                    'opponent per-game rebounds normalized to league-average pace'
                ),
                'is_position_level_dvp': False,
                'pace_baseline': 'player team season pace',
                'miss_baseline': 'player team offense/defense shooting profile',
                'trend_order': p_stats.get('trend_order'),
                'team_source': p_stats.get('team_source'),
                'rate_sample_size': p_stats.get('rate_sample_size'),
                'variance_sample_size': p_stats.get('variance_sample_size'),
                'recency_weights': {
                    'season': round(w_season, 3),
                    'recent': round(w_recent, 3),
                    'opponent_history': round(w_opp, 3),
                },
            },
            'data_freshness': data_freshness,
        }

    def compute_composite_projection(self, player_id, opponent_abbrev, spread=0, manual_minutes=None, home_game=True, days_rest=1, opp_days_rest=1, matchup_player=None, as_of_date=None):
        """
        Higher-order method that incorporates individual matchup player scouting 
        and environment context. Calculates matchup factor acting as input to core projection.
        """
        if as_of_date is not None:
            try:
                _parse_as_of_date(as_of_date)
            except (TypeError, ValueError):
                return {'error': 'as_of_date must use YYYY-MM-DD format'}
        if not isinstance(opponent_abbrev, str) or not re.fullmatch(r'[A-Za-z]{3}', opponent_abbrev.strip()):
            return {'error': 'opponent must be a three-letter NBA abbreviation'}

        # 1. Prelim: Get Player Info
        p_info = self.get_player_stats(player_id, as_of_date=as_of_date)
        if not p_info: return {'error': 'Player not found'}
        pos = p_info['position']
        
        # 2. Matchup Player Identification (Auto-find if not provided)
        opp_id = self.loader.get_team_id(opponent_abbrev)
        if not opp_id:
            return {'error': 'Opponent team not found'}
        m_pid = None
        m_note = None
        if matchup_player:
            m_pid = self.loader.get_player_id(matchup_player)
            if not m_pid:
                return {'error': 'Matchup player not found'}
            # A manual matchup must actually belong to the opponent roster.
            roster_kwargs = {}
            if as_of_date and hasattr(self.loader, '_as_of_context'):
                roster_kwargs['season'] = self.loader._as_of_context(as_of_date)[0]
            try:
                opponent_roster = self.loader.get_team_roster(opp_id, **roster_kwargs)
            except Exception:
                return {'error': 'Opponent roster is unavailable; matchup player cannot be verified'}
            if (
                opponent_roster.empty
                or 'PLAYER_ID' not in opponent_roster.columns
                or m_pid not in set(opponent_roster['PLAYER_ID'].tolist())
            ):
                return {'error': 'Matchup player is not on the opponent roster'}
            if _uses_live_injuries(as_of_date):
                injury_report = self.loader.get_injury_report()
                norm_name = normalize_name(matchup_player)
                status = injury_report.get(norm_name, 'Active')
                m_note = None if status == 'Active' else status
        else:
            # Find Who they are likely guarding (Minute-proximate match)
            target_min = p_info.get('season_min_avg', 30.0)
            matchup_kwargs = {'target_minutes': target_min}
            if as_of_date is not None:
                matchup_kwargs['as_of'] = as_of_date
            try:
                matchup_data = self.loader.get_likely_opponent_matchup(opp_id, pos, **matchup_kwargs)
            except Exception as exc:
                log.warning(f"Direct matchup lookup unavailable; using neutral adjustment: {exc}")
                matchup_data = None
            if matchup_data:
                m_pid = matchup_data['player_id']
                matchup_player = matchup_data['player_name']
                m_note = matchup_data.get('injury_note')

        # 3. Scouting Logic (Rebound PCT + Box Outs) -> Calculate Matchup Factor
        final_adjustment = 1.0
        matchup_context = "Neutral"
        
        if m_pid:
            # 1. Fetch Deep Stats
            def optional_frame(method, *args, **kwargs):
                try:
                    return method(*args, **kwargs)
                except Exception as exc:
                    log.debug(f"Optional matchup source unavailable: {exc}")
                    return pd.DataFrame()

            m_adv = optional_frame(
                _with_as_of, self.loader.get_player_advanced_stats, m_pid,
                as_of_date=as_of_date,
            )
            m_hustle = optional_frame(
                _with_as_of, self.loader.get_player_hustle_stats, m_pid,
                as_of_date=as_of_date,
            )
            m_pt = optional_frame(
                _with_as_of, self.loader.get_player_rebounding_tracking_stats, m_pid,
                as_of_date=as_of_date,
            )
            m_info = optional_frame(self.loader.get_common_player_info, m_pid)
            
            # Matchup Position
            m_pos = 'F'
            if not m_info.empty:
                m_pos_str = m_info.iloc[0].get('POSITION', 'Unknown')
                m_pos = _normalize_position(m_pos_str)

            # Position Calibration
            calibs = {
                'C': {'reb_pct': 0.16, 'chance_pct': 0.60, 'contest_pct': 0.45},
                'F': {'reb_pct': 0.11, 'chance_pct': 0.50, 'contest_pct': 0.35},
                'G': {'reb_pct': 0.08, 'chance_pct': 0.45, 'contest_pct': 0.25}
            }
            c = calibs.get(m_pos, calibs['F'])
            
            scout_factors = []
            
            # A: Dominance
            if not m_adv.empty and 'REB_PCT' in m_adv.columns:
                val = _finite_float(m_adv['REB_PCT'].iloc[0], None, minimum=0)
                if val is None:
                    val = c['reb_pct']
                if val > 1.0: val /= 100.0
                mod = 1.0 - (val - c['reb_pct']) * 0.5
                scout_factors.append(max(0.94, min(1.06, mod)))
            
            # B: Efficiency
            if not m_pt.empty and 'REB_CHANCE_PCT_ADJ' in m_pt.columns:
                val = _finite_float(m_pt['REB_CHANCE_PCT_ADJ'].iloc[0], c['chance_pct'], minimum=0)
                if val > 1.0: val /= 100.0
                mod = 1.0 - (val - c['chance_pct']) * 0.2
                scout_factors.append(max(0.96, min(1.04, mod)))

            if not m_pt.empty and 'REB_CONTEST_PCT' in m_pt.columns:
                # C: Toughness
                val = _finite_float(m_pt['REB_CONTEST_PCT'].iloc[0], c['contest_pct'], minimum=0)
                if val > 1.0: val /= 100.0
                mod = 1.0 - (val - c['contest_pct']) * 0.2
                scout_factors.append(max(0.96, min(1.04, mod)))

            # D: Physicality
            if not m_hustle.empty and 'BOX_OUTS' in m_hustle.columns:
                # Loader requests PerGame, so do not divide this value by GP again.
                val = _finite_float(m_hustle['BOX_OUTS'].iloc[0], 0.0, minimum=0)
                box_target = 2.5 if m_pos == 'C' else 1.0
                mod = 1.0 - (val - box_target) * 0.01
                scout_factors.append(max(0.96, min(1.04, mod)))
            
            # Combine Factors
            if scout_factors:
                raw_matchup = float(np.mean(scout_factors))
                final_adjustment = max(0.97, min(1.03, 1.0 + (raw_matchup - 1.0) * 0.60))
            
            # Narrative
            reasons = []
            if final_adjustment <= 0.975:
                strength = "Elite"
                if not m_pt.empty and 'REB_CONTEST_PCT' in m_pt.columns:
                    c_pct = m_pt['REB_CONTEST_PCT'].iloc[0]
                    if c_pct > 1.0: c_pct /= 100.0
                    if c_pct > c['contest_pct'] + 0.1: reasons.append("Tough Finisher")
            elif final_adjustment < 0.99:
                strength = "Difficult"
            elif final_adjustment >= 1.025:
                strength = "Weak"
            elif final_adjustment > 1.01:
                strength = "Soft"
            else:
                strength = "Standard"
                
            status_tag = f" [{m_note}]" if m_note else ""
            matchup_context = f"{strength} ({matchup_player}){status_tag}".strip()

        # 4. EXECUTE BASE PROJECTION WITH MATCHUP FACTOR
        proj_result = self.compute_projection(
            player_id, 
            opponent_abbrev, 
            spread, 
            manual_minutes, 
            home_game, 
            days_rest,
            opp_days_rest=opp_days_rest,
            matchup_factor=final_adjustment,
            as_of_date=as_of_date,
        )
        
        if 'error' in proj_result: return proj_result

        # Add context to result
        proj_result['matchup_context'] = matchup_context
        # Start populating 'modifiers' if missing
        if 'modifiers' not in proj_result: proj_result['modifiers'] = {}
        proj_result['modifiers']['matchup_player_adj'] = round(final_adjustment, 3)
        proj_result['matchup_injury'] = m_note 
        proj_result['team_injury'] = proj_result['modifiers'].get('injury_note')
        
        # Attach Full Injury Lists and Trend
        proj_result['team_injury_list'] = self.get_team_injury_list(p_info['team_id'], as_of_date=as_of_date)
        proj_result['opp_injury_list'] = self.get_team_injury_list(opp_id, as_of_date=as_of_date)
        proj_result['trend_data'] = p_info.get('last_10_games', [])
        # Injury-list collection above may have refreshed the loader metadata.
        # Re-apply the gate so the final composite result cannot retain a stale
        # eligibility decision made before that refresh.
        safety = _projection_safety_context(self.loader, as_of_date)
        freshness = proj_result.setdefault('data_freshness', {})
        metadata = proj_result.setdefault('metadata', {})
        freshness['injuries'] = safety['injury_freshness']
        freshness['projection_inputs'] = safety['data_sources']
        freshness['injury_status_acceptable'] = safety['injury_status_acceptable']
        freshness['prediction_eligible'] = safety['prediction_eligible']
        freshness['limitations'] = list(safety['limitations'])
        metadata['historical_mode'] = safety['historical_mode']
        metadata['live_injuries_applied'] = safety['injury_status_acceptable']
        metadata['injury_status_acceptable'] = safety['injury_status_acceptable']
        metadata['projection_inputs'] = safety['data_sources']
        metadata['prediction_eligible'] = safety['prediction_eligible']
        metadata['limitations'] = list(safety['limitations'])
        
        proj_result['mean_projection'] = proj_result['projection'] # Backwards compat
        
        # Attach variance data for simulation
        proj_result['player_variance'] = {
            'reb_variance': p_info.get('reb_variance'),
            'reb_std': p_info.get('reb_std'),
            'reb_mean': p_info.get('reb_mean'),
            'sample_size': p_info.get('variance_sample_size'),
        }
        
        return proj_result

    def generate_pick_summary(self, proj_data, line=None):
        """
        Generates a deeply analytical, razor-sharp narrative that explicitly tells the user WHY
        the model recommends a specific tier, what factors clashed, and what pushed it over the edge.
        """
        player = proj_data.get('player', 'Unknown')
        proj = proj_data.get('projection', 0.0)
        base_rebs = proj_data.get('components', {}).get('Base Rebs', 0)
        comps = proj_data.get('components', {})
        context = proj_data.get('matchup_context', 'Neutral')
        
        tier = proj_data.get('tier', 'Unknown Tier')
        direction = proj_data.get('direction', 'Unknown Direction')
        confidence = proj_data.get('confidence', 0.0)
        confidence_value = _finite_float(confidence, None, minimum=0, maximum=100)
        ev_value = _finite_float(proj_data.get('ev_roi'), None)
        
        paragraphs = []

        if line is None:
            paragraphs.append(
                f"**Projection only:** The model projects **{player}** for "
                f"**{proj} rebounds**. Add a sportsbook line and side-specific price "
                "to calculate a recommendation and expected value."
            )
        else:
            actionable_tiers = {
                'STRONG PLAY', 'PLAY', 'TREND LEAN', 'LEAN', 'HIGH-VARIANCE LEAN'
            }
            actionable = (
                tier in actionable_tiers
                and direction in {'OVER', 'UNDER'}
                and ev_value is not None
                and confidence_value is not None
            )
            if not actionable:
                p1 = "**Recommendation: NO BET**."
                p1 += f" The model projects **{proj}** rebounds against **{line}**, but the available probability, side-specific price, or sample quality does not justify a wager."
            else:
                p1 = f"**Recommendation: {tier} on the {direction}**."
                conf_frac = confidence_value / 100.0 if confidence_value > 1.0 else confidence_value
                win_perc = round(conf_frac * 100)
                ev_pct = round(ev_value * 100, 1)
                sign = '+' if ev_pct >= 0 else ''
                p1 += f" The model projects **{player}** for **{proj} rebounds**. The selected side has a {win_perc}% win probability and **{sign}{ev_pct}% Expected Value** at the supplied price."
            paragraphs.append(p1)
        
        # 2. The Mathematical Tug-of-War (Environment weights)
        boosts = []
        penalties = []
        
        dvp = comps.get('Opp Rebound Environment', comps.get('DvP', 1.0))
        if dvp >= 1.06: boosts.append(f"a poor opposing rebounding defense (+{int((dvp-1)*100)}% rebs allowed)")
        elif dvp <= 0.94: penalties.append(f"a stout rebounding defense (-{int((1-dvp)*100)}% rebs allowed)")
        
        pace = comps.get('Pace', 1.0)
        if pace >= 1.03: boosts.append("a fast game pace")
        elif pace <= 0.97: penalties.append("a slow game environment")
        
        matchup_adj = comps.get('Matchup', 1.0)
        m_name = context.split('(')[-1].replace(')', '') if '(' in context else 'his direct matchup'
        if matchup_adj <= 0.985: penalties.append(f"a physically tough individual matchup vs {m_name}")
        elif matchup_adj >= 1.015: boosts.append(f"a favorable individual matchup vs {m_name}")
        
        if boosts and penalties:
            p2 = f"**⚖️ The Tug-of-War:** The model had to weigh major negatives (like {penalties[0]}) against strong positives (like {boosts[0]}). Ultimately, the "
            if proj > base_rebs:
                p2 += "positive factors overpowered the limits, raising his expected ceiling beyond the baseline."
            else:
                p2 += "negative environment dragged down his baseline projection and capped his upside."
            paragraphs.append(p2)
        elif boosts:
            paragraphs.append(f"**🚀 Highly Favorable Environment:** The playing environment is uniformly positive, driven primarily by {boosts[0]}.")
        elif penalties:
            paragraphs.append(f"**🧱 Hostile Environment:** The external environment is broadly hostile to rebounding, heavily weighted down by {penalties[0]}.")

        # 3. The Deciding Factor
        decisions = []
        
        # Injury Impact
        injury = proj_data.get('team_injury')
        if injury:
            decisions.append((f"the absence of **{injury}**, which modestly increases available rotation minutes and rebounds.", 100))
            
        # Volatility
        var_data = proj_data.get('player_variance', {})
        if var_data and var_data.get('reb_mean', 0) > 0:
            fano = var_data['reb_variance'] / var_data['reb_mean']
            if fano > 2.2 and 'AVOID' in tier:
                decisions.append((f"the player's extreme game-to-game inconsistency (a boom-or-bust nature). The Monte Carlo simulation generated wildly unpredictable outcomes, ruining the safety of the play.", 90))
            elif fano < 1.3 and fano > 0.1 and tier in ['PLAY', 'STRONG PLAY', 'SAFE PLAY']:
                decisions.append((f"his remarkable rebounding consistency. The simulation grouped very tightly around the mean, offering an extremely safe mathematical floor.", 85))
                
        # Hot Streak
        trend = proj_data.get('trend_data', [])
        if len(trend) >= 4:
            # Trend payload is chronological (oldest -> newest).
            last_n = [g['rebounds'] for g in trend[-min(5, len(trend)):]]
            avg_last_n = sum(last_n) / len(last_n) if last_n else 0
            if avg_last_n >= proj + 1.5:
                decisions.append((f"a recent hot stretch (averaging {avg_last_n:.1f} rebounds), partially weighted into the projection with small-sample shrinkage.", 80))
            elif avg_last_n <= proj - 1.5:
                decisions.append((f"a recent cold stretch (averaging {avg_last_n:.1f} rebounds), partially weighted into the projection with small-sample shrinkage.", 80))

        if decisions:
            # Sort by priority score (index 1)
            decisions.sort(key=lambda x: x[1], reverse=True)
            top_reason = decisions[0][0]
            paragraphs.append(f"**🎯 The Deciding Factor:** Beyond the environment, the primary variable locking in this {tier} is {top_reason}")
            
        return "\n\n".join(paragraphs)

if __name__ == "__main__":
    # Example Usage
    # loader = NBADataLoader()
    # eng = FeatureEngineer(loader)
    # proj = eng.compute_composite_projection(pid, "BOS", spread=-14.5, home_game=True, days_rest=1)
    pass
