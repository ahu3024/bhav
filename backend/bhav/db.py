"""SQLite access + schema. One file, zero setup (roadmap §3)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

import pandas as pd

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS ndvi (
    district TEXT NOT NULL,
    date     TEXT NOT NULL,
    value    REAL NOT NULL,
    PRIMARY KEY (district, date)
);

CREATE TABLE IF NOT EXISTS weather (
    district   TEXT NOT NULL,
    date       TEXT NOT NULL,
    rainfall   REAL,
    temp_max   REAL,
    temp_min   REAL,
    PRIMARY KEY (district, date)
);

CREATE TABLE IF NOT EXISTS mandi_price (
    district         TEXT NOT NULL,
    crop             TEXT NOT NULL,
    date             TEXT NOT NULL,
    market           TEXT NOT NULL,
    price_per_quintal REAL NOT NULL,
    arrivals_tonnes   REAL,
    PRIMARY KEY (district, crop, date, market)
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
