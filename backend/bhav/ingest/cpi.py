"""India CPI, for deflating mandi prices (roadmap §H2–H12: "CPI deflation").

A ₹1,400/qtl modal price in 2016 and the same ₹1,400 in 2026 are not the same
price, and the model compares today against a rolling year and against matching
weeks years back. Left nominal, a decade of inflation looks like a decade of
slow bull market and every "price is high for the season" feature drifts.

Source: World Bank `FP.CPI.TOTL` for IND (annual, 2010 = 100). Free, no key.
"""

from __future__ import annotations

import pandas as pd
import requests

from ..config import RAW_DIR

OUT_CSV = RAW_DIR / "cpi_india.csv"
WB_URL = "https://api.worldbank.org/v2/country/IND/indicator/FP.CPI.TOTL"


def fetch(start_year: int = 2014, end_year: int | None = None) -> pd.DataFrame:
    end_year = end_year or pd.Timestamp.utcnow().year
    r = requests.get(
        WB_URL,
        params={"format": "json", "per_page": 200,
                "date": f"{start_year}:{end_year}"},
        timeout=90,
    )
    r.raise_for_status()
    payload = r.json()
    rows = payload[1] if len(payload) > 1 and payload[1] else []

    df = pd.DataFrame(
        [{"year": int(x["date"]), "cpi": x["value"]} for x in rows if x["value"]]
    )
    if df.empty:
        raise RuntimeError("World Bank returned no CPI observations for India")
    df = df.sort_values("year").reset_index(drop=True)

    # The current (and sometimes previous) year isn't published yet. Carry the
    # series forward at its own recent average rate rather than leaving a hole —
    # flagged so nobody mistakes the tail for a real observation.
    df["estimated"] = False
    recent = df["cpi"].pct_change().tail(3).mean()
    while df["year"].iloc[-1] < end_year:
        nxt = df["year"].iloc[-1] + 1
        df.loc[len(df)] = {"year": nxt,
                           "cpi": df["cpi"].iloc[-1] * (1 + recent),
                           "estimated": True}
    return df


def main() -> None:
    df = fetch()
    df.to_csv(OUT_CSV, index=False)
    est = int(df["estimated"].sum())
    print(f"cpi: {len(df)} years ({df['year'].min()}..{df['year'].max()}, "
          f"{est} extrapolated) -> {OUT_CSV}")


if __name__ == "__main__":
    main()
