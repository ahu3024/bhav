"""SQLite access + schema. One file, zero setup (roadmap §3)."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Iterator

import pandas as pd

from .config import DB_PATH

# Long enough to ride out a nightly ingest's write transaction, short enough
# that a genuinely wedged lock still surfaces as an error rather than a hang.
SQLITE_TIMEOUT = 30.0

SCHEMA = """
-- One row per 10-day Sentinel-2 composite, at the satellite's own cadence.
-- `date` is the composite period start; `obs_date` is the last real pass that
-- went into it. Daily alignment + ndvi_obs_age_days happen in features.py, so
-- this table stays an honest record of what was actually observed.
CREATE TABLE IF NOT EXISTS ndvi (
    district   TEXT NOT NULL,
    date       TEXT NOT NULL,
    value      REAL NOT NULL,   -- clear-pixel mean NDVI over the AOI
    pct_mature REAL,            -- share of clear pixels below the maturity cut
    clear_frac REAL,            -- mean clear-pixel coverage of the AOI
    obs_date   TEXT,            -- latest satellite pass inside the composite
    n_obs      INTEGER,         -- scenes that contributed
    PRIMARY KEY (district, date)
);

-- Daily Open-Meteo archive for the belt centroid. Humidity and ET0 are here
-- because onion is stored, not just grown: warm + humid means the crop cannot
-- be held, and a farmer who cannot hold is a forced seller.
CREATE TABLE IF NOT EXISTS weather (
    district      TEXT NOT NULL,
    date          TEXT NOT NULL,
    rainfall      REAL,
    rain_hours    REAL,
    temp_max      REAL,
    temp_min      REAL,
    temp_mean     REAL,
    humidity_max  REAL,
    humidity_min  REAL,
    humidity_mean REAL,
    et0           REAL,   -- reference evapotranspiration: drying power
    wind_max      REAL,
    PRIMARY KEY (district, date)
);

-- One row per market per variety per trading day, as Agmarknet reports it.
-- District-level aggregation, gap handling, outlier caps and CPI deflation all
-- happen in prices.py so this table stays a faithful record of the source.
CREATE TABLE IF NOT EXISTS mandi_price (
    district        TEXT NOT NULL,
    crop            TEXT NOT NULL,
    date            TEXT NOT NULL,
    market          TEXT NOT NULL,
    variety         TEXT NOT NULL DEFAULT 'Other',
    arrivals_tonnes REAL,
    price_min       REAL,
    price_modal     REAL NOT NULL,
    price_max       REAL,
    PRIMARY KEY (district, crop, date, market, variety)
);

-- Annual India CPI (World Bank FP.CPI.TOTL, 2010 = 100) for deflation.
CREATE TABLE IF NOT EXISTS cpi (
    year      INTEGER PRIMARY KEY,
    cpi       REAL NOT NULL,
    estimated INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alerts (
    district        TEXT NOT NULL,
    date            TEXT NOT NULL,
    color           TEXT NOT NULL,
    window_start    TEXT,
    window_end      TEXT,
    expected_impact REAL,
    reason          TEXT,
    confidence      REAL,
    PRIMARY KEY (district, date)
);

-- Registrations (roadmap: phone, crop, village pin, usual sell window).
-- Phone is E.164 and is the key: one farmer, one row, re-registering updates.
CREATE TABLE IF NOT EXISTS subscribers (
    phone       TEXT PRIMARY KEY,
    name        TEXT,
    crop        TEXT,
    district    TEXT,
    village_pin TEXT,
    lang        TEXT NOT NULL DEFAULT 'en',
    sell_window TEXT,
    channel     TEXT NOT NULL DEFAULT 'whatsapp',
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT,
    updated_at  TEXT
);

-- Every send attempt, delivered or not. The failures are the useful half:
-- the sandbox silently rejects anyone who hasn't joined it.
CREATE TABLE IF NOT EXISTS message_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    phone        TEXT NOT NULL,
    alert_date   TEXT,
    lang         TEXT,
    channel      TEXT,
    sent         INTEGER NOT NULL DEFAULT 0,
    provider_sid TEXT,
    error        TEXT,
    body         TEXT,
    created_at   TEXT
);

