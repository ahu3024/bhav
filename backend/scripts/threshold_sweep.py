"""Walk-forward alert-threshold sweep on regularised-33 (roadmap §H24–H32).

Answers the operating-point question: at what predicted probability should a
SELL alert fire? Three candidates are scored on two evaluation periods, and
every number is out-of-sample.

Method
------
* **Walk-forward, monthly refit, with an embargo.** For each decision date the
  model is trained only on rows more than HORIZON_DAYS before that calendar
  month. The embargo matters: a training row's label is built from prices up to
  ten days after it, so rows sitting at the boundary carry outcomes from inside
  the window being evaluated.
* **Weekly decision points.** Bhav issues a signal once a week, so daily
  evaluation would count the same decision ten times over a ten-day horizon and
  make the alert counts look far more independent than they are.
* **Thresholds from training probabilities only.** Conservative / moderate /
  liberal are defined as target coverage on the *training* distribution (5% /
  15% / 30%); the coverage reported on the evaluation periods is what actually
  happened out of sample.

Economics (same convention as backtest.py's RED branch)
------------------------------------------------------
When an alert fires the farmer sells across the alert window; the alert argues
against holding out for a better price later in the horizon.

    gain = mean(price over [t, t+WINDOW_DAYS])
         - mean(price over [t+WINDOW_DAYS+1, t+HORIZON_DAYS])

Nominal rupees per quintal - what a farmer actually banks.

    python -m scripts.threshold_sweep
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bhav.config import DROP_THRESHOLD_PCT, HORIZON_DAYS, WINDOW_DAYS
from bhav.features import FEATURE_COLS, build_features
from bhav.model import _build_estimator

# Target share of *training* days on which each candidate would have fired.
CANDIDATES = {
    "conservative": 0.05,
    "moderate": 0.15,
    "liberal": 0.30,
}

DECISION_FREQ = "7D"  # one signal a week, per the product

PERIODS = {
    # Spans both 2023 events: the June collapse and the Oct-Dec spike-and-crash.
    "2023 crash window": ("2023-06-01", "2023-12-31"),
    "2025 test year": ("2025-01-01", "2025-12-31"),
}


def _walk_forward_probs(frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Predicted probability at each weekly decision point, refit monthly."""
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    decisions = pd.date_range(start_ts, end_ts, freq=DECISION_FREQ)
    decisions = decisions[decisions.isin(frame.index)]

    rows = []
    for month, group in pd.Series(decisions, index=decisions).groupby(
        pd.Grouper(freq="MS")
    ):
        if group.empty:
            continue
        # Embargo the last HORIZON_DAYS before the evaluation month. A training
        # row's label is built from prices up to HORIZON_DAYS *after* it, so
        # rows right at the boundary carry outcomes that fall inside the window
        # being evaluated — training on them leaks the answer.
        cutoff = month - pd.Timedelta(days=HORIZON_DAYS)
        train = frame[frame.index < cutoff]
        if len(train) < 400:
            continue
        model, _ = _build_estimator()
        model.fit(train[FEATURE_COLS], train["target"].astype(int))

        block = frame.loc[group.values]
        rows.append(pd.DataFrame({
            "prob": model.predict_proba(block[FEATURE_COLS])[:, 1],
            "crash": block["target"].astype(int).to_numpy(),
            # Threshold anchors come from this refit's own training rows.
            **{f"cut_{name}": np.quantile(
                model.predict_proba(train[FEATURE_COLS])[:, 1], 1 - target)
               for name, target in CANDIDATES.items()},
        }, index=block.index))

    return pd.concat(rows) if rows else pd.DataFrame()


def _gain(price: pd.Series, t: pd.Timestamp) -> float:
    """₹/qtl from selling across the alert window vs holding out for better."""
    sell = price.loc[t: t + pd.Timedelta(days=WINDOW_DAYS)]
    hold = price.loc[t + pd.Timedelta(days=WINDOW_DAYS + 1):
                     t + pd.Timedelta(days=HORIZON_DAYS)]
    if sell.empty or hold.empty:
        return float("nan")
    return float(sell.mean() - hold.mean())


