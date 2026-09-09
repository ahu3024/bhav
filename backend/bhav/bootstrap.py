"""Make a fresh host usable before the first request arrives.

The pipeline's output ships with the deploy as `data/seed.db` (plus
`models/*.pkl`), so a container image already carries a decade of NDVI, weather
and mandi prints and answers its first request with a real signal.

`seed.db` is a *separate file* from the live `data/bhav.db`, and that is the
point: the live database also holds `subscribers` and `message_log` — real phone
numbers and the text of every message sent to them. Committing that file would
put those numbers in git history, where a later deletion does not remove them,
and in every image built from the repo. `scripts/make_seed.py` copies across
only the tables the model reads, and refuses to write a snapshot that picked up
anything a person created.

The other half of the problem is that a container has nowhere durable to
*write*: its filesystem is thrown away on every deploy, so a subscription taken
at 11am is gone at the next push. Hence two roots (see config.py) — `SEED_*` is
the read-only copy inside the image, `DATA_DIR`/`MODELS_DIR` is where the
process actually works. This module copies seed -> live on first boot, never the
other way, so the shipped history is there on day one and the rows farmers
create survive every deploy after.

`BHAV_SEED_MODE` picks what a *later* deploy does with newer shipped data:

    missing   (default) copy only what isn't there yet. A redeploy carrying a
              fresher pipeline run is ignored — the disk is the truth.
    refresh   replace the source tables (ndvi, weather, mandi_price, cpi,
              warehouses) from the shipped copy, keeping subscribers, the
              message log and the alert history. This is what you want when the
              pipeline runs in CI and ships its output with the image.
    never     touch nothing; the disk is expected to be populated already.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

from .config import (
    DATA_DIR,
    DB_PATH,
    MODELS_DIR,
    SEED_DATA_DIR,
    SEED_MODELS_DIR,
)
from .db import bump_data_version, connect, init_db

# Rewritten wholesale by an ingest, and read by nothing but the model. These are
# safe to replace from a newer shipped snapshot.
SOURCE_TABLES = ("ndvi", "weather", "mandi_price", "cpi", "warehouses")
# Written by people using the service. Never overwritten from a seed.
LIVE_TABLES = ("subscribers", "message_log", "alerts")

SEED_DB = SEED_DATA_DIR / "seed.db"
SEED_MODE = os.getenv("BHAV_SEED_MODE", "missing").strip().lower()


def _row_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return 0


def _has_data(db: Path) -> bool:
    """Does this file hold a usable pipeline run, as opposed to bare schema?"""
    if not db.exists() or db.stat().st_size == 0:
        return False
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            return any(_row_count(conn, t) > 0 for t in ("mandi_price", "weather"))
    except sqlite3.Error:
        return False


def _seed_stamp() -> str:
    st = SEED_DB.stat()
    return f"{st.st_mtime_ns}-{st.st_size}"


def _copy_models() -> list[str]:
    """Bring the pickles across. Unlike the database these have no live half —
    a model file is either the one that shipped or one the disk already had."""
    if MODELS_DIR == SEED_MODELS_DIR:
        return []
    copied = []
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for src in sorted(SEED_MODELS_DIR.glob("*.pkl")):
        dst = MODELS_DIR / src.name
        if dst.exists() and SEED_MODE != "refresh":
            continue
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            continue
        shutil.copy2(src, dst)
        copied.append(src.name)
    return copied


def _refresh_source_tables() -> list[str]:
    """Replace the pipeline tables from the shipped snapshot, in one
    transaction, leaving every row a farmer created exactly where it is."""
    refreshed: list[str] = []
    with connect() as conn:
        conn.execute("ATTACH DATABASE ? AS seed", (str(SEED_DB),))
        try:
            seeded = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM seed.sqlite_master WHERE type = 'table'"
                )
            }
            conn.execute("BEGIN")
            for table in SOURCE_TABLES:
                if table not in seeded:
                    continue
                if not _row_count(conn, f"seed.{table}"):
                    continue  # an empty shipped table is not an improvement
                conn.execute(f"DELETE FROM {table}")
                conn.execute(f"INSERT INTO {table} SELECT * FROM seed.{table}")
                refreshed.append(table)
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.execute("DETACH DATABASE seed")
    return refreshed


def _meta(key: str) -> str | None:
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None
    except sqlite3.Error:
        return None


def _set_meta(key: str, value: str) -> None:
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
    except sqlite3.Error:
        pass


def ensure_data() -> dict:
    """Idempotent. Safe to call on every boot; returns what it actually did."""
    report: dict = {
        "data_dir": str(DATA_DIR),
        "models_dir": str(MODELS_DIR),
        "seed_mode": SEED_MODE,
        "action": "none",
        "models_copied": [],
        "tables_refreshed": [],
        "warnings": [],
    }

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        report["warnings"].append(f"cannot create {DATA_DIR}: {e}")
        return report

    seed_available = SEED_DB.exists() and _has_data(SEED_DB)

    if SEED_MODE == "never":
        pass
    elif not seed_available:
        # Only worth complaining about when there is nothing else to serve:
        # a developer with a working data/bhav.db has simply never built one.
        if not _has_data(DB_PATH):
            report["warnings"].append(
                f"no snapshot at {SEED_DB} and no data at {DB_PATH} — the API "
                "will 503. Run the pipeline (python -m scripts.seed_demo && "
                "python -m scripts.build), then python -m scripts.make_seed"
            )
    elif not _has_data(DB_PATH):
        # First boot on a fresh disk. A straight file copy, so the schema and
        # the data_version travel with it.
        shutil.copy2(SEED_DB, DB_PATH)
        report["action"] = "seeded"
        report["tables_refreshed"] = list(SOURCE_TABLES)
        _set_meta("seed_stamp", _seed_stamp())
    elif SEED_MODE == "refresh" and _meta("seed_stamp") != _seed_stamp():
        try:
            report["tables_refreshed"] = _refresh_source_tables()
            report["action"] = "refreshed"
            _set_meta("seed_stamp", _seed_stamp())
            bump_data_version()
        except sqlite3.Error as e:
            report["warnings"].append(f"source refresh failed, kept existing data: {e}")

    try:
        init_db()  # brings an older disk up to the current schema
    except sqlite3.Error as e:
        report["warnings"].append(f"schema init failed: {e}")

    report["models_copied"] = _copy_models()
    return report


def main() -> None:
    import json

    print(json.dumps(ensure_data(), indent=2))


if __name__ == "__main__":
    main()
