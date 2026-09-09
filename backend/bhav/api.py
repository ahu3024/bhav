"""FastAPI surface for the judge-facing app.

Read endpoints (cached — see cache.py; every one carries an ETag keyed on the
data version, so a browser that already has the answer gets a 304):

    GET  /health               liveness. Cheap, no database, always 200.
    GET  /readyz               readiness: is there data and a model to serve
    GET  /meta                 data version, coverage, what delivery is possible
    GET  /snapshot             everything a page needs, in ONE request
    GET  /alert/today
    GET  /alert?date=YYYY-MM-DD
    GET  /backtest?date=YYYY-MM-DD
    GET  /track-record?step_days=7
    GET  /ndvi, /ndvi/asof, /weather, /weather/asof, /prices
    GET  /warehouse/nearest?lat=&lon=
    GET  /model/info

Write / delivery endpoints:

    POST /partial-sell
    POST /message/preview      {date?, lang}
    POST /message/preview/all
    POST /subscribe            {phone, lang, ...}
    POST /unsubscribe, /resubscribe

Admin — anything that can message real people or read who they are. Guarded
by BHAV_ADMIN_TOKEN. Leaving it unset leaves them open, which is what you want
on localhost and never on a host, so the boot log and /readyz both say so
loudly rather than the API quietly failing closed on your own machine:

    POST /message/send         {to, date?, lang}
    POST /broadcast            {dry_run}
    GET  /message/status, /message/qr, /message/check, /message/log
    GET  /subscribers
    POST /admin/cache/clear
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

# Raised when data/bhav.db has no tables yet (pipeline not run). Treated as
# "backend not provisioned" -> 503, not a 500, so the browser still gets CORS
# headers and the frontend can show a real message.
NOT_PROVISIONED = (FileNotFoundError, pd.errors.DatabaseError)

from . import cache
from .alert_engine import build_alert
from .backtest import backtest_date, track_record
from .bootstrap import ensure_data
from .config import (
    ADMIN_TOKEN,
    CORS_ORIGINS,
    CROP,
    DISTRICT,
    LAT,
    LON,
    NDVI_COMPOSITE_DAYS,
    NDVI_MATURITY_THRESHOLD,
    PERSIST_ALERTS,
    WARM_ON_BOOT,
)
from .db import data_version, read_df
from .message import LANGS, build_message
from .whatsapp import (
    check_number,
    qr_png,
    send_alert,
    verify_credentials,
    whatsapp_status,
)
from .subscribers import (
    active_subscribers,
    log_send,
    recent_log,
    register,
    resubscribe,
    summary as subscriber_summary,
    unsubscribe,
)
from .model import load_model
from .phenology import describe as describe_ndvi
from .weather_overlay import describe as describe_weather
from .warehouses import nearest, partial_sell

log = logging.getLogger("bhav.api")

# What the boot did, and how warm we are. Surfaced by /readyz so a deploy that
# came up without data says so instead of failing one request at a time.
BOOT: dict = {"bootstrap": None, "warm": "pending", "warm_error": None,
              "started_at": time.time()}


def _warm() -> None:
    """Pull the feature matrix and the model into memory before the first
    caller needs them.

    A container starts cold on every deploy, and on a free instance also after
    every idle spin-down. Whoever arrives first would otherwise pay for the
    whole pipeline read. Runs on a thread so the port is listening — and the
    platform's health check is passing — while it happens.
    """
    try:
        from .features import build_features

        build_features(with_target=False)
        try:
            load_model()
        except FileNotFoundError as e:
            BOOT["warm_error"] = str(e)
        BOOT["warm"] = "ready"
        log.info("warm-up complete")
    except Exception as e:  # a cold start must never take the process down
        BOOT["warm"] = "failed"
        BOOT["warm_error"] = str(e)
        log.warning("warm-up failed: %s", e)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    BOOT["bootstrap"] = ensure_data()
    for warning in BOOT["bootstrap"].get("warnings", []):
        log.warning("bootstrap: %s", warning)
    if not ADMIN_TOKEN:
        log.warning(
            "BHAV_ADMIN_TOKEN is unset — /broadcast, /message/send and the "
            "subscriber endpoints are OPEN. Fine on localhost, not on a host."
        )
    if WARM_ON_BOOT:
        threading.Thread(target=_warm, name="bhav-warm", daemon=True).start()
    else:
        BOOT["warm"] = "skipped"
    yield


app = FastAPI(title="Bhav API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["ETag", "X-Bhav-Data-Version", "X-Bhav-Cache"],
)
# A year of NDVI is mostly repeated digits; gzip takes /snapshot from a few
# hundred KB to a few tens. Below 1 KB the round trip costs more than it saves.
app.add_middleware(GZipMiddleware, minimum_size=1024)


# --- admin auth --------------------------------------------------------------


def require_admin(request: Request, token: str | None = Query(None, include_in_schema=False)):
    """Bearer token on anything that can message a real person.

    Also accepts `?token=` because /message/qr is opened in a browser — you
    cannot set a header on an <img> src, and a QR you cannot open is a session
    you cannot link.
    """
    if not ADMIN_TOKEN:
        return  # unset = open; the boot log and /readyz both say so
    header = request.headers.get("authorization", "")
    if header == f"Bearer {ADMIN_TOKEN}" or token == ADMIN_TOKEN:
        return
    raise HTTPException(401, "admin token required")


# --- registration rate limit -------------------------------------------------
#
# /subscribe is public and it sends a WhatsApp message. Left open, one bored
# person with a loop can get the linked account banned by Meta, which is not a
# recoverable failure. A small per-IP bucket is enough to stop that without
# getting in the way of a demo queue.

SUBSCRIBE_LIMIT = int(os.getenv("BHAV_SUBSCRIBE_LIMIT", "5"))
SUBSCRIBE_WINDOW = int(os.getenv("BHAV_SUBSCRIBE_WINDOW", "3600"))
_hits: dict[str, deque] = {}
_hits_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    # Behind a platform proxy the socket peer is the proxy, so the first hop in
    # X-Forwarded-For is the caller. Spoofable, but this is a courtesy limit.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_subscribe(request: Request) -> None:
    if SUBSCRIBE_LIMIT <= 0:
        return
    now = time.monotonic()
    ip = _client_ip(request)
    with _hits_lock:
        bucket = _hits.setdefault(ip, deque())
        while bucket and now - bucket[0] > SUBSCRIBE_WINDOW:
            bucket.popleft()
        if len(bucket) >= SUBSCRIBE_LIMIT:
            raise HTTPException(
                429,
                f"too many registrations from this address — {SUBSCRIBE_LIMIT} "
                f"per {SUBSCRIBE_WINDOW // 60} minutes",
            )
        bucket.append(now)
        if len(_hits) > 4096:  # bound the map; old buckets are all expired
            for key in [k for k, v in _hits.items() if not v or now - v[-1] > SUBSCRIBE_WINDOW]:
                _hits.pop(key, None)


# --- helpers -----------------------------------------------------------------


def _latest_date() -> pd.Timestamp:
    from .features import build_features

    return build_features(with_target=False).index.max()


def _round(v, nd: int = 4):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def _provisioned(e: Exception) -> HTTPException:
    return HTTPException(503, f"backend not provisioned — run the pipeline: {e}")


# --- liveness / readiness ----------------------------------------------------


@app.get("/health")
def health():
    """Liveness only. Never touches the database, so a platform health check
    cannot be failed by a slow query — and cannot keep a deploy from going
    live while the warm-up is still running."""
    return {"ok": True, "district": DISTRICT, "crop": CROP,
            "uptime_s": round(time.time() - BOOT["started_at"], 1)}


@app.get("/readyz")
def readyz():
    """Can this instance actually answer? Says why not, when it can't."""
    out = {
        "ok": False,
        "warm": BOOT["warm"],
        "warm_error": BOOT["warm_error"],
        "bootstrap": BOOT["bootstrap"],
        "admin_token_set": bool(ADMIN_TOKEN),
        "cache": cache.stats(),
    }
    try:
        out["latest_date"] = _latest_date().strftime("%Y-%m-%d")
        out["data_version"] = data_version()
        out["model"] = load_model().kind
        out["ok"] = True
    except NOT_PROVISIONED as e:
        out["error"] = f"no data: {e}"
    except Exception as e:
        out["error"] = str(e)
    if not out["ok"]:
        # A body, not a bare 503: the reason this instance cannot serve is the
        # only useful thing a readiness probe can tell you.
        return Response(content=json.dumps(out), media_type="application/json",
                        status_code=503)
    return out


