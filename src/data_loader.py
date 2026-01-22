import pandas as pd
from nba_api.stats.endpoints import playergamelog, teamgamelog, leaguedashteamstats, commonplayerinfo, boxscoretraditionalv2, shotchartdetail, cumestatsteam
import time

class NBADataLoader:
    def __init__(self, season='2025-26'):
        self.season = season
        # Simple in-memory cache to avoid spamming API during dev
        self._cache = {}

    def _get_from_cache(self, key):
        return self._cache.get(key)

    def _set_cache(self, key, value):
        self._cache[key] = value

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
        
        time.sleep(0.6) # Rate limit politeness
        log = playergamelog.PlayerGameLog(player_id=player_id, season=self.season)
        df = log.get_data_frames()[0]
        self._set_cache(key, df)
        return df

    def get_team_gamelog(self, team_id):
        """Fetches game log for a specific team."""
        key = f"team_log_{team_id}_{self.season}"
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)

        time.sleep(0.6)
        log = teamgamelog.TeamGameLog(team_id=team_id, season=self.season)
        df = log.get_data_frames()[0]
        self._set_cache(key, df)
        return df

    def get_team_stats(self):
        """Fetches current season stats (Base) for all teams"""
        key = f"league_team_stats_base_{self.season}"
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)

        time.sleep(0.6)
        stats = leaguedashteamstats.LeagueDashTeamStats(season=self.season)
        df = stats.get_data_frames()[0]
        self._set_cache(key, df)
        return df
    
    def get_team_advanced_stats(self):
        """Fetches Advanced stats (Pace, OffRtg, etc)"""
        key = f"league_team_stats_advanced_{self.season}"
        if self._get_from_cache(key) is not None:
             return self._get_from_cache(key)
        
        time.sleep(0.6)
        # Check argument name - usually measure_type_nullable
        stats = leaguedashteamstats.LeagueDashTeamStats(season=self.season, measure_type_detailed_defense='Advanced')
        df = stats.get_data_frames()[0]
        self._set_cache(key, df)
        return df
    
    def get_opponent_stats_per_game(self):
        """
        Gets stats AGAINST teams (Opponent FG%, Rebounds Allowed, etc).
        This is tricky in nba_api, often best derived from summing opponent logs 
        or using specific defense dashboards.
        For simplicity, we will use LeagueDashTeamStats with MeasureType='Opponent'.
        """
        key = f"league_opponent_stats_{self.season}"
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)

        time.sleep(0.6)
        # Try 'Opponent' measure type
        try:
            stats = leaguedashteamstats.LeagueDashTeamStats(season=self.season, measure_type_detailed_defense='Opponent') 
        except Exception as e:
            print(f"Error fetching opponent stats: {e}")
            # Fallback to Base, though it lacks OPP cols
            stats = leaguedashteamstats.LeagueDashTeamStats(season=self.season)
            
        df = stats.get_data_frames()[0]
        self._set_cache(key, df)
        return df
    
    def get_player_shot_chart(self, player_id, team_id):
        """Useful for shot profile (3PA rate, paint attempts - though paint is often easier from dashes)"""
        key = f"shot_chart_{player_id}_{self.season}"
        if self._get_from_cache(key) is not None:
             return self._get_from_cache(key)
        
        time.sleep(0.6)
        shots = shotchartdetail.ShotChartDetail(player_id=player_id, team_id=team_id, season_nullable=self.season, context_measure_simple='FGA')
        df = shots.get_data_frames()[0]
        self._set_cache(key, df)
        return df

    def get_common_player_info(self, player_id):
        key = f"common_info_{player_id}"
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)
        
        time.sleep(0.6)
        info = commonplayerinfo.CommonPlayerInfo(player_id=player_id)
        df = info.get_data_frames()[0]
        self._set_cache(key, df)
        return df

    def get_team_roster(self, team_id):
        """Fetches current roster for a team"""
        from nba_api.stats.endpoints import commonteamroster
        key = f"roster_{team_id}_{self.season}"
        if self._get_from_cache(key) is not None:
             return self._get_from_cache(key)
        
        time.sleep(0.6)
        roster = commonteamroster.CommonTeamRoster(team_id=team_id, season=self.season)
        df = roster.get_data_frames()[0]
        self._set_cache(key, df)
        return df

    def get_player_advanced_stats(self, player_id):
        """Fetches Advanced stats (REB_PCT etc) for a player"""
        # Check if we have the full league data cached already
        league_key = f"league_player_stats_advanced_{self.season}"
        df = self._get_from_cache(league_key)
        
        if df is None:
            time.sleep(0.6)
            from nba_api.stats.endpoints import leaguedashplayerstats
            stats = leaguedashplayerstats.LeagueDashPlayerStats(
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
            time.sleep(0.6)
            from nba_api.stats.endpoints import leaguehustlestatsplayer
            stats = leaguehustlestatsplayer.LeagueHustleStatsPlayer(season=self.season)
            df = stats.get_data_frames()[0]
            self._set_cache(league_key, df)
            
        player_row = df[df['PLAYER_ID'] == player_id]
        return player_row

    def get_player_rebounding_tracking_stats(self, player_id):
        """Fetches Rebounding Tracking stats (Contested %, Chance %, etc)"""
        league_key = f"league_rebounding_tracking_{self.season}"
        df = self._get_from_cache(league_key)
        
        if df is None:
            time.sleep(0.6)
            from nba_api.stats.endpoints import leaguedashptstats
            stats = leaguedashptstats.LeagueDashPtStats(
                season=self.season,
                pt_measure_type='Rebounding',
                player_or_team='Player'
            )
            df = stats.get_data_frames()[0]
            self._set_cache(league_key, df)
            
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

        def normalize_name(name):
            try:
                from unidecode import unidecode
            except ImportError:
                def unidecode(s): return s
            return unidecode(name).lower().replace('.', '').strip()

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
        
        def normalize_name(name):
            try:
                from unidecode import unidecode
            except ImportError:
                def unidecode(s): return s
            return unidecode(name).lower().replace('.', '').strip()

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

if __name__ == "__main__":
    # Quick test
    loader = NBADataLoader(season='2025-26')
    jokic_id = loader.get_player_id("Nikola Jokic")
    print(f"Jokic ID: {jokic_id}")
    if jokic_id:
        log = loader.get_player_gamelog(jokic_id)
        print(f"Games found: {len(log)}")
        print(log.head())
