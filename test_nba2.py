from nba_api.stats.endpoints import playergamelog
import pandas as pd
import time

pid = 2544 # Lebron
try:
    gl_reg = playergamelog.PlayerGameLog(player_id=pid, season='2023-24', season_type_all_star='Regular Season').get_data_frames()[0]
    time.sleep(1)
    gl_play = playergamelog.PlayerGameLog(player_id=pid, season='2023-24', season_type_all_star='Playoffs').get_data_frames()[0]
    df = pd.concat([gl_play, gl_reg], ignore_index=True)
    print("Combined length:", len(df))
    print(df.head(2))
except Exception as e:
    print("Error:", e)
