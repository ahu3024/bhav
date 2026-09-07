"""Baseline comparison on the relocked crash label (roadmap §H12–H20:
"Baselines: seasonal-naive, price-momentum-only. Then LightGBM").

An AUC quoted against random guessing tells you almost nothing — a seasonal crop
with a seasonal crash pattern can look predictable purely because the calendar
is predictable. So the same label and the same time split are run through three
models, and LightGBM is scored against the two baselines, not against 0.5.

Split is the roadmap's: train <= 2023, validate on 2024, test on 2025.

    python -m scripts.evaluate
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from bhav.config import DROP_THRESHOLD_PCT, HORIZON_DAYS
from bhav.features import FEATURE_COLS, build_features
from bhav.model import _build_estimator

TRAIN_END = 2023
VAL_YEAR = 2024
TEST_YEAR = 2025

# The roadmap's second baseline, spelled out: price momentum and nothing else.
MOMENTUM_COLS = ["price_mom_7", "price_mom_14", "price_mom_30"]

# Day-of-year bucket for the seasonal baseline — same width as the climatology
# used by the anomaly features, so the two agree on what "time of year" means.
SEASON_BUCKET_DAYS = 15


class SeasonalNaive:
    """P(crash) = the crash rate in this slice of the calendar, from train only.

    This is the baseline that matters most: onion crashes cluster around the
    two harvests, so a model that has only learned the calendar can already look
    good. Anything LightGBM earns above this line is what the satellite, weather
    and market data are actually contributing.
    """

    def fit(self, index: pd.DatetimeIndex, y: np.ndarray) -> "SeasonalNaive":
        bucket = self._bucket(index)
        frame = pd.DataFrame({"bucket": bucket, "y": y})
        self.rates_ = frame.groupby("bucket")["y"].mean()
        self.prior_ = float(np.mean(y))
        return self

    def predict_proba(self, index: pd.DatetimeIndex) -> np.ndarray:
        return (
            pd.Series(self._bucket(index))
            .map(self.rates_)
            .fillna(self.prior_)
            .to_numpy()
        )

    @staticmethod
    def _bucket(index: pd.DatetimeIndex) -> np.ndarray:
        doy = np.where((index.month == 2) & (index.day == 29), 59, index.dayofyear)
        return (doy - 1) // SEASON_BUCKET_DAYS


def _momentum_model() -> Pipeline:
    return Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
    ])


def _scores(y: np.ndarray, p: np.ndarray) -> dict:
    if len(np.unique(y)) < 2:
        return {"auc": float("nan"), "ap": float("nan"), "base": float(np.mean(y))}
    return {
        "auc": roc_auc_score(y, p),
        "ap": average_precision_score(y, p),
        "base": float(np.mean(y)),
    }


def main() -> None:
    frame = build_features(with_target=True).dropna(subset=FEATURE_COLS + ["target"])
    frame["target"] = frame["target"].astype(int)

    year = frame.index.year
    splits = {
        "train": frame[year <= TRAIN_END],
        "val": frame[year == VAL_YEAR],
        "test": frame[year == TEST_YEAR],
    }

    print(f"Label: modal price falls >= {DROP_THRESHOLD_PCT:.0%} within "
          f"{HORIZON_DAYS} days, on CPI-deflated price")
    print(f"Split: train <= {TRAIN_END} | val {VAL_YEAR} | test {TEST_YEAR}")
    print(f"Features: {len(FEATURE_COLS)}")
    print()
    for name, part in splits.items():
        print(f"  {name:<6} {len(part):>5} rows  "
              f"{part.index.min():%Y-%m-%d}..{part.index.max():%Y-%m-%d}  "
              f"base rate {part['target'].mean():.1%}")
    print()

    tr = splits["train"]
    y_tr = tr["target"].to_numpy()

    # --- fit all three on train only ---------------------------------------
    seasonal = SeasonalNaive().fit(tr.index, y_tr)

    momentum = _momentum_model()
    momentum.fit(tr[MOMENTUM_COLS], y_tr)

    lgbm, kind = _build_estimator()
    lgbm.fit(tr[FEATURE_COLS], y_tr)

    models = {
        "seasonal-naive": lambda d: seasonal.predict_proba(d.index),
        "price-momentum": lambda d: momentum.predict_proba(d[MOMENTUM_COLS])[:, 1],
        kind: lambda d: lgbm.predict_proba(d[FEATURE_COLS])[:, 1],
    }

    results: dict[str, dict[str, dict]] = {}
    for split_name in ("val", "test"):
        part = splits[split_name]
        y = part["target"].to_numpy()
        results[split_name] = {
            m: _scores(y, predict(part)) for m, predict in models.items()
        }

    # --- report -------------------------------------------------------------
    for split_name in ("val", "test"):
        r = results[split_name]
        base = next(iter(r.values()))["base"]
        print(f"=== {split_name.upper()} "
              f"({VAL_YEAR if split_name == 'val' else TEST_YEAR}) "
              f"— base rate {base:.1%} ===")
        print(f"  {'model':<16} {'ROC AUC':>9} {'avg prec':>10} {'AP lift':>9}")
        for m, s in r.items():
            lift = s["ap"] / base if base else float("nan")
            print(f"  {m:<16} {s['auc']:>9.3f} {s['ap']:>10.3f} {lift:>8.2f}x")
        print()

        lg = r[kind]
        print(f"  {kind} delta vs each baseline:")
        for m in ("seasonal-naive", "price-momentum"):
            b = r[m]
            print(f"    vs {m:<15} AUC {lg['auc'] - b['auc']:+.3f}"
                  f"   AP {lg['ap'] - b['ap']:+.3f}"
                  f"   ({(lg['ap'] / b['ap'] - 1) * 100:+.0f}% AP)")
        print(f"    vs random          AUC {lg['auc'] - 0.5:+.3f}"
              f"   AP {lg['ap'] - base:+.3f}")
        print()


if __name__ == "__main__":
    main()
