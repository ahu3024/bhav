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

# Raised when data/bhav.db has no tables yet (pipeline not run). Treated as
# "backend not provisioned" -> 503, not a 500, so the browser still gets CORS
# headers and the frontend can show a real message.
NOT_PROVISIONED = (FileNotFoundError, pd.errors.DatabaseError)

from .alert_engine import build_alert
from .backtest import backtest_date, track_record
from .config import (
    CROP,
    DISTRICT,
    LAT,
    LON,
    NDVI_COMPOSITE_DAYS,
    NDVI_MATURITY_THRESHOLD,
)
from .db import read_df
from .message import (
    LANGS,
    build_message,
    send_alert,
    verify_credentials,
    whatsapp_status,
)
from .subscribers import (
    active_subscribers,
    log_send,
    recent_log,
    register,
    summary as subscriber_summary,
    unsubscribe,
)
from .model import load_model
from .phenology import describe as describe_ndvi
from .weather_overlay import describe as describe_weather
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
    except NOT_PROVISIONED as e:
        raise HTTPException(503, f"backend not provisioned — run the pipeline: {e}")


@app.get("/alert")
def alert(date: str = Query(..., description="YYYY-MM-DD")):
    try:
        return build_alert(date).as_dict()
    except NOT_PROVISIONED as e:
        raise HTTPException(503, f"backend not provisioned — run the pipeline: {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/backtest")
def backtest(date: str = Query(..., description="YYYY-MM-DD")):
    try:
        return backtest_date(date)
    except NOT_PROVISIONED as e:
        raise HTTPException(503, f"backend not provisioned — run the pipeline: {e}")
    except ValueError as e:
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


@app.post("/message/preview/all")
def message_preview_all(body: MessageIn):
    """The same alert in all three languages — what the registration form shows
    so a farmer picks a language by reading it, not by guessing."""
    alert_obj = build_alert(body.date or _latest_date(), persist=False)
    return {
        "alert": alert_obj.as_dict(),
        "texts": {
            lang: build_message(alert_obj, crop=CROP.capitalize(),
                                market=body.market, lang=lang)
            for lang in LANGS
        },
    }


class SendIn(MessageIn):
    to: str
    channel: str = "whatsapp"     # whatsapp | template | text_only


@app.post("/message/send")
def message_send(body: SendIn):
    alert_obj = build_alert(body.date or _latest_date(), persist=False)
    text = build_message(alert_obj, crop=CROP.capitalize(),
                         market=body.market, lang=body.lang)
    result = send_alert(body.to, text, channel=body.channel)
    log_send(body.to, alert_obj.date, body.lang, result, text)
    return result


# --- registration ----------------------------------------------------------

class SubscribeIn(BaseModel):
    phone: str
    name: str | None = None
    village_pin: str | None = None
    lang: str = "en"
    sell_window: str | None = None
    channel: str = "whatsapp"
    send_welcome: bool = True