@app.get("/meta")
def meta(request: Request):
    """What this instance is serving, and how fresh it is. Small and cacheable
    — a client can poll this to decide whether its cached payloads are stale
    without pulling a year of series data to find out.

    Deliberately does not report delivery: that means calling the bridge over
    the network, and this endpoint's whole point is being cheap. /delivery/status
    answers that."""

    def build():
        try:
            latest = _latest_date()
        except NOT_PROVISIONED as e:
            raise _provisioned(e)
        return {
            "district": DISTRICT,
            "crop": CROP,
            "latest_date": latest.strftime("%Y-%m-%d"),
            "data_version": data_version(),
            "horizon_days": load_model().horizon_days if _model_ok() else None,
        }

    # Short: this is the endpoint whose whole job is to notice new data.
    return cache.serve(request, "/meta", build, max_age=60)


def _model_ok() -> bool:
    try:
        load_model()
        return True
    except Exception:
        return False


# --- signal ------------------------------------------------------------------


def _alert_payload(date=None) -> dict:
    return build_alert(date if date is not None else _latest_date(),
                       persist=PERSIST_ALERTS).as_dict()


@app.get("/alert/today")
def alert_today(request: Request):
    def build():
        try:
            return _alert_payload()
        except NOT_PROVISIONED as e:
            raise _provisioned(e)

    return cache.serve(request, "/alert/today", build)


