import os
import requests
from dotenv import load_dotenv

load_dotenv()
print("Proxy:", os.getenv('NBA_API_PROXY'))
print("Verify:", os.getenv('NBA_API_PROXY_VERIFY_SSL'))

from src.data_loader import NBADataLoader
loader = NBADataLoader()
print("Fetching common player info...")
try:
    info = loader.get_common_player_info(1628369) # Jayson Tatum
    print("Success! Player Name:", info.get('DISPLAY_FIRST_LAST'))
except Exception as e:
    import traceback
    traceback.print_exc()
