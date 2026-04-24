import pandas as pd
from nba_api.stats.endpoints import playergamelog, teamgamelog, leaguedashteamstats, commonplayerinfo, boxscoretraditionalv2, shotchartdetail, cumestatsteam, leaguedashplayerstats
import time
import random

from src.utils import normalize_name, get_logger

log = get_logger('data_loader')

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
                log.info("Offline cache is stale (>12 hours). Will rely on live API.")
                return
                
            with open(cache_file, 'r') as f:
                data = json.load(f)
                
            if data['season'] != self.season:
                return

            log.info("Loaded offline cache successfully.")
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
            log.debug(f"Failed to load offline cache: {e}")

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
                log.debug(f"API attempt {attempt+1}/{max_retries} for {func_name} failed: {e}")
                if attempt == max_retries - 1:
                    raise

    def get_player_id(self, player_name):
        from nba_api.stats.static import players

        nba_players = players.get_players()
        normalized_query = normalize_name(player_name)

        for player in nba_players:
            if normalize_name(player['full_name']) == normalized_query:
                return player['id']

        # Fallback: substring match
        for player in nba_players:
            if normalized_query in normalize_name(player['full_name']):
                log.info(f"Partial match found: {player['full_name']} for {player_name}")
                return player['id']

        log.warning(f"Player {player_name} not found in static list.")
        return None

    def get_team_id(self, team_abbreviation):
        from nba_api.stats.static import teams
        nba_teams = teams.get_teams()
        for team in nba_teams:
            if team['abbreviation'] == team_abbreviation:
                return team['id']
        return None

    def get_player_gamelog(self, player_id):
        """Fetches game log for a specific player (Regular Season + Playoffs)."""
        key = f"player_log_{player_id}_{self.season}_combined"
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)

        dfs = []
        try:
            reg_log = self._retry_api_call(
                playergamelog.PlayerGameLog,
                player_id=player_id, season=self.season, season_type_all_star='Regular Season'
            ).get_data_frames()[0]
            if not reg_log.empty:
                dfs.append(reg_log)
        except Exception as e:
            log.warning(f"Failed to fetch regular season logs for player {player_id}: {e}")

        try:
            play_log = self._retry_api_call(
                playergamelog.PlayerGameLog,
                player_id=player_id, season=self.season, season_type_all_star='Playoffs'
            ).get_data_frames()[0]
            if not play_log.empty:
                dfs.append(play_log)
        except Exception as e:
            log.warning(f"Failed to fetch playoff logs for player {player_id}: {e}")

        if dfs:
            df = pd.concat(dfs, ignore_index=True)
            if 'GAME_DATE' in df.columns:
                # nba_api gamelogs typically use 'MMM DD, YYYY' format
                df['GAME_DATE_DT'] = pd.to_datetime(df['GAME_DATE'])
                df = df.sort_values(by='GAME_DATE_DT', ascending=False).drop(columns=['GAME_DATE_DT']).reset_index(drop=True)
        else:
            df = pd.DataFrame()

        self._set_cache(key, df)
        return df

    def get_team_gamelog(self, team_id):
        """Fetches game log for a specific team (Regular Season + Playoffs)."""
        key = f"team_log_{team_id}_{self.season}_combined"
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)

        dfs = []
        try:
            reg_log = self._retry_api_call(
                teamgamelog.TeamGameLog,
                team_id=team_id, season=self.season, season_type_all_star='Regular Season'
            ).get_data_frames()[0]
            if not reg_log.empty:
                dfs.append(reg_log)
        except Exception as e:
            log.warning(f"Failed to fetch regular season logs for team {team_id}: {e}")

        try:
            play_log = self._retry_api_call(
                teamgamelog.TeamGameLog,
                team_id=team_id, season=self.season, season_type_all_star='Playoffs'
            ).get_data_frames()[0]
            if not play_log.empty:
                dfs.append(play_log)
        except Exception as e:
            log.warning(f"Failed to fetch playoff logs for team {team_id}: {e}")

        if dfs:
            df = pd.concat(dfs, ignore_index=True)
            if 'GAME_DATE' in df.columns:
                df['GAME_DATE_DT'] = pd.to_datetime(df['GAME_DATE'])
                df = df.sort_values(by='GAME_DATE_DT', ascending=False).drop(columns=['GAME_DATE_DT']).reset_index(drop=True)
        else:
            df = pd.DataFrame()

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
            log.warning(f"Error fetching opponent stats: {e}")
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
        log.debug(f"Getting info for player {player_id}")
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
                log.debug(f"Failed to fetch rebounding tracking stats: {e}")
                import pandas as pd
                return pd.DataFrame()
            
        player_row = df[df['PLAYER_ID'] == player_id]
        return player_row

    INJURY_DISK_CACHE = 'data/injury_report.json'
    INJURY_CACHE_TTL_SEC = 20 * 60  # 20 minutes
    INJURY_MIN_SANITY_COUNT = 10    # fewer than this → scrape likely broken

    def get_injury_report(self):
        """
        Fetches the current NBA injury report from CBS Sports and ESPN.
        Uses an in-memory cache + 20-min on-disk JSON cache to avoid hammering scrapers.
        Applies a sanity threshold: if the merged scrape returns suspiciously few rows,
        the in-memory cache is populated but the prior disk cache is *not* overwritten,
        so stale-but-real data survives a layout change.
        """
        key = "live_injury_report"
        cached = self._get_from_cache(key)
        if cached is not None:
            return cached

        import json
        import os

        # 1. Try disk cache first.
        disk_injuries = None
        if os.path.exists(self.INJURY_DISK_CACHE):
            try:
                age_sec = time.time() - os.path.getmtime(self.INJURY_DISK_CACHE)
                with open(self.INJURY_DISK_CACHE, 'r') as f:
                    disk_injuries = json.load(f)
                if age_sec < self.INJURY_CACHE_TTL_SEC and disk_injuries:
                    self._set_cache(key, disk_injuries)
                    return disk_injuries
            except Exception as e:
                log.warning(f"Injury disk cache read failed: {e}")

        import requests
        from bs4 import BeautifulSoup

        injuries = {}

        # --- CBS SPORTS ---
        log.debug("Fetching CBS Injuries...")
        try:
            url = "https://www.cbssports.com/nba/injuries/"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.text, 'html.parser')

            rows = soup.find_all('tr')
            log.debug(f"CBS Rows found: {len(rows)}")
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 5:
                    long_name = row.find('span', class_='CellPlayerName--long')
                    name = long_name.get_text(strip=True) if long_name else cols[0].get_text(strip=True)
                    status = cols[4].get_text(strip=True)
                    injuries[normalize_name(name)] = status
        except Exception as e:
            log.warning(f"Could not fetch from CBS: {e}")

        # --- ESPN ---
        log.debug("Fetching ESPN Injuries...")
        try:
            url = "https://www.espn.com/nba/injuries"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.text, 'html.parser')

            rows = soup.find_all('tr', class_='Table__TR')
            if len(rows) == 0:
                rows = soup.find_all('tr')
            log.debug(f"ESPN Rows found: {len(rows)}")

            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    name_link = cols[0].find('a')
                    name = name_link.get_text(strip=True) if name_link else cols[0].get_text(strip=True)
                    status = cols[3].get_text(strip=True)
                    norm_name = normalize_name(name)
                    if norm_name not in injuries or injuries[norm_name] == 'Active':
                        injuries[norm_name] = status
        except Exception as e:
            log.warning(f"Could not fetch from ESPN: {e}")

        log.info(f"Total injuries found: {len(injuries)}")

        # Sanity check: if too few results, the scrape is likely broken.
        # Prefer a stale-but-real disk cache over poisoned empty data.
        if len(injuries) < self.INJURY_MIN_SANITY_COUNT:
            log.warning(
                f"Injury scrape returned only {len(injuries)} entries "
                f"(threshold {self.INJURY_MIN_SANITY_COUNT}). Layout may have changed."
            )
            if disk_injuries:
                log.warning("Falling back to stale disk cache.")
                self._set_cache(key, disk_injuries)
                return disk_injuries
            # No disk fallback: return what we have, but don't clobber the disk cache.
            self._set_cache(key, injuries)
            return injuries

        # Healthy scrape: write disk cache.
        try:
            os.makedirs(os.path.dirname(self.INJURY_DISK_CACHE), exist_ok=True)
            with open(self.INJURY_DISK_CACHE, 'w') as f:
                json.dump(injuries, f)
        except Exception as e:
            log.warning(f"Injury disk cache write failed: {e}")

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

    DEFAULT_DAYS_REST = 2  # Neutral assumption when unknown; keeps rest_mult at 1.0

    def get_days_rest(self, team_id):
        """
        Days since the last game for a team.
        0 = played yesterday (B2B), 1 = played 2 days ago, etc.
        Uses DEFAULT_DAYS_REST (2 = neutral) whenever we can't compute a real value,
        so empty-log and parse-failure paths agree.
        """
        logs = self.get_team_gamelog(team_id)
        if logs.empty:
            return self.DEFAULT_DAYS_REST

        last_game_date_str = logs.iloc[0]['GAME_DATE']
        try:
            from datetime import datetime
            try:
                last_date = datetime.strptime(last_game_date_str, "%b %d, %Y")
            except ValueError:
                last_date = datetime.strptime(last_game_date_str, "%Y-%m-%d")

            days_diff = (datetime.now() - last_date).days
            rest = max(0, days_diff - 1)
            log.debug(f"Team {team_id} last game: {last_game_date_str} -> {days_diff} days ago -> {rest} rest")
            return rest
        except Exception as e:
            log.warning(f"Error calculating rest for team {team_id}: {e}")
            return self.DEFAULT_DAYS_REST

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
            
            log.debug(f"Fetching games for {date_str} via ScoreboardV2...")
            
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
                    
                    log.debug(f"ScoreboardV2 found {len(games)} unique games for {date_str}.")
                    break  # Success
                    
                except Exception as retry_err:
                    log.debug(f"ScoreboardV2 attempt {attempt+1} failed: {retry_err}")
                    if attempt < 2:
                        import time
                        time.sleep(2)
            
            if games:
                self._set_cache(key, games)
            return games

        except Exception as e:
            log.warning(f"Error fetching games for {date_str}: {e}")
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
            log.debug(f"Deep-searching odds for {home_team_code} vs {away_team_code} on {bookmaker}...")
            
            # 1. Get Events
            # We filter by likely active events.
            events_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events?apiKey={api_key}&regions=us"
            resp = requests.get(events_url)
            if resp.status_code != 200:
                log.warning(f"Odds API Error (Events): {resp.text}")
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
                log.debug("No matching Odds Event found.")
                return {}
                
            # 2. Get Props for ID - filtered by selected bookmaker
            log.debug(f"Found Event ID {target_event_id}. Fetching Props from {bookmaker}...")
            props_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{target_event_id}/odds?apiKey={api_key}&regions=us&bookmakers={bookmaker}&markets=player_rebounds&oddsFormat=american"
            
            p_resp = requests.get(props_url)
            if p_resp.status_code != 200:
                return {}
            
            props_data = p_resp.json()
            player_props = {}
            bookmakers = props_data.get('bookmakers', [])
            
            # DEBUG: Log available bookmakers
            book_keys = [b.get('key', 'unknown') for b in bookmakers]
            log.debug(f"Available bookmakers: {book_keys}")
            
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
            log.warning(f"Error fetching odds: {e}")
            return {}