@app.get("/alert")
def alert(request: Request, date: str = Query(..., description="YYYY-MM-DD")):
    def build():
        try:
            return _alert_payload(date)
        except NOT_PROVISIONED as e:
            raise _provisioned(e)
        except ValueError as e:
            raise HTTPException(400, str(e))

    return cache.serve(request, "/alert", build, {"date": date})


@app.get("/backtest")
def backtest(request: Request, date: str = Query(..., description="YYYY-MM-DD")):
    def build():
        try:
            return backtest_date(date)
        except NOT_PROVISIONED as e:
            raise _provisioned(e)
        except ValueError as e:
            raise HTTPException(400, str(e))

    return cache.serve(request, "/backtest", build, {"date": date})


@app.get("/track-record")
def track(request: Request, step_days: int = 7,
          start: str | None = None, end: str | None = None):
    # The expensive one: a walk of the whole history, hundreds of scored dates.
    # It changes only when the data does, so it should be computed once per
    # ingest and then handed out.
    return cache.serve(
        request, "/track-record",
        lambda: track_record(start=start, end=end, step_days=step_days),
        {"step_days": step_days, "start": start, "end": end},
    )


@app.get("/warehouse/nearest")
def warehouse_nearest(request: Request, lat: float = LAT, lon: float = LON,
                      limit: int = 3):
    return cache.serve(
        request, "/warehouse/nearest",
        lambda: {"warehouses": nearest(lat, lon, limit)},
        {"lat": lat, "lon": lon, "limit": limit},
        max_age=86400,   # a godown does not move
    )


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


# --- messages ----------------------------------------------------------------


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


def _preview_all(date: str | None, market: str) -> dict:
    alert_obj = build_alert(date or _latest_date(), persist=False)
    return {
        "alert": alert_obj.as_dict(),
        "texts": {
            lang: build_message(alert_obj, crop=CROP.capitalize(),
                                market=market, lang=lang)
            for lang in LANGS
        },
    }


@app.get("/message/preview/all")
def message_preview_all_get(request: Request, date: str | None = None,
                            market: str = "Lasalgaon"):
    """The same alert in all three languages — what the registration form shows
    so a farmer picks a language by reading it, not by guessing.

    A GET because it only reads: the POST below still works, but a POST from a
    browser costs a CORS preflight before the request it is previewing, and
    cannot be cached by anything.
    """
    return cache.serve(request, "/message/preview/all",
                       lambda: _preview_all(date, market),
                       {"date": date, "market": market})


@app.post("/message/preview/all")
def message_preview_all(body: MessageIn):
    """Kept for callers that already POST here; the GET above is the one the
    site uses."""
    return _preview_all(body.date, body.market)


class SendIn(MessageIn):
    to: str


@app.post("/message/send", dependencies=[Depends(require_admin)])
def message_send(body: SendIn):
    alert_obj = build_alert(body.date or _latest_date(), persist=False)
    text = build_message(alert_obj, crop=CROP.capitalize(),
                         market=body.market, lang=body.lang)
    result = send_alert(body.to, text)
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


@app.post("/subscribe", dependencies=[Depends(rate_limit_subscribe)])
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
            result = send_alert(sub["phone"], text)
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


@app.post("/resubscribe")
def resubscribe_ep(body: UnsubscribeIn):
    """Opt back in. The bridge posts here when someone replies START."""
    return resubscribe(body.phone)


