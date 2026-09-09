# How the three data sources work

Bhav answers one question — *should a Nashik onion farmer sell this week or
wait?* — by joining three independent views of the same belt on a daily grid:

| Source | What it sees | Why it matters |
|---|---|---|
| **Satellite** (Sentinel-2 NDVI) | how green the crop is, and how fast it is drying down | tells you *supply is coming* two to six weeks before it arrives |
| **Weather** (Open-Meteo archive) | rain, humidity, heat, drying power | decides whether the crop *can be lifted*, and whether it *can be held* |
| **Mandi** (Agmarknet APMC prints) | modal price + arrivals per market per day | the price itself, and the glut as it lands |

The governing idea is a supply-shock chain:

```
crop matures in the field        →  satellite sees NDVI fall
weather opens a dry window       →  everyone lifts at once
arrivals surge at the APMC yard  →  modal price collapses
```

The satellite gives lead time, the weather gives the trigger, and the mandi
gives confirmation. Any one alone is a lagging indicator. Together they are
early.

---

## Part 1 — Satellite: greenery and how it reads "near harvest"

### Where the numbers come from

`bhav/ingest/ndvi.py` — **Sentinel-2 L2A surface reflectance via Google Earth
Engine** (`COPERNICUS/S2_SR_HARMONIZED`), over a rectangular AOI around the
Lasalgaon onion belt (`NDVI_AOI` in `config.py`, roughly 74.00–74.55 °E,
19.95–20.40 °N).

NDVI is the standard vegetation index:

```
NDVI = (NIR − Red) / (NIR + Red) = (B8 − B4) / (B8 + B4)
```

computed in Earth Engine with `img.normalizedDifference(["B8", "B4"])`. Healthy
canopy reflects near-infrared strongly and absorbs red, so it scores high
(~0.6–0.8). Bare soil — which is exactly what a harvested onion field is —
scores low (~0.1–0.2).

**Cloud masking.** Every pixel carries a Sentinel-2 scene-classification (SCL)
code. Only three are kept:

```python
_CLEAR_SCL = [4, 5, 7]   # 4 vegetation, 5 not-vegetated (bare soil), 7 unclassified
```

Code 5 is deliberate: a harvested field must stay in the sample, or the belt
mean would rise every time a farmer lifts a crop. Everything else — cloud,
shadow, water, snow, saturation — is masked out.

**Three numbers per scene**, reduced over the AOI at 100 m scale:

| Field | Computation | Meaning |
|---|---|---|
| `ndvi` | mean NDVI over clear pixels | how green the belt is |
| `pct_mature` | share of clear pixels with `NDVI < 0.35` | **how much of the belt is past maturity** |
| `clear_frac` | mean of the clear mask | how much of the AOI was actually visible |

`NDVI_MATURITY_THRESHOLD = 0.35` is the cut that turns a continuous index into
the headline the UI shows as *"Fields past ripening — 42%"*.

### Compositing: why 10 days, and why in pandas

Sentinel-2 revisits every ~5 days, but a single pass over Nashik is routinely
cloud-wrecked, and the monsoon can hide the belt for weeks. So scenes are
collapsed into **10-day composites** (`NDVI_COMPOSITE_DAYS`).

Two decisions here are load-bearing:

1. **Weighted by clear coverage.** The AOI straddles two Sentinel-2 tiles, so
   one date usually yields two partial scenes. Averaging them weighted by
   `clear_frac` (`_wmean`) stops a mostly-clouded sliver from dragging the belt
   mean around.
2. **Compositing happens in pandas, not in Earth Engine.** An empty 10-day
   window has to *stay empty* — carried as observation age — rather than
   silently becoming a zero-band image. A composite that saw less than
   `NDVI_MIN_CLEAR_FRAC = 0.20` of the AOI is dropped outright, because a
   composite that saw almost nothing is worse than no composite at all.

Each composite also records `obs_date` — the **last real satellite pass** inside
the window.

### Phenology: turning a curve into "harvest is near"

`bhav/phenology.py` is where greenery becomes a harvest signal. It uses a
**Savitzky-Golay filter** (`scipy.signal.savgol_coeffs`) — a rolling
least-squares polynomial fit that smooths noise while preserving the shape of
peaks and slopes, which a moving average flattens.

**The critical modification:** a textbook Savitzky-Golay filter is *centred* —
the smoothed value at day *t* is fitted through days on both sides of *t*, so it
knows the future. Used as-is, that leaks straight into the backtest and makes
every historical call look prescient. So the coefficients are evaluated at the
**trailing edge** of the window:

