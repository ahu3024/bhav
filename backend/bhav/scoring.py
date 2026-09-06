"""The one scoring function.

`score_asof(date)` is called by BOTH the live alert path and the backtest engine
(roadmap "key design point"). It returns the model's drop probability plus the
human-readable drivers behind it — no color/window logic here, that's the alert
engine's job.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .features import feature_row_asof
from .model import load_model

# Plain-language phrasing for each feature, keyed by sign of its contribution.
_FEATURE_PHRASES = {
    "ndvi":            ("crop canopy healthy and near peak", "crop canopy thin / stressed"),
    "ndvi_d7":         ("greenness rising week-on-week", "greenness dropping week-on-week"),
    "ndvi_d14":        ("2-week crop growth strong", "2-week crop decline"),
    "ndvi_d30":        ("month-long crop build-up", "month-long crop senescence — harvest near"),
    "ndvi_vs_season":  ("crop ahead of the seasonal norm", "crop behind the seasonal norm"),
    "rain_7":          ("wet week — arrivals may stall", "dry week — smooth harvesting"),
    "rain_30":         ("wet month building", "dry month"),
    "rain_anom_30":    ("rainfall above normal", "rainfall below normal"),
    "tmax_anom_14":    ("hotter than normal — faster maturity", "cooler than normal"),
    "trange_14":       ("wide day-night temp swing", "narrow temp swing"),
    "price":           ("price level elevated", "price level low"),
    "price_mom_7":     ("price rising this week", "price falling this week"),
    "price_mom_14":    ("2-week price momentum up", "2-week price momentum down"),
    "price_mom_30":    ("month-long price rally — stretched", "month-long price slide"),
    "price_vs_year":   ("price well above its yearly median", "price below its yearly median"),
    "price_pctile_year": ("price in the top of its yearly range", "price in the bottom of its yearly range"),
    "arr_7":           ("mandi arrivals heavy", "mandi arrivals thin"),
    "arr_mom_14":      ("arrivals accelerating — glut risk", "arrivals easing"),
    "arr_vs_year":     ("arrivals above the yearly norm", "arrivals below the yearly norm"),
    "doy_sin":         ("seasonal timing", "seasonal timing"),
    "doy_cos":         ("seasonal timing", "seasonal timing"),
}


@dataclass
class Score:
    date: str
    drop_probability: float          # P(price falls > threshold within horizon)
    price_per_quintal: float
    horizon_days: int
    drop_threshold_pct: float
    factors: list[dict]              # [{feature, effect, direction, phrase}]
    model_kind: str

    def as_dict(self) -> dict:
        return {
            "date": self.date,
            "drop_probability": round(self.drop_probability, 4),
            "price_per_quintal": round(self.price_per_quintal, 2),
            "horizon_days": self.horizon_days,
            "drop_threshold_pct": self.drop_threshold_pct,
            "factors": self.factors,
            "model_kind": self.model_kind,
        }


def score_asof(date, top_n: int = 4) -> Score:
    date = pd.Timestamp(date).normalize()
    model = load_model()
    row = feature_row_asof(date)

    X = row[model.feature_cols].to_frame().T.astype(float)
    prob = float(model.predict_proba(X)[0])

    contribs = model.feature_contributions(row)
    # Calendar terms help the model but make a poor human explanation — keep them
    # out of the headline drivers.
    contribs = {k: v for k, v in contribs.items() if k not in ("doy_sin", "doy_cos")}
    ranked = sorted(contribs.items(), key=lambda kv: abs(kv[1]), reverse=True)

    factors = []
    for feat, effect in ranked[:top_n]:
        up, down = _FEATURE_PHRASES.get(feat, (feat, feat))
        factors.append({
            "feature": feat,
            "effect": round(float(effect), 4),
            "direction": "raises_sell_pressure" if effect > 0 else "supports_holding",
            "phrase": up if effect > 0 else down,
            "value": round(float(row[feat]), 4),
        })

    return Score(
        date=date.strftime("%Y-%m-%d"),
        drop_probability=prob,
        price_per_quintal=float(row["price"]),
        horizon_days=model.horizon_days,
        drop_threshold_pct=model.drop_threshold_pct,
        factors=factors,
        model_kind=model.kind,
    )
