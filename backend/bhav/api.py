"""FastAPI surface for the judge-facing app.

    GET  /health
    GET  /alert/today
    GET  /alert?date=YYYY-MM-DD
    GET  /backtest?date=YYYY-MM-DD
    GET  /track-record?step_days=7
    GET  /warehouse/nearest?lat=&lon=
    POST /partial-sell
    POST /message/preview      {date?, lang}
    POST /message/send         {to, date?, lang}
    GET  /model/info
"""

from __future__ import annotations

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .alert_engine import build_alert
from .backtest import backtest_date, track_record
from .config import CROP, DISTRICT, LAT, LON
from .message import build_message, send_whatsapp
from .model import load_model
from .warehouses import nearest, partial_sell

app = FastAPI(title="Bhav API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _latest_date() -> pd.Timestamp:
    from .features import build_features

    return build_features(with_target=False).index.max()


@app.get("/health")
def health():
    return {"ok": True, "district": DISTRICT, "crop": CROP}


@app.get("/alert/today")
def alert_today():
    try:
        return build_alert(_latest_date()).as_dict()
    except FileNotFoundError as e:
        raise HTTPException(503, str(e))


@app.get("/alert")
def alert(date: str = Query(..., description="YYYY-MM-DD")):
    try:
        return build_alert(date).as_dict()
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))


@app.get("/backtest")
def backtest(date: str = Query(..., description="YYYY-MM-DD")):
    try:
        return backtest_date(date)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))


@app.get("/track-record")
def track(step_days: int = 7, start: str | None = None, end: str | None = None):
    return track_record(start=start, end=end, step_days=step_days)


@app.get("/warehouse/nearest")
def warehouse_nearest(lat: float = LAT, lon: float = LON, limit: int = 3):
    return {"warehouses": nearest(lat, lon, limit)}


class PartialSellIn(BaseModel):
    cash_need_rupees: float
    total_quintals: float
    price_per_quintal: float | None = None
    date: str | None = None


@app.post("/partial-sell")
def partial_sell_ep(body: PartialSellIn):
    price = body.price_per_quintal
    if price is None:
        price = build_alert(
            body.date or _latest_date(), persist=False
        ).score.price_per_quintal
    return partial_sell(body.cash_need_rupees, body.total_quintals, price)


class MessageIn(BaseModel):
    date: str | None = None
    lang: str = "en"
    market: str = "Lasalgaon"


@app.post("/message/preview")
def message_preview(body: MessageIn):
    alert_obj = build_alert(body.date or _latest_date(), persist=False)
    return {
        "text": build_message(alert_obj, crop=CROP.capitalize(),
                              market=body.market, lang=body.lang),
        "alert": alert_obj.as_dict(),
    }


class SendIn(MessageIn):
    to: str


@app.post("/message/send")
def message_send(body: SendIn):
    alert_obj = build_alert(body.date or _latest_date(), persist=False)
    text = build_message(alert_obj, crop=CROP.capitalize(),
                         market=body.market, lang=body.lang)
    return send_whatsapp(body.to, text)


@app.get("/model/info")
def model_info():
    try:
        m = load_model()
    except FileNotFoundError as e:
        raise HTTPException(503, str(e))
    return {
        "kind": m.kind,
        "horizon_days": m.horizon_days,
        "drop_threshold_pct": m.drop_threshold_pct,
        "features": m.feature_cols,
        "metrics": m.metrics,
    }
