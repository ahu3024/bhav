"""Rules layer on top of the model score (roadmap §2).

score -> color tag + ₹ impact + a 3-5 day sell *window* (not a single day: the
anti-herd design) + a one-line reason from the dominant driver.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import CAUTION_PROB, DISTRICT, SELL_PROB, WINDOW_DAYS
from .db import cursor
from .scoring import Score, score_asof

_COLOR = {"RED": "Sell now", "AMBER": "Caution", "GREEN": "Wait"}


@dataclass
class Alert:
    district: str
    date: str
    color: str                      # RED | AMBER | GREEN
    label: str
    window_start: str
    window_end: str
    expected_impact: float          # ₹/quintal vs today's price over the horizon
    confidence: int                 # 0-100, raw: distance from a coin flip
    # Calibrated probability that *this call* is the right one, as a percentage.
    # For a sell-side call that is P(crash); for WAIT it is P(no crash). Unlike
    # `confidence` this is a real probability a person can act on, which is why
    # the dashboard shows it instead.
    calibrated_confidence: int
    reason: str
    score: Score

    def as_dict(self) -> dict:
        d = {
            "district": self.district,
            "date": self.date,
            "color": self.color,
            "label": self.label,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "expected_impact_per_quintal": round(self.expected_impact, 0),
            "confidence": self.confidence,
            "calibrated_confidence": self.calibrated_confidence,
            "reason": self.reason,
            "score": self.score.as_dict(),
        }
        return d


def _color(prob: float) -> str:
    if prob >= SELL_PROB:
        return "RED"
    if prob >= CAUTION_PROB:
        return "AMBER"
    return "GREEN"


def _expected_impact(score: Score, color: str) -> float:
    """Signed ₹/quintal move we expect over the horizon.

    Scale the threshold move by how far the probability sits from 0.5 — crude but
    explainable, and good enough for a demo headline number.
    """
    p = score.drop_probability
    magnitude = score.drop_threshold_pct * score.price_per_quintal
    if color == "RED":
        return -magnitude * (0.5 + p) / 1.0
    if color == "GREEN":
        # mild upside when hold-signals dominate
        return magnitude * (0.6 - p)
    return -magnitude * (p - 0.35)


def _window(date: pd.Timestamp, color: str) -> tuple[str, str]:
    if color == "RED":
        start, end = date, date + pd.Timedelta(days=WINDOW_DAYS - 1)
    elif color == "AMBER":
        start = date + pd.Timedelta(days=2)
        end = date + pd.Timedelta(days=2 + WINDOW_DAYS - 1)
    else:  # GREEN — hold, re-check after ~a week
        start = date + pd.Timedelta(days=7)
        end = start + pd.Timedelta(days=WINDOW_DAYS - 1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _reason(score: Score, color: str) -> str:
    drivers = score.factors
    if not drivers:
        return "Model signal only; no single dominant driver."
    lead = drivers[0]["phrase"]
    second = drivers[1]["phrase"] if len(drivers) > 1 else None
    verdict = {
        "RED": "sell into the current window",
        "AMBER": "part-sell and watch closely",
        "GREEN": "hold — conditions favour a better price",
    }[color]
    tail = f"; also {second}" if second else ""
    return f"{lead.capitalize()}{tail} — {verdict}."


def build_alert(date, persist: bool = True) -> Alert:
    date = pd.Timestamp(date).normalize()
    score = score_asof(date)
    color = _color(score.drop_probability)
    impact = _expected_impact(score, color)
    w_start, w_end = _window(date, color)
    confidence = int(round(100 * abs(score.drop_probability - 0.5) * 2))
    # GREEN argues the crash will *not* happen, so its confidence is the
    # complement. Stated the other way round a "Wait" would read as 20%
    # confident precisely when the model is most sure nothing is coming.
    p_cal = score.calibrated_probability
    calibrated_confidence = int(round(100 * (p_cal if color != "GREEN" else 1 - p_cal)))
    reason = _reason(score, color)

    alert = Alert(
        district=DISTRICT,
        date=score.date,
        color=color,
        label=_COLOR[color],
        window_start=w_start,
        window_end=w_end,
        expected_impact=impact,
        confidence=confidence,
        calibrated_confidence=calibrated_confidence,
        reason=reason,
        score=score,
    )

    if persist:
        with cursor() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO alerts (district, date, color, "
                "window_start, window_end, expected_impact, reason, confidence) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (alert.district, alert.date, alert.color, alert.window_start,
                 alert.window_end, alert.expected_impact, alert.reason,
                 alert.confidence),
            )
    return alert
