"""SQLite access + schema. One file, zero setup (roadmap §3)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

import pandas as pd

from .config import DB_PATH

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
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
    return len(df)


def read_df(query: str, params: tuple = ()) -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(query, conn, params=params)
