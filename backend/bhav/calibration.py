"""Probability calibration for the alert score.

The raw LightGBM score ranks well but its top end is not trustworthy: on
walk-forward data the 0.7–1.0 bin predicted 0.83 and observed 0.29. A farmer
being shown "87% confidence" on a call that is wrong most of the time is worse
than being shown nothing.

So an isotonic layer sits on top of the model. Isotonic (rather than Platt)
because the miscalibration here is non-monotone in shape — the top bin inverts —
and isotonic can flatten a region without being forced through a sigmoid.

Fit on the **validation year only**, never on the training years: a model's
in-sample probabilities are overconfident by construction, so a calibrator
learned from them would be learning the wrong mapping. This is the whole reason
a validation year is held out.

The underlying model is not touched — this is a monotone transform of its output.
"""

from __future__ import annotations

import pickle

import numpy as np

from .config import CALIBRATOR_PATH

_CACHE = None

# Isotonic is a step function and saturates: its end steps land on exactly 0.0
# and 1.0. Fit on 366 days, the finest frequency it can actually resolve is
# ~1/366, so a hard 1.0 is an artefact of the method rather than a claim the
# data supports — and "100% confidence" is the single worst number to put in
# front of a farmer. Bounded to a range the sample size can justify.
CAL_FLOOR, CAL_CEIL = 0.02, 0.98


def fit_calibrator(probs: np.ndarray, y: np.ndarray):
    """Isotonic map from raw score to observed crash frequency."""
    from sklearn.isotonic import IsotonicRegression

    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    iso.fit(np.asarray(probs, dtype=float), np.asarray(y, dtype=float))
    return iso


def save_calibrator(iso, meta: dict | None = None) -> None:
    with open(CALIBRATOR_PATH, "wb") as fh:
        pickle.dump({"isotonic": iso, "meta": meta or {}}, fh)


def load_calibrator():
    """The fitted calibrator, or None if one has never been built.

    Returning None rather than raising keeps the pipeline runnable on a fresh
    clone — callers fall back to the raw score.
    """
    global _CACHE
    if _CACHE is None:
        if not CALIBRATOR_PATH.exists():
            return None
        with open(CALIBRATOR_PATH, "rb") as fh:
            _CACHE = pickle.load(fh)
    return _CACHE


def calibrate(prob: float) -> tuple[float, bool]:
    """(calibrated probability, whether a calibrator was actually applied)."""
    bundle = load_calibrator()
    if bundle is None:
        return float(prob), False
    value = float(bundle["isotonic"].predict([float(prob)])[0])
    return min(max(value, CAL_FLOOR), CAL_CEIL), True


def calibrator_meta() -> dict:
    bundle = load_calibrator()
    return dict(bundle["meta"]) if bundle else {}
