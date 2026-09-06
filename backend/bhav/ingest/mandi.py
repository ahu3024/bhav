"""Mandi (APMC) price + arrivals history for onion in Nashik, scraped from the
Agmarknet report page (SearchCmmMkt.aspx).

Agmarknet caps each query to a short window and is flaky, so we pull one month
at a time with retries. Output: data/raw/mandi_onion_nashik.csv
(one row per market per day, modal price ₹/quintal).

If Agmarknet is down during the event, drop a manually exported CSV with columns
[date, market, price_per_quintal, arrivals_tonnes] at that path and skip this.
"""

from __future__ import annotations

import io
import time

import pandas as pd
import requests

from ..config import AGMARKNET, CROP, DISTRICT, HISTORY_START, RAW_DIR

OUT_CSV = RAW_DIR / "mandi_onion_nashik.csv"
BASE = "https://agmarknet.gov.in/SearchCmmMkt.aspx"
HEADERS = {"User-Agent": "Mozilla/5.0 (bhav-hackathon data pull)"}


def _month_ranges(start: str, end: str):
    cur = pd.Timestamp(start).normalize().replace(day=1)
    last = pd.Timestamp(end).normalize()
    while cur <= last:
        nxt = (cur + pd.offsets.MonthBegin(1))
        yield cur, min(nxt - pd.Timedelta(days=1), last)
        cur = nxt


def _fetch_window(d_from: pd.Timestamp, d_to: pd.Timestamp,
                  retries: int = 3) -> pd.DataFrame:
    f = d_from.strftime("%d-%b-%Y")
    t = d_to.strftime("%d-%b-%Y")
    params = {
        "Tx_Commodity": AGMARKNET["commodity_code"],
        "Tx_State": AGMARKNET["state_code"],
        "Tx_District": 0,
        "Tx_Market": 0,
        "DateFrom": f, "DateTo": t, "Fr_Date": f, "To_Date": t,
        "Tx_Trend": 0,
        "Tx_CommodityHead": AGMARKNET["commodity_head"],
        "Tx_StateHead": AGMARKNET["state_head"],
        "Tx_DistrictHead": "--Select--",
        "Tx_MarketHead": "--Select--",
    }
    for attempt in range(retries):
        try:
            r = requests.get(BASE, params=params, headers=HEADERS, timeout=90)
            r.raise_for_status()
            tables = pd.read_html(io.StringIO(r.text))
        except ValueError:
            return pd.DataFrame()          # "No Data Found" page -> no tables
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))
            continue

        for tbl in tables:
            cols = {str(c).strip().lower(): c for c in tbl.columns}
            if any("modal" in c for c in cols):
                return _normalise(tbl, cols)
        return pd.DataFrame()
    return pd.DataFrame()


def _normalise(tbl: pd.DataFrame, cols: dict) -> pd.DataFrame:
    def col(*keys):
        for k in keys:
            for lc, orig in cols.items():
                if k in lc:
                    return orig
        return None

    out = pd.DataFrame({
        "market": tbl[col("market")].astype(str).str.strip(),
        "district": tbl[col("district")].astype(str).str.strip()
        if col("district") else DISTRICT,
        "date": pd.to_datetime(tbl[col("price date", "date")],
                               dayfirst=True, errors="coerce"),
        "price_per_quintal": pd.to_numeric(
            tbl[col("modal")].astype(str).str.replace(",", ""), errors="coerce"),
    })
    arr = col("arrival")
    out["arrivals_tonnes"] = (
        pd.to_numeric(tbl[arr].astype(str).str.replace(",", ""), errors="coerce")
        if arr else pd.NA
    )
    return out.dropna(subset=["date", "price_per_quintal"])


def fetch(start: str = HISTORY_START, end: str | None = None) -> pd.DataFrame:
    end = end or pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    frames = []
    for d_from, d_to in _month_ranges(start, end):
        part = _fetch_window(d_from, d_to)
        if not part.empty:
            frames.append(part)
        print(f"  {d_from:%Y-%m}: {0 if part.empty else len(part)} rows")
        time.sleep(1.0)

    if not frames:
        raise RuntimeError(
            "Agmarknet returned no data. Drop a manual export at "
            f"{OUT_CSV} with columns [date, market, price_per_quintal, "
            "arrivals_tonnes] and re-run the loader."
        )

    df = pd.concat(frames, ignore_index=True)
    df = df[df["district"].str.contains(DISTRICT, case=False, na=False)]
    df["crop"] = CROP
    df = (
        df.groupby(["district", "crop", "date", "market"], as_index=False)
        .agg(price_per_quintal=("price_per_quintal", "mean"),
             arrivals_tonnes=("arrivals_tonnes", "sum"))
        .sort_values("date")
    )
    return df


def main() -> None:
    df = fetch()
    df.to_csv(OUT_CSV, index=False)
    print(f"mandi: {len(df)} rows, {df['date'].min():%Y-%m-%d}"
          f"..{df['date'].max():%Y-%m-%d} -> {OUT_CSV}")


if __name__ == "__main__":
    main()
