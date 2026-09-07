# MandiAlert — Hackathon Roadmap

**Format:** 36–48 hrs · 2–3 builders · demo weights *backtest depth* and *live farmer flow* equally.

**One-liner:** Fuse Sentinel-2 NDVI + weather + Agmarknet mandi prices into one backtested *Sell Now / Wait* signal with a ₹/quintal impact, delivered over WhatsApp/SMS in local language.

**v1 scope (frozen):** Onion · Nashik district (Maharashtra) · modal price · 2020–2025 history.

**North-star demo moments**
1. Judge picks any past date → sees the alert that *would have fired* + real ₹ outcome vs. selling blind that day, **misses shown too**.
2. Register a phone on stage → a real localized WhatsApp/SMS alert arrives.

---

## Golden rules for the 48 hrs

- **Pre-bake all data.** No live Google Earth Engine or Agmarknet calls during the demo. Export to CSV/Parquet early and commit it.
- **One district, one crop.** Every "let's also add…" is a cut.
- **The decision object is the contract.** Fix it in hour 1 so both tracks build against it in parallel.
- **Backtest = precomputed JSON.** Date picker reads a file, returns instantly.
- **Messaging = Twilio sandbox** (WhatsApp sandbox + SMS). No WhatsApp Business API approval in scope.
- **Model can be simple.** A small LightGBM *or* a transparent pattern-score. It only has to beat "seasonal-naive." Simplicity is on-brand ("not a forecast engine").
- **Record a working run by hour 40** as demo insurance against venue wifi.

---

## Pre-hackathon checklist (do before the clock starts, if rules allow)

- [ ] Google Earth Engine account + auth working; a notebook that exports Nashik NDVI 10-day composites 2020–2025 to `data/raw/ndvi_nashik.csv`.
- [ ] Agmarknet: download onion / Nashik daily arrivals + min/modal/max price 2020–2025 → `data/raw/prices_nashik.csv`. Keep this file committed as the source of truth.
- [ ] Open-Meteo historical weather pull for Nashik centroid → `data/raw/weather_nashik.csv`.
- [ ] Twilio account; WhatsApp sandbox joined from every team phone + (ideally) a judge phone; SMS-capable number.
- [ ] Repo skeleton pushed: `ingest/ features/ model/ backtest/ api/ delivery/ dashboard/ data/ notebooks/ docs/`, `.env.example`, task runner.
- [ ] Decide stack (below) and pin versions in a lockfile.
- [ ] 3 message templates drafted: English, Hindi, Marathi.

> If prep isn't allowed, the first 3 hrs of Track A become "get the data," and the model window shrinks accordingly.

---

## Timeline (relative hours, assumes ~48 hr event)

### H0–H2 — Shared kickoff (whole team)
- Lock the **decision object**:
  `{ date, signal: SELL_NOW | WAIT, window_days, expected_delta_rs_per_qtl, confidence, reason }`
- Lock the **"price crash" label**: modal price drop ≥ 8% within 7–14 days vs. a 14-day rolling baseline, on deflated price. (One definition. Move on.)
- Stub the API contract (`/signal/on/{date}`, `/signal/today`, `/backtest`, `/explain/{date}`) returning fake data so both tracks unblock.
- Split into **Track A (Data/ML/Backtest)** and **Track B (API/Dashboard/Messaging)**.

### H2–H12 — Parallel build I
**Track A — dataset**
- Load the 3 raw CSVs; align on `(date)` daily grid; NDVI forward-filled within its 10-day composite with an `ndvi_obs_age_days` column.
- Clean prices: holidays/zero-arrival days, outlier caps, CPI deflation, log.
- Smooth NDVI (Savitzky–Golay); derive greening rate, days-since-NDVI-peak, senescence slope, "% area past maturity threshold."
- Output `data/processed/v1.parquet` + a 1-page EDA notebook.

**Track B — thin vertical slice**
- Send **one real WhatsApp + one real SMS** to a phone via Twilio. This is the highest-risk integration — do it first.
- Registration form (Streamlit page or simple form): phone, crop, village pin, usual sell window → SQLite.
- Dashboard skeleton: Nashik map + NDVI/price/weather charts on real data, signal card on **mock** API.

### H12–H20 — Parallel build II
**Track A — features + model**
- Point-in-time feature table (strict: every feature uses only data available on/before `date`, honoring `ndvi_obs_age_days`). Groups: NDVI trend/phenology, weather anomalies, price return/vol, arrivals momentum, seasonality/festival flags, a few cross terms.
- Time split: train ≤2023, val 2024, test 2025.
- Baselines: seasonal-naive, price-momentum-only. Then LightGBM (small, regularized).
- Expected-₹ target: historical mean Δprice following similar patterns.
- Hand-check 2 dates for leakage.

**Track B — templates + wiring**
- Multilingual templates rendered from the decision object (color word + ₹ + one-line reason + window). Keep it to 4 lines.
- Dashboard reads the **real** API for `/signal/today`.
- Daily "compute → send" script (manual trigger is fine for demo).

### H20–H24 — Rest / stagger
Rotate sleep. At least one person awake per track. No new features after H20 tonight — only finish what's started.

### H24–H32 — Parallel build III
**Track A — backtest engine**
- Walk-forward: for every day in 2025 (and the 2023 crash window), emit the decision object, no lookahead, same feature code as serving.
- Outcome: `₹ gain = best modal price in the recommended window − modal price on the usual sell date`, per quintal.
- Aggregates: hit rate, avg ₹ gain/alert, worst case, false-alarm count, missed-crash count, coverage.
- Write `backtest/results/nashik.json` (precomputed) + `/backtest` and `/explain/{date}` serve from it.
- "Show the miss" list included in the JSON.

