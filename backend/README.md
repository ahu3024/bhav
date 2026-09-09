# Bhav backend

NDVI (Sentinel-2 via Google Earth Engine) + weather (Open-Meteo) + mandi price
(Agmarknet) → one **Sell now / Caution / Wait** signal for onion in Nashik, with
a time-travel backtest that shares the exact scoring path with the live alert.

```
bhav/
  config.py        crop/district, thresholds, AOI  ← widen scope here
  db.py            sqlite schema + helpers
  ingest/
    ndvi.py        Sentinel-2 → 10-day NDVI composites over the Lasalgaon belt
    weather.py     Open-Meteo daily archive
    mandi.py       Agmarknet 2.0 JSON API, month-chunked + canonical mandi names
    cpi.py         World Bank India CPI, for deflation
    load.py        raw CSV → sqlite
  prices.py        arrivals-weighted district series: holidays, outlier caps,
                   CPI deflation, log
  calibration.py   isotonic layer over the raw score (models/calibrator.pkl)
  phenology.py     causal Savitzky-Golay: greening rate, days-since-peak,
                   senescence slope, % area past maturity
  weather_overlay.py  harvest window (dry days, wet spell, ET0) + storage rot
                   risk (humidity x warmth)
  features.py      join on (district, date): NDVI trend + phenology, weather
                   anomaly, price/arrivals momentum, seasonal terms, + target
  model.py         LightGBM classifier (logreg fallback), TimeSeriesSplit CV
  scoring.py       score_asof(date)  ← the ONE function live + backtest share
  alert_engine.py  score → colour + ₹ impact + 3–5 day window + reason
  backtest.py      backtest_date(date), track_record()  (hits AND misses)
  warehouses.py    nearest WDRA godown + partial-sell heuristic
  message.py       WhatsApp body (en/hi/mr) — text and phone normalisation only
  whatsapp.py      send/status/QR over the open-wa bridge (whatsapp/, Node)
  subscribers.py   registrations + delivery log (sqlite)
  cache.py         ETags + a bounded response memo, keyed on the data version
  bootstrap.py     seed a fresh host's disk from the shipped data/seed.db
  api.py           FastAPI
scripts/
  fetch_all.py     pull every source → sqlite
  make_seed.py     data/bhav.db → data/seed.db, the snapshot the deploy ships
                   (refuses to include subscribers or the message log)
  seed_demo.py     synthetic ~9-season history, offline safety net
  build.py         features → train → models/model.pkl
  check_leakage.py point-in-time audit — proves no feature reads the future
  evaluate.py      LightGBM vs seasonal-naive vs price-momentum on the
                   roadmap's train<=2023 / val 2024 / test 2025 split
  prune_eval.py    one bounded capacity pass: pruned / regularised / stacked
                   variants on that same split
  threshold_sweep.py  walk-forward alert-threshold sweep (embargoed) over the
                   2023 crash window and the 2025 test year
  calibrate.py     fit the isotonic calibrator on the validation year, then
                   audit it on data strictly after that year
  broadcast.py     compute today's signal -> send to every subscriber
```

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-ingest.txt   # requirements.txt alone = serve only
cp .env.example .env            # fill EE_PROJECT (+ WA_BRIDGE_TOKEN for real sends)
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

Every GET below carries an `ETag` keyed on the data version and a
`Cache-Control` with `stale-while-revalidate`, so a client that already has the
answer gets a 304 with no body until an ingest has actually run. See
`bhav/cache.py`.

