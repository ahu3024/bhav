"""One bounded capacity pass on the relocked 16% label.

Three interventions, all pre-specified before looking at any holdout number so
nothing here is selected on the test year:

  1. prune 33 features to ~15 by gain importance (train-fit model only)
  2. capacity-appropriate regularisation for ~2,840 rows — fewer leaves,
     shallower trees, larger leaf minimum
  3. a stacked variant handing LightGBM the seasonal-naive probability as an
     input feature

Every variant is scored on the identical val-2024 / test-2025 split used by
scripts.evaluate, against all three existing baselines.

    python -m scripts.prune_eval
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from bhav.config import DROP_THRESHOLD_PCT, HORIZON_DAYS
from bhav.features import FEATURE_COLS, build_features
from scripts.evaluate import (
    MOMENTUM_COLS,
    TEST_YEAR,
    TRAIN_END,
    VAL_YEAR,
    SeasonalNaive,
    _momentum_model,
)

KEEP_N = 15
STACK_COL = "seasonal_prob"

# Capacity-appropriate parameters. 2,840 rows and a 23% base rate is ~650
# positive examples; 31 leaves can carve that into slivers of a dozen. One
# setting, chosen from the data's size rather than searched on the holdout.
REGULARISED = dict(
    n_estimators=400,
    learning_rate=0.03,
    num_leaves=8,          # was 31
    max_depth=4,           # was unbounded
    min_child_samples=60,  # was 30
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=5.0,        # was 1.0
    random_state=42,
    verbosity=-1,
)


def _lgbm(**overrides):
    from lightgbm import LGBMClassifier

    params = dict(
        n_estimators=400, learning_rate=0.03, num_leaves=31, subsample=0.8,
        colsample_bytree=0.8, min_child_samples=30, reg_lambda=1.0,
        random_state=42, verbosity=-1,
    )
    params.update(overrides)
    return LGBMClassifier(**params)


def _gain_importances(model, cols: list[str]) -> pd.Series:
    gains = model.booster_.feature_importance(importance_type="gain")
    return pd.Series(gains, index=cols).sort_values(ascending=False)


def _oof_seasonal(train: pd.DataFrame) -> np.ndarray:
    """Leave-one-year-out seasonal probabilities for the training rows.

    Fitting seasonal-naive on the same rows it then scores would let the stacked
    model see each year's own crash rate and trust the feature far more than it
    deserves. Holding each training year out keeps the stacked feature honest.
    """
    y = train["target"].to_numpy()
    out = np.empty(len(train), dtype=float)
    years = train.index.year
    for yr in np.unique(years):
        mask = years == yr
        fitted = SeasonalNaive().fit(train.index[~mask], y[~mask])
        out[mask] = fitted.predict_proba(train.index[mask])
    return out


def main() -> None:
    frame = build_features(with_target=True).dropna(subset=FEATURE_COLS + ["target"])
    frame["target"] = frame["target"].astype(int)
    year = frame.index.year
    tr = frame[year <= TRAIN_END]
    val = frame[year == VAL_YEAR]
    te = frame[year == TEST_YEAR]
    y_tr, y_val, y_te = (d["target"].to_numpy() for d in (tr, val, te))

    print(f"Label: >= {DROP_THRESHOLD_PCT:.0%} fall within {HORIZON_DAYS}d (deflated)")
    print(f"Split: train <= {TRAIN_END} ({len(tr)}) | val {VAL_YEAR} ({len(val)}) "
          f"| test {TEST_YEAR} ({len(te)})")
    print(f"Base rates: train {y_tr.mean():.1%} | val {y_val.mean():.1%} "
          f"| test {y_te.mean():.1%}")
    print()

    # ---- baselines ---------------------------------------------------------
    seasonal = SeasonalNaive().fit(tr.index, y_tr)
    momentum = _momentum_model().fit(tr[MOMENTUM_COLS], y_tr)
    # Pinned to the pre-pass configuration via _lgbm()'s defaults rather than
    # bhav.model — `regularised-33` has since been adopted there, and this row
    # has to keep meaning "the model as it was before this pass".
    base_lgbm = _lgbm()
    base_lgbm.fit(tr[FEATURE_COLS], y_tr)

    # ---- (1) prune by gain importance, train-fit only ----------------------
    imp = _gain_importances(base_lgbm, FEATURE_COLS)
    zero = int((imp <= 0).sum())
    keep = imp.head(KEEP_N).index.tolist()
    dropped = [c for c in FEATURE_COLS if c not in keep]

    print(f"Gain importance: {zero} of {len(FEATURE_COLS)} features contribute zero")
    print(f"Kept {len(keep)}:")
    for c in keep:
        print(f"    {c:<24} {imp[c]:>10.1f}")
    print(f"Dropped {len(dropped)}: {', '.join(dropped)}")
    print()

    # ---- (3) stacked feature ----------------------------------------------
    tr_s = tr.assign(**{STACK_COL: _oof_seasonal(tr)})
    val_s = val.assign(**{STACK_COL: seasonal.predict_proba(val.index)})
    te_s = te.assign(**{STACK_COL: seasonal.predict_proba(te.index)})
    stack_cols = keep + [STACK_COL]

    # ---- variants, all pre-specified --------------------------------------
    variants: dict[str, tuple] = {}

    v = _lgbm(); v.fit(tr[keep], y_tr)
    variants["pruned-15"] = (v, keep, tr, val, te)

    v = _lgbm(**REGULARISED); v.fit(tr[FEATURE_COLS], y_tr)
    variants["regularised-33"] = (v, FEATURE_COLS, tr, val, te)

    v = _lgbm(**REGULARISED); v.fit(tr[keep], y_tr)
    variants["pruned+reg"] = (v, keep, tr, val, te)

    v = _lgbm(**REGULARISED); v.fit(tr_s[stack_cols], y_tr)
    variants["pruned+reg+stack"] = (v, stack_cols, tr_s, val_s, te_s)

    # ---- score everything on the identical split ---------------------------
    rows = []

    def add(name, p_val, p_te):
        rows.append({
            "model": name,
            "val_auc": roc_auc_score(y_val, p_val),
            "val_ap": average_precision_score(y_val, p_val),
            "test_auc": roc_auc_score(y_te, p_te),
            "test_ap": average_precision_score(y_te, p_te),
        })

    add("seasonal-naive", seasonal.predict_proba(val.index),
        seasonal.predict_proba(te.index))
    add("price-momentum", momentum.predict_proba(val[MOMENTUM_COLS])[:, 1],
        momentum.predict_proba(te[MOMENTUM_COLS])[:, 1])
    add("lightgbm-33 (orig)", base_lgbm.predict_proba(val[FEATURE_COLS])[:, 1],
        base_lgbm.predict_proba(te[FEATURE_COLS])[:, 1])
    for name, (mdl, cols, _t, v_df, t_df) in variants.items():
        add(name, mdl.predict_proba(v_df[cols])[:, 1],
            mdl.predict_proba(t_df[cols])[:, 1])

    res = pd.DataFrame(rows).set_index("model")

    print("=" * 74)
    print(f"{'model':<20}{'val AUC':>9}{'val AP':>9}{'test AUC':>10}{'test AP':>9}")
    print("-" * 74)
    for name, r in res.iterrows():
        mark = "  <- baseline" if name in (
            "seasonal-naive", "price-momentum", "lightgbm-33 (orig)") else ""
        print(f"{name:<20}{r.val_auc:>9.3f}{r.val_ap:>9.3f}"
              f"{r.test_auc:>10.3f}{r.test_ap:>9.3f}{mark}")
    print("=" * 74)
    print()

    baselines = ["seasonal-naive", "price-momentum", "lightgbm-33 (orig)"]
    print("Deltas — each variant against all three baselines (test year):")
    print(f"  {'variant':<20}" + "".join(f"{b.split()[0][:14]:>17}" for b in baselines))
    for name in variants:
        cells = []
        for b in baselines:
            d_auc = res.loc[name, "test_auc"] - res.loc[b, "test_auc"]
            d_ap = res.loc[name, "test_ap"] - res.loc[b, "test_ap"]
            cells.append(f"{d_auc:+.3f}/{d_ap:+.3f}".rjust(17))
        print(f"  {name:<20}" + "".join(cells))
    print("  (AUC delta / AP delta)")
    print()

    sn_auc = res.loc["seasonal-naive", "test_auc"]
    winners = [n for n in variants if res.loc[n, "test_auc"] > sn_auc]
    print(f"Seasonal-naive test-year AUC: {sn_auc:.3f}")
    if winners:
        print("Variants beating it on TEST AUC: " + ", ".join(
            f"{n} ({res.loc[n, 'test_auc']:.3f})" for n in winners))
    else:
        print("NO variant beats seasonal-naive on test-year AUC.")


if __name__ == "__main__":
    main()
