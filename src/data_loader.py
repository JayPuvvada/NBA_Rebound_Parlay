import pandas as pd
from functools import wraps
from requests.exceptions import ConnectionError, Timeout, HTTPError
from nba_api.stats.endpoints import playergamelog, teamgamelog, leaguedashteamstats, commonplayerinfo, boxscoretraditionalv2, shotchartdetail, cumestatsteam, leaguedashplayerstats
from nba_api.stats.library.http import NBAStatsHTTP
from datetime import date, datetime, timedelta, timezone
import json
import math
from numbers import Real
import os
import re
import tempfile
import threading
import time
import random
from zoneinfo import ZoneInfo

from src.utils import normalize_name, get_logger, current_season
from src.cache import ttl_cache

log = get_logger('data_loader')
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NBA_SEASON_TYPES = ('Regular Season', 'PlayIn', 'Playoffs')


class DataUnavailableError(RuntimeError):
    """Raised when an upstream source failed rather than returned valid empty data."""


def _source_cache(seconds, *, cache_empty=False):
    """Cache data together with its provenance, replaying it on every read."""
    def decorate(method):
        def retention(result):
            value, metadata = result
            empty = value.empty if isinstance(value, pd.DataFrame) else not value
            if empty and not cache_empty:
                return 0
            return min(seconds, NBADataLoader.NBA_STATS_CIRCUIT_SEC) if metadata['status'] != 'primary' else seconds

        @ttl_cache(seconds, ttl_for_value=retention)
        def cached(loader, *args, **kwargs):
            previous = loader.get_data_source_metadata()
            loader.reset_data_source_metadata()
            try:
                value = method(loader, *args, **kwargs)
                return value, loader.get_data_source_metadata()
            finally:
                current = loader.get_data_source_metadata()
                loader._data_source_state.metadata = previous
                loader._merge_data_source_metadata(current)

        @wraps(method)
        def read(loader, *args, **kwargs):
            value, metadata = cached(loader, *args, **kwargs)
            loader._merge_data_source_metadata(metadata)
            return value

        read.invalidate = cached.invalidate
        return read
    return decorate