@app.get("/message/qr", dependencies=[Depends(require_admin)])
def message_qr():
    """The open-wa pairing QR, as a PNG, while the session is unlinked.

    This is how the sending phone gets attached: open it, scan it from
    WhatsApp -> Linked devices. Once linked it 409s, which is the success case.
    On a host, append ?token=<BHAV_ADMIN_TOKEN> — a browser cannot send the
    header, and this URL is a live handle on someone's WhatsApp account.
    """
    png = qr_png()
    if png is None:
        status = whatsapp_status()
        raise HTTPException(
            409,
            "no pairing QR right now — "
            + ("the session is already linked" if status["whatsapp_ready"]
               else f"bridge session is '{status['session_status']}'"),
        )
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.get("/message/check", dependencies=[Depends(require_admin)])
def message_check(phone: str = Query(..., description="number to test")):
    """Is this number actually on WhatsApp? Sends nothing."""
    return check_number(phone)


@app.get("/subscribers", dependencies=[Depends(require_admin)])
def subscribers_ep():
    """Counts only — the phone list is not something this API hands out."""
    return subscriber_summary()


@app.get("/message/status", dependencies=[Depends(require_admin)])
def message_status():
    """What delivery is actually possible right now, in full — including which
    number the session is linked to and where the bridge lives. Sends nothing.

    Admin-only: /delivery/status is the version a browser gets.
    """
    return {**whatsapp_status(), "credentials": verify_credentials()}


@app.get("/delivery/status")
def delivery_status(request: Request):
    """Whether an alert can actually be delivered right now — the public half.

    The registration form needs to tell a farmer whether the message it is
    promising will really arrive, so this much has to be public. Everything that
    identifies the deployment does not: the sending number, the bridge's
    address, the send counters and the pairing QR all stay behind the admin
    token. In particular the QR is a live handle on the sending WhatsApp
    account — anyone who scans it links *their* phone to this deployment — so it
    is never something a visitor's browser is handed.
    """

    def build():
        status = whatsapp_status()
        return {
            "ready": status["whatsapp_ready"],
            "reachable": status["configured"],
            # starting | qr | connected | reconnecting | failed | unreachable
            "state": status["session_status"],
            "awaiting_pairing": status["qr_available"],
        }

    # Bucketed, not data-versioned: the session can drop without a byte of
    # pipeline data changing, so this must age out on the clock. 15s is well
    # inside the time it takes a person to scan a QR and look back at the page,
    # and it caps the bridge at four health checks a minute however many tabs
    # are open.
    return cache.serve(request, "/delivery/status", build, max_age=30, bucket_s=15)


@app.get("/message/log", dependencies=[Depends(require_admin)])
def message_log(limit: int = Query(50, ge=1, le=500)):
    df = recent_log(limit)
    return {"n": int(len(df)), "rows": df.to_dict("records")}


class BroadcastIn(BaseModel):
    date: str | None = None
    dry_run: bool = True
    market: str = "Lasalgaon"


@app.post("/broadcast", dependencies=[Depends(require_admin)])
def broadcast_ep(body: BroadcastIn):
    """Send today's signal to every active subscriber.

    `dry_run` defaults to True: this is the one endpoint that can message a
    room full of real people, so firing it for real has to be deliberate.
    """
    try:
        alert_obj = build_alert(body.date or _latest_date(), persist=PERSIST_ALERTS)
    except NOT_PROVISIONED as e:
        raise _provisioned(e)

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
        result = send_alert(row["phone"], text)
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


@app.post("/admin/cache/clear", dependencies=[Depends(require_admin)])
def cache_clear():
    """Drop the response memo. The pipeline bumps the data version by itself,
    so this is only for when you have edited the database by hand."""
    before = cache.stats()
    cache.clear()
    from .features import _CACHE as feature_cache

    feature_cache.clear()
    return {"cleared": before, "now": cache.stats()}


# --- series ------------------------------------------------------------------


def _window(feats, start: str | None, end: str | None, days: int):
    end_ts = pd.Timestamp(end) if end else feats.index.max()
    start_ts = pd.Timestamp(start) if start else end_ts - pd.Timedelta(days=days)
    return start_ts, end_ts, feats.loc[start_ts:end_ts]


def _ndvi_payload(start: str | None, end: str | None, days: int) -> dict:
    from .features import build_features

    try:
        feats = build_features(with_target=False)
    except NOT_PROVISIONED as e:
        raise _provisioned(e)

    start_ts, end_ts, window = _window(feats, start, end, days)
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


