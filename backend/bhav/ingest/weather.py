"""Daily weather history for the Nashik onion belt, from the Open-Meteo free
archive API (no key). Produces data/raw/weather_nashik.csv."""

from __future__ import annotations

import pandas as pd
import requests

from ..config import DISTRICT, HISTORY_START, LAT, LON, RAW_DIR

OUT_CSV = RAW_DIR / "weather_nashik.csv"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch(start: str = HISTORY_START, end: str | None = None) -> pd.DataFrame:
    end = end or (pd.Timestamp.utcnow() - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": start,
        "end_date": end,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "Asia/Kolkata",
    }
    r = requests.get(ARCHIVE_URL, params=params, timeout=60)
    r.raise_for_status()
    d = r.json()["daily"]
    df = pd.DataFrame({
        "district": DISTRICT,
        "date": pd.to_datetime(d["time"]),
        "rainfall": d["precipitation_sum"],
        "temp_max": d["temperature_2m_max"],
        "temp_min": d["temperature_2m_min"],
    })
    return df


def main() -> None:
    df = fetch()
    df.to_csv(OUT_CSV, index=False)
    print(f"weather: {len(df)} rows -> {OUT_CSV}")


if __name__ == "__main__":
    main()
