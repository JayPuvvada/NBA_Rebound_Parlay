"""Persistent local Odds API accounting. All attempts reserve before network I/O."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


class OddsBudgetError(RuntimeError):
    code = 'budget_limit'


class OddsBusyError(OddsBudgetError):
    code = 'request_in_progress'


def _limit(name, default):
    try:
        value = int(os.environ.get(name, default))
        return max(0, value)
    except (TypeError, ValueError):
        return default


class OddsStore:
    def __init__(self, path=None, api_key='', *, clock=time.time):
        self.path = str(path or os.environ.get('ODDS_CACHE_PATH') or
                        Path(__file__).resolve().parents[1] / 'data' / 'odds-cache.db')
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.namespace = hashlib.sha256(api_key.encode()).hexdigest()
        self.clock = clock
        with self.connection() as db:
            db.executescript('''
                create table if not exists odds_cache (
                    namespace text, cache_key text, payload text not null,
                    fetched real not null, expires real not null,
                    primary key(namespace, cache_key));
                create table if not exists odds_meta (
                    namespace text primary key, cycle integer not null default 0,
                    provider_used integer not null default -1,
                    remaining integer not null default -1, checked real not null default 0);
                create table if not exists odds_charge (
                    id text primary key, namespace text not null, day text not null,
                    cycle integer not null, cost integer not null, resolved integer not null default 0);
                create index if not exists odds_charge_scope on odds_charge(namespace,cycle,day);
                create table if not exists odds_lease (
                    namespace text, lease_key text, owner text not null, expires real not null,
                    primary key(namespace,lease_key));
            ''')
            db.execute('insert or ignore into odds_meta(namespace) values (?)', (self.namespace,))
            # Upgrade existing local stores without resetting reservations.
            if not db.in_transaction:
                db.execute('begin immediate')
            if 'provider_date' not in {row[1] for row in db.execute('pragma table_info(odds_meta)')}:
                db.execute('alter table odds_meta add column provider_date real')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def cached(self, key, *, stale=False):
        with self.connection() as db:
            row = db.execute('select * from odds_cache where namespace=? and cache_key=?',
                             (self.namespace, key)).fetchone()
        if not row or (not stale and row['expires'] <= self.clock()):
            return None
        try:
            return json.loads(row['payload'])
        except (ValueError, TypeError):
            return None

    def cache(self, key, payload, ttl):
        now = self.clock()
        with self.connection() as db:
            db.execute('insert or replace into odds_cache values (?,?,?,?,?)',
                       (self.namespace, key, json.dumps(payload, allow_nan=False), now, now + ttl))

    @contextmanager
    def lease(self, key, seconds=90):
        owner, now = uuid.uuid4().hex, self.clock()
        with self.connection() as db:
            db.execute('begin immediate')
            row = db.execute('select expires from odds_lease where namespace=? and lease_key=?',
                             (self.namespace, key)).fetchone()
            if row and row['expires'] > now:
                raise OddsBusyError('A shared sportsbook request is already running. Retry shortly.')
            db.execute('insert or replace into odds_lease values (?,?,?,?)',
                       (self.namespace, key, owner, now + seconds))
        try:
            yield
        finally:
            with self.connection() as db:
                db.execute('delete from odds_lease where namespace=? and lease_key=? and owner=?',
                           (self.namespace, key, owner))

    @staticmethod
    def _header_int(headers, name):
        try:
            value = headers[name]
            if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit():
                raise ValueError
            return int(value)
        except (KeyError, TypeError, ValueError):
            return None

    def _observe_db(self, db, headers):
        used = self._header_int(headers, 'x-requests-used')
        remaining = self._header_int(headers, 'x-requests-remaining')
        if used is None or remaining is None:
            return False
        try:
            raw_date = headers.get('date') or headers.get('Date')
            provider_date = parsedate_to_datetime(raw_date).timestamp() if raw_date else None
        except (TypeError, ValueError, OverflowError):
            provider_date = None
        row = db.execute('select * from odds_meta where namespace=?', (self.namespace,)).fetchone()
        if provider_date is not None and row['provider_date'] is not None and provider_date < row['provider_date']:
            return False
        reset = row['provider_used'] >= 0 and used < row['provider_used'] and remaining > row['remaining']
        if reset:
            # An undated or older snapshot must never refill the monthly budget.
            if provider_date is None or (row['provider_date'] is not None and provider_date <= row['provider_date']):
                return False
            # A timed-out attempt could still have reached the new cycle.
            # Keep ambiguous reservations until a response can reconcile them.
            db.execute('update odds_charge set cycle=? where namespace=? and cycle=? and resolved=0',
                       (row['cycle'] + 1, self.namespace, row['cycle']))
        elif row['provider_used'] >= 0:
            used = max(used, row['provider_used'])
            remaining = min(remaining, row['remaining'])
        db.execute('update odds_meta set cycle=?,provider_used=?,remaining=?,checked=?,provider_date=? where namespace=?',
                   (row['cycle'] + int(reset), used, remaining, self.clock(),
                    provider_date if provider_date is not None else row['provider_date'], self.namespace))
        return True

    def observe(self, headers):
        with self.connection() as db:
            db.execute('begin immediate')
            return self._observe_db(db, headers)

    def snapshot(self):
        day = datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()
        with self.connection() as db:
            db.execute('begin')
            row = db.execute('select * from odds_meta where namespace=?', (self.namespace,)).fetchone()
            used = db.execute('select coalesce(sum(cost),0) from odds_charge where namespace=? and cycle=?',
                              (self.namespace, row['cycle'])).fetchone()[0]
            daily = db.execute('select coalesce(sum(cost),0) from odds_charge where namespace=? and day=?',
                               (self.namespace, day)).fetchone()[0]
        return {'daily_used': daily, 'daily_limit': _limit('ODDS_DAILY_CREDITS', 16),
                'cycle_used': used, 'cycle_limit': _limit('ODDS_CYCLE_CREDITS', 450),
                'provider_remaining': row['remaining'] if row['remaining'] >= 0 else None,
                'reserve': _limit('ODDS_CREDIT_RESERVE', 50), 'checked_at': row['checked'] or None}

    def reserve(self, cost):
        if isinstance(cost, bool) or not isinstance(cost, int) or cost <= 0:
            raise ValueError('A positive integer credit reservation is required')
        day = datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()
        charge = uuid.uuid4().hex
        with self.connection() as db:
            db.execute('begin immediate')
            meta = db.execute('select * from odds_meta where namespace=?', (self.namespace,)).fetchone()
            cycle_used = db.execute('select coalesce(sum(cost),0) from odds_charge where namespace=? and cycle=?',
                                    (self.namespace, meta['cycle'])).fetchone()[0]
            daily_used = db.execute('select coalesce(sum(cost),0) from odds_charge where namespace=? and day=?',
                                    (self.namespace, day)).fetchone()[0]
            outstanding = db.execute('select coalesce(sum(cost),0) from odds_charge where namespace=? and cycle=? and resolved=0',
                                     (self.namespace, meta['cycle'])).fetchone()[0]
            if meta['remaining'] < 0:
                raise OddsBudgetError('Sportsbook usage could not be verified. Cached quotes and manual inputs remain available.')
            if (daily_used + cost > _limit('ODDS_DAILY_CREDITS', 16)
                    or cycle_used + cost > _limit('ODDS_CYCLE_CREDITS', 450)
                    or meta['remaining'] - outstanding - cost < _limit('ODDS_CREDIT_RESERVE', 50)):
                raise OddsBudgetError('The shared sportsbook refresh budget has been reached. Use cached quotes or enter a price.')
            db.execute('insert into odds_charge values (?,?,?,?,?,0)',
                       (charge, self.namespace, day, meta['cycle'], cost))
        return charge

    def reconcile(self, charge, headers):
        """Atomically account for the actual charge and its provider cycle."""
        actual = self._header_int(headers, 'x-requests-last')
        with self.connection() as db:
            db.execute('begin immediate')
            reservation = db.execute('select * from odds_charge where namespace=? and id=?',
                                     (self.namespace, charge)).fetchone()
            if reservation is None or reservation['resolved']:
                return
            previous = db.execute('select * from odds_meta where namespace=?', (self.namespace,)).fetchone()
            observed = self._observe_db(db, headers)
            if actual is None:
                return  # Keep the worst-case reservation when cost is missing.
            current = db.execute('select * from odds_meta where namespace=?', (self.namespace,)).fetchone()
            db.execute('update odds_charge set cost=?,resolved=1,cycle=? where namespace=? and id=?',
                       (actual, current['cycle'], self.namespace, charge))
            if not observed:
                # A cost-only response must still consume known remaining credit.
                # Otherwise repeated responses could spend through the reserve.
                db.execute('update odds_meta set remaining=max(-1,remaining-?),provider_used=case when provider_used<0 then -1 else provider_used+? end where namespace=?',
                           (actual, actual, self.namespace))
            elif current['cycle'] == previous['cycle'] and actual:
                # Even a repeated usage header cannot make a known paid charge
                # free. Keep the stricter of the provider and local accounting.
                db.execute('update odds_meta set remaining=min(remaining,?),provider_used=max(provider_used,?) where namespace=?',
                           (max(-1, previous['remaining'] - actual), previous['provider_used'] + actual, self.namespace))


def metered_request(send, api_key, cost, *, timeout_for=None):
    """Wrap one paid attempt, including legacy endpoints. Never logs credentials."""
    if os.environ.get('ODDS_BUDGET_ENABLED') == '0':
        return send()
    if (os.environ.get('VERCEL') == '1' or os.environ.get('RENDER') == 'true') and not os.environ.get('ODDS_CACHE_PATH'):
        raise OddsBudgetError('Persistent sportsbook accounting must be configured before hosted refreshes are enabled.')
    store = OddsStore(api_key=api_key)
    # One paid connection at a time keeps usage-header reconciliation ordered.
    with store.lease('provider-request'):
        state = store.snapshot()
        if state['checked_at'] is None or store.clock() - state['checked_at'] > 900:
            import requests
            try:
                response = requests.get('https://api.the-odds-api.com/v4/sports',
                                        params={'apiKey': api_key}, timeout=timeout_for(8) if timeout_for else 8)
                if response.status_code != 200 or not store.observe(response.headers):
                    raise OddsBudgetError('Sportsbook usage could not be verified. Retry later.')
            except OddsBudgetError:
                raise
            except Exception:
                raise OddsBudgetError('Sportsbook usage could not be verified. Retry later.') from None
        charge = store.reserve(cost)
        response = send()
        store.reconcile(charge, response.headers)
        return response