```python
coeffs = savgol_coeffs(window, poly, deriv=deriv, delta=1.0,
                       pos=window - 1, use="dot")   # pos = last sample
return s.rolling(window).apply(lambda a: float(coeffs @ a), raw=True)
```

`pos = window - 1` asks scipy for the coefficients that estimate the fitted
polynomial — *or its derivative* — at the **last** sample. Same noise rejection,
zero lookahead.

Four phenology features come out of it:

| Feature | How | Reads as |
|---|---|---|
| `ndvi_smooth` | causal SG, 31-day window, quadratic | de-noised greenness |
| `ndvi_greening_rate` | **first derivative** of that same fit (`deriv=1`) | NDVI units/day. Positive = still greening up. Negative = **drying down toward harvest** |
| `ndvi_days_since_peak` | rolling `argmax` of `ndvi_smooth` over 150 days (~one onion cycle) | how far past green-up the crop is — the closer the peak recedes, the nearer the arrivals surge |
| `ndvi_senescence_slope` | causal SG derivative over a *short* 21-day window, clipped to its negative half and reported positive | **drying speed** — how fast the crop is senescing |

Window choices: `SMOOTH_WINDOW = 31` days ≈ three composites, enough to ride out
one cloudy pass. `SENESCENCE_WINDOW = 21` because the drying-down leg is short
and needs to stay local. `SMOOTH_POLY = 2` — a quadratic follows the
green-up/senescence curve without over-fitting.

### The crop stage the UI shows

`phenology.stage_of()` collapses all of this into one word:

```python
if mature >= 0.65:        return "Harvest window"    # most of the belt past the cut
if rate  >  0.0015:       return "Greening"
if rate  < -0.0015:       return "Senescing"         # "Drying down — harvest is near"
                          return "At peak"
```

### Staleness is a feature, not a gap

The most-copied mistake in satellite pipelines is interpolating across cloud
gaps and pretending to a daily read. Bhav does not. In `features._ndvi_frame()`:

- each composite is **held forward** (`ffill`) until the next one lands;
- the gap is carried explicitly as **`ndvi_obs_age_days`**, which is a model
  feature in its own right — so a decision made on a three-week-old picture is
  *visibly weaker* to the model than one made on this morning's pass;