| Method | Path | Purpose |
|---|---|---|
| GET  | `/snapshot?days=400` | **the whole page in one request** — alert + NDVI + weather (+ prices with `include_prices=1`). One thing to wait for, one ETag to revalidate |
| GET  | `/alert/today` | live signal for the latest data date |
| GET  | `/alert?date=YYYY-MM-DD` | signal as of any date |
| GET  | `/backtest?date=YYYY-MM-DD` | signal on that date **+ what actually happened** vs selling blind |
| GET  | `/track-record?step_days=7` | weekly walk of history, hit/miss tally by colour |
| GET  | `/warehouse/nearest` | nearest WDRA godowns |
| POST | `/partial-sell` | `{cash_need_rupees, total_quintals}` → sell/store split |
| POST | `/subscribe` | register a phone (rate-limited per IP; see WhatsApp delivery below) |
| GET  | `/message/preview/all` | the alert in all three languages — what the registration form shows |
| POST | `/message/preview` | localized WhatsApp text (`lang: en\|hi\|mr`) |
| GET  | `/delivery/status` | can an alert be delivered right now — the public, redacted half |
| GET  | `/ndvi?days=400` | NDVI series — the real 10-day composites **and** the smoothed daily curve the model reads |
| GET  | `/ndvi/asof?date=` | the satellite's read on one date: stage, greening rate, days since peak, % past maturity, how stale |
| GET  | `/weather?days=400` | daily rain + humidity, with the harvest-window and rot-risk scores |
| GET  | `/weather/asof?date=` | the overlay on one date: harvest window, storage risk, dry days, wet spell, humidity + a one-line read |
| GET  | `/prices?days=365` | cleaned district price series (nominal + deflated, arrivals, markets reporting) with a data-quality read-out |
| GET  | `/model/info` | model kind, features, CV metrics |
| GET  | `/health` | liveness. No database, no model — a slow query cannot fail a healthy deploy |
| GET  | `/readyz` | readiness, with the reason when the answer is no |
| GET  | `/meta` | data version, latest date — cheap enough to poll |

