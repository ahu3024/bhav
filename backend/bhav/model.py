"""LightGBM price-drop-risk classifier. Train once offline, serialize to
models/model.pkl. Falls back to a logistic-regression pipeline if LightGBM is
unavailable so the rest of the stack still runs."""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import DROP_THRESHOLD_PCT, HORIZON_DAYS, MODEL_PATH
from .features import FEATURE_COLS, training_frame


@dataclass
class TrainedModel:
    estimator: object
    kind: str                       # "lightgbm" | "logreg"
    feature_cols: list[str]
    metrics: dict
    horizon_days: int = HORIZON_DAYS
    drop_threshold_pct: float = DROP_THRESHOLD_PCT

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X = X[self.feature_cols]
        return self.estimator.predict_proba(X)[:, 1]

    def feature_contributions(self, row: pd.Series) -> dict[str, float]:
        """Per-feature push toward 'drop' for one row.

        LightGBM: SHAP values via pred_contrib. Logreg: standardized coef * value.
        Positive => pushed the probability up (toward SELL).
        """
        x = row[self.feature_cols].astype(float).values.reshape(1, -1)
        if self.kind == "lightgbm":
            booster = self.estimator.booster_
            contrib = booster.predict(x, pred_contrib=True)[0][:-1]
            return dict(zip(self.feature_cols, contrib.tolist()))
        clf = self.estimator.named_steps["clf"]
        scaler = self.estimator.named_steps["scaler"]
        z = (x[0] - scaler.mean_) / scaler.scale_
        return dict(zip(self.feature_cols, (z * clf.coef_[0]).tolist()))


def _build_estimator():
    try:
        from lightgbm import LGBMClassifier

        return LGBMClassifier(
            n_estimators=400,
            learning_rate=0.03,
            num_leaves=31,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_samples=30,
            reg_lambda=1.0,
            random_state=42,
            verbosity=-1,
        ), "lightgbm"
    except Exception:
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        return Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ]), "logreg"


def _time_series_metrics(estimator, X, y, kind) -> dict:
    from sklearn.metrics import average_precision_score, roc_auc_score
    from sklearn.model_selection import TimeSeriesSplit

    aucs, aps = [], []
    for tr, te in TimeSeriesSplit(n_splits=4).split(X):
        est, _ = _build_estimator() if kind != "clone" else (estimator, kind)
        est.fit(X.iloc[tr], y.iloc[tr])
        p = est.predict_proba(X.iloc[te])[:, 1]
        if y.iloc[te].nunique() > 1:
            aucs.append(roc_auc_score(y.iloc[te], p))
            aps.append(average_precision_score(y.iloc[te], p))
    return {
        "cv_roc_auc": float(np.mean(aucs)) if aucs else None,
        "cv_avg_precision": float(np.mean(aps)) if aps else None,
        "base_rate": float(y.mean()),
        "n_train": int(len(y)),
    }


def train() -> TrainedModel:
    frame = training_frame()
    X = frame[FEATURE_COLS]
    y = frame["target"].astype(int)

    estimator, kind = _build_estimator()
    metrics = _time_series_metrics(estimator, X, y, kind)
    estimator.fit(X, y)

    tm = TrainedModel(
        estimator=estimator, kind=kind, feature_cols=FEATURE_COLS,
        metrics=metrics,
    )
    with open(MODEL_PATH, "wb") as fh:
        pickle.dump(tm, fh)
    return tm


_CACHE: TrainedModel | None = None


def load_model() -> TrainedModel:
    global _CACHE
    if _CACHE is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"{MODEL_PATH} not found — run `python -m bhav.scripts.build`"
            )
        with open(MODEL_PATH, "rb") as fh:
            _CACHE = pickle.load(fh)
    return _CACHE


def main() -> None:
    tm = train()
    print(f"model: {tm.kind}")
    print(json.dumps(tm.metrics, indent=2))
    print(f"-> {MODEL_PATH}")


if __name__ == "__main__":
    main()