CREATE TABLE IF NOT EXISTS warehouses (
    name     TEXT PRIMARY KEY,
    district TEXT,
    lat      REAL,
    lon      REAL,
    capacity REAL
);

-- Small key/value scratch. Holds `data_version`: a counter bumped whenever an
-- ingest rewrites a source table. Everything cacheable keys off it, so a
-- subscription or an alert row -- writes that change nothing a model reads --
-- no longer look like new data. See data_version() below.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets readers keep serving while an ingest writes, which is the whole
    # difference between "the pipeline refreshes" and "the API 500s for a
    # minute every night". busy_timeout covers the brief exclusive moments WAL
    # still needs (checkpoint, schema change) instead of failing instantly.
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(f"PRAGMA busy_timeout = {int(SQLITE_TIMEOUT * 1000)}")
    except sqlite3.OperationalError:
        # A read-only mount cannot switch journal mode. Reads still work.
        pass
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def cursor() -> Iterator[sqlite3.Cursor]:
    conn = connect()
    try:
        yield conn.cursor()
        conn.commit()
    finally:
        conn.close()


def write_df(df: pd.DataFrame, table: str, if_exists: str = "replace") -> int:
    """Bulk-load a dataframe into a table. Used by the ingest scripts."""
    init_db()
    with connect() as conn:
        df.to_sql(table, conn, if_exists=if_exists, index=False)
    bump_data_version()
    return len(df)


def read_df(query: str, params: tuple = ()) -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(query, conn, params=params)


# --- data generation --------------------------------------------------------
#
# "Has the data changed?" used to be answered with the database file's mtime,
# and that was wrong in a way that cost a full feature rebuild per request: the
# API writes an alert row while serving /alert/today, which moves the mtime,
# which invalidated the cache the *next* request needed. Row counts have the
# same problem in reverse -- an ingest that corrects a value without adding a
# row would go unnoticed.
#
# So the ingest path states it outright. `write_df` bumps a counter, and
# everything cacheable keys off that counter. Writes that no model reads --
# subscriptions, alert rows, the message log -- leave it alone by construction.


# data_version() is read on every cached lookup, including inside the
# track-record walk that scores hundreds of dates, so it must not cost a sqlite
# connection each time. One second of staleness is invisible next to a pipeline
# that runs nightly, and a local bump clears the memo outright.
_VERSION_MEMO: tuple[float, str] | None = None
_VERSION_TTL = 1.0


def bump_data_version() -> str:
    """Record that a source table was rewritten. Returns the new version."""
    global _VERSION_MEMO
    _VERSION_MEMO = None
    version = f"{time.time_ns()}"
    try:
        with cursor() as cur:
            cur.execute(
                "INSERT INTO meta (key, value) VALUES ('data_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (version,),
            )
    except sqlite3.Error:
        return data_version()
    return version


def data_version() -> str:
    """A token that changes only when the pipeline rewrites a source table.

    Falls back to the file mtime for a database written before the meta table
    existed, so an older data/bhav.db still caches correctly (just coarsely).
    """
    global _VERSION_MEMO
    now = time.monotonic()
    if _VERSION_MEMO is not None and now - _VERSION_MEMO[0] < _VERSION_TTL:
        return _VERSION_MEMO[1]
    version = _read_data_version()
    _VERSION_MEMO = (now, version)
    return version


def _read_data_version() -> str:
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'data_version'"
            ).fetchone()
        if row and row["value"]:
            return str(row["value"])
    except sqlite3.Error:
        pass
    try:
        st = DB_PATH.stat()
        return f"mtime-{st.st_mtime_ns}-{st.st_size}"
    except OSError:
        return "absent"