**Admin** — everything that can message a real person or say who they are.
Guarded by `BHAV_ADMIN_TOKEN` (`Authorization: Bearer …`, or `?token=` for the
QR, which is opened in a browser). Unset leaves them open, which is right on
localhost and wrong anywhere else; the API warns at boot and `/readyz` reports
`admin_token_set`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/broadcast` | send to all subscribers — `dry_run` defaults to true |
| POST | `/message/send` | one message to one number |
| GET  | `/message/qr` | the open-wa pairing QR. **Scanning it links a WhatsApp account to this deployment** |
| GET  | `/message/status` | full bridge state, including the linked number |
| GET  | `/message/check` | is a number on WhatsApp? Sends nothing |
| GET  | `/message/log` | recent send attempts |
| GET  | `/subscribers` | counts only — the phone list is not something this API hands out |
| POST | `/admin/cache/clear` | drop the response memo |

## Deploying

See [../DEPLOY.md](../DEPLOY.md). The short version:

```bash
python -m scripts.make_seed     # data/bhav.db -> data/seed.db, the shipped copy
```

`data/seed.db` is committed and goes into the image, so a fresh container serves
a real signal on its first request. `data/bhav.db` is **not** committed — it
holds `subscribers` and `message_log`, which are real phone numbers and the text
of every message sent to them. `make_seed` copies across only the tables the
model reads and refuses to write a snapshot that picked up anything else
(`--check` verifies an existing one).

`BHAV_DATA_DIR` points the live database at a mounted disk; `bhav/bootstrap.py`
seeds it on first boot and, with `BHAV_SEED_MODE=refresh`, lets a later deploy
carrying newer data replace the pipeline tables while keeping every subscriber.

`requirements.txt` is what the API needs. `requirements-ingest.txt` adds Earth
Engine and lxml for the pipeline — the API never imports them, so a missing GEE
credential cannot take the signal down.

## Satellite NDVI

Sentinel-2 L2A over a rectangle around the Lasalgaon belt, cloud-masked with the
scene-classification band, reduced to two numbers per pass: mean NDVI, and the
share of clear pixels that have dropped below `NDVI_MATURITY_THRESHOLD` — the
crop that has dried down and is heading for the mandi.

Passes are composited to 10 days **in pandas, not in Earth Engine**, because a
10-day window over the monsoon is routinely empty and an empty window has to
stay empty. What that buys:

- The `ndvi` table stores composites at the satellite's own cadence, not a
  fabricated daily series. `obs_date` is the last real pass in each composite.
- `features.py` holds each composite forward and carries the staleness as
  `ndvi_obs_age_days`, which is itself a model feature — so a call made on a
  three-week-old picture is visibly weaker than one made on this morning's pass.
- A composite is **indexed by `obs_date`, not by its window start.** Indexing by
  the start would hand days early in the window a value derived from passes up
  to nine days in their future. That single choice is the difference between a
  backtest and a fantasy.
- `phenology.py` derives greening rate, days since peak and senescence slope
  with Savitzky-Golay coefficients evaluated at the **trailing edge** of the
  window. The textbook centred filter would smooth using future days.

Re-fetch (needs GEE auth; takes ~1 min for the decade):

```bash
python -c "from bhav.ingest import ndvi; ndvi.main()"   # -> data/raw/ndvi_nashik.csv
python -c "from bhav.ingest.load import load_ndvi; load_ndvi()"
python -m scripts.build
```

`scripts.seed_demo` will not overwrite fetched composites (`--force-ndvi` to
override), so the synthetic safety net can't quietly replace real data.

## Weather overlay

Open-Meteo's free archive (no key) for the belt centroid — temperature, rain,
**humidity**, ET0 and wind, 2016 to date. Raw daily weather isn't decision-grade
on its own: 12 mm means one thing in July and another in April. So the overlay
answers the two questions a farmer actually faces, both windowed over a
fortnight and both anomaly-based against the same prior-years-only climatology
the rest of the matrix uses:

- **Harvest window** — `dry_days_14`, `wet_spell`, `et0_anom_14`. Can the crop
  be lifted and cured? A wet *run* is what stops harvest; three wet days in a
  row halt it while the same rainfall spread over a fortnight barely registers,
  which is why the run length is a feature and the total isn't enough.
- **Storage risk** — `humidity_14`, `humidity_anom_14`. Can it be *held*? Onion
  rots in warm humidity, and a farmer who can't store is a forced seller. Forced
  sellers are what turn a harvest into a glut, so this is the overlay's real
  contribution: it sees the glut forming through the storage channel, not just
  the growing one.
- **Maturity pull** — `heat_days_14`. Heat brings the harvest forward.

Humidity is weighted above temperature in the rot score on purpose: in Nashik
the most humid season is also the *coolest*, so requiring both would have made
the "High" band unreachable — it never fired until the weighting was fixed.

Re-fetch (no auth, ~10 s):

```bash
python -c "from bhav.ingest import weather; weather.main()"
python -c "from bhav.ingest.load import load_weather; load_weather()"
python -m scripts.build
```

## Mandi prices (Agmarknet)

Agmarknet was rebuilt as a React app and the old `SearchCmmMkt.aspx` page this
project used to scrape no longer returns HTML tables. Two things to know about
the replacement JSON API at `api.agmarknet.gov.in/v1`:

- The site's own Price/Arrival Report endpoint (`/daily-price-arrival/report`)
  is **CAPTCHA-gated** and answers `TOKEN_OR_CAPTCHA_REQUIRED`. That is a
  deliberate anti-automation control; this project does not try to defeat it.
- `/prices-and-arrivals/date-wise/specific-commodity` is not gated and returns a
  whole **month** for one commodity in one ~140 KB response, so the decade costs
  ~130 polite requests instead of ~3,900 day-by-day calls.

`ingest/mandi.py` walks months, resolves canonical Nashik market names from
Agmarknet's own filter list (the roadmap's "mandi-name drift" risk — the same
yard appears as `APMC Lasalgaon`, `Lasalgaon(Niphad)` and `LASALGAON`), and
writes **44,034 rows across 25 markets, 2016-01 → 2026-09**.

`prices.py` then does the cleaning the roadmap asks for:

- **Arrivals-weighted** aggregation to a district series. Lasalgaon clearing
  2,000 t and a private yard clearing 3 t are not two equal opinions on price.
- **Non-trading days** — 624 of 3,901 days have no print (Sundays, holidays,
  bandhs). Gaps ≤ 5 days interpolate; longer closures hold the last print and
  surface as `days_since_trade`, a model feature, because a shut mandi is not a
  flat market. The longest closure in the record is 11 days.
- **Outlier caps** against a *trailing* robust (MAD) band — 73 prints capped. A
  centred band would let the outlier widen the very band meant to catch it, and
  would leak future prices into a point-in-time feature.
- **CPI deflation** (World Bank `FP.CPI.TOTL`, `ingest/cpi.py`). ₹674 in 2016 is
  ₹1,064 in 2026 rupees; left nominal, a decade of inflation reads as a decade
  of slow bull market and every "price is high for the season" feature drifts.

`price` stays **nominal** (it is what a farmer is quoted and what the ₹/quintal
outcome is measured in); `price_real` is deflated and is what the model and the
label actually use.

Re-fetch (~2 min):

```bash
python -c "from bhav.ingest import mandi, cpi; mandi.main(); cpi.main()"
python -c "from bhav.ingest.load import load_mandi, load_cpi; load_mandi(); load_cpi()"
python -m scripts.build
```

## Data provenance — what's real

| Source | Status |
|---|---|
| Sentinel-2 NDVI | **real** — 840 scenes → 248 composites, 2017-04 → 2026-07 |
| Open-Meteo weather | **real** — 3,900 days, 2016-01 → 2026-09 |
| Agmarknet mandi price | **real** — 44,034 rows, 25 markets, 2016-01 → 2026-09 |
| World Bank CPI | **real** — annual, current year extrapolated |

Every input is now real. `scripts.seed_demo` remains as the offline safety net
and refuses to overwrite any fetched table (`--force-ndvi` / `--force-weather` /
`--force-mandi` to override).

### A note on the label

The roadmap locks the crash label at "modal price drop ≥ 8% within 7–14 days vs
a 14-day rolling baseline". On the real series that fires on **55.6% of days** —
for Nashik onion, "the price will fall 8% sometime in the next fortnight" is
true more often than not, so the label carries almost no information and a SELL
alert would fire constantly. That threshold was fixed in the roadmap's hour-one
"lock it and move on" step, before anyone had seen the data.

The shipped label (≥10% within 10 days, on deflated price) sits at a 37.3% base
rate. Real base rates by threshold, 10-day horizon: 8% → 44.8%, 10% → 37.7%,
15% → 25.3%, **18% → 19.9%**, 20% → 17.3%. If the label is retuned, ~18% is
where "crash" starts meaning something unusual for this crop.

## Design notes

- **One scoring path.** `scoring.score_asof(date)` slices the feature matrix at
  `date` with no lookahead; `/alert` and `/backtest` both call it. A judge can
  pick any date and it's the same code.
- **Leakage is tested, not asserted.** `python -m scripts.check_leakage`
  rebuilds the features with every raw input truncated at date D and fails if
  any value at D moves. It caught a real one: the day-of-year climatology behind
  the anomaly features was averaging over the whole series, including future
  years. Making it expanding cost ~0.05 CV AUC — that gap was the leak.
- **Window, not a day.** The alert engine spreads the point prediction into a
  3–5 day window — the anti-herd design.
- **Honest track record.** `track_record()` reports misses alongside hits, per
  colour.
- **Degrades gracefully.** No LightGBM wheel → logistic-regression fallback.
  GEE not provisioned → `--skip-ndvi`, model trains on price+weather only.

## Baselines — does the model beat "just the calendar"?

`python -m scripts.evaluate` runs the relocked label (≥16% in 10 days, deflated)
through three models on the roadmap's split — train ≤2023, val 2024, test 2025 —
and scores LightGBM against the two baselines rather than against 0.5.

These are the **shipped** model's numbers (regularised-33, all 33 features —
see the capacity pass below for how it was arrived at):

| Split | Model | ROC AUC | Avg precision |
|---|---|---|---|
| **val 2024** (base 15.8%) | seasonal-naive | **0.830** | **0.468** |
| | price-momentum | 0.571 | 0.192 |
| | lightgbm (shipped) | 0.739 | 0.339 |
| **test 2025** (base 18.6%) | seasonal-naive | 0.779 | 0.357 |
| | price-momentum | 0.424 | 0.315 |
| | lightgbm (shipped) | **0.793** | **0.481** |

LightGBM vs each baseline:

| | val 2024 | test 2025 |
|---|---|---|
| vs seasonal-naive | AUC −0.091, AP −0.129 | AUC +0.014, AP +0.125 |
| vs price-momentum | AUC +0.167, AP +0.147 | AUC +0.369, AP +0.166 |

**Read this honestly.** LightGBM wins the test year on both metrics and clears
price-momentum everywhere, but it still *loses to the calendar on val 2024*
(−0.091 AUC). The test-year AUC win of +0.014 has a bootstrap 95% CI of
[−0.027, +0.056] — it is not distinguishable from noise. The **AP** win is the
one that holds: +0.127 on test with CI [+0.033, +0.225], P(better) = 100%.

So the fair summary is: the model earns its place on *precision*, not on
ranking. For a tool that fires a discrete SELL alert, precision on the positive
class is the metric that matters — but the roadmap's "beats seasonal-naive"
requirement is only half-met, and the calendar remains a stubbornly strong
baseline for this crop.

Seasonal-naive is not a straw man: it scores 0.806–0.851 (val) and 0.743–0.798
(test) across 7–30 day buckets and gets *better* as buckets widen, which is what
a real seasonal effect looks like. LightGBM has `doy_sin`/`doy_cos` too, so it
sees the same calendar.

### One bounded capacity pass

`python -m scripts.prune_eval` — three pre-specified interventions on the same
val-2024 / test-2025 split, run once, no selection on the holdout.

| model | val AUC | val AP | test AUC | test AP |
|---|---|---|---|---|
| seasonal-naive *(baseline)* | **0.830** | **0.468** | 0.779 | 0.357 |
| price-momentum *(baseline)* | 0.571 | 0.192 | 0.424 | 0.315 |
| lightgbm-33 *(baseline)* | 0.738 | 0.273 | 0.755 | 0.440 |
| pruned-15 | 0.762 | 0.364 | 0.733 | 0.386 |
| **regularised-33** | 0.739 | 0.339 | **0.793** | 0.481 |
| pruned+reg | 0.762 | 0.409 | 0.750 | 0.439 |
| pruned+reg+stack | 0.759 | 0.369 | 0.749 | **0.499** |

Test-year deltas (AUC / AP):

| variant | vs seasonal-naive | vs price-momentum | vs lightgbm-33 |
|---|---|---|---|
| pruned-15 | −0.046 / +0.029 | +0.309 / +0.070 | −0.022 / −0.055 |
| regularised-33 | **+0.014** / +0.125 | +0.369 / +0.166 | +0.038 / +0.041 |
| pruned+reg | −0.029 / +0.083 | +0.326 / +0.124 | −0.005 / −0.001 |
| pruned+reg+stack | −0.030 / +0.143 | +0.325 / +0.184 | −0.006 / +0.059 |

**Does anything beat seasonal-naive on test-year AUC?** Nominally yes, once:
`regularised-33` at 0.793 vs 0.779. It does not survive scrutiny:

- Bootstrap on the test year (365 rows, 68 positives): AUC diff **+0.014,
  95% CI [−0.027, +0.056]**, P(better) = 74%. The interval crosses zero.
- The same variant *loses* to seasonal-naive on val 2024 by −0.091. A real
  ranking improvement should appear in both holdout years; this appears in one.

So: no variant beats seasonal-naive on AUC in a way worth believing.

What did hold up is **average precision**. `regularised-33` beats seasonal-naive
on test AP by +0.127, 95% CI [+0.033, +0.225], P(better) = 100% — that margin
excludes zero. The stacked variant is the best AP overall (0.499). For a tool
that fires a discrete SELL alert, precision on the positive class is the metric
that matters more than global ranking, so this is not a small consolation.

Two incidental findings: **no feature had zero gain importance** (there was
nothing dead to prune, and no cross-terms were ever added despite the roadmap
planning them), and **pruning hurt** — regularisation alone, keeping all 33
features, was what moved the numbers. Capacity, not feature count, was the
binding constraint.

**Adopted: `regularised-33`** — all 33 features kept, no pruning. `num_leaves`
31→8, `max_depth` unbounded→4, `min_child_samples` 30→60, `reg_lambda` 1→5, and
`subsample_freq=1` so the `subsample=0.8` the config had always been asking for
actually takes effect (LightGBM silently ignores bagging without a frequency).

Two side effects worth knowing:

- **The alert mix got healthier.** Sampled monthly across the history, colours
  went from 35% RED / 2.6% AMBER / 62% GREEN to **16% RED / 13% AMBER / 71%
  GREEN**. RED now sits near the 18.6% base rate instead of over-firing, and
  AMBER is a real band rather than a vestigial one.
- **Confidence numbers dropped** on the demo dates (Dec 2019: 97%→87%,
  Dec 2024: 92%→41%) because the regularised model is less extreme. All three
  still call RED and still hold up. Note `confidence` is
  `|p − 0.5| × 200` — distance from a coin flip, *not* P(the call is right) —
  so a RED at 41% is coherent but reads oddly; worth revisiting separately.

## Alert threshold sweep (operating point)

`python -m scripts.threshold_sweep` — walk-forward with a monthly refit and a
10-day embargo, weekly decision points, regularised-33. Two periods: the 2023
crash window (June collapse *and* the Oct–Dec spike-and-crash) and the 2025 test
year. ₹ are nominal ₹/quintal.

Economics per alert, matching `backtest.py`'s RED branch: sell across the 5-day
alert window versus holding out for a better price later in the 10-day horizon.

**2023 crash window** — 31 weekly decisions, 7 preceded a crash (23%)

| candidate | p cut | alerts | coverage | hit rate | recall | avg ₹/alert | worst ₹ | false | missed |
|---|---|---|---|---|---|---|---|---|---|
| conservative | 0.84 | 3 | 10% | 0% | 0% | 0 | −415 | 3 | 7 |
| moderate | 0.69 | 5 | 16% | 20% | 14% | +206 | −415 | 4 | 6 |
| liberal | 0.30 | 11 | 35% | 36% | 57% | +135 | −1,114 | 7 | 3 |

**2025 test year** — 53 weekly decisions, 11 preceded a crash (21%)

| candidate | p cut | alerts | coverage | hit rate | recall | avg ₹/alert | worst ₹ | false | missed |
|---|---|---|---|---|---|---|---|---|---|
| conservative | 0.79 | 1 | 2% | 0% | 0% | +50 | +50 | 1 | 11 |
| moderate | 0.62 | 3 | 6% | 33% | 9% | −111 | −487 | 2 | 10 |
| liberal | 0.30 | 10 | 19% | 50% | 45% | +36 | −487 | 5 | 6 |

**Pooled** — 84 decisions, 18 crashes

| candidate | alerts | coverage | hit rate | avg ₹/alert | worst ₹ | false | missed | total ₹ |
|---|---|---|---|---|---|---|---|---|
| conservative | 4 | 5% | **0%** | +13 | −415 | 4 | 18 | +51 |
| moderate | 8 | 10% | 25% | +87 | −487 | 6 | 16 | +699 |
| liberal | 21 | 25% | **43%** | +88 | −1,114 | 12 | 9 | +1,842 |

### The precision/coverage trade-off is inverted here

The usual assumption — tighter threshold buys precision at the cost of coverage
— does not hold. Liberal has the **best** hit rate (43% vs 0%), the best recall
(9 of 18 crashes vs 0), and the most total rupees. Conservative fires four times
across three years and is wrong every time.

A calibration check on the pooled walk-forward probabilities explains why:

| predicted bin | n | mean predicted | observed crash rate |
|---|---|---|---|
| 0.0–0.1 | 46 | 0.04 | 0.07 |
| 0.1–0.2 | 13 | 0.16 | 0.31 |
| 0.2–0.3 | 4 | 0.23 | 0.50 |
| 0.3–0.5 | 10 | 0.40 | 0.40 |
| 0.5–0.7 | 4 | 0.55 | 0.75 |
| **0.7–1.0** | **7** | **0.83** | **0.29** |

Ranking works overall — Spearman(prob, crash) = **+0.341, p = 0.002** — but it
breaks in the top bin: the model's most confident calls are its least accurate.
Everything below 0.7 is calibrated or *under*-confident; above 0.7 it inverts.
That is precisely why the tight cutoffs perform worst.

### Read the sample sizes before choosing

Conservative fires **4 times** and moderate **8 times** across both periods. A
"0% hit rate" on four alerts and a "25%" on eight are close to noise; only the
liberal row (21 alerts) has enough events to say much. The top calibration bin
is n = 7. Treat the inversion as a strong hint, not a settled fact.

Two further notes for the decision: ₹ gain and crash-label hit are *different*
outcomes — 2025's conservative alert was a false alarm that still banked +₹50,
because selling into the window beat holding even without a 16% crash. And the
worst single loss scales with coverage (−₹1,114 liberal vs −₹415 conservative),
so the tail risk is the price of the recall.

No operating point recommended here.

### Intermediate cutoffs (0.35–0.55)

Four evenly spaced fixed cutoffs, same walk-forward and embargo, pooled over the
2023 crash window + 2025 test year (84 weekly decisions, 18 crashes):

| cutoff | alerts | coverage | hit rate | recall | avg ₹/alert | worst ₹ | false | missed | total ₹ |
|---|---|---|---|---|---|---|---|---|---|
| 0.35 | 19 | 23% | 47% | 50% | +86 | −1,114 | 10 | 9 | +1,627 |
| 0.42 | 14 | 17% | 43% | 33% | +90 | −1,114 | 8 | 12 | +1,258 |
| 0.48 | 11 | 13% | 45% | 28% | **+197** | −487 | 6 | 13 | **+2,165** |
| 0.55 | 8 | 10% | 25% | 11% | +87 | −487 | 6 | 16 | +699 |

Hit rate holds around 43–47% from 0.35 to 0.48 and then falls off at 0.55.
0.48 has the best per-alert and total rupees with half the tail risk of 0.35,
but on 11 alerts. Still small numbers — 8 to 19 events per row.

### Calibration audit

`python -m scripts.calibrate` fits isotonic on **2024 out-of-sample predictions
only** (model trained on rows >10 days before 2024, so no 2024-derived label
reaches it), then audits on **2025-01 → 2026-08**, strictly after the fit year.
Daily points here, not weekly — calibration is a question about probability
accuracy, and daily gives 603 points instead of ~50. Adjacent days correlate, so
read bin counts as weight of evidence, not independent samples.

Sub-0.6 zone (576 of 603 points), binned on the raw score:

| bin | n | raw | calibrated | observed | gap |
|---|---|---|---|---|---|
| 0.0–0.1 | 335 | 0.04 | 0.00 | 0.04 | −0.04 |
| 0.1–0.2 | 104 | 0.15 | 0.09 | **0.36** | −0.26 |
| 0.2–0.3 | 68 | 0.24 | 0.16 | 0.25 | −0.09 |
| 0.3–0.4 | 42 | 0.34 | 0.29 | **0.12** | +0.17 |
| 0.4–0.5 | 16 | 0.44 | 0.30 | 0.25 | +0.05 |
| 0.5–0.6 | 11 | 0.54 | 0.30 | **0.73** | −0.42 |

| | mean abs error | mean bias |
|---|---|---|
| raw | 0.210 | −0.025 |
| calibrated | **0.181** | −0.077 |

**The sub-0.6 zone does not stay clean.** On 84 weekly points it looked
well-behaved; on 576 daily points it is non-monotone — 0.1–0.2 badly
*under*-predicts (observes 0.36), 0.3–0.4 *over*-predicts (observes 0.12), and
0.5–0.6 under-predicts again (observes 0.73). The earlier "everything below 0.7
is fine" read was a small-sample artefact.

Isotonic still helps overall (mean absolute error 0.210 → 0.181) but it is not a
fix: it inherits 2024's low base rate (15.8%) and pushes the 0.5–0.6 band down
to 0.30 against an observed 0.73 — its largest error lands squarely in the band
the threshold sweep cares about most.

### Calibrated confidence in the dashboard

`bhav/calibration.py` holds the isotonic layer in `models/calibrator.pkl`,
separate from the model so recalibrating never means retraining. Every score now
carries both numbers:

```
score.drop_probability        raw
score.calibrated_probability  isotonic-adjusted
score.is_calibrated           False if no calibrator exists yet
alert.confidence              raw: |p - 0.5| x 200, distance from a coin flip
alert.calibrated_confidence   P(this call is right), as a percentage
```

`calibrated_confidence` is the calibrated probability *of the call actually
made* — P(crash) for a sell-side colour, P(no crash) for WAIT. Stated the other
way a "Wait" would read as 20% confident exactly when the model is most sure
nothing is coming. The dashboard shows this and labels it `CALIBRATED`; the
signal card falls back to the raw number (labelled `RAW`) against an older
backend.

Isotonic output is clipped to **[0.02, 0.98]**. Isotonic is a step function and
saturates to exactly 0.0 and 1.0; fit on 366 days it cannot resolve finer than
~1/366, so "100% confidence" would be an artefact of the method — and it is the
worst possible number to put in front of a farmer.

Two caveats worth keeping visible:

- The shipped model is trained on **all** data including 2024, so its 2024
  predictions are in-sample while the calibrator was fit on out-of-sample ones.
  That mismatch is the standard cost of calibrating on a held-out year.
- Backtest dates **before 2025** get a calibrator fit on later data. Their
  calibrated confidence is indicative, not a clean out-of-sample figure.

Stopped here: no further threshold search, no changes to the underlying model.

## WhatsApp delivery

Roadmap north-star #2: register a phone on stage, the localized alert arrives.

**Message.** Three languages (English, Hindi, Marathi), four lines, fixed order:
what to do, by when, what it is worth, why. A farmer who reads only the first
line still has the decision. The `reason` is assembled in English by the alert
engine and translated fragment-by-fragment via a lookup keyed on the English
phrase — so adding a feature to `scoring.py` needs no change here, it simply
falls through to English until someone translates it. The confidence shown is
the **calibrated** number, not the raw score.

```
🟢 *भाव* · लासलगाव कांदा · 2026-09-04
*थांबा* — कालावधी 2026-09-11 ते 2026-09-15
परिणाम: +₹251/क्विंटल थांबण्याच्या तुलनेत · 82% खात्री
कारण: महिनाभराची तेजी — आता ताणलेली; तसेच भाव वर्षाच्या सरासरीपेक्षा बराच वर
```

**Channel.** WhatsApp, through [open-wa](https://open-wa.org) — a real WhatsApp
account driven via WhatsApp Web by the Node bridge in `whatsapp/`. No 24-hour
window, no approved template: see the setup section below for why that decided
the design.

**Registration.** `subscribers` table keyed on an E.164 phone (a bare 10-digit
Indian mobile is normalised), holding crop, village PIN, language, usual sell
window and channel. Re-registering updates and reactivates; `STOP` is a soft
opt-out so history survives, and `START` opts back in — both arrive over
WhatsApp and are forwarded by the bridge. Every send attempt lands in
`message_log`, successes and failures both.

| Method | Path | Purpose |
|---|---|---|
| POST | `/subscribe` | register a phone; sends the current signal unless `send_welcome:false` |
| POST | `/unsubscribe` | soft opt-out (the bridge posts here on `STOP`) |
| POST | `/resubscribe` | opt back in (the bridge posts here on `START`) |
| GET  | `/subscribers` | counts by language and channel (never the phone list) |
| GET  | `/message/status` | bridge + session state; sends nothing |
| GET  | `/message/qr` | the pairing QR as a PNG, while the session is unlinked |
| GET  | `/message/check` | is a given number reachable on WhatsApp |
| POST | `/message/preview/all` | the alert in all three languages |
| POST | `/message/send` | one number |
| POST | `/broadcast` | everyone — **`dry_run` defaults to true** |
| GET  | `/message/log` | delivery attempts, with errors |

```bash
python -m scripts.broadcast                    # preview only, sends nothing
python -m scripts.broadcast --send             # actually deliver
python -m scripts.broadcast --to +91... --lang mr   # one number
```

### open-wa setup

Meta's Cloud API only permits a free-form message within **24 hours** of the
recipient's last inbound message; outside that window nothing sends but a
pre-approved template. A weekly alert to farmers who have never messaged us is
precisely the case that rule forbids, which is why delivery does not go through
it. (Twilio was tried first and was worse: its trial tier rejected every
free-form send with `21654` *and* blocked the Content API needed to create the
template it demanded.)

open-wa drives a real WhatsApp account instead — no window, no template. The
costs are real: a phone must link the session once and stay linked, the account
can be banned if it is used to spam, this is an unofficial automation of
WhatsApp Web rather than a supported API, and **unlicensed open-wa will only
message numbers already saved as contacts on the linked phone** — anything else
returns `Not a contact`. Save the recipient on the sending handset, or buy a
licence at <https://get.openwa.dev>.

The library is Node, so it runs as a separate process next to this API; the
Python side (`bhav/whatsapp.py`) only speaks HTTP to it.

```bash
cd whatsapp && npm install
cp .env.example .env      # WA_BRIDGE_TOKEN must match backend/.env
npm start
```

Two values in `backend/.env`:

| Variable | Notes |
|---|---|
| `WA_BRIDGE_URL` | Defaults to `http://localhost:3001`. |
| `WA_BRIDGE_TOKEN` | Shared secret with the bridge. Set it — that process can message anyone from the linked account. |

**Linking.** The session starts unlinked and reports `session_status: "qr"`.
Scan the pairing QR from the sending phone (WhatsApp → Linked devices → Link a
device) — the backend serves it at `/message/qr`, the registration section of
the site displays it and polls until it flips to linked, and `npm run link`
prints it in the terminal for an SSH session. `GET /message/status` reports
`whatsapp_ready`, which is the only field that means a message will actually go
out; `explain_error()` maps a dead bridge, an unlinked session and a token
mismatch to the specific thing to go and fix, and the broadcast script prints it
as `FIX:`.

**Status.** Delivering. The session is linked to a real handset and messages
have arrived on recipient phones with WhatsApp message ids logged in
`message_log`. The one live limitation is the contact restriction above: sends
to saved contacts succeed, sends to unknown numbers fail with `Not a contact`
and `explain_error()` says what to do about it.
