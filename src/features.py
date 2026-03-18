import pandas as pd
import numpy as np
from src.data_loader import NBADataLoader

def normalize_name(name):
    try:
        from unidecode import unidecode
    except ImportError:
        def unidecode(s): return s
    return unidecode(name).lower().replace('.', '').strip()

class FeatureEngineer:
    def __init__(self, data_loader):
        self.loader = data_loader
        # Heuristic constants for Long Rebounds
        # If Opponent 3PA Rate > 40%, adjust expectations:
        self.LONG_REB_MATRIX = {
            'G': 1.08,  # Guards get +8% boost (scoop long boards)
            'F': 1.00,  # Forwards are neutral
            'C': 0.96   # Centers get -4% penalty
        }

    def get_team_injury_list(self, team_id):
        """
        Returns a list of injured players for a given team.
        Format: ["Player Name (Status)", ...]
        """
        roster = self.loader.get_team_roster(team_id)
        if roster.empty: 
            print(f"DEBUG: Roster empty for team {team_id}")
            return [] 
        
        injury_report = self.loader.get_injury_report()
        print(f"DEBUG: Injury Report Size: {len(injury_report)}")
        
        notes = []
        
        for _, row in roster.iterrows():
            name = row['PLAYER']
            norm_name = normalize_name(name)
            
            # Check injury status
            status = injury_report.get(norm_name, 'Active')
            
            if status != 'Active':
                 print(f"DEBUG: Found injury for {name}: {status}")
                 notes.append(f"{name} ({status})")
            else:
                 # Debug potential mismatch
                 # if "durant" in norm_name: print(f"DEBUG: Durant status is Active. Key used: {norm_name}")
                 pass
                 
        return notes

    def get_player_stats(self, player_id, opponent_abbrev=None):
        """
        Fetches player logs and splits rebounding into OREB/DREB rates.
        Also calculates historical rates against the specific opponent.
        """
        logs = self.loader.get_player_gamelog(player_id)
        if logs.empty:
             return None
        
        # 1. Clean Minutes (Handle "24:30" string format)
        def clean_minutes(m):
            if isinstance(m, str):
                 if ':' in m:
                     parts = m.split(':')
                     return int(parts[0]) + int(parts[1])/60.0
            return float(m)

        logs['MIN_FLOAT'] = logs['MIN'].apply(clean_minutes)
        # Avoid divide by zero
        logs = logs[logs['MIN_FLOAT'] > 0].copy()

        # 2. Calculate Per-Minute Rates (The "Skill" Metric)
        # We use Per-Minute instead of Per-Game to decouple skill from playing time
        logs['OREB_PM'] = logs['OREB'] / logs['MIN_FLOAT']
        logs['DREB_PM'] = logs['DREB'] / logs['MIN_FLOAT']
        
        # 3. Get Context (Position, Name, TeamID)
        info = self.loader.get_common_player_info(player_id)
        
        # Robust Team ID Fetch
        team_id = None
        if 'TEAM_ID' in logs.columns:
            team_id = logs.iloc[0]['TEAM_ID']
        elif 'Team_ID' in logs.columns:
            team_id = logs.iloc[0]['Team_ID']
        
        if not team_id and not info.empty:
            team_id = info.iloc[0].get('TEAM_ID')
            
        if not info.empty:
            pos_str = info.iloc[0].get('POSITION', 'Unknown')
            # Normalize position to G/F/C
            if 'F' in pos_str: position = 'F'
            elif 'C' in pos_str: position = 'C'
            elif 'G' in pos_str: position = 'G'
            else: position = 'F' # Default
        else:
            position = 'F'

        # 4. Opponent History (Filtered by Opponent Abbrev)
        opp_oreb_rate = None
        opp_dreb_rate = None
        if opponent_abbrev:
            # Matchup string usually contains abbreviations like "OKC vs. GSW"
            # We look for the opponent abbreviation in the matchup string
            opp_logs = logs[logs['MATCHUP'].str.contains(opponent_abbrev, case=False)]
            if not opp_logs.empty:
                opp_oreb_rate = opp_logs['OREB_PM'].mean()
                opp_dreb_rate = opp_logs['DREB_PM'].mean()

        # 5. Trend Data for Chart
        last_10_trend = []
        if not logs.empty:
            # logs are usually sorted newest first
            trend_slice = logs.head(10).iloc[::-1] # Reverse to get oldest -> newest
            for _, row in trend_slice.iterrows():
                try: 
                    # Extract Opponent from MATCHUP
                    # Matchup ex: "DEN vs. BOS" or "DEN @ BOS"
                    m = row['MATCHUP']
                    opp_code = m.split(' ')[-1] # simplistic
                    
                    last_10_trend.append({
                        'date': row['GAME_DATE'],
                        'rebounds': int(row['REB']),
                        'opponent': opp_code,
                        'minutes': float(row['MIN_FLOAT'])
                    })
                except:
                    pass

        # 6. Variance-Aware Stats (actual game-to-game variance)
        reb_per_game = logs['REB'].astype(float)
        reb_variance = float(reb_per_game.var()) if len(reb_per_game) > 2 else None
        reb_std = float(reb_per_game.std()) if len(reb_per_game) > 2 else None
        reb_mean = float(reb_per_game.mean()) if len(reb_per_game) > 0 else None

        # 7. Minutes Trend Detection (linear regression on last 5 games)
        minutes_trend_slope = 0.0
        recent_mins = logs.head(5)['MIN_FLOAT'].values
        if len(recent_mins) >= 3:
            # logs are newest-first, so reverse for proper time order
            ordered_mins = recent_mins[::-1]
            x = np.arange(len(ordered_mins))
            coeffs = np.polyfit(x, ordered_mins, 1)
            minutes_trend_slope = float(coeffs[0])  # min/game slope

        return {
            'player_name': info.iloc[0].get('DISPLAY_FIRST_LAST', 'Unknown'),
            'position': position,
            'season_oreb_rate': logs['OREB_PM'].mean(),
            'season_dreb_rate': logs['DREB_PM'].mean(),
            # Weighted recent form (Last 5 games count 50% more)
            'recent_oreb_rate': (logs.head(5)['OREB_PM'].mean() * 1.5 + logs['OREB_PM'].mean()) / 2.5,
            'recent_dreb_rate': (logs.head(5)['DREB_PM'].mean() * 1.5 + logs['DREB_PM'].mean()) / 2.5,
            'opp_oreb_rate': opp_oreb_rate,
            'opp_dreb_rate': opp_dreb_rate,
            'last_5_min': logs.head(5)['MIN_FLOAT'].mean(),
            'last_10_min': logs.head(10)['MIN_FLOAT'].mean(),
            'season_min_avg': logs['MIN_FLOAT'].mean(),
            'team_id': team_id,
            'last_10_games': last_10_trend,
            # New: Variance-Aware Simulation data
            'reb_variance': reb_variance,
            'reb_std': reb_std,
            'reb_mean': reb_mean,
            'games_played': len(logs),
            # New: Minutes Trend
            'minutes_trend_slope': minutes_trend_slope
        }

    def get_matchup_context(self, team_id, opponent_team_id):
        """
        Fetches environment stats: Pace, Shooting %, and Opponent tendencies.
        """
        # Load Team & Opponent Stats
        league_adv = self.loader.get_team_advanced_stats()
        league_base = self.loader.get_team_stats()
        league_opp = self.loader.get_opponent_stats_per_game()
        
        team_stats = league_base[league_base['TEAM_ID'] == team_id]
        team_adv = league_adv[league_adv['TEAM_ID'] == team_id]
        
        opp_stats_off = league_base[league_base['TEAM_ID'] == opponent_team_id]
        opp_adv = league_adv[league_adv['TEAM_ID'] == opponent_team_id]
        opp_stats_def = league_opp[league_opp['TEAM_ID'] == opponent_team_id]

        if team_stats.empty or opp_stats_off.empty:
            return None

        # 3-Point Attempt Rate (3PA / FGA) - From Opponent's OFFENSE
        opp_3par = 0.0
        if 'FG3A' in opp_stats_off.columns and 'FGA' in opp_stats_off.columns:
            fga = opp_stats_off['FGA'].values[0]
            if fga > 0:
                opp_3par = opp_stats_off['FG3A'].values[0] / fga

        # Opponent Rebounds Allowed (Split)
        opp_oreb_allowed = 10.5
        opp_dreb_allowed = 33.5
        if not opp_stats_def.empty:
            if 'OPP_OREB' in opp_stats_def.columns:
                opp_oreb_allowed = opp_stats_def['OPP_OREB'].values[0]
            if 'OPP_DREB' in opp_stats_def.columns:
                opp_dreb_allowed = opp_stats_def['OPP_DREB'].values[0]
        
        # League Averages
        league_avg_oreb_allowed = 10.5
        league_avg_dreb_allowed = 33.5
        if 'OPP_OREB' in league_opp.columns:
            league_avg_oreb_allowed = league_opp['OPP_OREB'].mean()
        if 'OPP_DREB' in league_opp.columns:
            league_avg_dreb_allowed = league_opp['OPP_DREB'].mean()
            
        league_avg_fg_pct = 0.47
        if 'FG_PCT' in league_base.columns:
            league_avg_fg_pct = league_base['FG_PCT'].mean()

        return {
            'team_pace': team_adv['PACE'].values[0] if not team_adv.empty else 99.0,
            'opp_pace': opp_adv['PACE'].values[0] if not opp_adv.empty else 99.0,
            'team_fg_pct': team_stats['FG_PCT'].values[0],
            'opp_fg_pct': opp_stats_off['FG_PCT'].values[0],
            'opp_3par': opp_3par,
            'opp_oreb_allowed': opp_oreb_allowed,
            'opp_dreb_allowed': opp_dreb_allowed,
            'league_avg_pace': league_adv['PACE'].mean(),
            'league_avg_oreb_allowed': league_avg_oreb_allowed,
            'league_avg_dreb_allowed': league_avg_dreb_allowed,
            'league_avg_fg_pct': league_avg_fg_pct
        }

    def get_dvp_multiplier(self, position, opp_allowed, league_avg):
        """
        Calculates Defense vs Position multiplier.
        """
        # Base factor: How many rebounds does opp allow vs avg?
        base_factor = opp_allowed / league_avg if league_avg > 0 else 1.0
        
        # Position-specific weighting could go here (e.g. Centers impacted more)
        # For now, we apply the team-level allowance factor directly
        return base_factor

    def adjust_minutes_for_injuries(self, player_id, team_id, position, base_minutes):
        """
        Heuristic to boost minutes if key teammates at the same position are OUT.
        """
        injury_report = self.loader.get_injury_report()
        roster = self.loader.get_team_roster(team_id)
        
        if roster.empty:
            return base_minutes, None

        # 1. Check if the player themselves are OUT
        p_info = self.loader.get_common_player_info(player_id)
        p_name = p_info.iloc[0].get('DISPLAY_FIRST_LAST', 'Unknown')
        
        p_status = injury_report.get(normalize_name(p_name), 'Active')
        if 'out' in p_status.lower() or 'inactive' in p_status.lower() or 'nwt' in p_status.lower():
            return 0.0, f"{p_name} is listed as {p_status}!"

        # 2. Check for Teammate Injuries (Same position, Starter minutes)
        # Fetch advanced league stats to get teammate minutes (might be cached)
        league_adv_key = f"league_player_stats_advanced_{self.loader.season}"
        league_adv = self.loader._get_from_cache(league_adv_key)
        if league_adv is None:
            self.loader.get_player_advanced_stats(0)
            league_adv = self.loader._get_from_cache(league_adv_key)

        if league_adv is None:
            return base_minutes, None

        roster_stats = pd.merge(roster, league_adv[['PLAYER_ID', 'MIN']], on='PLAYER_ID', how='inner')
        
        # Look for "Starters" at the same position (> 24 MPG)
        teammate_boost = 0.0
        injury_notes = []
        
        # Define groupings for better matching
        is_big = any(pos in position for pos in ['F', 'C'])
        is_guard = 'G' in position

        for _, row in roster_stats.iterrows():
            if row['PLAYER_ID'] == player_id: continue
            
            t_pos = row['POSITION']
            t_is_big = any(pos in t_pos for pos in ['F', 'C'])
            t_is_guard = 'G' in t_pos
            
            # Match if both are Bigs or both are Guards
            match = (is_big and t_is_big) or (is_guard and t_is_guard)
            
            if match:
                # Is this a high-minute player?
                if row['MIN'] > 24.0:
                    t_name = row['PLAYER']
                    t_status = injury_report.get(normalize_name(t_name), 'Active')
                    if 'out' in t_status.lower() or 'inactive' in t_status.lower():
                        # Significant boost for backup if starter is out
                        # We limit total boost to avoid crazy minutes
                        boost = 8.0 if base_minutes < 22 else 4.0
                        teammate_boost += boost
                        injury_notes.append(f"{t_name} is OUT")

        # Clamp total minutes at ~36 unless manual
        new_minutes = min(36.0, base_minutes + teammate_boost)
        return new_minutes, ", ".join(injury_notes) if injury_notes else None

    def get_cannibalization_factor(self, team_id, opponent_abbrev, current_player_id, base_projection_func, current_proj_minutes):
        """
        Calculates a SOFT cap if the team is projecting way more rebounds than available.
        Uses a sqrt damping to avoid harsh penalties.
        """
        # We skip complex summing and use a simple heuristic if needed.
        # Returning 1.0 for now.
        return 1.0

    def compute_projection(self, player_id, opponent_abbrev, spread=0, manual_minutes=None, home_game=True, days_rest=1, opp_days_rest=1, matchup_factor=1.0):
        """
        Refactored 2-Layer Projection Model.
        Layer 1: Base (Skill * Minutes)
        Layer 2: Environment (Pace * Misses * DvP * Matchup) -> CLAMPED
        """
        # 1. Load Data
        p_stats = self.get_player_stats(player_id, opponent_abbrev)
        if not p_stats: 
            return {'error': 'Player stats not found'}
            
        opp_id = self.loader.get_team_id(opponent_abbrev)
        env = self.get_matchup_context(p_stats['team_id'], opp_id)
        if not env: 
            return {'error': 'Matchup stats not found'}

        # --- Layer 1: Base Projection ---
        
        # Minutes
        season_min = p_stats.get('season_min_avg', p_stats['last_10_min'])
        base_minutes = manual_minutes if manual_minutes else (season_min * 0.7 + p_stats['last_10_min'] * 0.3)
        
        # Minutes Trend Adjustment (NEW)
        # If minutes are trending significantly up/down, project forward
        min_trend_slope = p_stats.get('minutes_trend_slope', 0.0)
        trend_adjustment = 0.0
        if not manual_minutes and abs(min_trend_slope) > 0.5:
            # Project 2 games forward, capped at ±3 minutes
            trend_adjustment = max(-3.0, min(3.0, min_trend_slope * 2))
            base_minutes += trend_adjustment
        
        # Injury Adjustment for Minutes
        injury_note = None
        if not manual_minutes:
            base_minutes, injury_note = self.adjust_minutes_for_injuries(player_id, p_stats['team_id'], p_stats['position'], base_minutes)
        
        if base_minutes == 0:
             return {'error': injury_note or 'Player is OUT'}

        # Blowout Logic (Minutes Damping Only)
        abs_spread = abs(spread)
        blowout_risk_label = "None"
        blowout_modifier = 1.0
        
        # Only reduce minutes for extreme spreads
        if abs_spread >= 13.5:
            blowout_risk_label = "High"
            # Starters play ~10% less, Bench plays ~10% more
            if base_minutes >= 28: blowout_modifier = 0.90 
            elif base_minutes <= 18: blowout_modifier = 1.10
        elif abs_spread >= 9.5:
             blowout_risk_label = "Slight"
             if base_minutes >= 30: blowout_modifier = 0.96

        proj_minutes = base_minutes * blowout_modifier
        
        # Dynamic Recency Weights (NEW)
        # Adjust season/recent/opponent blend based on games played
        games_played = p_stats.get('games_played', 30)
        if games_played < 15:
            w_season, w_recent, w_opp = 0.65, 0.20, 0.15
        elif games_played <= 40:
            w_season, w_recent, w_opp = 0.50, 0.30, 0.20
        else:
            w_season, w_recent, w_opp = 0.35, 0.45, 0.20
        
        # Skill (Rebounds Per Minute) - Dynamic Weighted Blend
        if p_stats.get('opp_oreb_rate') is not None:
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
        pace_factor = game_pace / env['league_avg_pace']
        
        # 2. Miss Opportunities (Weighted for OREB vs DREB)
        # OREB needs My Team Misses, DREB needs Opp Team Misses
        # We blend them based on the player's OREB/DREB ratio
        total_rate = skill_oreb + skill_dreb
        if total_rate > 0:
            oreb_ratio = skill_oreb / total_rate
            dreb_ratio = skill_dreb / total_rate
        else:
            oreb_ratio, dreb_ratio = 0.25, 0.75

        dreb_miss_factor = (1.0 - env['opp_fg_pct']) / (1.0 - env['league_avg_fg_pct'])
        oreb_miss_factor = (1.0 - env['team_fg_pct']) / (1.0 - env['league_avg_fg_pct'])
        
        opportunity_factor = (dreb_miss_factor * dreb_ratio) + (oreb_miss_factor * oreb_ratio)
        
        # 3. DvP (Defense vs Position)
        # Using allowed vs avg
        dvp_factor_dreb = self.get_dvp_multiplier(p_stats['position'], env['opp_dreb_allowed'], env['league_avg_dreb_allowed'])
        dvp_factor_oreb = self.get_dvp_multiplier(p_stats['position'], env['opp_oreb_allowed'], env['league_avg_oreb_allowed'])
        dvp_factor = (dvp_factor_dreb * dreb_ratio) + (dvp_factor_oreb * oreb_ratio)
        
        # 4. Long Rebound (Opp 3PA)
        long_reb_factor = 1.0
        if env['opp_3par'] > 0.42:
             long_reb_factor = self.LONG_REB_MATRIX.get(p_stats['position'], 1.0)
        
        # --- COMBINE & CLAMP ---
        
        # Multipliers
        # Matchup factor comes from outside (composite), defaulting to 1.0
        
        raw_env_mult = pace_factor * opportunity_factor * dvp_factor * long_reb_factor * matchup_factor
        
        # Rest/Venue (Applied to Base or Env? Let's apply to Env so it gets clamped)
        # Modified Rest Logic:
        # Player B2B (rest=0) -> -5%
        # Opponent B2B (rest=0) -> +3%
        venue_mult = 1.03 if home_game else 0.97
        
        rest_mult = 1.0
        if days_rest == 0: rest_mult *= 0.95
        if opp_days_rest == 0: rest_mult *= 1.03
        
        raw_global_mult = raw_env_mult * venue_mult * rest_mult
        
        # CLAMPING: The Secret Sauce to avoid systematic bias
        # We don't want a player to get -30% just because of bad random factors.
        # Range: 0.85 to 1.18 (skewed slightly up because great spots > bad spots)
        final_env_mult = max(0.85, min(1.18, raw_global_mult))
        
        # --- Layer 3: Soft Team Cap (Cannibalization) ---
        # Very simple heuristic: If projected > 18 (star C), make it harder to go higher
        # Or relative to team total.
        
        team_cap_factor = 1.0
        # If the environment is boosting a Star > 20% and he's already high volume
        if base_rebs > 12 and final_env_mult > 1.10:
             # Dampen the boost
             excess = final_env_mult - 1.10
             final_env_mult = 1.10 + (excess * 0.5)
             
        # No more hard cannibalization recursion.
        
        final_projection = base_rebs * final_env_mult

        return {
            'player': p_stats['player_name'],
            'projection': round(final_projection, 2),
            'components': {
                'Base Rebs': round(base_rebs, 2),
                'Base Minutes': round(base_minutes, 1),
                'Proj Minutes': round(proj_minutes, 1),
                'Env Mult (Final)': round(final_env_mult, 2),
                'Raw Mult': round(raw_global_mult, 2),
                'Pace': round(pace_factor, 2),
                'Opp': round(opportunity_factor, 2),
                'DvP': round(dvp_factor, 2),
                'Matchup': round(matchup_factor, 2),
                'Blowout': blowout_risk_label
            },
            'modifiers': {
                'blowout_risk': blowout_risk_label,
                'minutes': round(proj_minutes, 1),
                'injury_note': injury_note
            }
        }

    def compute_composite_projection(self, player_id, opponent_abbrev, spread=0, manual_minutes=None, home_game=True, days_rest=1, opp_days_rest=1, matchup_player=None):
        """
        Higher-order method that incorporates individual matchup player scouting 
        and environment context. Calculates matchup factor acting as input to core projection.
        """
        # 1. Prelim: Get Player Info
        p_info = self.get_player_stats(player_id)
        if not p_info: return {'error': 'Player not found'}
        pos = p_info['position']
        
        # 2. Matchup Player Identification (Auto-find if not provided)
        opp_id = self.loader.get_team_id(opponent_abbrev)
        m_pid = None
        m_note = None
        if matchup_player:
            m_pid = self.loader.get_player_id(matchup_player)
            # Fetch injury note for manual matchup too
            if m_pid:
                injury_report = self.loader.get_injury_report()
                norm_name = normalize_name(matchup_player)
                m_note = injury_report.get(norm_name, 'Active')
                # Normalize m_note if not in report
                if m_note != 'Active':
                    pass # Keep status from report
        else:
            # Find Who they are likely guarding (Minute-proximate match)
            target_min = p_info.get('season_min_avg', 30.0)
            matchup_data = self.loader.get_likely_opponent_matchup(opp_id, pos, target_minutes=target_min)
            if matchup_data:
                m_pid = matchup_data['player_id']
                matchup_player = matchup_data['player_name']
                m_note = matchup_data.get('injury_note')

        # 3. Scouting Logic (Rebound PCT + Box Outs) -> Calculate Matchup Factor
        final_adjustment = 1.0
        matchup_context = "Neutral"
        
        if m_pid:
            # 1. Fetch Deep Stats
            m_adv = self.loader.get_player_advanced_stats(m_pid)
            m_hustle = self.loader.get_player_hustle_stats(m_pid)
            m_pt = self.loader.get_player_rebounding_tracking_stats(m_pid)
            m_info = self.loader.get_common_player_info(m_pid)
            
            # Matchup Position
            m_pos = 'F'
            if not m_info.empty:
                m_pos_str = m_info.iloc[0].get('POSITION', 'Unknown')
                if 'C' in m_pos_str: m_pos = 'C'
                elif 'F' in m_pos_str: m_pos = 'F'
                elif 'G' in m_pos_str: m_pos = 'G'

            # Position Calibration
            calibs = {
                'C': {'reb_pct': 0.16, 'chance_pct': 0.60, 'contest_pct': 0.45},
                'F': {'reb_pct': 0.11, 'chance_pct': 0.50, 'contest_pct': 0.35},
                'G': {'reb_pct': 0.08, 'chance_pct': 0.45, 'contest_pct': 0.25}
            }
            c = calibs.get(m_pos, calibs['F'])
            
            scout_factors = []
            
            # A: Dominance
            if not m_adv.empty:
                val = m_adv['REB_PCT'].iloc[0]
                if val > 1.0: val /= 100.0
                mod = 1.0 - (val - c['reb_pct']) * 0.5
                scout_factors.append(max(0.94, min(1.06, mod)))
            
            # B: Efficiency
            if not m_pt.empty:
                val = m_pt['REB_CHANCE_PCT_ADJ'].iloc[0]
                if val > 1.0: val /= 100.0
                mod = 1.0 - (val - c['chance_pct']) * 0.2
                scout_factors.append(max(0.96, min(1.04, mod)))
                
                # C: Toughness
                val = m_pt['REB_CONTEST_PCT'].iloc[0]
                if val > 1.0: val /= 100.0
                mod = 1.0 - (val - c['contest_pct']) * 0.2
                scout_factors.append(max(0.96, min(1.04, mod)))

            # D: Physicality
            if not m_hustle.empty:
                val = m_hustle['BOX_OUTS'].iloc[0]
                gp = m_hustle['G'].iloc[0] if 'G' in m_hustle.columns else (m_hustle['GP'].iloc[0] if 'GP' in m_hustle.columns else 1)
                if gp > 0: val = val / gp
                
                box_target = 2.5 if m_pos == 'C' else 1.0
                mod = 1.0 - (val - box_target) * 0.01
                scout_factors.append(max(0.96, min(1.04, mod)))
            
            # Combine Factors
            if scout_factors:
                final_adjustment = np.prod(scout_factors)
            
            # Narrative
            reasons = []
            if final_adjustment < 0.94:
                strength = "Elite"
                if not m_pt.empty:
                    c_pct = m_pt['REB_CONTEST_PCT'].iloc[0]
                    if c_pct > 1.0: c_pct /= 100.0
                    if c_pct > c['contest_pct'] + 0.1: reasons.append("Tough Finisher")
            elif final_adjustment < 0.97:
                strength = "Difficult"
            elif final_adjustment > 1.06:
                strength = "Weak"
            elif final_adjustment > 1.03:
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
            matchup_factor=final_adjustment
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
        proj_result['team_injury_list'] = self.get_team_injury_list(p_info['team_id'])
        proj_result['opp_injury_list'] = self.get_team_injury_list(opp_id)
        proj_result['trend_data'] = p_info.get('last_10_games', [])
        
        proj_result['mean_projection'] = proj_result['projection'] # Backwards compat
        
        # Attach variance data for simulation
        proj_result['player_variance'] = {
            'reb_variance': p_info.get('reb_variance'),
            'reb_std': p_info.get('reb_std'),
            'reb_mean': p_info.get('reb_mean')
        }
        
        return proj_result

    def generate_pick_summary(self, proj_data, line=None):
        """
        Generates a detailed, educational narrative summary.
        """
        player = proj_data['player']
        proj = proj_data['projection']
        base_rebs = proj_data.get('components', {}).get('Base Rebs', 0)
        comps = proj_data.get('components', {})
        context = proj_data.get('matchup_context', 'Neutral')
        
        # Narrative Building Blocks
        paragraphs = []
        
        # Paragraph 1: The Core Projection
        # "We start with a baseline of X rebounds based on Y minutes."
        base_mins = comps.get('Proj Minutes', 0)
        p1 = f"The model projects **{player}** for **{proj} rebounds**. "
        p1 += f"This starts with a baseline capability of **{base_rebs} rebounds** based on a projected **{base_mins} minutes** workload."
        if base_mins > 34: p1 += " (Heavy workload expected)."
        paragraphs.append(p1)
        
        # Paragraph 2: The Matchup Factors (Why it changed)
        # Interpret the multipliers
        factors = []
        
        # DvP
        dvp = comps.get('DvP', 1.0)
        opp_team = proj_data.get('opponent', 'OPP') # We might need to pass this or infer
        
        if dvp >= 1.05: factors.append(f"the opponent allows **{int((dvp-1)*100)}% more rebounds** than average to this position")
        elif dvp <= 0.95: factors.append(f"the opponent allows **{int((1-dvp)*100)}% fewer rebounds** to this position")
        
        # Pace
        pace = comps.get('Pace', 1.0)
        if pace >= 1.02: factors.append("the game **Pace** is faster than league average")
        elif pace <= 0.98: factors.append("the slow game **Pace** limits opportunities")
        
        # Opp Efficiency
        miss_opp = comps.get('Opp', 1.0)
        if miss_opp <= 0.96: factors.append("the opponent shoots efficiently, leading to fewer rebound chances")
        
        # Matchup Specific
        matchup_adj = comps.get('Matchup', 1.0)
        if matchup_adj <= 0.96: factors.append(f"the specific matchup against **{context.split('(')[-1].replace(')', '')}** is tough")
        elif matchup_adj >= 1.04: factors.append(f"the specific matchup against **{context.split('(')[-1].replace(')', '')}** is favorable")
        
        if factors:
            p2 = "Critical factors impacting this projection: " + "; ".join(factors) + "."
            paragraphs.append(p2)
        else:
            paragraphs.append("The matchup conditions are largely neutral, with no significant advantages or disadvantages.")

        # Paragraph 3: Betting Conclusion
        if line:
            diff = proj - line
            direction = "OVER" if proj > line else "UNDER"
            abs_diff = abs(diff)
            
            p3 = f"Against a line of **{line}**, the model sees a "
            if abs_diff > 1.5: p3 += f"**Significant {'Edge' if abs_diff > 2 else 'Value'}**"
            elif abs_diff > 0.6: p3 += "**Moderate Edge**"
            else: p3 += "**Slight Lean**"
            
            p3 += f" on the **{direction}**."
            paragraphs.append(p3)
            
        return "\n\n".join(paragraphs)

if __name__ == "__main__":
    # Example Usage
    # loader = NBADataLoader()
    # eng = FeatureEngineer(loader)
    # proj = eng.compute_composite_projection(pid, "BOS", spread=-14.5, home_game=True, days_rest=1)
    pass
