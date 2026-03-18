import os
import sys

# Add parent directory to path to allow importing src module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
from datetime import datetime
import pandas as pd
from src.data_loader import NBADataLoader

CACHE_FILE = 'data/nba_cache.json'
CACHE_EXPIRY_HOURS = 12

def fetch_and_cache_data():
    """
    Fetches all necessary NBA data for the day and saves it to a local JSON file.
    This prevents the live web server from being rate-limited by stats.nba.com.
    """
    print(f"[{datetime.now()}] Starting daily NBA data cache fetch...")
    
    # Ensure data directory exists
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    
    loader = NBADataLoader()
    cache_data = {
        'timestamp': datetime.now().isoformat(),
        'season': loader.season,
        'data': {}
    }
    
    try:
        # 1. Fetch League Advanced Player Stats
        print("Fetching League Advanced Player Stats...")
        stats_adv = loader._retry_api_call(
            loader.leaguedashplayerstats.LeagueDashPlayerStats,
            season=loader.season, 
            measure_type_detailed_defense='Advanced'
        ).get_data_frames()[0]
        cache_data['data']['league_player_stats_advanced'] = stats_adv.to_dict(orient='records')
        
        # 2. Fetch League Basic Player Stats (for MIN)
        print("Fetching League Basic Player Stats...")
        stats_base = loader._retry_api_call(
            loader.leaguedashplayerstats.LeagueDashPlayerStats,
            season=loader.season
        ).get_data_frames()[0]
        cache_data['data']['league_player_stats_base'] = stats_base.to_dict(orient='records')

        # 3. Fetch Team Advanced Stats
        print("Fetching League Team Advanced Stats...")
        from nba_api.stats.endpoints import leaguedashteamstats
        team_stats_adv = loader._retry_api_call(
            leaguedashteamstats.LeagueDashTeamStats,
            season=loader.season, measure_type_detailed_defense='Advanced'
        ).get_data_frames()[0]
        cache_data['data']['league_team_stats_advanced'] = team_stats_adv.to_dict(orient='records')
        
        # 4. Fetch Opponent Stats (for DvP)
        print("Fetching League Opponent Stats...")
        opp_stats = loader._retry_api_call(
            leaguedashteamstats.LeagueDashTeamStats,
            season=loader.season, measure_type_detailed_defense='Opponent'
        ).get_data_frames()[0]
        cache_data['data']['league_opponent_stats'] = opp_stats.to_dict(orient='records')

        # 5. Fetch Hustle Stats
        print("Fetching League Hustle Stats...")
        from nba_api.stats.endpoints import leaguehustlestatsplayer
        hustle = loader._retry_api_call(
            leaguehustlestatsplayer.LeagueHustleStatsPlayer,
            season=loader.season
        ).get_data_frames()[0]
        cache_data['data']['league_hustle_stats'] = hustle.to_dict(orient='records')

        # 6. Fetch Rebounding Tracking Stats
        print("Fetching League Rebounding Tracking Stats...")
        from nba_api.stats.endpoints import leaguedashptstats
        reb_track = loader._retry_api_call(
            leaguedashptstats.LeagueDashPtStats,
            season=loader.season, pt_measure_type='Rebounding', player_or_team='Player'
        ).get_data_frames()[0]
        cache_data['data']['league_rebounding_tracking'] = reb_track.to_dict(orient='records')

        # 7. Fetch Every Team's Roster
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
                cache_data['data']['rosters'][str(team_id)] = roster.to_dict(orient='records')
            except Exception as e:
                print(f"Failed to fetch roster for {team['full_name']}: {e}")

        # Save to disk
        print(f"Saving cache to {CACHE_FILE}...")
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_data, f)
            
        print(f"[{datetime.now()}] Cache successfully built.")
        return True
        
    except Exception as e:
        print(f"[{datetime.now()}] Error building cache: {e}")
        return False

def is_cache_stale():
    """Checks if the cache file is older than 12 hours or doesn't exist."""
    if not os.path.exists(CACHE_FILE):
        return True
    
    try:
        file_mod_time = os.path.getmtime(CACHE_FILE)
        current_time = time.time()
        hours_old = (current_time - file_mod_time) / 3600
        return hours_old > CACHE_EXPIRY_HOURS
    except Exception:
        return True

if __name__ == "__main__":
    fetch_and_cache_data()
