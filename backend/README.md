# Bhav backend

NDVI (Sentinel-2 via Google Earth Engine) + weather (Open-Meteo) + mandi price
(Agmarknet) → one **Sell now / Caution / Wait** signal for onion in Nashik, with
a time-travel backtest that shares the exact scoring path with the live alert.

```
bhav/
  config.py        crop/district, thresholds, AOI  ← widen scope here
  db.py            sqlite schema + helpers
  ingest/
    ndvi.py        Sentinel-2 NDVI over the Lasalgaon belt (GEE)
    weather.py     Open-Meteo daily archive
    mandi.py       Agmarknet SearchCmmMkt scraper, month-chunked
    load.py        raw CSV → sqlite
  features.py      join on (district, date): NDVI trend, weather anomaly,
                   price/arrivals momentum, seasonal terms, + target
  model.py         LightGBM classifier (logreg fallback), TimeSeriesSplit CV
  scoring.py       score_asof(date)  ← the ONE function live + backtest share
  alert_engine.py  score → colour + ₹ impact + 3–5 day window + reason
  backtest.py      backtest_date(date), track_record()  (hits AND misses)
  warehouses.py    nearest WDRA godown + partial-sell heuristic
  message.py       WhatsApp/SMS body (en/mr) + optional Twilio send
  api.py           FastAPI
scripts/
  fetch_all.py     pull every source → sqlite
  build.py         features → train → models/model.pkl
```

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill EE_PROJECT (+ Twilio if doing a real send)
earthengine authenticate       # one time, for NDVI
```

## Run the pipeline

```bash
# 1. pull ~9 seasons of data into data/bhav.db
python -m scripts.fetch_all
#    GEE not ready yet? skip NDVI and add it later:
#    python -m scripts.fetch_all --skip-ndvi

# 2. build features + train
python -m scripts.build

# 3. serve
uvicorn bhav.api:app --reload --port 8000
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET  | `/alert/today` | live signal for the latest data date |
| GET  | `/alert?date=YYYY-MM-DD` | signal as of any date |
| GET  | `/backtest?date=YYYY-MM-DD` | signal on that date **+ what actually happened** vs selling blind |
| GET  | `/track-record?step_days=7` | weekly walk of history, hit/miss tally by colour |
| GET  | `/warehouse/nearest` | nearest WDRA godowns |
| POST | `/partial-sell` | `{cash_need_rupees, total_quintals}` → sell/store split |
| POST | `/message/preview` | localized WhatsApp text (`lang: en\|mr`) |
| POST | `/message/send` | real Twilio send if configured, else preview |
| GET  | `/model/info` | model kind, features, CV metrics |

## Design notes

- **One scoring path.** `scoring.score_asof(date)` slices the feature matrix at
  `date` with no lookahead; `/alert` and `/backtest` both call it. A judge can
  pick any date and it's the same code.
- **Window, not a day.** The alert engine spreads the point prediction into a
  3–5 day window — the anti-herd design.
- **Honest track record.** `track_record()` reports misses alongside hits, per
  colour.
- **Degrades gracefully.** No LightGBM wheel → logistic-regression fallback.
  GEE not provisioned → `--skip-ndvi`, model trains on price+weather only.
