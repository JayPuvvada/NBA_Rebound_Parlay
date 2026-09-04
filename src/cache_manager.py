import os
import sys

# Add parent directory to path to allow importing src module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import datetime, timezone
import pandas as pd
from src.data_loader import NBADataLoader, _atomic_json_write, _date_to_parameter
from src.utils import current_season, eastern_today

CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'nba_cache.json')
CACHE_EXPIRY_HOURS = 12


def _records(frame):
    """Convert a DataFrame to strict-JSON records (NaN/NaT become null)."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("cache source must be a pandas DataFrame")
    return json.loads(frame.to_json(orient='records', date_format='iso'))

def fetch_and_cache_data():
    """
    Fetches all necessary NBA data for the day and saves it to a local JSON file.
    This prevents the live web server from being rate-limited by stats.nba.com.
    """
    print(f"[{datetime.now()}] Starting daily NBA data cache fetch...")
    
    # Ensure data directory exists
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    
    loader = NBADataLoader()
    cache_as_of = eastern_today()
    date_to = _date_to_parameter(cache_as_of)
    cache_data = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'season': loader.season,
        'as_of_date': cache_as_of,
        'data_through': date_to,
        'data': {}
    }
    
    try:
        # 1. Fetch League Advanced Player Stats
        print("Fetching League Advanced Player Stats...")
        stats_adv = loader._fetch_combined_dashboard(
            loader.leaguedashplayerstats.LeagueDashPlayerStats,
            'advanced player stats', 'PLAYER_ID',
            season=loader.season, 
            measure_type_detailed_defense='Advanced',
            per_mode_detailed='PerGame',
            date_to_nullable=date_to,
        )
        cache_data['data']['league_player_stats_advanced'] = _records(stats_adv)
        
        # 2. Fetch League Basic Player Stats (for MIN)
        print("Fetching League Basic Player Stats...")
        stats_base = loader._fetch_combined_dashboard(
            loader.leaguedashplayerstats.LeagueDashPlayerStats,
            'base player stats', 'PLAYER_ID',
            season=loader.season,
            per_mode_detailed='PerGame',
            date_to_nullable=date_to,
        )
        cache_data['data']['league_player_stats_base'] = _records(stats_base)

        # 3. Fetch Team Base Stats (required by matchup projections)
        print("Fetching League Team Base Stats...")
        from nba_api.stats.endpoints import leaguedashteamstats
        team_stats_base = loader._fetch_combined_dashboard(
            leaguedashteamstats.LeagueDashTeamStats,
            'team base stats', 'TEAM_ID',
            season=loader.season, per_mode_detailed='PerGame',
            date_to_nullable=date_to,
        )
        cache_data['data']['league_team_stats_base'] = _records(team_stats_base)

        # 4. Fetch Team Advanced Stats
        print("Fetching League Team Advanced Stats...")
        team_stats_adv = loader._fetch_combined_dashboard(
            leaguedashteamstats.LeagueDashTeamStats,
            'team advanced stats', 'TEAM_ID',
            season=loader.season, measure_type_detailed_defense='Advanced',
            per_mode_detailed='PerGame', date_to_nullable=date_to,
        )
        cache_data['data']['league_team_stats_advanced'] = _records(team_stats_adv)
        
        # 5. Fetch team-level opponent stats (per game)
        print("Fetching League Opponent Stats...")
        opp_stats = loader._fetch_combined_dashboard(
            leaguedashteamstats.LeagueDashTeamStats,
            'team opponent stats', 'TEAM_ID',
            season=loader.season, measure_type_detailed_defense='Opponent',
            per_mode_detailed='PerGame', date_to_nullable=date_to,
        )
        cache_data['data']['league_opponent_stats'] = _records(opp_stats)

        # 6. Fetch Hustle Stats
        print("Fetching League Hustle Stats...")
        from nba_api.stats.endpoints import leaguehustlestatsplayer
        hustle = loader._fetch_combined_dashboard(
            leaguehustlestatsplayer.LeagueHustleStatsPlayer,
            'player hustle stats', 'PLAYER_ID', games_column='G',
            season=loader.season, per_mode_time='PerGame',
            date_to_nullable=date_to,
        )
        cache_data['data']['league_hustle_stats'] = _records(hustle)

        # 7. Fetch Rebounding Tracking Stats
        print("Fetching League Rebounding Tracking Stats...")
        from nba_api.stats.endpoints import leaguedashptstats
        reb_track = loader._fetch_combined_dashboard(
            leaguedashptstats.LeagueDashPtStats,
            'player rebounding tracking stats', 'PLAYER_ID',
            season=loader.season, pt_measure_type='Rebounding', player_or_team='Player',
            per_mode_simple='PerGame',
            date_to_nullable=date_to,
        )
        cache_data['data']['league_rebounding_tracking'] = _records(reb_track)

        # 8. Fetch Every Team's Roster
        print("Fetching Top 30 Team Rosters...")
        from nba_api.stats.static import teams
        from nba_api.stats.endpoints import commonteamroster
        all_teams = teams.get_teams()
        cache_data['data']['rosters'] = {}
        for count, team in enumerate(all_teams[:30]):
            team_id = team['id']
            print(f"Fetching Roster for team {count+1}/30: {team['full_name']}")
            try:
                roster = loader._retry_api_call(
                    commonteamroster.CommonTeamRoster,
                    team_id=team_id, season=loader.season
                ).get_data_frames()[0]
                cache_data['data']['rosters'][str(team_id)] = _records(roster)
            except Exception as e:
                print(f"Failed to fetch roster for {team['full_name']}: {e}")

        # Save to disk
        print(f"Saving cache to {CACHE_FILE}...")
        NBADataLoader.validate_offline_cache_data(cache_data['data'])
        cache_data['timestamp'] = datetime.now(timezone.utc).isoformat()
        _atomic_json_write(CACHE_FILE, cache_data)
            
        print(f"[{datetime.now()}] Cache successfully built.")
        return True
        
    except Exception as e:
        print(f"[{datetime.now()}] Error building cache: {e}")
        return False

def is_cache_stale():
    """Validate freshness using content timestamp, season, and required datasets."""
    if not os.path.exists(CACHE_FILE):
        return True
    
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
        if payload.get('season') != current_season():
            return True
        if payload.get('as_of_date') != eastern_today():
            return True
        if payload.get('data_through') != _date_to_parameter(eastern_today()):
            return True
        datasets = payload.get('data')
        if not isinstance(datasets, dict):
            return True
        if NBADataLoader.REQUIRED_OFFLINE_DATASETS.difference(datasets):
            return True
        if any(
            not isinstance(datasets.get(key), list) or not datasets.get(key)
            for key in NBADataLoader.REQUIRED_OFFLINE_DATASETS
        ):
            return True
        for key, required_columns in NBADataLoader.REQUIRED_OFFLINE_COLUMNS.items():
            available_columns = set(pd.DataFrame(datasets[key]).columns)
            if required_columns.difference(available_columns):
                return True
        timestamp = datetime.fromisoformat(str(payload.get('timestamp')).replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds() / 3600
        return age_hours < 0 or age_hours > CACHE_EXPIRY_HOURS
    except Exception:
        return True

if __name__ == "__main__":
    fetch_and_cache_data()
