"""Point-in-time audit of the feature matrix (roadmap: "hand-check 2 dates for
leakage", risk register: "backtest looks fake-good").

The test: build the features once from the full history, then rebuild them with
every raw input truncated at date D. If a feature's value at D moves, it was
reading data that did not exist yet on D — and any backtest using it is telling
a flattering lie.

    python -m scripts.check_leakage
    python -m scripts.check_leakage 2024-04-05 2023-08-15
"""

from __future__ import annotations

import sys

import pandas as pd

import bhav.db as db
import bhav.features as F

DEFAULT_DATES = ["2024-04-05", "2023-08-15", "2021-11-20", "2019-05-10"]
TOL = 1e-9


def _features_asof(cut: pd.Timestamp) -> pd.DataFrame:
    """Rebuild the matrix with every raw table truncated at `cut`."""
    original = db.read_df

    def truncated(query: str, params: tuple = ()) -> pd.DataFrame:
        df = original(query, params)
        if "date" in df.columns:
            df = df[pd.to_datetime(df["date"]) <= cut]
        return df

    db.read_df = truncated
    F.read_df = truncated
    try:
        return F.build_features(with_target=False)
    finally:
        db.read_df = original
        F.read_df = original


def check(dates: list[str]) -> int:
    full = F.build_features(with_target=False)
    leaks = 0

    for d in dates:
        cut = pd.Timestamp(d)
        if cut not in full.index:
            print(f"{d}: not in the feature index — skipped")
            continue

        truncated = _features_asof(cut)
        a, b = full.loc[cut], truncated.loc[cut]

        offenders = []
        for col in F.FEATURE_COLS:
            av, bv = a[col], b[col]
            if pd.isna(av) and pd.isna(bv):
                continue
            if pd.isna(av) or pd.isna(bv) or abs(float(av) - float(bv)) > TOL:
                offenders.append((col, av, bv))

        if offenders:
            leaks += len(offenders)
            print(f"{d}: {len(offenders)} LEAKING feature(s)")
            for col, av, bv in offenders:
                print(f"    {col:<24} full={av!r:>14}  as-of={bv!r:>14}")
        else:
            print(f"{d}: clean ({len(F.FEATURE_COLS)} features)")

    print()
    if leaks:
        print(f"FAIL — {leaks} feature/date pair(s) depend on future data.")
    else:
        print(f"PASS — every feature is point-in-time safe on {len(dates)} dates.")
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(check(sys.argv[1:] or DEFAULT_DATES))