def _parse_iso_date(date_str):
    """Validate and parse an API date without accepting partial ISO strings."""
    if isinstance(date_str, datetime):
        return date_str.date()
    if isinstance(date_str, date):
        return date_str
    if not isinstance(date_str, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        raise ValueError("date must use YYYY-MM-DD format")
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("date must be a valid calendar date in YYYY-MM-DD format") from exc


def _season_for_date(date_value):
    """Return the NBA season containing ``date_value``."""
    return current_season(_parse_iso_date(date_value))


def _date_to_parameter(as_of):
    """NBA dashboard cutoff for a pre-game forecast on ``as_of`` (exclusive)."""
    if not as_of:
        return ""
    return (_parse_iso_date(as_of) - timedelta(days=1)).strftime("%m/%d/%Y")


def _within_live_injury_window(as_of, max_future_days=2):
    """Current injury scrapes are valid only for the immediate slate window."""
    if not as_of:
        return True
    requested = _parse_iso_date(as_of)
    today = datetime.now(ZoneInfo('America/New_York')).date()
    return today <= requested <= today + timedelta(days=max_future_days)


def _finite_number(value, default=None, *, minimum=None, maximum=None):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(result):
        return default
    if minimum is not None and result < minimum:
        return default
    if maximum is not None and result > maximum:
        return default
    return result


def _atomic_json_write(path, payload):
    """Write JSON in the destination directory and atomically replace the old file."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=directory, delete=False, encoding="utf-8") as handle:
            temp_path = handle.name
            json.dump(payload, handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _combine_period_per_game_frames(frames, id_column, games_column='GP'):
    """Combine period-level PerGame frames using games-played weights.

    NBA dashboard endpoints expose Regular Season, PlayIn, and Playoffs as
    separate requests. Counting rates and advanced rates are combined by their
    period sample sizes; GP/G and win/loss counts are summed. Identity and rank
    columns use the latest period in which the entity appeared.
    """
    if not isinstance(frames, (list, tuple)) or not frames:
        raise DataUnavailableError("no period frames were supplied")
    for frame in frames:
        if not isinstance(frame, pd.DataFrame):
            raise DataUnavailableError("period response is not tabular")
        if not frame.empty and not {id_column, games_column}.issubset(frame.columns):
            raise DataUnavailableError(
                f"period response is missing {id_column} or {games_column}"
            )

    populated = [frame.copy() for frame in frames if not frame.empty]
    if not populated:
        return frames[0].iloc[0:0].copy()

    columns = list(dict.fromkeys(
        column for frame in populated for column in frame.columns
    ))
    tagged = []
    for period_order, frame in enumerate(populated):
        current = frame.reindex(columns=columns).copy()
        current['_PERIOD_ORDER'] = period_order
        tagged.append(current)
    combined = pd.concat(tagged, ignore_index=True)

    rows = []
    for entity_id, group in combined.groupby(id_column, sort=False, dropna=False):
        group = group.sort_values('_PERIOD_ORDER')
        weights = pd.to_numeric(group[games_column], errors='coerce').fillna(0).clip(lower=0)
        row = {}
        for column in columns:
            series = group[column]
            non_null = series.dropna()
            latest = non_null.iloc[-1] if not non_null.empty else None
            if column == id_column or column.endswith('_ID'):
                row[column] = entity_id if column == id_column else latest
                continue
            numeric = pd.to_numeric(series, errors='coerce')
            numeric_like = int(numeric.notna().sum()) == int(series.notna().sum())
            if column in {games_column, 'W', 'L'} and numeric_like:
                row[column] = float(numeric.fillna(0).sum())
            elif (
                numeric_like
                and not column.endswith('_RANK')
                and column not in {'CFID', 'TEAM_COUNT'}
                and (weights > 0).any()
            ):
                valid = numeric.notna() & (weights > 0)
                denominator = float(weights.loc[valid].sum())
                row[column] = (
                    float((numeric.loc[valid] * weights.loc[valid]).sum() / denominator)
                    if denominator > 0 else latest
                )
            else:
                row[column] = latest
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)

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
    OFFLINE_CACHE_FILE = os.path.join(PROJECT_ROOT, 'data', 'nba_cache.json')
    OFFLINE_CACHE_TTL_SEC = 12 * 60 * 60
    REQUIRED_OFFLINE_DATASETS = {
        'league_team_stats_base',
        'league_team_stats_advanced',
        'league_opponent_stats',
    }
    REQUIRED_OFFLINE_COLUMNS = {
        'league_team_stats_base': {'TEAM_ID', 'FG_PCT'},
        'league_team_stats_advanced': {'TEAM_ID', 'PACE'},
        'league_opponent_stats': {'TEAM_ID', 'OPP_OREB', 'OPP_DREB'},
    }
    ROSTER_CACHE_TTL_SEC = 6 * 60 * 60
    EXPECTED_NBA_TEAM_COUNT = 30
    NBA_STATS_CIRCUIT_SEC = 5 * 60
    ESPN_SEARCH_URL = 'https://site.api.espn.com/apis/search/v2'
    ESPN_PLAYER_URL = (
        'https://site.web.api.espn.com/apis/common/v3/sports/'
        'basketball/nba/athletes/{athlete_id}/{resource}'
    )
    ESPN_SCOREBOARD_URL = (
        'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'
    )
    ESPN_ABBREVIATION_MAP = {
        'GS': 'GSW', 'NY': 'NYK', 'NO': 'NOP', 'SA': 'SAS',
        'UTAH': 'UTA', 'WSH': 'WAS',
    }

    @classmethod
    def validate_offline_cache_data(cls, cache):
        """Validate core datasets, schemas, and the complete 30-team universe."""
        if not isinstance(cache, dict):
            raise ValueError("cache data must be an object")
        missing = cls.REQUIRED_OFFLINE_DATASETS.difference(cache)
        if missing:
            raise ValueError(f"cache is incomplete; missing {sorted(missing)}")

        team_id_sets = {}
        for required_key in cls.REQUIRED_OFFLINE_DATASETS:
            records = cache.get(required_key)
            if not isinstance(records, list) or not records:
                raise ValueError(f"cache dataset {required_key} is empty or malformed")
            frame = pd.DataFrame(records)
            missing_columns = cls.REQUIRED_OFFLINE_COLUMNS[required_key].difference(frame.columns)
            if missing_columns:
                raise ValueError(
                    f"cache dataset {required_key} is missing columns {sorted(missing_columns)}"
                )
            ids = pd.to_numeric(frame['TEAM_ID'], errors='coerce').dropna()
            ids = {int(team_id) for team_id in ids if float(team_id) > 0}
            if len(ids) != cls.EXPECTED_NBA_TEAM_COUNT:
                raise ValueError(
                    f"cache dataset {required_key} has {len(ids)} unique teams; "
                    f"expected {cls.EXPECTED_NBA_TEAM_COUNT}"
                )
            team_id_sets[required_key] = ids
        if len({frozenset(ids) for ids in team_id_sets.values()}) != 1:
            raise ValueError("core cache datasets do not contain the same team IDs")

    def __init__(self, season=None):
        self.season = season or current_season()
        # Simple in-memory cache to avoid spamming API during dev
        self._cache = {}
        self._cache_loaded_at = {}
        self._nba_stats_unavailable_until = 0.0
        self._data_source_state = threading.local()
        self.reset_data_source_metadata()
        self._injury_report_metadata = {
            'status': 'not_loaded',
            'source': None,
            'fetched_at': None,
            'entry_count': None,
            'stale': None,
        }
        self.leaguedashplayerstats = leaguedashplayerstats
        self._load_offline_cache()

    def _load_offline_cache(self):
        """Load a complete cache only when its embedded timestamp is fresh."""
        cache_file = self.OFFLINE_CACHE_FILE
        if not os.path.exists(cache_file):
            return

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, dict):
                raise ValueError("cache root must be an object")
            timestamp = data.get('timestamp')
            if not isinstance(timestamp, str):
                raise ValueError("cache has no embedded timestamp")
            generated_at = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            if generated_at.tzinfo is None:
                # Legacy cache timestamps were local wall-clock values.
                generated_at = generated_at.replace(tzinfo=datetime.now().astimezone().tzinfo)
            age_sec = (datetime.now(timezone.utc) - generated_at.astimezone(timezone.utc)).total_seconds()
            if age_sec < -300 or age_sec > self.OFFLINE_CACHE_TTL_SEC:
                log.info("Offline cache timestamp is stale or invalid; using live data.")
                return

            if data.get('season') != self.season:
                return

            cache = data.get('data')
            self.validate_offline_cache_data(cache)

            cache_as_of = data.get('as_of_date')
            if cache_as_of is not None:
                cache_as_of = _parse_iso_date(cache_as_of).isoformat()
                if data.get('data_through') != _date_to_parameter(cache_as_of):
                    raise ValueError("cache data_through does not match its as_of_date")
            current_snapshot = (
                cache_as_of is None
                or cache_as_of == datetime.now(ZoneInfo('America/New_York')).date().isoformat()
            )

            log.info("Loaded offline cache successfully.")
            self.offline_cache_timestamp = generated_at.astimezone(timezone.utc).isoformat()
            
            # Map the JSON arrays back to Pandas DataFrames in our memory cache
            keys_to_map = [
                'league_player_stats_advanced', 'league_player_stats_base',
                'league_team_stats_base', 'league_team_stats_advanced', 'league_opponent_stats',
                'league_hustle_stats', 'league_rebounding_tracking'
            ]
            
            for key in keys_to_map:
                if key in cache:
                    frame = pd.DataFrame(cache[key])
                    # Only today's daily snapshot (or a legacy undated snapshot)
                    # may satisfy an unqualified/current lookup. Historical
                    # snapshots remain available solely under their exact date.
                    if current_snapshot:
                        self._cache[f"{key}_{self.season}"] = frame
                    if cache_as_of:
                        self._cache[f"{key}_{self.season}_{cache_as_of}"] = frame.copy(deep=True)
                    
            # Load rosters
            if 'rosters' in cache:
                for team_id, roster_data in cache['rosters'].items():
                    roster_key = f"roster_{team_id}_{self.season}"
                    self._cache[roster_key] = pd.DataFrame(roster_data)
                    self._cache_loaded_at[roster_key] = time.monotonic()

        except Exception as e:
            log.warning(f"Ignoring invalid offline cache: {e}")

    def _get_from_cache(self, key):
        return self._cache.get(key)

    def _set_cache(self, key, value):
        self._cache[key] = value

    def get_injury_report_metadata(self):
        """Return non-sensitive provenance for the currently held injury data."""
        return dict(self._injury_report_metadata)

    def get_data_source_metadata(self):
        """Return non-sensitive provenance for projection inputs."""
        metadata = getattr(self._data_source_state, 'metadata', None)
        if not isinstance(metadata, dict):
            self.reset_data_source_metadata()
            metadata = self._data_source_state.metadata
        return {
            **metadata,
            'limitations': list(metadata.get('limitations') or []),
        }

    def reset_data_source_metadata(self):
        """Start source tracking for one synchronous request/thread."""
        self._data_source_state.metadata = {
            'status': 'primary',
            'source': 'stats.nba.com',
            'limitations': [],
        }

    def _merge_data_source_metadata(self, metadata):
        if metadata.get('status') != 'primary':
            for limitation in metadata.get('limitations') or ['alternate data was used']:
                self.mark_data_degraded(limitation, source=metadata.get('source', 'unknown'))

    def mark_data_degraded(self, limitation, source='espn'):
        """Make alternate/estimated inputs visible to the actionability gate."""
        metadata = getattr(self._data_source_state, 'metadata', None)
        if not isinstance(metadata, dict):
            self.reset_data_source_metadata()
            metadata = self._data_source_state.metadata
        limitations = metadata.setdefault('limitations', [])
        if limitation not in limitations:
            limitations.append(limitation)
        metadata.update({'status': 'degraded', 'source': source})

    def _retry_api_call(self, api_func, max_retries=1, **kwargs):
        """Bounded NBA Stats probe with optional caller-requested retries."""
        if not isinstance(max_retries, int) or max_retries < 1:
            raise ValueError("max_retries must be a positive integer")
        func_name = api_func.__name__ if hasattr(api_func, '__name__') else str(api_func)

        if time.monotonic() < self._nba_stats_unavailable_until:
            raise DataUnavailableError('stats.nba.com circuit is temporarily open')

        # Inject proxy if specifically set for NBA API (avoids breaking pip/global requests)
        nba_proxy = os.getenv('NBA_API_PROXY')
        if nba_proxy and 'proxy' not in kwargs:
            kwargs['proxy'] = nba_proxy

        # Some authenticated interception proxies (including ScraperAPI's proxy
        # endpoint) terminate TLS with their own certificate. Keep verification
        # enabled by default and relax it only for the NBA API session when the
        # operator explicitly opts in.
        verify_proxy_ssl = os.getenv('NBA_API_PROXY_VERIFY_SSL', 'true').strip().lower()
        verify_proxy_ssl = verify_proxy_ssl not in {'0', 'false', 'no', 'off'}
        NBAStatsHTTP.get_session().verify = verify_proxy_ssl if nba_proxy else True

        timeout = kwargs.pop('timeout', 8)
        supplied_headers = kwargs.pop('headers', None)
        for attempt in range(max_retries):
            try:
                # Back off only after a failed attempt; do not delay healthy calls.
                if attempt:
                    delay = 0.5 * (2 ** (attempt - 1)) + random.uniform(0.1, 0.3)
                    time.sleep(delay)
                
                # Use fresh headers every attempt to rotate User-Agent
                headers = get_random_headers()
                if supplied_headers:
                    headers.update(supplied_headers)
                
                return api_func(**kwargs, headers=headers, timeout=timeout)
            except Exception as e:
                # Endpoint schema/argument errors do not mean the entire host
                # is down. Only connectivity or blocking/server HTTP failures
                # should suspend other, potentially healthy endpoints.
                transport_failure = isinstance(e, (ConnectionError, Timeout, TimeoutError))
                if isinstance(e, HTTPError) and e.response is not None:
                    transport_failure = e.response.status_code in {403, 429} or e.response.status_code >= 500
                log.debug("API attempt %s/%s for %s failed: %s", attempt + 1, max_retries, func_name, type(e).__name__)
                if not transport_failure:
                    raise
                if attempt == max_retries - 1:
                    self._nba_stats_unavailable_until = (
                        time.monotonic() + self.NBA_STATS_CIRCUIT_SEC
                    )
                    raise

    def get_player_id(self, player_name):
        from nba_api.stats.static import players

        if not isinstance(player_name, str) or not player_name.strip():
            return None
        nba_players = players.get_players()
        normalized_query = normalize_name(player_name)

        for player in nba_players:
            if normalize_name(player['full_name']) == normalized_query:
                return player['id']

        # Only accept an unambiguous token/substring fallback.
        partials = [
            player for player in nba_players
            if normalized_query in normalize_name(player.get('full_name', ''))
        ]
        if len(partials) == 1:
            log.info(f"Partial match found: {partials[0]['full_name']} for {player_name}")
            return partials[0]['id']
        if len(partials) > 1:
            log.warning(f"Ambiguous player name {player_name!r}; found {len(partials)} matches.")
            return None

        log.warning(f"Player {player_name} not found in static list.")
        return None

    def get_team_id(self, team_abbreviation):
        from nba_api.stats.static import teams
        if not isinstance(team_abbreviation, str):
            return None
        team_abbreviation = self._normalize_espn_abbreviation(team_abbreviation)
        nba_teams = teams.get_teams()
        for team in nba_teams:
            if team['abbreviation'] == team_abbreviation:
                return team['id']
        return None

    @classmethod
    def _normalize_espn_abbreviation(cls, abbreviation):
        value = str(abbreviation or '').strip().upper()
        return cls.ESPN_ABBREVIATION_MAP.get(value, value)

    @staticmethod
    def _espn_season_year(season):
        match = re.fullmatch(r'(\d{4})-(\d{2})', str(season or ''))
        if not match:
            raise ValueError('season must use YYYY-YY format')
        year = int(match.group(1)) + 1
        if year % 100 != int(match.group(2)):
            raise ValueError('season years must be consecutive')
        return year

    @staticmethod
    def _espn_json(response, source_name):
        try:
            payload = response.json()
        except Exception as exc:
            raise DataUnavailableError(f'{source_name} returned invalid JSON') from exc
        if not isinstance(payload, dict):
            raise DataUnavailableError(f'{source_name} returned an invalid payload')
        return payload

    def _espn_player_identity(self, player_id):
        """Resolve an NBA player ID to ESPN's athlete ID using an exact name match."""
        key = f'espn_identity_{int(player_id)}'
        cached = self._get_from_cache(key)
        if cached is not None:
            return cached

        from nba_api.stats.static import players

        nba_player = next(
            (item for item in players.get_players() if int(item.get('id', 0)) == int(player_id)),
            None,
        )
        if not nba_player:
            raise DataUnavailableError(f'NBA player {player_id} is not in the static directory')
        player_name = nba_player['full_name']
        response = self._retry_http_get(
            self.ESPN_SEARCH_URL,
            params={'query': player_name, 'limit': 10},
            timeout=8,
            max_retries=2,
        )
        payload = self._espn_json(response, 'ESPN player search')
        candidates = []
        for group in payload.get('results', []):
            if not isinstance(group, dict) or group.get('type') != 'player':
                continue
            for item in group.get('contents', []):
                if not isinstance(item, dict):
                    continue
                if str(item.get('description') or '').upper() != 'NBA':
                    continue
                if normalize_name(item.get('displayName', '')) != normalize_name(player_name):
                    continue
                uid_match = re.search(r'~a:(\d+)', str(item.get('uid') or ''))
                web_link = (item.get('link') or {}).get('web') if isinstance(item.get('link'), dict) else ''
                link_match = re.search(r'/id/(\d+)', str(web_link or ''))
                match = uid_match or link_match
                if match:
                    candidates.append({
                        'athlete_id': int(match.group(1)),
                        'player_name': item.get('displayName') or player_name,
                    })
        unique_ids = {candidate['athlete_id'] for candidate in candidates}
        if len(unique_ids) != 1:
            raise DataUnavailableError(
                f'ESPN player mapping for {player_name} was not unique'
            )
        identity = candidates[0]
        self._set_cache(key, identity)
        return identity

    def _espn_player_resource(self, player_id, resource, season):
        identity = self._espn_player_identity(player_id)
        season_year = self._espn_season_year(season)
        key = f'espn_{resource}_{identity["athlete_id"]}_{season_year}'
        cached = self._get_from_cache(key)
        cached_at = self._cache_loaded_at.get(key)
        if cached is not None and cached_at is not None and time.monotonic() - cached_at < self.NBA_STATS_CIRCUIT_SEC:
            return identity, cached
        response = self._retry_http_get(
            self.ESPN_PLAYER_URL.format(
                athlete_id=identity['athlete_id'], resource=resource,
            ),
            params={
                'region': 'us', 'lang': 'en', 'contentorigin': 'espn',
                'season': season_year,
            },
            timeout=12,
            max_retries=2,
        )
        payload = self._espn_json(response, f'ESPN player {resource}')
        self._set_cache(key, payload)
        self._cache_loaded_at[key] = time.monotonic()
        return identity, payload

    @staticmethod
    def _espn_category_row(payload, category_name, season_year):
        for category in payload.get('categories', []):
            if not isinstance(category, dict) or category.get('name') != category_name:
                continue
            names = category.get('names') or []
            for row in reversed(category.get('statistics') or []):
                if not isinstance(row, dict):
                    continue
                if (row.get('season') or {}).get('year') != season_year:
                    continue
                values = row.get('stats') or []
                return row, {
                    name: values[index] if index < len(values) else None
                    for index, name in enumerate(names)
                }
        return None, {}

    def _espn_common_player_info(self, player_id, season=None):
        season = season or self.season
        identity, payload = self._espn_player_resource(player_id, 'stats', season)
        season_year = self._espn_season_year(season)
        stats_row, _ = self._espn_category_row(payload, 'averages', season_year)
        if not stats_row:
            raise DataUnavailableError('ESPN has no season row for this player')

        espn_team_id = str(stats_row.get('teamId') or '')
        team_abbreviation = None
        teams_payload = payload.get('teams') or {}
        teams = teams_payload.values() if isinstance(teams_payload, dict) else teams_payload
        for team in teams:
            if isinstance(team, dict) and str(team.get('id') or '') == espn_team_id:
                team_abbreviation = self._normalize_espn_abbreviation(
                    team.get('abbreviation')
                )
                break
        team_id = self.get_team_id(team_abbreviation) if team_abbreviation else None
        if not team_id:
            raise DataUnavailableError('ESPN player team could not be mapped to the NBA')
        self.mark_data_degraded(
            'player identity came from ESPN season statistics; current roster is unverified'
        )
        return pd.DataFrame([{
            'PERSON_ID': int(player_id),
            'DISPLAY_FIRST_LAST': identity['player_name'],
            'TEAM_ID': team_id,
            'TEAM_ABBREVIATION': team_abbreviation,
            'POSITION': stats_row.get('position') or 'F',
        }])

    def _espn_player_gamelog(self, player_id, season, as_of=None):
        _, gamelog_payload = self._espn_player_resource(player_id, 'gamelog', season)

        stat_names = gamelog_payload.get('names') or []
        event_stats = {}
        for season_type in gamelog_payload.get('seasonTypes', []):
            display_name = str((season_type or {}).get('displayName') or '').lower()
            if 'regular season' not in display_name and 'postseason' not in display_name:
                continue
            for category in (season_type or {}).get('categories', []):
                for item in (category or {}).get('events', []):
                    if not isinstance(item, dict) or not item.get('eventId'):
                        continue
                    values = item.get('stats') or []
                    event_stats[str(item['eventId'])] = {
                        name: values[index] if index < len(values) else None
                        for index, name in enumerate(stat_names)
                    }

        rows = []
        for event_id, values in event_stats.items():
            event = (gamelog_payload.get('events') or {}).get(event_id) or {}
            rebounds = _finite_number(values.get('totalRebounds'), None, minimum=0)
            minutes = _finite_number(values.get('minutes'), None, minimum=0)
            if rebounds is None or minutes is None:
                continue
            team_abbreviation = self._normalize_espn_abbreviation(
                (event.get('team') or {}).get('abbreviation')
            )
            opponent = self._normalize_espn_abbreviation(
                (event.get('opponent') or {}).get('abbreviation')
            )
            raw_date = str(event.get('gameDate') or '')
            try:
                game_time = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                if game_time.tzinfo is None:
                    game_time = game_time.replace(tzinfo=timezone.utc)
                game_date = game_time.astimezone(ZoneInfo('America/New_York')).date().isoformat()
            except ValueError:
                continue
            separator = '@' if str(event.get('atVs') or '').strip() == '@' else 'vs.'
            rows.append({
                'GAME_ID': event_id,
                'GAME_DATE': game_date,
                'MATCHUP': f'{team_abbreviation} {separator} {opponent}',
                'TEAM_ID': self.get_team_id(team_abbreviation),
                'MIN': minutes,
                'REB': rebounds,
            })
        if not rows:
            raise DataUnavailableError('ESPN returned no usable player games')
        self.mark_data_degraded(
            'ESPN provides total rebounds only; split-dependent matchup adjustments are disabled'
        )
        frame = self._prepare_gamelog(pd.DataFrame(rows), as_of)
        frame.attrs['total_rebounds_only'] = True
        return frame

    @staticmethod
    def _prepare_gamelog(df, as_of=None):
        """Normalize date order and enforce the pre-game as-of cutoff."""
        if df.empty or 'GAME_DATE' not in df.columns:
            return df.reset_index(drop=True)
        result = df.copy()
        parsed = pd.to_datetime(result['GAME_DATE'], errors='coerce', format='mixed')
        result = result.loc[parsed.notna()].copy()
        parsed = parsed.loc[parsed.notna()]
        if as_of:
            # Forecasts for a game date may only use games completed before it.
            cutoff = pd.Timestamp(_parse_iso_date(as_of))
            keep = parsed.dt.normalize() < cutoff
            result = result.loc[keep].copy()
            parsed = parsed.loc[keep]
        result['_GAME_DATE_DT'] = parsed
        return (
            result.sort_values('_GAME_DATE_DT', ascending=False)
            .drop(columns=['_GAME_DATE_DT'])
            .reset_index(drop=True)
        )

    @_source_cache(seconds=2700)
    def get_player_gamelog(self, player_id, as_of=None):
        """Fetch a player's logs, optionally restricted to games before ``as_of``."""
        if isinstance(player_id, bool) or not isinstance(player_id, Real) or not math.isfinite(float(player_id)) or int(player_id) <= 0:
            raise ValueError("player_id must be a positive number")
        season = _season_for_date(as_of) if as_of else self.season
        date_to = _date_to_parameter(as_of)
        dfs = []
        failures = []
        for season_type in NBA_SEASON_TYPES:
            try:
                period_log = self._retry_api_call(
                    playergamelog.PlayerGameLog,
                    player_id=int(player_id), season=season,
                    season_type_all_star=season_type,
                    date_to_nullable=date_to,
                ).get_data_frames()[0]
                if not period_log.empty:
                    dfs.append(period_log)
            except Exception as e:
                log.warning(
                    "Failed to fetch %s logs for player %s: %s",
                    season_type, player_id, e,
                )
                failures.append(e)

        if failures:
            log.warning(
                "NBA player gamelog unavailable for %s; trying ESPN fallback.",
                player_id,
            )
            try:
                return self._espn_player_gamelog(
                    int(player_id), season, as_of=as_of,
                )
            except Exception as fallback_error:
                raise DataUnavailableError(
                    f"player gamelog history is unavailable for {player_id}"
                ) from fallback_error
        df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

        return self._prepare_gamelog(df, as_of)

    @ttl_cache(seconds=2700)
    def get_team_gamelog(self, team_id, as_of=None):
        """Fetch a team's logs, optionally restricted to games before ``as_of``."""
        if isinstance(team_id, bool) or not isinstance(team_id, Real) or not math.isfinite(float(team_id)) or int(team_id) <= 0:
            raise ValueError("team_id must be a positive number")
        season = _season_for_date(as_of) if as_of else self.season
        date_to = _date_to_parameter(as_of)
        dfs = []
        failures = []
        for season_type in NBA_SEASON_TYPES:
            try:
                period_log = self._retry_api_call(
                    teamgamelog.TeamGameLog,
                    team_id=int(team_id), season=season,
                    season_type_all_star=season_type,
                    date_to_nullable=date_to,
                ).get_data_frames()[0]
                if not period_log.empty:
                    dfs.append(period_log)
            except Exception as e:
                log.warning(
                    "Failed to fetch %s logs for team %s: %s",
                    season_type, team_id, e,
                )
                failures.append(e)

        if failures:
            raise DataUnavailableError(
                f"team gamelog history is incomplete for {team_id}"
            ) from failures[-1]
        df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

        return self._prepare_gamelog(df, as_of)

    def _as_of_context(self, as_of=None):
        if not as_of:
            return self.season, '', 'current'
        parsed = _parse_iso_date(as_of)
        return _season_for_date(parsed), _date_to_parameter(parsed), parsed.isoformat()

    @staticmethod
    def _first_frame(response, source_name):
        frames = response.get_data_frames()
        if not frames or not isinstance(frames[0], pd.DataFrame):
            raise DataUnavailableError(f"{source_name} returned no tabular data")
        return frames[0]

    def _fetch_combined_dashboard(
        self, endpoint, source_name, id_column, *, games_column='GP', **kwargs
    ):
        """Fetch and games-weight Regular Season, PlayIn, and Playoffs data."""
        period_frames = []
        for season_type in NBA_SEASON_TYPES:
            try:
                response = self._retry_api_call(
                    endpoint,
                    season_type_all_star=season_type,
                    **kwargs,
                )
                period_frames.append(
                    self._first_frame(response, f'{source_name} ({season_type})')
                )
            except Exception as exc:
                raise DataUnavailableError(
                    f'{source_name} is incomplete; {season_type} failed'
                ) from exc
        return _combine_period_per_game_frames(
            period_frames, id_column, games_column=games_column
        )

    def get_team_stats(self, as_of=None):
        """Fetch per-game base team stats, optionally through the prior day."""
        season, date_to, cutoff_key = self._as_of_context(as_of)
        key = f"league_team_stats_base_{season}_{cutoff_key}"
        legacy_key = f"league_team_stats_base_{season}"
        if as_of is None and self._get_from_cache(legacy_key) is not None:
            return self._get_from_cache(legacy_key)
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)

        df = self._fetch_combined_dashboard(
            leaguedashteamstats.LeagueDashTeamStats,
            'team base stats', 'TEAM_ID',
            season=season, per_mode_detailed='PerGame', date_to_nullable=date_to,
        )
        self._set_cache(key, df)
        return df
    
    def get_team_advanced_stats(self, as_of=None):
        """Fetch advanced team stats, optionally through the prior day."""
        season, date_to, cutoff_key = self._as_of_context(as_of)
        key = f"league_team_stats_advanced_{season}_{cutoff_key}"
        legacy_key = f"league_team_stats_advanced_{season}"
        if as_of is None and self._get_from_cache(legacy_key) is not None:
            return self._get_from_cache(legacy_key)
        if self._get_from_cache(key) is not None:
             return self._get_from_cache(key)
        
        df = self._fetch_combined_dashboard(
            leaguedashteamstats.LeagueDashTeamStats,
            'team advanced stats', 'TEAM_ID',
            season=season, measure_type_detailed_defense='Advanced',
            per_mode_detailed='PerGame', date_to_nullable=date_to,
        )
        self._set_cache(key, df)
        return df
    
    def get_opponent_stats_per_game(self, as_of=None):
        """
        Get per-game stats allowed by each team (not position-level DvP).
        """
        season, date_to, cutoff_key = self._as_of_context(as_of)
        key = f"league_opponent_stats_{season}_{cutoff_key}"
        legacy_key = f"league_opponent_stats_{season}"
        if as_of is None and self._get_from_cache(legacy_key) is not None:
            return self._get_from_cache(legacy_key)
        if self._get_from_cache(key) is not None:
            return self._get_from_cache(key)

        # Falling back to offensive/base stats would silently invert the meaning
        # of every "allowed" feature, so surface an upstream failure instead.
        df = self._fetch_combined_dashboard(
            leaguedashteamstats.LeagueDashTeamStats,
            'team opponent stats', 'TEAM_ID',
            season=season, measure_type_detailed_defense='Opponent',
            per_mode_detailed='PerGame', date_to_nullable=date_to,
        )
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

    @_source_cache(seconds=6 * 60 * 60)
    def get_common_player_info(self, player_id):
        log.debug(f"Getting info for player {player_id}")
        
        try:
            info = self._retry_api_call(
                commonplayerinfo.CommonPlayerInfo,
                max_retries=1,
                timeout=8,
                player_id=player_id,
            )
            df = info.get_data_frames()[0]
        except Exception as exc:
            log.warning(
                "NBA common player info unavailable for %s; trying ESPN fallback: %s",
                player_id,
                type(exc).__name__,
            )
            df = self._espn_common_player_info(int(player_id))
            self.mark_data_degraded('player identity came from ESPN season statistics; current roster is unverified')
        return df

    def get_team_roster(self, team_id, season=None):
        """Fetch a roster for the requested season (current season by default)."""
        from nba_api.stats.endpoints import commonteamroster
        season = season or self.season
        key = f"roster_{team_id}_{season}"
        cached = self._get_from_cache(key)
        cached_at = self._cache_loaded_at.get(key)
        if (
            cached is not None
            and cached_at is not None
            and time.monotonic() - cached_at < self.ROSTER_CACHE_TTL_SEC
        ):
             return cached
        
        roster = self._retry_api_call(
            commonteamroster.CommonTeamRoster,
            team_id=team_id, season=season
        )
        df = roster.get_data_frames()[0]
        self._set_cache(key, df)
        self._cache_loaded_at[key] = time.monotonic()
        return df

    def get_player_advanced_stats(self, player_id, as_of=None):
        """Fetches Advanced stats (REB_PCT etc) for a player"""
        season, date_to, cutoff_key = self._as_of_context(as_of)
        # Check if we have the full league data cached already
        league_key = f"league_player_stats_advanced_{season}_{cutoff_key}"
        legacy_key = f"league_player_stats_advanced_{season}"
        if as_of is None and self._get_from_cache(legacy_key) is not None:
            df = self._get_from_cache(legacy_key)
        else:
            df = self._get_from_cache(league_key)
        
        if df is None:
            from nba_api.stats.endpoints import leaguedashplayerstats
            df = self._fetch_combined_dashboard(
                leaguedashplayerstats.LeagueDashPlayerStats,
                'advanced player stats', 'PLAYER_ID',
                season=season, measure_type_detailed_defense='Advanced',
                per_mode_detailed='PerGame', date_to_nullable=date_to,
            )
            self._set_cache(league_key, df)
        
        # Filter for this player
        if 'PLAYER_ID' not in df.columns:
            raise DataUnavailableError("advanced player stats are missing PLAYER_ID")
        player_row = df[df['PLAYER_ID'] == player_id]
        return player_row

    def get_player_hustle_stats(self, player_id, as_of=None):
        """Fetches Hustle stats (BOX_OUTS etc) for a player"""
        season, date_to, cutoff_key = self._as_of_context(as_of)
        league_key = f"league_hustle_stats_{season}_{cutoff_key}"
        legacy_key = f"league_hustle_stats_{season}"
        df = self._get_from_cache(legacy_key) if as_of is None else None
        if df is None:
            df = self._get_from_cache(league_key)
        
        if df is None:
            from nba_api.stats.endpoints import leaguehustlestatsplayer
            df = self._fetch_combined_dashboard(
                leaguehustlestatsplayer.LeagueHustleStatsPlayer,
                'player hustle stats', 'PLAYER_ID', games_column='G',
                season=season, per_mode_time='PerGame', date_to_nullable=date_to,
            )
            self._set_cache(league_key, df)
            
        if 'PLAYER_ID' not in df.columns:
            return pd.DataFrame()
        player_row = df[df['PLAYER_ID'] == player_id]
        return player_row

    def get_player_rebounding_tracking_stats(self, player_id, as_of=None):
        """Fetches Rebounding Tracking stats (Contested %, Chance %, etc)"""
        season, date_to, cutoff_key = self._as_of_context(as_of)
        league_key = f"league_rebounding_tracking_{season}_{cutoff_key}"
        legacy_key = f"league_rebounding_tracking_{season}"
        df = self._get_from_cache(legacy_key) if as_of is None else None
        if df is None:
            df = self._get_from_cache(league_key)
        
        if df is None:
            from nba_api.stats.endpoints import leaguedashptstats
            try:
                df = self._fetch_combined_dashboard(
                    leaguedashptstats.LeagueDashPtStats,
                    'player rebounding tracking stats', 'PLAYER_ID',
                    season=season,
                    pt_measure_type='Rebounding',
                    player_or_team='Player', per_mode_simple='PerGame',
                    date_to_nullable=date_to,
                )
                self._set_cache(league_key, df)
            except Exception as e:
                log.debug(f"Failed to fetch rebounding tracking stats: {e}")
                import pandas as pd
                return pd.DataFrame()
            
        if 'PLAYER_ID' not in df.columns:
            return pd.DataFrame()
        player_row = df[df['PLAYER_ID'] == player_id]
        return player_row

    INJURY_DISK_CACHE = os.path.join(PROJECT_ROOT, 'data', 'injury_report.json')
    INJURY_CACHE_TTL_SEC = 20 * 60  # 20 minutes
    INJURY_STALE_MAX_SEC = 6 * 60 * 60
    INJURY_FAILURE_TTL_SEC = 2 * 60
    INJURY_MIN_SANITY_COUNT = 10    # fewer than this → scrape likely broken

    def _retry_http_get(self, url, *, params=None, headers=None, timeout=12, max_retries=3):
        """Bounded retries for non-NBA HTTP sources."""
        import requests

        last_error = None
        for attempt in range(max_retries):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=timeout)
                if response.status_code == 200:
                    return response
                last_error = DataUnavailableError(
                    f"HTTP {response.status_code} from {url.split('?')[0]}"
                )
                # Authentication and request-shape failures do not improve on retry.
                if response.status_code in {400, 401, 403, 404, 422}:
                    break
            except Exception as exc:
                last_error = exc
            if attempt < max_retries - 1:
                time.sleep(0.25 * (2 ** attempt) + random.uniform(0.0, 0.1))
        raise DataUnavailableError(f"request failed for {url.split('?')[0]}") from last_error

    @staticmethod
    def _decode_injury_cache(payload, file_mtime):
        """Read a timestamped injury cache with verifiable provenance."""
        if not isinstance(payload, dict):
            return None, None
        if isinstance(payload.get('injuries'), dict):
            timestamp = payload.get('timestamp')
            try:
                written_at = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
                if written_at.tzinfo is None:
                    written_at = written_at.replace(tzinfo=timezone.utc)
                written_epoch = written_at.timestamp()
            except (TypeError, ValueError) as exc:
                # Timestamped-format files must stand on their embedded
                # provenance. Falling back to mtime would make a freshly copied
                # corrupt/ancient report look current.
                raise ValueError("injury cache has an invalid embedded timestamp") from exc
            return payload['injuries'], written_epoch
        # A plain legacy mapping has no trustworthy age. In particular, a deploy
        # or file copy refreshes its mtime and can make old injuries actionable.
        raise ValueError("legacy injury cache has no embedded timestamp")

    def get_injury_report(self):
        """
        Fetches the current NBA injury report from CBS Sports and ESPN.
        Uses an in-memory cache + 20-min on-disk JSON cache to avoid hammering scrapers.
        Applies a sanity threshold: if the merged scrape returns suspiciously few rows,
        the in-memory cache is populated but the prior disk cache is *not* overwritten,
        so stale-but-real data survives a layout change.
        """
        key = "live_injury_report"
        timestamp_key = "live_injury_report_fetched_at"
        now = time.time()
        cached = self._get_from_cache(key)
        cached_at = self._get_from_cache(timestamp_key)
        if cached is not None and cached_at is not None and now - cached_at < self.INJURY_CACHE_TTL_SEC:
            return cached

        # 1. Try disk cache first.
        disk_injuries = None
        disk_age_sec = None
        if os.path.exists(self.INJURY_DISK_CACHE):
            try:
                file_mtime = os.path.getmtime(self.INJURY_DISK_CACHE)
                with open(self.INJURY_DISK_CACHE, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
                disk_injuries, disk_written_at = self._decode_injury_cache(payload, file_mtime)
                raw_disk_age_sec = now - disk_written_at
                if raw_disk_age_sec < -300:
                    raise ValueError("injury cache timestamp is implausibly far in the future")
                disk_age_sec = max(0.0, raw_disk_age_sec)
                if disk_age_sec < self.INJURY_CACHE_TTL_SEC and disk_injuries:
                    self._set_cache(key, disk_injuries)
                    self._set_cache(timestamp_key, now)
                    self._injury_report_metadata = {
                        'status': 'available',
                        'source': 'disk_cache',
                        'fetched_at': datetime.fromtimestamp(disk_written_at, timezone.utc).isoformat(),
                        'entry_count': len(disk_injuries),
                        'stale': False,
                    }
                    return disk_injuries
            except Exception as e:
                log.warning(f"Injury disk cache read failed: {e}")
        from bs4 import BeautifulSoup

        injuries = {}
        successful_sources = []

        # --- CBS SPORTS ---
        log.debug("Fetching CBS Injuries...")
        try:
            url = "https://www.cbssports.com/nba/injuries/"
            headers = get_random_headers()
            resp = self._retry_http_get(url, headers=headers, timeout=10)
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
            successful_sources.append('cbs')
        except Exception as e:
            log.warning(f"Could not fetch from CBS: {e}")

        # --- ESPN ---
        log.debug("Fetching ESPN Injuries...")
        try:
            url = "https://www.espn.com/nba/injuries"
            headers = get_random_headers()
            resp = self._retry_http_get(url, headers=headers, timeout=10)
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
            successful_sources.append('espn')
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
            if disk_injuries and disk_age_sec is not None and disk_age_sec <= self.INJURY_STALE_MAX_SEC:
                log.warning("Falling back to a bounded-age disk cache.")
                self._set_cache(key, disk_injuries)
                # Do not let the normal in-memory TTL extend a stale report past
                # the hard stale-age ceiling established for the disk cache.
                remaining_stale_sec = max(0.0, self.INJURY_STALE_MAX_SEC - disk_age_sec)
                reuse_sec = min(self.INJURY_CACHE_TTL_SEC, remaining_stale_sec)
                self._set_cache(
                    timestamp_key,
                    now - self.INJURY_CACHE_TTL_SEC + reuse_sec,
                )
                self._injury_report_metadata = {
                    'status': 'degraded',
                    'source': 'bounded_stale_disk_cache',
                    'fetched_at': datetime.fromtimestamp(disk_written_at, timezone.utc).isoformat(),
                    'entry_count': len(disk_injuries),
                    'stale': True,
                }
                return disk_injuries
            # Never treat an arbitrarily old report as current injury information.
            self._set_cache(key, injuries)
            self._set_cache(timestamp_key, now - self.INJURY_CACHE_TTL_SEC + self.INJURY_FAILURE_TTL_SEC)
            self._injury_report_metadata = {
                'status': 'degraded' if injuries else 'unavailable',
                'source': '+'.join(successful_sources) or None,
                'fetched_at': datetime.now(timezone.utc).isoformat(),
                'entry_count': len(injuries),
                'stale': False,
            }
            return injuries

        # Healthy scrape: write disk cache.
        try:
            _atomic_json_write(self.INJURY_DISK_CACHE, {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'injuries': injuries,
            })
        except Exception as e:
            log.warning(f"Injury disk cache write failed: {e}")

        self._set_cache(key, injuries)
        self._set_cache(timestamp_key, now)
        self._injury_report_metadata = {
            'status': 'available',
            'source': '+'.join(successful_sources) or 'live_scrape',
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'entry_count': len(injuries),
            'stale': False,
        }
        return injuries

    def get_likely_opponent_matchup(self, opponent_team_id, position, target_minutes=None, as_of=None):
        """
        Attempts to find the likely opponent player at a given position.
        If target_minutes is provided, it finds the player whose playing time 
        most closely matches the target (Starters vs Starters, Bench vs Bench).
        """
        if not opponent_team_id:
            return None
        season = _season_for_date(as_of) if as_of else self.season
        roster = self.get_team_roster(opponent_team_id, season=season)
        if roster.empty:
            return None

        # Trigger/load the as-of league data. PerGame MIN is required for depth.
        self.get_player_advanced_stats(0, as_of=as_of)
        _, _, cutoff_key = self._as_of_context(as_of)
        league_adv = self._get_from_cache(f"league_player_stats_advanced_{season}_{cutoff_key}")
        if league_adv is None and as_of is None:
            league_adv = self._get_from_cache(f"league_player_stats_advanced_{season}")
        if league_adv is None or not {'PLAYER_ID', 'MIN'}.issubset(league_adv.columns):
            return None
        if not {'PLAYER_ID', 'PLAYER', 'POSITION'}.issubset(roster.columns):
            return None

        # Merge roster with league stats to get minutes and positions
        roster_stats = pd.merge(roster, league_adv[['PLAYER_ID', 'MIN']], on='PLAYER_ID', how='inner')
        roster_stats['MIN'] = pd.to_numeric(roster_stats['MIN'], errors='coerce')
        roster_stats = roster_stats.dropna(subset=['MIN'])
        if roster_stats.empty:
            return None
        
        # Filter out injured players
        injury_report = self.get_injury_report() if _within_live_injury_window(as_of) else {}

        def check_status(name):
            norm_name = normalize_name(name)
            status = str(injury_report.get(norm_name, 'Active') or 'Active')
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
            player_pos = str(player_pos or '').upper()
            target_pos = str(target_pos or '').upper()
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
            target_minutes = _finite_number(target_minutes, None, minimum=0, maximum=48)
            if target_minutes is None:
                return None
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
            'injury_note': (
                None if likely_starter['injury_status'] == 'Active'
                else likely_starter['injury_status']
            )
        }

    DEFAULT_DAYS_REST = 2  # Neutral assumption when unknown; keeps rest_mult at 1.0

    def get_days_rest(self, team_id, as_of: str = None):
        """
        Days since the last game for a team.
        0 = played yesterday (B2B), 1 = played 2 days ago, etc.
        Uses DEFAULT_DAYS_REST (2 = neutral) whenever we can't compute a real value,
        so empty-log and parse-failure paths agree.
        """
        try:
            logs = self.get_team_gamelog(team_id, as_of=as_of)
        except Exception as exc:
            log.warning(
                "Team gamelog unavailable for rest calculation; using neutral rest: %s",
                exc,
            )
            self.mark_data_degraded(
                'team rest was unavailable and used the neutral assumption'
            )
            return self.DEFAULT_DAYS_REST
        if logs.empty:
            return self.DEFAULT_DAYS_REST

        if 'GAME_DATE' not in logs.columns:
            return self.DEFAULT_DAYS_REST
        last_game_date_str = logs.iloc[0]['GAME_DATE']
        try:
            from datetime import datetime
            try:
                last_date = datetime.strptime(last_game_date_str, "%b %d, %Y")
            except ValueError:
                last_date = datetime.strptime(last_game_date_str, "%Y-%m-%d")

            target_date = datetime.combine(_parse_iso_date(as_of), datetime.min.time()) if as_of else datetime.now()
            days_diff = (target_date - last_date).days
            # Downstream logic only distinguishes back-to-backs from rested
            # players. Cap long breaks (All-Star/offseason) to its validated
            # range instead of rejecting an otherwise valid projection.
            rest = min(14, max(0, days_diff - 1))
            log.debug(f"Team {team_id} last game: {last_game_date_str} -> {days_diff} days ago -> {rest} rest")
            return rest
        except Exception as e:
            log.warning(f"Error calculating rest for team {team_id}: {e}")
            return self.DEFAULT_DAYS_REST

    def _fetch_espn_games_for_date(self, requested_date):
        response = self._retry_http_get(
            self.ESPN_SCOREBOARD_URL,
            params={'dates': requested_date.replace('-', '')},
            timeout=10,
            max_retries=2,
        )
        payload = self._espn_json(response, 'ESPN scoreboard')
        if not isinstance(payload.get('events'), list):
            raise DataUnavailableError('ESPN scoreboard is missing its events list')
        games = []
        for event in payload['events']:
            if not isinstance(event, dict):
                raise DataUnavailableError('ESPN scoreboard contains an invalid event')
            try:
                event_time = datetime.fromisoformat(str(event.get('date')).replace('Z', '+00:00'))
                if event_time.tzinfo is None:
                    raise ValueError('missing timezone')
                event_date = event_time.astimezone(ZoneInfo('America/New_York')).date().isoformat()
            except ValueError as exc:
                raise DataUnavailableError('ESPN scoreboard contains an invalid date') from exc
            if event_date != requested_date:
                continue
            competitions = event.get('competitions') or []
            competition = competitions[0] if competitions else {}
            home_id = away_id = None
            for competitor in competition.get('competitors', []):
                abbreviation = self._normalize_espn_abbreviation(
                    ((competitor or {}).get('team') or {}).get('abbreviation')
                )
                nba_team_id = self.get_team_id(abbreviation)
                if (competitor or {}).get('homeAway') == 'home':
                    home_id = nba_team_id
                elif (competitor or {}).get('homeAway') == 'away':
                    away_id = nba_team_id
            if not home_id or not away_id:
                raise DataUnavailableError('ESPN scoreboard contains unknown teams')
            status = event.get('status') or competition.get('status') or {}
            status_type = status.get('type') or {}
            state = str(status_type.get('state') or '').lower()
            status_id = {'pre': 1, 'in': 2, 'post': 3}.get(state)
            if state == 'pre' and status_type.get('name') != 'STATUS_SCHEDULED':
                status_id = None
            game_id = str(event.get('id') or competition.get('id') or '')
            if not game_id:
                raise DataUnavailableError('ESPN scoreboard is missing a game ID')
            games.append({
                'game_id': game_id,
                'home_id': home_id,
                'away_id': away_id,
                'status': status_id,
                'status_text': (
                    status_type.get('shortDetail')
                    or status_type.get('detail')
                    or status_type.get('description')
                ),
                'game_time': status_type.get('shortDetail'),
                'game_date_est': event_date,
                'source': 'espn',
            })
        self.mark_data_degraded(
            'stats.nba.com schedule was unavailable; schedule verification used ESPN'
        )
        return games

    def _fetch_games_for_date(self, date_str):
        """Fetch a slate from NBA Stats, falling back to ESPN on an outage."""
        requested_date = _parse_iso_date(date_str).isoformat()
        from nba_api.stats.endpoints import scoreboardv2

        log.debug(f"Fetching games for {requested_date} via ScoreboardV2...")
        try:
            board = self._retry_api_call(
                scoreboardv2.ScoreboardV2,
                game_date=requested_date,
                timeout=8,
            )
        except Exception as exc:
            log.warning(
                "NBA scoreboard unavailable for %s; trying ESPN fallback: %s",
                requested_date,
                exc,
            )
            return self._fetch_espn_games_for_date(requested_date)
        try:
            games_dict = board.game_header.get_dict()
            headers = games_dict['headers']
            rows = games_dict['data']
        except (AttributeError, KeyError, TypeError) as exc:
            raise DataUnavailableError("ScoreboardV2 returned an invalid schema") from exc

        required = {'GAME_ID', 'HOME_TEAM_ID', 'VISITOR_TEAM_ID'}
        if not isinstance(headers, list) or not required.issubset(headers) or not isinstance(rows, list):
            raise DataUnavailableError("ScoreboardV2 response is missing required columns")

        indexes = {name: headers.index(name) for name in headers}

        def get_col(row, col_name):
            index = indexes.get(col_name)
            return row[index] if index is not None and index < len(row) else None

        games = []
        seen_game_ids = set()
        for row in rows:
            if not isinstance(row, (list, tuple)):
                raise DataUnavailableError("ScoreboardV2 contains a malformed game row")
            gid = get_col(row, 'GAME_ID')
            hid = get_col(row, 'HOME_TEAM_ID')
            vid = get_col(row, 'VISITOR_TEAM_ID')
            if not gid or not hid or not vid:
                log.warning("Skipping schedule row missing game/team identifiers")
                continue
            if gid in seen_game_ids:
                continue
            seen_game_ids.add(gid)
            games.append({
                'game_id': gid,
                'home_id': hid,
                'away_id': vid,
                'status': get_col(row, 'GAME_STATUS_ID'),
                'status_text': get_col(row, 'GAME_STATUS_TEXT'),
                'game_time': get_col(row, 'GAME_STATUS_TEXT'),
                'game_date_est': get_col(row, 'GAME_DATE_EST') or requested_date,
            })

        log.debug(f"ScoreboardV2 found {len(games)} unique games for {requested_date}.")
        return games

    @_source_cache(seconds=900, cache_empty=True)
    def get_games_for_date(self, date_str):
        """Return a cached, validated ScoreboardV2 slate for normal reads."""
        return self._fetch_games_for_date(date_str)

    def get_games_for_date_fresh(self, date_str):
        """Return a fresh slate, bypassing TTL state for pre-wager checks."""
        return self._fetch_games_for_date(date_str)

    @ttl_cache(seconds=300)
    def get_odds_for_game(self, api_key, home_team_code, away_team_code, date_str, bookmaker='fanduel'):
        """
        Targeted Odds Fetch:
        1. Get ALL events for the date (cheap/free-ish).
        2. Find the event matching the teams AND date.
        3. Get odds ONLY for that event ID (costs quota).
        """
        if not isinstance(api_key, str) or not api_key.strip():
            return {}
        requested_date = _parse_iso_date(date_str)
        home_team_code = str(home_team_code or '').strip().upper()
        away_team_code = str(away_team_code or '').strip().upper()
        bookmaker = str(bookmaker or '').strip().lower()
        if not home_team_code or not away_team_code or not bookmaker:
            raise ValueError("home team, away team, and bookmaker are required")

        log.debug(f"Deep-searching odds for {home_team_code} vs {away_team_code} on {bookmaker}...")
        events_url = "https://api.the-odds-api.com/v4/sports/basketball_nba/events"
        resp = self._retry_http_get(
            events_url,
            params={'apiKey': api_key, 'regions': 'us'},
            timeout=12,
        )
        try:
            events = resp.json()
        except Exception as exc:
            raise DataUnavailableError("Odds API returned invalid events JSON") from exc
        if not isinstance(events, list):
            raise DataUnavailableError("Odds API events response must be a list")

        team_map = {
            'ATL': 'Hawks', 'BOS': 'Celtics', 'BKN': 'Nets', 'CHA': 'Hornets', 'CHI': 'Bulls',
            'CLE': 'Cavaliers', 'DAL': 'Mavericks', 'DEN': 'Nuggets', 'DET': 'Pistons', 'GSW': 'Warriors',
            'HOU': 'Rockets', 'IND': 'Pacers', 'LAC': 'Clippers', 'LAL': 'Lakers', 'MEM': 'Grizzlies',
            'MIA': 'Heat', 'MIL': 'Bucks', 'MIN': 'Timberwolves', 'NOP': 'Pelicans', 'NYK': 'Knicks',
            'OKC': 'Thunder', 'ORL': 'Magic', 'PHI': '76ers', 'PHX': 'Suns', 'POR': 'Trail Blazers',
            'SAC': 'Kings', 'SAS': 'Spurs', 'TOR': 'Raptors', 'UTA': 'Jazz', 'WAS': 'Wizards'
        }
        h_name_part = team_map.get(home_team_code)
        a_name_part = team_map.get(away_team_code)
        if not h_name_part or not a_name_part:
            raise ValueError("unknown NBA team abbreviation")

        def event_eastern_date(raw_value):
            try:
                value = str(raw_value).replace('Z', '+00:00')
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(ZoneInfo('America/New_York')).date()
            except (TypeError, ValueError):
                return None

        target_event = None
        for event in events:
            if not isinstance(event, dict):
                continue
            e_home = str(event.get('home_team', ''))
            e_away = str(event.get('away_team', ''))
            teams_match = h_name_part.lower() in e_home.lower() and a_name_part.lower() in e_away.lower()
            if teams_match and event_eastern_date(event.get('commence_time')) == requested_date:
                target_event = event
                break

        if not target_event or not target_event.get('id'):
            log.debug("No matching Odds Event found.")
            return {}

        target_event_id = target_event['id']
        log.debug(f"Found Event ID {target_event_id}. Fetching props from {bookmaker}...")
        props_url = (
            "https://api.the-odds-api.com/v4/sports/basketball_nba/events/"
            f"{target_event_id}/odds"
        )
        props_params = {
            'apiKey': api_key,
            'regions': 'us',
            'bookmakers': bookmaker,
            'markets': 'player_rebounds,spreads',
            'oddsFormat': 'american',
        }
        try:
            p_resp = self._retry_http_get(props_url, params=props_params, timeout=15)
        except DataUnavailableError:
            # Some Odds API plans/providers reject mixed prop + game markets.
            # Preserve prop availability and mark spread as unavailable.
            log.info("Combined props/spread request unavailable; retrying player props only.")
            props_params['markets'] = 'player_rebounds'
            p_resp = self._retry_http_get(props_url, params=props_params, timeout=15)
        try:
            props_data = p_resp.json()
        except Exception as exc:
            raise DataUnavailableError("Odds API returned invalid props JSON") from exc
        if not isinstance(props_data, dict):
            raise DataUnavailableError("Odds API props response must be an object")

        fetched_at = datetime.now(timezone.utc).isoformat()
        player_sides = {}
        home_spread = None
        away_spread = None
        selected_book_title = bookmaker
        book_updated_at = None
        bookmakers = props_data.get('bookmakers', [])
        if not isinstance(bookmakers, list):
            raise DataUnavailableError("Odds API bookmakers field must be a list")

        for book in bookmakers:
            if not isinstance(book, dict):
                continue
            selected_book_title = book.get('title') or selected_book_title
            book_updated_at = book.get('last_update') or book_updated_at
            for market in book.get('markets', []):
                if not isinstance(market, dict):
                    continue
                outcomes = market.get('outcomes', [])
                if market.get('key') == 'spreads':
                    for outcome in outcomes:
                        spread_point = _finite_number(outcome.get('point'), minimum=-50, maximum=50)
                        if outcome.get('name') == target_event.get('home_team'):
                            home_spread = spread_point
                        elif outcome.get('name') == target_event.get('away_team'):
                            away_spread = spread_point
                    continue
                if market.get('key') != 'player_rebounds':
                    continue
                for outcome in outcomes:
                    side_name = str(outcome.get('name', '')).strip().title()
                    player_name = outcome.get('description')
                    if side_name not in {'Over', 'Under'} or not player_name:
                        continue
                    point = outcome.get('point')
                    price = outcome.get('price')
                    try:
                        point = float(point)
                        price_float = float(price)
                        price = int(price_float)
                    except (TypeError, ValueError):
                        continue
                    if (
                        not math.isfinite(point)
                        or not math.isfinite(price_float)
                        or price_float != price
                        or point < 0
                        or (-100 < price < 100)
                    ):
                        continue
                    quote_updated_at = market.get('last_update') or book_updated_at or fetched_at
                    normalized = normalize_name(player_name)
                    player_sides.setdefault(normalized, {})[side_name.lower()] = {
                        'line': point,
                        'point': point,
                        'odds': price,
                        'price': price,
                        'book': selected_book_title,
                        'bookmaker': bookmaker,
                        'source': 'the-odds-api',
                        'fetched_at': fetched_at,
                        'updated_at': quote_updated_at,
                    }

        player_props = {}
        for player_name, sides in player_sides.items():
            over = sides.get('over')
            under = sides.get('under')
            legacy_line = over['line'] if over else (under['line'] if under else None)
            legacy_odds = over['odds'] if over else None
            player_props[player_name] = {
                # Legacy fields intentionally remain the Over quote.
                'line': legacy_line,
                'odds': legacy_odds,
                'over_odds': over['odds'] if over else None,
                'under_odds': under['odds'] if under else None,
                'over': over,
                'under': under,
                'prices': {
                    'Over': over['odds'] if over else None,
                    'Under': under['odds'] if under else None,
                },
                'book': selected_book_title,
                'book_key': bookmaker,
                'event_id': target_event_id,
                'fetched_at': fetched_at,
                'updated_at': (
                    (over or under).get('updated_at') if (over or under) else book_updated_at
                ),
                'source': 'the-odds-api',
                'home_spread': home_spread,
            }

        player_props['_meta'] = {
            'event_id': target_event_id,
            'book': selected_book_title,
            'book_key': bookmaker,
            'fetched_at': fetched_at,
            'updated_at': book_updated_at or fetched_at,
            'source': 'the-odds-api',
            'commence_time': target_event.get('commence_time'),
            'home_spread': home_spread,
            'away_spread': away_spread,
        }
        return player_props