@app.get("/ndvi")
def ndvi_series(
    request: Request,
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
    return cache.serve(request, "/ndvi", lambda: _ndvi_payload(start, end, days),
                       {"start": start, "end": end, "days": days})


@app.get("/ndvi/asof")
def ndvi_asof(request: Request, date: str = Query(..., description="YYYY-MM-DD")):
    """The satellite's read of the crop on one date — stage, greening rate,
    days since peak, % of the belt past maturity, and how old the read is."""

    def build():
        from .features import feature_row_asof

        try:
            row = feature_row_asof(date)
        except NOT_PROVISIONED as e:
            raise _provisioned(e)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"district": DISTRICT,
                "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                **describe_ndvi(row)}

    return cache.serve(request, "/ndvi/asof", build, {"date": date})


def _weather_payload(start: str | None, end: str | None, days: int) -> dict:
    from .features import build_features

    try:
        feats = build_features(with_target=False)
    except NOT_PROVISIONED as e:
        raise _provisioned(e)

    start_ts, end_ts, window = _window(feats, start, end, days)
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


@app.get("/weather")
def weather_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    days: int = Query(365, ge=30, le=4000,
                      description="trailing window when start/end are omitted"),
):
    """The weather overlay: daily rain and humidity, plus the two derived
    judgements the model and the alert actually use — can the crop be lifted
    and cured (harvest window), and can it be held (rot risk)."""
    return cache.serve(request, "/weather",
                       lambda: _weather_payload(start, end, days),
                       {"start": start, "end": end, "days": days})


@app.get("/weather/asof")
def weather_asof(request: Request, date: str = Query(..., description="YYYY-MM-DD")):
    """The weather overlay on one date — harvest window, rot risk, and the
    fortnight of dry days / wet spell / humidity behind them."""

    def build():
        from .features import feature_row_asof

        try:
            row = feature_row_asof(date)
        except NOT_PROVISIONED as e:
            raise _provisioned(e)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"district": DISTRICT,
                "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                **describe_weather(row)}

    return cache.serve(request, "/weather/asof", build, {"date": date})


def _prices_payload(start: str | None, end: str | None, days: int) -> dict:
    from .prices import district_daily, summary

    try:
        d = district_daily()
    except NOT_PROVISIONED as e:
        raise _provisioned(e)

    start_ts, end_ts, window = _window(d, start, end, days)
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


@app.get("/prices")
def prices_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    days: int = Query(365, ge=30, le=4000),
):
    """The cleaned district mandi series, plus what the cleaning had to do.

    Nominal and deflated prices are both returned: nominal is what a farmer is
    quoted, deflated is what the model compares across years.
    """
    return cache.serve(request, "/prices",
                       lambda: _prices_payload(start, end, days),
                       {"start": start, "end": end, "days": days})


# --- the one-request page load ----------------------------------------------


@app.get("/snapshot")
def snapshot(
    request: Request,
    days: int = Query(400, ge=30, le=4000),
    include_prices: bool = False,
):
    """Everything a page needs, in one round trip.

    The dashboard used to open with three or four separate calls, each of which
    woke the same feature matrix and paid its own connection setup — on a cold
    free instance that is four cold starts, not one. Bundling them means the
    page has a single thing to wait for, a single ETag to revalidate, and a
    single object to keep in the browser between visits.

    A partial failure does not sink the response: any section that could not be
    built comes back as null with the reason beside it, because a missing NDVI
    read is not a reason to hide the price.
    """

    def build():
        out: dict = {"district": DISTRICT, "crop": CROP,
                     "data_version": data_version(), "errors": {}}
        try:
            latest = _latest_date()
            out["latest_date"] = latest.strftime("%Y-%m-%d")
        except NOT_PROVISIONED as e:
            raise _provisioned(e)

        sections = {
            "alert": lambda: _alert_payload(latest),
            "ndvi": lambda: _ndvi_payload(None, None, days),
            "weather": lambda: _weather_payload(None, None, days),
        }
        if include_prices:
            sections["prices"] = lambda: _prices_payload(None, None, days)

        for name, fn in sections.items():
            try:
                out[name] = fn()
            except HTTPException as e:
                out[name] = None
                out["errors"][name] = e.detail
            except Exception as e:
                out[name] = None
                out["errors"][name] = str(e)

        try:
            m = load_model()
            out["model"] = {"kind": m.kind, "horizon_days": m.horizon_days,
                            "drop_threshold_pct": m.drop_threshold_pct}
        except Exception as e:
            out["model"] = None
            out["errors"]["model"] = str(e)
        return out

    return cache.serve(request, "/snapshot", build,
                       {"days": days, "include_prices": include_prices})


@app.get("/model/info")
def model_info(request: Request):
    def build():
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

    return cache.serve(request, "/model/info", build)
