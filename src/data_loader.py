import pandas as pd
from nba_api.stats.endpoints import playergamelog, teamgamelog, leaguedashteamstats, commonplayerinfo, boxscoretraditionalv2, shotchartdetail, cumestatsteam, leaguedashplayerstats
import time

def normalize_name(name):
    try:
        from unidecode import unidecode
    except ImportError:
        def unidecode(s): return s
    return unidecode(name).lower().replace('.', '').strip()

import random

# A robust list of valid User-Agents to rotate
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
]

# Base headers
def get_random_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Referer': 'https://www.nba.com/',
        'Accept': 'application/json, text/plain, */*',
        'x-nba-stats-origin': 'stats',
        'x-nba-stats-token': 'true',
        'Origin': 'https://www.nba.com',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
    }

class NBADataLoader:
    def __init__(self, season='2025-26'):
        self.season = season
        # Simple in-memory cache to avoid spamming API during dev
        self._cache = {}
        self.leaguedashplayerstats = leaguedashplayerstats
        self._load_offline_cache()

    def _load_offline_cache(self):
        """Loads data from the daily JSON cache if it's fresh enough."""
        import os
        import json
        import time
        cache_file = 'data/nba_cache.json'
        
        if not os.path.exists(cache_file):
            return

        try:
            file_mod_time = os.path.getmtime(cache_file)
            hours_old = (time.time() - file_mod_time) / 3600
            
            # If the cache is too old, we let the live API take over or trigger a background refresh
            if hours_old > 12:
                print("DEBUG: Offline cache is stale (>12 hours). Will rely on live API.")
                return
                
            with open(cache_file, 'r') as f:
                data = json.load(f)
                
            if data['season'] != self.season:
                return

            print("DEBUG: Loaded offline cache successfully!", flush=True)
            cache = data['data']
            
            # Map the JSON arrays back to Pandas DataFrames in our memory cache
            keys_to_map = [
                'league_player_stats_advanced', 'league_player_stats_base',
                'league_team_stats_advanced', 'league_opponent_stats',
                'league_hustle_stats', 'league_rebounding_tracking'
            ]
            
            for key in keys_to_map:
                if key in cache:
                    self._cache[f"{key}_{self.season}"] = pd.DataFrame(cache[key])
                    
            # Load rosters
            if 'rosters' in cache:
                for team_id, roster_data in cache['rosters'].items():
                    self._cache[f"roster_{team_id}_{self.season}"] = pd.DataFrame(roster_data)

        except Exception as e:
            print(f"DEBUG: Failed to load offline cache: {e}", flush=True)

    def _get_from_cache(self, key):
        return self._cache.get(key)

    def _set_cache(self, key, value):
        self._cache[key] = value

    def _retry_api_call(self, api_func, max_retries=3, **kwargs):
        """Retry wrapper for nba_api calls with backoff."""
        func_name = api_func.__name__ if hasattr(api_func, '__name__') else str(api_func)
        for attempt in range(max_retries):
            try:
                # Add delay and jitter to avoid patterns
                delay = 1.0 + (attempt * 1.5) + random.uniform(0.1, 0.5)
                time.sleep(delay)
                
                # Use fresh headers every attempt to rotate User-Agent
                headers = get_random_headers()
                
                return api_func(**kwargs, headers=headers, timeout=30)
            except Exception as e:
                print(f"DEBUG: API attempt {attempt+1}/{max_retries} for {func_name} failed: {e}", flush=True)
                if attempt == max_retries - 1:
                    raise

    def get_player_id(self, player_name):
        from nba_api.stats.static import players
        try:
            from unidecode import unidecode
        except ImportError:
            # simple fallback if unidecode fails or not installed?
            def unidecode(s): return s
            
        nba_players = players.get_players()
        normalized_query = unidecode(player_name).lower()

        for player in nba_players:
            normalized_player = unidecode(player['full_name']).lower()
            if normalized_player == normalized_query:
                return player['id']
        
        # Fallback: Check if name is in full_name
        for player in nba_players:
             normalized_player = unidecode(player['full_name']).lower()
             if normalized_query in normalized_player:
                 print(f"Partial match found: {player['full_name']} for {player_name}")
                 return player['id']

        print(f"Player {player_name} not found in static list.")
        return None

    def get_team_id(self, team_abbreviation):
        from nba_api.stats.static import teams
        nba_teams = teams.get_teams()
        for team in nba_teams:
            if team['abbreviation'] == team_abbreviation:
                return team['id']
        return None

    def get_player_gamelog(self, player_id):
        """Fetches game log for a specific player."""
        key = f"player_log_{player_id}_{self.season}"
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)
        
        log = self._retry_api_call(
            playergamelog.PlayerGameLog,
            player_id=player_id, season=self.season
        )
        df = log.get_data_frames()[0]
        self._set_cache(key, df)
        return df

    def get_team_gamelog(self, team_id):
        """Fetches game log for a specific team."""
        key = f"team_log_{team_id}_{self.season}"
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)

        log = self._retry_api_call(
            teamgamelog.TeamGameLog,
            team_id=team_id, season=self.season
        )
        df = log.get_data_frames()[0]
        self._set_cache(key, df)
        return df

    def get_team_stats(self):
        """Fetches current season stats (Base) for all teams"""
        key = f"league_team_stats_base_{self.season}"
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)

        stats = self._retry_api_call(
            leaguedashteamstats.LeagueDashTeamStats,
            season=self.season
        )
        df = stats.get_data_frames()[0]
        self._set_cache(key, df)
        return df
    
    def get_team_advanced_stats(self):
        """Fetches Advanced stats (Pace, OffRtg, etc)"""
        key = f"league_team_stats_advanced_{self.season}"
        if self._get_from_cache(key) is not None:
             return self._get_from_cache(key)
        
        stats = self._retry_api_call(
            leaguedashteamstats.LeagueDashTeamStats,
            season=self.season, measure_type_detailed_defense='Advanced'
        )
        df = stats.get_data_frames()[0]
        self._set_cache(key, df)
        return df
    
    def get_opponent_stats_per_game(self):
        """
        Gets stats AGAINST teams (Opponent FG%, Rebounds Allowed, etc).
        """
        key = f"league_opponent_stats_{self.season}"
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)

        try:
            stats = self._retry_api_call(
                leaguedashteamstats.LeagueDashTeamStats,
                season=self.season, measure_type_detailed_defense='Opponent'
            )
        except Exception as e:
            print(f"Error fetching opponent stats: {e}")
            stats = self._retry_api_call(
                leaguedashteamstats.LeagueDashTeamStats,
                season=self.season
            )
            
        df = stats.get_data_frames()[0]
        self._set_cache(key, df)
        return df
    
    def get_player_shot_chart(self, player_id, team_id):
        """Useful for shot profile"""
        key = f"shot_chart_{player_id}_{self.season}"
        if self._get_from_cache(key) is not None:
             return self._get_from_cache(key)
        
        shots = self._retry_api_call(
            shotchartdetail.ShotChartDetail,
            player_id=player_id, team_id=team_id, season_nullable=self.season, context_measure_simple='FGA'
        )
        df = shots.get_data_frames()[0]
        self._set_cache(key, df)
        return df

    def get_common_player_info(self, player_id):
        print(f"DEBUG: Getting info for player {player_id}", flush=True)
        key = f"common_info_{player_id}"
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)
        
        info = self._retry_api_call(
            commonplayerinfo.CommonPlayerInfo,
            player_id=player_id
        )
        df = info.get_data_frames()[0]
        self._set_cache(key, df)
        return df

    def get_team_roster(self, team_id):
        """Fetches current roster for a team"""
        from nba_api.stats.endpoints import commonteamroster
        key = f"roster_{team_id}_{self.season}"
        if self._get_from_cache(key) is not None:
             return self._get_from_cache(key)
        
        roster = self._retry_api_call(
            commonteamroster.CommonTeamRoster,
            team_id=team_id, season=self.season
        )
        df = roster.get_data_frames()[0]
        self._set_cache(key, df)
        return df

    def get_player_advanced_stats(self, player_id):
        """Fetches Advanced stats (REB_PCT etc) for a player"""
        # Check if we have the full league data cached already
        league_key = f"league_player_stats_advanced_{self.season}"
        df = self._get_from_cache(league_key)
        
        if df is None:
            from nba_api.stats.endpoints import leaguedashplayerstats
            stats = self._retry_api_call(
                leaguedashplayerstats.LeagueDashPlayerStats,
                season=self.season, 
                measure_type_detailed_defense='Advanced'
            )
            df = stats.get_data_frames()[0]
            self._set_cache(league_key, df)
        
        # Filter for this player
        player_row = df[df['PLAYER_ID'] == player_id]
        return player_row

    def get_player_hustle_stats(self, player_id):
        """Fetches Hustle stats (BOX_OUTS etc) for a player"""
        league_key = f"league_hustle_stats_{self.season}"
        df = self._get_from_cache(league_key)
        
        if df is None:
            from nba_api.stats.endpoints import leaguehustlestatsplayer
            stats = self._retry_api_call(
                leaguehustlestatsplayer.LeagueHustleStatsPlayer,
                season=self.season
            )
            df = stats.get_data_frames()[0]
            self._set_cache(league_key, df)
            
        player_row = df[df['PLAYER_ID'] == player_id]
        return player_row

    def get_player_rebounding_tracking_stats(self, player_id):
        """Fetches Rebounding Tracking stats (Contested %, Chance %, etc)"""
        league_key = f"league_rebounding_tracking_{self.season}"
        df = self._get_from_cache(league_key)
        
        if df is None:
            from nba_api.stats.endpoints import leaguedashptstats
            try:
                stats = self._retry_api_call(
                    leaguedashptstats.LeagueDashPtStats,
                    season=self.season,
                    pt_measure_type='Rebounding',
                    player_or_team='Player'
                )
                df = stats.get_data_frames()[0]
                self._set_cache(league_key, df)
            except Exception as e:
                print(f"DEBUG: Failed to fetch rebounding tracking stats: {e}", flush=True)
                import pandas as pd
                return pd.DataFrame()
            
        player_row = df[df['PLAYER_ID'] == player_id]
        return player_row

    def get_injury_report(self):
        """
        Fetches the current NBA injury report from CBS Sports and ESPN.
        """
        key = "live_injury_report"
        if self._get_from_cache(key):
            return self._get_from_cache(key)
            
        import requests
        from bs4 import BeautifulSoup
        
        injuries = {}

        # --- CBS SPORTS ---
        print("DEBUG: Fetching CBS Injuries...", flush=True)
        try:
            url = "https://www.cbssports.com/nba/injuries/"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            rows = soup.find_all('tr')
            print(f"DEBUG: CBS Rows found: {len(rows)}", flush=True)
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 5:
                    long_name = row.find('span', class_='CellPlayerName--long')
                    if long_name:
                        name = long_name.get_text(strip=True)
                    else:
                        name = cols[0].get_text(strip=True)
                        
                    status = cols[4].get_text(strip=True)
                    injuries[normalize_name(name)] = status
        except Exception as e:
            print(f"Warning: Could not fetch from CBS: {e}", flush=True)

        # --- ESPN ---
        print("DEBUG: Fetching ESPN Injuries...", flush=True)
        try:
            url = "https://www.espn.com/nba/injuries"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            rows = soup.find_all('tr', class_='Table__TR') # Note: ESPN classes change often
            if len(rows) == 0:
                 # Fallback for Table structure changes
                 rows = soup.find_all('tr')
            
            print(f"DEBUG: ESPN Rows found: {len(rows)}", flush=True)
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    name_link = cols[0].find('a')
                    name = name_link.get_text(strip=True) if name_link else cols[0].get_text(strip=True)
                    status = cols[3].get_text(strip=True)
                    # Use a normalized key, but preserve status accuracy
                    norm_name = normalize_name(name)
                    if norm_name not in injuries or injuries[norm_name] == 'Active':
                        injuries[norm_name] = status
        except Exception as e:
            print(f"Warning: Could not fetch from ESPN: {e}", flush=True)
            
        print(f"DEBUG: Total Injuries Found: {len(injuries)}", flush=True)
        self._set_cache(key, injuries)
        return injuries

    def get_likely_opponent_matchup(self, opponent_team_id, position, target_minutes=None):
        """
        Attempts to find the likely opponent player at a given position.
        If target_minutes is provided, it finds the player whose playing time 
        most closely matches the target (Starters vs Starters, Bench vs Bench).
        """
        roster = self.get_team_roster(opponent_team_id)
        if roster.empty:
            return None
            
        # Get advanced stats for all player on roster to find starters (by MIN)
        league_adv_key = f"league_player_stats_advanced_{self.season}"
        league_adv = self._get_from_cache(league_adv_key)
        
        if league_adv is None:
            # Trigger a fetch
            self.get_player_advanced_stats(0) # Logic in that method will fetch all and cache
            league_adv = self._get_from_cache(league_adv_key)

        if league_adv is None: return None

        # Merge roster with league stats to get minutes and positions
        roster_stats = pd.merge(roster, league_adv[['PLAYER_ID', 'MIN']], on='PLAYER_ID', how='inner')
        
        # Filter out injured players
        injury_report = self.get_injury_report()

        def check_status(name):
            norm_name = normalize_name(name)
            status = injury_report.get(norm_name, 'Active')
            status_low = status.lower()
            
            # Expanded Keywords for "Out"
            if any(k in status_low for k in ['out', 'inactive', 'injured', 'nwt', 'ruled out']):
                return 'Out'
            
            # Expanded Keywords for "Day-to-Day"
            if any(k in status_low for k in ['questionable', 'day-to-day', 'gtd', 'game time decision', 'doubtful']):
                return 'Day-to-Day'
                
            return 'Active'
            
        roster_stats['injury_status'] = roster_stats['PLAYER'].apply(check_status)
        
        # Filter out players who are OUT
        roster_stats = roster_stats[roster_stats['injury_status'] != 'Out']
        
        # Position matching priority:
        # 1. Exact match (e.g. 'C' == 'C')
        # 2. Contains match (e.g. 'C' in 'C-F')
        
        def score_match(player_pos, target_pos):
            # 1. Perfect Match
            if player_pos == target_pos: return 100
            
            # 2. Strong Hybrid (e.g. C-F matching C)
            # High 90s score ensures we treat hybrid bigs/guards almost as exact matches
            if player_pos.startswith(target_pos): return 95
            if target_pos in player_pos: return 90
            
            # 3. Positional Groupings (Bigs vs Bigs, Guards vs Guards)
            # We treat any Big (F or C) as a solid match for another Big
            target_is_big = any(p in target_pos for p in ['F', 'C'])
            player_is_big = any(p in player_pos for p in ['F', 'C'])
            if target_is_big and player_is_big: return 80
            
            target_is_guard = 'G' in target_pos
            player_is_guard = 'G' in player_pos
            if target_is_guard and player_is_guard: return 80
            
            return 0
            
        roster_stats['match_score'] = roster_stats['POSITION'].apply(lambda x: score_match(x, position))
        
        # Filter by those who can play the position (Score > 0)
        # We now accept anything with a score >= 80 as a primary candidate
        pos_match = roster_stats[roster_stats['match_score'] >= 80].copy()
        
        if pos_match.empty:
            # Fallback to any positive match
            pos_match = roster_stats[roster_stats['match_score'] > 0].copy()

        if pos_match.empty:
            return None
            
        # Select best match:
        # We want to find the player with the best combination of match_score and rotation status.
        # A rotation player (15+ min) who is a "Good" (80) match is better than 
        # a deep bench player (<10 min) who is an "Exact" (100) match.
        
        if target_minutes is not None:
            # Calculate a 'Depth Score' based on minutes relative to target
            # Weight positional score highly but allow minutes to be the tie-breaker/differentiator
            pos_match['depth_penalty'] = (pos_match['MIN'] - target_minutes).abs() * 0.5
            pos_match['final_score'] = pos_match['match_score'] - pos_match['depth_penalty']
            
            # Additional penalty for very low minute players if the target is a starter
            if target_minutes > 24:
                pos_match.loc[pos_match['MIN'] < 15, 'final_score'] -= 30
                pos_match.loc[pos_match['MIN'] < 8, 'final_score'] -= 50

            pos_match = pos_match.sort_values(by='final_score', ascending=False)
            likely_starter = pos_match.iloc[0]
        else:
            likely_starter = pos_match.sort_values(by=['match_score', 'MIN'], ascending=[False, False]).iloc[0]
        
        return {
            'player_id': likely_starter['PLAYER_ID'],
            'player_name': likely_starter['PLAYER'],
            'injury_note': likely_starter['injury_status']
        }

    def get_days_rest(self, team_id):
        """
        Calculates days since the last game for a team.
        Returns 0 if played yesterday (B2B), 1 if played 2 days ago, etc.
        For simplicity/robustness, we check the date of the last game in the gamelog.
        """
        logs = self.get_team_gamelog(team_id)
        if logs.empty:
            return 3 # Default to rested if no logs

        # Get last game date
        last_game_date_str = logs.iloc[0]['GAME_DATE'] # Format: "JAN 20, 2026" or "2026-01-20"
        
        try:
            from datetime import datetime
            # nba_api often uses "JAN 20, 2026"
            try:
                last_date = datetime.strptime(last_game_date_str, "%b %d, %Y")
            except ValueError:
                # Try ISO format
                last_date = datetime.strptime(last_game_date_str, "%Y-%m-%d")
                
            # Compare to "Today" (simulated or real)
            # For this app, we assume "Run Time" is "Today"
            today = datetime.now()
            
            delta = today - last_date
            days_diff = delta.days
            
            # days_diff = 1 means they played yesterday (Today is 21st, Game was 20th) -> 0 Days Rest
            # days_diff = 2 means they played day before yesterday -> 1 Day Rest
            
            rest = max(0, days_diff - 1)
            print(f"DEBUG: Team {team_id} Last Game: {last_game_date_str} -> {days_diff} days ago -> {rest} days rest")
            return rest
            
        except Exception as e:
            print(f"Error calculating rest: {e}")
            return 1 # Default

    def get_games_for_date(self, date_str):
        """
        Get games for a specific date (YYYY-MM-DD).
        Always uses ScoreboardV2 with the explicit date string to guarantee
        the correct slate regardless of time-of-day or timezone.
        """
        key = f"games_{date_str}"
        cached = self._get_from_cache(key)
        if cached: return cached
        
        try:
            from nba_api.stats.endpoints import scoreboardv2
            
            games = []
            seen_game_ids = set()
            
            print(f"DEBUG: Fetching games for {date_str} via ScoreboardV2...", flush=True)
            
            # Use retry logic to handle rate-limiting
            for attempt in range(3):
                try:
                    board = scoreboardv2.ScoreboardV2(
                        game_date=date_str,
                        timeout=15
                    )
                    
                    games_dict = board.game_header.get_dict()
                    headers = games_dict['headers']
                    rows = games_dict['data']
                    
                    def get_col(row, col_name):
                        try:
                            idx = headers.index(col_name)
                            return row[idx]
                        except ValueError:
                            return None
                    
                    for row in rows:
                        gid = get_col(row, 'GAME_ID')
                        if gid in seen_game_ids:
                            continue
                        seen_game_ids.add(gid)
                        
                        hid = get_col(row, 'HOME_TEAM_ID')
                        vid = get_col(row, 'VISITOR_TEAM_ID')
                        games.append({
                            'game_id': gid,
                            'home_id': hid,
                            'away_id': vid
                        })
                    
                    print(f"DEBUG: ScoreboardV2 found {len(games)} unique games for {date_str}.", flush=True)
                    break  # Success
                    
                except Exception as retry_err:
                    print(f"DEBUG: ScoreboardV2 attempt {attempt+1} failed: {retry_err}", flush=True)
                    if attempt < 2:
                        import time
                        time.sleep(2)
            
            if games:
                self._set_cache(key, games)
            return games

        except Exception as e:
            print(f"Error fetching games for {date_str}: {e}")
            return []

    def get_odds_for_game(self, api_key, home_team_code, away_team_code, date_str, bookmaker='fanduel'):
        """
        Targeted Odds Fetch:
        1. Get ALL events for the date (cheap/free-ish).
        2. Find the event matching the teams.
        3. Get odds ONLY for that event ID (costs quota).
        """
        key = f"odds_{home_team_code}_{away_team_code}_{date_str}_{bookmaker}"
        cached = self._get_from_cache(key)
        if cached: return cached

        import requests
        
        try:
            print(f"DEBUG: Deep-searching odds for {home_team_code} vs {away_team_code} on {bookmaker}...", flush=True)
            
            # 1. Get Events
            # We filter by likely active events.
            events_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events?apiKey={api_key}&regions=us"
            resp = requests.get(events_url)
            if resp.status_code != 200:
                print(f"Odds API Error (Events): {resp.text}")
                return {}
            
            events = resp.json()
            target_event_id = None
            
            # Helper for loose matching
            # API names: "Boston Celtics", "Los Angeles Lakers"
            # Our codes: "BOS", "LAL"
            
            team_map = {
                'ATL': 'Hawks', 'BOS': 'Celtics', 'BKN': 'Nets', 'CHA': 'Hornets', 'CHI': 'Bulls',
                'CLE': 'Cavaliers', 'DAL': 'Mavericks', 'DEN': 'Nuggets', 'DET': 'Pistons', 'GSW': 'Warriors',
                'HOU': 'Rockets', 'IND': 'Pacers', 'LAC': 'Clippers', 'LAL': 'Lakers', 'MEM': 'Grizzlies',
                'MIA': 'Heat', 'MIL': 'Bucks', 'MIN': 'Timberwolves', 'NOP': 'Pelicans', 'NYK': 'Knicks',
                'OKC': 'Thunder', 'ORL': 'Magic', 'PHI': '76ers', 'PHX': 'Suns', 'POR': 'Trail Blazers',
                'SAC': 'Kings', 'SAS': 'Spurs', 'TOR': 'Raptors', 'UTA': 'Jazz', 'WAS': 'Wizards'
            }
            
            h_name_part = team_map.get(home_team_code, home_team_code)
            a_name_part = team_map.get(away_team_code, away_team_code)

            for event in events:
                e_home = event['home_team']
                e_away = event['away_team']
                
                # Check for match (either side)
                # If "Celtics" in "Boston Celtics"
                if (h_name_part in e_home and a_name_part in e_away) or \
                   (h_name_part in e_away and a_name_part in e_home):
                    target_event_id = event['id']
                    break
            
            if not target_event_id:
                print("DEBUG: No matching Odds Event found.")
                return {}
                
            # 2. Get Props for ID - filtered by selected bookmaker
            print(f"DEBUG: Found Event ID {target_event_id}. Fetching Props from {bookmaker}...", flush=True)
            props_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{target_event_id}/odds?apiKey={api_key}&regions=us&bookmakers={bookmaker}&markets=player_rebounds&oddsFormat=american"
            
            p_resp = requests.get(props_url)
            if p_resp.status_code != 200:
                return {}
            
            props_data = p_resp.json()
            player_props = {}
            bookmakers = props_data.get('bookmakers', [])
            
            # DEBUG: Log available bookmakers
            book_keys = [b.get('key', 'unknown') for b in bookmakers]
            print(f"DEBUG: Available bookmakers: {book_keys}", flush=True)
            
            for book in bookmakers:
                for market in book.get('markets', []):
                    if market['key'] == 'player_rebounds':
                         for outcome in market['outcomes']:
                            if outcome['name'] == 'Over':
                                p_name = outcome['description']
                                line = outcome['point']
                                
                                from unidecode import unidecode
                                norm_p = unidecode(p_name).lower().replace('.', '').strip()
                                
                                player_props[norm_p] = {
                                    'line': line,
                                    'odds': outcome['price'],
                                    'book': book['title']
                                }
            
            self._set_cache(key, player_props)
            return player_props

        except Exception as e:
            print(f"Error fetching odds: {e}")
            return {}
