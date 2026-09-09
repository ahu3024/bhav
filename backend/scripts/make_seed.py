"""Build the shipped snapshot: data/seed.db.

The deploy needs the pipeline's output — a decade of NDVI, weather and mandi
prints — inside the image, so a fresh instance serves a real signal on its first
request instead of 503ing until someone runs an ingest.

What it must **not** carry is the live database. `data/bhav.db` also holds
`subscribers` and `message_log`: real phone numbers, and the text of every
message sent to them. Committing that file would publish those numbers into git
history, where deleting them later does not remove them, and bake them into
every container image built from the repo.

So the two are separate files. This script copies only the tables the model
reads into `data/seed.db`, which is the one that is committed and shipped;
`data/bhav.db` stays git-ignored and local. bootstrap.py copies seed -> live on
a fresh host, and never the other way.

    python -m scripts.make_seed          # rebuild data/seed.db
    python -m scripts.make_seed --check  # verify it carries no personal data
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

from bhav.bootstrap import SOURCE_TABLES
from bhav.config import DB_PATH, SEED_DATA_DIR
from bhav.db import SCHEMA

SEED_PATH = SEED_DATA_DIR / "seed.db"
# Everything a person created. Present in the seed as empty tables — the schema
# has to be there, the rows must not be.
PERSONAL_TABLES = ("subscribers", "message_log")


def build() -> dict:
    if not DB_PATH.exists():
        raise SystemExit(
            f"no live database at {DB_PATH} — run the pipeline first:\n"
            "  python -m scripts.fetch_all   (or scripts.seed_demo offline)\n"
            "  python -m scripts.build"
        )

    SEED_PATH.unlink(missing_ok=True)
    counts: dict[str, int] = {}
    with sqlite3.connect(SEED_PATH) as out:
        out.executescript(SCHEMA)
        out.execute("ATTACH DATABASE ? AS live", (str(DB_PATH),))
        live_tables = {
            r[0] for r in out.execute(
                "SELECT name FROM live.sqlite_master WHERE type = 'table'"
            )
        }
        for table in SOURCE_TABLES:
            if table not in live_tables:
                counts[table] = 0
                continue
            out.execute(f"INSERT INTO {table} SELECT * FROM live.{table}")
            counts[table] = out.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        # A fresh generation stamp, so a host that already has data can tell
        # this snapshot apart from the last one it saw.
        out.execute(
            "INSERT INTO meta (key, value) VALUES ('data_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"seed-{max(counts.values(), default=0)}-{sum(counts.values())}",),
        )
        out.commit()
        out.execute("DETACH DATABASE live")
    # Sidecars would otherwise ship a half-written snapshot.
    with sqlite3.connect(SEED_PATH) as out:
        out.execute("PRAGMA journal_mode = DELETE")
        out.execute("VACUUM")
    return counts


def check() -> int:
    """Fail loudly if the snapshot picked up anything personal."""
    if not SEED_PATH.exists():
        print(f"{SEED_PATH} does not exist — run `python -m scripts.make_seed`")
        return 1
    problems = []
    with sqlite3.connect(SEED_PATH) as conn:
        for table in PERSONAL_TABLES + ("alerts",):
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                continue
            if n:
                problems.append(f"{table}: {n} rows")
        source = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in SOURCE_TABLES
        }
    for table, n in source.items():
        print(f"  {table:14} {n:>7,}")
    if problems:
        print("\nREFUSING: the seed contains rows people created:")
        for p in problems:
            print(f"  {p}")
        return 1
    if not source.get("mandi_price"):
        print("\nREFUSING: no mandi prices — this seed would serve nothing.")
        return 1
    print(f"\nclean — no subscriber or message rows in {SEED_PATH.name}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the existing seed rather than rebuilding it")
    args = ap.parse_args()

    if not args.check:
        counts = build()
        size = SEED_PATH.stat().st_size
        print(f"wrote {SEED_PATH} ({size / 1024:.0f} KB)")
        for table, n in counts.items():
            print(f"  {table:14} {n:>7,}")
        print()
    sys.exit(check())


if __name__ == "__main__":
    main()
