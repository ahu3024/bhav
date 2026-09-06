"""Sentinel-2 NDVI history for the Nashik onion belt, via Google Earth Engine.

Run once (needs GEE auth) to produce data/raw/ndvi_nashik.csv, then the rest of
the pipeline only ever reads that CSV / the sqlite table. Live path re-runs this
incrementally for recent dates.

Auth (one time on the machine that runs this):
    earthengine authenticate
or set EE_PROJECT + a service-account key (GOOGLE_APPLICATION_CREDENTIALS).
"""

from __future__ import annotations

import os

import pandas as pd

from ..config import DISTRICT, HISTORY_START, NDVI_AOI, RAW_DIR

OUT_CSV = RAW_DIR / "ndvi_nashik.csv"
_CLOUD_PROP = "CLOUDY_PIXEL_PERCENTAGE"


def _init_ee():
    import ee

    project = os.getenv("EE_PROJECT")
    try:
        ee.Initialize(project=project) if project else ee.Initialize()
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=project) if project else ee.Initialize()
    return ee


def fetch(start: str = HISTORY_START, end: str | None = None) -> pd.DataFrame:
    """Return a tidy frame: district, date, value (mean NDVI over the AOI)."""
    ee = _init_ee()
    end = end or pd.Timestamp.utcnow().strftime("%Y-%m-%d")

    aoi = ee.Geometry.Rectangle(
        [NDVI_AOI["min_lon"], NDVI_AOI["min_lat"],
         NDVI_AOI["max_lon"], NDVI_AOI["max_lat"]]
    )

    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.lt(_CLOUD_PROP, 40))
    )

    def add_ndvi(img):
        ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
        stat = ndvi.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=aoi, scale=20, maxPixels=1e9
        )
        return ee.Feature(None, {
            "date": img.date().format("YYYY-MM-dd"),
            "value": stat.get("NDVI"),
        })

    feats = col.map(add_ndvi).filter(ee.Filter.notNull(["value"]))
    rows = feats.reduceColumns(
        ee.Reducer.toList(2), ["date", "value"]
    ).get("list").getInfo()

    df = pd.DataFrame(rows, columns=["date", "value"])
    df["date"] = pd.to_datetime(df["date"])
    # Multiple tiles per day -> average, then daily-resample + interpolate so
    # downstream joins on a continuous date index.
    df = df.groupby("date", as_index=False)["value"].mean()
    df = (
        df.set_index("date")
        .resample("D")
        .mean()
        .interpolate("time")
        .rolling(7, min_periods=1, center=True)
        .mean()
        .reset_index()
    )
    df.insert(0, "district", DISTRICT)
    return df


def main() -> None:
    df = fetch()
    df.to_csv(OUT_CSV, index=False)
    print(f"NDVI: {len(df)} rows -> {OUT_CSV}")


if __name__ == "__main__":
    main()