def _evaluate(probs: pd.DataFrame, price: pd.Series, name: str,
              cuts: dict | None = None) -> list[dict]:
    """Score each candidate. `cuts` maps a label to either a fixed probability
    or a column name in `probs` holding a per-refit threshold."""
    gains = pd.Series({t: _gain(price, t) for t in probs.index})
    cuts = cuts or {c: f"cut_{c}" for c in CANDIDATES}
    out = []
    for candidate, spec in cuts.items():
        cut = probs[spec] if isinstance(spec, str) else pd.Series(spec, index=probs.index)
        fired = probs["prob"] >= cut
        crash = probs["crash"] == 1

        hits = int((fired & crash).sum())
        false_alarms = int((fired & ~crash).sum())
        missed = int((~fired & crash).sum())
        n_alerts = int(fired.sum())
        n_points = len(probs)

        g = gains[fired].dropna()
        out.append({
            "period": name,
            "candidate": candidate,
            "cut": float(cut.median()),
            "points": n_points,
            "alerts": n_alerts,
            "coverage": n_alerts / n_points if n_points else float("nan"),
            "hit_rate": hits / n_alerts if n_alerts else float("nan"),
            "recall": hits / int(crash.sum()) if int(crash.sum()) else float("nan"),
            "avg_gain": float(g.mean()) if len(g) else float("nan"),
            "worst_loss": float(g.min()) if len(g) else float("nan"),
            "total_gain": float(g.sum()) if len(g) else float("nan"),
            "false_alarms": false_alarms,
            "missed": missed,
            "crashes": int(crash.sum()),
        })
    return out


def main() -> None:
    frame = build_features(with_target=True).dropna(subset=FEATURE_COLS + ["target"])
    price = build_features(with_target=False)["price"]

    print(f"Model: regularised-33 | label: >= {DROP_THRESHOLD_PCT:.0%} fall within "
          f"{HORIZON_DAYS}d (deflated)")
    print(f"Walk-forward: monthly refit, trained only on rows before each month")
    print(f"Decision cadence: weekly | alert window: {WINDOW_DAYS}d | "
          f"horizon: {HORIZON_DAYS}d")
    print(f"Candidates by TRAIN coverage: " + ", ".join(
        f"{k} {v:.0%}" for k, v in CANDIDATES.items()))
    print()

    results = []
    for name, (start, end) in PERIODS.items():
        probs = _walk_forward_probs(frame, start, end)
        if probs.empty:
            print(f"{name}: no decision points")
            continue
        results += _evaluate(probs, price, name)

    res = pd.DataFrame(results)

    for name in PERIODS:
        part = res[res["period"] == name]
        if part.empty:
            continue
        head = part.iloc[0]
        print("=" * 100)
        print(f"{name}  -  {head['points']} weekly decision points, "
              f"{head['crashes']} of them preceded a crash "
              f"({head['crashes'] / head['points']:.0%})")
        print("-" * 100)
        print(f"{'candidate':<14}{'p cut':>7}{'alerts':>8}{'coverage':>10}"
              f"{'hit rate':>10}{'recall':>8}{'avg Rs/alert':>13}"
              f"{'worst Rs':>10}{'false':>7}{'missed':>8}")
        for _, r in part.iterrows():
            print(f"{r['candidate']:<14}{r['cut']:>7.2f}{r['alerts']:>8.0f}"
                  f"{r['coverage']:>9.0%}{r['hit_rate']:>10.0%}{r['recall']:>8.0%}"
                  f"{r['avg_gain']:>13,.0f}{r['worst_loss']:>10,.0f}"
                  f"{r['false_alarms']:>7.0f}{r['missed']:>8.0f}")
        print()

    print("=" * 100)
    print("Pooled across both periods:")
    print(f"{'candidate':<14}{'alerts':>8}{'coverage':>10}{'hit rate':>10}"
          f"{'avg Rs/alert':>13}{'worst Rs':>10}{'false':>7}{'missed':>8}"
          f"{'total Rs':>12}")
    for candidate in CANDIDATES:
        part = res[res["candidate"] == candidate]
        alerts = part["alerts"].sum()
        points = part["points"].sum()
        hits = (part["hit_rate"] * part["alerts"]).sum()
        # Weight the per-alert average by how many alerts each period produced.
        avg = (part["avg_gain"] * part["alerts"]).sum() / alerts if alerts else np.nan
        print(f"{candidate:<14}{alerts:>8.0f}{alerts / points:>9.0%}"
              f"{hits / alerts if alerts else np.nan:>10.0%}"
              f"{avg:>13,.0f}{part['worst_loss'].min():>10,.0f}"
              f"{part['false_alarms'].sum():>7.0f}{part['missed'].sum():>8.0f}"
              f"{part['total_gain'].sum():>12,.0f}")
    print("=" * 100)
    print()
    print("Rs figures are nominal Rs/quintal, per alert. 'hit rate' = share of")
    print("alerts that preceded a real crash (precision); 'recall' = share of")
    print("crashes caught. No operating point is recommended here.")


if __name__ == "__main__":
    main()
