"""Central config for the Bhav backend.

Hackathon scope: one crop, one district — onion, Nashik (Maharashtra).
Everything downstream (ingest, features, model, alert engine) reads from here
so widening scope later is a config change, not a rewrite.

Paths are environment-overridable so the same code runs from a checkout and
from a container whose writable storage is a mounted disk. See DEPLOY.md.
"""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Load .env *first*: everything below reads the environment, and on a bare
# checkout the file is the only place the deployment settings exist. Without
# this the API silently ran with no WhatsApp bridge token and no Earth Engine
# project. On a real host the platform's own env wins — load_dotenv does not
# overwrite variables that are already set.
try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env")
except ImportError:  # python-dotenv is in requirements; don't hard-fail without it
    pass


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# --- Paths ------------------------------------------------------------------
#
# Two roots, because a container's image and its writable storage are not the
# same place:
#
#   SEED_*  ships inside the deploy — the pipeline output committed to the repo.
#           Read-only in a container, and gone on the next deploy.
#   DATA_DIR / MODELS_DIR  is where the process actually reads and writes. Point
#           them at a mounted disk (BHAV_DATA_DIR=/var/data) and subscriptions
#           survive a redeploy; leave them unset and everything stays in-tree,
#           which is exactly the old behaviour.
#
# `bootstrap.py` copies SEED -> DATA_DIR on first boot when the two differ, so a
# fresh disk starts with the shipped history rather than 503ing.
SEED_DATA_DIR = BACKEND_DIR / "data"
SEED_MODELS_DIR = BACKEND_DIR / "models"

DATA_DIR = _env_path("BHAV_DATA_DIR", SEED_DATA_DIR)
MODELS_DIR = _env_path("BHAV_MODELS_DIR", SEED_MODELS_DIR)
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "bhav.db"
MODEL_PATH = MODELS_DIR / "model.pkl"
# Isotonic layer over the model's raw score (see calibration.py). Separate file
# so recalibrating never means retraining.
CALIBRATOR_PATH = MODELS_DIR / "calibrator.pkl"

for _d in (DATA_DIR, RAW_DIR, MODELS_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        # A read-only image layer. Only fatal if this is also where the process
        # was told to write, and bootstrap.py reports that far more usefully.
        pass

# --- Target crop / district -------------------------------------------------

CROP = "onion"
DISTRICT = "Nashik"
STATE = "Maharashtra"

# Agmarknet form codes (SearchCmmMkt.aspx).
AGMARKNET = {
    "commodity_code": 23,       # Onion
    "commodity_head": "Onion",
    "state_code": "MH",
    "state_head": "Maharashtra",
    "district_head": "Nashik",
    # Nashik APMC markets we care about; blank district code pulls the whole
    # state, we filter to these after download.
    "markets": ["Lasalgaon", "Pimpalgaon Baswant", "Nashik", "Yeola", "Devla"],
}

# Centroid of the Nashik onion belt (Lasalgaon area) for satellite + weather.
LAT = 20.145
LON = 74.238

# Rectangular AOI around the belt for NDVI sampling (deg).
NDVI_AOI = {"min_lon": 74.00, "min_lat": 19.95, "max_lon": 74.55, "max_lat": 20.40}

# --- Satellite NDVI (Sentinel-2 via Earth Engine) --------------------------- #

# Sentinel-2 L2A (surface reflectance) coverage over India starts here. Earlier
# dates simply have no NDVI; features fall back to the seasonal climatology.
NDVI_START = "2017-04-01"
# Roadmap: 10-day composites. A single pass is often cloud-wrecked; compositing
# to 10 days is what makes the series usable, and the gap between composites is
# carried explicitly as ndvi_obs_age_days rather than silently interpolated.
NDVI_COMPOSITE_DAYS = 10
NDVI_MAX_CLOUD_PCT = 60      # per-scene CLOUDY_PIXEL_PERCENTAGE cut
NDVI_SCALE_M = 100           # reduceRegion scale — 100 m is plenty for a belt mean
# Below this NDVI a clear pixel is read as "past maturity" — crop drying down
# and close to harvest. Drives the "% area past maturity" feature.
NDVI_MATURITY_THRESHOLD = 0.35
# A composite built from less than this much clear sky is dropped as unreliable.
NDVI_MIN_CLEAR_FRAC = 0.20
# Beyond this, a stale composite is treated as "no current read" by the UI.
NDVI_STALE_DAYS = 21

# --- History window -------------------------------------------------------- #

HISTORY_START = "2016-01-01"   # ~9 seasons back
# HISTORY_END defaults to "today" at fetch time.

# --- Mandi price cleaning (see prices.py) ---------------------------------- #

# Mandis close for Sundays, holidays and bandhs. A gap up to this long is
# interpolated; anything longer holds the last print and shows up in
# days_since_trade instead of being smoothed away.
PRICE_MAX_GAP_DAYS = 5
# Trailing window and robust width for capping bad prints.
PRICE_OUTLIER_WINDOW = 21
PRICE_OUTLIER_MAD = 6.0

# --- Modelling ------------------------------------------------------------- #

# Predict: will the modal price fall by more than DROP_THRESHOLD_PCT within
# HORIZON_DAYS, relative to today's price?
HORIZON_DAYS = 10
# Relocked at 16% after seeing the real Agmarknet series. The roadmap's
# hour-one 8% was fixed before anyone had the data: on real Nashik onion it
# fires on 55.6% of days, so "crash" meant nothing. At 16% the event is
# genuinely unusual (~23% of days) while still being frequent enough to learn.
DROP_THRESHOLD_PCT = 0.16

# Alert-engine thresholds on predicted drop probability.
SELL_PROB = 0.60     # >= this  -> RED  (sell now)
CAUTION_PROB = 0.35  # >= this  -> AMBER (caution)
# below CAUTION_PROB          -> GREEN (wait)

# Sell window length (days) the point prediction is spread into.
WINDOW_DAYS = 5

# --- Serving --------------------------------------------------------------- #

# Who may call the API from a browser. A hosted frontend is on a different
# origin to the API, so this has to be set there — "*" is the local default and
# is refused for credentialed requests by every browser anyway.
CORS_ORIGINS = [
    o.strip() for o in os.getenv("BHAV_CORS_ORIGINS", "*").split(",") if o.strip()
]

# Shared secret for the endpoints that can message real people or read the
# subscriber log. Unset = those endpoints are open, which is fine on localhost
# and is exactly what you must not do on a public host; api.py says so at boot.
ADMIN_TOKEN = os.getenv("BHAV_ADMIN_TOKEN", "")

# How long a browser or CDN may reuse a signal/series response before
# revalidating. Responses also carry an ETag keyed on the data generation, so a
# revalidation after this expires is a 304 with no body unless the pipeline has
# actually run. Zero disables client caching without touching the server cache.
CACHE_MAX_AGE = int(os.getenv("BHAV_CACHE_MAX_AGE", "300"))
CACHE_SWR = int(os.getenv("BHAV_CACHE_SWR", "86400"))

# Writing an alert row on every read mutates the database, which used to
# invalidate the feature cache on literally every request (see features.py).
# The row is a nice-to-have audit trail; the rebuild is not. Off by default on
# a host, on for scripted/offline use via BHAV_PERSIST_ALERTS=1.
PERSIST_ALERTS = env_flag("BHAV_PERSIST_ALERTS", False)

# Skip the startup warm-up (feature matrix + model into memory). Only useful if
# you are debugging boot order.
WARM_ON_BOOT = env_flag("BHAV_WARM_ON_BOOT", True)