- past `NDVI_STALE_DAYS = 21` the UI marks the read stale (*"Clouds have hidden
  the fields recently"*).

**Point-in-time rule:** a composite is indexed by its `obs_date`, not by the
window start. Indexing by the start would hand days early in the window a value
derived from satellite passes up to nine days in their own future — exactly the
leak that makes a backtest look prescient.

---

## Part 2 — Weather: can it be lifted, can it be held

### Where the numbers come from

`bhav/ingest/weather.py` — the **Open-Meteo free archive API** (no key) at the
belt centroid (20.145 °N, 74.238 °E). Ten daily variables:

`temp_max`, `temp_min`, `temp_mean`, `rainfall`, `rain_hours`, `humidity_max`,
`humidity_min`, `humidity_mean`, `et0` (FAO reference evapotranspiration),
`wind_max`.

Humidity and ET0 are pulled for a specific reason: **onion is stored, not just
grown.** Warm and humid means the crop cannot be held — and a farmer who cannot
hold is a *forced seller*. Forced sellers are what turn a harvest into a glut.
That is the mechanism the overlay is trying to see.

Missing days: rain is a *total* so a gap is filled with `0.0` (interpolating
would invent a drizzle that breaks a wet-spell run); levels like temperature are
linearly interpolated.

### The overlay: from raw mm to two decisions

`bhav/weather_overlay.py`. Raw weather is not decision-grade — 12 mm of rain
means one thing in July and another in April. The overlay turns the archive into
the two questions a farmer actually faces.

**Thresholds** (all onion-specific):

```python
DRY_DAY_MM  = 1.0    # below this, a day is workable for lifting/curing
ROT_HUMIDITY = 70.0  # onion cures poorly and rots above this, when also warm
ROT_TEMP_C   = 20.0
HEAT_DAY_C   = 35.0  # Nashik onion hits heat stress past this; pulls maturity forward
WINDOW       = 14    # "can I harvest this fortnight"
```

**Six model features:**

| Feature | How |
|---|---|
| `dry_days_14` | count of days with `rain < 1.0 mm` in the trailing fortnight |
| `wet_spell` | **length of the run of consecutive wet days ending today** |
| `humidity_14` | 14-day mean relative humidity |
| `humidity_anom_14` | that, minus the seasonal normal |
| `heat_days_14` | count of days `tmax ≥ 35 °C` |
| `et0_anom_14` | 14-day mean drying power vs. the seasonal normal |

`wet_spell` deserves the note it carries in the source: three wet days in a row
stops harvest outright, while the same rainfall spread over a fortnight barely
registers. **Totals miss that; runs don't.** It is computed with the standard
reset trick — cumulative count minus the count at the last dry day:

```python
wet = (rain >= DRY_DAY_MM).astype(int)
group = (wet == 0).cumsum()
return wet.groupby(group).cumsum()
```

**Two composite scores** (0–1, for the UI and the alert reason — not model
features):

```python
harvest_score = (dry_days/14) * (1 − 0.7 * min(wet_spell/3, 1))
```
1 = a clear fortnight to lift and cure, 0 = washed out. An active wet run is
disqualifying regardless of the fortnight's total.

```python
rot_score = clip((humidity − 70)/20) * (0.55 + 0.45 * clip((temp − 20)/10))
```
1 = storage is a losing bet. Humidity is the driver and **warmth only
accelerates it** — weighting the two equally would understate the monsoon, which
in Nashik is both the wettest *and* the coolest part of the year. So temperature
*scales* the humidity term rather than gating it.

These become the UI's *"Good — dry enough to lift the crop"* / *"Low — stored
crop should keep"* bands, and `_note()` writes the one actionable line, ordered
by what actually matters (an active wet spell first, then rot, then curing
conditions).

---

## Part 3 — Mandi: the price and the glut

### Where the numbers come from

`bhav/ingest/mandi.py` — **Agmarknet** (the Government of India APMC price
portal). Two notes on endpoint choice:

- The report endpoint the site's own page calls (`/daily-price-arrival/report`)
  is **CAPTCHA-gated** and answers `TOKEN_OR_CAPTCHA_REQUIRED`. That is a
  deliberate anti-automation control and this module does not try to defeat it.
- `/prices-and-arrivals/date-wise/specific-commodity` is not gated and is far
  kinder besides: it returns a whole **month** for one commodity in one ~140 KB
  response, so a decade costs ~130 requests instead of ~3,900 day-by-day calls.
  Serial, with a 0.6 s pause between calls.

Per market per variety per trading day: `arrivals_tonnes`, `price_min`,
`price_modal`, `price_max`.

**Mandi-name drift** is handled by normalising to lowercase alphanumerics
(`_norm`) — the same yard appears as `APMC Lasalgaon`, `Lasalgaon(Niphad) ` and
`LASALGAON` depending on endpoint and year. The canonical market list comes from
Agmarknet's own filter endpoint rather than being hardcoded, so a new private
yard appears automatically instead of being silently dropped.

### Cleaning: four decisions, each a place a backtest can go wrong

`bhav/prices.py`.

**1. Aggregation — arrivals-weighted, not a plain mean.** Lasalgaon clearing
2,000 tonnes and a private yard clearing 3 tonnes are not two equal opinions
about the price of onion.

**2. Non-trading days.** Mandis close for Sundays, holidays and bandhs — 624 of
3,901 days in the window have no print at all. Gaps up to
`PRICE_MAX_GAP_DAYS = 5` are time-interpolated; anything longer holds the last
print, and the staleness is carried as **`days_since_trade`** — the same
treatment NDVI's observation age gets. *A closed mandi is not a flat market.*

**3. Outlier caps.** A single fat-fingered print can move a district mean hard.
Prices are clipped to a **trailing** robust band — rolling median ± `6.0 × 1.4826
× MAD` — and the window is `.shift(1)`ed. A centred window, or one including
today, would let the outlier defend itself by widening the very band meant to
catch it, and would leak future prices into a point-in-time feature.

**4. CPI deflation.** `bhav/ingest/cpi.py` pulls World Bank `FP.CPI.TOTL` for
India. Two series are then carried on purpose:

- `price` stays **nominal** — that is what a farmer is quoted, and what the
  ₹/quintal outcome must be measured in;
- `price_real` is **CPI-deflated**, and is what the *model* reads. A decade of
  inflation would otherwise read as a decade of slow bull market, and every
  "price is high for the season" comparison against a rolling year would drift.

**Eleven price/arrivals features** come out: `price_real`, `price_mom_7/14/30`,
`price_vs_year` (vs. rolling 365-day median), `price_pctile_year`,
`days_since_trade`, `arr_7`, `arr_mom_14`, `arr_vs_year`.

---

## Part 4 — How the three are joined

`bhav/features.py` — one function, `build_features()`, joins everything on
`(district, date)` and produces **33 features**. Training uses the whole matrix;
scoring asks for a single as-of row. **Same code path either way**, which is what
makes the backtest honest.

```
mandi_price ─┬─ prices.district_daily()      ─┐
cpi ─────────┘                                │
                                              ├─→ build_features() → 33 cols
weather ─────┬─ (rolling anomalies)           │
             └─ weather_overlay.add_overlay() ─┤
                                              │
ndvi ────────┬─ _ndvi_frame()  (ffill + age)  │
             └─ phenology.add_phenology()     ─┘
```

### The seasonal normal — prior years only

Every anomaly feature needs a normal to compare against. The obvious way —
average each day-of-year across the whole series — quietly tells 2019 what 2024
did. So `_seasonal_norm()` buckets the year into 15-day windows and takes the
**expanding mean shifted by one**:

```python
return s.groupby(bucket).transform(lambda x: x.expanding().mean().shift(1))
```

Only strictly-prior seasons. Early rows come back `NaN` and the warm-up drop
handles them. The same function is passed into the weather overlay, so the
anomalies there use exactly the same prior-years-only normal as the rest of the
matrix.

### The target

```python
fwd_min = price_real.shift(-1).rolling(10).min().shift(-9)
target  = (fwd_min / price_real − 1.0) <= −0.16
```

*Will the real price fall more than 16% within 10 days?*
`DROP_THRESHOLD_PCT` was relocked at 16% after seeing the real Agmarknet series
— the roadmap's original 8% fires on 55.6% of days on real Nashik onion, at
which point "crash" means nothing.

### Model → alert

| Module | Job |
|---|---|
| `model.py` | **LightGBM** `LGBMClassifier`, deliberately small (`num_leaves=8`, `max_depth=4`, `min_child_samples=60`, `reg_lambda=5.0`) — ~3,800 rows at an 8% base rate can't feed 31 leaves. Falls back to a scaled logistic regression if LightGBM is unavailable. Validated with `TimeSeriesSplit`, never a random split. |
| `scoring.py` | `score_asof(date)` — **the one function the live alert and the backtest share.** Ranks drivers by SHAP (`pred_contrib`) and phrases each one in plain language, choosing the wording by whether the value sits above or below its *to-date* median. |
| `calibration.py` | Isotonic layer on the raw score. The raw 0.7–1.0 bin predicted 0.83 and observed 0.29 — showing a farmer "87% confidence" on a call that is wrong most of the time is worse than showing nothing. Fitted on the **validation year only**, and clamped to [0.02, 0.98] because isotonic saturates to a hard 1.0 that 366 days cannot justify. |
| `alert_engine.py` | Probability → colour (`≥0.60` RED, `≥0.35` AMBER, else GREEN) + ₹/quintal impact + a **3–5 day window** rather than a single date (deliberately anti-herd) + a one-line reason from the dominant driver. |
| `backtest.py` | Re-runs the alert as if today were any past date, then grades it against what the price actually did — with a colour-appropriate baseline, and hits *and* misses reported. |

Current model card (`GET /model/info`): LightGBM, 33 features, 3,824 training
rows, 8.3% base rate, CV ROC-AUC 0.783, CV average precision 0.224.

---

## Part 5 — The leakage discipline

Every rolling window in this codebase looks **strictly backwards**. That is not
incidental — it is the single property that makes the backtest page worth
showing. The recurring pattern:

| Where | Naive version | What Bhav does |
|---|---|---|
| `phenology.py` | centred Savitzky-Golay | `pos=window-1` — trailing edge |
| `features._seasonal_norm` | full-series day-of-year mean | `expanding().mean().shift(1)` |
| `prices._cap_outliers` | centred robust band | trailing, `.shift(1)` |
| `features._ndvi_frame` | composite indexed by window start | indexed by `obs_date` |
| `scoring.score_asof` | medians over all history | `feature_context_asof` — medians to date only |
| cloud/holiday gaps | interpolate them away | hold forward + carry `ndvi_obs_age_days` / `days_since_trade` as features |

And it is *tested*, not just asserted. `scripts/check_leakage.py` builds the
feature matrix twice — once from full history, once with every raw table
truncated at date D — and fails if any feature's value at D moves:

> If a feature's value at D moves, it was reading data that did not exist yet on
> D, and any backtest using it is telling a flattering lie.

---

## Every Python module, at a glance

### Ingest — `bhav/ingest/`

| Module | Source | Produces |
|---|---|---|
| `ndvi.py` | Sentinel-2 L2A via Google Earth Engine | `data/raw/ndvi_nashik.csv` — 10-day composites with `value`, `pct_mature`, `clear_frac`, `obs_date` |
| `weather.py` | Open-Meteo archive API | `data/raw/weather_nashik.csv` — 10 daily variables |
| `mandi.py` | Agmarknet 2.0 JSON API | `data/raw/mandi_onion_nashik.csv` — per market/variety/day |
| `cpi.py` | World Bank `FP.CPI.TOTL` | `data/raw/cpi_india.csv` — annual India CPI |
| `load.py` | — | raw CSVs → sqlite (`data/bhav.db`) |

### Core — `bhav/`

| Module | Job |
|---|---|
| `config.py` | crop, district, AOI, every threshold. Widening scope is a config change |
| `db.py` | sqlite schema + helpers — one file, zero setup |
| `phenology.py` | **causal Savitzky-Golay** → greening rate, days-since-peak, senescence slope, % past maturity, crop stage |
| `weather_overlay.py` | harvest window + rot risk from dry days, wet-spell runs, humidity × warmth, ET0 |
| `prices.py` | arrivals-weighted district series: holidays, outlier caps, CPI deflation, log |
| `features.py` | the join — 33 features + the target. Cached on the db's mtime |
| `model.py` | LightGBM classifier (logreg fallback), `TimeSeriesSplit` CV |
| `calibration.py` | isotonic layer over the raw score |
| `scoring.py` | `score_asof(date)` — shared by live and backtest |
| `alert_engine.py` | score → colour + ₹ impact + sell window + reason |
| `backtest.py` | `backtest_date()`, `track_record()` — hits *and* misses |
| `warehouses.py` | nearest WDRA godown + partial-sell heuristic |
| `message.py` | WhatsApp body in English / Hindi / Marathi |
| `whatsapp.py` | send / status / QR over the open-wa Node bridge |
| `subscribers.py` | registrations + delivery log |
| `api.py` | FastAPI — `/alert/today`, `/backtest`, `/ndvi`, `/weather`, `/track-record`, … |

### Scripts — `scripts/`

| Script | Job |
|---|---|
| `fetch_all.py` | pull every source → sqlite (`--skip-ndvi` if GEE auth isn't ready) |
| `build.py` | features → train → `models/model.pkl` |
| `seed_demo.py` | synthetic ~9-season history, offline safety net |
| `check_leakage.py` | point-in-time audit — proves no feature reads the future |
| `evaluate.py` | LightGBM vs seasonal-naive vs price-momentum, train ≤2023 / val 2024 / test 2025 |
| `prune_eval.py` | bounded capacity pass: pruned / regularised / stacked variants |
| `threshold_sweep.py` | walk-forward alert-threshold sweep (embargoed) |
| `calibrate.py` | fit the isotonic calibrator on the validation year, audit after it |
| `broadcast.py` | today's signal → every subscriber |

### Third-party packages

| Package | Used for |
|---|---|
| `earthengine-api` | Sentinel-2 access, cloud masking, `reduceRegion` over the AOI |
| `pandas` / `numpy` | every series, join, rolling window and composite |
| `scipy` | `signal.savgol_coeffs` — the causal Savitzky-Golay filter. **Not declared in `requirements.txt`**; it currently arrives transitively via scikit-learn, so `phenology.py` would break on a resolver that stopped pulling it in |
| `scikit-learn` | `TimeSeriesSplit`, `IsotonicRegression`, metrics, logreg fallback |
| `lightgbm` | the classifier and its SHAP `pred_contrib` explanations |
| `requests` | Open-Meteo, Agmarknet, World Bank, the WhatsApp bridge |
| `fastapi` / `uvicorn` | the API the web app reads |

---

## Running it

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
earthengine authenticate          # one time, for NDVI

python -m scripts.fetch_all       # all sources → sqlite  (or --skip-ndvi)
python -m scripts.build           # features → train → models/model.pkl
python -m scripts.calibrate       # fit the isotonic layer
python -m scripts.check_leakage   # prove no feature reads the future
uvicorn bhav.api:app --reload     # :8000
```

Earth Engine is called **before** the demo, never live — everything downstream
reads the CSV and the sqlite `ndvi` table.
