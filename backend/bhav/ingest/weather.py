"""Daily weather history for the Nashik onion belt, from the Open-Meteo free
archive API (no key). Produces data/raw/weather_nashik.csv.

Beyond temperature and rain, this pulls **humidity** and evaporative demand,
because for onion the weather that matters is not just "did it rain" but:

    can the crop be lifted and cured?   dry days, ET0, rain hours
    can it be stored, or is it forced?  humidity + warmth -> rot

A farmer who cannot store is a forced seller, and forced sellers are what turn a
harvest into a glut. That is the mechanism the overlay is trying to see.
"""

from __future__ import annotations

import pandas as pd
import requests

from ..config import DISTRICT, HISTORY_START, LAT, LON, RAW_DIR

OUT_CSV = RAW_DIR / "weather_nashik.csv"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Open-Meteo daily variable -> our column name.
DAILY_VARS = {
    "temperature_2m_max": "temp_max",
    "temperature_2m_min": "temp_min",
    "temperature_2m_mean": "temp_mean",
    "precipitation_sum": "rainfall",
    "precipitation_hours": "rain_hours",
    "relative_humidity_2m_max": "humidity_max",
    "relative_humidity_2m_min": "humidity_min",
    "relative_humidity_2m_mean": "humidity_mean",
    "et0_fao_evapotranspiration": "et0",
    "wind_speed_10m_max": "wind_max",
}

COLUMNS = ["district", "date", *DAILY_VARS.values()]


def fetch(start: str = HISTORY_START, end: str | None = None) -> pd.DataFrame:
    # The archive lags real time by ~2 days.
    end = end or (pd.Timestamp.utcnow() - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": start,
        "end_date": end,
        "daily": ",".join(DAILY_VARS),
        "timezone": "Asia/Kolkata",
    }
    r = requests.get(ARCHIVE_URL, params=params, timeout=120)
    r.raise_for_status()
    daily = r.json()["daily"]

    df = pd.DataFrame({"date": pd.to_datetime(daily["time"])})
    for api_name, col in DAILY_VARS.items():
        df[col] = daily.get(api_name)
    df.insert(0, "district", DISTRICT)

    # Open-Meteo returns nulls for the odd missing day; interpolate rather than
    # letting a NaN propagate through every rolling window downstream.
    for col in DAILY_VARS.values():
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["rainfall"] = df["rainfall"].fillna(0.0)
    df["rain_hours"] = df["rain_hours"].fillna(0.0)
    others = [c for c in DAILY_VARS.values() if c not in ("rainfall", "rain_hours")]
    df[others] = df[others].interpolate("linear", limit_direction="both")
    return df[COLUMNS]


def main() -> None:
    df = fetch()
    df.to_csv(OUT_CSV, index=False)
    span = f"{df['date'].min():%Y-%m-%d} .. {df['date'].max():%Y-%m-%d}"
    print(f"weather: {len(df)} days ({span}) -> {OUT_CSV}")


if __name__ == "__main__":
    main()