@app.post("/subscribe")
def subscribe(body: SubscribeIn):
    """Register a phone and, unless asked not to, send it the current signal.

    The welcome send is the demo's second north-star moment — register on stage,
    the alert arrives — so it is on by default but always reported separately
    from the registration itself. A failed send never loses the registration.
    """
    try:
        sub = register(
            phone=body.phone, name=body.name, village_pin=body.village_pin,
            lang=body.lang, sell_window=body.sell_window, channel=body.channel,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    out = {"subscriber": sub, "welcome": None}
    if body.send_welcome:
        try:
            alert_obj = build_alert(_latest_date(), persist=False)
            text = build_message(alert_obj, crop=CROP.capitalize(),
                                 lang=body.lang)
            result = send_alert(sub["phone"], text, channel=body.channel)
            log_send(sub["phone"], alert_obj.date, body.lang, result, text)
            out["welcome"] = result
        except NOT_PROVISIONED as e:
            out["welcome"] = {"sent": False, "reason": f"no signal yet: {e}"}
    return out


class UnsubscribeIn(BaseModel):
    phone: str


@app.post("/unsubscribe")
def unsubscribe_ep(body: UnsubscribeIn):
    return unsubscribe(body.phone)


@app.get("/subscribers")
def subscribers_ep():
    """Counts only — the phone list is not something this API hands out."""
    return subscriber_summary()


@app.get("/message/status")
def message_status():
    """What delivery is actually possible right now. Sends nothing."""
    return {**whatsapp_status(), "credentials": verify_credentials()}


@app.get("/message/log")
def message_log(limit: int = Query(50, ge=1, le=500)):
    df = recent_log(limit)
    return {"n": int(len(df)), "rows": df.to_dict("records")}


class BroadcastIn(BaseModel):
    date: str | None = None
    dry_run: bool = True
    market: str = "Lasalgaon"


@app.post("/broadcast")
def broadcast_ep(body: BroadcastIn):
    """Send today's signal to every active subscriber.

    `dry_run` defaults to True: this is the one endpoint that can message a
    room full of real people, so firing it for real has to be deliberate.
    """
    try:
        alert_obj = build_alert(body.date or _latest_date(), persist=False)
    except NOT_PROVISIONED as e:
        raise HTTPException(503, f"backend not provisioned — run the pipeline: {e}")

    people = active_subscribers()
    results = []
    for _, row in people.iterrows():
        lang = row.get("lang") or "en"
        text = build_message(alert_obj, crop=CROP.capitalize(),
                             market=body.market, lang=lang)
        if body.dry_run:
            results.append({"phone": row["phone"], "lang": lang,
                            "sent": False, "dry_run": True, "preview": text})
            continue
        result = send_alert(row["phone"], text,
                            channel=row.get("channel") or "whatsapp")
        log_send(row["phone"], alert_obj.date, lang, result, text)
        results.append({"phone": row["phone"], "lang": lang, **result})

    return {
        "alert_date": alert_obj.date,
        "color": alert_obj.color,
        "dry_run": body.dry_run,
        "recipients": int(len(people)),
        "sent": sum(1 for r in results if r.get("sent")),
        "results": results,
    }


@app.get("/ndvi")
def ndvi_series(
    start: str | None = None,
    end: str | None = None,
    days: int = Query(365, ge=30, le=4000,
                      description="trailing window when start/end are omitted"),
):
    """Sentinel-2 NDVI for the belt: the raw 10-day composites the satellite
    actually produced, plus the causally-smoothed daily curve the model reads.

    The two are returned separately on purpose — the composites show where there
    was a real observation (and where the monsoon blinded us), the smooth line
    shows what the model saw on each day.
    """
    from .features import build_features

    try:
        feats = build_features(with_target=False)
    except NOT_PROVISIONED as e:
        raise HTTPException(503, f"backend not provisioned — run the pipeline: {e}")

    end_ts = pd.Timestamp(end) if end else feats.index.max()
    start_ts = pd.Timestamp(start) if start else end_ts - pd.Timedelta(days=days)
    window = feats.loc[start_ts:end_ts]
    if window.empty:
        raise HTTPException(400, "no NDVI in that range")

    raw = read_df(
        "SELECT date, value, pct_mature, clear_frac, obs_date, n_obs FROM ndvi "
        "WHERE district = ? AND obs_date BETWEEN ? AND ? ORDER BY obs_date",
        (DISTRICT, start_ts.strftime("%Y-%m-%d"), end_ts.strftime("%Y-%m-%d")),
    )

    latest = window.iloc[-1]
    return {
        "district": DISTRICT,
        "crop": CROP,
        "start": start_ts.strftime("%Y-%m-%d"),
        "end": end_ts.strftime("%Y-%m-%d"),
        "maturity_threshold": NDVI_MATURITY_THRESHOLD,
        "composite_days": NDVI_COMPOSITE_DAYS,
        "current": describe_ndvi(latest),
        "composites": [
            {
                "date": r["obs_date"] or r["date"],
                "ndvi": _round(r["value"]),
                "pct_mature": _round(r["pct_mature"]),
                "clear_frac": _round(r["clear_frac"], 3),
                "n_obs": None if pd.isna(r["n_obs"]) else int(r["n_obs"]),
            }
            for _, r in raw.iterrows()
        ],
        "daily": [
            {
                "date": d.strftime("%Y-%m-%d"),
                "ndvi": _round(row["ndvi"]),
                "smooth": _round(row["ndvi_smooth"]),
                "pct_mature": _round(row["ndvi_pct_mature"]),
                "obs_age_days": None if pd.isna(row["ndvi_obs_age_days"])
                else int(row["ndvi_obs_age_days"]),
            }
            for d, row in window.iterrows()
        ],
    }


@app.get("/ndvi/asof")
def ndvi_asof(date: str = Query(..., description="YYYY-MM-DD")):
    """The satellite's read of the crop on one date — stage, greening rate,
    days since peak, % of the belt past maturity, and how old the read is."""
    from .features import feature_row_asof

    try:
        row = feature_row_asof(date)
    except NOT_PROVISIONED as e:
        raise HTTPException(503, f"backend not provisioned — run the pipeline: {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"district": DISTRICT, "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            **describe_ndvi(row)}


@app.get("/weather")
def weather_series(
    start: str | None = None,
    end: str | None = None,
    days: int = Query(365, ge=30, le=4000,
                      description="trailing window when start/end are omitted"),
):
    """The weather overlay: daily rain and humidity, plus the two derived
    judgements the model and the alert actually use — can the crop be lifted
    and cured (harvest window), and can it be held (rot risk)."""
    from .features import build_features

    try:
        feats = build_features(with_target=False)
    except NOT_PROVISIONED as e:
        raise HTTPException(503, f"backend not provisioned — run the pipeline: {e}")

    end_ts = pd.Timestamp(end) if end else feats.index.max()
    start_ts = pd.Timestamp(start) if start else end_ts - pd.Timedelta(days=days)
    window = feats.loc[start_ts:end_ts]
    if window.empty:
        raise HTTPException(400, "no weather in that range")

    raw = read_df(
        "SELECT date, rainfall, humidity_mean, temp_max FROM weather "
        "WHERE district = ? AND date BETWEEN ? AND ? ORDER BY date",
        (DISTRICT, start_ts.strftime("%Y-%m-%d"), end_ts.strftime("%Y-%m-%d")),
    )
    raw["date"] = pd.to_datetime(raw["date"])
    raw = raw.set_index("date").reindex(window.index)

    return {
        "district": DISTRICT,
        "crop": CROP,
        "start": start_ts.strftime("%Y-%m-%d"),
        "end": end_ts.strftime("%Y-%m-%d"),
        "current": describe_weather(window.iloc[-1]),
        "daily": [
            {
                "date": d.strftime("%Y-%m-%d"),
                "rain_mm": _round(raw.loc[d, "rainfall"], 1),
                "humidity": _round(raw.loc[d, "humidity_mean"], 1),
                "temp_max": _round(raw.loc[d, "temp_max"], 1),
                "harvest_score": _round(row.get("harvest_score"), 3),
                "rot_score": _round(row.get("rot_score"), 3),
            }
            for d, row in window.iterrows()
        ],
    }


@app.get("/prices")
def prices_series(
    start: str | None = None,
    end: str | None = None,
    days: int = Query(365, ge=30, le=4000),
):
    """The cleaned district mandi series, plus what the cleaning had to do.

    Nominal and deflated prices are both returned: nominal is what a farmer is
    quoted, deflated is what the model compares across years.
    """
    from .prices import district_daily, summary

    try:
        d = district_daily()
    except NOT_PROVISIONED as e:
        raise HTTPException(503, f"backend not provisioned — run the pipeline: {e}")

    end_ts = pd.Timestamp(end) if end else d.index.max()
    start_ts = pd.Timestamp(start) if start else end_ts - pd.Timedelta(days=days)
    window = d.loc[start_ts:end_ts]
    if window.empty:
        raise HTTPException(400, "no prices in that range")

    return {
        "district": DISTRICT,
        "crop": CROP,
        "source": "Agmarknet (agmarknet.gov.in)",
        "quality": summary(),
        "daily": [
            {
                "date": i.strftime("%Y-%m-%d"),
                "price": _round(r["price"], 2),
                "price_real": _round(r["price_real"], 2),
                "price_min": _round(r["price_min"], 2),
                "price_max": _round(r["price_max"], 2),
                "arrivals_tonnes": _round(r["arrivals"], 1),
                "markets": int(r["n_markets"]),
                "traded": bool(r["traded"]),
            }
            for i, r in window.iterrows()
        ],
    }


@app.get("/weather/asof")
def weather_asof(date: str = Query(..., description="YYYY-MM-DD")):
    """The weather overlay on one date — harvest window, rot risk, and the
    fortnight of dry days / wet spell / humidity behind them."""
    from .features import feature_row_asof

    try:
        row = feature_row_asof(date)
    except NOT_PROVISIONED as e:
        raise HTTPException(503, f"backend not provisioned — run the pipeline: {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"district": DISTRICT, "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            **describe_weather(row)}


def _round(v, nd: int = 4):
    return None if v is None or pd.isna(v) else round(float(v), nd)


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
