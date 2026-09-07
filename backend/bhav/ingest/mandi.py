"""Mandi (APMC) price + arrivals history for onion in Nashik, from Agmarknet.

Agmarknet was rebuilt as a React app ("Agmarknet 2.0") and the old
`SearchCmmMkt.aspx` page this module used to scrape no longer returns HTML
tables. The replacement is a JSON API at `api.agmarknet.gov.in/v1`.

Two notes on which endpoint we use and why:

* The report endpoint the site's own "Price/Arrival Report" page calls
  (`/daily-price-arrival/report`) is **CAPTCHA-gated** — it answers
  `TOKEN_OR_CAPTCHA_REQUIRED`. That is a deliberate anti-automation control and
  this module does not try to defeat it.
* `/prices-and-arrivals/date-wise/specific-commodity` is not gated, and is far
  kinder to the server besides: it returns a whole **month** for one commodity
  in one ~140 KB response, so the decade costs ~130 requests instead of ~3,900
  day-by-day calls.

Roadmap: pull daily arrivals + min/modal/max for Nashik onion, write
`data/raw/mandi_onion_nashik.csv`, and commit it — this is a pre-bake, never a
live call during the demo.

If Agmarknet is unreachable, drop a manual export at that path with columns
[date, market, price_modal, arrivals_tonnes] and run the loader instead.
"""

from __future__ import annotations

import time

import pandas as pd
import requests

from ..config import AGMARKNET, CROP, DISTRICT, HISTORY_START, RAW_DIR

OUT_CSV = RAW_DIR / "mandi_onion_nashik.csv"

API = "https://api.agmarknet.gov.in/v1"
MONTH_URL = f"{API}/prices-and-arrivals/date-wise/specific-commodity"
FILTERS_URL = f"{API}/daily-price-arrival/filters"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (bhav-hackathon data pull)",
    "Origin": "https://agmarknet.gov.in",
    "Referer": "https://agmarknet.gov.in/",
}

COLUMNS = [
    "district", "crop", "date", "market", "variety",
    "arrivals_tonnes", "price_min", "price_modal", "price_max",
]

# Be a good citizen: this is a public government API and one full pull is ~130
# requests. No concurrency, a pause between calls.
REQUEST_PAUSE_S = 0.6


def _get(url: str, params: dict, retries: int = 4) -> dict:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=120)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return {}


def _norm(name: str) -> str:
    """Loose key for matching market names across Agmarknet's spellings.

    The same yard appears as 'APMC Lasalgaon', 'Lasalgaon(Niphad) ' and
    'LASALGAON' depending on the endpoint and the year — the roadmap calls this
    out as 'mandi-name drift'. Normalising to lowercase alphanumerics lets the
    canonical list absorb it without a hand-maintained alias table.
    """
    s = name.strip().lower()
    if s.startswith("apmc"):
        s = s[4:]
    return "".join(ch for ch in s if ch.isalnum())


def nashik_markets() -> dict[str, str]:
    """Canonical {normalised key: display name} for every market in the district.

    Sourced from Agmarknet's own filter list rather than hardcoded, so a new
    private market yard appears automatically instead of being silently dropped.
    """
    data = _get(FILTERS_URL, {})["data"]
    state_id = next(s["state_id"] for s in data["state_data"]
                    if s["state_name"].strip().lower()
                    == AGMARKNET["state_head"].lower())
    district_id = next(d["id"] for d in data["district_data"]
                       if d["state_id"] == state_id
                       and d["district_name"].strip().lower() == DISTRICT.lower())
    markets = {}
    for m in data["market_data"]:
        if m.get("district_id") == district_id:
            markets[_norm(m["mkt_name"])] = m["mkt_name"].strip()
    return markets


def _ids() -> tuple[int, int]:
    data = _get(FILTERS_URL, {})["data"]
    commodity = next(c["cmdt_id"] for c in data["cmdt_data"]
                     if c["cmdt_name"].strip().lower()
                     == AGMARKNET["commodity_head"].lower())
    state = next(s["state_id"] for s in data["state_data"]
                 if s["state_name"].strip().lower()
                 == AGMARKNET["state_head"].lower())
    return commodity, state


def fetch_month(year: int, month: int, commodity_id: int, state_id: int,
                canonical: dict[str, str]) -> pd.DataFrame:
    """One month of Maharashtra onion prices, filtered to Nashik markets."""
    payload = _get(MONTH_URL, {
        "year": year, "month": month, "includeExcel": "false",
        "stateId": state_id, "commodityId": commodity_id,
    })
    if not payload.get("success"):
        return pd.DataFrame(columns=COLUMNS)

    rows = []
    for market in payload.get("markets", []):
        key = _norm(market.get("marketName", ""))
        if key not in canonical:
            continue                      # a market outside Nashik district
        name = canonical[key]
        for day in market.get("dates", []):
            date = pd.to_datetime(day.get("arrivalDate"), dayfirst=True,
                                  errors="coerce")
            if pd.isna(date):
                continue
            for lot in day.get("data", []):
                rows.append({
                    "district": DISTRICT,
                    "crop": CROP,
                    "date": date,
                    "market": name,
                    "variety": (lot.get("variety") or "Other").strip(),
                    "arrivals_tonnes": lot.get("arrivals"),
                    "price_min": lot.get("minimumPrice"),
                    "price_modal": lot.get("modalPrice"),
                    "price_max": lot.get("maximumPrice"),
                })
    return pd.DataFrame(rows, columns=COLUMNS)


def fetch(start: str = HISTORY_START, end: str | None = None) -> pd.DataFrame:
    end_ts = pd.Timestamp(end) if end else pd.Timestamp.utcnow().normalize().tz_localize(None)
    commodity_id, state_id = _ids()
    canonical = nashik_markets()
    print(f"  {len(canonical)} canonical Nashik markets")

    frames = []
    months = pd.date_range(pd.Timestamp(start).replace(day=1), end_ts, freq="MS")
    for i, m in enumerate(months, 1):
        part = fetch_month(m.year, m.month, commodity_id, state_id, canonical)
        frames.append(part)
        if i % 12 == 0 or i == len(months):
            print(f"  {m:%Y-%m} ({i}/{len(months)}): "
                  f"{sum(len(f) for f in frames)} rows so far")
        time.sleep(REQUEST_PAUSE_S)

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    if df.empty:
        raise RuntimeError(
            "Agmarknet returned no rows. Drop a manual export at "
            f"{OUT_CSV} with columns [date, market, price_modal, "
            "arrivals_tonnes] and run the loader instead."
        )

    for c in ("arrivals_tonnes", "price_min", "price_modal", "price_max"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values(["date", "market", "variety"]).reset_index(drop=True)


def main() -> None:
    df = fetch()
    df.to_csv(OUT_CSV, index=False)
    print(f"mandi: {len(df)} rows, {df['date'].min():%Y-%m-%d}"
          f"..{df['date'].max():%Y-%m-%d}, "
          f"{df['market'].nunique()} markets -> {OUT_CSV}")


if __name__ == "__main__":
    main()
