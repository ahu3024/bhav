"""Time-travel engine (roadmap §1.2 — never cut this).

Re-run the alert engine as if "today" were any past date, then look up what the
price actually did, and compare against the naive "sold blind on the usual date"
baseline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .alert_engine import build_alert
from .config import DISTRICT, DROP_THRESHOLD_PCT, HORIZON_DAYS
from .features import build_features


def _price_frame() -> pd.Series:
    df = build_features(with_target=False)
    return df["price"]


def backtest_date(date, horizon_days: int = HORIZON_DAYS) -> dict:
    """What the alert said on `date`, and what actually happened after."""
    date = pd.Timestamp(date).normalize()
    price = _price_frame()
    if date not in price.index:
        date = price.index[price.index.get_indexer([date], method="nearest")[0]]

    alert = build_alert(date, persist=False)
    p0 = float(price.loc[date])

    future = price.loc[date + pd.Timedelta(days=1):
                       date + pd.Timedelta(days=horizon_days)]
    realized = {
        "horizon_days": horizon_days,
        "price_now": round(p0, 2),
        "price_min": round(float(future.min()), 2) if len(future) else None,
        "price_max": round(float(future.max()), 2) if len(future) else None,
        "price_end": round(float(future.iloc[-1]), 2) if len(future) else None,
    }
    if len(future):
        realized["max_drop_pct"] = round(float(future.min() / p0 - 1.0), 4)
        realized["actually_dropped"] = bool(
            future.min() / p0 - 1.0 <= -DROP_THRESHOLD_PCT
        )

    # Outcome vs "sold blind today".
    sell_blind = p0
    if alert.color == "RED":
        strategy_price = float(
            price.loc[alert.window_start:alert.window_end].mean()
        )
        action = "sold in the alert window"
    else:  # held to end of horizon (or window for AMBER)
        hold_to = alert.window_end if alert.color == "AMBER" else (
            (date + pd.Timedelta(days=horizon_days)).strftime("%Y-%m-%d")
        )
        seg = price.loc[date:hold_to]
        strategy_price = float(seg.iloc[-1]) if len(seg) else p0
        action = "held past the usual sell date"

    delta = strategy_price - sell_blind
    move = realized.get("max_drop_pct")
    end_move = (
        (realized["price_end"] / p0 - 1.0)
        if realized.get("price_end") is not None else None
    )
    if move is None:
        hit = None                       # not enough future data to grade
    elif alert.color == "RED":
        hit = bool(realized.get("actually_dropped"))
    elif alert.color == "GREEN":
        # hold was right if price didn't fall through the threshold AND
        # you were no worse off at the end
        hit = bool(not realized.get("actually_dropped")
                   and (end_move is None or end_move >= -0.03))
    else:  # AMBER — caution was right if the move stayed modest either way
        hit = bool(move > -DROP_THRESHOLD_PCT
                   and (end_move is None or abs(end_move) < DROP_THRESHOLD_PCT))

    return {
        "alert": alert.as_dict(),
        "realized": realized,
        "outcome": {
            "action": action,
            "strategy_price_per_quintal": round(strategy_price, 2),
            "sold_blind_price_per_quintal": round(sell_blind, 2),
            "delta_per_quintal": round(delta, 2),
            "delta_pct": round(delta / sell_blind, 4),
            "call_was_right": bool(hit),
        },
    }


def track_record(start=None, end=None, step_days: int = 7) -> dict:
    """Walk the history weekly, score every date, tally hits and misses.

    This is the "shows hits *and* misses" view (roadmap §1.4).
    """
    price = _price_frame()
    start = pd.Timestamp(start) if start else price.index.min() + pd.Timedelta(days=400)
    end = pd.Timestamp(end) if end else price.index.max() - pd.Timedelta(days=HORIZON_DAYS)

    rows = []
    for d in pd.date_range(start, end, freq=f"{step_days}D"):
        if d not in price.index:
            continue
        try:
            r = backtest_date(d)
        except Exception:
            continue
        rows.append({
            "date": r["alert"]["date"],
            "color": r["alert"]["color"],
            "confidence": r["alert"]["confidence"],
            "drop_probability": r["alert"]["score"]["drop_probability"],
            "actually_dropped": r["realized"].get("actually_dropped"),
            "delta_pct": r["outcome"]["delta_pct"],
            "call_was_right": r["outcome"]["call_was_right"],
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return {"n": 0, "rows": []}

    graded = df.dropna(subset=["actually_dropped", "call_was_right"])
    by_color = {
        c: {
            "n": int((graded.color == c).sum()),
            "hit_rate": round(float(graded.loc[graded.color == c, "call_was_right"].mean()), 3)
            if (graded.color == c).any() else None,
        }
        for c in ("RED", "AMBER", "GREEN")
    }
    return {
        "n": int(len(df)),
        "graded": int(len(graded)),
        "overall_hit_rate": round(float(graded["call_was_right"].mean()), 3),
        "avg_delta_pct": round(float(df["delta_pct"].mean()), 4),
        "by_color": by_color,
        "rows": df.to_dict("records"),
    }