**Track B — backtest UI + explain**
- Date picker → calls `/backtest` / `/signal/on/{date}` → renders alert card + ₹ outcome vs. blind sell + a small chart marking the window.
- "Misses" table view.
- `reason` string: template + top-3 features (SHAP if time; otherwise gain-based importance).

### H32–H40 — Integration + freeze
- End-to-end run 1: pick 3 different past dates → correct alert + honest outcome each time.
- End-to-end run 2: register a phone → receive the localized alert for today's signal.
- **Freeze features and model.** Bugfix only after this.
- Optional if ahead: cash-need branch — partial-sell qty calc + a static list of ~5 nearby WDRA warehouses with distance.
- **Record the full demo run** (screen + phone).

### H40–H46 — Polish + pitch
- Demo script (below), rehearse twice with a stopwatch.
- Slides: problem, "traders have this signal, farmers don't," how it works (5 steps), backtest metrics table, honest limitations.
- Dashboard cosmetics: labels, units (₹/quintal), a legend, a "model card" link.
- Limitations slide: pattern-matched not forecast, one district, small data, shows its misses.

### H46–H48 — Buffer
Dry runs, fallback video ready, submission form, repo README, `.env` sanitized.

---

## Scope guillotine

**MUST (no demo without these)**
- Aligned NDVI + weather + price dataset for Nashik onion.
- One crash label; one model beating seasonal-naive on the test year.
- Precomputed backtest with ₹ outcomes **and a misses list**.
- Dashboard: date picker + alert card + outcome + misses table + today's signal.
- One live WhatsApp + one live SMS, localized template (EN + at least Hindi or Marathi).
- Registration capturing phone + crop + usual sell window.
- Limitations slide.

**NICE (only if a track is ahead)**
- Probability calibration; SHAP reasons.
- Cash-need branch: partial-sell calc + static WDRA warehouse list.
- Third language; mandi diversification hint.
- Deployed URL (vs. laptop + ngrok).

**CUT (explicitly out)**
- Live GEE / Agmarknet during demo · WhatsApp Business API · auth · Celery/queues · multi-district · retraining · monitoring dashboards · pilot playbook · anti-herding guardrail (mention it verbally as "next step").

---

## Team split (2–3 people)

| Role | Owns | Phases |
|---|---|---|
| **Dev A — Data/ML** | ingestion, alignment, features, label, model, backtest engine | H2–H32 heavy |
| **Dev B — Full-stack** | API, dashboard, date-picker UI, integration | throughout |
| **Dev C — Delivery/Pitch** (or split A/B if 2 people) | Twilio WhatsApp+SMS, templates, registration, slides, demo script, fallback recording | H2–H12 spike, then pitch |

If **2 people**: A takes Data/ML + backtest; B takes API + dashboard + messaging; slides shared in H40–H46.

---

## Demo script (~5 min)

1. **Problem (30s):** smallholders sell on habit/cash-need; a glut can be weeks away; NDVI + weather already predict harvest volume — traders use it, farmers don't.
2. **Today's signal (30s):** dashboard, Nashik onion — "WAIT, sell within 4–7 days, +₹180/qtl expected, NDVI shows nearby harvest surge in ~10 days."
3. **Backtest, the proof (90s):** judge names any date in 2023 → show the alert that would have fired and the **real** ₹ gain vs. selling blind that day.
4. **Honesty (30s):** open the misses table — every false alarm and missed crash. "A tool that admits when it's wrong."
5. **Live farmer flow (60s):** register a phone on stage → WhatsApp alert arrives in Marathi with color + ₹ + one-line reason.
6. **Cash-need + next steps (30s):** if you need money now → partial-sell qty + nearest WDRA warehouse. Next: personalized per-plot signals + anti-herding dispersion, more crops/districts.
7. **Limitations (20s):** pattern-matched, not a forecast engine; one district; small data; shows its misses.

---

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11 (`uv`) |
| Satellite | Google Earth Engine → CSV export **before** the event |
| Weather | Open-Meteo historical API → CSV |
| Prices | Agmarknet historical CSV (committed) |
| Store | DuckDB/Parquet (analytics) + SQLite (registrations, serving) |
| ML | LightGBM + scikit-learn (+ SHAP if time) |
| API | FastAPI + Uvicorn |
| Dashboard | Streamlit (fastest for this timebox) |
| Messaging | Twilio — WhatsApp sandbox + SMS |
| Expose | ngrok / Cloudflare Tunnel from a laptop is fine |

---

## Hackathon risk register

| Risk | Mitigation |
|---|---|
| GEE auth / export eats hours | Do it pre-event; commit `ndvi_nashik.csv`; never call GEE live |
| Twilio WhatsApp sandbox needs recipient opt-in | Pre-join team + judge phones; SMS as the always-works fallback; narrate |
| Venue wifi dies mid-demo | Pre-recorded full run by H40; screenshots in slides |
| Backtest looks fake-good (leakage) | One shared feature path for train + serve; hand-check 2 dates; show misses |
| Overfit to the 2023 crash | ≤ ~15 features, time split, report per-year numbers, keep confidence humble |
| Agmarknet gaps / mandi-name drift | Use the committed snapshot; canonical mandi mapping; interpolate small gaps |
| Dashboard polish rabbit-hole | Timebox to H40–H46; function over finish |
| Scope creep (second crop/district) | Guillotine list is law |

---

## Definition of done

- `make demo` (or documented steps) brings up API + dashboard from the committed data with no network calls.
- Any date in 2025 (and the 2023 crash window) returns an alert + ₹ outcome in < 1s.
- A fresh phone registration receives a localized WhatsApp **or** SMS alert.
- Backtest metrics table + misses list visible in the dashboard.
- Fallback recording exists.
- README explains what's real, what's stubbed, and the limitations.
