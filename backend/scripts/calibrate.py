"""Fit the isotonic calibrator on the validation year and audit it after.

Fit:   2024 (VAL_YEAR) out-of-sample predictions from a model trained on rows
       more than HORIZON_DAYS before 2024 — embargoed, so no label built from
       2024 prices reaches the training set.
Audit: 2025 onward, walk-forward with a monthly refit. Strictly *after* the
       calibration year, so the audit never sees data the calibrator was fit on.

Daily decision points here, not weekly: calibration is a question about
probability accuracy rather than about independent decisions, and daily gives
~600 points instead of ~50. Adjacent days are correlated, so read the bin counts
as "how much evidence" rather than as independent samples.

    python -m scripts.calibrate
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bhav.calibration import fit_calibrator, save_calibrator
from bhav.config import CALIBRATOR_PATH, HORIZON_DAYS
from bhav.features import FEATURE_COLS, build_features
from bhav.model import _build_estimator

VAL_YEAR = 2024
AUDIT_START = "2025-01-01"
BINS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]


def _embargoed_train(frame: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    return frame[frame.index < cutoff - pd.Timedelta(days=HORIZON_DAYS)]


def _val_predictions(frame: pd.DataFrame) -> pd.DataFrame:
    """Out-of-sample probabilities for every day of the validation year."""
    start = pd.Timestamp(f"{VAL_YEAR}-01-01")
    end = pd.Timestamp(f"{VAL_YEAR}-12-31")
    train = _embargoed_train(frame, start)
    model, _ = _build_estimator()
    model.fit(train[FEATURE_COLS], train["target"].astype(int))

    block = frame.loc[start:end]
    return pd.DataFrame({
        "prob": model.predict_proba(block[FEATURE_COLS])[:, 1],
        "crash": block["target"].astype(int).to_numpy(),
    }, index=block.index)


def _audit_predictions(frame: pd.DataFrame) -> pd.DataFrame:
    """Daily walk-forward probabilities from AUDIT_START to the end of data."""
    days = frame.loc[AUDIT_START:].index
    rows = []
    for month, group in pd.Series(days, index=days).groupby(pd.Grouper(freq="MS")):
        if group.empty:
            continue
        train = _embargoed_train(frame, month)
        if len(train) < 400:
            continue
        model, _ = _build_estimator()
        model.fit(train[FEATURE_COLS], train["target"].astype(int))
        block = frame.loc[group.values]
        rows.append(pd.DataFrame({
            "prob": model.predict_proba(block[FEATURE_COLS])[:, 1],
            "crash": block["target"].astype(int).to_numpy(),
        }, index=block.index))
    return pd.concat(rows) if rows else pd.DataFrame()


def _bin_table(df: pd.DataFrame, col: str, label: str) -> None:
    sub = df[df[col] < 0.6].copy()
    sub["bin"] = pd.cut(sub[col], BINS, right=False)
    grouped = sub.groupby("bin", observed=True).agg(
        n=("crash", "size"),
        raw=("prob", "mean"),
        calibrated=("cal", "mean"),
        observed=("crash", "mean"),
    )
    print(f"  {label} (binned on {col}, restricted to < 0.6) — "
          f"{len(sub)} of {len(df)} points")
    print(f"    {'bin':<12}{'n':>5}{'raw':>8}{'calibrated':>12}{'observed':>10}"
          f"{'gap':>8}")
    for b, r in grouped.iterrows():
        gap = r["calibrated"] - r["observed"]
        print(f"    {str(b):<12}{int(r['n']):>5}{r['raw']:>8.2f}"
              f"{r['calibrated']:>12.2f}{r['observed']:>10.2f}{gap:>+8.2f}")
    print()


def main() -> None:
    frame = build_features(with_target=True).dropna(subset=FEATURE_COLS + ["target"])

    val = _val_predictions(frame)
    iso = fit_calibrator(val["prob"].to_numpy(), val["crash"].to_numpy())
    save_calibrator(iso, meta={
        "method": "isotonic",
        "fit_on": f"{VAL_YEAR} out-of-sample, embargoed {HORIZON_DAYS}d",
        "n_fit": int(len(val)),
        "base_rate_fit": round(float(val["crash"].mean()), 4),
    })
    print(f"Fitted isotonic on {len(val)} days of {VAL_YEAR} "
          f"(base rate {val['crash'].mean():.1%}) -> {CALIBRATOR_PATH.name}")
    print()

    audit = _audit_predictions(frame)
    if audit.empty:
        print("no audit period available")
        return
    audit["cal"] = iso.predict(audit["prob"].to_numpy())

    print(f"AUDIT: {AUDIT_START} .. {audit.index.max():%Y-%m-%d}  "
          f"({len(audit)} daily points, base rate {audit['crash'].mean():.1%})")
    print("Strictly after the calibration year.")
    print()
    _bin_table(audit, "prob", "Sub-0.6 zone")

    below = audit[audit["prob"] < 0.6]
    for name, col in (("raw", "prob"), ("calibrated", "cal")):
        err = (below[col] - below["crash"]).abs().mean()
        bias = (below[col] - below["crash"]).mean()
        print(f"  {name:<11} mean |pred - outcome| = {err:.3f}   "
              f"mean bias = {bias:+.3f}")
    print()
    print("  (bias > 0 = over-predicting crashes, < 0 = under-predicting)")


if __name__ == "__main__":
    main()
